import streamlit as st
import pandas as pd
from datetime import date, datetime, timedelta
from config.settings import APP_NAME, COLORS, COL_CN, COL_LAB, COL_NOMBRE, COL_STOCK
from core.business import calcular_health_score, calcular_roturas, calcular_stock_zombie, cargar_calendario_farmacia, cargar_perfil_farmacia, cargar_productos_protegidos, cargar_reglas_surtido, generar_panel_surtido, generar_pedido_cobertura, generar_pedido_presupuesto, imputar_stockouts, obtener_ventas_media, registrar_promociones_pedido, registrar_snapshot_kpi, validar_surtido_pedido
from core.network import MARGEN_SEGURIDAD_DIAS, registrar_pedido_confirmado
from ml.engine import MESES_DESFASE_AVISO, ML_AVAILABLE, construir_features_futuras, generar_pedido_ensemble, generar_pedido_ml, obtener_modelo_cacheado
from ui.charts import exportar_pedido_excel
from ui.components import render_kpi
from utils.helpers import format_eur, safe_div


def modulo_generador_pedidos():
    if "inventario" not in st.session_state or "historico" not in st.session_state:
        st.warning("\u26a0\ufe0f Carga datos en Configuracion."); return

    df_inv = st.session_state["inventario"]
    df_ofertas = st.session_state.get("ofertas_normalizadas")
    protegidos = cargar_productos_protegidos()

    st.markdown("### \U0001f680 Generador de Pedidos Transfer")

    # --- 1. Laboratorio ---
    st.markdown("#### 1. Laboratorio")
    labs = ["-- Todos --"]
    if COL_LAB in df_inv.columns:
        labs += sorted(df_inv[COL_LAB].dropna().unique().tolist())
    lab_sel = st.selectbox("Laboratorio:", labs, key="lab_transfer")

    # --- 2. Parametros (meses cobertura AQUI) ---
    st.markdown("#### 2. Parametros")
    cp1, cp2, cp3 = st.columns(3)
    with cp1:
        modo = st.radio("Modo:", ["\U0001f4c5 Cobertura", "\U0001f4b0 Presupuesto"], horizontal=True, key="modo_ped")
    with cp2:
        meses = st.slider("Meses cobertura:", 1, 6, 2, key="meses_cob")
        presupuesto = 0
        if "Presupuesto" in modo:
            presupuesto = st.number_input("Presupuesto (\u20ac):", 100, 100000, 2000, step=100, key="ppto")
    with cp3:
        pedido_min = st.number_input("Pedido minimo (\u20ac):", 0, 10000, 100, step=25, key="ped_min")

    # --- 3. Motor de prediccion ---
    st.markdown("#### 3. Motor de Prediccion")
    model, met, rmse_cn = obtener_modelo_cacheado()
    opciones_motor = ["\U0001f4d0 Heuristico (Mirroring + Tendencia)"]
    if model and ML_AVAILABLE:
        r2_txt = met.get("r2", "?") if met else "?"
        opciones_motor.append(f"\U0001f9e0 ML Optimizado (R\u00b2={r2_txt})")
        opciones_motor.append(f"\U0001f500 Ensemble ML+Heuristico (R\u00b2={r2_txt})")
    motor = st.radio("Motor:", opciones_motor, horizontal=True, key="motor_pred")
    usar_ensemble = "Ensemble" in motor and model is not None
    usar_ml = not usar_ensemble and "ML" in motor and model is not None

    nivel_servicio = 95
    if usar_ml or usar_ensemble:
        nivel_servicio = st.radio("Nivel de Servicio:", [95, 99], horizontal=True, key="nivel_srv",
            format_func=lambda x: f"{x}% {'(Eficiencia)' if x == 95 else '(Seguridad)'}")

    params_actuales = {"lab_sel": lab_sel, "modo": modo, "meses": meses, "presupuesto": presupuesto,
                       "motor": motor, "nivel_servicio": nivel_servicio}

    # --- Generar ---
    st.markdown("---")
    if st.button("\u26a1 Generar Pedido", type="primary", width='stretch'):
        with st.spinner("Calculando..."):
            df_f = df_inv.copy()
            if lab_sel != "-- Todos --" and COL_LAB in df_f.columns:
                df_f = df_f[df_f[COL_LAB] == lab_sel]

            if usar_ml or usar_ensemble:
                perfil_f = cargar_perfil_farmacia()
                cal_f = cargar_calendario_farmacia()
                df_hist_imp = imputar_stockouts(st.session_state["historico"], df_inv)
                ppto_ml = presupuesto if "Presupuesto" in modo else None
                # Features de los meses que cubre el pedido (no del ultimo mes del historico).
                df_futuro, meses_sin_datos = construir_features_futuras(
                    model, df_hist_imp, df_inv, perfil_f, cal_f, df_ofertas, meses)
                if meses_sin_datos > MESES_DESFASE_AVISO:
                    st.warning(f"\u26a0\ufe0f El historico acaba {meses_sin_datos} meses antes del periodo del pedido. "
                               "Esos meses se han estimado con el propio modelo: actualiza el historico para una prediccion fiable.")
                if lab_sel != "-- Todos --":
                    cns_lab = set(df_f[COL_CN])
                    df_futuro = df_futuro[df_futuro[COL_CN].isin(cns_lab)]

                if usar_ensemble:
                    df_vm_heur = obtener_ventas_media(meses_cobertura=meses)
                    ped = generar_pedido_ensemble(df_f, model, df_futuro, rmse_cn,
                                                  df_vm_heur, meses, nivel_servicio,
                                                  df_ofertas, protegidos, presupuesto=ppto_ml)
                    st.session_state["motor_usado"] = "Ensemble" + (" (presupuesto)" if ppto_ml else "")
                else:
                    ped = generar_pedido_ml(df_f, model, df_futuro, rmse_cn, meses,
                                            nivel_servicio, df_ofertas, protegidos, presupuesto=ppto_ml)
                    st.session_state["motor_usado"] = "ML" + (" (presupuesto)" if ppto_ml else "")
            else:
                df_vm = obtener_ventas_media(meses_cobertura=meses)
                if "Cobertura" in modo:
                    ped = generar_pedido_cobertura(df_f, df_vm, meses, df_ofertas,
                                                   productos_protegidos=protegidos)
                else:
                    ped = generar_pedido_presupuesto(df_f, df_vm, presupuesto, meses,
                                                      df_ofertas, protegidos)
                st.session_state["motor_usado"] = "Heuristico"

            st.session_state["pedido_generado"] = ped
            st.session_state["pedido_params"] = params_actuales
            st.session_state.pop("pedido_confirmado", None)

    # --- Resultados ---
    df_ped = st.session_state.get("pedido_generado")
    motor_usado = st.session_state.get("motor_usado", "")
    if df_ped is not None and not df_ped.empty:
        params_ped = st.session_state.get("pedido_params", params_actuales)
        lab_p, modo_p, meses_p, presupuesto_p = (params_ped["lab_sel"], params_ped["modo"],
                                                 params_ped["meses"], params_ped["presupuesto"])
        cambiados = params_ped != params_actuales
        if cambiados:
            st.warning("\u26a0\ufe0f Has cambiado laboratorio, modo, meses, presupuesto o motor desde que se genero "
                       "este pedido. Se muestra el pedido generado; vuelve a generarlo para aplicar los cambios.")
        if motor_usado:
            st.info(f"Motor utilizado: **{motor_usado}**")

        tc = df_ped["Coste_Con_Dto"].sum()
        ta = df_ped["Ahorro"].sum()
        tu = df_ped["Cantidad_A_Pedir"].sum()

        k1, k2, k3, k4 = st.columns(4)
        with k1: render_kpi("Total Pedido", format_eur(tc))
        with k2: render_kpi("Ahorro", format_eur(ta), f"{safe_div(ta, tc+ta)*100:.1f}%", True)
        with k3: render_kpi("Lineas", str(len(df_ped)))
        with k4: render_kpi("Unidades", f"{int(tu):,}".replace(",", "."))

        if "Presupuesto" in modo_p and presupuesto_p > 0:
            pct = min(100, safe_div(tc, presupuesto_p) * 100)
            bar_col = COLORS["success"] if pct < 80 else (COLORS["warning"] if pct < 95 else COLORS["danger"])
            st.markdown(f"""
            <div style="margin:1rem 0;">
                <div style="display:flex;justify-content:space-between;margin-bottom:4px;">
                    <span style="font-size:0.85rem;font-weight:600;">Presupuesto</span>
                    <span style="font-size:0.85rem;font-weight:600;">{format_eur(tc)} / {format_eur(presupuesto_p)}</span>
                </div>
                <div class="budget-bar-container">
                    <div class="budget-bar-fill" style="width:{pct}%;background:{bar_col};">{pct:.0f}%</div>
                </div>
            </div>""", unsafe_allow_html=True)

        st.markdown("---")
        df_ped_display = df_ped.copy()
        if COL_LAB in df_ped_display.columns:
            lab_list = sorted(df_ped_display[COL_LAB].dropna().unique())
        else:
            df_ped_display[COL_LAB] = "General"; lab_list = ["General"]

        for lab in lab_list:
            dl = df_ped_display[df_ped_display[COL_LAB] == lab]
            pl = dl["Coste_Con_Dto"].sum()
            al = dl["Ahorro"].sum()
            ups = dl["Upselling"].any() if "Upselling" in dl.columns else False
            cumple = pl >= pedido_min
            status = "\u2705" if cumple else "\u274c"
            ups_txt = " | \U0001f7e2 Upselling" if ups else ""

            with st.expander(f"\U0001f3ed **{lab}** | {format_eur(pl)} | Ahorro: {format_eur(al)} | {status}{ups_txt}",
                             expanded=(len(lab_list) == 1)):
                cols_d = [c for c in [COL_CN, COL_NOMBRE, COL_STOCK, "Venta_Media_Mensual",
                    "Safety_Stock", "Cantidad_A_Pedir", "Precio_Unitario", "Descuento_Aplicado",
                    "Coste_Con_Dto", "Ahorro", "Tier_Aplicado", "Upselling"] if c in dl.columns]
                dd = dl[cols_d].copy()
                if "Descuento_Aplicado" in dd.columns:
                    dd["Descuento_Aplicado"] = (dd["Descuento_Aplicado"] * 100).round(1).astype(str) + "%"
                if "Venta_Media_Mensual" in dd.columns:
                    dd["Venta_Media_Mensual"] = dd["Venta_Media_Mensual"].round(1)
                if "Safety_Stock" in dd.columns:
                    dd["Safety_Stock"] = dd["Safety_Stock"].round(0).astype(int)
                if "Upselling" in dd.columns:
                    dd["Upselling"] = dd["Upselling"].map({True: "\U0001f7e2 Si", False: ""})
                st.dataframe(dd, width='stretch', hide_index=True)

        st.markdown("---")
        lab_txt = lab_p if lab_p != "-- Todos --" else "Todos"
        col_dl, col_confirm = st.columns(2)
        with col_dl:
            st.download_button(
                f"\U0001f4e5 Descargar Pedido {lab_txt} (.xlsx)",
                data=exportar_pedido_excel(df_ped),
                file_name=f"{APP_NAME}_{lab_txt}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary", width='stretch')
        with col_confirm:
            confirmado = st.session_state.get("pedido_confirmado")
            if confirmado:
                st.success(confirmado)
            # Una sola confirmacion por pedido generado: cada clic registraba otra vez el pedido,
            # las promociones y el snapshot KPI, duplicando ahorro e inversion.
            if st.button("\u2705 Confirmar Pedido", width='stretch', type="secondary",
                         disabled=bool(confirmado) or cambiados) and not confirmado and not cambiados:
                modo_conf = "presupuesto" if "Presupuesto" in modo_p else "cobertura"
                df_vm_conf = obtener_ventas_media(meses_cobertura=meses_p)
                registrar_promociones_pedido(df_ped)
                # Registrar por laboratorio real (no "Todos")
                if lab_p == "-- Todos --" and COL_LAB in df_ped.columns:
                    labs_ped = df_ped[COL_LAB].fillna("General")
                    regs = [registrar_pedido_confirmado(df_ped[labs_ped == lab_real], str(lab_real), modo_conf, meses_p, df_vm_conf)
                            for lab_real in labs_ped.unique()]
                    regs = [r for r in regs if r]
                    reg_count = len(regs)
                    total_coste = round(float(df_ped["Coste_Con_Dto"].sum()), 2)
                    total_ahorro = round(float(df_ped["Ahorro"].sum()), 2)
                    # Cobertura global = el laboratorio que antes se agota (stock actual + pedido).
                    reg_min = min(regs, key=lambda r: r["dias_cobertura_estimados"]) if regs else None
                    dias = reg_min["dias_cobertura_estimados"] if reg_min else (meses_p or 2) * 30
                    cuello = reg_min["producto_cuello_botella"] if reg_min else ""
                else:
                    lab_real = lab_p if lab_p != "-- Todos --" else "General"
                    reg = registrar_pedido_confirmado(df_ped, lab_real, modo_conf, meses_p, df_vm_conf)
                    reg_count = 1
                    total_coste = reg["coste_total"] if reg else 0
                    total_ahorro = reg["ahorro_ofertas"] if reg else 0
                    dias = reg["dias_cobertura_estimados"] if reg else (meses_p or 2) * 30
                    cuello = reg["producto_cuello_botella"] if reg else ""

                # Snapshot KPI automatico
                if "inventario" in st.session_state:
                    df_inv_c = st.session_state["inventario"]
                    hs = calcular_health_score(df_inv_c, df_vm_conf)
                    df_z = calcular_stock_zombie(df_inv_c, st.session_state.get("historico", pd.DataFrame()))
                    dz_val = df_z["Valor_Inmovilizado"].sum() if "Valor_Inmovilizado" in df_z.columns else 0
                    nr = len(calcular_roturas(df_inv_c, df_vm_conf))
                    registrar_snapshot_kpi(hs, len(df_z), dz_val, nr, total_ahorro, total_coste)

                prox = (date.today() + timedelta(days=max(0, dias - MARGEN_SEGURIDAD_DIAS))).strftime("%d/%m/%Y")
                st.session_state.pop("alertas_red_cache", None)  # Invalidar cache tras confirmar
                msg_conf = (f"\u2705 Pedido confirmado ({reg_count} lab{'s' if reg_count > 1 else ''}) | "
                            f"Cobertura: ~{dias} dias | Proximo pedido sugerido: {prox}")
                st.session_state["pedido_confirmado"] = msg_conf
                st.success(msg_conf)
                if cuello:
                    st.caption(f"Cuello de botella: {cuello}")
                if pedido_min > 0 and total_coste < pedido_min:
                    st.warning(f"\u26a0\ufe0f Pedido ({format_eur(total_coste)}) por debajo del minimo ({format_eur(pedido_min)})")
                # Validacion de surtido post-pedido
                reglas_s = cargar_reglas_surtido()
                if reglas_s and "inventario" in st.session_state:
                    alertas_s = validar_surtido_pedido(st.session_state["inventario"], df_ped, reglas_s)
                    for alerta in alertas_s:
                        st.warning(alerta["mensaje"])

    elif df_ped is not None and df_ped.empty:
        st.info("\u2139\ufe0f Stock suficiente \u2014 no se necesitan compras.")

    # --- Panel de Surtido ---
    st.markdown("---")
    st.markdown("#### 🧪 Panel de Surtido Avanzado")
    st.caption("Diversificacion de laboratorios. Configura reglas con Dosis/Cant. en Configuracion > Reglas de Surtido.")
    if "inventario" in st.session_state:
        reglas_panel = cargar_reglas_surtido()
        df_surtido = generar_panel_surtido(st.session_state["inventario"], reglas_panel)
        if not df_surtido.empty:
            
            # --- Filtros Activos UI ---
            col_fT, col_fL = st.columns(2)
            with col_fT:
                tipos_disp = ["Todos"] + sorted([t.strip() for ts in df_surtido["Tipo"].unique() for t in ts.split(",") if t.strip()])
                tipos_disp = list(dict.fromkeys(tipos_disp)) # Remove duplicates
                filtro_tipo = st.selectbox("🗂️ Tipo de Producto:", options=tipos_disp, index=0)
            
            with col_fL:
                all_labs = list(set([l.strip() for row in df_surtido["Labs"].dropna() for l in row.split(",") if l.strip()]))
                all_labs.sort()
                filtro_labs = st.multiselect("🏭 Filtrar por Laboratorio/s (opc):", options=all_labs)

            df_surt_filtered = df_surtido.copy()
            if filtro_tipo != "Todos":
                df_surt_filtered = df_surt_filtered[df_surt_filtered["Tipo"].str.contains(filtro_tipo, na=False, case=False)]
            if filtro_labs:
                mask = df_surt_filtered["Labs"].apply(lambda labs_str: any(lab in labs_str for lab in filtro_labs) if pd.notna(labs_str) else False)
                df_surt_filtered = df_surt_filtered[mask]
                
            n_moleculas = len(df_surt_filtered)
            n_mono = len(df_surt_filtered[df_surt_filtered["N_Labs"] == 1])
            col1, col2, col3 = st.columns(3)
            with col1: render_kpi("Productos Base (Filtro)", f"{n_moleculas:,}")
            with col2: render_kpi("Monolab", f"{n_mono:,}")
            with col3:
                if reglas_panel:
                    n_incumple = len(df_surt_filtered[df_surt_filtered["Cumple"] == "❌"])
                    render_kpi(f"{'⚠️' if n_incumple > 0 else '✅'} Alertas Surtido Min.", f"{n_incumple}")
                else: render_kpi("ℹ️ Reglas Activas", "0")

            with st.expander(f"Ver tabla de surtido ({n_moleculas} registros)"):
                st.dataframe(df_surt_filtered.rename(columns={"Presentacion/Molecula": "Regla / Molécula"}), width='stretch', hide_index=True)
        else:
            st.info("Carga inventario para ver el panel de surtido.")
    else:
        st.info("Carga inventario en Configuracion.")
