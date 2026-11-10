import json
import pandas as pd
import numpy as np
import streamlit as st
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from calendar import monthrange
from data.io import cargar_json_farmacia, guardar_json_farmacia
from utils.helpers import normalizar_cn
from config.settings import (
    HEALTH_SCORE_MESES_DEFAULT, BASE_DIR, COL_CN, COL_STOCK, COL_NOMBRE, COL_PVL,
    COL_VENTAS, COL_FECHA, COL_MOLECULA, COL_LAB
)

def heuristica_tipo_producto(cn, molecula=""):
    """Clasifica como Medicamento o Parafarmacia evaluando C.N., EAN y la familia."""
    mol_str = str(molecula).strip().lower()
    if any(k in mol_str for k in ["parafarmacia", "cosmetica", "dietetica", "higiene", "ortopedia"]):
        return "Parafarmacia"
    cn_str = str(cn).strip()
    if not cn_str or cn_str.lower() in ["nan", "none"]:
        return "Parafarmacia"
    if "847000" in cn_str:
        return "Medicamento"
    if len(cn_str) >= 12:
        return "Parafarmacia"
    if cn_str[0] in ['6', '7', '8', '9']:
        return "Medicamento"
    return "Parafarmacia"

def asignar_grupo_surtido(nombre, molecula, reglas_list):
    nom_lower = str(nombre).lower()
    for regla in reglas_list:
        if not regla: continue
        partes = [p.strip() for p in regla.split(",") if p.strip()]
        if partes and all(p in nom_lower for p in partes):
            return regla
    mol_str = str(molecula).strip()
    if pd.isna(molecula) or mol_str.lower() in ["parafarmacia", "otros", "varios", "desconocido", "", "-", "cosmetica", "higiene", "dietetica", "infantil"]:
        return str(nombre).strip()
    return mol_str

def registrar_snapshot_kpi(health_score, n_zombies, valor_zombie, n_roturas, ahorro_pedido=0, coste_pedido=0):
    historico = cargar_json_farmacia("historico_kpi.json", default=[])
    historico.append({
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "health_score": health_score, "n_zombies": n_zombies,
        "valor_zombie": round(valor_zombie, 2), "n_roturas": n_roturas,
        "ahorro_pedido": round(ahorro_pedido, 2), "coste_pedido": round(coste_pedido, 2),
    })
    guardar_json_farmacia("historico_kpi.json", historico)
    return historico

def obtener_historico_kpi():
    historico = cargar_json_farmacia("historico_kpi.json", default=[])
    if not historico:
        return pd.DataFrame()
    df = pd.DataFrame(historico)
    df["fecha"] = pd.to_datetime(df["fecha"])
    return df

def cargar_reglas_surtido():
    return cargar_json_farmacia("reglas_surtido.json", default=[])
def guardar_reglas_surtido(reglas):
    guardar_json_farmacia("reglas_surtido.json", reglas)
def _normalizar_protegidos(protegidos):
    res = []
    for pp in protegidos or []:
        pp = dict(pp)
        pp["codigo_nacional"] = normalizar_cn(pp.get("codigo_nacional"))
        if pp["codigo_nacional"]:
            res.append(pp)
    return res
def cargar_productos_protegidos():
    return _normalizar_protegidos(cargar_json_farmacia("productos_protegidos.json", default=[]))
def guardar_productos_protegidos(protegidos):
    guardar_json_farmacia("productos_protegidos.json", _normalizar_protegidos(protegidos))

def registrar_snapshot_auditoria(df_inventario, df_ventas_media):
    df = df_inventario.merge(df_ventas_media, on=COL_CN, how="left")
    df["Venta_Media_Mensual"] = df["Venta_Media_Mensual"].fillna(0)

    # Misma definicion que BI/Auditoria: stock > 0 y 12 meses sin ventas.
    df_hist = st.session_state.get("historico")
    if df_hist is not None and not df_hist.empty:
        zombies = df[df[COL_CN].isin(calcular_stock_zombie(df_inventario, df_hist)[COL_CN])]
    else:
        zombies = df[(df[COL_STOCK] > 0) & (df["Venta_Media_Mensual"] == 0)]
    valor_zombie_total = round(float((zombies[COL_STOCK] * zombies.get(COL_PVL, pd.Series(0, index=zombies.index))).fillna(0).sum()), 2)
    zombie_list = []
    for _, r in zombies.head(30).iterrows():
        val = float(r[COL_STOCK]) * float(r.get(COL_PVL, 0))
        zombie_list.append({"cn": r[COL_CN], "nombre": str(r.get(COL_NOMBRE, ""))[:50], "valor": round(val, 2)})

    roturas = df[(df[COL_STOCK] == 0) & (df["Venta_Media_Mensual"] > 0)]
    rotura_list = [{"cn": r[COL_CN], "nombre": str(r.get(COL_NOMBRE, ""))[:50],
                    "venta_media": round(float(r["Venta_Media_Mensual"]), 1)}
                   for _, r in roturas.head(20).iterrows()]

    valor_sobrestock, df_exceso = calcular_sobrestock(df_inventario, df_ventas_media, excluir_cns=zombies[COL_CN])
    sobr = df_exceso.nlargest(20, "Valor_Exceso")
    sobrestock_list = [{"cn": r[COL_CN], "nombre": str(r.get(COL_NOMBRE, ""))[:50],
                        "exceso": int(r["Exceso"]), "valor": round(float(r["Valor_Exceso"]), 2)}
                       for _, r in sobr.iterrows()]

    snapshot = {
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "n_productos": len(df_inventario),
        "n_zombies": len(zombies),
        "valor_zombie": valor_zombie_total,
        "n_roturas": len(roturas),
        "valor_sobrestock": valor_sobrestock,
        "zombies": zombie_list,
        "roturas": rotura_list,
        "sobrestock": sobrestock_list,
    }

    historico = cargar_json_farmacia("historico_auditorias.json", default=[])
    historico.append(snapshot)
    if len(historico) > 24:
        historico = historico[-24:]
    guardar_json_farmacia("historico_auditorias.json", historico)
    return snapshot

def obtener_historico_auditorias():
    return cargar_json_farmacia("historico_auditorias.json", default=[])

def cargar_perfil_farmacia():
    return cargar_json_farmacia("perfil_farmacia.json", default={
        "centro_salud": False, "residencia": False, "colegio": False,
        "zona_turistica": False, "zona_rural": False,
        "epi_gripe": 0, "epi_alergias": 0, "epi_covid": 0,
    })

def guardar_perfil_farmacia(perfil):
    guardar_json_farmacia("perfil_farmacia.json", perfil)

def cargar_calendario_farmacia():
    return cargar_json_farmacia("calendario_farmacia.json", default={
        "horario": {
            "lunes": {"abre": True, "apertura": "09:30", "cierre": "21:00"},
            "martes": {"abre": True, "apertura": "09:30", "cierre": "21:00"},
            "miercoles": {"abre": True, "apertura": "09:30", "cierre": "21:00"},
            "jueves": {"abre": True, "apertura": "09:30", "cierre": "21:00"},
            "viernes": {"abre": True, "apertura": "09:30", "cierre": "21:00"},
            "sabado": {"abre": True, "apertura": "10:00", "cierre": "14:00"},
            "domingo": {"abre": False, "apertura": "00:00", "cierre": "00:00"},
        },
        "festivos": [],
        "excepciones_abiertas": [],
    })

def guardar_calendario_farmacia(calendario):
    guardar_json_farmacia("calendario_farmacia.json", calendario)

def _dia_abre(d, horario, festivos_str, excepciones_str):
    dias_semana_es = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
    d_str = d.strftime("%d/%m/%Y")
    dia_semana = dias_semana_es[d.weekday()]
    config_dia = horario.get(dia_semana, {"abre": False})
    es_festivo = d_str in festivos_str
    es_excepcion = d_str in excepciones_str
    if es_excepcion:
        return True, config_dia
    elif es_festivo:
        return False, config_dia
    else:
        return config_dia.get("abre", False), config_dia

def calcular_horas_mes(anio, mes, calendario):
    horario = calendario.get("horario", {})
    festivos_str = set(calendario.get("festivos", []))
    excepciones_str = set(calendario.get("excepciones_abiertas", []))
    total_dias = monthrange(anio, mes)[1]
    horas_total = 0.0
    for dia in range(1, total_dias + 1):
        try:
            d = date(anio, mes, dia)
        except ValueError:
            continue
        abre, config_dia = _dia_abre(d, horario, festivos_str, excepciones_str)
        if abre:
            try:
                h_ap = config_dia.get("apertura", "09:30").split(":")
                h_ci = config_dia.get("cierre", "21:00").split(":")
                horas = (int(h_ci[0]) + int(h_ci[1]) / 60) - (int(h_ap[0]) + int(h_ap[1]) / 60)
                horas_total += max(0, horas)
            except (ValueError, IndexError):
                horas_total += 8.0
    return round(horas_total, 1)

def calcular_dias_abiertos_mes(anio, mes, calendario):
    horario = calendario.get("horario", {})
    festivos_str = set(calendario.get("festivos", []))
    excepciones_str = set(calendario.get("excepciones_abiertas", []))
    total_dias = monthrange(anio, mes)[1]
    abiertos = 0
    for dia in range(1, total_dias + 1):
        try:
            d = date(anio, mes, dia)
        except ValueError:
            continue
        abre, _ = _dia_abre(d, horario, festivos_str, excepciones_str)
        if abre:
            abiertos += 1
    return abiertos

def registrar_promociones_pedido(df_pedido):
    if df_pedido is None or df_pedido.empty:
        return
    if "Descuento_Aplicado" not in df_pedido.columns:
        return
    df_promo = df_pedido[df_pedido["Descuento_Aplicado"] > 0].copy()
    if df_promo.empty:
        return
    registros = cargar_json_farmacia("historico_promociones.json", default=[])
    fecha = datetime.now().strftime("%Y-%m-%d")
    for _, row in df_promo.iterrows():
        registros.append({
            "fecha": fecha,
            "codigo_nacional": normalizar_cn(row.get(COL_CN, "")),
            "molecula": row.get(COL_MOLECULA, ""),
            "laboratorio": row.get(COL_LAB, ""),
            "descuento": round(float(row.get("Descuento_Aplicado", 0)), 4),
            "tier": row.get("Tier_Aplicado", ""),
        })
    guardar_json_farmacia("historico_promociones.json", registros)

def obtener_cns_con_promo_historica():
    registros = cargar_json_farmacia("historico_promociones.json", default=[])
    return {normalizar_cn(r["codigo_nacional"]) for r in registros if r.get("codigo_nacional")}

def normalizar_ofertas_dinamico(df_raw, mapping_nombre, mappings_tiers):
    df = df_raw.copy()
    resultados = []
    for _, row in df.iterrows():
        nombre = str(row.get(mapping_nombre, "")).strip()
        if not nombre:
            continue
        tiers = []
        for mt in mappings_tiers:
            col_cant = mt.get("col_cantidad")
            col_dto = mt.get("col_descuento")
            if not col_cant or not col_dto:
                continue
            cant = pd.to_numeric(str(row.get(col_cant, 0)).strip(), errors="coerce")
            dto_raw = str(row.get(col_dto, 0)).replace("%", "").replace(",", ".").strip()
            dto = pd.to_numeric(dto_raw, errors="coerce")
            if pd.isna(cant) or pd.isna(dto) or cant <= 0 or dto <= 0:
                continue
            if dto > 1:
                dto = dto / 100
            tiers.append({"min": int(cant), "dto": float(dto)})
        tiers.sort(key=lambda t: t["min"])
        if tiers:
            resultados.append({"Oferta_Nombre": nombre, "Tiers": tiers})
    return pd.DataFrame(resultados)

def imputar_stockouts(df_ventas, df_inventario):
    df = df_ventas.copy()
    if COL_STOCK not in df_inventario.columns:
        return df
    stock_map = df_inventario.set_index(COL_CN)[COL_STOCK].to_dict()
    cns_sin_stock = {cn for cn, s in stock_map.items() if s == 0}
    if not cns_sin_stock:
        return df
    for cn in cns_sin_stock:
        mask_cn = df[COL_CN] == cn
        df_cn = df[mask_cn].sort_values(COL_FECHA if COL_FECHA in df.columns else COL_CN)
        if COL_VENTAS not in df_cn.columns:
            continue
        ventas = df_cn[COL_VENTAS].values.copy()
        periodos_con_venta = ventas[ventas > 0]
        if len(periodos_con_venta) == 0:
            continue
        media_movil = periodos_con_venta[-7:].mean() if len(periodos_con_venta) >= 7 else periodos_con_venta.mean()
        for i in range(len(ventas) - 1, -1, -1):
            if ventas[i] == 0:
                ventas[i] = max(1, int(round(media_movil)))
            else:
                break
        df.loc[mask_cn, COL_VENTAS] = list(ventas)
    return df

def crecimiento_12m(ventas_por_mes, col_periodo="_periodo"):
    """Crecimiento por producto en cada periodo p: ventas de p-12..p-1 frente a p-24..p-13.

    Solo usa meses anteriores a p (sin mirar el futuro); los meses sin fila cuentan
    como 0. Si el producto no tiene 24 meses de historia antes de p, vale 0.
    Devuelve [COL_CN, col_periodo, "Crecimiento_12m"] desde el primer periodo hasta el ultimo + 1.
    """
    if ventas_por_mes.empty:
        return pd.DataFrame(columns=[COL_CN, col_periodo, "Crecimiento_12m"])
    pmin, pmax = int(ventas_por_mes[col_periodo].min()), int(ventas_por_mes[col_periodo].max())
    ancho = (ventas_por_mes.groupby([col_periodo, COL_CN])[COL_VENTAS].sum()
             .unstack(COL_CN).reindex(range(pmin, pmax + 2)).fillna(0))
    ult12 = ancho.rolling(12, min_periods=12).sum().shift(1)
    prev12 = ult12.shift(12)
    crec = (ult12 / prev12.where(prev12 > 0) - 1).clip(-0.5, 0.5)
    primer = ventas_por_mes.groupby(COL_CN)[col_periodo].min().reindex(crec.columns).to_numpy()
    con_historia = crec.index.to_numpy()[:, None] >= primer[None, :] + 24
    crec = crec.where(con_historia).fillna(0.0).round(4)
    crec.index.name = col_periodo
    crec.columns.name = COL_CN
    return crec.stack(future_stack=True).reset_index(name="Crecimiento_12m")

def fecha_corte():
    """Fecha del inventario confirmada en Configuracion (dia del export del ERP), o None si no se ha indicado.

    Es la referencia de todo lo que mira hacia delante (meses que se preven, caducidades,
    calendario de reposicion). Antes se usaba la fecha de hoy: con los mismos datos las
    cifras cambiaban de un dia a otro. Lo que mira hacia atras (zombie, UVI, tendencia)
    sigue anclado al ultimo dia con ventas del historico.
    """
    f = cargar_json_farmacia("parametros_analisis.json", default={}).get("fecha_inventario")
    return pd.Timestamp(f) if f else None

def calcular_ventas_mensuales(df_ventas, meses_cobertura=2, fecha_ref=None):
    """`fecha_ref`: dia desde el que se cuentan los meses a prever (por defecto, hoy)."""
    df = df_ventas.copy()
    if COL_FECHA not in df.columns:
        agg = df.groupby(COL_CN)[COL_VENTAS].agg(["sum", "std"]).reset_index()
        agg.columns = [COL_CN, "total", "std_raw"]
        agg["Venta_Media_Mensual"] = agg["total"] / 12
        agg["Venta_Std_Mensual"] = agg["std_raw"].fillna(0) / np.sqrt(12)
        agg["Factor_Tendencia"] = 0.0
        return agg[[COL_CN, "Venta_Media_Mensual", "Venta_Std_Mensual", "Factor_Tendencia"]]

    df[COL_FECHA] = pd.to_datetime(df[COL_FECHA], errors="coerce", dayfirst=True)
    df = df.dropna(subset=[COL_FECHA])
    df["Anio"] = df[COL_FECHA].dt.year
    df["Mes_Cal"] = df[COL_FECHA].dt.month
    ventas_por_mes = df.groupby([COL_CN, "Anio", "Mes_Cal"])[COL_VENTAS].sum().reset_index()
    ventas_por_mes["_periodo"] = ventas_por_mes["Anio"] * 12 + ventas_por_mes["Mes_Cal"]
    p_max = ventas_por_mes["_periodo"].max()

    # Tendencia: ultimos 12 meses frente a los 12 anteriores (no anos naturales,
    # que con el ano en curso incompleto daban caidas ficticias).
    crec = crecimiento_12m(ventas_por_mes)
    factor_tendencia = (crec[crec["_periodo"] == p_max + 1][[COL_CN, "Crecimiento_12m"]]
                        .rename(columns={"Crecimiento_12m": "Factor_Tendencia"}))

    hoy = pd.Timestamp(fecha_ref) if fecha_ref is not None else datetime.now()
    meses_futuro = [(hoy + relativedelta(months=m)).month for m in range(1, meses_cobertura+1)]
    # Mirroring: el mismo mes en los ultimos 12 meses de historico (cada mes aparece una vez).
    recientes = ventas_por_mes[ventas_por_mes["_periodo"] > p_max - 12]
    mirror = recientes[recientes["Mes_Cal"].isin(meses_futuro)]
    venta_mirror = mirror.groupby(COL_CN)[COL_VENTAS].mean().reset_index().rename(columns={COL_VENTAS: "Venta_Media_Mensual"}) if not mirror.empty else pd.DataFrame(columns=[COL_CN, "Venta_Media_Mensual"])
    media_global = ventas_por_mes.groupby(COL_CN)[COL_VENTAS].mean().reset_index().rename(columns={COL_VENTAS: "Venta_Media_Global"})
    std_mensual = ventas_por_mes.groupby(COL_CN)[COL_VENTAS].std().fillna(0).reset_index().rename(columns={COL_VENTAS: "Venta_Std_Mensual"})

    vm = media_global.merge(venta_mirror, on=COL_CN, how="left")
    vm["Venta_Media_Mensual"] = vm["Venta_Media_Mensual"].fillna(vm["Venta_Media_Global"])
    vm = vm.drop(columns=["Venta_Media_Global"]).merge(std_mensual, on=COL_CN, how="left").merge(factor_tendencia, on=COL_CN, how="left")
    vm["Venta_Std_Mensual"] = vm["Venta_Std_Mensual"].fillna(0)
    vm["Factor_Tendencia"] = vm["Factor_Tendencia"].fillna(0)
    vm["Venta_Media_Mensual"] = (vm["Venta_Media_Mensual"] * (1 + vm["Factor_Tendencia"])).clip(lower=0)
    return vm

def obtener_ventas_media(meses_cobertura=2):
    df_hist = st.session_state.get("historico")
    if df_hist is None:
        return pd.DataFrame()
    ref = fecha_corte()
    current_hash = hash((pd.util.hash_pandas_object(df_hist).sum(), meses_cobertura, str(ref)))
    if "ventas_media_cache" not in st.session_state or st.session_state.get("historico_hash") != current_hash:
        st.session_state["ventas_media_cache"] = calcular_ventas_mensuales(df_hist, meses_cobertura, fecha_ref=ref)
        st.session_state["historico_hash"] = current_hash
    return st.session_state["ventas_media_cache"]


# ANALISIS, MATCHING, TIERS, PEDIDOS
# ===========================================================================
def calcular_health_score(df_inventario, df_ventas_media, meses_cobertura_objetivo=None):
    if meses_cobertura_objetivo is None:
        meses_cobertura_objetivo = HEALTH_SCORE_MESES_DEFAULT
    df = df_inventario.merge(df_ventas_media, on=COL_CN, how="left")
    df["Venta_Media_Mensual"] = df["Venta_Media_Mensual"].fillna(0)
    df["Stock_Ideal"] = df["Venta_Media_Mensual"] * meses_cobertura_objetivo
    con_venta = df["Venta_Media_Mensual"] > 0
    # Productos con stock y sin ventas cuentan con la desviacion maxima: bajan el score.
    mask = con_venta | (df[COL_STOCK] > 0)
    if mask.sum() == 0: return 50.0
    df_a = df[mask].copy()
    desv = (df_a[COL_STOCK] - df_a["Stock_Ideal"]).abs() / df_a["Stock_Ideal"].where(con_venta[mask])
    df_a["Desv"] = desv.fillna(2.0).clip(upper=2.0)
    return round(max(0, 100 - df_a["Desv"].mean() * 100), 1)

def calcular_stock_zombie(df_inventario, df_ventas, meses_sin_venta=12):
    df_inv = df_inventario.copy()
    if COL_FECHA in df_ventas.columns:
        df_v = df_ventas.copy()
        df_v[COL_FECHA] = pd.to_datetime(df_v[COL_FECHA], errors="coerce", dayfirst=True)
        fecha_corte = df_v[COL_FECHA].max() - relativedelta(months=meses_sin_venta)
        ventas_rec = df_v[df_v[COL_FECHA] >= fecha_corte].groupby(COL_CN)[COL_VENTAS].sum().reset_index()
        cn_con_ventas = set(ventas_rec[ventas_rec[COL_VENTAS] > 0][COL_CN])
    else:
        vt = df_ventas.groupby(COL_CN)[COL_VENTAS].sum().reset_index()
        cn_con_ventas = set(vt[vt[COL_VENTAS] > 0][COL_CN])
    df_z = df_inv[(df_inv[COL_STOCK] > 0) & (~df_inv[COL_CN].isin(cn_con_ventas))].copy()
    # Un producto recien dado de alta tampoco tiene ventas, pero no es stock muerto.
    nuevos = cns_alta_reciente(df_inventario, df_ventas, meses_sin_venta)
    if nuevos:
        df_z = df_z[~df_z[COL_CN].isin(nuevos)].copy()
    df_z["Valor_Inmovilizado"] = (df_z[COL_STOCK] * df_z.get(COL_PVL, pd.Series(0))).fillna(0)
    return df_z

def cns_alta_reciente(df_inventario, df_ventas, meses=12):
    """Productos del inventario sin ninguna venta en todo el historico que entraron en la farmacia
    hace menos de `meses`. El ERP no da fecha de alta, asi que la entrada se deduce de las fotos de
    stock (primera foto en la que aparece, si hay fotos anteriores sin el) y de las compras registradas.
    Con una sola foto y sin compras no se puede saber: devuelve un conjunto vacio."""
    vendidos = set(df_ventas[df_ventas[COL_VENTAS] > 0][COL_CN]) if COL_VENTAS in df_ventas.columns else set()
    nunca_vendidos = set(df_inventario[COL_CN]) - vendidos
    if not nunca_vendidos:
        return set()
    from data.historicos import entradas_recientes  # import diferido: data.historicos importa de este modulo
    return nunca_vendidos & entradas_recientes(meses)

def calcular_sobrestock(df_inventario, df_ventas_media, excluir_cns=(), meses_objetivo=HEALTH_SCORE_MESES_DEFAULT):
    """Exceso de stock sobre `meses_objetivo` de venta, en unidades y euros.

    `excluir_cns`: productos ya contados como zombie/UVI. Sin excluirlos, su stock
    entero aparecia tambien como sobrestock y el dinero en riesgo se sumaba dos veces.
    """
    df = df_inventario.merge(df_ventas_media[[COL_CN, "Venta_Media_Mensual"]], on=COL_CN, how="left")
    df["Venta_Media_Mensual"] = df["Venta_Media_Mensual"].fillna(0)
    df = df[~df[COL_CN].isin(set(excluir_cns))].copy()
    df["Stock_Ideal"] = df["Venta_Media_Mensual"] * meses_objetivo
    df["Exceso"] = (df[COL_STOCK] - df["Stock_Ideal"]).clip(lower=0)
    pvl = df[COL_PVL] if COL_PVL in df.columns else pd.Series(0.0, index=df.index)
    df["Valor_Exceso"] = (df["Exceso"] * pvl).fillna(0)
    df_exceso = df[df["Exceso"] > 0]
    return round(float(df_exceso["Valor_Exceso"].sum()), 2), df_exceso

def calcular_roturas(df_inventario, df_ventas_media):
    df_m = df_inventario.merge(df_ventas_media, on=COL_CN, how="left")
    df_m["Venta_Media_Mensual"] = df_m["Venta_Media_Mensual"].fillna(0)
    return df_m[(df_m[COL_STOCK] == 0) & (df_m["Venta_Media_Mensual"] > 0)]

def calcular_pareto_laboratorios(df_inventario):
    df = df_inventario.copy()
    if COL_PVL not in df.columns or COL_LAB not in df.columns: return pd.DataFrame()
    df["Valor_Stock"] = (df[COL_STOCK] * df[COL_PVL]).fillna(0)
    pareto = df.groupby(COL_LAB)["Valor_Stock"].sum().sort_values(ascending=False).reset_index()
    total = pareto["Valor_Stock"].sum()
    pareto["Pct_Acumulado"] = (pareto["Valor_Stock"].cumsum() / total * 100) if total > 0 else pd.Series(0.0, index=pareto.index)
    return pareto


# --- UVI: productos sin ventas en 6 meses ---
def calcular_stock_uvi(df_inventario, df_ventas, meses_sin_venta=6):
    """Productos con stock > 0 sin ventas en los ultimos 6 meses (pre-zombie)."""
    df_inv = df_inventario.copy()
    if COL_FECHA in df_ventas.columns:
        df_v = df_ventas.copy()
        df_v[COL_FECHA] = pd.to_datetime(df_v[COL_FECHA], errors="coerce", dayfirst=True)
        fecha_corte_uvi = df_v[COL_FECHA].max() - relativedelta(months=meses_sin_venta)
        fecha_corte_zombie = df_v[COL_FECHA].max() - relativedelta(months=12)
        ventas_rec = df_v[df_v[COL_FECHA] >= fecha_corte_uvi].groupby(COL_CN)[COL_VENTAS].sum().reset_index()
        ventas_12m = df_v[df_v[COL_FECHA] >= fecha_corte_zombie].groupby(COL_CN)[COL_VENTAS].sum().reset_index()
        cn_sin_venta_6m = set(df_inv[COL_CN]) - set(ventas_rec[ventas_rec[COL_VENTAS] > 0][COL_CN])
        cn_con_venta_12m = set(ventas_12m[ventas_12m[COL_VENTAS] > 0][COL_CN])
        # UVI = sin ventas 6 meses PERO con ventas en 12 meses (si no, ya es zombie)
        cn_uvi = cn_sin_venta_6m & cn_con_venta_12m
    else:
        return pd.DataFrame()
    df_u = df_inv[(df_inv[COL_STOCK] > 0) & (df_inv[COL_CN].isin(cn_uvi))].copy()
    if COL_PVL in df_u.columns:
        df_u["Valor_Inmovilizado"] = (df_u[COL_STOCK] * df_u[COL_PVL]).fillna(0)
    else:
        df_u["Valor_Inmovilizado"] = 0
    return df_u


# --- Rotacion de stock ---
def calcular_rotacion_stock(df_inventario, df_ventas_media):
    """Ratio de venta sobre stock. Alto = buen movimiento, bajo = sobrestock.
    Excluye productos con stock=0 (son roturas, no sobrestock)."""
    df = df_inventario.merge(df_ventas_media[[COL_CN, "Venta_Media_Mensual"]], on=COL_CN, how="left")
    df["Venta_Media_Mensual"] = df["Venta_Media_Mensual"].fillna(0)
    # Solo productos CON stock (stock=0 es rotura, no va aqui)
    df = df[df[COL_STOCK] > 0].copy()
    if df.empty:
        return pd.DataFrame()
    df["Rotacion"] = (df["Venta_Media_Mensual"] / df[COL_STOCK]).round(2)
    df["Meses_Stock"] = np.where(df["Venta_Media_Mensual"] > 0,
        (df[COL_STOCK] / df["Venta_Media_Mensual"]).round(1), np.nan)
    cols = [c for c in [COL_CN, COL_NOMBRE, COL_LAB, COL_STOCK, "Venta_Media_Mensual",
            "Rotacion", "Meses_Stock"] if c in df.columns]
    return df[cols].sort_values("Rotacion", ascending=True)


# --- ROI por laboratorio ---
def ventas_ultimos_12_meses(df_ventas):
    """(unidades vendidas por producto en los 12 ultimos meses con datos, meses que cubren, ultimo dia con ventas).

    Devuelve (None, 0, None) si el historico no tiene fechas. Si hay menos de 12 meses de
    historico, `meses` lo dice para que quien llame pueda anualizar y avisar.
    """
    if df_ventas is None or df_ventas.empty or COL_FECHA not in df_ventas.columns:
        return None, 0, None
    fechas = pd.to_datetime(df_ventas[COL_FECHA], errors="coerce", dayfirst=True)
    periodo = fechas.dt.year * 12 + fechas.dt.month
    if periodo.notna().sum() == 0:
        return None, 0, None
    p_max = periodo.max()
    meses = int(min(12, p_max - periodo.min() + 1))
    uds = df_ventas[periodo > p_max - 12].groupby(COL_CN)[COL_VENTAS].sum()
    return uds, meses, fechas.max()

def calcular_roi_laboratorios(df_inventario, df_ventas_media, df_ventas=None):
    """ROI = Venta_Anual_€ / Stock_€ por laboratorio.

    Venta anual = lo vendido de verdad en los ultimos 12 meses del historico (`df_ventas`), a PVL.
    Antes se multiplicaba por 12 la prevision de los dos meses siguientes, que es estacional: en
    junio los laboratorios de verano parecian los mejores y en noviembre los peores.
    Con menos de 12 meses de historico se anualiza lo que hay (attrs["meses_venta"] lo indica).
    Sin historico con fechas se mantiene el calculo antiguo (attrs["venta_real"] = False).
    """
    if COL_LAB not in df_inventario.columns or COL_PVL not in df_inventario.columns:
        return pd.DataFrame()
    df = df_inventario.merge(df_ventas_media[[COL_CN, "Venta_Media_Mensual"]], on=COL_CN, how="left")
    df["Venta_Media_Mensual"] = df["Venta_Media_Mensual"].fillna(0)
    df["Stock_EUR"] = (df[COL_STOCK] * df[COL_PVL]).fillna(0)
    uds_12m, meses, hasta = ventas_ultimos_12_meses(df_ventas)
    if uds_12m is not None:
        df["Venta_Anual_EUR"] = (df[COL_CN].map(uds_12m).fillna(0) * (12 / meses) * df[COL_PVL]).fillna(0)
    else:
        df["Venta_Anual_EUR"] = (df["Venta_Media_Mensual"] * 12 * df[COL_PVL]).fillna(0)
    lab_agg = df.groupby(COL_LAB).agg(
        Stock_EUR=("Stock_EUR", "sum"),
        Venta_Anual_EUR=("Venta_Anual_EUR", "sum"),
        N_Productos=(COL_CN, "count"),
    ).reset_index()
    lab_agg["ROI"] = np.where(lab_agg["Stock_EUR"] > 0,
        (lab_agg["Venta_Anual_EUR"] / lab_agg["Stock_EUR"]).round(2), 0.0)
    lab_agg = lab_agg.sort_values("ROI", ascending=False)
    lab_agg.attrs.update({"venta_real": uds_12m is not None, "meses_venta": meses, "hasta": hasta})
    return lab_agg


# --- Coste de oportunidad de roturas ---
def calcular_coste_oportunidad(df_inventario, df_ventas_media, precios_venta=None):
    """Venta que se pierde al mes por no tener stock de productos con demanda.

    `precios_venta`: Serie {codigo nacional: PVP sin IVA}. Con ella la venta perdida se valora a
    precio de venta, que es lo que deja de entrar en caja; los productos sin PVP, y todos si no
    se pasa la serie, se valoran a PVL.
    """
    df_rot = calcular_roturas(df_inventario, df_ventas_media)
    if df_rot.empty:
        return 0.0, pd.DataFrame()
    df_rot = df_rot.copy()
    precio = df_rot[COL_PVL] if COL_PVL in df_rot.columns else pd.Series(0.0, index=df_rot.index)
    if precios_venta is not None:
        df_rot["PVP_Sin_IVA"] = df_rot[COL_CN].map(precios_venta)
        precio = df_rot["PVP_Sin_IVA"].where(df_rot["PVP_Sin_IVA"].notna(), precio)
    df_rot["Venta_Perdida_Mes"] = (df_rot["Venta_Media_Mensual"] * precio).fillna(0).round(2)
    total = df_rot["Venta_Perdida_Mes"].sum()
    cols = [c for c in [COL_CN, COL_NOMBRE, COL_LAB, "Venta_Media_Mensual",
            COL_PVL, "PVP_Sin_IVA", "Venta_Perdida_Mes"] if c in df_rot.columns]
    return round(total, 2), df_rot[cols].sort_values("Venta_Perdida_Mes", ascending=False)


# --- Benchmark HS vs red ---
def calcular_benchmark_hs(mi_hs):
    """Compara el HS de la farmacia activa con la media de la red."""
    from core.network import cargar_red_config  # import diferido: core.network importa de este modulo
    red = cargar_red_config()
    farmacias = red.get("farmacias_activas", [])
    farmacia_activa = st.session_state.get("farmacia_activa", "")
    if len(farmacias) < 2:
        return {"mi_hs": mi_hs, "media_red": None, "n_farmacias": 0}
    scores = []
    for farm in farmacias:
        if farm == farmacia_activa:
            continue
        path = BASE_DIR / farm / "historico_kpi.json"
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    hist = json.load(f)
                if hist:
                    scores.append(hist[-1].get("health_score", 0))
            except Exception:
                pass
    if not scores:
        return {"mi_hs": mi_hs, "media_red": None, "n_farmacias": 0}
    return {
        "mi_hs": mi_hs,
        "media_red": round(np.mean(scores), 1),
        "n_farmacias": len(scores),
    }

# --- Nuevas Métricas Auditoría ---
def calcular_indice_servicio(df_inventario, df_ventas):
    """Calcula el Fill Rate: % de productos con demanda habitual que NO están en rotura."""
    if df_ventas.empty or COL_FECHA not in df_ventas.columns: return 100.0, 0, 0
    df_v = df_ventas.copy()
    df_v[COL_FECHA] = pd.to_datetime(df_v[COL_FECHA], errors="coerce", dayfirst=True)
    
    fecha_reciente = df_v[COL_FECHA].max()
    if pd.isna(fecha_reciente): return 100.0, 0, 0
    
    fecha_corte = fecha_reciente - relativedelta(months=3)
    ventas_recientes = df_v[df_v[COL_FECHA] >= fecha_corte].groupby(COL_CN)[COL_VENTAS].sum().reset_index()
    cn_demanda = set(ventas_recientes[ventas_recientes[COL_VENTAS] > 0][COL_CN])
    if not cn_demanda: return 100.0, 0, 0
    
    df_i = df_inventario[df_inventario[COL_CN].isin(cn_demanda)]
    cn_con_stock = set(df_i[df_i[COL_STOCK] > 0][COL_CN])
    
    fill_rate = len(cn_con_stock) / len(cn_demanda) * 100
    return fill_rate, len(cn_demanda), len(cn_demanda) - len(cn_con_stock)

def _stock_con_caducidad(df_inventario):
    """Productos con stock y fecha de caducidad valida, o None si el inventario no trae fechas."""
    if df_inventario.empty or "Fecha_Caducidad" not in df_inventario.columns:
        return None
    df = df_inventario.copy()
    df["Fecha_Caducidad"] = pd.to_datetime(df["Fecha_Caducidad"], errors="coerce", dayfirst=True)
    if df["Fecha_Caducidad"].notna().sum() == 0:
        return None
    df = df[df["Fecha_Caducidad"].notna() & (df[COL_STOCK] > 0)].copy()
    pvl = df[COL_PVL] if COL_PVL in df.columns else pd.Series(0.0, index=df.index)
    df["Valor_Caducidad"] = (df[COL_STOCK] * pvl).fillna(0)
    return df

def calcular_riesgo_caducidad(df_inventario):
    """(valor, n productos, hay_datos) del stock que caduca en los 6 meses siguientes a la fecha del inventario.

    Solo productos con stock y aun no caducados (lo ya caducado va en calcular_stock_caducado).
    Sin fechas de caducidad reales devuelve (None, 0, False): no se estima nada."""
    df = _stock_con_caducidad(df_inventario)
    if df is None: return None, 0, False
    ref = fecha_corte() or pd.Timestamp(datetime.now())
    df_cad = df[(df["Fecha_Caducidad"] > ref) & (df["Fecha_Caducidad"] <= ref + relativedelta(months=6))]
    return float(df_cad["Valor_Caducidad"].sum()), len(df_cad), True

def calcular_stock_caducado(df_inventario):
    """(valor, n productos) del stock cuya fecha de caducidad ya ha pasado a la fecha del inventario."""
    df = _stock_con_caducidad(df_inventario)
    if df is None: return 0.0, 0
    ref = fecha_corte() or pd.Timestamp(datetime.now())
    df_cad = df[df["Fecha_Caducidad"] <= ref]
    return float(df_cad["Valor_Caducidad"].sum()), len(df_cad)

def calcular_matriz_rentabilidad_gmroi(df_inventario, df_ventas_media):
    """Calcula GMROI proxy (Margen * Rotación) si existe PVP y PVL."""
    if COL_PVL not in df_inventario.columns or df_inventario.empty: return pd.DataFrame(), False
        
    df = df_inventario.copy()
    df = df.merge(df_ventas_media[[COL_CN, "Venta_Media_Mensual"]], on=COL_CN, how="left")
    df["Venta_Media_Mensual"] = df["Venta_Media_Mensual"].fillna(0)
    
    df["PVP_Calc"] = pd.to_numeric(df.get("PVP", pd.Series(np.nan)), errors="coerce")
    df["PVL_Calc"] = pd.to_numeric(df.get(COL_PVL, pd.Series(np.nan)), errors="coerce")
    tiene_pvp_real = "PVP" in df.columns and df["PVP_Calc"].notna().sum() > 0
    df["PVP_Calc"] = df["PVP_Calc"].fillna(df["PVL_Calc"] * 1.3).fillna(0)
    
    # Margen Bruto estimado
    df["Margen_Bruto_Pct"] = np.where(df["PVP_Calc"] > 0, (df["PVP_Calc"] - df["PVL_Calc"]) / df["PVP_Calc"], 0)
    
    # Rotacion proxy
    df["Rotacion_Proxy"] = np.where(df[COL_STOCK] > 0, df["Venta_Media_Mensual"] / df[COL_STOCK], df["Venta_Media_Mensual"])
    df["GMROI"] = df["Margen_Bruto_Pct"] * df["Rotacion_Proxy"]
    
    margen_mediano = df[df["Margen_Bruto_Pct"]>0]["Margen_Bruto_Pct"].median() if not df[df["Margen_Bruto_Pct"]>0].empty else 0.3
    rot_mediana = df[df["Rotacion_Proxy"]>0]["Rotacion_Proxy"].median() if not df[df["Rotacion_Proxy"]>0].empty else 1.0
    
    cond_alta_rot = df["Rotacion_Proxy"] >= rot_mediana
    cond_alto_mar = df["Margen_Bruto_Pct"] >= margen_mediano
    
    df["Cuadrante"] = np.where(cond_alta_rot & cond_alto_mar, "Estrellas (Alto M. / Alta R.)",
                      np.where(cond_alta_rot & ~cond_alto_mar, "Genera Tráfico (Bajo M. / Alta R.)",
                      np.where(~cond_alta_rot & cond_alto_mar, "Rentables Lentos (Alto M. / Baja R.)",
                               "Problema (Bajo M. / Baja R.)")))
    return df, tiene_pvp_real

def calcular_dependencia_estacional(df_ventas):
    """Calcula el % de ventas que concentra cada mes para detectar picos brutales (estacionalidad)."""
    if df_ventas.empty or COL_FECHA not in df_ventas.columns: return pd.DataFrame()
    df_v = df_ventas.copy()
    df_v[COL_FECHA] = pd.to_datetime(df_v[COL_FECHA], errors="coerce", dayfirst=True)
    df_v["Mes"] = df_v[COL_FECHA].dt.month
    df_v["Anio"] = df_v[COL_FECHA].dt.year
    
    ventas_por_mes_anio = df_v.groupby(["Anio", "Mes"])[COL_VENTAS].sum().reset_index()
    promedio_mensual = ventas_por_mes_anio.groupby("Mes")[COL_VENTAS].mean().reset_index()
    total_ventas_promedio_anual = promedio_mensual[COL_VENTAS].sum()
    
    if total_ventas_promedio_anual == 0: return pd.DataFrame()
    
    promedio_mensual["Pct_Ventas"] = (promedio_mensual[COL_VENTAS] / total_ventas_promedio_anual) * 100
    promedio_mensual["Mes_Nombre"] = promedio_mensual["Mes"].map({
        1:"Ene", 2:"Feb", 3:"Mar", 4:"Abr", 5:"May", 6:"Jun",
        7:"Jul", 8:"Ago", 9:"Sep", 10:"Oct", 11:"Nov", 12:"Dic"})
    return promedio_mensual.sort_values("Mes")

def calcular_conciliacion_fisico_logico(df_teorico, df_fisico, conteo_completo=False):
    """Cruza Stock_Teorico con Cantidad_Fisica del CSV con la pistola. Devuelve (descuadres, alcance).

    Por defecto solo se comparan los productos que aparecen en el archivo del conteo: lo normal es
    contar una parte de la farmacia, y dar por desaparecido todo lo que no se ha contado inventaba
    perdidas. Con `conteo_completo=True` (se ha contado toda la farmacia) lo que no aparece en el
    archivo si cuenta como faltante. `alcance` dice cuanto se ha contado; (None, {}) si no se
    reconocen las columnas del archivo.
    """
    col_cn = [c for c in df_fisico.columns if "cod" in c.lower() or "cn" in c.lower()]
    col_cant = [c for c in df_fisico.columns if "cant" in c.lower() or "stock" in c.lower()]
    if not col_cn or not col_cant: return None, {}

    c_cn, c_qt = col_cn[0], col_cant[0]
    agg_fisico = df_fisico.groupby(c_cn)[c_qt].sum().reset_index()
    agg_fisico.columns = [COL_CN, "Stock_Fisico"]
    agg_fisico[COL_CN] = normalizar_cn(agg_fisico[COL_CN])
    agg_fisico = agg_fisico.groupby(COL_CN, as_index=False)["Stock_Fisico"].sum()
    
    df = df_teorico.copy()
    if COL_PVL not in df.columns: df[COL_PVL] = 0
    df = df.merge(agg_fisico, on=COL_CN, how="outer", indicator="_origen")
    df[COL_STOCK] = df[COL_STOCK].fillna(0)
    df["Stock_Fisico"] = df["Stock_Fisico"].fillna(0)
    en_inventario, contado = df["_origen"] != "right_only", df["_origen"] != "left_only"
    valor = (df[COL_STOCK] * df[COL_PVL]).fillna(0)
    alcance = {
        "en_inventario": int(en_inventario.sum()), "contados": int((en_inventario & contado).sum()),
        "no_contados": int((~contado).sum()), "fuera_de_inventario": int((~en_inventario).sum()),
        "valor_inventario": float(valor[en_inventario].sum()), "valor_contado": float(valor[en_inventario & contado].sum()),
        "valor_no_contado": float(valor[~contado].sum()), "conteo_completo": bool(conteo_completo),
    }
    if not conteo_completo:
        df = df[contado]
    df = df.drop(columns=["_origen"]).copy()

    df["Descuadre_Uds"] = df["Stock_Fisico"] - df[COL_STOCK]
    df["Descuadre_Eur"] = df["Descuadre_Uds"] * df[COL_PVL]
    return df, alcance

def calcular_flujo_caja_inventario(df_inv, df_vm, dias_pago_media, df_facturas=None):
    """Cruza la rotacion del inventario con los dias de pago para ver el Flujo de Caja."""
    if df_facturas is not None and not df_facturas.empty:
        c_imp = [c for c in df_facturas.columns if "import" in c.lower() or "total" in c.lower() or "eur" in c.lower()]
        c_dias = [c for c in df_facturas.columns if "dias" in c.lower() or "pago" in c.lower()]
        if c_imp and c_dias:
            df_facturas["Importe_Calc"] = pd.to_numeric(df_facturas[c_imp[0]], errors="coerce").fillna(0)
            df_facturas["Dias_Calc"] = pd.to_numeric(df_facturas[c_dias[0]], errors="coerce").fillna(0)
            sum_imp = df_facturas["Importe_Calc"].sum()
            if sum_imp > 0:
                df_facturas["Peso"] = df_facturas["Importe_Calc"] * df_facturas["Dias_Calc"]
                dias_pago_media = df_facturas["Peso"].sum() / sum_imp
            
    if COL_PVL not in df_inv.columns or df_inv.empty: return dias_pago_media, 0, 0, 0, 0
    
    df = df_inv.merge(df_vm[[COL_CN, "Venta_Media_Mensual"]], on=COL_CN, how="left")
    df["Venta_Media_Mensual"] = df["Venta_Media_Mensual"].fillna(0)
    
    valor_stock_total = (df[COL_STOCK] * df[COL_PVL]).fillna(0).sum()
    coste_ventas_mensual = (df["Venta_Media_Mensual"] * df[COL_PVL]).fillna(0).sum()
    
    if coste_ventas_mensual == 0: return dias_pago_media, 0, 0, 0, 0
    
    coste_ventas_diario = coste_ventas_mensual / 30
    dias_inventario = valor_stock_total / coste_ventas_diario
    
    ccc = dias_inventario - dias_pago_media
    necesidad_fm = ccc * coste_ventas_diario if ccc > 0 else 0
    flotador = abs(ccc) * coste_ventas_diario if ccc < 0 else 0
    
    return dias_pago_media, dias_inventario, ccc, necesidad_fm, flotador


# --- Panel de surtido ---
def generar_panel_surtido(df_inventario, reglas=None):
    """Por cada molecula o regla granulada, cuantos labs distintos tienen stock."""
    if COL_NOMBRE not in df_inventario.columns or COL_LAB not in df_inventario.columns:
        return pd.DataFrame()
    df = df_inventario[df_inventario[COL_STOCK] > 0].copy()
    if df.empty:
        return pd.DataFrame()
        
    df["Tipo_Prod"] = df.apply(lambda r: heuristica_tipo_producto(r.get(COL_CN, ""), r.get(COL_MOLECULA if COL_MOLECULA in df.columns else COL_NOMBRE, "")), axis=1)
    
    # Extraer lista de reglas en texto
    reglas_str = []
    reglas_map = {}
    if reglas:
        for r in reglas:
            r_str = str(r.get("presentacion", "")).lower().strip()
            if r_str:
                reglas_str.append(r_str)
                reglas_map[r_str] = int(float(r.get("min_labs", 1)))
                
    # Asignar grupo dinamico
    col_mol = COL_MOLECULA if COL_MOLECULA in df.columns else COL_NOMBRE
    df["Surtido_Grupo"] = df.apply(lambda r: asignar_grupo_surtido(r[COL_NOMBRE], r[col_mol], reglas_str), axis=1)

    panel = df.groupby("Surtido_Grupo", as_index=False).agg(
        N_Labs=(COL_LAB, "nunique"),
        Labs=(COL_LAB, lambda x: ", ".join(sorted([str(i) for i in x.unique() if pd.notna(i)]))),
        Stock_Total=(COL_STOCK, "sum"),
        Tipo=( "Tipo_Prod", lambda x: ", ".join(sorted(list(set(x)))))
    ).rename(columns={"Surtido_Grupo": "Presentacion/Molecula"}).sort_values("N_Labs", ascending=True)

    # Aplicar reglas si existen
    if reglas:
        panel["Regla_Min"] = panel["Presentacion/Molecula"].str.lower().map(reglas_map).fillna(0).astype(int)
        panel["Cumple"] = panel.apply(
            lambda r: "✅" if r["Regla_Min"] == 0 or r["N_Labs"] >= r["Regla_Min"] else "❌", axis=1)
    else:
        panel["Regla_Min"] = 0
        panel["Cumple"] = "—"
    return panel


# --- Validacion post-pedido de surtido ---
def validar_surtido_pedido(df_inventario, df_pedido, reglas):
    """Comprueba si el pedido mantiene la diversificacion minima preasignando grupos."""
    alertas = []
    if not reglas or df_pedido is None or df_pedido.empty:
        return alertas
    if COL_NOMBRE not in df_inventario.columns or COL_LAB not in df_inventario.columns:
        return alertas
    
    # Estado actual de surtido + Pedidos (Ficticio/Simulado juntos)
    df_stock = df_inventario[df_inventario[COL_STOCK] > 0].copy()
    
    reglas_str = []
    for r in reglas:
        r_str = str(r.get("presentacion", "")).lower().strip()
        if r_str: reglas_str.append(r_str)
        
    col_mol = COL_MOLECULA if COL_MOLECULA in df_stock.columns else COL_NOMBRE
    df_stock["Surtido_Grupo"] = df_stock.apply(lambda r: asignar_grupo_surtido(r[COL_NOMBRE], r[col_mol], reglas_str), axis=1)
    
    surtido_actual = df_stock.groupby("Surtido_Grupo")[COL_LAB].nunique().to_dict()
    
    # Verificar reglas
    for regla in reglas:
        mol = str(regla.get("presentacion", "")).strip().lower()
        min_labs = int(float(regla.get("min_labs", 1)))
        if not mol or min_labs <= 0:
            continue
        labs_actuales = surtido_actual.get(mol, 0)
        if labs_actuales < min_labs:
            alertas.append({
                "molecula": mol.title(),
                "min_labs": min_labs,
                "labs_actuales": labs_actuales,
                "mensaje": f"⚠️ {mol.title()}: tienes {labs_actuales} lab(s), regla exige mín. {min_labs}",
            })
    return alertas




# --- Matching indexado ---
def construir_indice_ofertas(df_ofertas):
    indice = {}
    if df_ofertas is None or df_ofertas.empty or "Oferta_Nombre" not in df_ofertas.columns: return indice
    for idx, row in df_ofertas.iterrows():
        nombre = str(row.get("Oferta_Nombre", "")).lower().strip()
        if len(nombre) < 3: continue
        for token in nombre.split():
            if len(token) >= 3:
                indice.setdefault(token, []).append(idx)
    return indice

def _token_contenido(token_oferta, tokens_disponibles):
    return any(token_oferta in tp for tp in tokens_disponibles)

def buscar_oferta_por_indice(nombre_producto, molecula_producto, indice, df_ofertas):
    tokens_prod = set(nombre_producto.lower().strip().split())
    tokens_mol = set(molecula_producto.lower().strip().split())
    tokens_disponibles = tokens_prod | tokens_mol
    candidatas_idx = set()
    for token in tokens_disponibles:
        if token in indice: candidatas_idx.update(indice[token])
        for idx_token, idx_list in indice.items():
            if idx_token in token or token in idx_token:
                candidatas_idx.update(idx_list)
    for oidx in candidatas_idx:
        oferta = df_ofertas.loc[oidx]
        nombre_oferta = str(oferta.get("Oferta_Nombre", "")).lower().strip()
        if len(nombre_oferta) < 3: continue
        tokens_oferta = set(nombre_oferta.split())
        if all(_token_contenido(to, tokens_disponibles) for to in tokens_oferta):
            return oferta
    return None

# --- Tiers dinamicos ---
def aplicar_tiers_dinamicos(cantidad, tiers):
    if tiers is None or (hasattr(tiers, '__len__') and len(tiers) == 0): return cantidad, 0.0, "Sin oferta", False
    for i in range(len(tiers)-1, -1, -1):
        tier = tiers[i]; tier_num = i + 1
        if cantidad >= tier["min"]: return cantidad, tier["dto"], f"Tier {tier_num}", False
        if cantidad >= tier["min"] * 0.8: return tier["min"], tier["dto"], f"Tier {tier_num} (Upselling)", True
    return cantidad, 0.0, "Sin oferta", False

def aplicar_ofertas_indexado(df_pedido, df_ofertas=None):
    df = df_pedido.copy()
    df["Descuento_Aplicado"] = 0.0; df["Tier_Aplicado"] = "Sin oferta"; df["Upselling"] = False
    if df_ofertas is None or df_ofertas.empty or "Oferta_Nombre" not in df_ofertas.columns: return df
    indice = construir_indice_ofertas(df_ofertas)
    for idx, row in df.iterrows():
        oferta = buscar_oferta_por_indice(str(row.get(COL_NOMBRE, "")), str(row.get(COL_MOLECULA, "")), indice, df_ofertas)
        if oferta is None: continue
        tiers = oferta.get("Tiers", [])
        if isinstance(tiers, str):
            try: tiers = json.loads(tiers)
            except (json.JSONDecodeError, ValueError, TypeError): tiers = []
        cant_final, dto, tier_nombre, es_ups = aplicar_tiers_dinamicos(int(row["Cantidad_A_Pedir"]), tiers)
        df.at[idx, "Cantidad_A_Pedir"] = cant_final
        df.at[idx, "Descuento_Aplicado"] = dto
        df.at[idx, "Tier_Aplicado"] = tier_nombre
        df.at[idx, "Upselling"] = es_ups
    return df

# --- Generadores de pedido ---
def generar_pedido_cobertura(df_inventario, df_ventas_media, meses_cobertura,
                             df_ofertas=None, nivel_servicio=1.65, productos_protegidos=None,
                             restriccion_caducidad_dias=None):
    df = df_inventario.merge(df_ventas_media, on=COL_CN, how="left")
    df["Venta_Media_Mensual"] = df["Venta_Media_Mensual"].fillna(0)
    df["Venta_Std_Mensual"] = df.get("Venta_Std_Mensual", pd.Series(0, index=df.index)).fillna(0)
    df["Safety_Stock"] = np.ceil(nivel_servicio * df["Venta_Std_Mensual"] * np.sqrt(meses_cobertura))
    df["Stock_Objetivo"] = np.ceil(df["Venta_Media_Mensual"] * meses_cobertura + df["Safety_Stock"])

    if restriccion_caducidad_dias is not None and "Caducidad_Dias" in df.columns:
        meses_hasta_cad = (df["Caducidad_Dias"] / 30).clip(lower=0)
        tope_cad = np.ceil(df["Venta_Media_Mensual"] * meses_hasta_cad)
        mask_cad = meses_hasta_cad < meses_cobertura
        df.loc[mask_cad, "Stock_Objetivo"] = np.minimum(
            df.loc[mask_cad, "Stock_Objetivo"], tope_cad[mask_cad])

    df["Cantidad_A_Pedir"] = np.maximum(0, df["Stock_Objetivo"] - df[COL_STOCK]).astype(int)

    if productos_protegidos:
        for pp in productos_protegidos:
            cn = normalizar_cn(pp.get("codigo_nacional", "")); stock_min = int(float(pp.get("stock_minimo", 1)))
            mask = df[COL_CN] == cn
            if mask.any():
                if df.loc[mask, COL_STOCK].iloc[0] < stock_min:
                    df.loc[mask, "Cantidad_A_Pedir"] = df.loc[mask, "Cantidad_A_Pedir"].clip(lower=stock_min - df.loc[mask, COL_STOCK].iloc[0])
            else:
                nueva = {COL_CN: cn, COL_STOCK: 0, "Cantidad_A_Pedir": stock_min,
                         "Venta_Media_Mensual": 0, "Safety_Stock": 0, "Stock_Objetivo": stock_min,
                         COL_NOMBRE: pp.get("nombre", cn)}
                df = pd.concat([df, pd.DataFrame([nueva])], ignore_index=True)

    df_ped = df[df["Cantidad_A_Pedir"] > 0].copy()
    df_ped["Precio_Unitario"] = df_ped[COL_PVL].fillna(0) if COL_PVL in df_ped.columns else 0.0
    df_ped = aplicar_ofertas_indexado(df_ped, df_ofertas)
    df_ped["Coste_Sin_Dto"] = df_ped["Cantidad_A_Pedir"] * df_ped["Precio_Unitario"]
    df_ped["Coste_Con_Dto"] = df_ped["Coste_Sin_Dto"] * (1 - df_ped["Descuento_Aplicado"])
    df_ped["Ahorro"] = df_ped["Coste_Sin_Dto"] - df_ped["Coste_Con_Dto"]
    return df_ped

def _tiers_de_oferta(oferta):
    tiers = oferta.get("Tiers", []) if oferta is not None else []
    if isinstance(tiers, str):
        try: tiers = json.loads(tiers)
        except (json.JSONDecodeError, ValueError, TypeError): tiers = []
    return list(tiers) if tiers is not None else []

def max_unidades_en_presupuesto(deseadas, precio, tiers, margen):
    """Mayor cantidad <= deseadas cuyo coste, con el descuento que corresponde a ESA
    cantidad, cabe en el margen. Devuelve (unidades, descuento, nombre del tramo).

    Se evalua cada tramo por separado porque el coste no es monotono: llegar a un
    tramo puede abaratar el total, y bajar de el lo encarece.
    """
    tramos = [(0, 0.0, "Sin oferta")] + [(int(t["min"]), float(t["dto"]), f"Tier {i + 1}") for i, t in enumerate(tiers)]
    tramos.sort(key=lambda t: t[0])
    mejor = (0, 0.0, "Sin oferta")
    for i, (minimo, dto, nombre) in enumerate(tramos):
        tope = tramos[i + 1][0] - 1 if i + 1 < len(tramos) else deseadas
        neto = precio * (1 - dto)
        caben = deseadas if neto <= 0 else int(margen / neto + 1e-9)
        q = min(deseadas, tope, caben)
        if q >= max(minimo, 1) and q > mejor[0]:
            mejor = (q, dto, nombre)
    return mejor

def generar_pedido_presupuesto(df_inventario, df_ventas_media, presupuesto, meses_cobertura,
                                df_ofertas=None, productos_protegidos=None, nivel_servicio=1.65):
    df_ideal = generar_pedido_cobertura(df_inventario, df_ventas_media, meses_cobertura, df_ofertas,
                                         nivel_servicio=nivel_servicio, productos_protegidos=productos_protegidos)
    if df_ideal.empty: return df_ideal
    cn_prot = {normalizar_cn(pp.get("codigo_nacional")) for pp in (productos_protegidos or [])}
    df_p = df_ideal[df_ideal[COL_CN].isin(cn_prot)].copy()
    df_r = df_ideal[~df_ideal[COL_CN].isin(cn_prot)].copy()
    gasto_p = (df_p["Cantidad_A_Pedir"] * df_p["Precio_Unitario"] * (1 - df_p["Descuento_Aplicado"])).sum() if not df_p.empty else 0
    ppto_r = max(0, presupuesto - gasto_p)
    df_r = df_r.sort_values("Venta_Media_Mensual", ascending=False).reset_index(drop=True)
    # Al recortar unidades hay que recalcular el tramo: antes se conservaba el descuento
    # de la cantidad completa aunque la recortada ya no llegara al minimo del tramo.
    indice = construir_indice_ofertas(df_ofertas)
    gasto = 0.0
    for idx, row in df_r.iterrows():
        deseadas = int(row["Cantidad_A_Pedir"])
        precio = float(row["Precio_Unitario"])
        if precio <= 0:
            continue
        tiers = []
        if row.get("Tier_Aplicado", "Sin oferta") != "Sin oferta":
            tiers = _tiers_de_oferta(buscar_oferta_por_indice(
                str(row.get(COL_NOMBRE, "")), str(row.get(COL_MOLECULA, "")), indice, df_ofertas))
        uds, dto, tramo = max_unidades_en_presupuesto(deseadas, precio, tiers, max(0.0, ppto_r - gasto))
        if uds < deseadas:
            df_r.at[idx, "Cantidad_A_Pedir"] = uds
            df_r.at[idx, "Descuento_Aplicado"] = dto
            df_r.at[idx, "Tier_Aplicado"] = tramo
            df_r.at[idx, "Upselling"] = False
        gasto += uds * precio * (1 - dto)
    df_r = df_r[df_r["Cantidad_A_Pedir"] > 0]
    df_f = pd.concat([df_p, df_r], ignore_index=True)
    df_f["Coste_Sin_Dto"] = df_f["Cantidad_A_Pedir"] * df_f["Precio_Unitario"]
    df_f["Coste_Con_Dto"] = df_f["Coste_Sin_Dto"] * (1 - df_f["Descuento_Aplicado"])
    df_f["Ahorro"] = df_f["Coste_Sin_Dto"] - df_f["Coste_Con_Dto"]
    return df_f
