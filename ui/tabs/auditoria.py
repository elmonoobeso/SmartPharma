import streamlit as st
import pandas as pd
from config.settings import COL_CN, COL_LAB, COL_NOMBRE, COL_STOCK, HEALTH_SCORE_MESES_DEFAULT
from core.business import calcular_conciliacion_fisico_logico, calcular_coste_oportunidad, calcular_dependencia_estacional, calcular_flujo_caja_inventario, calcular_health_score, calcular_indice_servicio, calcular_matriz_rentabilidad_gmroi, calcular_riesgo_caducidad, calcular_sobrestock, calcular_stock_caducado, calcular_stock_uvi, calcular_stock_zombie, obtener_historico_auditorias, obtener_ventas_media
from ui.charts import grafico_concentracion_riesgo, grafico_dinero_en_riesgo_donut, grafico_distribucion_laboratorios, grafico_estacionalidad_liquidez, grafico_gauge_health, grafico_heatmap_cobertura, grafico_long_tail
from ui.components import render_kpi
from ui.tabs.analisis_ui import (inventario_con_pvp, pie_lista, precios_venta, render_abc, render_caducidades, render_plan_accion,
                                 render_roturas_recurrentes, render_sello_datos)
from utils.helpers import format_eur


def modulo_auditoria():
    if "inventario" not in st.session_state or "historico" not in st.session_state:
        st.warning("\u26a0\ufe0f Carga datos en Configuracion."); return

    df_inv = st.session_state["inventario"]
    df_hist = st.session_state["historico"]
    df_vm = obtener_ventas_media(meses_cobertura=int(HEALTH_SCORE_MESES_DEFAULT))

    st.markdown("### \U0001f6e0\ufe0f Auditoría Integral de Stock")
    
    render_sello_datos()

    # Pre-calculo de variables Core
    hs = calcular_health_score(df_inv, df_vm)
    df_z = calcular_stock_zombie(df_inv, df_hist)
    dz = df_z["Valor_Inmovilizado"].sum() if not df_z.empty and "Valor_Inmovilizado" in df_z.columns else 0
    df_u = calcular_stock_uvi(df_inv, df_hist)
    du = df_u["Valor_Inmovilizado"].sum() if not df_u.empty and "Valor_Inmovilizado" in df_u.columns else 0

    c_op, _ = calcular_coste_oportunidad(df_inv, df_vm, precios_venta())
    
    # Nuevas variables
    fill_rate, total_con_demanda, n_roturas_hab = calcular_indice_servicio(df_inv, df_hist)
    val_cad, prods_cad, cad_real = calcular_riesgo_caducidad(df_inv)
    
    
    # --- RESUMEN EJECUTIVO (Scorecard) ---
    st.markdown("#### \U0001f4cb Resumen Ejecutivo")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.plotly_chart(grafico_gauge_health(hs), width='stretch', config={"displayModeBar":False}, key="gauge_auditoria")
    with c2:
        render_kpi("Índice Servicio (Fill Rate)", f"{fill_rate:.1f}%", f"{n_roturas_hab} roturas / {total_con_demanda} actvs", fill_rate>90)
        st.markdown("<br>", unsafe_allow_html=True)
        if cad_real:
            val_ya, n_ya = calcular_stock_caducado(df_inv)
            render_kpi("Caducidades (<6m)", format_eur(val_cad),
                       f"{prods_cad} productos" + (f" · ya caducado: {format_eur(val_ya)} ({n_ya})" if n_ya else ""), False)
        else:
            render_kpi("Caducidades (<6m)", "Sin datos", "Anade Fecha_Caducidad al inventario")
    with c3:
        # Sobrestock sin el stock zombie, que ya tiene su porcion en el donut.
        val_sob, _ = calcular_sobrestock(df_inv, df_vm, excluir_cns=df_z[COL_CN] if not df_z.empty else ())
        
        fig_donut = grafico_dinero_en_riesgo_donut(dz, val_sob)
        if fig_donut:
            fig_donut.update_layout(height=180, margin=dict(t=0, b=0, l=0, r=0))
            st.plotly_chart(fig_donut, width='stretch', config={"displayModeBar":False}, key="donut_auditoria")
        st.caption(f"Aparte: roturas, {format_eur(c_op)}/mes de venta perdida (no se suma al capital parado).")
    with c4:
        # Comparativa temporal rapida
        hist_aud = obtener_historico_auditorias()
        if len(hist_aud) >= 2:
            prev = hist_aud[-2]; curr = hist_aud[-1]
            dz_kpi = curr["n_zombies"] - prev["n_zombies"]
            render_kpi("Comparativa Zombies", f"{curr['n_zombies']}", f"{dz_kpi:+d} vs anterior", dz_kpi <= 0)
        else:
            st.info("Guarda snapshots para ver la evolución vs auditoría previa.")
            
    st.markdown("---")
    
    # --- PESTAÑAS DE ANÁLISIS PROFUNDO ---
    ta0, ta1, ta2, ta3, ta4, ta5, ta6 = st.tabs([
        "✅ Plan de Acción",
        "📊 Distribución y Eficiencia",
        "⚠️ Riesgo Operacional",
        "💸 Flujo de Caja y Estacionalidad",
        "⚖️ Conciliación Físico-Lógico",
        "📅 Caducidades",
        "🔁 Roturas Recurrentes",
    ])

    with ta0:
        render_plan_accion()
    with ta5:
        render_caducidades()
    with ta6:
        render_roturas_recurrentes()

    with ta1:
        st.markdown("#### \U0001f4ca Distribución del Surtido e Inversión")
        c_l, c_r = st.columns([1.5, 1])
        with c_l:
            st.markdown("**Análisis de Pareto (Regla 80/20)**")
            fig_tail = grafico_long_tail(df_inv, df_vm)
            if fig_tail: st.plotly_chart(fig_tail, width='stretch', config={"displayModeBar":False}, key="tail_auditoria")
            
        with c_r:
            st.markdown("**Inversión por Laboratorio**")
            tipo_filtro = st.radio("Filtro:", ["Todos", "Medicamento", "Parafarmacia"], horizontal=True)
            fig_labs = grafico_distribucion_laboratorios(df_inv, tipo_filtro)
            if fig_labs: st.plotly_chart(fig_labs, width='stretch', config={"displayModeBar":False}, key="labs_auditoria")
            
        render_abc()

    with ta2:
        st.markdown("#### \u26a0\ufe0f Riesgo Operacional (Inmovilizado)")
        c_z, c_u = st.columns(2)
        with c_z:
            st.markdown(f"**\U0001f9df Stock Zombie (12m sin ventas)** — {format_eur(dz)}")
            if not df_z.empty:
                st.dataframe(df_z[[COL_NOMBRE, COL_LAB, COL_STOCK, "Valor_Inmovilizado"]].sort_values("Valor_Inmovilizado", ascending=False).head(15), width='stretch', hide_index=True)
                pie_lista(df_z.sort_values("Valor_Inmovilizado", ascending=False), 15, "Zombie", "aud_zombie")
            else: st.success("Sin zombies")
        with c_u:
            st.markdown(f"**\U0001fa79 Stock UVI (6m sin ventas)** — {format_eur(du)}")
            if not df_u.empty:
                st.dataframe(df_u[[COL_NOMBRE, COL_LAB, COL_STOCK, "Valor_Inmovilizado"]].sort_values("Valor_Inmovilizado", ascending=False).head(15), width='stretch', hide_index=True)
                pie_lista(df_u.sort_values("Valor_Inmovilizado", ascending=False), 15, "UVI", "aud_uvi")
            else: st.success("Sin UVI")
            
        st.markdown("---")
        c_hc, c_cr = st.columns([1.5, 1])
        with c_hc:
            fig_heat = grafico_heatmap_cobertura(df_inv, df_vm)
            if fig_heat: st.plotly_chart(fig_heat, width='stretch', config={"displayModeBar":False}, key="heat_auditoria")
        with c_cr:
            # Zombie y UVI ya tienen su barra: el sobrestock no repite ese stock.
            excluir = set(df_z[COL_CN]) if not df_z.empty else set()
            if not df_u.empty:
                excluir |= set(df_u[COL_CN])
            _, df_exceso = calcular_sobrestock(df_inv, df_vm, excluir_cns=excluir)
            fig_conc = grafico_concentracion_riesgo(df_z, df_u, df_exceso)
            if fig_conc: st.plotly_chart(fig_conc, width='stretch', config={"displayModeBar":False}, key="conc_auditoria")
            
    with ta3:
        st.markdown("#### \U0001f4b8 Flujo de Caja y Estacionalidad")
        c_fc, c_est = st.columns(2)
        
        with c_fc:
            st.markdown("**Ciclo de Conversión de Efectivo (CCC)**")
            st.caption("¿La farmacia se financia con proveedores o con su bolsillo?")
            
            dias_pago_manual = st.slider("Días promedio de pago a proveedores (Manual)", 0, 150, 60, 5)
            
            uploaded_facturas = st.file_uploader("Opcional: Sube CSV Facturas/Mayor Proveedores para cálculo exacto", type=["csv"], key="up_facts")
            df_facts = None
            if uploaded_facturas:
                df_facts = pd.read_csv(uploaded_facturas, encoding="utf-8")
                st.success("Facturas cargadas. Se usará media ponderada.")
                
            d_pago, d_inv, ccc, nec_fm, flotador = calcular_flujo_caja_inventario(df_inv, df_vm, dias_pago_manual, df_facts)
            
            if d_inv > 0:
                st.markdown(f"- **Días que el stock tarda en venderse:** {d_inv:.0f} días")
                st.markdown(f"- **Días promedio de pago:** {d_pago:.0f} días")
                if ccc > 0:
                    st.error(f"**Agujero Financiero:** El comprador necesita fondear {format_eur(nec_fm)} (Caja retenida {ccc:.0f} días)")
                else:
                    st.success(f"**Flotador Positivo:** Proveedores financian {format_eur(flotador)} al comprador (Caja adelantada {abs(ccc):.0f} días)")
            else:
                st.info("Sube datos con PVL para calcular.")
                
            st.markdown("---")
            st.markdown("**Matriz Rentabilidad (GMROI)**")
            df_gmroi, tiene_pvp = calcular_matriz_rentabilidad_gmroi(inventario_con_pvp(df_inv), df_vm)
            if tiene_pvp and not df_gmroi.empty:
                res = df_gmroi.groupby("Cuadrante")[COL_CN].count().reset_index()
                st.dataframe(res, width='stretch', hide_index=True)
            else:
                st.info("Se requiere columna PVP para calcular matriz real.")
                
        with c_est:
            st.markdown("**Dependencia Estacional (Riesgo de Liquidez)**")
            df_est = calcular_dependencia_estacional(df_hist)
            if not df_est.empty:
                fig_est = grafico_estacionalidad_liquidez(df_est)
                if fig_est: st.plotly_chart(fig_est, width='stretch', config={"displayModeBar":False}, key="est_auditoria")
                
                # Alerta si un trimestre acumula > 40% ventas
                max_3m = df_est["Pct_Ventas"].rolling(window=3, min_periods=1).sum().max()
                if max_3m > 40:
                    st.warning(f"\u26a0\ufe0f **Riesgo Estacional Alto:** El {max_3m:.1f}% de las ventas ocurre en solo 3 meses seguidos.")
                else:
                    st.success(f"\u2705 **Riesgo Estacional Bajo:** Ingresos estables (pico trimestral {max_3m:.1f}%).")
            else:
                st.info("Sin histórico suficiente para calcular estacionalidad.")
                
    with ta4:
        st.markdown("#### \u2696\ufe0f Conciliación Físico vs Lógico")
        st.caption("Cruza el stock teórico del ordenador con un archivo CSV exportado desde un lector de códigos de barras.")
        
        uploaded_fisico = st.file_uploader("Sube CSV Inventario Físico (Columnas: Codigo_Nacional, Cantidad)", type=["csv"], key="up_fisico")
        completo = st.checkbox("He contado toda la farmacia (lo que no aparezca en el archivo cuenta como faltante)", value=False, key="conc_completo")

        if uploaded_fisico:
            try:
                df_fisico = pd.read_csv(uploaded_fisico, sep=None, engine="python", encoding="utf-8")
                df_conc, alcance = calcular_conciliacion_fisico_logico(df_inv, df_fisico, conteo_completo=completo)

                if df_conc is not None:
                    # Alcance del conteo: sin esto, un conteo parcial parecia una perdida de casi todo el stock
                    pct = alcance["valor_contado"] / alcance["valor_inventario"] * 100 if alcance["valor_inventario"] > 0 else 0
                    texto = (f"Has contado **{alcance['contados']} de {alcance['en_inventario']}** productos del inventario "
                             f"({format_eur(alcance['valor_contado'])} de {format_eur(alcance['valor_inventario'])} de stock, el {pct:.0f} %).")
                    if alcance["fuera_de_inventario"]:
                        texto += f" Además, {alcance['fuera_de_inventario']} código(s) del conteo no están en el inventario."
                    if alcance["no_contados"] and completo:
                        st.warning(texto + f" Los **{alcance['no_contados']} no contados** ({format_eur(alcance['valor_no_contado'])}) "
                                           "se están tratando como faltantes porque has marcado que el conteo es de toda la farmacia.")
                    elif alcance["no_contados"]:
                        st.info(texto + f" Los {alcance['no_contados']} productos no contados no se evalúan.")
                    else:
                        st.success(texto)

                if df_conc is not None and not df_conc.empty:
                    faltantes_eur = abs(df_conc[df_conc["Descuadre_Uds"] < 0]["Descuadre_Eur"].sum())
                    sobrantes_eur = df_conc[df_conc["Descuadre_Uds"] > 0]["Descuadre_Eur"].sum()
                    
                    c_f1, c_f2 = st.columns(2)
                    with c_f1: render_kpi("Faltantes (Pérdida)", format_eur(faltantes_eur), delta_positive=False)
                    with c_f2: render_kpi("Sobrantes (No registrados)", format_eur(sobrantes_eur), delta_positive=True)
                    
                    st.markdown("**Lista de Descuadres:**")
                    df_muest = df_conc[df_conc["Descuadre_Uds"] != 0].copy()
                    df_muest["Stock_Teorico"] = df_muest[COL_STOCK]
                    if df_muest.empty:
                        st.success("✅ Todo lo contado coincide con el stock del ordenador.")
                    else:
                        st.dataframe(df_muest[[COL_NOMBRE, "Stock_Teorico", "Stock_Fisico", "Descuadre_Uds", "Descuadre_Eur"]].sort_values("Descuadre_Eur"), width='stretch', hide_index=True)
                elif df_conc is not None:
                    st.warning("El archivo del conteo no contiene ningún producto con código y cantidad.")
                else:
                    st.error("No se pudieron detectar las columnas correctas en el CSV subido.")
            except Exception as e:
                st.error(f"Error procesando CSV: {str(e)}")
        else:
            st.info("Sube un CSV de conteo físico para visualizar el descuadre y detectar roturas o robos invisibles al software.")
