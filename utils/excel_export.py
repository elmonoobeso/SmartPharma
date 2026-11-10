"""Exportacion a Excel de las listas de trabajo: una hoja por lista, completas y filtrables."""
import re
from io import BytesIO

import pandas as pd

_PROHIBIDOS = re.compile(r"[\[\]:*?/\\]")


_ACENTOS = {"Accion": "Acción", "Codigo": "Código", "Ubicacion": "Ubicación", "Rotacion": "Rotación", "Ultima": "Última", "Lineas": "Líneas"}


def titulo_columna(nombre):
    """'Valor_Afectado_EUR' -> 'Valor Afectado €'; 'EUR_Recuperable' -> 'Recuperable €'."""
    t = str(nombre)
    if t.startswith("EUR_"):
        t = t[4:] + "_EUR"
    t = t.replace("_EUR", " €").replace("_Pct", " %").replace("_Uds", " uds").replace("_", " ").strip()
    for sin, con in _ACENTOS.items():
        t = t.replace(sin, con)
    return t[0].upper() + t[1:] if t else t


def _nombre_hoja(nombre, usados):
    base = _PROHIBIDOS.sub("-", str(nombre)).strip("'")[:31] or "Hoja"
    final, i = base, 2
    while final.lower() in usados:
        sufijo = f" ({i})"
        final, i = base[:31 - len(sufijo)] + sufijo, i + 1
    usados.add(final.lower())
    return final


def libro_excel(hojas, portada=None):
    """bytes de un .xlsx. `hojas`: {titulo: DataFrame}. `portada`: lista de (concepto, valor) para la primera hoja."""
    salida = BytesIO()
    with pd.ExcelWriter(salida, engine="xlsxwriter", datetime_format="dd/mm/yyyy", date_format="dd/mm/yyyy") as writer:
        libro = writer.book
        f_cab = libro.add_format({"bold": True, "bg_color": "#0066FF", "font_color": "#FFFFFF", "border": 1, "text_wrap": True, "valign": "top"})
        f_eur = libro.add_format({"num_format": "#,##0.00 €"})
        f_dec = libro.add_format({"num_format": "#,##0.0"})
        f_negrita = libro.add_format({"bold": True})
        usados = set()
        if portada:
            ws = libro.add_worksheet(_nombre_hoja("Datos del informe", usados))
            for i, (concepto, valor) in enumerate(portada):
                ws.write(i, 0, str(concepto), f_negrita)
                ws.write(i, 1, "" if valor is None else str(valor))
            ws.set_column(0, 0, 34)
            ws.set_column(1, 1, 70)
        for titulo, df in hojas.items():
            df = df.copy()
            for c in df.columns:
                if pd.api.types.is_datetime64_any_dtype(df[c]):
                    df[c] = df[c].dt.date
            originales = list(df.columns)
            df.columns = [titulo_columna(c) for c in originales]
            hoja = _nombre_hoja(titulo, usados)
            df.to_excel(writer, sheet_name=hoja, index=False)
            ws = writer.sheets[hoja]
            for j, (orig, visible) in enumerate(zip(originales, df.columns)):
                ws.write(0, j, visible, f_cab)
                muestra = df.iloc[:300, j].astype(str).str.len()
                ancho = min(60, max(len(visible) + 2, int(muestra.max()) + 2 if len(muestra) else 0))
                es_num = pd.api.types.is_numeric_dtype(df.iloc[:, j])
                if es_num and ("EUR" in str(orig) or str(orig) in ("PVL", "Coste_Unit", "Importe")):
                    ws.set_column(j, j, max(ancho, 14), f_eur)
                elif es_num and pd.api.types.is_float_dtype(df.iloc[:, j]):
                    ws.set_column(j, j, max(ancho, 10), f_dec)
                else:
                    ws.set_column(j, j, ancho)
            ws.freeze_panes(1, 0)
            if len(df):
                ws.autofilter(0, 0, len(df), len(df.columns) - 1)
    return salida.getvalue()
