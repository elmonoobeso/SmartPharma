"""Persistencia por farmacia de lo que usan los analisis de BI y Auditoria:
parametros de analisis, fotos fechadas del stock y compras subidas por Excel."""
import os

import pandas as pd

from config.settings import COL_CN, COL_STOCK
from core.analisis import COLS_COMPRAS, completar_parametros
from data.io import cargar_json_farmacia, guardar_json_farmacia, ruta_farmacia_activa
from utils.helpers import normalizar_cn

ARCHIVO_PARAMETROS = "parametros_analisis.json"
ARCHIVO_FOTOS = "fotos_stock.parquet"
ARCHIVO_COMPRAS = "compras.parquet"


def cargar_parametros():
    return completar_parametros(cargar_json_farmacia(ARCHIVO_PARAMETROS, default={}))


def guardar_parametros(params):
    guardar_json_farmacia(ARCHIVO_PARAMETROS, params)


def marca_archivos():
    """Fecha de modificacion de los archivos de la farmacia: sirve para saber si hay que recalcular."""
    ruta = ruta_farmacia_activa()
    if ruta is None:
        return ()
    nombres = (ARCHIVO_PARAMETROS, ARCHIVO_FOTOS, ARCHIVO_COMPRAS, "historico_pedidos.json", "productos_protegidos.json")
    return tuple((ruta / n).stat().st_mtime_ns if (ruta / n).exists() else 0 for n in nombres)


def _leer(nombre, columnas):
    ruta = ruta_farmacia_activa()
    if ruta is None or not (ruta / nombre).exists():
        return pd.DataFrame(columns=columnas)
    return pd.read_parquet(ruta / nombre, engine="pyarrow")


def _escribir(nombre, df):
    ruta = ruta_farmacia_activa()
    if ruta is None:
        raise RuntimeError("No hay farmacia activa")
    destino = ruta / nombre
    tmp = destino.with_suffix(destino.suffix + ".tmp")
    df.to_parquet(tmp, index=False, engine="pyarrow")
    os.replace(tmp, destino)


# --- Fotos de stock: una por fecha de inventario ---
def huella_inventario(df_inv):
    """Identifica el archivo de inventario cargado, para saber si su fecha ya esta confirmada."""
    cn = normalizar_cn(df_inv[COL_CN]).astype(str)
    stock = pd.to_numeric(df_inv[COL_STOCK], errors="coerce").fillna(0) if COL_STOCK in df_inv.columns else 0
    return f"{len(df_inv)}-{int(pd.util.hash_pandas_object(pd.DataFrame({'cn': cn, 's': stock}), index=False).sum() % 10**12)}"


def cargar_fotos_stock():
    return _leer(ARCHIVO_FOTOS, ["Fecha", COL_CN, COL_STOCK])


def registrar_foto_stock(df_inv, fecha, sustituye=None):
    """Guarda el stock de cada producto en `fecha`. Si ya habia foto de ese dia, la sustituye.

    `sustituye`: fecha anterior de este mismo inventario cuando se esta corrigiendo la fecha; su foto se elimina.
    Devuelve el numero de fotos guardadas."""
    fecha = pd.Timestamp(fecha).strftime("%Y-%m-%d")
    foto = pd.DataFrame({"Fecha": fecha, COL_CN: normalizar_cn(df_inv[COL_CN]).astype(str),
                         COL_STOCK: pd.to_numeric(df_inv[COL_STOCK], errors="coerce").fillna(0).astype(float)})
    foto = foto[foto[COL_CN] != ""].groupby(["Fecha", COL_CN], as_index=False)[COL_STOCK].sum()
    previas = cargar_fotos_stock()
    previas = previas[previas["Fecha"] != fecha]
    if sustituye:
        previas = previas[previas["Fecha"] != pd.Timestamp(sustituye).strftime("%Y-%m-%d")]
    todas = pd.concat([previas, foto], ignore_index=True) if not previas.empty else foto
    _escribir(ARCHIVO_FOTOS, todas)
    return int(todas["Fecha"].nunique())


_cache_entradas = {}


def entradas_recientes(meses=12):
    """Codigos nacionales que entraron en la farmacia en los `meses` anteriores a la fecha del inventario.

    El ERP no da fecha de alta. Se deduce de:
      - las fotos de stock: primera foto en la que aparece el producto, siempre que haya
        alguna foto anterior en la que no estaba (con una sola foto no se sabe nada);
      - las compras: lineas subidas por Excel o pedidos confirmados en la herramienta.
    """
    ruta = ruta_farmacia_activa()
    if ruta is None:
        return set()
    clave = (str(ruta), marca_archivos(), meses)
    if _cache_entradas.get("clave") == clave:
        return _cache_entradas["cns"]
    from core.analisis import compras_desde_pedidos
    f_inv = cargar_json_farmacia(ARCHIVO_PARAMETROS, default={}).get("fecha_inventario")
    ref = pd.Timestamp(f_inv) if f_inv else pd.Timestamp.now().normalize()
    desde = ref - pd.DateOffset(months=meses)
    cns = set()
    fotos = cargar_fotos_stock()
    if not fotos.empty:
        fechas = pd.to_datetime(fotos["Fecha"])
        primera = fechas.groupby(fotos[COL_CN].astype(str)).min()
        cns |= set(primera[(primera > fechas.min()) & (primera >= desde)].index)
    compras = [cargar_compras(), compras_desde_pedidos(cargar_json_farmacia("historico_pedidos.json", default=[]))]
    for c in compras:
        if not c.empty:
            cns |= set(c[(c["Fecha"] >= desde) & (c["Fecha"] <= ref + pd.Timedelta(days=1))][COL_CN].astype(str))
    _cache_entradas.update({"clave": clave, "cns": cns})
    return cns


# --- Compras subidas por Excel ---
def cargar_compras():
    df = _leer(ARCHIVO_COMPRAS, COLS_COMPRAS)
    if not df.empty:
        df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce")
    return df


def anadir_compras(df_nuevas):
    """Anade lineas de compra sin duplicar las que ya estaban. Devuelve (total guardado, lineas nuevas)."""
    previas = cargar_compras()
    todas = pd.concat([previas, df_nuevas[COLS_COMPRAS]], ignore_index=True) if not previas.empty else df_nuevas[COLS_COMPRAS].copy()
    todas["Fecha"] = pd.to_datetime(todas["Fecha"], errors="coerce")
    todas = todas.drop_duplicates(["Fecha", COL_CN, "Unidades", "PVL", "Descuento"]).reset_index(drop=True)
    _escribir(ARCHIVO_COMPRAS, todas)
    return len(todas), len(todas) - len(previas)


def vaciar_compras():
    ruta = ruta_farmacia_activa()
    if ruta is not None and (ruta / ARCHIVO_COMPRAS).exists():
        (ruta / ARCHIVO_COMPRAS).unlink()
