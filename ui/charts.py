import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import timedelta, date
from io import BytesIO
from config.settings import COLORS, COL_CN, COL_LAB, COL_NOMBRE, COL_STOCK, COL_PVL, COL_MOLECULA
from core.business import heuristica_tipo_producto

def exportar_pedido_excel(df_pedido):
    output = BytesIO()
    cols_export = [COL_CN, COL_NOMBRE, COL_LAB, COL_STOCK, "Venta_Media_Mensual", "Safety_Stock",
        "Cantidad_A_Pedir", "Precio_Unitario", "Descuento_Aplicado", "Coste_Con_Dto", "Ahorro", "Tier_Aplicado"]
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        col_lab = COL_LAB if COL_LAB in df_pedido.columns else None
        if col_lab and df_pedido[col_lab].nunique() > 1:
            for lab in sorted(df_pedido[col_lab].dropna().unique()):
                dl = df_pedido[df_pedido[col_lab] == lab]
                cv = [c for c in cols_export if c in dl.columns]
                dl[cv].to_excel(writer, sheet_name=str(lab)[:31].replace("/","-"), index=False)
        else:
            cv = [c for c in cols_export if c in df_pedido.columns]
            lab_name = str(df_pedido[col_lab].iloc[0])[:31] if col_lab and not df_pedido.empty else "Pedido"
            df_pedido[cv].to_excel(writer, sheet_name=lab_name, index=False)
    output.seek(0)
    return output

def grafico_gauge_health(score):
    bar_color = COLORS["success"] if score >= 70 else (COLORS["warning"] if score >= 40 else COLORS["danger"])
    fig = go.Figure(go.Indicator(mode="gauge+number", value=score,
        number={"suffix": "%", "font": {"size": 42, "color": COLORS["text"]}},
        gauge={"axis": {"range": [0,100]}, "bar": {"color": bar_color, "thickness": 0.3},
            "bgcolor": "#F1F5F9", "borderwidth": 0,
            "steps": [{"range":[0,40],"color":"#FEE2E2"},{"range":[40,70],"color":"#FEF3C7"},{"range":[70,100],"color":"#D1FAE5"}],
            "threshold": {"line":{"color":COLORS["text"],"width":3},"thickness":0.8,"value":score}},
        title={"text": "Stock Health Score", "font": {"size": 16, "color": COLORS["muted"]}}))
    fig.update_layout(height=280, margin=dict(l=30,r=30,t=50,b=10), paper_bgcolor="rgba(0,0,0,0)", font={"family":"Inter"})
    return fig

def grafico_calendario_reposicion(df_inv, df_ventas_media):
    """Timeline de fechas estimadas de reposicion por laboratorio."""
    if COL_LAB not in df_inv.columns:
        return None
    df_m = df_inv.merge(df_ventas_media[[COL_CN, "Venta_Media_Mensual"]], on=COL_CN, how="left")
    df_m["Venta_Media_Mensual"] = df_m["Venta_Media_Mensual"].fillna(0)
    df_m["Dias_Stock"] = np.where(df_m["Venta_Media_Mensual"] > 0,
        (df_m[COL_STOCK] / (df_m["Venta_Media_Mensual"] / 30.44)), 999)
    # Minimo dias por laboratorio (cuello de botella)
    lab_dias = df_m[df_m["Dias_Stock"] < 999].groupby(COL_LAB)["Dias_Stock"].min().reset_index()
    lab_dias = lab_dias.sort_values("Dias_Stock").head(15)
    if lab_dias.empty:
        return None
    hoy = date.today()
    lab_dias["Fecha_Reposicion"] = lab_dias["Dias_Stock"].apply(
        lambda d: (hoy + timedelta(days=max(0, d - 7))).strftime("%d/%m/%Y"))
    lab_dias["Dias_Stock"] = lab_dias["Dias_Stock"].round(0).astype(int)
    lab_dias_sorted = lab_dias.sort_values("Dias_Stock", ascending=True)
    # Colores por urgencia: un color distinto por tramo
    colores = []
    for d in lab_dias_sorted["Dias_Stock"]:
        if d <= 14: colores.append(COLORS["danger"])
        elif d <= 30: colores.append(COLORS["warning"])
        elif d <= 60: colores.append("#EAB308")
        else: colores.append(COLORS["success"])
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=lab_dias_sorted["Dias_Stock"],
        y=lab_dias_sorted[COL_LAB],
        orientation="h",
        marker_color=colores,
        text=[f"{d}d -> {f}" for d, f in zip(lab_dias_sorted["Dias_Stock"], lab_dias_sorted["Fecha_Reposicion"])],
        textposition="outside",
        hovertemplate="<b>%{y}</b><br>Stock restante: %{x} dias<extra></extra>",
    ))
    fig.add_vline(x=30, line_dash="dash", line_color=COLORS["warning"],
        annotation_text="30 dias", annotation_position="top right")
    fig.update_layout(
        title={"text": "Calendario de Reposicion", "font": {"size": 16}},
        height=max(280, len(lab_dias_sorted) * 30),
        margin=dict(l=50, r=80, t=50, b=40),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "Inter"},
        xaxis=dict(title="Dias de stock restante", gridcolor="#E2E8F0"),
        # El mas urgente arriba (Plotly pinta la primera categoria abajo)
        yaxis=dict(title="", autorange="reversed"),
    )
    return fig

def grafico_pareto_laboratorios(df_pareto):
    if df_pareto.empty: return go.Figure().update_layout(title="Sin datos")
    df_top = df_pareto.head(15).copy()
    fig = go.Figure()
    fig.add_trace(go.Bar(x=df_top[COL_LAB], y=df_top["Valor_Stock"], marker_color=COLORS["primary"], name="Valor Stock", opacity=0.85))
    fig.add_trace(go.Scatter(x=df_top[COL_LAB], y=df_top["Pct_Acumulado"], name="% Acum", yaxis="y2", line=dict(color=COLORS["warning"],width=3)))
    fig.add_hline(y=80, line_dash="dot", line_color=COLORS["danger"], annotation_text="80%", yref="y2", opacity=0.6)
    fig.update_layout(title={"text":"Pareto — Stock por Lab","font":{"size":16}},
        yaxis=dict(title="\u20ac",gridcolor="#E2E8F0"), yaxis2=dict(title="%",overlaying="y",side="right",range=[0,105]),
        height=400, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font={"family":"Inter"},
        xaxis=dict(tickangle=-45), barmode="group", margin=dict(l=50,r=50,t=50,b=80))
    return fig

def grafico_historico_kpi(df_hist_kpi):
    if df_hist_kpi.empty: return None, None
    df_h = df_hist_kpi.copy()
    fig_hs = go.Figure()
    fig_hs.add_trace(go.Scatter(x=df_h["fecha"], y=df_h["health_score"], mode="lines+markers",
        line=dict(color=COLORS["primary"],width=3), marker=dict(size=8)))
    fig_hs.update_layout(title={"text":"Evolucion Health Score","font":{"size":16}}, yaxis=dict(range=[0,100],title="%",gridcolor="#E2E8F0"),
        height=300, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font={"family":"Inter"})
    # Evolucion zombies y roturas (en vez de ahorro duplicado)
    fig_zr = go.Figure()
    if "n_zombies" in df_h.columns:
        fig_zr.add_trace(go.Scatter(x=df_h["fecha"], y=df_h["n_zombies"], mode="lines+markers",
            name="Zombies", line=dict(color=COLORS["warning"], width=2), marker=dict(size=6)))
    if "n_roturas" in df_h.columns:
        fig_zr.add_trace(go.Scatter(x=df_h["fecha"], y=df_h["n_roturas"], mode="lines+markers",
            name="Roturas", line=dict(color=COLORS["danger"], width=2), marker=dict(size=6)))
    fig_zr.update_layout(title={"text":"Evolucion Zombies y Roturas","font":{"size":16}},
        yaxis=dict(title="Productos", gridcolor="#E2E8F0"),
        height=300, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font={"family":"Inter"},
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
    return fig_hs, fig_zr

def grafico_importancia_features(metricas):
    imp = metricas.get("importance", {})
    if not imp: return None
    df_imp = pd.DataFrame({"Feature": list(imp.keys()), "Importancia": list(imp.values())})
    df_imp = df_imp.sort_values("Importancia", ascending=True).tail(10)
    fig = px.bar(df_imp, x="Importancia", y="Feature", orientation="h",
        color_discrete_sequence=[COLORS["primary"]], title="Top Features del Modelo ML")
    fig.update_layout(height=350, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font={"family":"Inter"})
    return fig


def grafico_waterfall_ahorro(pedidos_confirmados):
    """Waterfall chart mostrando ahorro acumulado por pedido/laboratorio."""
    if not pedidos_confirmados:
        return None
    labs = [p.get("laboratorio", "?") for p in pedidos_confirmados]
    fechas = [p.get("fecha", "") for p in pedidos_confirmados]
    ahorros = [p.get("ahorro_ofertas", 0) for p in pedidos_confirmados]
    # Plotly no interpreta "\n": el salto de linea es <br>. El numero de pedido mantiene las etiquetas unicas.
    labels = [f"#{i + 1} {l}<br>{f}" for i, (l, f) in enumerate(zip(labs, fechas))]
    acum = list(np.cumsum(ahorros))
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=labels, y=ahorros, name="Ahorro por Pedido",
        marker_color=[COLORS["primary"] if a > 0 else (COLORS["muted"] if a == 0 else COLORS["danger"]) for a in ahorros],
        text=[f"{a:,.0f}€" for a in ahorros], textposition="outside",
        hovertemplate="<b>%{x}</b><br>Ahorro: %{y:,.2f}€<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=labels, y=acum, name="Acumulado",
        line=dict(color=COLORS["success"], width=3),
        mode="lines+markers+text",
        text=[f"{v:,.0f}€" for v in acum], textposition="top center",
        textfont=dict(size=10, color=COLORS["success"]),
    ))
    fig.update_layout(
        title="💶 Ahorro Generado por Pedido", height=400,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "Inter"},
        xaxis=dict(title="Pedido (Laboratorio)", gridcolor="#E2E8F0"),
        yaxis=dict(title="Ahorro (€)", gridcolor="#E2E8F0"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        showlegend=True,
    )
    return fig


def grafico_dinero_en_riesgo_donut(valor_zombie, valor_sobrestock, coste_oportunidad):
    """Donut chart: composicion instantanea del dinero en riesgo."""
    labels = ["Capital Zombie", "Sobrestock", "Venta Perdida (est.)"]
    values = [max(0, valor_zombie), max(0, valor_sobrestock), max(0, coste_oportunidad * 12)]
    total = sum(values)
    if total == 0:
        return None
    # Mismos colores que el grafico de concentracion de riesgo; venta perdida en gris (es un flujo, no stock)
    colors_donut = [COLORS["danger"], COLORS["primary"], COLORS["muted"]]
    fig = go.Figure(data=[go.Pie(
        labels=labels, values=values,
        hole=0.55, marker=dict(colors=colors_donut),
        textinfo="label+percent", textposition="outside",
        hovertemplate="<b>%{label}</b><br>%{value:,.0f} EUR<br>%{percent}<extra></extra>",
    )])
    fig.update_layout(
        title="💰 Dinero en Riesgo", height=350,
        paper_bgcolor="rgba(0,0,0,0)", font={"family": "Inter"},
        annotations=[dict(text=f"{total:,.0f}€", x=0.5, y=0.5, font_size=18,
                          font_family="Inter", font_weight="bold", showarrow=False)],
        showlegend=False,
    )
    return fig


# --- GRAFICOS NUEVOS DE AUDITORÍA ---
def grafico_distribucion_laboratorios(df_inv, tipo="Todos"):
    """Treemap o BarChart de valor inmovilizado por Laboratorio filtrado por tipo."""
    if df_inv.empty or COL_LAB not in df_inv.columns or COL_PVL not in df_inv.columns: return None
    df = df_inv.copy()
    df["Valor_Stock"] = (df[COL_STOCK] * df[COL_PVL]).fillna(0)
    
    if tipo != "Todos":
        df["Tipo_Prod"] = df.apply(lambda r: heuristica_tipo_producto(r.get(COL_CN,""), r.get(COL_MOLECULA if COL_MOLECULA in df.columns else COL_NOMBRE, "")), axis=1)
        df = df[df["Tipo_Prod"] == tipo]
        
    if df.empty: return None
    
    agg = df.groupby(COL_LAB)["Valor_Stock"].sum().reset_index()
    agg = agg[agg["Valor_Stock"] > 0].sort_values("Valor_Stock", ascending=False)
    if agg.empty: return None
    
    if len(agg) > 15:
        top15 = agg.iloc[:15].copy()
        resto = pd.DataFrame([{COL_LAB: "OTROS LABS", "Valor_Stock": agg.iloc[15:]["Valor_Stock"].sum()}])
        agg = pd.concat([top15, resto], ignore_index=True)
        
    fig = px.bar(agg.sort_values("Valor_Stock", ascending=True), 
                 x="Valor_Stock", y=COL_LAB, orientation="h",
                 title=f"Distribución de Inversión ({tipo})",
                 color_discrete_sequence=[COLORS["primary"]])
    fig.update_layout(height=450, margin={"t":40,"b":10,"l":10,"r":10}, xaxis_title="Euros Invertidos", yaxis_title="")
    return fig

def grafico_long_tail(df_inv, df_vm):
    """Pareto ancho de catalogo vs ventas"""
    if df_inv.empty or df_vm.empty: return None
    df = df_inv.merge(df_vm[[COL_CN, "Venta_Media_Mensual"]], on=COL_CN, how="left")
    df["Venta_Media_Mensual"] = df["Venta_Media_Mensual"].fillna(0)
    
    df = df[(df[COL_STOCK]>0) | (df["Venta_Media_Mensual"]>0)]
    if df.empty: return None
    
    df = df.sort_values(by="Venta_Media_Mensual", ascending=False).reset_index(drop=True)
    total_ventas = df["Venta_Media_Mensual"].sum()
    if total_ventas == 0: return None
    
    df["Pct_Ventas_Acum"] = (df["Venta_Media_Mensual"].cumsum() / total_ventas) * 100
    df["Pct_Refs_Acum"] = ((df.index + 1) / len(df)) * 100
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df["Pct_Refs_Acum"], y=df["Pct_Ventas_Acum"], 
                             mode='lines', line=dict(color=COLORS["success"], width=3),
                             name='Ventas Acumuladas', fill='tozeroy'))
    fig.add_shape(type="line", x0=0, y0=80, x1=20, y1=80, line=dict(color="red", width=1, dash="dash"))
    fig.add_shape(type="line", x0=20, y0=0, x1=20, y1=80, line=dict(color="red", width=1, dash="dash"))
    
    fig.update_layout(title="Análisis de Long Tail (80/20)",
                      xaxis_title="% Referencias del Catálogo",
                      yaxis_title="% Ventas Generadas",
                      height=300, margin={"t":40,"b":40,"l":10,"r":10})
    return fig

def grafico_concentracion_riesgo(df_zombie, df_uvi, df_sobrestock):
    """Muestra qué laboratorios concentran el riesgo (combina los 3 dataframes)"""
    riesgos = []
    
    if not df_zombie.empty and "Valor_Inmovilizado" in df_zombie.columns:
        tz = df_zombie.groupby(COL_LAB)["Valor_Inmovilizado"].sum().reset_index()
        tz.columns = [COL_LAB, "Valor"]; tz["Tipo_Riesgo"] = "Zombie"
        riesgos.append(tz)
        
    if not df_uvi.empty and "Valor_Inmovilizado" in df_uvi.columns:
        tu = df_uvi.groupby(COL_LAB)["Valor_Inmovilizado"].sum().reset_index()
        tu.columns = [COL_LAB, "Valor"]; tu["Tipo_Riesgo"] = "UVI"
        riesgos.append(tu)
        
    if not df_sobrestock.empty and "Valor_Exceso" in df_sobrestock.columns:
        ts = df_sobrestock.groupby(COL_LAB)["Valor_Exceso"].sum().reset_index()
        ts.columns = [COL_LAB, "Valor"]; ts["Tipo_Riesgo"] = "Sobrestock"
        riesgos.append(ts)
        
    if not riesgos: return None
    
    df_r = pd.concat(riesgos, ignore_index=True)
    df_r = df_r[df_r["Valor"] > 0]
    if df_r.empty: return None
    
    top_labs = df_r.groupby(COL_LAB)["Valor"].sum().nlargest(10).index
    df_r_top = df_r[df_r[COL_LAB].isin(top_labs)]
    
    if df_r_top.empty: return None
    fig = px.bar(df_r_top, x="Valor", y=COL_LAB, color="Tipo_Riesgo", orientation="h",
                 title="Concentración de Capital en Riesgo (Top 10 Labs)",
                 color_discrete_map={"Zombie": COLORS["danger"], "UVI": COLORS["warning"], "Sobrestock": COLORS["primary"]})
    fig.update_layout(barmode='stack', yaxis={'categoryorder':'total ascending'}, height=350,
                      margin={"t":40,"b":10,"l":10,"r":10})
    return fig

def grafico_heatmap_cobertura(df_inv, df_vm):
    """Heatmap de meses de stock por molecula o lab principal para ver donde sobra y donde falta."""
    if df_inv.empty or df_vm.empty: return None
    col_agrupacion = COL_MOLECULA if COL_MOLECULA in df_inv.columns else COL_LAB
    if col_agrupacion not in df_inv.columns: return None
    
    df = df_inv.merge(df_vm[[COL_CN, "Venta_Media_Mensual"]], on=COL_CN, how="left")
    df["Venta_Media_Mensual"] = df["Venta_Media_Mensual"].fillna(0)
    
    agg = df.groupby(col_agrupacion).agg(Stock_Total=(COL_STOCK, "sum"), Venta_Media=("Venta_Media_Mensual", "sum")).reset_index()
    agg = agg[agg["Venta_Media"] > 2] 
    if agg.empty: return None
    
    agg["Meses_Cobertura"] = np.where(agg["Venta_Media"] > 0, agg["Stock_Total"] / agg["Venta_Media"], 0)
    agg["Meses_Cobertura"] = agg["Meses_Cobertura"].clip(upper=12).round(1)
    agg = agg.nlargest(25, "Venta_Media").sort_values("Meses_Cobertura", ascending=False)
    
    fig = px.imshow([agg["Meses_Cobertura"].values], 
                    x=agg[col_agrupacion].values, y=["Meses Stock"],
                    color_continuous_scale="RdYlGn_r", aspect="auto")
    fig.update_layout(title="Mapa de Calor: Cobertura de Stock (Meses)", height=250, margin={"t":40,"b":40,"l":10,"r":10})
    return fig

def grafico_estacionalidad_liquidez(df_stats):
    """Gráfico radar histórico para el índice de dependencia"""
    if df_stats.empty: return None
    fig = px.line_polar(df_stats, r="Pct_Ventas", theta="Mes_Nombre", line_close=True,
                        title="Radar de Riesgo de Liquidez Anual (Estacionalidad)")
    fig.update_traces(fill='toself', line_color=COLORS["primary"])
    fig.update_layout(height=350, margin={"t":40,"b":20,"l":20,"r":20})
    return fig


def grafico_roi_laboratorios(df_roi, n_extremo=7):
    """Barras horizontales de ROI por laboratorio: los `n_extremo` mejores y los `n_extremo` peores.

    Los laboratorios sin stock no tienen ROI (no hay inversion): no entran en el ranking
    ni en la media; se listan aparte con laboratorios_sin_stock_roi().
    """
    if df_roi.empty:
        return None
    df_con = df_roi[df_roi["Stock_EUR"] > 0].sort_values("ROI", ascending=False)
    if df_con.empty:
        return None
    n_total = len(df_con)
    recortado = n_total > 2 * n_extremo
    df_sel = pd.concat([df_con.head(n_extremo), df_con.tail(n_extremo)]) if recortado else df_con
    df_top = df_sel.sort_values("ROI", ascending=True)
    media_roi = df_con["ROI"].mean()
    colores = [COLORS["success"] if r >= media_roi else COLORS["danger"] for r in df_top["ROI"]]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df_top["ROI"], y=df_top[COL_LAB], orientation="h",
        marker_color=colores,
        text=[f"ROI: {r:.1f}x | {n} prods" for r, n in zip(df_top["ROI"], df_top["N_Productos"])],
        textposition="outside",
        hovertemplate="<b>%{y}</b><br>ROI: %{x:.2f}x<br>Stock: %{customdata[0]:,.0f}€<br>Venta Anual: %{customdata[1]:,.0f}€<extra></extra>",
        customdata=list(zip(df_top["Stock_EUR"], df_top["Venta_Anual_EUR"])),
    ))
    fig.add_vline(x=media_roi, line_dash="dash", line_color=COLORS["muted"],
        annotation_text=f"Media: {media_roi:.1f}x", annotation_position="top right")
    titulo = "📊 ROI por Laboratorio (Venta Anual / Stock)"
    if recortado:
        # Separador entre los peores (abajo, posiciones 0..n-1) y los mejores (arriba)
        fig.add_hline(y=n_extremo - 0.5, line_dash="dot", line_color=COLORS["muted"], line_width=1)
        titulo += f"<br><sup>{n_extremo} mejores y {n_extremo} peores de {n_total} laboratorios con stock</sup>"
    x_max = float(df_top["ROI"].max()) if len(df_top) else 0.0
    fig.update_layout(
        title=titulo, height=max(300, len(df_top) * 28 + 100),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "Inter"},
        # Margen a la derecha para que quepa el texto fuera de la barra mas larga
        xaxis=dict(title="ROI (veces)", gridcolor="#E2E8F0", range=[0, max(1.0, x_max * 1.45)]),
        yaxis=dict(title=""),
    )
    return fig


def laboratorios_sin_stock_roi(df_roi):
    """Laboratorios con ventas pero sin stock (ROI no aplicable), de mayor a menor venta."""
    if df_roi.empty:
        return df_roi
    return df_roi[(df_roi["Stock_EUR"] <= 0) & (df_roi["Venta_Anual_EUR"] > 0)].sort_values(
        "Venta_Anual_EUR", ascending=False)


# Cache


# ===========================================================================
# LABORATORIO ML — visualizacion de cada fase del pipeline
# ===========================================================================
def _mes_a_fecha(periodo):
    return pd.Timestamp(f"{periodo}-01")

def grafico_timeline_split(pipeline):
    """Ventas reales por mes con las zonas de entrenamiento y holdout y las predicciones del backtest."""
    serie = pipeline.get("datos", {}).get("serie_mensual", [])
    corte = pipeline.get("split", {}).get("periodo_corte")
    if not serie or not corte:
        return None
    fechas = [_mes_a_fecha(x["periodo"]) for x in serie]
    fin = fechas[-1] + pd.offsets.MonthBegin(1)
    fig = go.Figure()
    fig.add_vrect(x0=fechas[0], x1=_mes_a_fecha(corte), fillcolor=COLORS["primary"], opacity=0.07, line_width=0,
                  annotation_text="Entrenamiento", annotation_position="top left")
    fig.add_vrect(x0=_mes_a_fecha(corte), x1=fin, fillcolor=COLORS["warning"], opacity=0.18, line_width=0,
                  annotation_text="Holdout (solo medir)", annotation_position="top right")
    fig.add_trace(go.Scatter(x=fechas, y=[x["real"] for x in serie], mode="lines+markers", name="Ventas reales",
                             line=dict(color=COLORS["text"], width=2), marker=dict(size=4)))
    folds = pipeline.get("backtest", {}).get("folds", [])
    if folds:
        xf = [_mes_a_fecha(f["periodo"]) for f in folds]
        fig.add_trace(go.Scatter(x=xf, y=[f["total_ml"] for f in folds], mode="lines+markers", name="Prediccion ML",
                                 line=dict(color=COLORS["primary"], width=2, dash="dot"), marker=dict(size=8)))
        fig.add_trace(go.Scatter(x=xf, y=[f["total_baseline"] for f in folds], mode="lines+markers",
                                 name="Baseline (mismo mes ano anterior)",
                                 line=dict(color=COLORS["warning"], width=2, dash="dash"), marker=dict(size=8, symbol="diamond")))
    fig.update_layout(height=340, margin=dict(l=10, r=10, t=40, b=10), paper_bgcolor="white", plot_bgcolor="white",
                      font={"family": "Inter"}, yaxis=dict(title="Unidades vendidas (total farmacia)", gridcolor="#E2E8F0"),
                      xaxis=dict(gridcolor="#E2E8F0"), legend=dict(orientation="h", y=-0.15), hovermode="x unified")
    return fig

def grafico_walk_forward(pipeline):
    """Cada paso del backtest: meses con los que entrena y mes que predice."""
    folds = pipeline.get("backtest", {}).get("folds", [])
    desde = pipeline.get("datos", {}).get("desde")
    if not folds or not desde:
        return None
    filas = []
    for f in folds:
        paso = f"Predice {f['periodo']}  (ML {f['ml']['rmse']} / Base {f['baseline']['rmse']})"
        ini_test = _mes_a_fecha(f["periodo"])
        filas.append({"Paso": paso, "Fase": "Entrena", "Inicio": _mes_a_fecha(f.get("train_desde", desde)), "Fin": ini_test})
        filas.append({"Paso": paso, "Fase": "Predice", "Inicio": ini_test, "Fin": ini_test + pd.offsets.MonthBegin(1)})
    fig = px.timeline(pd.DataFrame(filas), x_start="Inicio", x_end="Fin", y="Paso", color="Fase",
                      color_discrete_map={"Entrena": COLORS["primary"], "Predice": COLORS["warning"]})
    fig.update_yaxes(autorange="reversed", title="")
    fig.update_layout(height=120 + 45 * len(folds), margin=dict(l=10, r=10, t=30, b=10), paper_bgcolor="white",
                      plot_bgcolor="white", font={"family": "Inter"}, legend=dict(orientation="h", y=-0.25, title=""),
                      xaxis=dict(gridcolor="#E2E8F0"))
    return fig

def grafico_horizonte(bh):
    """Error por mes de horizonte al predecir encadenado, ML frente a baseline."""
    pasos = (bh or {}).get("pasos", [])
    if not pasos:
        return None
    etiquetas = [f"Mes +{x['h']} ({x['periodo']})" for x in pasos]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=etiquetas, y=[x["ml"]["rmse"] for x in pasos], name="ML", marker_color=COLORS["primary"]))
    fig.add_trace(go.Bar(x=etiquetas, y=[x["baseline"]["rmse"] for x in pasos], name="Baseline", marker_color=COLORS["warning"]))
    fig.update_layout(barmode="group", height=280, margin=dict(l=10, r=10, t=40, b=10), paper_bgcolor="white",
                      plot_bgcolor="white", font={"family": "Inter"}, yaxis=dict(title="RMSE (uds/producto)", gridcolor="#E2E8F0"),
                      title={"text": "Error segun lo lejos que se predice", "font": {"size": 14}}, legend=dict(orientation="h", y=-0.2))
    return fig

def grafico_seleccion_variables(seleccion):
    """Cuanto empeora el error de validacion al quitar cada grupo de variables."""
    grupos = (seleccion or {}).get("grupos", [])
    if not grupos:
        return None
    g = sorted(grupos, key=lambda x: x["impacto_pct"])
    color = {"obligatorio": COLORS["muted"], "se mantiene": COLORS["success"], "se descarta": COLORS["danger"]}
    fig = go.Figure(go.Bar(x=[x["impacto_pct"] for x in g], y=[x["grupo"] for x in g], orientation="h",
                           marker_color=[color.get(x["decision"], COLORS["primary"]) for x in g],
                           text=[f"{x['impacto_pct']:+.1f}% · {x['decision']}" for x in g], textposition="auto"))
    fig.add_vline(x=0, line_color=COLORS["text"], line_width=1)
    fig.update_layout(title={"text": "Error al quitar cada grupo (+ = el grupo ayuda)", "font": {"size": 14}},
                      height=110 + 40 * len(g), margin=dict(l=10, r=10, t=40, b=10), paper_bgcolor="white",
                      plot_bgcolor="white", font={"family": "Inter"}, xaxis=dict(title="% de empeoramiento del RMSE", gridcolor="#E2E8F0"))
    return fig

def grafico_tuning(ensayos, elegidos):
    """RMSE de validacion por combinacion probada, marcando la ganadora."""
    if not ensayos:
        return None
    etiquetas, valores, colores = [], [], []
    for e in ensayos:
        p = e.get("params", {})
        et = f"d{p.get('max_depth')}·lr{p.get('learning_rate')}·n{p.get('n_estimators')}"
        etiquetas.append(et)
        valores.append(e.get("rmse_validacion"))
        colores.append(COLORS["success"] if p == elegidos else COLORS["muted"])
    fig = go.Figure(go.Bar(x=etiquetas, y=valores, marker_color=colores,
                           text=[f"{v:.2f}" for v in valores], textposition="outside"))
    fig.update_layout(height=330, margin=dict(l=10, r=10, t=30, b=10),
                      paper_bgcolor="white", plot_bgcolor="white", font={"family": "Inter"},
                      xaxis=dict(title="Combinacion de hiperparametros"),
                      yaxis=dict(title="RMSE validacion (menor es mejor)", gridcolor="#E2E8F0"))
    return fig

def grafico_backtest_folds(backtest):
    """Error del ML frente al baseline en cada mes del backtest."""
    folds = backtest.get("folds", [])
    if not folds:
        return None
    periodos = [f["periodo"] for f in folds]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=periodos, y=[f["ml"]["rmse"] for f in folds],
                         name="ML", marker_color=COLORS["primary"]))
    fig.add_trace(go.Bar(x=periodos, y=[f["baseline"]["rmse"] for f in folds],
                         name="Baseline heuristico", marker_color=COLORS["muted"]))
    fig.update_layout(barmode="group", height=340, margin=dict(l=10, r=10, t=30, b=10),
                      paper_bgcolor="white", plot_bgcolor="white", font={"family": "Inter"},
                      xaxis=dict(title="Mes predicho"),
                      yaxis=dict(title="RMSE (menor es mejor)", gridcolor="#E2E8F0"),
                      legend=dict(orientation="h", y=-0.25))
    return fig

def grafico_backtest_totales(backtest):
    """Unidades reales frente a lo que predijo cada motor, mes a mes."""
    folds = backtest.get("folds", [])
    if not folds or "total_real" not in folds[0]:
        return None
    periodos = [f["periodo"] for f in folds]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=periodos, y=[f["total_real"] for f in folds], name="Real",
                             mode="lines+markers", line=dict(color=COLORS["text"], width=3)))
    fig.add_trace(go.Scatter(x=periodos, y=[f["total_ml"] for f in folds], name="ML",
                             mode="lines+markers", line=dict(color=COLORS["primary"], width=2, dash="dash")))
    fig.add_trace(go.Scatter(x=periodos, y=[f["total_baseline"] for f in folds], name="Baseline",
                             mode="lines+markers", line=dict(color=COLORS["muted"], width=2, dash="dot")))
    fig.update_layout(height=340, margin=dict(l=10, r=10, t=30, b=10),
                      paper_bgcolor="white", plot_bgcolor="white", font={"family": "Inter"},
                      xaxis=dict(title="Mes predicho"),
                      yaxis=dict(title="Unidades totales", gridcolor="#E2E8F0"),
                      legend=dict(orientation="h", y=-0.25))
    return fig

def grafico_residuos(hist):
    """Distribucion del error. Centrada en 0 = modelo sin sesgo sistematico."""
    if not hist or not hist.get("counts"):
        return None
    bordes = hist["bordes"]
    centros = [(bordes[i] + bordes[i + 1]) / 2 for i in range(len(bordes) - 1)]
    fig = go.Figure(go.Bar(x=centros, y=hist["counts"], marker_color=COLORS["primary"]))
    fig.add_vline(x=0, line_dash="dash", line_color=COLORS["danger"],
                  annotation_text="prediccion perfecta")
    fig.update_layout(height=330, margin=dict(l=10, r=10, t=40, b=10),
                      paper_bgcolor="white", plot_bgcolor="white", font={"family": "Inter"},
                      xaxis=dict(title="Error (predicho − real). Negativo = se queda corto"),
                      yaxis=dict(title="Nº de predicciones", gridcolor="#E2E8F0"))
    return fig
