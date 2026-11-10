"""Informe PDF para el titular: resumen ejecutivo, ventas, laboratorios, plan de accion, caducidades,
roturas, compras y metodologia. Sin Streamlit ni disco: recibe los datos ya calculados y devuelve bytes.

Los graficos se dibujan con primitivas de fpdf2 (no hace falta ningun motor de imagenes).
Se usa una fuente TrueType del sistema para poder escribir € y acentos; si no hay ninguna,
se cae a Helvetica y el texto se adapta a latin-1 en vez de fallar.
"""
import math
from datetime import datetime
from pathlib import Path

import pandas as pd
from fpdf import FPDF
from fpdf.fonts import FontFace

from config.settings import APP_NAME, COL_CN, COL_LAB, COL_NOMBRE, HEALTH_SCORE_MESES_DEFAULT, VERSION

AZUL, VERDE, TINTA, GRIS_TXT = (0, 102, 255), (0, 196, 154), (30, 41, 59), (100, 116, 139)
GRIS, REJILLA, FONDO, ROJO, NARANJA = (148, 163, 184), (226, 232, 240), (248, 249, 252), (255, 75, 75), (255, 167, 38)
ANCHO = 180  # ancho util con margenes de 15 mm

_FUENTES = [
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/ariali.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"),
    ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
     "/System/Library/Fonts/Supplemental/Arial Italic.ttf"),
    ("/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Bold.ttf", "/Library/Fonts/Arial Italic.ttf"),
]
_SIN_UNICODE = {"€": "EUR", "−": "-", "–": "-", "—": "-", "×": "x", "→": "->", "≥": ">=", "≤": "<=", "…": "...", "“": '"', "”": '"',
                "‘": "'", "’": "'", "•": "-"}


def _eur(v, dec=0):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    return f"{v:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"


def _n(v, dec=0):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    return f"{v:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _corta(txt, n):
    txt = str(txt)
    return txt if len(txt) <= n else txt[:n - 1].rstrip() + "…"


def _tope(v):
    """Maximo 'redondo' del eje para un valor v (1, 2, 2.5, 5 x 10^n)."""
    if v <= 0:
        return 1.0
    exp = 10 ** math.floor(math.log10(v))
    for m in (1, 1.2, 2, 3, 4, 6, 8, 10):     # divididos en 4 tramos dan marcas redondas
        if v <= m * exp:
            return m * exp
    return 10 * exp


def _k(v, maximo):
    """Etiqueta del eje: en miles (k) cuando el maximo lo pide, sin decimales de relleno."""
    if maximo < 2000:
        return _n(v)
    return f"{v / 1000:.2f}".rstrip("0").rstrip(".").replace(".", ",") + " k"


# ---------------------------------------------------------------------------
# Hallazgos: las tres cosas mas importantes, en euros
# ---------------------------------------------------------------------------
def hallazgos(d, n=3):
    """Frases ordenadas por los euros que mueven. Devuelve una lista de (titulo, texto)."""
    an = d["an"]
    cap, plan, labs = an["capital"], an["plan"], an["labs"]
    cand = []
    if cap["liberable"] > 0 and cap["actual"] > 0:
        pct = cap["liberable"] / cap["actual"] * 100
        extra = f" De ellos, {_eur(cap['zombie'])} llevan 12 meses sin una sola venta." if cap["zombie"] > 0 else ""
        cand.append((cap["liberable"], "Hay stock de más",
                     f"{_eur(cap['liberable'])} de stock están por encima de lo que la farmacia necesita: el {pct:.0f} % de todo lo que hay "
                     f"en la estantería ({_eur(cap['actual'])}).{extra}"))
    rot = plan[plan["Bloque"] == "Recuperar ventas"]
    perdida = float(rot["Venta_Perdida_Mes_EUR"].sum())
    margen_perdido = float(an["base"]["Margen_Perdido_Mes_EUR"].sum(skipna=True)) if an["calidad"]["tiene_pvp"] else 0.0
    if perdida > 0:
        cand.append((perdida * 12, "Se pierden ventas por roturas",
                     f"{len(rot)} productos que se venden con regularidad están sin stock. Cada mes que siguen así se dejan de vender "
                     f"unos {_eur(perdida)} ({_eur(perdida * 12)} al año)"
                     + (f", de los que {_eur(margen_perdido)} al mes son margen." if margen_perdido else ".")))
    cad = an["cad_res"].set_index("Tramo")
    caducado = float(cad.at["Caducado", "Valor_EUR"]) if "Caducado" in cad.index else 0.0
    riesgo = float(cad.loc[[t for t in ("0-3 meses", "3-6 meses") if t in cad.index], "Valor_Riesgo_EUR"].sum())
    if caducado + riesgo > 0:
        partes = ([f"{_eur(caducado)} de stock ya han caducado"] if caducado > 0 else []) + \
                 ([f"{_eur(riesgo)} caducarán en los próximos 6 meses sin llegar a venderse al ritmo actual"] if riesgo > 0 else [])
        cand.append((caducado + riesgo, "Stock que caduca", " y ".join(partes).capitalize() + "."))
    if not labs.empty and cap["liberable"] > 0:
        top = labs.sort_values("Capital_Parado_EUR", ascending=False).iloc[0]
        cuota = top["Capital_Parado_EUR"] / cap["liberable"] * 100
        if cuota >= 25 and len(labs) > 3:
            cand.append((top["Capital_Parado_EUR"] * 0.5, "El exceso se concentra en un laboratorio",
                         f"{top[COL_LAB]} acumula {_eur(top['Capital_Parado_EUR'])} de stock sobrante, el {cuota:.0f} % del total: "
                         "es el primer laboratorio con el que renegociar."))
    perd = an["dto_perdidos"]
    if perd is not None and not perd.empty:
        cand.append((float(perd["Perdido_EUR"].sum()), "Descuentos que se escapan",
                     f"En las compras analizadas se dejaron de ganar {_eur(float(perd['Perdido_EUR'].sum()))} en descuentos, por quedarse "
                     "a las puertas de un tramo o por recibir menos descuento del que correspondía."))
    res = an["res_interanual"]
    if res and res.get("var_pct") is not None:
        v = res["var_pct"]
        verbo = "suben" if v >= 0 else "bajan"
        cand.append((abs(v) / 100 * res["total_12m"] * (0.5 if v < 0 else 0.05), f"Las ventas {verbo}",
                     f"Las ventas de los últimos 12 meses ({_eur(res['total_12m'])}) {verbo} un {abs(v):.1f} % frente a los 12 meses anteriores."))
    cand.sort(key=lambda c: c[0], reverse=True)
    elegidos = [(t, x) for _, t, x in cand[:n]]
    if not elegidos:
        elegidos = [("Stock ajustado", "No se detecta stock sobrante, roturas ni caducidades relevantes con los datos cargados.")]
    return elegidos


# ---------------------------------------------------------------------------
# Documento
# ---------------------------------------------------------------------------
class _Doc(FPDF):
    def __init__(self, farmacia, fecha_datos, generado):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.farmacia, self.fecha_datos, self.generado = farmacia, fecha_datos, generado
        self.fam, self.latin = "Helvetica", True
        for normal, negrita, cursiva in _FUENTES:
            if all(Path(p).exists() for p in (normal, negrita, cursiva)):
                self.add_font("Inf", "", normal)
                self.add_font("Inf", "B", negrita)
                self.add_font("Inf", "I", cursiva)
                self.fam, self.latin = "Inf", False
                break
        self.set_margins(15, 16, 15)
        self.set_auto_page_break(True, margin=16)

    # --- texto ---
    def tx(self, s):
        s = "" if s is None else str(s)
        if self.latin:
            for a, b in _SIN_UNICODE.items():
                s = s.replace(a, b)
            s = s.encode("latin-1", "replace").decode("latin-1")
        return s

    def f(self, tam, estilo="", color=TINTA):
        self.set_font(self.fam, estilo, tam)
        self.set_text_color(*color)

    def txt(self, x, y, s, tam=8, estilo="", color=TINTA, align="L", w=0):
        """Texto en (x, y) = esquina superior izquierda de su caja; con `w` se alinea dentro de ese ancho."""
        self.f(tam, estilo, color)
        self.set_xy(x, y)
        self.cell(w or self.get_string_width(self.tx(s)) + 1, tam * 0.42, self.tx(s), align=align)

    def header(self):
        if self.page_no() == 1:
            return
        self.txt(15, 8, f"Informe de stock y compras · {self.farmacia}", 8, color=GRIS_TXT)
        self.txt(15, 8, f"Datos a {self.fecha_datos}", 8, color=GRIS_TXT, align="R", w=ANCHO)
        self.set_draw_color(*REJILLA)
        self.set_line_width(0.3)
        self.line(15, 13, 195, 13)
        self.set_y(18)

    def footer(self):
        self.txt(15, 287, f"Generado con {APP_NAME} v{VERSION} el {self.generado:%d/%m/%Y}", 7, color=GRIS_TXT)
        self.txt(15, 287, f"Página {self.page_no()} de {{nb}}", 7, color=GRIS_TXT, align="R", w=ANCHO)

    def hueco(self, alto):
        """Salta de pagina si no caben `alto` mm."""
        if self.get_y() + alto > self.h - 18:
            self.add_page()

    def titulo(self, s, sub=None, reserva=30):
        """`reserva`: mm que deben caber debajo del titulo; si no caben, el titulo pasa a la pagina siguiente con su contenido."""
        self.hueco(14 + (6 if sub else 0) + reserva)
        y = self.get_y() + 2
        self.set_fill_color(*AZUL)
        self.rect(15, y, 1.4, 6.5, style="F")
        self.txt(18.5, y + 0.6, s, 13, "B")
        self.set_y(y + 9)
        if sub:
            self.parrafo(sub, 8.5, GRIS_TXT)

    def parrafo(self, s, tam=9, color=TINTA, estilo=""):
        self.f(tam, estilo, color)
        self.set_x(15)
        self.multi_cell(ANCHO, tam * 0.5, self.tx(s), align="L", new_x="LMARGIN", new_y="NEXT")
        self.ln(1.5)

    def vinetas(self, items, tam=8.5):
        for it in items:
            self.hueco(10)
            y = self.get_y()
            self.set_fill_color(*AZUL)
            self.ellipse(16.5, y + 1.5, 1.3, 1.3, style="F")
            self.f(tam, "", TINTA)
            self.set_xy(20, y)
            self.multi_cell(ANCHO - 5, tam * 0.5, self.tx(it), align="L", new_x="LMARGIN", new_y="NEXT")
            self.ln(0.8)
        self.ln(1)

    def kpis(self, items):
        """Fila de tarjetas (etiqueta, valor, nota)."""
        self.hueco(26)
        n, y, sep = len(items), self.get_y(), 3
        w = (ANCHO - sep * (n - 1)) / n
        for i, (etiqueta, valor, nota) in enumerate(items):
            x = 15 + i * (w + sep)
            self.set_fill_color(*FONDO)
            self.set_draw_color(*REJILLA)
            self.set_line_width(0.2)
            self.rect(x, y, w, 22, style="DF", round_corners=True, corner_radius=1.5)
            tam = 6.3
            self.f(tam, "", GRIS_TXT)
            while self.get_string_width(self.tx(etiqueta.upper())) > w - 6 and tam > 4.5:
                tam -= 0.2
                self.f(tam, "", GRIS_TXT)
            self.txt(x + 3, y + 2.6, etiqueta.upper(), tam, color=GRIS_TXT)
            self.txt(x + 3, y + 7.5, valor, 14, "B")
            self.f(6.8, "", GRIS_TXT)
            self.set_xy(x + 3, y + 15)
            self.multi_cell(w - 5, 3, self.tx(_corta(nota, 62)), align="L", new_x="LMARGIN", new_y="NEXT")
        self.set_y(y + 26)

    def tabla(self, cabeceras, filas, anchos, alinear, tam=7.6, entera=False):
        """`entera`: si no cabe completa en lo que queda de pagina, empieza en la siguiente."""
        self.hueco(8 + tam * 0.75 * (len(filas) if entera else min(len(filas), 4)))
        self.f(tam, "", TINTA)
        self.set_draw_color(*REJILLA)
        self.set_line_width(0.2)
        estilo_cab = FontFace(emphasis="BOLD", color=(255, 255, 255), fill_color=AZUL)
        with self.table(col_widths=anchos, text_align=alinear, width=sum(anchos), align="LEFT", line_height=tam * 0.55,
                        borders_layout="HORIZONTAL_LINES", headings_style=estilo_cab, padding=(0.9, 1.2)) as t:
            fila = t.row()
            for c in cabeceras:
                fila.cell(self.tx(c))
            for i, datos in enumerate(filas):
                fila = t.row(style=FontFace(fill_color=FONDO if i % 2 else (255, 255, 255)))
                for c in datos:
                    fila.cell(self.tx(c))
        self.ln(3)

    def nota(self, s):
        self.parrafo(s, 7.3, GRIS_TXT, "I")

    # --- graficos ---
    def _ejes(self, x, y, w, h, maximo, pasos=4, izq=13):
        """Rejilla horizontal con etiquetas en euros. Devuelve (x0, y0, ancho, alto) del area de dibujo."""
        x0, an, al = x + izq, w - izq - 2, h
        self.set_draw_color(*REJILLA)
        self.set_line_width(0.15)
        for i in range(pasos + 1):
            yy = y + al - al * i / pasos
            self.line(x0, yy, x0 + an, yy)
            v = maximo * i / pasos
            self.txt(x, yy - 1.3, _k(v, maximo), 6.3, color=GRIS_TXT, align="R", w=izq - 1.5)
        return x0, y, an, al

    def leyenda(self, x, y, series):
        for nombre, color in series:
            self.set_fill_color(*color)
            self.rect(x, y + 0.5, 3, 2, style="F")
            self.txt(x + 4, y, nombre, 6.8, color=GRIS_TXT)
            x += 6 + self.get_string_width(self.tx(nombre)) + 4

    def cascada(self, pasos, alto=58):
        """pasos: [(etiqueta, valor, 'abs' | 'rel' | 'total')]."""
        self.hueco(alto + 16)
        y = self.get_y() + 5
        niveles, cur = [], 0.0
        for _, v, tipo in pasos:
            if tipo == "abs":
                niveles.append((0.0, v))
                cur = v
            elif tipo == "rel":
                niveles.append((min(cur, cur + v), max(cur, cur + v)))
                cur += v
            else:
                niveles.append((0.0, cur))
        maximo = _tope(max(b for _, b in niveles) * 1.08)
        x0, y0, an, al = self._ejes(15, y, ANCHO, alto, maximo)
        hueco = an / len(pasos)
        for i, ((etq, v, tipo), (a, b)) in enumerate(zip(pasos, niveles)):
            color = AZUL if tipo != "rel" else (VERDE if v < 0 else GRIS)
            bx, bw = x0 + i * hueco + hueco * 0.19, hueco * 0.62
            ya, yb = y0 + al - al * b / maximo, y0 + al - al * a / maximo
            self.set_fill_color(*color)
            self.rect(bx, ya, bw, max(yb - ya, 0.3), style="F")
            signo = "" if tipo != "rel" else ("−" if v < 0 else "+")
            self.txt(bx - 5, ya - 4, signo + _eur(abs(v) if tipo == "rel" else b), 7.2, "B", align="C", w=bw + 10)
            for k, linea in enumerate(etq.split("\n")):
                self.txt(bx - 8, y0 + al + 1.5 + k * 3.2, linea, 7, color=GRIS_TXT, align="C", w=bw + 16)
        self.set_y(y0 + al + 10)

    def lineas(self, etiquetas, series, alto=50, x=15, w=ANCHO, maximo=None, y=None):
        """series: [(nombre, color, valores, discontinua)]. Los valores None no se dibujan.
        Con `y` se dibuja en esa posicion sin comprobar el salto de pagina (para colocarlo junto a otro bloque)."""
        if y is None:
            self.hueco(alto + 16)
            y = self.get_y() + 6
        validos = [v for _, _, vals, _ in series for v in vals if v is not None and not (isinstance(v, float) and math.isnan(v))]
        if maximo is None:
            maximo = _tope(max(validos) * 1.05) if validos else 1.0
        self.leyenda(x + 13, y - 5.5, [(n, c) for n, c, _, _ in series])
        x0, y0, an, al = self._ejes(x, y, w, alto, maximo)
        paso = an / max(len(etiquetas) - 1, 1)
        for nombre, color, vals, disc in series:
            self.set_draw_color(*color)
            self.set_fill_color(*color)
            self.set_line_width(0.55 if not disc else 0.4)
            pts = [(x0 + i * paso, y0 + al - al * v / maximo) if v is not None and not (isinstance(v, float) and math.isnan(v)) else None
                   for i, v in enumerate(vals)]
            if disc:
                self.set_dash_pattern(dash=1.2, gap=1)
            for p, q in zip(pts, pts[1:]):
                if p and q:
                    self.line(p[0], p[1], q[0], q[1])
            self.set_dash_pattern()
            for p in pts:
                if p:
                    r = 0.9 if not disc else 0.6
                    self.ellipse(p[0] - r, p[1] - r, 2 * r, 2 * r, style="F")
        cada = max(1, math.ceil(len(etiquetas) / max(1, int(an // 13))))     # si no caben todas las etiquetas, una de cada N
        for i, e in enumerate(etiquetas):
            if i % cada == 0 or i == len(etiquetas) - 1:
                self.txt(x0 + i * paso - 8, y0 + al + 1.5, e, 6.5, color=GRIS_TXT, align="C", w=16)
        self.set_y(y0 + al + 8)

    def salud(self, hs, benchmark, evolucion, hoy):
        """Indice de salud del stock: nota, barra por zonas, media de la red y evolucion entre visitas."""
        self.hueco(52)
        y = self.get_y()
        zona, color = ("Bajo", ROJO) if hs < 40 else (("Medio", NARANJA) if hs < 70 else ("Bueno", VERDE))
        self.txt(15, y + 1, _n(hs, 1), 30, "B")
        ancho_nota = self.get_string_width(self.tx(_n(hs, 1)))
        self.txt(15 + ancho_nota + 2, y + 8.5, "sobre 100", 9, color=GRIS_TXT)
        self.set_fill_color(*color)
        self.rect(15, y + 15.5, 3, 3, style="F")
        self.txt(19.5, y + 15.3, f"Nivel {zona.lower()}", 8.5, "B")
        # barra 0-100 con sus tres zonas y la marca de la farmacia
        bx, by, bw = 15, y + 23, 62
        for desde, hasta, c in ((0, 40, (254, 226, 226)), (40, 70, (254, 243, 199)), (70, 100, (209, 250, 229))):
            self.set_fill_color(*c)
            self.rect(bx + bw * desde / 100, by, bw * (hasta - desde) / 100, 3.2, style="F")
        self.set_fill_color(*TINTA)
        self.rect(bx + bw * min(max(hs, 0), 100) / 100 - 0.4, by - 1.2, 0.8, 5.6, style="F")
        for v in (0, 40, 70, 100):
            self.txt(bx + bw * v / 100 - 5, by + 4, str(v), 6.3, color=GRIS_TXT, align="C", w=10)
        if benchmark and benchmark.get("media_red") is not None:
            dif = hs - benchmark["media_red"]
            self.txt(15, by + 9.5, f"Media de la red ({benchmark['n_farmacias']} farmacia(s)): {_n(benchmark['media_red'], 1)}  ·  "
                                   f"{'+' if dif >= 0 else '−'}{_n(abs(dif), 1)} puntos", 7.5, color=GRIS_TXT)
        puntos = list(evolucion or [])
        if not puntos or puntos[-1][0].normalize() < hoy.normalize():
            puntos.append((hoy, hs))
        else:
            puntos[-1] = (puntos[-1][0], hs)
        if len(puntos) >= 2:
            self.lineas([f"{f:%d/%m/%y}" for f, _ in puntos], [("Evolución del índice entre visitas", AZUL, [v for _, v in puntos], False)],
                        alto=30, x=88, w=107, maximo=100, y=y + 6)
            dif = puntos[-1][1] - puntos[0][1]
            self.txt(88 + 13, y + 43, f"Desde la primera medición ({puntos[0][0]:%d/%m/%Y}): {'+' if dif >= 0 else '−'}{_n(abs(dif), 1)} puntos.", 7.5,
                     color=GRIS_TXT)
        else:
            self.f(8, "I", GRIS_TXT)
            self.set_xy(92, y + 12)
            self.multi_cell(100, 4, self.tx("Todavía no hay evolución que enseñar: es la primera medición. A partir de la próxima visita "
                                            "aquí se verá cómo cambia el índice."), align="L")
        self.set_y(y + 50)

    def barras_h(self, etiquetas, valores, color=AZUL, textos=None, col_etq=42):
        self.hueco(len(etiquetas) * 6 + 6)
        y = self.get_y() + 1
        maximo = max(max(valores), 1e-9)
        area = ANCHO - col_etq - 48
        for i, (e, v) in enumerate(zip(etiquetas, valores)):
            yy = y + i * 6
            self.txt(15, yy + 0.6, _corta(e, 26), 7.5, align="R", w=col_etq - 2)
            self.set_fill_color(*color)
            self.rect(15 + col_etq, yy, max(area * v / maximo, 0.3), 4.2, style="F")
            self.txt(15 + col_etq + area * v / maximo + 1.5, yy + 0.6, textos[i] if textos else _eur(v), 7.3)
        self.set_y(y + len(etiquetas) * 6 + 3)

    def barras_grupo(self, categorias, series, alto=46):
        """series: [(nombre, color, valores)]."""
        self.hueco(alto + 16)
        y = self.get_y() + 6
        maximo = _tope(max(max(v) for _, _, v in series) * 1.12) if any(max(v) > 0 for _, _, v in series) else 1.0
        self.leyenda(15 + 13, y - 5.5, [(n, c) for n, c, _ in series])
        x0, y0, an, al = self._ejes(15, y, ANCHO, alto, maximo)
        hueco = an / len(categorias)
        bw = hueco * 0.7 / len(series)
        for i, cat in enumerate(categorias):
            for j, (_, color, vals) in enumerate(series):
                v = vals[i]
                bx = x0 + i * hueco + hueco * 0.15 + j * bw
                alt = al * v / maximo
                self.set_fill_color(*color)
                self.rect(bx + 0.3, y0 + al - alt, bw - 0.6, max(alt, 0.2), style="F")
                self.txt(bx - 4, y0 + al - alt - 3.6, _eur(v), 6.6, align="C", w=bw + 8)
            self.txt(x0 + i * hueco, y0 + al + 1.5, cat, 7, color=GRIS_TXT, align="C", w=hueco)
        self.set_y(y0 + al + 8)


# ---------------------------------------------------------------------------
# Informe
# ---------------------------------------------------------------------------
def generar_informe_completo(d):
    """bytes del PDF. `d`: farmacia, an (analisis), y opcionales hs (indice de salud), benchmark, hs_evolucion
    [(fecha, nota)], ahorro_confirmado, n_pedidos, inversion_confirmada, ahorro_potencial, abc (resumen), abc_fuente, generado."""
    an = d["an"]
    q, p, cap, plan, labs, base = an["calidad"], an["params"], an["capital"], an["plan"], an["labs"], an["base"]
    generado = d.get("generado") or datetime.now()
    f_inv = q["fecha_inventario"]
    fecha_datos = f_inv.strftime("%d/%m/%Y") if f_inv is not None else "fecha de inventario sin confirmar"
    pdf = _Doc(d["farmacia"], fecha_datos, generado)
    pdf.set_title(pdf.tx(f"Informe de stock y compras - {d['farmacia']}"))
    pdf.set_author(APP_NAME)
    liberar = plan[plan["Bloque"] == "Liberar capital"]
    roturas = plan[plan["Bloque"] == "Recuperar ventas"]
    res = an["res_interanual"] or {}
    venta_coste = float(labs["Venta_12m_Coste_EUR"].sum()) if not labs.empty else 0.0
    hay_pvp = bool(q["tiene_pvp"]) and not labs.empty and labs["Margen_12m_EUR"].notna().any()

    # ===================== 1. Resumen ejecutivo =====================
    pdf.add_page()
    pdf.set_fill_color(*AZUL)
    pdf.rect(0, 0, 210, 44, style="F")
    pdf.set_fill_color(*VERDE)
    pdf.rect(0, 44, 210, 1.6, style="F")
    pdf.txt(15, 11, "INFORME DE STOCK Y COMPRAS", 9, "B", color=(219, 234, 254))
    pdf.txt(15, 17, _corta(d["farmacia"], 44), 22, "B", color=(255, 255, 255))
    hist_txt = f"Ventas de {q['hist_desde']:%m/%Y} a {q['hist_hasta']:%m/%Y} ({q['meses_hist']} meses)" if q.get("hist_hasta") is not None else "Sin histórico de ventas con fechas"
    pdf.txt(15, 30, f"Inventario a {fecha_datos}  ·  {hist_txt}  ·  {_n(q['n_refs'])} referencias", 9, color=(219, 234, 254))
    pdf.set_y(52)

    pct = cap["liberable"] / cap["actual"] * 100 if cap["actual"] > 0 else 0
    perdida = float(roturas["Venta_Perdida_Mes_EUR"].sum())
    var = res.get("var_pct")
    pdf.kpis([
        ("Stock en la farmacia", _eur(cap["actual"]), "valorado a precio de coste"),
        ("Stock de más", _eur(cap["liberable"]), f"el {pct:.0f} % del stock está por encima de lo necesario"),
        ("Ventas perdidas por roturas", _eur(perdida) + "/mes", f"{len(roturas)} productos habituales sin stock"),
        ("Ventas, últimos 12 meses", _eur(res.get("total_12m", 0)), f"{var:+.1f} % frente al año anterior".replace(".", ",") if var is not None else "sin año anterior para comparar"),
    ])

    pdf.titulo("Lo más importante")
    for i, (tit, texto) in enumerate(hallazgos(d), 1):
        pdf.hueco(18)
        y = pdf.get_y()
        pdf.set_fill_color(*AZUL)
        pdf.ellipse(15, y, 7, 7, style="F")
        pdf.txt(15, y + 1.7, str(i), 10, "B", color=(255, 255, 255), align="C", w=7)
        pdf.txt(25, y + 0.2, tit, 10, "B")
        pdf.f(9, "", TINTA)
        pdf.set_xy(25, y + 5.2)
        pdf.multi_cell(ANCHO - 10, 4.5, pdf.tx(texto), align="L", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

    pdf.titulo("Del stock actual al stock que la farmacia necesita", reserva=66, sub=
               f"Stock objetivo: {p['meses_objetivo_medicamento']:g} meses de venta en medicamento y {p['meses_objetivo_parafarmacia']:g} en parafarmacia. "
               "En verde, lo que sobra; en gris, lo que habría que reponer.")
    pasos = [("Stock actual", cap["actual"], "abs")]
    pasos += [(e, -v, "rel") for e, v in (("Sin ventas\nen 12 meses", cap["zombie"]), ("Sin ventas\nen 6 meses", cap["uvi"]), ("Sobrestock", cap["sobrestock"])) if v >= 0.5]
    if cap["reponer"] >= 0.5:
        pasos.append(("Reponer roturas\ny bajo mínimo", cap["reponer"], "rel"))
    pasos.append(("Stock óptimo", cap["optimo"], "total"))
    pdf.cascada(pasos, alto=48)

    if not liberar.empty:
        res_acc = (liberar.groupby("Accion").agg(n=(COL_CN, "count"), valor=("Valor_Afectado_EUR", "sum"), rec=("EUR_Recuperable", "sum"))
                   .sort_values(["rec", "valor"], ascending=False).reset_index())
        filas = [[r["Accion"], _n(r["n"]), _eur(r["valor"]), _eur(r["rec"])] for _, r in res_acc.head(5).iterrows()]
        if len(res_acc) > 5:
            resto = res_acc.iloc[5:]
            filas.append(["Otras acciones", _n(resto["n"].sum()), _eur(resto["valor"].sum()), _eur(resto["rec"].sum())])
        pdf.titulo("Qué proponemos", f"Con el plan de acción se recuperan {_eur(float(liberar['EUR_Recuperable'].sum()))} de los "
                                     f"{_eur(float(liberar['Valor_Afectado_EUR'].sum()))} afectados. El detalle producto a producto está en la sección «Plan de acción».",
                   reserva=8 + 6.5 * len(filas))
        pdf.tabla(["Acción", "Productos", "Stock afectado", "Recuperable"], filas, (92, 24, 32, 32), ("LEFT", "RIGHT", "RIGHT", "RIGHT"), tam=8.5,
                  entera=True)

    # ===================== 2. Salud del stock, ventas y laboratorios =====================
    pdf.add_page()
    if d.get("hs") is not None:
        pdf.titulo("Salud del stock",
                   f"Una nota de 0 a 100: 100 sería tener cada producto con el stock justo para {HEALTH_SCORE_MESES_DEFAULT:g} meses de venta. "
                   "Baja con las roturas, con el exceso y con el producto que no se vende.", reserva=52)
        pdf.salud(float(d["hs"]), d.get("benchmark"), d.get("hs_evolucion"), pd.Timestamp(generado))
    inter = an["interanual"]
    if not inter.empty and inter["Actual"].notna().any():
        pdf.titulo("Ventas mes a mes", f"Euros valorados con: {an['fuente_ventas']}.", reserva=88)
        series = [("Últimos 12 meses", AZUL, [None if pd.isna(v) else float(v) for v in inter["Actual"]], False)]
        if inter["Anterior"].notna().any():
            series.insert(0, ("12 meses anteriores", GRIS, [None if pd.isna(v) else float(v) for v in inter["Anterior"]], True))
        pdf.lineas(inter["Mes"].tolist(), series)
        dias = cap["actual"] / (venta_coste / 365) if venta_coste > 0 else None
        tarjetas = [("Ventas 12 meses", _eur(res.get("total_12m", 0)), an["fuente_ventas"].split(" (")[0]),
                    ("Frente al año anterior", (f"{var:+.1f} %".replace(".", ",") if var is not None else "—"),
                     f"sobre {res.get('meses_comparables', 0)} meses comparables"),
                    ("Días de stock", _n(dias) if dias else "—", "días que duraría el stock al ritmo de venta actual"),
                    ("Rotación anual", (_n(venta_coste / cap["actual"], 1) + " veces") if cap["actual"] > 0 else "—", "ventas a coste / stock")]
        pdf.kpis(tarjetas)
        if res.get("mejor_mes"):
            pdf.nota(f"Mejor mes frente al año anterior: {res['mejor_mes'][0]} ({res['mejor_mes'][1]:+.0f} %). Peor: {res['peor_mes'][0]} ({res['peor_mes'][1]:+.0f} %).")

    if not labs.empty:
        col_venta = "Venta_12m_PVP_EUR" if hay_pvp else "Venta_12m_Coste_EUR"
        pdf.titulo("Laboratorios", "Los diez con más stock. Rotación = veces al año que se vende su stock; cuanto más alta, mejor trabaja ese dinero.",
                   reserva=10 + 6 * min(len(labs), 10))
        cab = ["Laboratorio", "Refs.", "Stock", "Venta 12 m" + (" (PVP)" if hay_pvp else " (coste)"), "Rotación", "Stock de más"] + (["Margen"] if hay_pvp else ["Roturas"])
        filas = []
        for _, r in labs.head(10).iterrows():
            ultimo = (f"{_eur(r['Margen_12m_EUR'])} · {r['Margen_Pct']:.0f} %" if pd.notna(r["Margen_12m_EUR"]) and pd.notna(r["Margen_Pct"]) else "—") if hay_pvp else _n(r["Roturas"])
            filas.append([_corta(r[COL_LAB], 26), _n(r["Referencias"]), _eur(r["Stock_EUR"]), _eur(0 if pd.isna(r[col_venta]) else r[col_venta]),
                          (_n(r["Rotacion_Anual"], 1) + "×") if pd.notna(r["Rotacion_Anual"]) else "—", _eur(r["Capital_Parado_EUR"]), ultimo])
        pdf.tabla(cab, filas, (44, 13, 24, 30, 18, 24, 27), ("LEFT", "RIGHT", "RIGHT", "RIGHT", "RIGHT", "RIGHT", "RIGHT"), entera=True)
        parados = labs[labs["Capital_Parado_EUR"] > 0].nlargest(8, "Capital_Parado_EUR")
        if not parados.empty:
            pdf.titulo("Dónde está el stock de más", "Stock por encima del objetivo, por laboratorio (sin ventas + sobrestock).",
                       reserva=6 * len(parados) + 6)
            pdf.barras_h(parados[COL_LAB].tolist(), parados["Capital_Parado_EUR"].tolist(), color=VERDE,
                         textos=[f"{_eur(v)}  ·  {v / r * 100:.0f} % de su stock" if r > 0 else _eur(v)
                                 for v, r in zip(parados["Capital_Parado_EUR"], parados["Stock_EUR"])])
        if hay_pvp:
            mg = labs[labs["Venta_12m_PVP_EUR"] > 0].nlargest(8, "Margen_12m_EUR")
            if not mg.empty:
                pdf.titulo("Qué laboratorios dejan más margen", "Margen de 12 meses = ventas a PVP sin IVA − coste de lo vendido.",
                           reserva=6 * len(mg) + 6)
                pdf.barras_h(mg[COL_LAB].tolist(), mg["Margen_12m_EUR"].clip(lower=0).tolist(),
                             textos=[f"{_eur(m)}  ·  {pc:.0f} % sobre venta" for m, pc in zip(mg["Margen_12m_EUR"], mg["Margen_Pct"].fillna(0))])

    # ===================== 3. Plan de accion =====================
    pdf.titulo("Plan de acción: liberar capital",
               f"Las {min(len(liberar), 20)} acciones que más dinero recuperan, de {len(liberar)}. La lista completa se entrega en Excel.", reserva=60)
    if liberar.empty:
        pdf.parrafo("No hay stock por encima del objetivo: nada que liberar.")
    else:
        filas = [[str(r["Prioridad"]), _corta(r[COL_NOMBRE], 40), _corta(r[COL_LAB], 16), _corta(r["Accion"], 34), _n(r["Uds_Afectadas"]),
                  _eur(r["EUR_Recuperable"]), _corta(str(r["Plazo"]).replace(".", ","), 18)] for _, r in liberar.head(20).iterrows()]
        pdf.tabla(["#", "Producto", "Laboratorio", "Qué hacer", "Uds.", "Recuperable", "Plazo"], filas,
                  (7, 51, 23, 46, 11, 20, 22), ("RIGHT", "LEFT", "LEFT", "LEFT", "RIGHT", "RIGHT", "LEFT"), tam=7.3)
        pdf.nota(f"Devolución al proveedor: hasta {p['dias_devolucion_refrigerado']} días desde la recepción en refrigerados y {p['dias_devolucion_resto']} en el resto. "
                 f"Al liquidar se supone recuperar el {100 - p['dto_liquidacion_pct']:g} % del coste.")
    pdf.titulo("Plan de acción: recuperar ventas", "Productos con demanda y sin stock. «Pierde/mes» es lo que deja de entrar cada mes mientras siga la rotura.",
               reserva=10 + 6 * min(len(roturas), 6))
    if roturas.empty:
        pdf.parrafo("No hay roturas de productos con demanda.")
    else:
        vmm = base.drop_duplicates(COL_CN).set_index(COL_CN)["Venta_Media_Mensual"]
        filas = [[_corta(r[COL_NOMBRE], 46), _corta(r[COL_LAB], 18), _n(vmm.get(r[COL_CN], 0), 1), _n(r["Uds_Afectadas"]), _eur(r["Valor_Afectado_EUR"]),
                  _eur(r["Venta_Perdida_Mes_EUR"])] for _, r in roturas.head(14).iterrows()]
        pdf.tabla(["Producto", "Laboratorio", "Vende/mes", "Pedir (uds.)", "Coste pedido", "Pierde/mes"], filas,
                  (64, 30, 20, 21, 23, 22), ("LEFT", "LEFT", "RIGHT", "RIGHT", "RIGHT", "RIGHT"))
        if len(roturas) > 14:
            pdf.nota(f"Se muestran 14 de {len(roturas)}; el resto, en el Excel.")

    # ===================== 4. Caducidades, roturas repetidas, compras, ABC =====================
    cad_res, cad_det = an["cad_res"], an["cad_det"]
    if q["pct_caducidad"] is not None and not cad_det.empty:
        pdf.titulo("Caducidades", "Stock que caduca en cada tramo y, en rojo, la parte que no llegará a venderse al ritmo de venta actual.", reserva=70)
        tramos = cad_res[cad_res["Tramo"] != "Más de 12 meses"]
        pdf.barras_grupo(tramos["Tramo"].tolist(), [("Stock que caduca", GRIS, tramos["Valor_EUR"].tolist()),
                                                    ("No se venderá a tiempo", ROJO, tramos["Valor_Riesgo_EUR"].tolist())])
        urg = cad_det[cad_det["Valor_Riesgo_EUR"] > 0].head(12)
        if not urg.empty:
            pdf.tabla(["Producto", "Laboratorio", "Caduca", "Stock", "Valor", "En riesgo"],
                      [[_corta(r[COL_NOMBRE], 46), _corta(r[COL_LAB], 18), f"{r['Fecha_Caducidad']:%d/%m/%Y}", _n(r["Stock"]), _eur(r["Valor_EUR"]),
                        _eur(r["Valor_Riesgo_EUR"])] for _, r in urg.iterrows()],
                      (66, 30, 22, 16, 22, 24), ("LEFT", "LEFT", "LEFT", "RIGHT", "RIGHT", "RIGHT"))

    rr = an["rot_rec"]
    if not rr.empty:
        pdf.titulo("Roturas que se repiten", "Productos habituales que se han quedado sin stock dos o más veces: conviene subirles el stock mínimo.",
                   reserva=10 + 6 * min(len(rr), 6))
        pdf.tabla(["Producto", "Laboratorio", "Veces", "Cómo se sabe", "Uds. no vendidas (est.)"],
                  [[_corta(r[COL_NOMBRE], 48), _corta(r[COL_LAB], 18), _n(r["Veces"]), r["Evidencia"], _n(r["Uds_Perdidas_Est"])] for _, r in rr.head(12).iterrows()],
                  (66, 28, 14, 46, 26), ("LEFT", "LEFT", "RIGHT", "LEFT", "RIGHT"))

    dto = an["dto_lab"]
    if not dto.empty or d.get("n_pedidos"):
        pdf.titulo("Compras y descuentos", reserva=34 + 6 * min(len(dto), 8))
        bruto, ahorro = float(dto["Bruto_EUR"].sum()) if not dto.empty else 0.0, float(dto["Ahorro_EUR"].sum()) if not dto.empty else 0.0
        perd = an["dto_perdidos"]
        pdf.kpis([
            ("Ahorro confirmado", _eur(d.get("ahorro_confirmado", 0), 2), f"en {d.get('n_pedidos', 0)} pedido(s) confirmados por {_eur(d.get('inversion_confirmada', 0))}"),
            ("Descuento medio", (f"{ahorro / bruto * 100:.1f} %".replace(".", ",")) if bruto > 0 else "—", f"sobre {_eur(bruto)} de compras a PVL"),
            ("Dejado de ganar", _eur(float(perd["Perdido_EUR"].sum()), 2) if perd is not None else "—",
             "tramos no alcanzados o no aplicados" if perd is not None else "hacen falta las ofertas con sus tramos"),
            ("Ahorro posible próximo pedido", _eur(d.get("ahorro_potencial", 0), 2), "estimación: no cuenta hasta confirmar el pedido"),
        ])
        if not dto.empty:
            pdf.tabla(["Laboratorio", "Líneas", "Compras a PVL", "Descuento conseguido", "Dto. medio", "Dejado de ganar"],
                      [[_corta(r[COL_LAB], 30), _n(r["Lineas"]), _eur(r["Bruto_EUR"]), _eur(r["Ahorro_EUR"], 2), f"{r['Dto_Medio_Pct']:.1f} %".replace(".", ","),
                        _eur(r["Perdido_EUR"], 2) if perd is not None else "—"] for _, r in dto.head(8).iterrows()],
                      (50, 16, 30, 32, 22, 30), ("LEFT", "RIGHT", "RIGHT", "RIGHT", "RIGHT", "RIGHT"))
        pdf.nota("«Ahorro confirmado» suma solo los pedidos confirmados. El ahorro del próximo pedido es una estimación con las ofertas actuales.")

    abc = d.get("abc")
    if abc is not None and float(abc["Venta_12m_EUR"].sum()) > 0:
        a = abc.set_index("Clase_ABC")
        pdf.titulo("Surtido: qué vende y qué ocupa (ABC)",
                   f"Los productos A suman el 80 % de las ventas; B, el 15 % siguiente; C, el 5 % final. Ventas valoradas con {d.get('abc_fuente', 'PVL')}.",
                   reserva=52)
        pdf.tabla(["Clase", "Referencias", "% refs.", "Ventas 12 m", "% ventas", "Stock", "% stock", "Stock de más"],
                  [[c, _n(r["Referencias"]), f"{r['Pct_Referencias']:.0f} %", _eur(r["Venta_12m_EUR"]), f"{r['Pct_Ventas']:.0f} %", _eur(r["Stock_EUR"]),
                    f"{r['Pct_Stock']:.0f} %", _eur(r["Exceso_EUR"])] for c, r in a.iterrows()],
                  (26, 22, 18, 28, 18, 26, 18, 24), ("LEFT", "RIGHT", "RIGHT", "RIGHT", "RIGHT", "RIGHT", "RIGHT", "RIGHT"), tam=8, entera=True)
        cola = float(a.loc[[c for c in ("C", "Sin ventas") if c in a.index], "Pct_Stock"].sum())
        pdf.parrafo(f"Los productos A son el {a.at['A', 'Pct_Referencias']:.0f} % de las referencias y ocupan el {a.at['A', 'Pct_Stock']:.0f} % del stock. "
                    f"Los que casi no venden (C y sin ventas) ocupan el {cola:.0f} %: ahí está el margen para adelgazar el surtido.", 8.5)

    # ===================== 5. Como leer el informe =====================
    pdf.titulo("Cómo leer este informe", reserva=48)
    pdf.vinetas([
        "Todo el stock se valora a precio de coste: PVL" + (f" menos un {p['descuento_compra_pct']:g} % de descuento de compra." if p["descuento_compra_pct"] else "."),
        f"Stock objetivo: {p['meses_objetivo_medicamento']:g} meses de venta prevista en medicamento, {p['meses_objetivo_parafarmacia']:g} en parafarmacia y "
        f"{p['meses_objetivo_no_caducable']:g} en productos no caducables. Lo que supera ese nivel es «stock de más».",
        "Sin ventas en 12 meses (zombie): producto con stock que no se ha vendido ni una vez en el último año. Sin ventas en 6 meses: aviso previo.",
        "Rotura: producto con demanda y sin stock. La venta perdida se valora " + ("a precio de venta (PVP sin IVA)." if q["tiene_pvp"] else "a PVL, porque los datos no traen PVP."),
        "El capital parado y la venta perdida no se suman: uno es dinero que ya está en la estantería y la otra, dinero que deja de entrar cada mes.",
    ])
    if q["avisos"]:
        pdf.titulo("Sobre los datos", reserva=8 + 6 * len(q["avisos"]))
        pdf.vinetas(q["avisos"])
    return bytes(pdf.output())
