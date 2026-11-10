"""Pruebas de core/analisis.py y utils/excel_export.py con datos sinteticos (no toca farmacias/).

Ejecutar:  py -3.14 tests/test_analisis.py
"""
import sys
import warnings
from io import BytesIO
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from config.settings import COL_CN, COL_FECHA, COL_LAB, COL_MOLECULA, COL_NOMBRE, COL_PVL, COL_STOCK, COL_VENTAS  # noqa: E402
from core import analisis as A  # noqa: E402
from utils.excel_export import libro_excel  # noqa: E402

REF = "2026-11-10"


def _inv(filas):
    return pd.DataFrame(filas, columns=[COL_CN, COL_NOMBRE, COL_MOLECULA, COL_LAB, COL_STOCK, COL_PVL])


def _vm(d):
    return pd.DataFrame({COL_CN: list(d), "Venta_Media_Mensual": list(d.values())})


def _hist_mensual(ventas, inicio="2023-11-01", extra=None):
    """ventas: {cn: [uds por mes]}"""
    filas = []
    for cn, serie in ventas.items():
        for i, u in enumerate(serie):
            if u is None:
                continue
            f = pd.Timestamp(inicio) + pd.DateOffset(months=i)
            fila = {COL_CN: cn, COL_FECHA: f.strftime("%d/%m/%Y"), COL_VENTAS: u}
            if extra:
                fila.update(extra(cn, u))
            filas.append(fila)
    return pd.DataFrame(filas)


def _base(inv, vm, params=None, hist=None, **kw):
    p = A.completar_parametros({"fecha_inventario": REF, **(params or {})})
    h = A.preparar_historico(hist, p) if hist is not None else None
    return A.construir_base(inv, vm, h, p, **kw), p, h


def test_columnas_opcionales():
    df = pd.DataFrame(columns=["Codigo_Barras", "Código Nacional", "Fecha Caducidad", "P.V.P.", "Ubicación", "Cantidad"])
    assert A.columna(df, "cn") == "Código Nacional", A.columna(df, "cn")
    assert A.columna(df, "caducidad") == "Fecha Caducidad"
    assert A.columna(df, "pvp") == "P.V.P."
    assert A.columna(df, "ubicacion") == "Ubicación"
    assert A.columna(pd.DataFrame(columns=["Codigo_Barras", "Uds"]), "cn") is None
    assert A._num(pd.Series(["1.234,50 €", "12 %", "3,5", "7"])).tolist() == [1234.5, 12.0, 3.5, 7.0]


def test_capital_liberable_cuadra():
    inv = _inv([("1", "Correcto", "X", "LabA", 20, 2.0), ("2", "Sobre", "X", "LabA", 100, 2.0), ("3", "Zombie", "X", "LabB", 5, 10.0),
                ("4", "Rotura", "X", "LabB", 0, 3.0), ("5", "UVI", "X", "LabB", 30, 1.0), ("6", "Bajo", "X", "LabA", 4, 5.0)])
    vm = _vm({"1": 10, "2": 10, "4": 10, "5": 2, "6": 10})
    base, _, _ = _base(inv, vm, cns_zombie=["3"], cns_uvi=["5"])
    assert base.set_index(COL_CN)["Estado"].to_dict() == {"1": "Correcto", "2": "Sobrestock", "3": "Zombie", "4": "Rotura", "5": "UVI",
                                                           "6": "Bajo objetivo"}
    cap = A.calcular_capital_liberable(base)
    assert cap["zombie"] == 50.0 and cap["uvi"] == 26.0 and cap["sobrestock"] == 160.0, cap
    assert cap["reponer"] == 20 * 3.0 + 16 * 5.0, cap
    optimo = float((base["Stock_Objetivo"] * base["Coste_Unit"]).sum())
    assert abs(cap["optimo"] - optimo) < 0.01, (cap, optimo)
    assert abs(cap["actual"] - cap["liberable"] + cap["reponer"] - cap["optimo"]) < 0.01


def test_parametros_por_farmacia():
    inv = _inv([("700001", "Med", "X", "LabA", 100, 10.0), ("2", "Vendas", "X", "LabA", 100, 10.0), ("123456", "Crema", "cosmetica", "LabB", 100, 10.0)])
    vm = _vm({"700001": 10, "2": 10, "123456": 10})
    base, _, _ = _base(inv, vm, params={"no_caducables": ["2"], "meses_objetivo_parafarmacia": 3, "descuento_compra_pct": 10,
                                        "descuento_compra_por_lab": {"LabB": 20}})
    b = base.set_index(COL_CN)
    assert b["Stock_Objetivo"].to_dict() == {"700001": 20, "2": 60, "123456": 30}, b["Stock_Objetivo"].to_dict()
    assert b["Coste_Unit"].to_dict() == {"700001": 9.0, "2": 9.0, "123456": 8.0}
    # protegido: el minimo manda aunque no tenga ventas
    base2, _, _ = _base(inv, _vm({"2": 0}), protegidos=[{"codigo_nacional": 2, "stock_minimo": 40}])
    assert base2.set_index(COL_CN).at["2", "Stock_Objetivo"] == 40


def test_plan_reglas_devolucion_y_liquidacion():
    inv = _inv([("1", "Insulina", "X", "LabA", 50, 10.0), ("2", "Vacuna", "X", "LabA", 50, 10.0), ("3", "Jarabe", "X", "LabA", 50, 10.0),
                ("4", "Pomada", "X", "LabA", 50, 10.0), ("5", "Muerto", "X", "LabB", 5, 10.0), ("6", "Roto", "X", "LabB", 0, 3.0),
                ("7", "Lento", "X", "LabC", 80, 1.0), ("8", "SinDev", "X", "LabD", 50, 10.0)])
    vm = _vm({str(i): 10 for i in (1, 2, 3, 4, 6, 7, 8)})
    compras = pd.DataFrame({"Fecha": pd.to_datetime(["2026-11-09", "2026-11-05", "2026-11-05", "2026-10-20", "2026-11-09"]),
                            COL_CN: ["1", "2", "3", "4", "8"]})
    base, p, _ = _base(inv, vm, params={"refrigerados": ["1", "2"], "laboratorios_sin_devolucion": ["labd"]}, cns_zombie=["5"], compras=compras)
    plan = A.generar_plan_accion(base, p)
    acc = plan.set_index(COL_CN)["Accion"].to_dict()
    assert acc["1"] == "Devolver al proveedor", acc          # refrigerado recibido ayer: dentro de 48 h
    assert acc["2"] != "Devolver al proveedor", acc          # refrigerado recibido hace 5 dias: fuera de plazo
    assert acc["3"] == "Devolver al proveedor", acc          # no refrigerado hace 5 dias: dentro de 10
    assert acc["4"] == "No reponer hasta bajar a objetivo", acc   # hace 21 dias: fuera de plazo, 5 meses de stock
    assert acc["5"] == "Liquidar y dar de baja", acc
    assert acc["6"] == "Pedir ya", acc
    assert acc["7"] == "Liquidar exceso y no reponer", acc   # 8 meses de stock >= 6
    assert acc["8"] != "Devolver al proveedor", acc          # laboratorio que no admite devolucion
    fila5 = plan[plan[COL_CN] == "5"].iloc[0]
    assert fila5["Valor_Afectado_EUR"] == 50.0 and fila5["EUR_Recuperable"] == 35.0   # liquidacion al 30 %
    assert plan[plan[COL_CN] == "1"].iloc[0]["Plazo"] == "Quedan 1 día(s)"
    # los dos bloques no se mezclan y cada uno lleva su prioridad
    assert set(plan["Bloque"]) == {"Liberar capital", "Recuperar ventas"}
    lib = plan[plan["Bloque"] == "Liberar capital"]
    assert lib["Prioridad"].tolist() == list(range(1, len(lib) + 1)) and lib["EUR_Recuperable"].is_monotonic_decreasing
    assert (plan[plan["Bloque"] == "Recuperar ventas"]["EUR_Recuperable"] == 0).all()
    # traspaso a la red
    plan_red = A.generar_plan_accion(base, p, necesidades_red={"5": ("Farmacia Norte", 3)})
    f = plan_red[plan_red[COL_CN] == "5"].iloc[0]
    assert f["Accion"] == "Traspasar a Farmacia Norte" and f["Uds_Afectadas"] == 3 and f["EUR_Recuperable"] == 30.0
    # sin compras cargadas nunca propone devolver
    base_sin, p2, _ = _base(inv, vm, cns_zombie=["5"])
    assert "Devolver al proveedor" not in set(A.generar_plan_accion(base_sin, p2)["Accion"])


def test_caducidades():
    inv = _inv([("1", "Caducado", "X", "L", 10, 2.0), ("2", "Pronto", "X", "L", 100, 2.0), ("3", "Medio", "X", "L", 30, 2.0),
                ("4", "Lejos", "X", "L", 10, 2.0), ("5", "SinStock", "X", "L", 0, 2.0), ("6", "SinFecha", "X", "L", 9, 2.0)])
    inv["Fecha_Caducidad"] = ["01/10/2026", "10/01/2027", "10/04/2027", "10/11/2028", "01/01/2020", None]
    base, p, _ = _base(inv, _vm({"2": 10, "3": 10, "4": 1}))
    det, res = A.calcular_caducidades(base)
    assert det.set_index(COL_CN)["Tramo"].to_dict() == {"1": "Caducado", "2": "0-3 meses", "3": "3-6 meses", "4": "Más de 12 meses"}
    r = det.set_index(COL_CN)
    assert r.at["1", "Uds_Riesgo"] == 10                      # caducado: todo
    assert r.at["2", "Uds_Riesgo"] == 100 - 20                # 2 meses a 10 uds/mes -> se venden 20
    assert r.at["3", "Uds_Riesgo"] == 0                       # 5 meses a 10 -> se vende todo
    assert int(res["Productos"].sum()) == 4 and res.set_index("Tramo").at["0-3 meses", "Valor_Riesgo_EUR"] == 160.0
    plan = A.generar_plan_accion(base, p).set_index(COL_CN)["Accion"].to_dict()
    assert plan["1"] == "Retirar (caducado)" and plan["2"] == "Promocionar antes de caducar", plan
    base_z, pz, _ = _base(inv, _vm({"3": 10}), cns_zombie=["2"])
    fz = A.generar_plan_accion(base_z, pz).set_index(COL_CN).loc["2"]
    assert fz["Accion"] == "Liquidar y dar de baja" and "caduca el 10/01/2027" in fz["Motivo"], fz
    assert A.calcular_caducidades(_base(_inv([("1", "a", "X", "L", 5, 1.0)]), _vm({"1": 1}))[0])[0].empty


def test_ventas_margen_e_iva():
    inv = _inv([("700001", "Med", "X", "LabA", 10, 6.0), ("123456", "Para", "cosmetica", "LabB", 10, 10.0)])
    pvp = {"700001": 10.4, "123456": 24.2}   # con IVA 4 % y 21 % -> 10 y 20 sin IVA
    hist = _hist_mensual({"700001": [10] * 24, "123456": [5] * 12 + [10] * 12}, inicio="2024-11-01", extra=lambda cn, u: {"PVP": pvp[cn]})
    base, p, h = _base(inv, _vm({"700001": 10, "123456": 10}), hist=hist)
    b = base.set_index(COL_CN)
    assert abs(b.at["700001", "PVP_Neto_Unit"] - 10) < 1e-6 and abs(b.at["123456", "PVP_Neto_Unit"] - 20) < 1e-6
    assert abs(b.at["700001", "Margen_Unit"] - 4) < 1e-6 and abs(b.at["123456", "Margen_Unit"] - 10) < 1e-6
    mens, fuente = A.ventas_mensuales(h, base)
    assert "PVP" in fuente and len(mens) == 24
    tabla, res = A.comparativa_interanual(mens)
    assert len(tabla) == 12 and res["meses_comparables"] == 12
    assert abs(res["total_12m"] - (12 * 100 + 12 * 200)) < 1e-6
    assert abs(res["var_pct"] - ((3600 / 2400) - 1) * 100) < 1e-6
    labs = A.resumen_laboratorios(base).set_index(COL_LAB)
    assert abs(labs.at["LabA", "Margen_12m_EUR"] - 120 * 4) < 0.01 and abs(labs.at["LabB", "Margen_Pct"] - 50) < 0.01
    assert abs(labs.at["LabA", "Rotacion_Anual"] - (120 * 6) / 60) < 0.01
    # sin PVP: euros aproximados a PVL y margen vacio
    base2, _, h2 = _base(inv, _vm({"700001": 10}), hist=_hist_mensual({"700001": [10] * 24}, inicio="2024-11-01"))
    mens2, fuente2 = A.ventas_mensuales(h2, base2)
    assert "aproximación" in fuente2 and abs(mens2["EUR"].iloc[-1] - 60) < 1e-6
    assert pd.isna(A.resumen_laboratorios(base2).set_index(COL_LAB).at["LabA", "Margen_12m_EUR"])


def test_venta_perdida_a_pvp():
    from core.business import calcular_coste_oportunidad
    inv = _inv([("700001", "Roto con PVP", "X", "LabA", 0, 6.0), ("700002", "Roto sin PVP", "X", "LabA", 0, 5.0)])
    hist = _hist_mensual({"700001": [10] * 24}, inicio="2024-11-01", extra=lambda cn, u: {"PVP": 10.4})    # 10 € sin IVA
    hist = pd.concat([hist, _hist_mensual({"700002": [10] * 24}, inicio="2024-11-01")], ignore_index=True)
    vm = _vm({"700001": 10, "700002": 10})
    base, p, _ = _base(inv, vm, hist=hist)
    b = base.set_index(COL_CN)
    assert abs(b.at["700001", "Venta_Perdida_Mes_EUR"] - 100) < 0.01      # 10 uds x 10 € de PVP sin IVA (no 60 € a PVL ni 40 € de margen)
    assert abs(b.at["700001", "Margen_Perdido_Mes_EUR"] - 40) < 0.01
    assert abs(b.at["700002", "Venta_Perdida_Mes_EUR"] - 50) < 0.01       # sin PVP: a PVL
    plan = A.generar_plan_accion(base, p).set_index(COL_CN)
    assert "PVP sin IVA" in plan.at["700001", "Motivo"] and "PVL" in plan.at["700002", "Motivo"]
    # el indicador antiguo de BI da la misma cifra que el plan cuando se le pasan los precios de venta
    precios = base.drop_duplicates(COL_CN).set_index(COL_CN)["PVP_Neto_Unit"].dropna()
    total, detalle = calcular_coste_oportunidad(inv, vm, precios)
    assert abs(total - float(base["Venta_Perdida_Mes_EUR"].sum())) < 0.01 and abs(total - 150) < 0.01, total
    assert calcular_coste_oportunidad(inv, vm)[0] == 110.0                # sin precios de venta, como antes: todo a PVL


def test_compras_y_descuentos():
    inv = _inv([("1", "Paracetamol 1g 20 comp", "Paracetamol", "Cinfa", 10, 2.0), ("2", "Omeprazol 20mg", "Omeprazol", "Cinfa", 10, 3.0)])
    crudo = pd.DataFrame({"Fecha pedido": ["05/11/2026", "05/11/2026", "06/11/2026", "x"], "C.N.": [1, 2, 1, 1],
                          "Cantidad": ["30", "40", "36", "5"], "% Dto": ["6", "20", "6 %", "0"], "Proveedor": ["Cinfa", None, "Cinfa", "Cinfa"]})
    compras, enc = A.normalizar_compras(crudo, inv)
    assert enc["Codigo_Nacional"] == "C.N." and enc["Unidades"] == "Cantidad" and enc["Descuento"] == "% Dto", enc
    assert len(compras) == 3 and compras["Descuento"].tolist() == [0.06, 0.2, 0.06]
    assert compras[COL_PVL].tolist() == [2.0, 3.0, 2.0] and compras[COL_LAB].tolist() == ["Cinfa", "Cinfa", "Cinfa"]   # completado con inventario
    assert abs(compras["Importe"].iloc[0] - 30 * 2 * 0.94) < 1e-6
    assert A.normalizar_compras(pd.DataFrame({"Fecha": ["01/01/2026"], "Importe": [3]}))[0].empty   # sin CN ni unidades
    ofertas = pd.DataFrame({"Oferta_Nombre": ["Paracetamol", "Omeprazol"],
                            "Tiers": [[{"min": 12, "dto": 0.06}, {"min": 36, "dto": 0.16}], [{"min": 20, "dto": 0.08}, {"min": 60, "dto": 0.2}]]})
    base, _, _ = _base(inv, _vm({"1": 10, "2": 10}))
    por_lab, perdidos = A.analizar_descuentos(compras, ofertas, base)
    m = perdidos.set_index(["Unidades", COL_CN])
    assert m.at[(30.0, "1"), "Motivo"] == "A un paso del tramo" and m.at[(30.0, "1"), "Faltaban_Uds"] == 6     # 30 >= 80 % de 36
    assert abs(m.at[(30.0, "1"), "Perdido_EUR"] - 30 * 2 * 0.10) < 0.01
    assert m.at[(36.0, "1"), "Motivo"] == "Descuento no aplicado" and abs(m.at[(36.0, "1"), "Perdido_EUR"] - 36 * 2 * 0.10) < 0.01
    assert (40.0, "2") not in m.index                           # 40 uds al 20 %: recibio mas de lo que tocaba
    fila = por_lab.iloc[0]
    bruto = 30 * 2 + 40 * 3 + 36 * 2
    assert fila["Bruto_EUR"] == bruto and abs(fila["Dto_Medio_Pct"] - (60 * .06 + 120 * .2 + 72 * .06) / bruto * 100) < 0.01
    assert A.analizar_descuentos(compras, None, base)[1] is None   # sin ofertas: funciona, sin 'perdido'
    ped = [{"fecha": "2026-03-07", "laboratorio": "Cinfa", "productos": [{"cn": 1, "cantidad": 12, "pvl": 2.0, "descuento": 0.06, "coste": 22.56}]}]
    todas = A.unir_compras(compras, A.compras_desde_pedidos(ped), compras)
    assert len(todas) == 4 and set(todas["Origen"]) == {"Excel", "Pedido SmartPharma"}


def test_roturas_recurrentes():
    hist = _hist_mensual({
        "1": [10, 10, 0, 10, 10, 0, 10, 10, 10, 0, 10, 10],      # habitual con 3 huecos -> recurrente
        "2": [1, 0, 0, 1, 0, 1, 0, 0, 1, 0, 0, 1],               # lento: los huecos son normales
        "3": [10, 10, 10, 10, 0, 0, 0, 0, 0, 0, 0, 0],           # dejo de venderse: no es rotura
        "4": [10] * 12,                                           # nunca falla
        "5": [10] * 10 + [0, 0],                                  # dos ultimos meses sin venta -> cuenta
    }, inicio="2025-11-01")
    hist = hist[hist[COL_VENTAS] > 0]                             # el ERP no exporta lineas a cero
    hist = pd.concat([hist, pd.DataFrame([{COL_CN: "9", COL_FECHA: "01/10/2026", COL_VENTAS: 1}])])   # para que el ultimo mes exista
    inv = _inv([(str(i), f"P{i}", "X", "L", 5, 2.0) for i in range(1, 6)])
    base, p, h = _base(inv, _vm({str(i): 10 for i in range(1, 6)}), hist=hist)
    tabla, periodo = A.roturas_recurrentes(h, base, None, p)
    assert periodo == "mes" and tabla.set_index(COL_CN)["Periodos_Sin_Venta"].to_dict() == {"1": 3, "5": 2}, tabla
    assert tabla.set_index(COL_CN).at["1", "Uds_Perdidas_Est"] == 30 and tabla.set_index(COL_CN).at["1", "EUR_Perdido_Est"] == 60.0
    fotos = pd.DataFrame({"Fecha": ["2026-09-01", "2026-10-01", "2026-11-01"] * 2, COL_CN: ["4"] * 3 + ["2"] * 3, COL_STOCK: [0, 0, 5, 0, 0, 0]})
    t2 = A.roturas_recurrentes(h, base, fotos, p)[0].set_index(COL_CN)
    assert t2.at["4", "Fotos_Sin_Stock"] == 2 and t2.at["4", "Evidencia"] == "Confirmada (inventarios)"
    assert "2" not in t2.index                                   # producto lento sin stock: no es rotura de un habitual
    # historico diario: periodo de 14 dias
    dias = pd.date_range("2026-08-01", "2026-10-31", freq="D")
    diario = pd.DataFrame({COL_CN: "1", COL_FECHA: dias.strftime("%d/%m/%Y"), COL_VENTAS: 1})
    diario = diario[~((dias >= "2026-08-29") & (dias < "2026-09-26"))]      # 4 semanas sin vender = 2 quincenas
    hd = A.preparar_historico(diario, p)
    td, periodo_d = A.roturas_recurrentes(hd, base, None, p)
    assert periodo_d.startswith("quincena") and td.set_index(COL_CN).at["1", "Periodos_Sin_Venta"] == 2, td


def test_calidad_datos():
    inv = _inv([("1", "a", "X", "L", 5, 0.0), ("1", "a", "X", "L", -2, 1.0), ("2", "b", "X", None, 3, 1.0)])
    hist = _hist_mensual({"1": [1] * 10, "77": [1] * 10}, inicio="2025-01-01")
    p = A.completar_parametros({"fecha_inventario": "2026-06-01"})
    q = A.calidad_datos(inv, A.preparar_historico(hist, p), p, hoy="2026-11-10")
    assert q["sin_pvl"] == 1 and q["stock_negativo"] == 1 and q["cn_duplicados"] == 1 and q["sin_laboratorio"] == 1
    assert q["meses_hist"] == 10 and q["ventas_sin_inventario"] == 1 and q["dias_inventario"] == 162
    assert len(q["avisos"]) == 7, q["avisos"]
    q2 = A.calidad_datos(inv, None, A.completar_parametros(), hoy="2026-11-10")
    assert "sin confirmar" in q2["avisos"][0]


def test_excel_listas_completas():
    n = 250
    inv = _inv([(str(i), f"Producto {i}", "X", f"Lab/{i % 7}:A", 50, 2.0) for i in range(n)])
    inv["Ubicación"] = [f"E{i % 5}" for i in range(n)]
    base, p, _ = _base(inv, _vm({}), cns_zombie=[str(i) for i in range(n)])
    plan = A.generar_plan_accion(base, p)
    hojas = A.listas_trabajo(base, plan, None, None, orden="Ubicación")
    assert len(hojas["Zombie"]) == n and len(hojas["Plan - Liberar capital"]) == n      # sin recortes
    assert hojas["Zombie"]["Ubicacion"].is_monotonic_increasing
    datos = libro_excel({**hojas, "Lab/0:A [x]*?": hojas["Zombie"], "lab-0-a -x---": hojas["Zombie"]}, portada=[("Farmacia", "Prueba")])
    libro = pd.read_excel(BytesIO(datos), sheet_name=None)
    assert len(libro) == 5 and len(libro["Zombie"]) == n and "Valor Stock €" in libro["Zombie"].columns, list(libro)
    assert "Ubicacion" not in A.listas_trabajo(_base(_inv([("1", "a", "X", "L", 5, 9.0)]), _vm({}), cns_zombie=["1"])[0], None, None, None)["Zombie"].columns


def test_farmacia_demo_no_falla():
    """Humo con la farmacia demo real (solo lectura)."""
    raiz = Path(__file__).resolve().parent.parent / "farmacias" / "Farmacia_Demo_Centro"
    if not raiz.exists():
        return
    from core.business import calcular_stock_uvi, calcular_stock_zombie, calcular_ventas_mensuales
    inv, hist = pd.read_parquet(raiz / "inventario.parquet"), pd.read_parquet(raiz / "historico.parquet")
    from utils.helpers import normalizar_cn
    inv[COL_CN], hist[COL_CN] = normalizar_cn(inv[COL_CN]), normalizar_cn(hist[COL_CN])
    vm = calcular_ventas_mensuales(hist, 2)
    z, u = calcular_stock_zombie(inv, hist), calcular_stock_uvi(inv, hist)
    base, p, h = _base(inv, vm, hist=hist, cns_zombie=z[COL_CN], cns_uvi=u[COL_CN] if not u.empty else [])
    cap = A.calcular_capital_liberable(base)
    assert abs(cap["zombie"] - float(z["Valor_Inmovilizado"].sum())) < 0.01, cap     # misma cifra que la pantalla actual
    assert abs(cap["actual"] - float((inv[COL_STOCK] * inv[COL_PVL]).sum())) < 0.01
    plan = A.generar_plan_accion(base, p)
    assert len(plan) and (plan["Bloque"] == "Recuperar ventas").sum() == (base["Estado"] == "Rotura").sum()
    mens, _ = A.ventas_mensuales(h, base)
    assert len(A.comparativa_interanual(mens)[0]) == 12 and len(A.resumen_laboratorios(base)) == inv[COL_LAB].nunique()
    A.roturas_recurrentes(h, base, None, p)
    assert libro_excel(A.listas_trabajo(base, plan, A.calcular_caducidades(base)[0], None))[:2] == b"PK"


# --- Arreglos de la revision de BI y Auditoria ---
def test_venta_anual_real_en_el_roi():
    from core.business import calcular_roi_laboratorios, calcular_ventas_mensuales
    # Solar: 80 uds en junio y julio, 2 el resto del anio -> 180 al anio. Analgesico: 10 todos los meses -> 120.
    filas = []
    for f in pd.date_range("2024-01-01", periods=24, freq="MS"):
        filas.append({COL_CN: "1", COL_FECHA: f.strftime("%d/%m/%Y"), COL_VENTAS: 80 if f.month in (6, 7) else 2})
        filas.append({COL_CN: "2", COL_FECHA: f.strftime("%d/%m/%Y"), COL_VENTAS: 10})
    hist = pd.DataFrame(filas)
    inv = _inv([("1", "Solar SPF50", "X", "LabSol", 30, 10.0), ("2", "Analgesico", "X", "LabTodoElAnio", 30, 10.0)])
    en_mayo = calcular_ventas_mensuales(hist, 2, fecha_ref="2026-05-20")
    en_noviembre = calcular_ventas_mensuales(hist, 2, fecha_ref="2026-11-10")
    roi_mayo = calcular_roi_laboratorios(inv, en_mayo, hist).set_index(COL_LAB)
    roi_nov = calcular_roi_laboratorios(inv, en_noviembre, hist).set_index(COL_LAB)
    assert roi_mayo.at["LabSol", "Venta_Anual_EUR"] == roi_nov.at["LabSol", "Venta_Anual_EUR"] == 180 * 10.0   # no depende del mes en que se mira
    assert roi_mayo.at["LabSol", "ROI"] == 6.0 and roi_mayo.at["LabTodoElAnio", "ROI"] == 4.0
    assert roi_mayo.attrs["venta_real"] and roi_mayo.attrs["meses_venta"] == 12
    # el calculo antiguo (sin historico) si dependia: en mayo 80 x 12 y en noviembre 2 x 12
    viejo_mayo = calcular_roi_laboratorios(inv, en_mayo).set_index(COL_LAB).at["LabSol", "Venta_Anual_EUR"]
    viejo_nov = calcular_roi_laboratorios(inv, en_noviembre).set_index(COL_LAB).at["LabSol", "Venta_Anual_EUR"]
    assert viejo_mayo == 9600.0 and viejo_nov == 240.0
    # con 6 meses de historico se extrapola y se avisa
    corto = calcular_roi_laboratorios(inv, en_mayo, hist[hist[COL_CN] == "2"].tail(6))
    assert corto.attrs["meses_venta"] == 6 and corto.set_index(COL_LAB).at["LabTodoElAnio", "Venta_Anual_EUR"] == 60 * 2 * 10.0


def test_conciliacion_con_conteo_parcial():
    from core.business import calcular_conciliacion_fisico_logico
    inv = _inv([("1", "Ibuprofeno", "X", "L", 10, 2.0), ("2", "Paracetamol", "X", "L", 20, 1.0), ("3", "Omeprazol", "X", "L", 30, 3.0)])
    solo_ibuprofeno = pd.DataFrame({"Codigo_Nacional": ["1"], "Cantidad": [10]})
    df, alc = calcular_conciliacion_fisico_logico(inv, solo_ibuprofeno)
    assert len(df) == 1 and (df["Descuadre_Uds"] == 0).all()                       # contar una parte ya no inventa perdidas
    assert alc["contados"] == 1 and alc["en_inventario"] == 3 and alc["no_contados"] == 2
    assert alc["valor_contado"] == 20.0 and alc["valor_inventario"] == 130.0 and alc["valor_no_contado"] == 110.0
    # si se ha contado toda la farmacia, lo que no aparece si falta
    df_c, alc_c = calcular_conciliacion_fisico_logico(inv, solo_ibuprofeno, conteo_completo=True)
    assert len(df_c) == 3 and df_c["Descuadre_Uds"].sum() == -50 and abs(df_c["Descuadre_Eur"].sum() + 110.0) < 0.01 and alc_c["conteo_completo"]
    # un descuadre real en lo contado y un codigo que no esta en el inventario
    conteo = pd.DataFrame({"Codigo_Nacional": ["1", "2", "999"], "Cantidad": [7, 20, 4]})
    df2, alc2 = calcular_conciliacion_fisico_logico(inv, conteo)
    d = df2.set_index(COL_CN)["Descuadre_Uds"].to_dict()
    assert d == {"1": -3, "2": 0, "999": 4} and alc2["contados"] == 2 and alc2["fuera_de_inventario"] == 1 and alc2["no_contados"] == 1
    assert calcular_conciliacion_fisico_logico(inv, pd.DataFrame({"x": [1]})) == (None, {})


# --- Otros arreglos ---
def test_abc_por_ventas_no_por_stock():
    inv = _inv([("1", "Estrella", "X", "L", 10, 2.0), ("2", "Medio", "X", "L", 10, 2.0), ("3", "Cola", "X", "L", 10, 2.0),
                ("4", "Muerto caro", "X", "L", 50, 100.0), ("5", "Sin stock ni ventas", "X", "L", 0, 5.0)])
    hist = _hist_mensual({"1": [80] * 12, "2": [15] * 12, "3": [5] * 12}, inicio="2025-11-01")
    base, _, _ = _base(inv, _vm({"1": 80, "2": 15, "3": 5}), hist=hist, cns_zombie=["4"])
    det, res, fuente = A.analisis_abc(base)
    clases = det.set_index(COL_CN)["Clase_ABC"].to_dict()
    assert clases == {"1": "A", "2": "B", "3": "C", "4": "Sin ventas"}, clases      # el stock muerto ya no sale como A
    r = res.set_index("Clase_ABC")
    assert r.at["A", "Pct_Ventas"] == 80.0 and r.at["Sin ventas", "Stock_EUR"] == 5000.0 and r.at["Sin ventas", "Pct_Ventas"] == 0
    assert int(res["Referencias"].sum()) == 4 and "PVL" in fuente
    # con PVP en el historico las ventas se valoran a PVP sin IVA
    hist_pvp = _hist_mensual({"1": [10] * 12, "2": [10] * 12}, inicio="2025-11-01", extra=lambda cn, u: {"PVP": 12.1 if cn == "1" else 121.0})
    det2, _, fuente2 = A.analisis_abc(_base(inv, _vm({"1": 10, "2": 10}), hist=hist_pvp)[0])
    assert "PVP" in fuente2 and det2.iloc[0][COL_CN] == "2" and abs(det2.iloc[0]["Venta_12m_EUR"] - 120 * 100) < 0.01, det2


def test_alta_reciente_no_es_exceso():
    inv = _inv([("1", "Lanzamiento", "X", "L", 20, 10.0), ("2", "Viejo sin ventas", "X", "L", 20, 10.0)])
    base, p, _ = _base(inv, _vm({}), cns_zombie=["2"], cns_nuevos=["1", "2"])
    b = base.set_index(COL_CN)
    assert b.at["1", "Estado"] == "Alta reciente" and b.at["1", "Exceso_Uds"] == 0
    assert b.at["2", "Estado"] == "Zombie"                      # si ya esta marcado como zombie, lo sigue siendo
    assert set(A.generar_plan_accion(base, p)[COL_CN]) == {"2"}
    assert A.calcular_capital_liberable(base)["liberable"] == 200.0


def test_prevision_anclada_a_la_fecha_del_inventario():
    from core.business import calcular_ventas_mensuales
    # 30 meses: junio y julio venden 10, diciembre y enero 100, el resto 50
    por_mes = {6: 10, 7: 10, 12: 100, 1: 100}
    filas = [{COL_CN: "1", COL_FECHA: f.strftime("%d/%m/%Y"), COL_VENTAS: por_mes.get(f.month, 50)}
             for f in pd.date_range("2024-01-01", periods=30, freq="MS")]
    hist = pd.DataFrame(filas)
    verano = calcular_ventas_mensuales(hist, 2, fecha_ref="2026-05-20")
    invierno = calcular_ventas_mensuales(hist, 2, fecha_ref="2026-11-10")
    assert abs(verano["Venta_Media_Mensual"].iloc[0] - 10) < 1e-6, verano       # preve junio y julio
    assert abs(invierno["Venta_Media_Mensual"].iloc[0] - 100) < 1e-6, invierno  # preve diciembre y enero
    assert calcular_ventas_mensuales(hist, 2, fecha_ref="2026-05-20").equals(verano)   # mismos datos y fecha -> mismas cifras


def test_caducidad_solo_stock_vivo():
    from core.business import calcular_riesgo_caducidad, calcular_stock_caducado
    hoy = pd.Timestamp.now().normalize()
    f = lambda dias: (hoy + pd.Timedelta(days=dias)).strftime("%d/%m/%Y")  # noqa: E731
    inv = _inv([("1", "Caducado", "X", "L", 10, 2.0), ("2", "Pronto", "X", "L", 5, 4.0), ("3", "Pronto sin stock", "X", "L", 0, 9.0),
                ("4", "Lejos", "X", "L", 7, 3.0), ("5", "Sin fecha", "X", "L", 7, 3.0)])
    inv["Fecha_Caducidad"] = [f(-10), f(60), f(60), f(400), None]
    assert calcular_riesgo_caducidad(inv) == (20.0, 1, True)        # ni lo caducado ni lo que no tiene stock
    assert calcular_stock_caducado(inv) == (20.0, 1)
    assert calcular_riesgo_caducidad(inv.drop(columns=["Fecha_Caducidad"])) == (None, 0, False)


def test_donut_solo_capital_parado():
    from ui.charts import grafico_dinero_en_riesgo_donut
    fig = grafico_dinero_en_riesgo_donut(100, 50)
    assert list(fig.data[0].values) == [100, 50] and list(fig.data[0].labels) == ["Capital Zombie", "Sobrestock"]
    assert fig.layout.annotations[0].text == "150€"                  # la venta perdida ya no infla el total
    assert grafico_dinero_en_riesgo_donut(0, 0) is None


def test_columnas_opcionales_al_cargar():
    df = pd.DataFrame({"Codigo_Nacional": [1], "Stock": [2], "PVL": [3.0], "P.V.P.": [5.0], "Caducidad": ["01/01/2027"], "Ubicación": ["E1"]})
    out, enc = A.normalizar_opcionales(df, "inventario")
    assert {"PVP", "Fecha_Caducidad", "Ubicacion"} <= set(out.columns) and "PVL" in out.columns
    assert enc == {"PVP": "P.V.P.", "Fecha_Caducidad": "Caducidad", "Ubicacion": "Ubicación", "Refrigerado": None}
    out2, enc2 = A.normalizar_opcionales(pd.DataFrame({"Codigo_Nacional": [1], "Ventas": [2], "Fecha": ["01/01/2026"]}), "historico")
    assert enc2 == {"PVP": None, "Importe": None} and list(out2.columns) == ["Codigo_Nacional", "Ventas", "Fecha"]


def _analisis(inv, vm, hist_crudo, params=None, **kw):
    """El mismo diccionario que monta la pantalla, sin Streamlit."""
    base, p, h = _base(inv, vm, params=params, hist=hist_crudo, **kw)
    mens, fuente = A.ventas_mensuales(h, base)
    inter, res = A.comparativa_interanual(mens)
    cad_det, cad_res = A.calcular_caducidades(base)
    compras = A.unir_compras(kw.get("compras"))
    dto_lab, perdidos = A.analizar_descuentos(compras, None, base)
    rot, per = A.roturas_recurrentes(h, base, None, p)
    return {"params": p, "base": base, "plan": A.generar_plan_accion(base, p), "capital": A.calcular_capital_liberable(base), "cad_det": cad_det,
            "cad_res": cad_res, "mensual": mens, "fuente_ventas": fuente, "interanual": inter, "res_interanual": res,
            "labs": A.resumen_laboratorios(base, compras, p), "compras": compras, "dto_lab": dto_lab, "dto_perdidos": perdidos, "rot_rec": rot,
            "periodo_rot": per, "calidad": A.calidad_datos(inv, h, p, compras)}


def test_informe_pdf():
    from utils import pdf_informe as P
    inv = _inv([("700001", "Ibuprofeno 600 mg 40 comp", "Ibuprofeno", "Cinfa", 300, 2.0), ("700002", "Omeprazol 20 mg", "Omeprazol", "Normon", 0, 3.0),
                ("123456", "Crema solar SPF50", "cosmetica", "Isdin", 12, 15.0), ("700003", "Paracetamol 1 g", "Paracetamol", "Cinfa", 40, 1.5)])
    inv["Fecha_Caducidad"] = ["01/02/2027", None, "20/11/2026", "01/01/2026"]
    hist = _hist_mensual({"700001": [20] * 24, "700002": [30] * 24, "700003": [25] * 24}, inicio="2024-11-01",
                         extra=lambda cn, u: {"PVP": 6.24})
    an = _analisis(inv, _vm({"700001": 20, "700002": 30, "700003": 25}), hist, cns_zombie=["123456"])
    _, abc, fuente = A.analisis_abc(an["base"])
    datos = {"farmacia": "Farmàcia L’Estel – Ω & Cía", "an": an, "n_pedidos": 2, "ahorro_confirmado": 120.5, "inversion_confirmada": 3000,
             "ahorro_potencial": 44.2, "abc": abc, "abc_fuente": fuente, "hs": 41.3, "benchmark": {"media_red": 55.0, "n_farmacias": 3},
             "hs_evolucion": [(pd.Timestamp("2026-06-01") + pd.DateOffset(months=i), 30.0 + 2 * i) for i in range(5)]}
    titulos = [t for t, _ in P.hallazgos(datos)]
    assert 1 <= len(titulos) <= 3 and "Hay stock de más" in titulos and "Se pierden ventas por roturas" in titulos, titulos
    pdf = P.generar_informe_completo(datos)
    assert pdf[:5] == b"%PDF-" and len(pdf) > 20000
    # sin fuente TrueType en el equipo no falla: cae a Helvetica y adapta el texto
    fuentes = P._FUENTES
    try:
        P._FUENTES = []
        assert P.generar_informe_completo(datos)[:5] == b"%PDF-"
    finally:
        P._FUENTES = fuentes
    # farmacia casi vacia: sin ventas con fecha, sin caducidad, sin compras
    vacio = _analisis(_inv([("1", "a", "X", "L", 1, 1.0)]), _vm({}), None)
    assert P.generar_informe_completo({"farmacia": "Vacía", "an": vacio})[:5] == b"%PDF-"


if __name__ == "__main__":
    pruebas = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    fallos = 0
    for t in pruebas:
        try:
            t()
            print(f"OK    {t.__name__}")
        except Exception as e:  # noqa: BLE001
            fallos += 1
            import traceback
            print(f"FALLO {t.__name__}: {type(e).__name__}: {e}")
            traceback.print_exc(limit=3)
    print(f"\n{len(pruebas) - fallos}/{len(pruebas)} pruebas pasan")
    sys.exit(1 if fallos else 0)
