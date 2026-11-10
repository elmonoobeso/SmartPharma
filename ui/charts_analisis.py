"""Graficos de los analisis nuevos de BI y Auditoria (capital liberable, caducidades, ventas, margen, descuentos).

Criterios: un solo eje por grafico, leyenda siempre que hay dos series, etiquetas en tinta
neutra (el color lo lleva la marca) y rojo reservado para lo que es un problema.
"""
import plotly.graph_objects as go

from config.settings import COLORS, COL_LAB

_GRIS = "#94A3B8"
_REJILLA = "#E2E8F0"


def _base_layout(fig, titulo, alto):
    fig.update_layout(
        title={"text": titulo, "font": {"size": 15, "color": COLORS["text"]}}, height=alto,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font={"family": "Inter", "color": COLORS["text"]},
        separators=",.", margin=dict(l=10, r=20, t=50, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1, title=""))
    # Sin esto las etiquetas largas de los ejes (nombres de laboratorio) se cortan con margenes estrechos
    fig.update_xaxes(automargin=True)
    fig.update_yaxes(automargin=True)
    return fig


def _eur(v):
    return f"{v:,.0f} €".replace(",", ".")


def grafico_capital_liberable(cap):
    """Cascada del stock actual al stock optimo: lo que sale (zombie, UVI, sobrestock) y lo que hay que reponer."""
    if not cap or cap["actual"] <= 0:
        return None
    pasos = [("Stock actual", cap["actual"], "absolute"), ("Zombie", -cap["zombie"], "relative"), ("UVI", -cap["uvi"], "relative"),
             ("Sobrestock", -cap["sobrestock"], "relative"), ("Reponer roturas<br>y bajo objetivo", cap["reponer"], "relative"),
             ("Stock óptimo", cap["optimo"], "total")]
    pasos = [p for p in pasos if p[2] != "relative" or abs(p[1]) >= 0.5]
    fig = go.Figure(go.Waterfall(
        x=[p[0] for p in pasos], y=[p[1] for p in pasos], measure=[p[2] for p in pasos],
        text=[("−" if p[1] < 0 else "+" if p[2] == "relative" else "") + _eur(abs(p[1])) for p in pasos],
        textposition="outside", textfont={"color": COLORS["text"], "size": 12},
        decreasing={"marker": {"color": COLORS["secondary"]}}, increasing={"marker": {"color": _GRIS}},
        totals={"marker": {"color": COLORS["primary"]}}, connector={"line": {"color": _REJILLA, "width": 1}},
        hovertemplate="<b>%{x}</b><br>%{text}<extra></extra>"))
    _base_layout(fig, "Del stock actual al stock óptimo (a coste)", 380)
    fig.update_layout(showlegend=False, yaxis=dict(title="€", gridcolor=_REJILLA, rangemode="tozero"), xaxis=dict(title=""))
    fig.update_yaxes(range=[0, max(cap["actual"], cap["optimo"]) * 1.15])
    return fig


def grafico_caducidades(resumen):
    """Por tramo: valor del stock que caduca y la parte que, al ritmo de venta actual, no se vendera a tiempo."""
    if resumen is None or resumen["Valor_EUR"].sum() <= 0:
        return None
    df = resumen[resumen["Tramo"] != "Más de 12 meses"]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=df["Tramo"], y=df["Valor_EUR"], name="Stock que caduca en el tramo", marker_color=_GRIS,
                         text=[_eur(v) for v in df["Valor_EUR"]], textposition="outside", textfont={"color": COLORS["text"]},
                         customdata=df["Productos"], hovertemplate="<b>%{x}</b><br>%{text} · %{customdata} productos<extra></extra>"))
    fig.add_trace(go.Bar(x=df["Tramo"], y=df["Valor_Riesgo_EUR"], name="No se venderá a tiempo", marker_color=COLORS["danger"],
                         text=[_eur(v) for v in df["Valor_Riesgo_EUR"]], textposition="outside", textfont={"color": COLORS["text"]},
                         hovertemplate="<b>%{x}</b><br>En riesgo real: %{text}<extra></extra>"))
    _base_layout(fig, "Calendario de caducidades (a coste)", 360)
    fig.update_layout(barmode="group", bargap=0.3, bargroupgap=0.06, yaxis=dict(title="€", gridcolor=_REJILLA, rangemode="tozero"))
    fig.update_yaxes(range=[0, max(1.0, float(df["Valor_EUR"].max())) * 1.2])
    return fig


def grafico_ventas_interanual(tabla, fuente=""):
    """Ultimos 12 meses frente a los 12 anteriores, mes a mes."""
    if tabla is None or tabla.empty or tabla["Actual"].notna().sum() == 0:
        return None
    fig = go.Figure()
    if tabla["Anterior"].notna().any():
        fig.add_trace(go.Scatter(x=tabla["Mes"], y=tabla["Anterior"], name="12 meses anteriores", mode="lines+markers",
                                 line=dict(color=_GRIS, width=2, dash="dot"), marker=dict(size=6),
                                 hovertemplate="%{y:,.0f} €<extra>Año anterior</extra>"))
    fig.add_trace(go.Scatter(x=tabla["Mes"], y=tabla["Actual"], name="Últimos 12 meses", mode="lines+markers",
                             line=dict(color=COLORS["primary"], width=2.5), marker=dict(size=8),
                             hovertemplate="%{y:,.0f} €<extra>Últimos 12 meses</extra>"))
    _base_layout(fig, "Ventas mes a mes", 340)
    fig.update_layout(hovermode="x unified", yaxis=dict(title="€", gridcolor=_REJILLA, rangemode="tozero"), xaxis=dict(title=""))
    return fig


def grafico_margen_laboratorios(labs, n=15):
    """Margen en euros de los ultimos 12 meses por laboratorio (los `n` mayores)."""
    if labs is None or labs.empty or labs["Margen_12m_EUR"].notna().sum() == 0:
        return None
    df = labs.dropna(subset=["Margen_12m_EUR"])
    df = df[df["Venta_12m_PVP_EUR"] > 0].nlargest(n, "Margen_12m_EUR").sort_values("Margen_12m_EUR")
    if df.empty:
        return None
    fig = go.Figure(go.Bar(
        x=df["Margen_12m_EUR"], y=df[COL_LAB], orientation="h", marker_color=COLORS["primary"],
        text=[f"{_eur(m)} · {p:.0f} %" for m, p in zip(df["Margen_12m_EUR"], df["Margen_Pct"].fillna(0))],
        textposition="outside", textfont={"color": COLORS["text"]},
        customdata=df["Margen_por_EUR_Stock"].fillna(0),
        hovertemplate="<b>%{y}</b><br>Margen 12 m: %{x:,.0f} €<br>Margen por € en stock: %{customdata:.2f} €<extra></extra>"))
    _base_layout(fig, "Margen por laboratorio, últimos 12 meses (PVP sin IVA − coste)", max(300, len(df) * 28 + 90))
    x_max = float(df["Margen_12m_EUR"].max())
    fig.update_layout(showlegend=False, xaxis=dict(title="€", gridcolor=_REJILLA, range=[min(0, float(df["Margen_12m_EUR"].min())), max(1.0, x_max * 1.4)]),
                      yaxis=dict(title=""))
    return fig


def grafico_descuentos(por_lab, con_perdido, n=10):
    """Por laboratorio: descuento conseguido y, si hay ofertas cargadas, lo que se dejo de ganar."""
    if por_lab is None or por_lab.empty:
        return None
    df = por_lab.assign(_t=por_lab["Ahorro_EUR"] + por_lab["Perdido_EUR"]).nlargest(n, "_t").sort_values("_t")
    if df["_t"].sum() <= 0:
        return None
    fig = go.Figure()
    fig.add_trace(go.Bar(x=df["Ahorro_EUR"], y=df[COL_LAB], orientation="h", name="Descuento conseguido", marker_color=COLORS["primary"],
                         text=[f"{_eur(a)} · {d:.1f} %" for a, d in zip(df["Ahorro_EUR"], df["Dto_Medio_Pct"])],
                         textposition="outside", textfont={"color": COLORS["text"]},
                         hovertemplate="<b>%{y}</b><br>Conseguido: %{x:,.2f} €<extra></extra>"))
    if con_perdido:
        fig.add_trace(go.Bar(x=df["Perdido_EUR"], y=df[COL_LAB], orientation="h", name="Dejado de ganar", marker_color=COLORS["warning"],
                             text=[_eur(v) if v > 0 else "" for v in df["Perdido_EUR"]], textposition="outside",
                             textfont={"color": COLORS["text"]}, hovertemplate="<b>%{y}</b><br>Dejado de ganar: %{x:,.2f} €<extra></extra>"))
    _base_layout(fig, "Descuentos por laboratorio", max(300, len(df) * (44 if con_perdido else 28) + 90))
    fig.update_layout(barmode="group", bargroupgap=0.08, yaxis=dict(title=""),
                      xaxis=dict(title="€", gridcolor=_REJILLA, range=[0, max(1.0, float(df[["Ahorro_EUR", "Perdido_EUR"]].max().max()) * 1.45)]))
    return fig


def grafico_abc(resumen):
    """Por clase ABC: que parte de las ventas genera y que parte del stock ocupa."""
    if resumen is None or resumen["Venta_12m_EUR"].sum() <= 0:
        return None
    fig = go.Figure()
    fig.add_trace(go.Bar(x=resumen["Clase_ABC"], y=resumen["Pct_Ventas"], name="% de las ventas", marker_color=COLORS["primary"],
                         text=[f"{v:.0f} %" for v in resumen["Pct_Ventas"]], textposition="outside", textfont={"color": COLORS["text"]},
                         hovertemplate="<b>Clase %{x}</b><br>%{y:.1f} % de las ventas<extra></extra>"))
    fig.add_trace(go.Bar(x=resumen["Clase_ABC"], y=resumen["Pct_Stock"], name="% del stock", marker_color=_GRIS,
                         text=[f"{v:.0f} %" for v in resumen["Pct_Stock"]], textposition="outside", textfont={"color": COLORS["text"]},
                         customdata=resumen["Referencias"], hovertemplate="<b>Clase %{x}</b><br>%{y:.1f} % del stock · %{customdata} referencias<extra></extra>"))
    _base_layout(fig, "Qué vende y qué ocupa cada clase", 320)
    fig.update_layout(barmode="group", bargap=0.3, bargroupgap=0.06, yaxis=dict(title="%", gridcolor=_REJILLA, range=[0, 105]))
    return fig
