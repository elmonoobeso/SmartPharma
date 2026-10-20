import streamlit as st
import pandas as pd
from config.settings import APP_NAME, COL_CN, COL_LAB, COL_NOMBRE, COL_PVL, COL_STOCK, HEALTH_SCORE_MESES_DEFAULT
from core.business import calcular_benchmark_hs, calcular_coste_oportunidad, calcular_health_score, calcular_roi_laboratorios, calcular_rotacion_stock, calcular_roturas, calcular_sobrestock, calcular_stock_uvi, calcular_stock_zombie, cargar_productos_protegidos, generar_pedido_cobertura, obtener_historico_kpi, obtener_ventas_media, registrar_snapshot_kpi
from data.io import cargar_json_farmacia
from ml.engine import obtener_modelo_cacheado
from ui.charts import grafico_calendario_reposicion, grafico_dinero_en_riesgo_donut, grafico_gauge_health, grafico_historico_kpi, grafico_importancia_features, grafico_roi_laboratorios, grafico_waterfall_ahorro
from ui.components import render_kpi
from utils.helpers import format_eur
from utils.pdf_generator import generar_informe_pdf


def modulo_business_intelligence():
    if "inventario" not in st.session_state or "historico" not in st.session_state:
        st.warning("\u26a0\ufe0f Carga datos en Configuracion."); return
    df_inv = st.session_state["inventario"]
    df_hist = st.session_state["historico"]

    st.markdown("### \U0001f4ca Business Intelligence")

    # --- HS fijo a 2 meses ---
    meses_hs = HEALTH_SCORE_MESES_DEFAULT
    df_vm = obtener_ventas_media(meses_cobertura=max(1, int(meses_hs)))

    hs = calcular_health_score(df_inv, df_vm, meses_hs)
    df_z = calcular_stock_zombie(df_inv, df_hist)
    dz = df_z["Valor_Inmovilizado"].sum() if "Valor_Inmovilizado" in df_z.columns else 0
    df_rot = calcular_roturas(df_inv, df_vm)
    nr = len(df_rot)
    df_of = st.session_state.get("ofertas_normalizadas"); prot = cargar_productos_protegidos()
    df_prev = generar_pedido_cobertura(df_inv, df_vm, meses_hs, df_of, productos_protegidos=prot)
    ahorro = df_prev["Ahorro"].sum() if not df_prev.empty else 0
    coste = df_prev["Coste_Con_Dto"].sum() if not df_prev.empty else 0
    tend = df_vm["Factor_Tendencia"].mean()*100 if "Factor_Tendencia" in df_vm.columns else 0
    # Nuevos calculos
    df_rotacion = calcular_rotacion_stock(df_inv, df_vm)
    rotacion_media = df_rotacion["Rotacion"].mean() if not df_rotacion.empty else 0
    coste_op, df_coste_op = calcular_coste_oportunidad(df_inv, df_vm)
    df_uvi = calcular_stock_uvi(df_inv, df_hist)
    duvi = df_uvi["Valor_Inmovilizado"].sum() if not df_uvi.empty and "Valor_Inmovilizado" in df_uvi.columns else 0
    benchmark = calcular_benchmark_hs(hs)

    # === 1. KPIs principales ===
    st.markdown("---")
    k1,k2,k3,k4,k5,k6 = st.columns(6)
    with k1: render_kpi("Health Score", f"{hs}%")
    with k2: render_kpi("Zombie", format_eur(dz), f"{len(df_z)} prods", False)
    with k3: render_kpi("UVI", format_eur(duvi), f"{len(df_uvi)} prods", False)
    with k4: render_kpi("Roturas", str(nr), f"{format_eur(coste_op)}/mes", False)
    with k5: render_kpi("Rotacion", f"{rotacion_media:.2f}", "Media (>1=buen giro)")
    with k6: render_kpi("Tend. Ventas", f"{tend:+.1f}%", "ult. 12m vs 12m previos")
    st.markdown("<br>", unsafe_allow_html=True)

    if st.button("\U0001f4f8 Guardar Snapshot KPIs"):
        registrar_snapshot_kpi(hs, len(df_z), dz, nr, ahorro, coste)
        st.success("\u2705 Guardado.")

    # === 2. Gauge HS + Benchmark + Evolucion proyectada ===
    cg, ce = st.columns([1, 2])
    with cg:
        st.plotly_chart(grafico_gauge_health(hs), width='stretch', config={"displayModeBar":False})
        if benchmark.get("media_red") is not None:
            diff = hs - benchmark["media_red"]
            color = "green" if diff >= 0 else "red"
            st.markdown(f"""
            <div style="background:#F8F9FC;border-radius:10px;padding:10px;text-align:center;margin-top:-10px;">
                <span style="font-size:0.8rem;color:#64748B;">BENCHMARK RED ({benchmark['n_farmacias']} farmacias)</span><br>
                <span style="font-size:1.3rem;font-weight:700;">Media: {benchmark['media_red']}%</span>
                <span style="color:{color};font-weight:700;font-size:1.1rem;"> ({diff:+.1f}%)</span>
            </div>""", unsafe_allow_html=True)
        else:
            st.caption("Ref: 2 meses | Benchmark: solo disponible con red activa")
    with ce:
        fig_cal = grafico_calendario_reposicion(df_inv, df_vm)
        if fig_cal:
            st.plotly_chart(fig_cal, width='stretch', config={"displayModeBar":False})
        else:
            st.info("Sin datos de ventas para calcular calendario de reposicion.")

    # === 3. Dinero en Riesgo + Productos con peor rotacion ===
    st.markdown("---"); st.markdown("#### \U0001f4b0 Dinero en Riesgo")
    c_dr, c_top = st.columns([3, 2])
    with c_dr:
        val_sob, _ = calcular_sobrestock(df_inv, df_vm, excluir_cns=df_z[COL_CN] if not df_z.empty else ())
        fig_dr = grafico_dinero_en_riesgo_donut(dz, val_sob, coste_op)
        if fig_dr:
            st.plotly_chart(fig_dr, width='stretch', config={"displayModeBar":False})
        else:
            st.success("\u2705 Sin dinero en riesgo")
    with c_top:
        # Top productos con peor ratio rotacion (calculados con datos actuales)
        st.markdown("**\U0001f4c9 Productos con peor rotacion**")
        st.caption("Stock alto relativo a sus ventas")
        if not df_rotacion.empty:
            df_peor = df_rotacion[df_rotacion["Rotacion"] < 0.3].head(10)
            if not df_peor.empty:
                cols_show = [c for c in [COL_NOMBRE, COL_STOCK, "Venta_Media_Mensual", "Rotacion"] if c in df_peor.columns]
                st.dataframe(df_peor[cols_show], hide_index=True, width='stretch')
            else:
                st.success("\u2705 Todos los productos con buena rotacion")
        else:
            st.info("Carga datos para ver rotacion.")

    # === 4. Waterfall de Ahorro ===
    pedidos_hist = cargar_json_farmacia("historico_pedidos.json", default=[])
    if pedidos_hist:
        st.markdown("---"); st.markdown("#### \U0001f4b6 Ahorro Generado por Pedido")
        fig_wf = grafico_waterfall_ahorro(pedidos_hist)
        if fig_wf:
            st.plotly_chart(fig_wf, width='stretch', config={"displayModeBar":False})
        ahorro_total = sum(p.get("ahorro_ofertas", 0) for p in pedidos_hist)
        coste_total = sum(p.get("coste_total", 0) for p in pedidos_hist)
        c1, c2, c3 = st.columns(3)
        with c1: render_kpi("Ahorro Ofertas", format_eur(ahorro_total), "Dctos aplicados")
        with c2: render_kpi("Inversion Total", format_eur(coste_total))
        with c3: render_kpi("Pedidos", str(len(pedidos_hist)))

    # === 5. Evolucion HS (mantener) ===
    st.markdown("---"); st.markdown("#### \U0001f4c8 Evolucion Historica")
    df_hk = obtener_historico_kpi()
    if not df_hk.empty and len(df_hk) >= 2:
        fh, fzr = grafico_historico_kpi(df_hk)
        c1, c2 = st.columns(2)
        with c1:
            if fh: st.plotly_chart(fh, width='stretch', config={"displayModeBar":False})
        with c2:
            if fzr: st.plotly_chart(fzr, width='stretch', config={"displayModeBar":False})
        mejora = df_hk.iloc[-1]["health_score"] - df_hk.iloc[0]["health_score"]
        mejora_z = df_hk.iloc[0].get("n_zombies", 0) - df_hk.iloc[-1].get("n_zombies", 0)
        c1,c2,c3 = st.columns(3)
        with c1: render_kpi("Mejora Score", f"{mejora:+.1f}%", delta_positive=mejora>0)
        with c2: render_kpi("Zombies Eliminados", str(int(mejora_z)), delta_positive=mejora_z>0)
        with c3: render_kpi("Sesiones", str(len(df_hk)))
    else:
        st.info("Guarda al menos 2 snapshots para ver evolucion.")

    # === 6. ROI por Laboratorio ===
    st.markdown("---"); st.markdown("#### \U0001f4ca ROI por Laboratorio")
    df_roi = calcular_roi_laboratorios(df_inv, df_vm)
    if not df_roi.empty:
        fig_roi = grafico_roi_laboratorios(df_roi)
        if fig_roi:
            st.plotly_chart(fig_roi, width='stretch', config={"displayModeBar":False})
        with st.expander("Ver tabla completa de ROI"):
            df_roi_show = df_roi.copy()
            df_roi_show["Stock_EUR"] = df_roi_show["Stock_EUR"].apply(lambda x: f"{x:,.2f} \u20ac")
            df_roi_show["Venta_Anual_EUR"] = df_roi_show["Venta_Anual_EUR"].apply(lambda x: f"{x:,.2f} \u20ac")
            df_roi_show["ROI"] = df_roi_show["ROI"].apply(lambda x: f"{x:.2f}x")
            st.dataframe(df_roi_show, width='stretch', hide_index=True)

    # === 7. Rotacion de Stock + Coste de Oportunidad ===
    st.markdown("---"); st.markdown("#### \U0001f504 Rotacion de Stock")
    st.caption("Rotacion = Venta Mensual / Stock. Solo productos CON stock (stock=0 = rotura, se muestra en Roturas).")
    c_rot, c_co = st.columns(2)
    with c_rot:
        if not df_rotacion.empty:
            # Semaforo
            df_rot_show = df_rotacion.copy()
            def _semaforo_rot(r):
                if r >= 1.0: return "\U0001f7e2 Buena"
                if r >= 0.3: return "\U0001f7e1 Ajustar"
                return "\U0001f534 Sobrestock"
            df_rot_show["Estado"] = df_rot_show["Rotacion"].apply(_semaforo_rot)
            # Meses_Stock: reemplazar NaN por "Sin ventas"
            df_rot_show["Meses_Stock"] = df_rot_show["Meses_Stock"].apply(
                lambda x: f"{x:.1f}" if pd.notna(x) else "Sin ventas")
            n_sobre = len(df_rot_show[df_rot_show["Rotacion"] < 0.3])
            st.caption(f"Rotacion media: **{rotacion_media:.2f}** | \U0001f534 Sobrestock (<0.3): **{n_sobre}** prods")
            with st.expander("Ver ranking completo"):
                cols_show = [c for c in [COL_CN, COL_NOMBRE, COL_LAB, COL_STOCK, "Venta_Media_Mensual",
                             "Rotacion", "Meses_Stock", "Estado"] if c in df_rot_show.columns]
                st.dataframe(df_rot_show[cols_show].head(30), width='stretch', hide_index=True)
        else:
            st.info("Sin datos de rotacion.")
    with c_co:
        st.markdown("**\U0001f4c9 Coste de Oportunidad de Roturas**")
        if coste_op > 0:
            st.metric("Venta perdida estimada", f"{coste_op:,.2f} \u20ac/mes")
            if not df_coste_op.empty:
                with st.expander(f"Ver {len(df_coste_op)} productos en rotura"):
                    st.dataframe(df_coste_op.head(20), width='stretch', hide_index=True)
        else:
            st.success("\u2705 Sin roturas — no hay venta perdida")

    # === 8. Zombie + UVI ===
    st.markdown("---"); st.markdown("#### \U0001f9df Stock Inmovilizado")
    c_z, c_u = st.columns(2)
    with c_z:
        st.markdown(f"**Zombie (12m sin ventas)** — {len(df_z)} prods | {format_eur(dz)}")
        if not df_z.empty:
            cs = [c for c in [COL_CN,COL_NOMBRE,COL_LAB,COL_STOCK,COL_PVL,"Valor_Inmovilizado"] if c in df_z.columns]
            st.dataframe(df_z[cs].sort_values("Valor_Inmovilizado",ascending=False).head(20), width='stretch', hide_index=True)
        else:
            st.success("\u2705 Sin stock zombie")
    with c_u:
        st.markdown(f"**UVI (6m sin ventas)** — {len(df_uvi)} prods | {format_eur(duvi)}")
        if not df_uvi.empty:
            cs = [c for c in [COL_CN,COL_NOMBRE,COL_LAB,COL_STOCK,COL_PVL,"Valor_Inmovilizado"] if c in df_uvi.columns]
            st.dataframe(df_uvi[cs].sort_values("Valor_Inmovilizado",ascending=False).head(20), width='stretch', hide_index=True)
        else:
            st.success("\u2705 Sin stock UVI")

    # === 9. Modelo ML (mantener) ===
    model, met, _ = obtener_modelo_cacheado()
    if model and met:
        st.markdown("---"); st.markdown("#### \U0001f9e0 Rendimiento del Modelo ML")
        c1,c2,c3 = st.columns(3)
        with c1: render_kpi("RMSE", str(met.get("rmse","?")))
        with c2: render_kpi("R\u00b2 Score", str(met.get("r2","?")))
        with c3: render_kpi("Features", str(len(met.get("features",[]))))
        fig_imp = grafico_importancia_features(met)
        if fig_imp: st.plotly_chart(fig_imp, width='stretch', config={"displayModeBar":False})

    # === 10. Descargar Informe ===
    st.markdown("---")
    farmacia_nombre = st.session_state.get("farmacia_activa", "Farmacia").replace("_", " ").title()
    ahorro_acum_total = df_hk["ahorro_pedido"].sum() if not df_hk.empty else 0
    informe_bytes = generar_informe_pdf(
        farmacia_nombre, hs, len(df_z), dz, len(df_uvi), duvi,
        nr, coste_op, ahorro_acum_total, rotacion_media, benchmark)
    
    informe_filename = f"informe_{APP_NAME.lower()}.pdf"
    
    # GUARDA FISICAMENTE COMO BACKUP 100% SEGURO
    with open(informe_filename, "wb") as f:
        f.write(informe_bytes)
        
    st.success(f"✅ Informe guardado físicamente en la carpeta como **{informe_filename}**.")
    st.info("💡 Si el botón de abajo te descarga un archivo sin extensión, simplemente renómbralo a '.pdf' o abre directamente el archivo guardado en tu carpeta.")
    
    # INTENTO DE DESCARGA NATIVA
    with open(informe_filename, "rb") as f:
        pdf_data = f.read()
        
    st.download_button(
        label="📄 Intentar Descargar Informe (PDF)",
        data=pdf_data, 
        file_name=informe_filename,
        mime="application/pdf", 
        width="stretch"
    )
