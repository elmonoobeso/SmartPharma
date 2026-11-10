"""Analisis de stock, ventas y compras para Business Intelligence y Auditoria.

Funciones puras (sin Streamlit ni disco): reciben DataFrames y parametros y devuelven
DataFrames. Todo lo que cambia de una farmacia a otra viene en `params`
(ver PARAMETROS_DEFECTO); las columnas opcionales del ERP (PVP, caducidad, ubicacion,
refrigerado) se detectan por nombre y, si faltan, la parte que depende de ellas se omite.
"""
import unicodedata

import numpy as np
import pandas as pd

from config.settings import COL_CN, COL_FECHA, COL_LAB, COL_MOLECULA, COL_NOMBRE, COL_PVL, COL_STOCK, COL_VENTAS
from core.business import _tiers_de_oferta, buscar_oferta_por_indice, construir_indice_ofertas, heuristica_tipo_producto
from utils.helpers import normalizar_cn

PARAMETROS_DEFECTO = {
    # Fecha del inventario cargado y huella del archivo al que corresponde
    "fecha_inventario": None,
    "huella_inventario": None,
    # Stock optimo: meses de venta que se quieren tener en la estanteria
    "meses_objetivo_medicamento": 2.0,
    "meses_objetivo_parafarmacia": 2.0,
    "meses_objetivo_no_caducable": 6.0,
    "no_caducables": [],
    # Devolucion al proveedor: dias desde la recepcion en que aun se acepta
    "dias_devolucion_refrigerado": 2,
    "dias_devolucion_resto": 10,
    "refrigerados": [],
    "laboratorios_sin_devolucion": [],
    # Coste real = PVL x (1 - descuento). General y, si se conoce, por laboratorio (en %)
    "descuento_compra_pct": 0.0,
    "descuento_compra_por_lab": {},
    # Reglas del plan de accion
    "dto_liquidacion_pct": 30.0,
    "meses_cobertura_liquidar": 6.0,
    "min_eur_accion": 5.0,
    "traspaso_red": True,
    # PVP del historico de ventas
    "pvp_incluye_iva": True,
    "iva_medicamento_pct": 4.0,
    "iva_parafarmacia_pct": 21.0,
    # Avisos y roturas
    "dias_aviso_datos": 45,
    "rotura_min_ventas_periodo": 3.0,
}

# (nombres exactos, fragmentos que basta con que el nombre contenga)
ALIAS = {
    "pvp": (["pvp", "precio_venta", "pvp_iva", "precio_venta_publico"], ["precio_venta"]),
    "importe": (["importe", "importe_venta", "total_venta", "importe_total"], ["importe"]),
    "caducidad": (["fecha_caducidad", "caducidad", "fecha_cad", "cad"], ["caducidad"]),
    "refrigerado": (["refrigerado", "frio", "nevera", "termolabil", "cadena_frio"], ["refriger", "termolab"]),
    "ubicacion": (["ubicacion", "localizacion", "estanteria", "zona"], ["ubicacion", "localizacion"]),
    "fecha": (["fecha", "fecha_pedido", "fecha_compra", "fecha_albaran", "fecha_recepcion"], ["fecha"]),
    "cn": (["codigo_nacional", "cn", "cod_nacional", "c_n", "codigo"], ["codigo_nacional", "cod_nacional"]),
    "unidades": (["unidades", "cantidad", "uds", "unidades_pedidas", "cant"], ["unidades", "cantidad"]),
    "pvl": (["pvl", "precio", "precio_unitario", "coste_unitario", "precio_coste"], ["precio"]),
    "descuento": (["descuento", "dto", "descuento_pct", "dto_pct", "%dto", "%_dto"], ["descuento"]),
    "importe_compra": (["importe", "importe_neto", "total", "neto", "coste"], ["importe"]),
    "laboratorio": (["laboratorio", "proveedor", "lab"], ["laboratorio", "proveedor"]),
}
MESES_ES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
TRAMOS_CADUCIDAD = ["Caducado", "0-3 meses", "3-6 meses", "6-12 meses", "Más de 12 meses"]
_VERDADERO = {"si", "s", "1", "true", "x", "verdadero", "yes", "y", "1.0"}


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def completar_parametros(params=None):
    """Parametros de la farmacia sobre los valores por defecto (los que falten se rellenan)."""
    p = {k: (v.copy() if isinstance(v, (list, dict)) else v) for k, v in PARAMETROS_DEFECTO.items()}
    p.update({k: v for k, v in (params or {}).items() if v is not None or k in ("fecha_inventario", "huella_inventario")})
    return p


def _norm(txt):
    t = unicodedata.normalize("NFKD", str(txt)).encode("ascii", "ignore").decode().lower().strip()
    return t.replace(" ", "_").replace("-", "_").replace(".", "")


def columna(df, clave):
    """Nombre real de la columna opcional `clave` en df, o None si no esta."""
    if df is None or not len(df.columns):
        return None
    nombres = {_norm(c): c for c in df.columns}
    exactos, fragmentos = ALIAS[clave]
    for a in exactos:
        if a in nombres:
            return nombres[a]
    for a in fragmentos:
        for n, original in nombres.items():
            if a in n:
                return original
    return None


COLUMNAS_OPCIONALES = {
    "inventario": [("PVP", "pvp"), ("Fecha_Caducidad", "caducidad"), ("Ubicacion", "ubicacion"), ("Refrigerado", "refrigerado")],
    "historico": [("PVP", "pvp"), ("Importe", "importe")],
}


def normalizar_opcionales(df, tipo):
    """Da su nombre canonico a las columnas opcionales del export ('P.V.P.' -> 'PVP', 'Caducidad' -> 'Fecha_Caducidad'...).

    Devuelve (df, {nombre canonico: columna original o None}). Asi todas las pantallas las
    encuentran con el mismo nombre, venga como venga del ERP.
    """
    df = df.copy()
    encontrado = {}
    for canonico, clave in COLUMNAS_OPCIONALES[tipo]:
        original = columna(df, clave)
        encontrado[canonico] = original
        if original is not None and original != canonico and canonico not in df.columns:
            df = df.rename(columns={original: canonico})
    return df, encontrado


def _num(serie):
    """Numeros aunque vengan como texto espanol ('1.234,50 €', '12 %')."""
    if pd.api.types.is_numeric_dtype(serie):
        return pd.to_numeric(serie, errors="coerce")
    s = serie.astype(str).str.replace(r"[€%\s]", "", regex=True)
    ambos = s.str.contains(",", regex=False) & s.str.contains(".", regex=False)
    s = s.where(~ambos, s.str.replace(".", "", regex=False))
    return pd.to_numeric(s.str.replace(",", ".", regex=False), errors="coerce")


def _lista_cn(valores):
    return {normalizar_cn(v) for v in ([] if valores is None else valores) if normalizar_cn(v)}


def _tipos(df):
    col_mol = COL_MOLECULA if COL_MOLECULA in df.columns else (COL_NOMBRE if COL_NOMBRE in df.columns else None)
    mols = df[col_mol] if col_mol else [""] * len(df)
    return [heuristica_tipo_producto(cn, mol) for cn, mol in zip(df[COL_CN], mols)]


def _iva(tipo, params):
    return (params["iva_medicamento_pct"] if tipo == "Medicamento" else params["iva_parafarmacia_pct"]) / 100.0


def fecha_referencia(params, hoy=None):
    """Fecha del inventario si esta confirmada; si no, hoy."""
    f = params.get("fecha_inventario")
    return pd.Timestamp(f) if f else pd.Timestamp(hoy or pd.Timestamp.now().normalize())


# ---------------------------------------------------------------------------
# Historico de ventas
# ---------------------------------------------------------------------------
def preparar_historico(df_hist, params, tipos_por_cn=None):
    """Ventas por linea con fecha, unidades e importe sin IVA (NaN si el historico no trae PVP).

    Devuelve columnas [CN, Fecha, Uds, Importe_Neto, Periodo]; Periodo = anio*12 + mes.
    """
    vacio = pd.DataFrame(columns=[COL_CN, "Fecha", "Uds", "Importe_Neto", "Periodo"])
    if df_hist is None or df_hist.empty or COL_FECHA not in df_hist.columns or COL_VENTAS not in df_hist.columns:
        return vacio
    df = pd.DataFrame({COL_CN: normalizar_cn(df_hist[COL_CN]),
                       "Fecha": pd.to_datetime(df_hist[COL_FECHA], errors="coerce", dayfirst=True),
                       "Uds": _num(df_hist[COL_VENTAS]).fillna(0)})
    c_imp, c_pvp = columna(df_hist, "importe"), columna(df_hist, "pvp")
    if c_imp:
        bruto = _num(df_hist[c_imp])
    elif c_pvp:
        bruto = df["Uds"] * _num(df_hist[c_pvp])
    else:
        bruto = pd.Series(np.nan, index=df_hist.index)
    bruto = pd.Series(bruto.to_numpy(), index=df.index)
    if params.get("pvp_incluye_iva", True):
        tipos_por_cn = tipos_por_cn or {}
        iva_cn = {cn: _iva(tipos_por_cn.get(cn) or heuristica_tipo_producto(cn), params) for cn in df[COL_CN].unique()}
        iva = df[COL_CN].map(iva_cn)
        bruto = bruto / (1 + iva)
    df["Importe_Neto"] = bruto
    df = df.dropna(subset=["Fecha"])
    df["Periodo"] = df["Fecha"].dt.year * 12 + df["Fecha"].dt.month
    return df


# ---------------------------------------------------------------------------
# Base por producto
# ---------------------------------------------------------------------------
def construir_base(df_inv, df_vm, hist, params, cns_zombie=(), cns_uvi=(), protegidos=None, compras=None, cns_nuevos=()):
    """Una fila por linea de inventario con todo lo que usan el plan de accion y los informes.

    Estado: Rotura, Zombie, UVI, Alta reciente, Sobrestock, Bajo objetivo, Correcto o Sin stock ni demanda.
    Zombie, UVI y altas recientes llegan ya calculados (misma definicion que el resto de la herramienta).
    Un alta reciente no tiene ventas todavia: su stock no cuenta como exceso ni genera acciones.
    """
    df = df_inv.copy()
    df[COL_CN] = normalizar_cn(df[COL_CN])
    for c, defecto in ((COL_NOMBRE, ""), (COL_LAB, "Sin laboratorio")):
        if c not in df.columns:
            df[c] = defecto
    df[COL_LAB] = df[COL_LAB].fillna("Sin laboratorio").astype(str)
    df[COL_STOCK] = _num(df[COL_STOCK]).fillna(0) if COL_STOCK in df.columns else 0
    df[COL_PVL] = _num(df[COL_PVL]).fillna(0) if COL_PVL in df.columns else 0.0
    df["Tipo"] = _tipos(df)

    # Coste real de compra
    dto_lab = {str(k): float(v) for k, v in (params.get("descuento_compra_por_lab") or {}).items()}
    dto = df[COL_LAB].map(dto_lab).fillna(float(params.get("descuento_compra_pct") or 0)) / 100.0
    df["Coste_Unit"] = (df[COL_PVL] * (1 - dto.clip(0, 1))).round(4)

    # Demanda prevista (la misma que usa el resto de la herramienta) y venta real de 12 meses
    vm = df_vm[[COL_CN, "Venta_Media_Mensual"]] if df_vm is not None and not df_vm.empty else pd.DataFrame(columns=[COL_CN, "Venta_Media_Mensual"])
    df = df.merge(vm.drop_duplicates(COL_CN), on=COL_CN, how="left")
    df["Venta_Media_Mensual"] = df["Venta_Media_Mensual"].fillna(0)
    if hist is not None and not hist.empty:
        ult12 = hist[hist["Periodo"] > hist["Periodo"].max() - 12]
        agg12 = ult12.groupby(COL_CN).agg(Venta_12m_Uds=("Uds", "sum"), Importe_12m=("Importe_Neto", lambda s: s.sum(min_count=1)))
        df = df.merge(agg12, left_on=COL_CN, right_index=True, how="left")
        con_precio = hist.dropna(subset=["Importe_Neto"])
        con_precio = con_precio[con_precio["Uds"] > 0]
        # Precio de venta vigente: media de las 3 ultimas lineas vendidas de cada producto
        ult3 = con_precio.sort_values("Fecha").groupby(COL_CN).tail(3).groupby(COL_CN)[["Importe_Neto", "Uds"]].sum()
        ult_precio = ult3["Importe_Neto"] / ult3["Uds"]
        df["PVP_Neto_Unit"] = df[COL_CN].map(ult_precio)
        df["Ultima_Venta"] = df[COL_CN].map(hist[hist["Uds"] > 0].groupby(COL_CN)["Fecha"].max())
    else:
        df["Venta_12m_Uds"], df["Importe_12m"], df["PVP_Neto_Unit"], df["Ultima_Venta"] = 0.0, np.nan, np.nan, pd.NaT
    df["Venta_12m_Uds"] = df["Venta_12m_Uds"].fillna(0)
    c_pvp_inv = columna(df_inv, "pvp")
    if c_pvp_inv:
        pvp_inv = _num(df[c_pvp_inv])
        if params.get("pvp_incluye_iva", True):
            pvp_inv = pvp_inv / (1 + df["Tipo"].map(lambda t: _iva(t, params)))
        df["PVP_Neto_Unit"] = df["PVP_Neto_Unit"].fillna(pvp_inv)
    df["Margen_Unit"] = df["PVP_Neto_Unit"] - df["Coste_Unit"]

    # Objetivo de stock por producto
    no_cad = _lista_cn(params.get("no_caducables"))
    meses = np.where(df[COL_CN].isin(no_cad), float(params["meses_objetivo_no_caducable"]),
                     np.where(df["Tipo"] == "Medicamento", float(params["meses_objetivo_medicamento"]),
                              float(params["meses_objetivo_parafarmacia"])))
    df["Meses_Objetivo"] = meses
    es_zombie = df[COL_CN].isin(_lista_cn(cns_zombie))
    es_uvi = df[COL_CN].isin(_lista_cn(cns_uvi)) & ~es_zombie
    objetivo = np.ceil(df["Venta_Media_Mensual"] * meses - 1e-9)
    objetivo = np.where(es_zombie, 0, objetivo)
    minimos = {}
    for pp in protegidos or []:
        try:
            minimos[normalizar_cn(pp.get("codigo_nacional"))] = float(pp.get("stock_minimo", 1) or 0)
        except (TypeError, ValueError):
            continue
    df["Stock_Objetivo"] = np.maximum(objetivo, df[COL_CN].map(minimos).fillna(0))
    stock = df[COL_STOCK].clip(lower=0)
    es_nuevo = df[COL_CN].isin(_lista_cn(cns_nuevos)) & ~es_zombie & (stock > 0)
    df["Stock_Objetivo"] = np.where(es_nuevo, np.maximum(df["Stock_Objetivo"], stock), df["Stock_Objetivo"])
    df["Exceso_Uds"] = (stock - df["Stock_Objetivo"]).clip(lower=0)
    df["Deficit_Uds"] = (df["Stock_Objetivo"] - stock).clip(lower=0)
    df["Valor_Stock_EUR"] = (stock * df["Coste_Unit"]).round(2)
    df["Exceso_EUR"] = (df["Exceso_Uds"] * df["Coste_Unit"]).round(2)
    df["Deficit_EUR"] = (df["Deficit_Uds"] * df["Coste_Unit"]).round(2)
    df["Meses_Stock"] = np.where(df["Venta_Media_Mensual"] > 0, stock / df["Venta_Media_Mensual"].where(df["Venta_Media_Mensual"] > 0), np.nan)

    rotura = (df[COL_STOCK] <= 0) & (df["Venta_Media_Mensual"] > 0)
    df["Estado"] = np.select(
        [rotura, es_zombie & (stock > 0), es_uvi & (stock > 0), es_nuevo, df["Exceso_Uds"] > 0, df["Deficit_Uds"] > 0, stock > 0],
        ["Rotura", "Zombie", "UVI", "Alta reciente", "Sobrestock", "Bajo objetivo", "Correcto"], default="Sin stock ni demanda")
    # Venta perdida = lo que se deja de vender, a precio de venta (PVP sin IVA). Sin PVP en los datos, a PVL.
    df["Venta_Perdida_Mes_EUR"] = np.where(
        rotura, df["Venta_Media_Mensual"] * df["PVP_Neto_Unit"].where(df["PVP_Neto_Unit"].notna(), df[COL_PVL]), 0.0).round(2)
    df["Margen_Perdido_Mes_EUR"] = np.where(rotura, df["Venta_Media_Mensual"] * df["Margen_Unit"], 0.0).round(2)

    # Opcionales del ERP
    c_ref, c_ubi, c_cad = columna(df_inv, "refrigerado"), columna(df_inv, "ubicacion"), columna(df_inv, "caducidad")
    marcados = df[c_ref].astype(str).str.strip().str.lower().isin(_VERDADERO) if c_ref else False
    df["Refrigerado"] = marcados | df[COL_CN].isin(_lista_cn(params.get("refrigerados")))
    df["Ubicacion"] = df[c_ubi].astype(str).where(df[c_ubi].notna(), "") if c_ubi else ""
    df["Fecha_Caducidad_"] = pd.to_datetime(df[c_cad], errors="coerce", dayfirst=True) if c_cad else pd.NaT
    ref = fecha_referencia(params)
    df["Meses_Hasta_Cad"] = (df["Fecha_Caducidad_"] - ref).dt.days / 30.44
    vendible = np.floor(df["Venta_Media_Mensual"] * df["Meses_Hasta_Cad"].clip(lower=0))
    df["Uds_Riesgo_Cad"] = np.where(df["Fecha_Caducidad_"].notna() & (stock > 0), (stock - vendible).clip(lower=0), 0.0)
    df["Uds_Riesgo_Cad"] = np.where(df["Meses_Hasta_Cad"] > 12, 0.0, df["Uds_Riesgo_Cad"])

    if compras is not None and not compras.empty:
        df["Ultima_Compra"] = df[COL_CN].map(compras.groupby(COL_CN)["Fecha"].max())
    else:
        df["Ultima_Compra"] = pd.NaT
    return df


# ---------------------------------------------------------------------------
# Plan de accion
# ---------------------------------------------------------------------------
def generar_plan_accion(base, params, necesidades_red=None):
    """Una accion por producto con problema, con los euros que mueve.

    Dos bloques que no se suman entre si: 'Liberar capital' (dinero que ya esta en la
    estanteria) y 'Recuperar ventas' (venta que se pierde cada mes por una rotura).
    `necesidades_red`: {cn: (farmacia, unidades que le faltan)} de otras farmacias de la red.
    """
    cols = ["Bloque", "Prioridad", "Accion", "Motivo", COL_CN, COL_NOMBRE, COL_LAB, "Ubicacion", COL_STOCK,
            "Uds_Afectadas", "Valor_Afectado_EUR", "EUR_Recuperable", "Venta_Perdida_Mes_EUR", "Plazo"]
    if base is None or base.empty:
        return pd.DataFrame(columns=cols)
    ref = fecha_referencia(params)
    dto_liq = float(params["dto_liquidacion_pct"]) / 100.0
    min_eur = float(params["min_eur_accion"])
    sin_dev = {str(x).strip().lower() for x in params.get("laboratorios_sin_devolucion") or []}
    red = necesidades_red if params.get("traspaso_red", True) else None
    filas = []

    def fila(r, bloque, accion, motivo, uds, valor, recuperable, perdida=0.0, plazo=""):
        filas.append({"Bloque": bloque, "Accion": accion, "Motivo": motivo, COL_CN: r[COL_CN], COL_NOMBRE: r[COL_NOMBRE],
                      COL_LAB: r[COL_LAB], "Ubicacion": r["Ubicacion"], COL_STOCK: r[COL_STOCK], "Uds_Afectadas": int(round(uds)),
                      "Valor_Afectado_EUR": round(valor, 2), "EUR_Recuperable": round(recuperable, 2),
                      "Venta_Perdida_Mes_EUR": round(perdida, 2), "Plazo": plazo})

    candidatos = base[(base["Exceso_Uds"] > 0) | (base["Uds_Riesgo_Cad"] > 0) | (base["Estado"] == "Rotura")]
    for r in candidatos.to_dict("records"):
        coste, vmm, estado = r["Coste_Unit"], r["Venta_Media_Mensual"], r["Estado"]
        if estado == "Rotura":
            base_val = "PVP sin IVA" if pd.notna(r["PVP_Neto_Unit"]) else "PVL, porque no hay PVP"
            fila(r, "Recuperar ventas", "Pedir ya", f"Rotura: vende {vmm:.1f} uds/mes y no hay stock (venta perdida a {base_val})",
                 r["Deficit_Uds"], r["Deficit_EUR"], 0.0, r["Venta_Perdida_Mes_EUR"], "Hoy")
            continue
        cad = r["Fecha_Caducidad_"]
        if pd.notna(cad) and cad <= ref and r[COL_STOCK] > 0:
            fila(r, "Liberar capital", "Retirar (caducado)", f"Caducó el {cad:%d/%m/%Y}", r[COL_STOCK], r["Valor_Stock_EUR"], 0.0, plazo="Hoy")
            continue
        uds = max(r["Exceso_Uds"], r["Uds_Riesgo_Cad"])
        valor = uds * coste
        if valor < min_eur:
            continue
        # 1. Devolucion: solo si se recibio hace menos dias que el plazo del proveedor
        ult = r["Ultima_Compra"]
        plazo_dev = int(params["dias_devolucion_refrigerado"] if r["Refrigerado"] else params["dias_devolucion_resto"])
        if pd.notna(ult) and str(r[COL_LAB]).strip().lower() not in sin_dev:
            dias = (ref - ult).days
            if 0 <= dias <= plazo_dev:
                tipo = "refrigerado" if r["Refrigerado"] else "no refrigerado"
                fila(r, "Liberar capital", "Devolver al proveedor",
                     f"Recibido el {ult:%d/%m/%Y} ({tipo}: plazo de {plazo_dev} días)", uds, valor, valor,
                     plazo=f"Quedan {plazo_dev - dias} día(s)")
                continue
        # 2. Caducidad: no se vendera a tiempo
        if r["Uds_Riesgo_Cad"] > 0 and r["Uds_Riesgo_Cad"] >= r["Exceso_Uds"] and estado not in ("Zombie", "UVI"):
            fila(r, "Liberar capital", "Promocionar antes de caducar",
                 f"Caduca el {cad:%d/%m/%Y}; al ritmo actual sobran {int(r['Uds_Riesgo_Cad'])} uds",
                 r["Uds_Riesgo_Cad"], r["Uds_Riesgo_Cad"] * coste, r["Uds_Riesgo_Cad"] * coste * (1 - dto_liq),
                 plazo=f"{max(0, r['Meses_Hasta_Cad']):.1f} meses")
            continue
        # 3. Traspaso a otra farmacia de la red que lo necesita
        if red and r[COL_CN] in red:
            destino, falta = red[r[COL_CN]]
            mover = min(uds, falta)
            if mover * coste >= min_eur:
                fila(r, "Liberar capital", f"Traspasar a {destino}", f"Allí faltan {int(falta)} uds y aquí sobran {int(uds)}",
                     mover, mover * coste, mover * coste, plazo="Esta semana")
                continue
        # 4. Sin salida externa: liquidar o dejar de reponer
        caduca = f"; caduca el {cad:%d/%m/%Y}" if pd.notna(cad) and r["Meses_Hasta_Cad"] <= 12 else ""
        if estado == "Zombie":
            fila(r, "Liberar capital", "Liquidar y dar de baja", "12 meses sin ventas" + caduca, uds, valor, valor * (1 - dto_liq), plazo="Este mes")
        elif estado == "UVI":
            fila(r, "Liberar capital", "Promocionar y no reponer", "6 meses sin ventas (aún no es zombie)" + caduca, uds, valor,
                 valor * (1 - dto_liq), plazo="Este mes")
        elif vmm > 0 and r["Meses_Stock"] >= float(params["meses_cobertura_liquidar"]):
            fila(r, "Liberar capital", "Liquidar exceso y no reponer",
                 f"Stock para {r['Meses_Stock']:.1f} meses (objetivo {r['Meses_Objetivo']:g})", uds, valor, valor * (1 - dto_liq),
                 plazo="Este mes")
        elif vmm > 0:
            fila(r, "Liberar capital", "No reponer hasta bajar a objetivo",
                 f"Stock para {r['Meses_Stock']:.1f} meses (objetivo {r['Meses_Objetivo']:g})", uds, valor, valor,
                 plazo=f"{uds / vmm:.1f} meses")
        else:
            fila(r, "Liberar capital", "Promocionar y no reponer", "Sin demanda prevista", uds, valor, valor * (1 - dto_liq), plazo="Este mes")
    plan = pd.DataFrame(filas, columns=[c for c in cols if c != "Prioridad"])
    if plan.empty:
        return pd.DataFrame(columns=cols)
    plan["_orden"] = np.where(plan["Bloque"] == "Liberar capital", plan["EUR_Recuperable"], plan["Venta_Perdida_Mes_EUR"])
    plan = plan.sort_values(["Bloque", "_orden", "Valor_Afectado_EUR"], ascending=[True, False, False])
    plan["Prioridad"] = plan.groupby("Bloque").cumcount() + 1
    return plan[cols].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Capital liberable
# ---------------------------------------------------------------------------
def calcular_capital_liberable(base):
    """Del stock actual al stock optimo. Se cumple: actual - zombie - uvi - sobrestock + reponer = optimo."""
    if base is None or base.empty:
        return {"actual": 0.0, "zombie": 0.0, "uvi": 0.0, "sobrestock": 0.0, "reponer": 0.0, "optimo": 0.0, "liberable": 0.0}
    exc = base.groupby("Estado")["Exceso_EUR"].sum()
    zombie, uvi = float(exc.get("Zombie", 0)), float(exc.get("UVI", 0))
    sobre = float(base["Exceso_EUR"].sum()) - zombie - uvi
    actual, reponer = float(base["Valor_Stock_EUR"].sum()), float(base["Deficit_EUR"].sum())
    return {"actual": round(actual, 2), "zombie": round(zombie, 2), "uvi": round(uvi, 2), "sobrestock": round(sobre, 2),
            "reponer": round(reponer, 2), "optimo": round(actual - zombie - uvi - sobre + reponer, 2),
            "liberable": round(zombie + uvi + sobre, 2)}


# ---------------------------------------------------------------------------
# ABC
# ---------------------------------------------------------------------------
CLASES_ABC = ["A", "B", "C", "Sin ventas"]


def analisis_abc(base):
    """ABC por ventas en euros de los ultimos 12 meses, cruzado con el stock. Devuelve (detalle, resumen, fuente).

    A = productos que suman el primer 80 % de las ventas, B = hasta el 95 %, C = el resto,
    'Sin ventas' = con stock y sin ninguna venta en 12 meses. Las ventas se valoran con el PVP
    del historico (sin IVA) si lo trae; si no, a PVL.
    """
    cols = [COL_CN, COL_NOMBRE, COL_LAB, "Clase_ABC", "Venta_12m_Uds", "Venta_12m_EUR", "Pct_Ventas_Acum", COL_STOCK, "Valor_Stock_EUR",
            "Exceso_EUR", "Estado"]
    vacio = pd.DataFrame({"Clase_ABC": CLASES_ABC, "Referencias": 0, "Pct_Referencias": 0.0, "Venta_12m_EUR": 0.0, "Pct_Ventas": 0.0,
                          "Stock_EUR": 0.0, "Pct_Stock": 0.0, "Exceso_EUR": 0.0})
    if base is None or base.empty:
        return pd.DataFrame(columns=cols), vacio, ""
    df = base.copy()
    a_pvl = df["Venta_12m_Uds"] * df[COL_PVL]
    if df["Importe_12m"].notna().any():
        df["Venta_12m_EUR"], fuente = df["Importe_12m"].fillna(a_pvl), "PVP del histórico, sin IVA"
    else:
        df["Venta_12m_EUR"], fuente = a_pvl, "PVL (el histórico no trae PVP)"
    df = df[(df["Venta_12m_EUR"] > 0) | (df[COL_STOCK] > 0)].sort_values("Venta_12m_EUR", ascending=False).reset_index(drop=True)
    total = float(df["Venta_12m_EUR"].sum())
    acum = df["Venta_12m_EUR"].cumsum() / total * 100 if total > 0 else pd.Series(0.0, index=df.index)
    previo = acum.shift(1, fill_value=0.0)          # el producto que cruza el 80 % sigue siendo A
    df["Pct_Ventas_Acum"] = acum.round(1)
    df["Clase_ABC"] = np.select([df["Venta_12m_EUR"] <= 0, previo < 80, previo < 95], ["Sin ventas", "A", "B"], default="C")
    res = df.groupby("Clase_ABC").agg(Referencias=(COL_CN, "count"), Venta_12m_EUR=("Venta_12m_EUR", "sum"),
                                      Stock_EUR=("Valor_Stock_EUR", "sum"), Exceso_EUR=("Exceso_EUR", "sum")).reindex(CLASES_ABC).fillna(0)
    res["Referencias"] = res["Referencias"].astype(int)
    for col, pct in (("Referencias", "Pct_Referencias"), ("Venta_12m_EUR", "Pct_Ventas"), ("Stock_EUR", "Pct_Stock")):
        t = float(res[col].sum())
        res[pct] = (res[col] / t * 100).round(1) if t > 0 else 0.0
    res = res.reset_index()[["Clase_ABC", "Referencias", "Pct_Referencias", "Venta_12m_EUR", "Pct_Ventas", "Stock_EUR", "Pct_Stock", "Exceso_EUR"]]
    return df[cols], res.round(2), fuente


# ---------------------------------------------------------------------------
# Caducidades
# ---------------------------------------------------------------------------
def calcular_caducidades(base):
    """(detalle por producto, resumen por tramo). Solo productos con stock y fecha de caducidad.

    Valor_Riesgo = unidades que, al ritmo de venta actual, no se venderan antes de caducar.
    """
    cols = [COL_CN, COL_NOMBRE, COL_LAB, "Ubicacion", COL_STOCK, "Fecha_Caducidad", "Tramo", "Venta_Media_Mensual",
            "Uds_Riesgo", "Valor_EUR", "Valor_Riesgo_EUR"]
    resumen_vacio = pd.DataFrame({"Tramo": TRAMOS_CADUCIDAD, "Productos": 0, "Valor_EUR": 0.0, "Valor_Riesgo_EUR": 0.0})
    if base is None or base.empty:
        return pd.DataFrame(columns=cols), resumen_vacio
    df = base[base["Fecha_Caducidad_"].notna() & (base[COL_STOCK] > 0)].copy()
    if df.empty:
        return pd.DataFrame(columns=cols), resumen_vacio
    m = df["Meses_Hasta_Cad"]
    df["Tramo"] = np.select([m <= 0, m <= 3, m <= 6, m <= 12], TRAMOS_CADUCIDAD[:4], default=TRAMOS_CADUCIDAD[4])
    df["Uds_Riesgo"] = np.where(m <= 0, df[COL_STOCK], df["Uds_Riesgo_Cad"])
    df["Valor_EUR"] = df["Valor_Stock_EUR"]
    df["Valor_Riesgo_EUR"] = (df["Uds_Riesgo"] * df["Coste_Unit"]).round(2)
    df["Fecha_Caducidad"] = df["Fecha_Caducidad_"]
    resumen = (df.groupby("Tramo").agg(Productos=(COL_CN, "count"), Valor_EUR=("Valor_EUR", "sum"), Valor_Riesgo_EUR=("Valor_Riesgo_EUR", "sum"))
               .reindex(TRAMOS_CADUCIDAD).fillna(0).reset_index())
    resumen["Productos"] = resumen["Productos"].astype(int)
    return df.sort_values("Fecha_Caducidad_")[cols].reset_index(drop=True), resumen


# ---------------------------------------------------------------------------
# Ventas en el tiempo
# ---------------------------------------------------------------------------
def ventas_mensuales(hist, base):
    """(serie mensual [Periodo, Fecha, EUR, Uds], texto que dice con que se han valorado los euros)."""
    vacio = pd.DataFrame(columns=["Periodo", "Fecha", "EUR", "Uds"])
    if hist is None or hist.empty:
        return vacio, ""
    df = hist.copy()
    if df["Importe_Neto"].notna().any():
        fuente = "PVP del histórico, sin IVA"
        eur = df["Importe_Neto"]
        if eur.isna().any() and base is not None and not base.empty:
            pvl = base.drop_duplicates(COL_CN).set_index(COL_CN)[COL_PVL]
            eur = eur.fillna(df["Uds"] * df[COL_CN].map(pvl))
            fuente += " (líneas sin precio, a PVL)"
    else:
        fuente = "unidades × PVL actual (aproximación: el histórico no trae PVP)"
        pvl = base.drop_duplicates(COL_CN).set_index(COL_CN)[COL_PVL] if base is not None and not base.empty else pd.Series(dtype=float)
        eur = df["Uds"] * df[COL_CN].map(pvl)
    df["EUR"] = eur.fillna(0)
    mens = df.groupby("Periodo").agg(EUR=("EUR", "sum"), Uds=("Uds", "sum"))
    mens = mens.reindex(range(int(mens.index.min()), int(mens.index.max()) + 1), fill_value=0).reset_index(names="Periodo")
    mens["Fecha"] = [pd.Timestamp(year=(p - 1) // 12, month=(p - 1) % 12 + 1, day=1) for p in mens["Periodo"]]
    return mens[["Periodo", "Fecha", "EUR", "Uds"]], fuente


def comparativa_interanual(mens):
    """Ultimos 12 meses frente a los 12 anteriores, mes a mes. Devuelve (tabla, resumen)."""
    if mens is None or mens.empty:
        return pd.DataFrame(columns=["Mes", "Actual", "Anterior"]), {}
    por_periodo = mens.set_index("Periodo")["EUR"]
    pmax = int(mens["Periodo"].max())
    filas = []
    for p in range(pmax - 11, pmax + 1):
        filas.append({"Mes": f"{MESES_ES[(p - 1) % 12]} {str((p - 1) // 12)[2:]}", "Actual": por_periodo.get(p, np.nan),
                      "Anterior": por_periodo.get(p - 12, np.nan)})
    tabla = pd.DataFrame(filas)
    comparables = tabla.dropna(subset=["Actual", "Anterior"])
    act, ant = float(comparables["Actual"].sum()), float(comparables["Anterior"].sum())
    resumen = {"total_12m": float(tabla["Actual"].sum(skipna=True)), "meses_comparables": len(comparables),
               "var_pct": (act / ant - 1) * 100 if ant > 0 else None}
    if len(comparables):
        dif = (comparables["Actual"] / comparables["Anterior"].where(comparables["Anterior"] > 0) - 1) * 100
        if dif.notna().any():
            resumen["mejor_mes"] = (comparables.loc[dif.idxmax(), "Mes"], float(dif.max()))
            resumen["peor_mes"] = (comparables.loc[dif.idxmin(), "Mes"], float(dif.min()))
    return tabla, resumen


# ---------------------------------------------------------------------------
# Compras
# ---------------------------------------------------------------------------
COLS_COMPRAS = ["Fecha", COL_LAB, COL_CN, "Unidades", COL_PVL, "Descuento", "Importe", "Origen"]


def normalizar_compras(df_raw, df_inv=None, origen="Excel"):
    """Excel/CSV de pedidos o albaranes -> tabla de compras. Devuelve (df, {campo: columna encontrada}).

    Obligatorias: fecha, codigo nacional y unidades. Precio, descuento, importe y laboratorio
    son opcionales: lo que falte se completa con el inventario (PVL y laboratorio) o se deja a 0.
    """
    encontrado = {k: columna(df_raw, c) for k, c in (("Fecha", "fecha"), ("Codigo_Nacional", "cn"), ("Unidades", "unidades"),
                                                     ("PVL", "pvl"), ("Descuento", "descuento"), ("Importe", "importe_compra"),
                                                     ("Laboratorio", "laboratorio"))}
    if not (encontrado["Fecha"] and encontrado["Codigo_Nacional"] and encontrado["Unidades"]):
        return pd.DataFrame(columns=COLS_COMPRAS), encontrado
    df = pd.DataFrame({"Fecha": pd.to_datetime(df_raw[encontrado["Fecha"]], errors="coerce", dayfirst=True),
                       COL_CN: normalizar_cn(df_raw[encontrado["Codigo_Nacional"]]),
                       "Unidades": _num(df_raw[encontrado["Unidades"]])})
    df[COL_PVL] = _num(df_raw[encontrado["PVL"]]) if encontrado["PVL"] else np.nan
    dto = _num(df_raw[encontrado["Descuento"]]).fillna(0) if encontrado["Descuento"] else 0.0
    df["Descuento"] = np.where(dto > 1, dto / 100.0, dto)
    df[COL_LAB] = np.nan
    if encontrado["Laboratorio"]:
        lab = df_raw[encontrado["Laboratorio"]]
        df[COL_LAB] = lab.astype(str).str.strip().where(lab.notna() & ~lab.astype(str).str.strip().str.lower().isin(["", "nan", "none"]))
    if df_inv is not None and not df_inv.empty:
        inv = df_inv.assign(**{COL_CN: normalizar_cn(df_inv[COL_CN])}).drop_duplicates(COL_CN).set_index(COL_CN)
        if COL_PVL in inv.columns:
            df[COL_PVL] = df[COL_PVL].fillna(df[COL_CN].map(_num(inv[COL_PVL])))
        if COL_LAB in inv.columns:
            df[COL_LAB] = df[COL_LAB].fillna(df[COL_CN].map(inv[COL_LAB]))
    df[COL_PVL] = df[COL_PVL].fillna(0.0)
    df[COL_LAB] = df[COL_LAB].fillna("Sin laboratorio").astype(str)
    calculado = df["Unidades"] * df[COL_PVL] * (1 - df["Descuento"])
    df["Importe"] = _num(df_raw[encontrado["Importe"]]).fillna(calculado) if encontrado["Importe"] else calculado
    df["Origen"] = origen
    df = df.dropna(subset=["Fecha", "Unidades"])
    df = df[(df[COL_CN] != "") & (df["Unidades"] > 0)]
    return df[COLS_COMPRAS].reset_index(drop=True), encontrado


def compras_desde_pedidos(pedidos):
    """Pedidos confirmados en la herramienta (historico_pedidos.json) con el formato de compras."""
    filas = []
    for ped in pedidos or []:
        for pr in ped.get("productos", []):
            try:
                uds, pvl, dto = float(pr.get("cantidad", 0)), float(pr.get("pvl", 0)), float(pr.get("descuento", 0))
            except (TypeError, ValueError):
                continue
            if uds <= 0:
                continue
            filas.append({"Fecha": pd.to_datetime(ped.get("fecha"), errors="coerce"), COL_LAB: str(ped.get("laboratorio", "")),
                          COL_CN: normalizar_cn(pr.get("cn")), "Unidades": uds, COL_PVL: pvl, "Descuento": dto,
                          "Importe": float(pr.get("coste", uds * pvl * (1 - dto))), "Origen": "Pedido SmartPharma"})
    df = pd.DataFrame(filas, columns=COLS_COMPRAS)
    return df.dropna(subset=["Fecha"]).reset_index(drop=True)


def unir_compras(*tablas):
    validas = [t[COLS_COMPRAS] for t in tablas if t is not None and not t.empty]
    if not validas:
        return pd.DataFrame(columns=COLS_COMPRAS)
    df = pd.concat(validas, ignore_index=True)
    df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce")
    return df.drop_duplicates(["Fecha", COL_CN, "Unidades", COL_PVL, "Descuento"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Descuentos aprovechados y perdidos
# ---------------------------------------------------------------------------
def analizar_descuentos(compras, df_ofertas=None, base=None):
    """(resumen por laboratorio, lineas con descuento perdido o None si no hay ofertas cargadas).

    Perdido, por linea de compra con oferta:
      - 'Descuento no aplicado': la cantidad daba derecho a un tramo mayor que el descuento recibido.
      - 'A un paso del tramo': faltaba menos del 20 % para el tramo siguiente.
    """
    cols_lab = [COL_LAB, "Lineas", "Bruto_EUR", "Ahorro_EUR", "Dto_Medio_Pct", "Perdido_EUR"]
    if compras is None or compras.empty:
        return pd.DataFrame(columns=cols_lab), None
    df = compras.copy()
    df["Bruto_EUR"] = df["Unidades"] * df[COL_PVL]
    df["Ahorro_EUR"] = df["Bruto_EUR"] * df["Descuento"]
    perdidos = None
    if df_ofertas is not None and not df_ofertas.empty and "Oferta_Nombre" in df_ofertas.columns and base is not None and not base.empty:
        indice = construir_indice_ofertas(df_ofertas)
        info = base.drop_duplicates(COL_CN).set_index(COL_CN)
        mol = info[COL_MOLECULA] if COL_MOLECULA in info.columns else pd.Series("", index=info.index)
        cache, filas = {}, []
        for r in df.to_dict("records"):
            cn = r[COL_CN]
            if cn not in info.index:
                continue
            if cn not in cache:
                oferta = buscar_oferta_por_indice(str(info.at[cn, COL_NOMBRE]), str(mol.get(cn, "")), indice, df_ofertas)
                cache[cn] = sorted(_tiers_de_oferta(oferta), key=lambda t: t["min"]) if oferta is not None else []
            tiers = cache[cn]
            if not tiers:
                continue
            uds, dto_real = r["Unidades"], r["Descuento"]
            ganado = max([float(t["dto"]) for t in tiers if uds >= t["min"]], default=0.0)
            siguiente = next((t for t in tiers if uds < t["min"]), None)
            comun = {"Fecha": r["Fecha"], COL_LAB: r[COL_LAB], COL_CN: cn, COL_NOMBRE: info.at[cn, COL_NOMBRE], "Unidades": uds,
                     "Dto_Recibido_Pct": round(dto_real * 100, 1)}
            if ganado - dto_real > 0.001:
                filas.append({**comun, "Motivo": "Descuento no aplicado", "Dto_Posible_Pct": round(ganado * 100, 1), "Faltaban_Uds": 0,
                              "Perdido_EUR": round(r["Bruto_EUR"] * (ganado - dto_real), 2)})
            elif siguiente and uds >= 0.8 * siguiente["min"] and float(siguiente["dto"]) > max(dto_real, ganado):
                filas.append({**comun, "Motivo": "A un paso del tramo", "Dto_Posible_Pct": round(float(siguiente["dto"]) * 100, 1),
                              "Faltaban_Uds": int(siguiente["min"] - uds),
                              "Perdido_EUR": round(r["Bruto_EUR"] * (float(siguiente["dto"]) - max(dto_real, ganado)), 2)})
        perdidos = pd.DataFrame(filas, columns=["Fecha", COL_LAB, COL_CN, COL_NOMBRE, "Unidades", "Dto_Recibido_Pct", "Motivo",
                                                "Dto_Posible_Pct", "Faltaban_Uds", "Perdido_EUR"])
        perdidos = perdidos.sort_values("Perdido_EUR", ascending=False).reset_index(drop=True)
    por_lab = df.groupby(COL_LAB).agg(Lineas=(COL_CN, "count"), Bruto_EUR=("Bruto_EUR", "sum"), Ahorro_EUR=("Ahorro_EUR", "sum")).reset_index()
    por_lab["Dto_Medio_Pct"] = np.where(por_lab["Bruto_EUR"] > 0, por_lab["Ahorro_EUR"] / por_lab["Bruto_EUR"].where(por_lab["Bruto_EUR"] > 0) * 100, 0.0)
    por_lab["Perdido_EUR"] = por_lab[COL_LAB].map(perdidos.groupby(COL_LAB)["Perdido_EUR"].sum()).fillna(0.0) if perdidos is not None and not perdidos.empty else 0.0
    return por_lab.round(2).sort_values("Bruto_EUR", ascending=False).reset_index(drop=True)[cols_lab], perdidos


# ---------------------------------------------------------------------------
# Laboratorios
# ---------------------------------------------------------------------------
def resumen_laboratorios(base, compras=None, params=None):
    """Una fila por laboratorio: lo que hay en stock, lo que rota, lo que sobra y lo que se le compra."""
    if base is None or base.empty:
        return pd.DataFrame()
    b = base.copy()
    b["Venta_12m_Coste"] = b["Venta_12m_Uds"] * b["Coste_Unit"]
    b["Margen_12m"] = b["Importe_12m"] - b["Venta_12m_Coste"]
    b["Zombie_"] = np.where(b["Estado"] == "Zombie", b["Exceso_EUR"], 0.0)
    b["UVI_"] = np.where(b["Estado"] == "UVI", b["Exceso_EUR"], 0.0)
    b["Sobre_"] = np.where(b["Estado"] == "Sobrestock", b["Exceso_EUR"], 0.0)
    b["Cad6_"] = np.where(b["Fecha_Caducidad_"].notna() & (b["Meses_Hasta_Cad"] <= 6), b["Valor_Stock_EUR"], 0.0)
    b["Rot_"] = (b["Estado"] == "Rotura").astype(int)
    lab = b.groupby(COL_LAB).agg(
        Referencias=(COL_CN, "count"), Stock_EUR=("Valor_Stock_EUR", "sum"), Venta_12m_Uds=("Venta_12m_Uds", "sum"),
        Venta_12m_Coste_EUR=("Venta_12m_Coste", "sum"), Venta_12m_PVP_EUR=("Importe_12m", lambda s: s.sum(min_count=1)),
        Margen_12m_EUR=("Margen_12m", lambda s: s.sum(min_count=1)), Zombie_EUR=("Zombie_", "sum"), UVI_EUR=("UVI_", "sum"),
        Sobrestock_EUR=("Sobre_", "sum"), Roturas=("Rot_", "sum"), Venta_Perdida_Mes_EUR=("Venta_Perdida_Mes_EUR", "sum"),
        Caduca_6m_EUR=("Cad6_", "sum")).reset_index()
    lab["Rotacion_Anual"] = np.where(lab["Stock_EUR"] > 0, lab["Venta_12m_Coste_EUR"] / lab["Stock_EUR"].where(lab["Stock_EUR"] > 0), np.nan)
    lab["Margen_Pct"] = np.where(lab["Venta_12m_PVP_EUR"] > 0, lab["Margen_12m_EUR"] / lab["Venta_12m_PVP_EUR"].where(lab["Venta_12m_PVP_EUR"] > 0) * 100, np.nan)
    lab["Margen_por_EUR_Stock"] = np.where(lab["Stock_EUR"] > 0, lab["Margen_12m_EUR"] / lab["Stock_EUR"].where(lab["Stock_EUR"] > 0), np.nan)
    lab["Capital_Parado_EUR"] = lab["Zombie_EUR"] + lab["UVI_EUR"] + lab["Sobrestock_EUR"]
    lab["Compras_12m_EUR"], lab["Dto_Medio_Pct"] = 0.0, np.nan
    if compras is not None and not compras.empty:
        ref = fecha_referencia(params or {})
        c = compras[compras["Fecha"] > ref - pd.DateOffset(months=12)].copy()
        if not c.empty:
            c["Bruto"] = c["Unidades"] * c[COL_PVL]
            c["Aho"] = c["Bruto"] * c["Descuento"]
            g = c.groupby(COL_LAB)[["Importe", "Bruto", "Aho"]].sum()
            lab["Compras_12m_EUR"] = lab[COL_LAB].map(g["Importe"]).fillna(0.0)
            lab["Dto_Medio_Pct"] = lab[COL_LAB].map(g["Aho"] / g["Bruto"].where(g["Bruto"] > 0) * 100)
    return lab.round(2).sort_values("Stock_EUR", ascending=False).reset_index(drop=True)


def _eur(x):
    return f"{x:,.0f}".replace(",", ".") + " €"


def argumentos_negociacion(fila, labs):
    """Frases para sentarse con el delegado, a partir de la fila del laboratorio y de la tabla de todos."""
    args = []
    total_stock = float(labs["Stock_EUR"].sum())
    total_venta = float(labs["Venta_12m_Coste_EUR"].sum())
    rot_media = total_venta / total_stock if total_stock > 0 else None
    if total_stock > 0 and fila["Stock_EUR"] > 0:
        peso_stock = fila["Stock_EUR"] / total_stock * 100
        peso_venta = fila["Venta_12m_Coste_EUR"] / total_venta * 100 if total_venta > 0 else 0
        if peso_stock - peso_venta >= 3:
            args.append(f"Ocupa el {peso_stock:.0f} % de tu stock pero solo aporta el {peso_venta:.0f} % de tus ventas.")
        elif peso_venta - peso_stock >= 3:
            args.append(f"Aporta el {peso_venta:.0f} % de tus ventas con solo el {peso_stock:.0f} % de tu stock: es un laboratorio rentable para ti.")
    if rot_media and pd.notna(fila["Rotacion_Anual"]):
        comp = "por debajo de" if fila["Rotacion_Anual"] < rot_media else "por encima de"
        args.append(f"Su stock rota {fila['Rotacion_Anual']:.1f} veces al año, {comp} la media de la farmacia ({rot_media:.1f}).")
    if fila["Zombie_EUR"] > 0:
        args.append(f"Tienes {_eur(fila['Zombie_EUR'])} de sus productos sin una sola venta en 12 meses: pide abono, cambio o devolución.")
    if fila["Sobrestock_EUR"] + fila["UVI_EUR"] > 0:
        args.append(f"Además hay {_eur(fila['Sobrestock_EUR'] + fila['UVI_EUR'])} por encima del stock objetivo: no aceptes pedidos mínimos hasta bajarlo.")
    if fila["Caduca_6m_EUR"] > 0:
        args.append(f"{_eur(fila['Caduca_6m_EUR'])} caducan en menos de 6 meses.")
    if fila["Roturas"] > 0:
        args.append(f"{int(fila['Roturas'])} referencia(s) en rotura: {_eur(fila['Venta_Perdida_Mes_EUR'])} de venta perdida al mes.")
    if pd.notna(fila["Dto_Medio_Pct"]) and fila["Compras_12m_EUR"] > 0:
        args.append(f"Le has comprado {_eur(fila['Compras_12m_EUR'])} en 12 meses con un descuento medio del {fila['Dto_Medio_Pct']:.1f} %.")
    if pd.notna(fila["Margen_Pct"]):
        args.append(f"Margen del {fila['Margen_Pct']:.1f} % sobre venta ({_eur(fila['Margen_12m_EUR'])} en 12 meses).")
    return args


# ---------------------------------------------------------------------------
# Roturas recurrentes
# ---------------------------------------------------------------------------
def roturas_recurrentes(hist, base, fotos=None, params=None):
    """Productos habituales que se quedan sin stock una y otra vez. Devuelve (tabla, texto del periodo usado).

    Dos pruebas:
      - Fotos de inventario: cuantas veces aparecia con stock 0 (prueba directa).
      - Huecos de venta: periodos sin ninguna venta en un producto que vende lo bastante
        (media >= `rotura_min_ventas_periodo`) como para que el hueco no sea casualidad.
        Periodo = 14 dias si el historico es diario/semanal, o el mes si es mensual.
    Los ceros al final solo cuentan si son 1 o 2 periodos: mas es un producto que se dejo de vender.
    """
    params = completar_parametros(params)
    cols = [COL_CN, COL_NOMBRE, COL_LAB, COL_STOCK, "Media_Periodo_Uds", "Periodos_Sin_Venta", "Fotos_Sin_Stock", "Fotos",
            "Veces", "Evidencia", "Uds_Perdidas_Est", "EUR_Perdido_Est"]
    if hist is None or hist.empty:
        return pd.DataFrame(columns=cols), ""
    fechas = np.sort(hist["Fecha"].dt.normalize().unique())
    paso = np.median(np.diff(fechas).astype("timedelta64[D]").astype(int)) if len(fechas) > 1 else 30
    if paso < 20:
        origen = pd.Timestamp(fechas[0])
        idx = ((hist["Fecha"] - origen).dt.days // 14).astype(int)
        periodo_txt = "quincena (14 días)"
    else:
        idx = hist["Periodo"] - hist["Periodo"].min()
        periodo_txt = "mes"
    n_per = int(idx.max()) + 1
    mat = hist.assign(_p=idx).groupby(["_p", COL_CN])["Uds"].sum().unstack(COL_CN).reindex(range(n_per)).fillna(0)
    con_venta = mat > 0
    n_con = con_venta.sum()
    pos = np.arange(n_per)[:, None]
    primero = np.where(con_venta.to_numpy(), pos, n_per).min(axis=0)
    ultimo = np.where(con_venta.to_numpy(), pos, -1).max(axis=0)
    activos = ultimo - primero + 1
    huecos = activos - n_con.to_numpy()
    cola = (n_per - 1) - ultimo
    huecos = huecos + np.where((cola >= 1) & (cola <= 2), cola, 0)
    media = np.where(n_con.to_numpy() > 0, mat.sum().to_numpy() / np.maximum(n_con.to_numpy(), 1), 0.0)
    res = pd.DataFrame({COL_CN: mat.columns, "Media_Periodo_Uds": media, "Periodos_Sin_Venta": huecos})
    res.loc[res["Media_Periodo_Uds"] < float(params["rotura_min_ventas_periodo"]), "Periodos_Sin_Venta"] = 0

    res["Fotos_Sin_Stock"], res["Fotos"] = 0, 0
    if fotos is not None and not fotos.empty:
        f = fotos.assign(**{COL_CN: normalizar_cn(fotos[COL_CN])})
        g = f.groupby(COL_CN).agg(Fotos=("Fecha", "nunique"), Cero=(COL_STOCK, lambda s: int((s <= 0).sum())))
        res["Fotos"] = res[COL_CN].map(g["Fotos"]).fillna(0).astype(int)
        res["Fotos_Sin_Stock"] = res[COL_CN].map(g["Cero"]).fillna(0).astype(int)
        # para las fotos basta con que sea un producto habitual: al menos 1 ud por periodo contando los periodos a cero
        habitual = pd.Series(mat.sum().to_numpy() / np.maximum(activos, 1), index=res.index) >= 1
        res.loc[~habitual, "Fotos_Sin_Stock"] = 0
    res["Veces"] = res["Periodos_Sin_Venta"] + res["Fotos_Sin_Stock"]
    res = res[res["Veces"] >= 2].copy()
    if res.empty:
        return pd.DataFrame(columns=cols), periodo_txt
    res["Evidencia"] = np.where(res["Fotos_Sin_Stock"] >= 2, "Confirmada (inventarios)",
                                np.where(res["Fotos_Sin_Stock"] >= 1, "Probable (inventario + huecos)", "Probable (huecos de venta)"))
    info = base.drop_duplicates(COL_CN).set_index(COL_CN) if base is not None and not base.empty else pd.DataFrame()
    for c, defecto in ((COL_NOMBRE, "(no está en el inventario)"), (COL_LAB, ""), (COL_STOCK, 0)):
        res[c] = res[COL_CN].map(info[c]) if c in info.columns else defecto
        res[c] = res[c].fillna(defecto)
    valor = pd.Series(0.0, index=res.index)
    if not info.empty:
        valor = res[COL_CN].map(info["PVP_Neto_Unit"].where(info["PVP_Neto_Unit"].notna(), info[COL_PVL])).fillna(0.0)
    res["Uds_Perdidas_Est"] = (res["Periodos_Sin_Venta"] * res["Media_Periodo_Uds"]).round(0)
    res["EUR_Perdido_Est"] = (res["Uds_Perdidas_Est"] * valor).round(2)
    res["Media_Periodo_Uds"] = res["Media_Periodo_Uds"].round(1)
    return res.sort_values(["EUR_Perdido_Est", "Veces"], ascending=False)[cols].reset_index(drop=True), periodo_txt


# ---------------------------------------------------------------------------
# Fecha y calidad de los datos
# ---------------------------------------------------------------------------
def calidad_datos(df_inv, hist, params, compras=None, hoy=None):
    """Sello de los datos: de cuando son, cuanto historial hay y que les falta."""
    hoy = pd.Timestamp(hoy or pd.Timestamp.now().normalize())
    q = {"fecha_inventario": pd.Timestamp(params["fecha_inventario"]) if params.get("fecha_inventario") else None,
         "n_refs": len(df_inv), "avisos": []}
    cn = normalizar_cn(df_inv[COL_CN])
    stock = _num(df_inv[COL_STOCK]).fillna(0) if COL_STOCK in df_inv.columns else pd.Series(0, index=df_inv.index)
    pvl = _num(df_inv[COL_PVL]) if COL_PVL in df_inv.columns else pd.Series(np.nan, index=df_inv.index)
    q["sin_pvl"] = int(((pvl.isna() | (pvl <= 0)) & (stock > 0)).sum())
    q["sin_laboratorio"] = int(df_inv[COL_LAB].isna().sum()) if COL_LAB in df_inv.columns else len(df_inv)
    q["stock_negativo"] = int((stock < 0).sum())
    q["cn_duplicados"] = int(cn.duplicated().sum())
    c_cad = columna(df_inv, "caducidad")
    q["pct_caducidad"] = round(float(pd.to_datetime(df_inv[c_cad], errors="coerce", dayfirst=True).notna().mean() * 100), 0) if c_cad else None
    q["tiene_pvp"] = bool(hist is not None and not hist.empty and hist["Importe_Neto"].notna().any()) or columna(df_inv, "pvp") is not None
    q["tiene_ubicacion"] = columna(df_inv, "ubicacion") is not None
    q["n_compras"] = 0 if compras is None else len(compras)
    if hist is not None and not hist.empty:
        q["hist_desde"], q["hist_hasta"] = hist["Fecha"].min(), hist["Fecha"].max()
        q["meses_hist"] = int(hist["Periodo"].max() - hist["Periodo"].min() + 1)
        ult12 = hist[(hist["Periodo"] > hist["Periodo"].max() - 12) & (hist["Uds"] > 0)]
        q["ventas_sin_inventario"] = int(len(set(ult12[COL_CN]) - set(cn)))
    else:
        q["hist_desde"] = q["hist_hasta"] = None
        q["meses_hist"], q["ventas_sin_inventario"] = 0, 0

    av, lim = q["avisos"], int(params.get("dias_aviso_datos", 45))
    if q["fecha_inventario"] is None:
        av.append("La fecha del inventario está sin confirmar (Configuración → A. Archivos Base). Caducidades y plazos de devolución se calculan respecto a hoy.")
    else:
        q["dias_inventario"] = int((hoy - q["fecha_inventario"]).days)
        if q["dias_inventario"] > lim:
            av.append(f"El inventario tiene {q['dias_inventario']} días: las cifras describen la farmacia de entonces, no la de hoy.")
        if q["hist_hasta"] is not None:
            desfase = int((q["fecha_inventario"] - q["hist_hasta"]).days)
            if desfase > lim + 31:
                av.append(f"Las ventas acaban el {q['hist_hasta']:%d/%m/%Y}, {desfase} días antes del inventario: faltan ventas recientes.")
            elif desfase < -31:
                av.append(f"Hay ventas posteriores a la fecha del inventario (hasta el {q['hist_hasta']:%d/%m/%Y}): revisa la fecha.")
    if 0 < q["meses_hist"] < 24:
        av.append(f"Solo hay {q['meses_hist']} meses de ventas: la tendencia y la comparativa interanual necesitan 24.")
    if q["sin_pvl"]:
        av.append(f"{q['sin_pvl']} producto(s) con stock y sin PVL: su valor cuenta como 0 €.")
    if q["stock_negativo"]:
        av.append(f"{q['stock_negativo']} producto(s) con stock negativo en el ERP (se tratan como 0).")
    if q["cn_duplicados"]:
        av.append(f"{q['cn_duplicados']} código(s) nacional(es) repetidos en el inventario.")
    if q["ventas_sin_inventario"]:
        av.append(f"{q['ventas_sin_inventario']} producto(s) vendidos en los últimos 12 meses no aparecen en el inventario.")
    return q


# ---------------------------------------------------------------------------
# Listas de trabajo
# ---------------------------------------------------------------------------
def listas_trabajo(base, plan, caducidades, roturas_rec, orden="Laboratorio"):
    """Hojas completas (sin recortes) para exportar. `orden`: Laboratorio, Ubicación o Euros."""
    def ordenar(df, col_eur):
        if df.empty:
            return df
        if orden == "Ubicación" and "Ubicacion" in df.columns and (df["Ubicacion"] != "").any():
            return df.sort_values(["Ubicacion", COL_NOMBRE])
        if orden == "Laboratorio" and COL_LAB in df.columns:
            return df.sort_values([COL_LAB, col_eur], ascending=[True, False])
        return df.sort_values(col_eur, ascending=False)

    hojas = {}
    if plan is not None and not plan.empty:
        for bloque, col in (("Liberar capital", "EUR_Recuperable"), ("Recuperar ventas", "Venta_Perdida_Mes_EUR")):
            parte = plan[plan["Bloque"] == bloque].drop(columns=["Bloque"])
            if not parte.empty:
                hojas[f"Plan - {bloque}"] = ordenar(parte, col)
    if base is not None and not base.empty:
        cols = [COL_CN, COL_NOMBRE, COL_LAB, "Ubicacion", COL_STOCK, "Venta_Media_Mensual", "Venta_12m_Uds", "Stock_Objetivo",
                "Exceso_Uds", "Coste_Unit", "Valor_Stock_EUR", "Exceso_EUR", "Ultima_Venta", "Ultima_Compra"]
        for estado in ("Zombie", "UVI", "Sobrestock"):
            parte = base[base["Estado"] == estado][cols]
            if not parte.empty:
                hojas[estado] = ordenar(parte, "Exceso_EUR")
        rot = base[base["Estado"] == "Rotura"][[COL_CN, COL_NOMBRE, COL_LAB, "Ubicacion", "Venta_Media_Mensual", "Stock_Objetivo",
                                                 "Coste_Unit", "Venta_Perdida_Mes_EUR"]]
        if not rot.empty:
            hojas["Roturas"] = ordenar(rot, "Venta_Perdida_Mes_EUR")
    if caducidades is not None and not caducidades.empty:
        hojas["Caducidades"] = caducidades
    if roturas_rec is not None and not roturas_rec.empty:
        hojas["Roturas recurrentes"] = roturas_rec
    if not (base is not None and not base.empty and (base["Ubicacion"] != "").any()):
        hojas = {k: v.drop(columns=["Ubicacion"], errors="ignore") for k, v in hojas.items()}
    return hojas
