"""Secciones de BI, Auditoria y Configuracion que se apoyan en core/analisis.py.

Todo el calculo se hace una vez por combinacion de datos y parametros (obtener_analisis)
y se reutiliza en cada rerun; las secciones solo pintan.
"""
from datetime import date

import numpy as np
import pandas as pd
import streamlit as st

from config.settings import BASE_DIR, COL_CN, COL_LAB, COL_NOMBRE, COL_PVL, COL_STOCK, HEALTH_SCORE_MESES_DEFAULT
from core import analisis as A
from core.business import (calcular_stock_uvi, calcular_stock_zombie, calcular_ventas_mensuales, cargar_productos_protegidos,
                           cns_alta_reciente, obtener_ventas_media)
from core.network import cargar_red_config
from data.historicos import (anadir_compras, cargar_compras, cargar_fotos_stock, cargar_parametros, guardar_parametros,
                             huella_inventario, marca_archivos, registrar_foto_stock, vaciar_compras)
from data.io import cargar_json_farmacia
from ui.charts_analisis import (grafico_abc, grafico_caducidades, grafico_capital_liberable, grafico_descuentos, grafico_margen_laboratorios,
                                grafico_ventas_interanual)
from utils.excel_export import libro_excel, titulo_columna
from utils.helpers import format_eur, normalizar_cn

_SIN_BARRA = {"displayModeBar": False}
_MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ---------------------------------------------------------------------------
# Calculo (cacheado en la sesion)
# ---------------------------------------------------------------------------
def _necesidades_red(params):
    """{cn: (farmacia, unidades que le faltan)} en las otras farmacias de la red; ({}, []) si no hay red."""
    activa = st.session_state.get("farmacia_activa")
    red = cargar_red_config().get("farmacias_activas", [])
    if not params.get("traspaso_red", True) or activa not in red:
        return {}, []
    necesidades, omitidas = {}, []
    for farm in red:
        if farm == activa:
            continue
        try:
            inv = pd.read_parquet(BASE_DIR / farm / "inventario.parquet")
            hist = pd.read_parquet(BASE_DIR / farm / "historico.parquet")
            inv[COL_CN], hist[COL_CN] = normalizar_cn(inv[COL_CN]), normalizar_cn(hist[COL_CN])
            vm = calcular_ventas_mensuales(hist, int(HEALTH_SCORE_MESES_DEFAULT))
        except Exception as e:  # otra farmacia sin datos o con datos ilegibles: se omite y se avisa
            omitidas.append(f"{farm} ({type(e).__name__})")
            continue
        m = inv.merge(vm[[COL_CN, "Venta_Media_Mensual"]], on=COL_CN, how="left")
        falta = (np.ceil(m["Venta_Media_Mensual"].fillna(0) * HEALTH_SCORE_MESES_DEFAULT) - pd.to_numeric(m[COL_STOCK], errors="coerce").fillna(0).clip(lower=0)).clip(lower=0)
        nombre = farm.replace("_", " ").title()
        for cn, uds in zip(m[COL_CN], falta):
            if uds >= 1 and uds > necesidades.get(cn, (None, 0))[1]:
                necesidades[cn] = (nombre, int(uds))
    return necesidades, omitidas


def obtener_analisis():
    """Todos los analisis de la farmacia activa, o None si faltan inventario o historico."""
    ss = st.session_state
    if "inventario" not in ss or "historico" not in ss:
        return None
    inv, hist_raw = ss["inventario"], ss["historico"]
    df_vm = obtener_ventas_media(meses_cobertura=int(HEALTH_SCORE_MESES_DEFAULT))
    ofertas = ss.get("ofertas_normalizadas")
    pvl_total = float(pd.to_numeric(inv[COL_PVL], errors="coerce").sum()) if COL_PVL in inv.columns else 0.0
    clave = (ss.get("farmacia_activa"), huella_inventario(inv), tuple(inv.columns), pvl_total, ss.get("historico_hash"), len(hist_raw),
             marca_archivos(), None if ofertas is None else hash(ofertas.astype(str).to_csv()), date.today().isoformat())
    cache = ss.get("_analisis_cache")
    if cache and cache["clave"] == clave:
        return cache["datos"]

    params = cargar_parametros()
    inv_n = inv.assign(**{COL_CN: normalizar_cn(inv[COL_CN])})
    hist = A.preparar_historico(hist_raw, params, dict(zip(inv_n[COL_CN], A._tipos(inv_n))))
    compras = A.unir_compras(cargar_compras(), A.compras_desde_pedidos(cargar_json_farmacia("historico_pedidos.json", default=[])))
    df_z, df_u = calcular_stock_zombie(inv, hist_raw), calcular_stock_uvi(inv, hist_raw)
    nuevos = cns_alta_reciente(inv_n, hist_raw)
    base = A.construir_base(inv, df_vm, hist, params, df_z[COL_CN], df_u[COL_CN] if COL_CN in df_u.columns else [],
                            cargar_productos_protegidos(), compras, nuevos)
    red, omitidas = _necesidades_red(params)
    plan = A.generar_plan_accion(base, params, red)
    cad_det, cad_res = A.calcular_caducidades(base)
    mensual, fuente = A.ventas_mensuales(hist, base)
    interanual, res_interanual = A.comparativa_interanual(mensual)
    por_lab_dto, perdidos = A.analizar_descuentos(compras, ofertas, base)
    fotos = cargar_fotos_stock()
    rot_rec, periodo_rot = A.roturas_recurrentes(hist, base, fotos, params)
    datos = {
        "clave": clave, "params": params, "base": base, "plan": plan, "capital": A.calcular_capital_liberable(base),
        "cad_det": cad_det, "cad_res": cad_res, "mensual": mensual, "fuente_ventas": fuente, "interanual": interanual,
        "res_interanual": res_interanual, "labs": A.resumen_laboratorios(base, compras, params), "compras": compras,
        "dto_lab": por_lab_dto, "dto_perdidos": perdidos, "rot_rec": rot_rec, "periodo_rot": periodo_rot,
        "n_fotos": int(fotos["Fecha"].nunique()) if not fotos.empty else 0,
        "calidad": A.calidad_datos(inv, hist, params, compras), "red_omitidas": omitidas, "hay_red": bool(red),
        "n_altas": int((base["Estado"] == "Alta reciente").sum()),
    }
    ss["_analisis_cache"] = {"clave": clave, "datos": datos}
    return datos


# ---------------------------------------------------------------------------
# Piezas comunes
# ---------------------------------------------------------------------------
def _kpi(etiqueta, valor, nota=""):
    nota_html = f'<div style="font-size:0.8rem;color:#64748B;margin-top:4px;">{nota}</div>' if nota else ""
    st.markdown(f'<div class="kpi-card"><div class="kpi-label">{etiqueta}</div><div class="kpi-value">{valor}</div>{nota_html}</div>',
                unsafe_allow_html=True)


def _tabla(df, columnas=None, n=None):
    """Tabla con cabeceras legibles y euros formateados. Si se recorta en pantalla, lo dice."""
    vista = df[[c for c in columnas if c in df.columns]] if columnas else df
    if "Ubicacion" in vista.columns and not (vista["Ubicacion"] != "").any():
        vista = vista.drop(columns=["Ubicacion"])
    total = len(vista)
    if n and total > n:
        vista = vista.head(n)
    cfg = {}
    for c in vista.columns:
        if pd.api.types.is_datetime64_any_dtype(vista[c]):
            cfg[c] = st.column_config.DateColumn(titulo_columna(c), format="DD/MM/YYYY")
        elif "EUR" in str(c) or c in (COL_PVL, "Coste_Unit"):
            cfg[c] = st.column_config.NumberColumn(titulo_columna(c), format="%.2f €")
        elif pd.api.types.is_float_dtype(vista[c]):
            cfg[c] = st.column_config.NumberColumn(titulo_columna(c), format="%.1f")
        else:
            cfg[c] = st.column_config.Column(titulo_columna(c))
    st.dataframe(vista, hide_index=True, width="stretch", column_config=cfg)
    if n and total > n:
        st.caption(f"Mostrando {n} de {total}. La lista completa está en el Excel.")


def _portada(an):
    q, p = an["calidad"], an["params"]
    f = lambda d: d.strftime("%d/%m/%Y") if d is not None and pd.notna(d) else "sin confirmar"  # noqa: E731
    return [("Farmacia", st.session_state.get("farmacia_activa", "").replace("_", " ").title()),
            ("Fecha del inventario", f(q["fecha_inventario"])),
            ("Ventas desde / hasta", f"{f(q.get('hist_desde'))} — {f(q.get('hist_hasta'))} ({q['meses_hist']} meses)"),
            ("Referencias en inventario", q["n_refs"]),
            ("Stock objetivo (meses)", f"medicamento {p['meses_objetivo_medicamento']:g} · parafarmacia {p['meses_objetivo_parafarmacia']:g} · "
                                       f"no caducables {p['meses_objetivo_no_caducable']:g}"),
            ("Valoración", f"a coste = PVL − {p['descuento_compra_pct']:g} % de descuento de compra"),
            ("Plazo de devolución", f"refrigerados {p['dias_devolucion_refrigerado']} días · resto {p['dias_devolucion_resto']} días"),
            ("Descuento de liquidación", f"{p['dto_liquidacion_pct']:g} %"),
            ("Avisos sobre los datos", " | ".join(q["avisos"]) or "ninguno")]


def _excel_diferido(an, constructor):
    """Funcion que genera el Excel al pulsar el boton de descarga, no en cada carga de la pantalla
    (con un surtido real tarda varios segundos). Se ejecuta en otro hilo: no puede usar Streamlit,
    por eso la portada se prepara aqui."""
    portada = _portada(an)
    return lambda: libro_excel(constructor(), portada=portada)


def _nombre_archivo(prefijo, an):
    farm = st.session_state.get("farmacia_activa", "farmacia")
    f = an["calidad"]["fecha_inventario"]
    return f"{prefijo}_{farm}_{(f or pd.Timestamp.now()).strftime('%Y-%m-%d')}.xlsx"


def render_sello_datos():
    """Linea con la fecha y el alcance de los datos, y los avisos si los hay."""
    an = obtener_analisis()
    if an is None:
        return
    q = an["calidad"]
    f = lambda d: d.strftime("%d/%m/%Y")  # noqa: E731
    partes = [f"📅 Inventario a **{f(q['fecha_inventario'])}**" if q["fecha_inventario"] is not None else "📅 Inventario **sin fecha confirmada**"]
    if q.get("hist_hasta") is not None:
        partes.append(f"ventas de {q['hist_desde']:%m/%Y} a **{q['hist_hasta']:%m/%Y}** ({q['meses_hist']} meses)")
    partes.append(f"{q['n_refs']} referencias")
    extras = [t for t, ok in (("PVP", q["tiene_pvp"]), ("caducidades", q["pct_caducidad"] is not None), ("ubicación", q["tiene_ubicacion"]),
                              ("compras", q["n_compras"] > 0)) if ok]
    partes.append("con " + ", ".join(extras) if extras else "sin PVP, caducidades ni compras")
    st.caption(" · ".join(partes))
    if q["avisos"]:
        with st.expander(f"⚠️ {len(q['avisos'])} aviso(s) sobre los datos", expanded=q["fecha_inventario"] is None):
            for a in q["avisos"]:
                st.markdown(f"- {a}")


def pie_lista(df_completo, mostradas, nombre, clave):
    """Bajo una tabla recortada en pantalla: dice cuantas filas se ven y ofrece la lista entera en Excel."""
    total = len(df_completo)
    if total > mostradas:
        st.caption(f"Mostrando {mostradas} de {total}. La lista completa, en el Excel:")
    hojas = {nombre: df_completo}
    farm = st.session_state.get("farmacia_activa", "farmacia")
    st.download_button(f"📥 {nombre}: lista completa ({total})", data=lambda: libro_excel(hojas),
                       file_name=f"{nombre.lower().replace(' ', '_')}_{farm}.xlsx", mime=_MIME_XLSX, key=f"dl_{clave}")


def precios_venta():
    """Serie {codigo nacional: PVP sin IVA} de la farmacia activa, o None si sus datos no traen PVP."""
    an = obtener_analisis()
    if an is None or not an["base"]["PVP_Neto_Unit"].notna().any():
        return None
    return an["base"].drop_duplicates(COL_CN).set_index(COL_CN)["PVP_Neto_Unit"].dropna()


def inventario_con_pvp(df_inv):
    """El inventario con una columna PVP (sin IVA) tomada del historico de ventas o del propio inventario."""
    precios = precios_venta()
    if precios is None:
        return df_inv
    return df_inv.assign(PVP=normalizar_cn(df_inv[COL_CN]).map(precios))


def render_columnas_opcionales(encontrado):
    """Tras cargar un archivo: que columnas opcionales trae y cuales no."""
    partes = [f"✅ `{canon}`" + (f" (columna «{orig}»)" if orig != canon else "") if orig else f"➖ `{canon}` no viene"
              for canon, orig in encontrado.items()]
    st.caption("Opcionales: " + " · ".join(partes))


def render_abc():
    an = obtener_analisis()
    if an is None:
        return
    det, res, fuente = A.analisis_abc(an["base"])
    st.markdown("#### Análisis ABC (por ventas de los últimos 12 meses)")
    if res["Venta_12m_EUR"].sum() <= 0:
        st.info("No hay ventas con fecha en los últimos 12 meses para clasificar el surtido.")
        return
    st.caption(f"A = los productos que suman el primer 80 % de las ventas, B = el 15 % siguiente, C = el 5 % final. "
               f"Ventas valoradas con: {fuente}.")
    c_g, c_t = st.columns([1, 1])
    with c_g:
        fig = grafico_abc(res)
        if fig:
            st.plotly_chart(fig, width="stretch", config=_SIN_BARRA, key="an_abc")
    with c_t:
        _tabla(res)
        r = res.set_index("Clase_ABC")
        cola = float(r.loc[["C", "Sin ventas"], "Stock_EUR"].sum())
        st.markdown(f"Los **A** son el {r.at['A', 'Pct_Referencias']:.0f} % de las referencias y ocupan el {r.at['A', 'Pct_Stock']:.0f} % del stock. "
                    f"Los que casi no venden (C y sin ventas) tienen **{format_eur(cola)}** en la estantería.")
    with st.expander("Ver productos por clase"):
        clases = st.multiselect("Clases:", A.CLASES_ABC, default=A.CLASES_ABC, key="an_abc_clases")
        vista = det[det["Clase_ABC"].isin(clases)]
        _tabla(vista, n=25)
        pie_lista(vista, 25, "ABC", "aud_abc")


# ---------------------------------------------------------------------------
# Auditoria: plan de accion, caducidades, roturas recurrentes
# ---------------------------------------------------------------------------
def render_plan_accion():
    an = obtener_analisis()
    if an is None:
        return
    plan, cap, p, base = an["plan"], an["capital"], an["params"], an["base"]
    liberar = plan[plan["Bloque"] == "Liberar capital"]
    ventas = plan[plan["Bloque"] == "Recuperar ventas"]
    st.markdown("#### ✅ Plan de acción")
    st.caption("Qué hacer con cada producto y cuántos euros mueve. El capital parado y la venta perdida se muestran por separado: "
               "uno es dinero que ya está en la estantería y la otra es dinero que deja de entrar cada mes.")
    k1, k2, k3, k4 = st.columns(4)
    pct = cap["liberable"] / cap["actual"] * 100 if cap["actual"] > 0 else 0
    with k1: _kpi("Capital por encima del óptimo", format_eur(cap["liberable"]), f"{pct:.0f} % del stock ({format_eur(cap['actual'])})")
    with k2: _kpi("Recuperable con el plan", format_eur(float(liberar["EUR_Recuperable"].sum())), f"{len(liberar)} acciones")
    margen_perdido = float(base["Margen_Perdido_Mes_EUR"].sum(skipna=True)) if an["calidad"]["tiene_pvp"] else None
    with k3: _kpi("Venta perdida por roturas", f"{format_eur(float(ventas['Venta_Perdida_Mes_EUR'].sum()))}/mes",
                  f"{len(ventas)} productos que pedir ya" + (f" · {format_eur(margen_perdido)} de margen" if margen_perdido else " · a PVL, sin PVP"))
    with k4: _kpi("Stock óptimo", format_eur(cap["optimo"]), f"reponiendo {format_eur(cap['reponer'])}")
    st.markdown("<br>", unsafe_allow_html=True)

    c_g, c_r = st.columns([3, 2])
    with c_g:
        fig = grafico_capital_liberable(cap)
        if fig:
            st.plotly_chart(fig, width="stretch", config=_SIN_BARRA, key="an_capital")
    with c_r:
        st.markdown("**Resumen por acción**")
        if liberar.empty:
            st.success("✅ No hay capital que liberar con las reglas actuales.")
        else:
            res = (liberar.groupby("Accion").agg(Productos=(COL_CN, "count"), Valor_Afectado_EUR=("Valor_Afectado_EUR", "sum"),
                                                 EUR_Recuperable=("EUR_Recuperable", "sum"))
                   .sort_values("EUR_Recuperable", ascending=False).reset_index())
            _tabla(res)
        st.caption(f"Stock objetivo: {p['meses_objetivo_medicamento']:g} meses en medicamento, {p['meses_objetivo_parafarmacia']:g} en parafarmacia y "
                   f"{p['meses_objetivo_no_caducable']:g} en la lista de no caducables. Devolución: {p['dias_devolucion_refrigerado']} días "
                   f"(refrigerados) / {p['dias_devolucion_resto']} días (resto) desde la recepción. Liquidación al {p['dto_liquidacion_pct']:g} %. "
                   "Se cambia en Configuración → J.")

    if an["compras"].empty and not liberar.empty:
        st.info("Sin compras cargadas no se puede saber cuándo se recibió cada producto, así que el plan nunca propone **devolver**. "
                "Sube los pedidos o albaranes en Configuración → K.")
    if an["n_altas"]:
        st.caption(f"{an['n_altas']} producto(s) sin ventas no cuentan como zombie ni como exceso: son altas recientes "
                   "(aparecen por primera vez en un inventario reciente o constan comprados hace poco).")
    if an["red_omitidas"]:
        st.caption("Traspasos: no se han podido leer los datos de " + ", ".join(an["red_omitidas"]) + ".")

    cols_lib = ["Prioridad", "Accion", COL_NOMBRE, COL_LAB, "Ubicacion", COL_STOCK, "Uds_Afectadas", "Valor_Afectado_EUR", "EUR_Recuperable", "Plazo", "Motivo"]
    cols_ven = ["Prioridad", "Accion", COL_NOMBRE, COL_LAB, "Uds_Afectadas", "Valor_Afectado_EUR", "Venta_Perdida_Mes_EUR", "Motivo"]
    t1, t2 = st.tabs([f"💶 Liberar capital ({len(liberar)})", f"🚨 Recuperar ventas ({len(ventas)})"])
    with t1:
        if liberar.empty:
            st.success("✅ Nada que liberar.")
        else:
            _tabla(liberar, cols_lib, n=25)
    with t2:
        if ventas.empty:
            st.success("✅ Sin roturas de productos con demanda.")
        else:
            st.caption("Uds afectadas = unidades a pedir para volver al stock objetivo; valor afectado = su coste.")
            _tabla(ventas, cols_ven, n=25)

    st.markdown("**📥 Listas de trabajo completas (Excel)**")
    opciones = ["Laboratorio", "Euros"] + (["Ubicación"] if (base["Ubicacion"] != "").any() else [])
    c_o, c_d = st.columns([2, 1])
    with c_o:
        orden = st.radio("Ordenar las listas por:", opciones, horizontal=True, key="an_orden_excel")
    with c_d:
        datos = _excel_diferido(an, lambda: A.listas_trabajo(base, plan, an["cad_det"], an["rot_rec"], orden))
        st.download_button("📥 Descargar listas de trabajo", data=datos, file_name=_nombre_archivo("listas_trabajo", an),
                           mime=_MIME_XLSX, width="stretch", key="an_dl_listas")
    st.caption("Una hoja por lista, sin recortes: plan de acción, zombie, UVI, sobrestock, roturas, caducidades y roturas recurrentes.")


def render_caducidades():
    an = obtener_analisis()
    if an is None:
        return
    st.markdown("#### 📅 Calendario de caducidades")
    if an["calidad"]["pct_caducidad"] is None:
        st.info("El inventario cargado no trae fecha de caducidad. Añade al export del ERP una columna **Fecha_Caducidad** "
                "(una fecha por producto) y vuelve a subirlo: esta sección se rellena sola.")
        return
    det, res = an["cad_det"], an["cad_res"]
    r = res.set_index("Tramo")
    st.caption(f"Fechas respecto al inventario. El {an['calidad']['pct_caducidad']:.0f} % de las referencias trae caducidad. "
               "«No se venderá a tiempo» = unidades que sobran si se sigue vendiendo al ritmo actual hasta la fecha de caducidad.")
    k1, k2, k3, k4 = st.columns(4)
    with k1: _kpi("Ya caducado", format_eur(r.at["Caducado", "Valor_EUR"]), f"{r.at['Caducado', 'Productos']} productos")
    with k2: _kpi("Caduca en 0-3 meses", format_eur(r.at["0-3 meses", "Valor_EUR"]), f"en riesgo real {format_eur(r.at['0-3 meses', 'Valor_Riesgo_EUR'])}")
    with k3: _kpi("Caduca en 3-6 meses", format_eur(r.at["3-6 meses", "Valor_EUR"]), f"en riesgo real {format_eur(r.at['3-6 meses', 'Valor_Riesgo_EUR'])}")
    with k4: _kpi("Caduca en 6-12 meses", format_eur(r.at["6-12 meses", "Valor_EUR"]), f"en riesgo real {format_eur(r.at['6-12 meses', 'Valor_Riesgo_EUR'])}")
    st.markdown("<br>", unsafe_allow_html=True)
    fig = grafico_caducidades(res)
    if fig:
        st.plotly_chart(fig, width="stretch", config=_SIN_BARRA, key="an_caducidades")
    tramos = st.multiselect("Tramos a mostrar:", A.TRAMOS_CADUCIDAD, default=A.TRAMOS_CADUCIDAD[:3], key="an_cad_tramos")
    vista = det[det["Tramo"].isin(tramos)]
    if vista.empty:
        st.success("✅ Nada en los tramos elegidos.")
    else:
        _tabla(vista, n=30)
        st.caption("La acción propuesta para cada uno está en el Plan de acción; la lista completa, en el Excel de listas de trabajo.")


def render_roturas_recurrentes():
    an = obtener_analisis()
    if an is None:
        return
    st.markdown("#### 🔁 Roturas recurrentes")
    tabla, per = an["rot_rec"], an["periodo_rot"]
    umbral = an["params"]["rotura_min_ventas_periodo"]
    st.caption(f"Productos habituales que se quedan sin stock dos o más veces. Se usan dos pruebas: las fotos de inventario "
               f"({an['n_fotos']} guardadas; cada inventario con fecha confirmada añade una) y los huecos de venta: {per or 'periodo'}s sin "
               f"ninguna venta en productos que venden {umbral:g} o más unidades por {per or 'periodo'}. Los productos lentos no cuentan, "
               "porque en ellos un hueco es normal.")
    if tabla.empty:
        st.success("✅ No se detectan roturas repetidas.")
        if an["n_fotos"] < 2:
            st.caption("Con menos de dos fotos de inventario solo se pueden ver huecos de venta; la detección mejora con cada carga.")
        return
    k1, k2, k3 = st.columns(3)
    with k1: _kpi("Productos con rotura repetida", str(len(tabla)), f"{int((tabla['Fotos_Sin_Stock'] >= 2).sum())} confirmadas por inventario")
    with k2: _kpi("Unidades no vendidas (est.)", f"{int(tabla['Uds_Perdidas_Est'].sum())}", f"en {int(tabla['Periodos_Sin_Venta'].sum())} {per}(es) sin venta")
    with k3: _kpi("Venta perdida (est.)", format_eur(float(tabla["EUR_Perdido_Est"].sum())),
                  "a PVP sin IVA" if an["calidad"]["tiene_pvp"] else "a PVL (los datos no traen PVP)")
    st.markdown("<br>", unsafe_allow_html=True)
    _tabla(tabla, n=30)
    st.caption("La venta perdida solo se estima para los huecos de venta (en una foto de inventario no se sabe cuántos días duró la rotura). "
               "No distingue si fue por falta del proveedor o por no pedir a tiempo: para eso harían falta las faltas del mayorista.")


# ---------------------------------------------------------------------------
# BI: ventas y margen, descuentos, ficha de laboratorio
# ---------------------------------------------------------------------------
def render_ventas_margen():
    an = obtener_analisis()
    if an is None:
        return
    st.markdown("---")
    st.markdown("#### 📈 Ventas y margen")
    tabla, res = an["interanual"], an["res_interanual"]
    c_g, c_k = st.columns([3, 1])
    with c_g:
        fig = grafico_ventas_interanual(tabla)
        if fig:
            st.plotly_chart(fig, width="stretch", config=_SIN_BARRA, key="an_ventas")
        else:
            st.info("El histórico no tiene fechas: no se puede ver la evolución.")
    with c_k:
        if res:
            _kpi("Ventas últimos 12 meses", format_eur(res["total_12m"]))
            st.markdown("<br>", unsafe_allow_html=True)
            if res.get("var_pct") is not None:
                nota = f"sobre {res['meses_comparables']} meses comparables"
                _kpi("Frente a los 12 anteriores", f"{res['var_pct']:+.1f} %", nota)
                if res.get("mejor_mes"):
                    st.caption(f"Mejor mes: {res['mejor_mes'][0]} ({res['mejor_mes'][1]:+.0f} %) · peor: {res['peor_mes'][0]} ({res['peor_mes'][1]:+.0f} %)")
            else:
                st.caption("Hacen falta 24 meses de historial para comparar con el año anterior.")
    if an["fuente_ventas"]:
        st.caption(f"Euros valorados con: {an['fuente_ventas']}.")

    labs = an["labs"]
    fig_m = grafico_margen_laboratorios(labs)
    if fig_m is None:
        st.info("**Margen:** el histórico de ventas no trae PVP, así que aún no se puede calcular. En cuanto el export incluya una columna "
                "**PVP** (precio por unidad) o **Importe** (total de la línea), aquí aparecerá el margen por laboratorio y la venta perdida "
                "se valorará a PVP en lugar de a PVL.")
        return
    st.plotly_chart(fig_m, width="stretch", config=_SIN_BARRA, key="an_margen")
    p = an["params"]
    iva = f"quitando el IVA ({p['iva_medicamento_pct']:g} % medicamento, {p['iva_parafarmacia_pct']:g} % parafarmacia)" if p["pvp_incluye_iva"] else "tomando el PVP como precio sin IVA"
    st.caption(f"Margen = ventas a PVP {iva} − unidades × coste (PVL − {p['descuento_compra_pct']:g} % de descuento de compra). "
               "«Margen por € en stock» dice cuánto margen anual deja cada euro que tienes invertido en ese laboratorio.")
    with st.expander("Ver tabla de margen por laboratorio"):
        _tabla(labs.sort_values("Margen_12m_EUR", ascending=False),
               [COL_LAB, "Referencias", "Venta_12m_PVP_EUR", "Margen_12m_EUR", "Margen_Pct", "Stock_EUR", "Margen_por_EUR_Stock", "Rotacion_Anual"])


def render_descuentos():
    an = obtener_analisis()
    if an is None:
        return
    st.markdown("---")
    st.markdown("#### 🏷️ Descuentos: aprovechados y perdidos")
    compras, por_lab, perdidos = an["compras"], an["dto_lab"], an["dto_perdidos"]
    if compras.empty:
        st.info("Aún no hay compras: se rellenará con los pedidos que confirmes en Pedidos Transfer y con los que subas por Excel "
                "en Configuración → K.")
        return
    bruto, ahorro = float(por_lab["Bruto_EUR"].sum()), float(por_lab["Ahorro_EUR"].sum())
    k1, k2, k3, k4 = st.columns(4)
    with k1: _kpi("Compras analizadas", format_eur(bruto), f"{len(compras)} líneas, a PVL")
    with k2: _kpi("Descuento conseguido", format_eur(ahorro))
    with k3: _kpi("Descuento medio", f"{ahorro / bruto * 100 if bruto > 0 else 0:.1f} %")
    with k4:
        if perdidos is None:
            _kpi("Dejado de ganar", "—", "carga las ofertas para verlo")
        else:
            _kpi("Dejado de ganar", format_eur(float(perdidos["Perdido_EUR"].sum())), f"{len(perdidos)} líneas")
    st.markdown("<br>", unsafe_allow_html=True)
    fig = grafico_descuentos(por_lab, perdidos is not None)
    if fig:
        st.plotly_chart(fig, width="stretch", config=_SIN_BARRA, key="an_descuentos")
    origenes = compras["Origen"].value_counts().to_dict()
    st.caption("Origen de las compras: " + ", ".join(f"{k} ({v} líneas)" for k, v in origenes.items()) + ".")
    if perdidos is None:
        st.caption("Sin ofertas cargadas solo se ve lo conseguido. Con los tramos (Configuración → B) se calcula además lo que se dejó de ganar.")
    elif perdidos.empty:
        st.success("✅ Ninguna compra se quedó a las puertas de un tramo ni recibió menos descuento del que le tocaba.")
    else:
        with st.expander(f"Ver las {len(perdidos)} líneas con descuento perdido", expanded=True):
            st.caption("«A un paso del tramo»: faltaba menos del 20 % para el tramo siguiente. «Descuento no aplicado»: la cantidad daba "
                       "derecho a más descuento del recibido (reclamable al laboratorio). Se compara con las ofertas cargadas hoy: si los tramos eran otros "
                       "cuando se hizo el pedido, esa línea no aplica.")
            _tabla(perdidos, n=30)


def render_ficha_laboratorio():
    an = obtener_analisis()
    if an is None or an["labs"].empty:
        return
    labs, base = an["labs"], an["base"]
    st.markdown("---")
    st.markdown("#### 🤝 Ficha de negociación por laboratorio")
    lab = st.selectbox("Laboratorio:", labs[COL_LAB].tolist(), key="an_ficha_lab",
                       format_func=lambda x: f"{x} — {format_eur(float(labs.set_index(COL_LAB).at[x, 'Stock_EUR']))} en stock")
    fila = labs.set_index(COL_LAB).loc[lab]
    k1, k2, k3, k4, k5 = st.columns(5)
    with k1: _kpi("Stock", format_eur(fila["Stock_EUR"]), f"{int(fila['Referencias'])} referencias")
    with k2: _kpi("Venta 12 meses", format_eur(fila["Venta_12m_Coste_EUR"]), f"{int(fila['Venta_12m_Uds'])} uds, a coste")
    with k3: _kpi("Rotación anual", f"{fila['Rotacion_Anual']:.1f}×" if pd.notna(fila["Rotacion_Anual"]) else "—", "ventas a coste / stock")
    with k4: _kpi("Capital parado", format_eur(fila["Capital_Parado_EUR"]), f"zombie {format_eur(fila['Zombie_EUR'])}")
    with k5:
        if pd.notna(fila["Margen_12m_EUR"]):
            _kpi("Margen 12 meses", format_eur(fila["Margen_12m_EUR"]), f"{fila['Margen_Pct']:.1f} % sobre venta")
        elif fila["Compras_12m_EUR"] > 0:
            _kpi("Compras 12 meses", format_eur(fila["Compras_12m_EUR"]), f"descuento medio {fila['Dto_Medio_Pct']:.1f} %")
        else:
            _kpi("Roturas", str(int(fila["Roturas"])), f"{format_eur(fila['Venta_Perdida_Mes_EUR'])}/mes")
    st.markdown("<br>", unsafe_allow_html=True)
    args = A.argumentos_negociacion(fila, labs)
    if args:
        st.markdown("**Para la reunión con el delegado:**\n" + "\n".join(f"- {a}" for a in args))
    prods = base[base[COL_LAB] == lab].sort_values("Valor_Stock_EUR", ascending=False)
    cols = [COL_CN, COL_NOMBRE, "Estado", COL_STOCK, "Venta_Media_Mensual", "Venta_12m_Uds", "Stock_Objetivo", "Valor_Stock_EUR", "Exceso_EUR"]
    with st.expander(f"Ver los {len(prods)} productos de {lab}"):
        _tabla(prods, cols)

    def _hojas():
        hojas = {"Resumen": fila.to_frame("Valor").reset_index(names="Indicador").assign(Indicador=lambda d: d["Indicador"].map(titulo_columna)),
                 "Argumentos": pd.DataFrame({"Para la reunión": args or ["(sin argumentos destacables)"]}), "Productos": prods[cols]}
        comp = an["compras"][an["compras"][COL_LAB] == lab]
        if not comp.empty:
            hojas["Compras"] = comp.sort_values("Fecha", ascending=False)
        perd = an["dto_perdidos"]
        if perd is not None and not perd[perd[COL_LAB] == lab].empty:
            hojas["Descuentos perdidos"] = perd[perd[COL_LAB] == lab]
        return hojas
    st.download_button(f"📥 Descargar ficha de {lab}", data=_excel_diferido(an, _hojas),
                       file_name=_nombre_archivo(f"ficha_{str(lab).replace(' ', '_').replace('/', '-')}", an), mime=_MIME_XLSX, key="an_dl_ficha")


# ---------------------------------------------------------------------------
# Configuracion: fecha del inventario, parametros y compras
# ---------------------------------------------------------------------------
def render_fecha_inventario():
    """Bajo el cargador de inventario: fecha del export. Al guardarla se registra la foto de stock de ese dia."""
    if "inventario" not in st.session_state:
        return
    inv = st.session_state["inventario"]
    params = cargar_parametros()
    huella = huella_inventario(inv)
    confirmada = bool(params.get("fecha_inventario")) and params.get("huella_inventario") == huella
    defecto = date.fromisoformat(params["fecha_inventario"]) if confirmada else date.today()
    c1, c2 = st.columns([3, 2])
    with c1:
        fecha = st.date_input("📅 Fecha del inventario (día del export del ERP)", value=defecto, max_value=date.today(),
                              format="DD/MM/YYYY", key=f"fecha_inv_{huella}")
    with c2:
        st.markdown("<div style='height:1.75rem'></div>", unsafe_allow_html=True)
        pulsado = st.button("💾 Guardar fecha", key="btn_fecha_inv", width="stretch",
                            type="secondary" if confirmada and fecha == defecto else "primary")
    if pulsado:
        anterior = params.get("fecha_inventario") if confirmada else None   # mismo inventario: se corrige la fecha, no se anade otra foto
        params["fecha_inventario"], params["huella_inventario"] = fecha.isoformat(), huella
        guardar_parametros(params)
        n = registrar_foto_stock(inv, fecha, sustituye=anterior)
        st.success(f"✅ Inventario fechado a {fecha:%d/%m/%Y}. Foto de stock guardada ({n} en total).")
    elif confirmada:
        st.caption(f"✅ Inventario fechado a {defecto:%d/%m/%Y}.")
    elif params.get("fecha_inventario"):
        st.warning(f"Este inventario es distinto del que se fechó el {date.fromisoformat(params['fecha_inventario']):%d/%m/%Y}. "
                   "Indica su fecha y pulsa **Guardar fecha**.")
    else:
        st.warning("Indica la fecha de este inventario y pulsa **Guardar fecha**: la usan caducidades, plazos de devolución y roturas.")


def _texto_a_lista(txt):
    return sorted({normalizar_cn(x) for x in str(txt).replace(",", "\n").replace(";", "\n").split("\n") if normalizar_cn(x.strip())})


def render_parametros_analisis():
    st.divider()
    st.markdown("#### J. Parámetros de análisis (BI y Auditoría)")
    st.caption("Propios de cada farmacia. Afectan al plan de acción, al capital liberable, a las caducidades y al margen; "
               "no cambian los pedidos ni el resto de pantallas.")
    p = cargar_parametros()
    with st.form("form_parametros_analisis"):
        st.markdown("**Stock óptimo (meses de venta en estantería)**")
        c1, c2, c3 = st.columns(3)
        m_med = c1.number_input("Medicamento", 0.25, 12.0, float(p["meses_objetivo_medicamento"]), 0.25)
        m_par = c2.number_input("Parafarmacia", 0.25, 12.0, float(p["meses_objetivo_parafarmacia"]), 0.25)
        m_noc = c3.number_input("Lista de no caducables", 0.25, 24.0, float(p["meses_objetivo_no_caducable"]), 0.25)
        no_cad = st.text_area("Productos no caducables (códigos nacionales, uno por línea o separados por comas)",
                              "\n".join(p["no_caducables"]), height=80)

        st.markdown("**Devolución al proveedor (días desde la recepción)**")
        c1, c2 = st.columns(2)
        d_ref = c1.number_input("Refrigerados", 0, 60, int(p["dias_devolucion_refrigerado"]), 1)
        d_res = c2.number_input("Resto", 0, 120, int(p["dias_devolucion_resto"]), 1)
        refrig = st.text_area("Productos refrigerados (códigos nacionales). No hace falta si el inventario trae una columna «Refrigerado».",
                              "\n".join(p["refrigerados"]), height=80)
        sin_dev = st.text_input("Laboratorios que no admiten devolución (separados por comas)", ", ".join(p["laboratorios_sin_devolucion"]))

        st.markdown("**Coste real de compra**")
        c1, c2 = st.columns([1, 2])
        dto_gen = c1.number_input("Descuento general sobre PVL (%)", 0.0, 90.0, float(p["descuento_compra_pct"]), 0.5)
        with c2:
            st.caption("Descuento distinto para algún laboratorio (opcional):")
            df_dto = pd.DataFrame([{"Laboratorio": k, "Descuento_%": float(v)} for k, v in p["descuento_compra_por_lab"].items()],
                                  columns=["Laboratorio", "Descuento_%"])
            ed_dto = st.data_editor(df_dto, num_rows="dynamic", hide_index=True, width="stretch", key="ed_dto_lab")

        st.markdown("**Reglas del plan de acción**")
        c1, c2, c3 = st.columns(3)
        dto_liq = c1.number_input("Descuento al liquidar (%)", 0.0, 100.0, float(p["dto_liquidacion_pct"]), 5.0)
        m_liq = c2.number_input("Liquidar si hay stock para más de (meses)", 1.0, 36.0, float(p["meses_cobertura_liquidar"]), 0.5)
        min_eur = c3.number_input("Ignorar excesos menores de (€)", 0.0, 500.0, float(p["min_eur_accion"]), 1.0)
        traspaso = st.checkbox("Proponer traspasos a otras farmacias de la red", bool(p["traspaso_red"]))

        st.markdown("**PVP del histórico de ventas**")
        c1, c2, c3 = st.columns(3)
        con_iva = c1.checkbox("El PVP incluye IVA", bool(p["pvp_incluye_iva"]))
        iva_med = c2.number_input("IVA medicamento (%)", 0.0, 30.0, float(p["iva_medicamento_pct"]), 0.5)
        iva_par = c3.number_input("IVA parafarmacia (%)", 0.0, 30.0, float(p["iva_parafarmacia_pct"]), 0.5)

        st.markdown("**Avisos y roturas**")
        c1, c2 = st.columns(2)
        dias_av = c1.number_input("Avisar si los datos tienen más de (días)", 1, 365, int(p["dias_aviso_datos"]), 1)
        rot_min = c2.number_input("Rotura por hueco de venta: ventas mínimas por periodo", 1.0, 50.0, float(p["rotura_min_ventas_periodo"]), 0.5)

        if st.form_submit_button("💾 Guardar parámetros", type="primary"):
            dto_lab = {}
            for _, r in ed_dto.dropna(subset=["Laboratorio"]).iterrows():
                if str(r["Laboratorio"]).strip() and pd.notna(r["Descuento_%"]):
                    dto_lab[str(r["Laboratorio"]).strip()] = float(r["Descuento_%"])
            p.update({"meses_objetivo_medicamento": m_med, "meses_objetivo_parafarmacia": m_par, "meses_objetivo_no_caducable": m_noc,
                      "no_caducables": _texto_a_lista(no_cad), "dias_devolucion_refrigerado": int(d_ref), "dias_devolucion_resto": int(d_res),
                      "refrigerados": _texto_a_lista(refrig), "laboratorios_sin_devolucion": [x.strip() for x in sin_dev.split(",") if x.strip()],
                      "descuento_compra_pct": dto_gen, "descuento_compra_por_lab": dto_lab, "dto_liquidacion_pct": dto_liq,
                      "meses_cobertura_liquidar": m_liq, "min_eur_accion": min_eur, "traspaso_red": traspaso, "pvp_incluye_iva": con_iva,
                      "iva_medicamento_pct": iva_med, "iva_parafarmacia_pct": iva_par, "dias_aviso_datos": int(dias_av),
                      "rotura_min_ventas_periodo": rot_min})
            guardar_parametros(p)
            st.success("✅ Parámetros guardados.")


def _leer_tabla(archivo):
    """CSV (con ; o , y acentos) o Excel."""
    if not archivo.name.lower().endswith(".csv"):
        return pd.read_excel(archivo)
    for cod in ("utf-8-sig", "latin-1"):
        try:
            archivo.seek(0)
            return pd.read_csv(archivo, sep=None, engine="python", encoding=cod, dtype=str)
        except UnicodeDecodeError:
            continue
    raise ValueError("No se ha podido leer el CSV: guárdalo como UTF-8 o como Excel.")


def render_compras():
    st.divider()
    st.markdown("#### K. Compras y pedidos transfer (opcional)")
    st.caption("Sube los pedidos grandes o albaranes en Excel o CSV. Obligatorias: **fecha, código nacional y unidades**. "
               "Opcionales: PVL, descuento (%), importe y laboratorio (lo que falte se completa con el inventario). "
               "Sirven para saber qué se puede devolver, el descuento conseguido y la ficha de cada laboratorio. "
               "Los pedidos confirmados en esta herramienta ya cuentan sin subir nada.")
    plantilla = pd.DataFrame({"Fecha": ["05/11/2026"], "Codigo_Nacional": ["654321"], "Unidades": [36], "PVL": [2.10], "Descuento": [16],
                              "Laboratorio": ["Cinfa"]})
    st.download_button("📄 Descargar plantilla", data=libro_excel({"Compras": plantilla}), file_name="plantilla_compras.xlsx",
                       mime=_MIME_XLSX, key="dl_plantilla_compras")
    archivo = st.file_uploader("🧾 COMPRAS / PEDIDOS TRANSFER", type=["xlsx", "xls", "csv"], key="up_compras")
    if archivo is not None:
        ident = getattr(archivo, "file_id", None) or f"{archivo.name}-{archivo.size}"
        if st.session_state.get("_proc_up_compras") == ident:
            st.caption(f"✅ {archivo.name} ya procesado.")
        else:
            try:
                crudo = _leer_tabla(archivo)
                nuevas, enc = A.normalizar_compras(crudo, st.session_state.get("inventario"))
                faltan = [k for k in ("Fecha", "Codigo_Nacional", "Unidades") if not enc[k]]
                if faltan:
                    st.error(f"No encuentro la(s) columna(s) obligatoria(s): {', '.join(faltan)}. Columnas del archivo: {', '.join(map(str, crudo.columns))}.")
                elif nuevas.empty:
                    st.error("El archivo no tiene ninguna línea válida (fecha legible, código nacional y unidades mayores que 0).")
                else:
                    total, anadidas = anadir_compras(nuevas)
                    st.session_state["_proc_up_compras"] = ident
                    st.success(f"✅ {anadidas} línea(s) nueva(s) de {len(nuevas)} válidas ({len(crudo) - len(nuevas)} descartadas). Total guardado: {total}.")
                    st.caption("Columnas usadas: " + " · ".join(f"{k} ← {v}" if v else f"{k}: no viene" for k, v in enc.items()))
            except Exception as e:
                st.error(f"No se ha podido leer el archivo: {e}")
    guardadas = cargar_compras()
    if guardadas.empty:
        st.caption("No hay compras subidas por Excel.")
    else:
        st.caption(f"Guardadas: {len(guardadas)} líneas de {guardadas[COL_LAB].nunique()} laboratorio(s), del {guardadas['Fecha'].min():%d/%m/%Y} "
                   f"al {guardadas['Fecha'].max():%d/%m/%Y}, por {format_eur(float(guardadas['Importe'].sum()))}.")
        c1, c2 = st.columns([2, 1])
        seguro = c1.checkbox("Quiero borrar todas las compras subidas por Excel", key="chk_vaciar_compras")
        if c2.button("🗑️ Vaciar compras", disabled=not seguro, key="btn_vaciar_compras") and seguro:
            vaciar_compras()
            st.session_state.pop("_proc_up_compras", None)
            st.success("Compras subidas eliminadas. Los pedidos confirmados en la herramienta no se tocan.")
