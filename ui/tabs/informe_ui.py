"""Informe PDF para el cliente: se elige la farmacia, se genera al pulsar el boton y se descarga.

No se genera en cada rerun ni con un nombre comun a todas las farmacias: el archivo lleva el
nombre de la farmacia y la fecha de sus datos, y se guarda una copia en su carpeta.
"""
from contextlib import contextmanager
from datetime import datetime

import streamlit as st

from config.settings import BASE_DIR, HEALTH_SCORE_MESES_DEFAULT
from core import analisis as A
from core.business import (calcular_benchmark_hs, calcular_health_score, cargar_productos_protegidos, generar_pedido_cobertura,
                           obtener_historico_kpi, obtener_ventas_media)
from data.io import _autocargar_datos_farmacia, cargar_json_farmacia, obtener_farmacias_disponibles
from ui.tabs.analisis_ui import obtener_analisis
from utils.pdf_informe import generar_informe_completo

# Lo que en la sesion pertenece a la farmacia activa y hay que apartar para calcular otra
_CLAVES_FARMACIA = ("farmacia_activa", "inventario", "historico", "ofertas_normalizadas", "ventas_media_cache", "historico_hash",
                    "_analisis_cache")


def _bonito(nombre):
    return str(nombre).replace("_", " ").title()


@contextmanager
def _como_farmacia(nombre):
    """Dentro del bloque, la farmacia activa es `nombre` (sus datos se leen de disco). Al salir se restaura la de verdad."""
    ss = st.session_state
    if nombre == ss.get("farmacia_activa"):
        yield
        return
    guardado = {k: ss[k] for k in _CLAVES_FARMACIA if k in ss}
    try:
        for k in _CLAVES_FARMACIA:
            ss.pop(k, None)
        ss["farmacia_activa"] = nombre
        _autocargar_datos_farmacia()
        yield
    finally:
        for k in _CLAVES_FARMACIA:
            ss.pop(k, None)
        for k, v in guardado.items():
            ss[k] = v


def reunir_datos_informe():
    """Todo lo que necesita el PDF de la farmacia activa."""
    ss = st.session_state
    if "inventario" not in ss or "historico" not in ss:
        raise ValueError("esa farmacia no tiene inventario e histórico de ventas cargados")
    an = obtener_analisis()
    inv = ss["inventario"]
    df_vm = obtener_ventas_media(meses_cobertura=int(HEALTH_SCORE_MESES_DEFAULT))
    pedidos = cargar_json_farmacia("historico_pedidos.json", default=[])
    # Pedido sugerido hoy: su ahorro es una estimacion y se presenta aparte del ahorro confirmado
    previo = generar_pedido_cobertura(inv, df_vm, HEALTH_SCORE_MESES_DEFAULT, ss.get("ofertas_normalizadas"),
                                      productos_protegidos=cargar_productos_protegidos())
    _, abc, abc_fuente = A.analisis_abc(an["base"])
    hs = calcular_health_score(inv, df_vm)
    kpi = obtener_historico_kpi()
    # Una medicion por dia (la ultima), para que los guardados repetidos no ensucien la evolucion
    evolucion = []
    if not kpi.empty and "health_score" in kpi.columns:
        por_dia = kpi.dropna(subset=["fecha", "health_score"]).sort_values("fecha").groupby(kpi["fecha"].dt.normalize())["health_score"].last()
        evolucion = [(f, float(v)) for f, v in por_dia.items()]
    return {
        "farmacia": _bonito(ss["farmacia_activa"]), "an": an, "hs": hs, "benchmark": calcular_benchmark_hs(hs), "hs_evolucion": evolucion,
        "n_pedidos": len(pedidos), "ahorro_confirmado": float(sum(p.get("ahorro_ofertas", 0) for p in pedidos)),
        "inversion_confirmada": float(sum(p.get("coste_total", 0) for p in pedidos)),
        "ahorro_potencial": float(previo["Ahorro"].sum()) if not previo.empty else 0.0,
        "abc": abc, "abc_fuente": abc_fuente, "generado": datetime.now(),
    }


def render_informe():
    st.markdown("---")
    st.markdown("#### 📄 Informe para el cliente (PDF)")
    st.caption("Resumen ejecutivo, ventas, laboratorios, plan de acción, caducidades, roturas, compras y cómo leerlo. "
               "Se genera solo al pulsar el botón, con los datos y parámetros guardados de la farmacia elegida.")
    ss = st.session_state
    farmacias = obtener_farmacias_disponibles()
    activa = ss.get("farmacia_activa")
    c1, c2 = st.columns([2, 1])
    with c1:
        elegida = st.selectbox("Farmacia del informe:", farmacias, index=farmacias.index(activa) if activa in farmacias else 0,
                               format_func=lambda f: _bonito(f) + (" (la que estás viendo)" if f == activa else ""), key="inf_farmacia")
    with c2:
        st.markdown("<div style='height:1.75rem'></div>", unsafe_allow_html=True)
        generar = st.button("📄 Generar informe", type="primary", width="stretch", key="inf_generar")
    if generar:
        try:
            with st.spinner(f"Preparando el informe de {_bonito(elegida)}..."):
                with _como_farmacia(elegida):
                    datos = reunir_datos_informe()
                pdf = generar_informe_completo(datos)
            f_inv = datos["an"]["calidad"]["fecha_inventario"]
            nombre = f"informe_{elegida}_{(f_inv or datos['generado']).strftime('%Y-%m-%d')}.pdf"
            copia = None
            try:
                (BASE_DIR / elegida / nombre).write_bytes(pdf)
                copia = f"farmacias/{elegida}/{nombre}"
            except OSError as e:
                st.warning(f"El informe está listo para descargar, pero no se ha podido guardar la copia en la carpeta de la farmacia: {e}")
            ss["_informe_pdf"] = {"farmacia": elegida, "pdf": pdf, "nombre": nombre, "copia": copia, "hora": datos["generado"],
                                  "fecha_datos": f_inv, "avisos": len(datos["an"]["calidad"]["avisos"])}
        except Exception as e:
            ss.pop("_informe_pdf", None)
            st.error(f"No se ha podido generar el informe de {_bonito(elegida)}: {e} ({type(e).__name__})")
    inf = ss.get("_informe_pdf")
    if inf and inf["farmacia"] == elegida:
        fecha = f"datos a {inf['fecha_datos']:%d/%m/%Y}" if inf["fecha_datos"] is not None else "inventario sin fecha confirmada"
        st.success(f"✅ Informe de {_bonito(elegida)} generado a las {inf['hora']:%H:%M} ({fecha})."
                   + (f" Copia guardada en `{inf['copia']}`." if inf["copia"] else ""))
        if inf["avisos"]:
            st.caption(f"El informe incluye {inf['avisos']} aviso(s) sobre los datos en su última página: revísalos antes de entregarlo.")
        st.download_button("📥 Descargar informe (PDF)", data=inf["pdf"], file_name=inf["nombre"], mime="application/pdf",
                           width="stretch", key="inf_descargar")
    elif inf:
        st.caption(f"Hay un informe generado de {_bonito(inf['farmacia'])}; pulsa «Generar informe» para hacer el de {_bonito(elegida)}.")
