from fpdf import FPDF
from datetime import datetime
from config.settings import APP_NAME, VERSION

def generar_informe_pdf(farmacia_nombre, hs, n_zombies, valor_zombie, n_uvi, valor_uvi,
                       n_roturas, coste_oportunidad, ahorro_acum, rotacion_media, benchmark):
    """Genera un informe PDF descargable para el titular."""
    fecha = datetime.now().strftime("%d/%m/%Y")
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    # Titulo
    pdf.set_font("Helvetica", "B", 22)
    pdf.set_text_color(0, 102, 255)
    pdf.cell(0, 12, f"{APP_NAME} - Informe de Estado", new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(0, 196, 154)
    pdf.set_line_width(1)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(6)
    # Farmacia y fecha
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(30, 41, 59)
    pdf.cell(0, 8, f"Farmacia: {farmacia_nombre}  |  Fecha: {fecha}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    # Benchmark
    if benchmark and benchmark.get("media_red") is not None:
        diff = hs - benchmark["media_red"]
        signo = "+" if diff >= 0 else ""
        pdf.set_font("Helvetica", "I", 10)
        pdf.set_text_color(100, 116, 139)
        pdf.cell(0, 7, f"Benchmark Red: Tu {hs}% vs Media {benchmark['media_red']}% ({benchmark['n_farmacias']} farmacias) ({signo}{diff:.1f}%)", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)
    # KPIs tabla
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(30, 41, 59)
    pdf.cell(0, 10, "Indicadores Clave", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    kpis = [
        ("Health Score", f"{hs}%"),
        ("Rotacion Media", f"{rotacion_media:.2f}"),
        ("Ahorro Acumulado", f"{ahorro_acum:,.2f} EUR"),
        ("Stock Zombie", f"{valor_zombie:,.2f} EUR ({n_zombies} prods)"),
        ("Stock UVI", f"{valor_uvi:,.2f} EUR ({n_uvi} prods)"),
        ("Roturas", f"{n_roturas} prods ({coste_oportunidad:,.2f} EUR/mes)"),
    ]
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_fill_color(248, 249, 252)
    col_w = 90
    for i, (label, value) in enumerate(kpis):
        fill = i % 2 == 0
        pdf.cell(col_w, 8, f"  {label}", border=0, fill=fill)
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(col_w, 8, value, border=0, fill=fill, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "B", 10)
    pdf.ln(6)
    # Resumen
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "Resumen", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.ln(2)
    resumen = [
        f"Capital inmovilizado en productos sin movimiento: {valor_zombie + valor_uvi:,.2f} EUR",
        f"Coste de oportunidad por roturas: {coste_oportunidad:,.2f} EUR/mes",
        f"Ahorro generado con {APP_NAME}: {ahorro_acum:,.2f} EUR",
    ]
    for linea in resumen:
        pdf.cell(5, 7, "-")
        pdf.cell(0, 7, linea, new_x="LMARGIN", new_y="NEXT")
    # Footer
    pdf.ln(10)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(100, 116, 139)
    pdf.cell(0, 6, f"Generado por {APP_NAME} v{VERSION} | {fecha}", align="C")
    return bytes(pdf.output())
