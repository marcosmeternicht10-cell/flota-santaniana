"""
pdf_export.py — Generación de reportes PDF con gráficos
Sistema de Gestión de Flota - La Santaniana

Usa matplotlib para los gráficos (barras + torta) y reportlab para el PDF.
matplotlib se importa solo cuando se genera un PDF (ahorra RAM al arrancar).
"""

import os
import io
import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT


def _get_plt():
    """Importa matplotlib solo cuando se necesita (ahorra ~26 MB de RAM)."""
    import matplotlib
    matplotlib.use("Agg")  # backend sin pantalla
    import matplotlib.pyplot as plt
    return plt

# ─── Paleta corporativa ───────────────────────────────────────────────────────
AZUL      = "#185FA5"
AZUL_CLARO= "#378ADD"
ROJO      = "#E24B4A"
VERDE     = "#1D9E75"
AMARILLO  = "#EF9F27"
GRIS      = "#5F5E5A"
GRIS_CLARO= "#F1EFE8"


def gs(v):
    """Formatea guaraní: ₲ 84.000.000"""
    if v is None:
        return "₲ 0"
    return f"Gs. {int(round(v)):,}".replace(",", ".")


# ─── Gráficos ─────────────────────────────────────────────────────────────────

def _grafico_barras(k, ruta):
    """Barras horizontales de la estructura de costos."""
    plt = _get_plt()
    from matplotlib.ticker import FuncFormatter
    conceptos = ["Ingreso", "Costos\nvariables", "Margen\ncontribución",
                 "Fijos\ndirectos", "Fijos\nindirectos", "Utilidad\noperativa"]
    valores = [k["ingreso"], k["costos_variables"], k["margen_contribucion"],
               k["costos_fijos_directos"], k["costos_fijos_indirectos"],
               k["utilidad_operativa"]]
    colores = [AZUL_CLARO, ROJO, VERDE, AMARILLO, AMARILLO, AZUL]

    fig, ax = plt.subplots(figsize=(7, 3.6), dpi=150)
    barras = ax.barh(conceptos[::-1], valores[::-1], color=colores[::-1],
                     edgecolor="white", height=0.65)

    # Etiquetas de valor
    max_v = max(valores) if valores else 1
    for b, v in zip(barras, valores[::-1]):
        ax.text(b.get_width() + max_v * 0.01, b.get_y() + b.get_height()/2,
                gs(v), va="center", ha="left", fontsize=8, color="#333")

    ax.xaxis.set_major_formatter(FuncFormatter(
        lambda x, _: f"{x/1_000_000:.0f}M" if x >= 1_000_000 else f"{x:.0f}"))
    ax.set_xlim(0, max_v * 1.25)
    ax.tick_params(axis="y", labelsize=8)
    ax.tick_params(axis="x", labelsize=7, colors=GRIS)
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    ax.spines["left"].set_color("#DDD")
    ax.spines["bottom"].set_color("#DDD")
    ax.set_title("Estructura de Costos (Gs.)", fontsize=11, fontweight="bold",
                 color="#222", pad=12, loc="left")
    plt.tight_layout()
    fig.savefig(ruta, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _grafico_torta(k, ruta):
    """Torta de distribución del ingreso."""
    plt = _get_plt()
    variables   = k["costos_variables"]
    fijos       = k["costos_fijos_directos"] + k["costos_fijos_indirectos"]
    utilidad    = max(0, k["utilidad_operativa"])

    valores, etiquetas, cols = [], [], []
    if variables > 0:
        valores.append(variables); etiquetas.append("Costos variables"); cols.append(ROJO)
    if fijos > 0:
        valores.append(fijos); etiquetas.append("Costos fijos"); cols.append(AMARILLO)
    if utilidad > 0:
        valores.append(utilidad); etiquetas.append("Utilidad operativa"); cols.append(AZUL)

    if not valores:
        valores, etiquetas, cols = [1], ["Sin datos"], [GRIS]

    fig, ax = plt.subplots(figsize=(4.2, 3.6), dpi=150)
    wedges, _, autotexts = ax.pie(
        valores, colors=cols, autopct=lambda p: f"{p:.0f}%",
        startangle=90, pctdistance=0.78,
        wedgeprops=dict(width=0.42, edgecolor="white", linewidth=2))
    for at in autotexts:
        at.set_color("white"); at.set_fontsize(9); at.set_fontweight("bold")

    ax.legend(wedges, etiquetas, loc="center", fontsize=8,
              frameon=False, bbox_to_anchor=(0.5, -0.08), ncol=1)
    ax.set_title("Distribución del Ingreso", fontsize=11, fontweight="bold",
                 color="#222", pad=12)
    plt.tight_layout()
    fig.savefig(ruta, bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ─── PDF ──────────────────────────────────────────────────────────────────────

def generar_pdf(vehiculo, k, servicios, titulo_periodo, modo):
    """Genera el PDF y devuelve la ruta del archivo."""
    carpeta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reportes")
    os.makedirs(carpeta, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    ruta_pdf = os.path.join(carpeta, f"reporte_{vehiculo['patente']}_{ts}.pdf")

    # Generar gráficos temporales
    g_barras = os.path.join(carpeta, f"_barras_{ts}.png")
    g_torta  = os.path.join(carpeta, f"_torta_{ts}.png")
    _grafico_barras(k, g_barras)
    _grafico_torta(k, g_torta)

    # Estilos
    styles = getSampleStyleSheet()
    estilo_titulo = ParagraphStyle("Titulo", parent=styles["Title"],
        fontSize=20, textColor=colors.HexColor(AZUL), spaceAfter=2, alignment=TA_LEFT)
    estilo_sub = ParagraphStyle("Sub", parent=styles["Normal"],
        fontSize=10, textColor=colors.HexColor(GRIS), spaceAfter=2)
    estilo_seccion = ParagraphStyle("Seccion", parent=styles["Heading2"],
        fontSize=13, textColor=colors.HexColor("#222"), spaceBefore=14, spaceAfter=6)

    doc = SimpleDocTemplate(ruta_pdf, pagesize=A4,
                            topMargin=18*mm, bottomMargin=16*mm,
                            leftMargin=18*mm, rightMargin=18*mm)
    elementos = []

    # ── Encabezado ──
    encab = Table([[
        Paragraph("🚌 LA SANTANIANA", ParagraphStyle("Logo", fontSize=16,
            textColor=colors.HexColor(AZUL), fontName="Helvetica-Bold")),
        Paragraph(f"Reporte generado<br/>{datetime.datetime.now().strftime('%d/%m/%Y %H:%M')}",
            ParagraphStyle("Fecha", fontSize=8, textColor=colors.HexColor(GRIS),
            alignment=2)),
    ]], colWidths=[110*mm, 60*mm])
    encab.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -1), 1.5, colors.HexColor(AZUL)),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    elementos.append(encab)
    elementos.append(Spacer(1, 10))

    # ── Título ──
    elementos.append(Paragraph("Reporte de Gestión de Flota", estilo_titulo))
    elementos.append(Paragraph(
        f"Vehículo: <b>{vehiculo['patente']}</b> — {vehiculo['marca']} {vehiculo['modelo']}",
        estilo_sub))
    modo_txt = "Producción total acumulada" if modo == "produccion" else f"Periodo: {titulo_periodo}"
    elementos.append(Paragraph(modo_txt, estilo_sub))
    elementos.append(Spacer(1, 8))

    # ── Tarjetas KPI (tabla) ──
    tarjetas_data = [[
        _celda_kpi("Servicios", str(k["cantidad_servicios"]), AZUL),
        _celda_kpi("KM totales", f"{k['total_km']:,.0f}".replace(",", "."), VERDE),
        _celda_kpi("Ingreso", gs(k["ingreso"]), AZUL),
        _celda_kpi("Rentabilidad", f"{k['rentabilidad_pct']:.1f}%", VERDE),
    ]]
    t_tarjetas = Table(tarjetas_data, colWidths=[42.5*mm]*4)
    t_tarjetas.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(GRIS_CLARO)),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.white),
        ("INNERGRID", (0, 0), (-1, -1), 3, colors.white),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    elementos.append(t_tarjetas)

    # ── Gráficos ──
    elementos.append(Paragraph("Análisis Gráfico", estilo_seccion))
    fila_graf = Table([[
        Image(g_barras, width=105*mm, height=54*mm),
        Image(g_torta, width=63*mm, height=54*mm),
    ]], colWidths=[107*mm, 65*mm])
    fila_graf.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    elementos.append(fila_graf)

    # ── Tabla estructura de costos ──
    elementos.append(Paragraph("Estructura de Costos", estilo_seccion))
    ec_data = [
        ["Concepto", "Monto (Gs.)", "% del ingreso"],
        ["Ingreso", gs(k["ingreso"]), "100%"],
        ["(−) Costos variables", gs(k["costos_variables"]), f"{_pct(k['costos_variables'], k['ingreso'])}%"],
        ["(=) Margen de contribución", gs(k["margen_contribucion"]), f"{_pct(k['margen_contribucion'], k['ingreso'])}%"],
        ["(−) Costos fijos directos", gs(k["costos_fijos_directos"]), f"{_pct(k['costos_fijos_directos'], k['ingreso'])}%"],
        ["(−) Costos fijos indirectos", gs(k["costos_fijos_indirectos"]), f"{_pct(k['costos_fijos_indirectos'], k['ingreso'])}%"],
        ["(=) UTILIDAD OPERATIVA", gs(k["utilidad_operativa"]), f"{_pct(k['utilidad_operativa'], k['ingreso'])}%"],
    ]
    t_ec = Table(ec_data, colWidths=[88*mm, 50*mm, 34*mm])
    t_ec.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(AZUL)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7FAFC")]),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#DDD")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        # Resaltar margen y utilidad
        ("BACKGROUND", (0, 3), (-1, 3), colors.HexColor("#F0FFF4")),
        ("BACKGROUND", (0, 6), (-1, 6), colors.HexColor("#EBF8FF")),
        ("FONTNAME", (0, 6), (-1, 6), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 6), (-1, 6), colors.HexColor(AZUL)),
    ]))
    elementos.append(t_ec)

    # ── Indicadores adicionales ──
    elementos.append(Paragraph("Indicadores Operativos", estilo_seccion))
    ind_data = [
        ["Ingreso por KM", gs(k["ingreso_por_km"]), "Ingreso por hora", gs(k["ingreso_por_hora"])],
        ["Costo var. por KM", gs(k["costo_variable_por_km"]), "Margen contrib.", f"{k['margen_pct']:.1f}%"],
        ["KM prom./servicio", f"{k['km_promedio']:,.0f}".replace(",", "."), "Ingreso prom./serv.", gs(k["ingreso_promedio_servicio"])],
    ]
    t_ind = Table(ind_data, colWidths=[43*mm, 43*mm, 43*mm, 43*mm])
    t_ind.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor(GRIS)),
        ("TEXTCOLOR", (2, 0), (2, -1), colors.HexColor(GRIS)),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("ALIGN", (3, 0), (3, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.HexColor("#FAFAFA"), colors.white]),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#EEE")),
    ]))
    elementos.append(t_ind)

    # ── Detalle de servicios (máx 15) ──
    if servicios:
        elementos.append(Paragraph(
            f"Detalle de Servicios ({len(servicios)} en total)", estilo_seccion))
        serv_data = [["Fecha", "KM", "Horas", "Ingreso (Gs.)", "Descripción"]]
        for s in servicios[:15]:
            serv_data.append([
                s["fecha"], f"{s['km']:.0f}", f"{s['horas']:.0f}",
                gs(s["ingreso"]), (s["descripcion"] or "—")[:30]
            ])
        if len(servicios) > 15:
            serv_data.append(["...", "", "", f"+{len(servicios)-15} más", ""])
        t_serv = Table(serv_data, colWidths=[28*mm, 20*mm, 18*mm, 42*mm, 64*mm])
        t_serv.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(GRIS)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ALIGN", (1, 0), (3, -1), "RIGHT"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7FAFC")]),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#EEE")),
        ]))
        elementos.append(t_serv)

    # ── Pie ──
    elementos.append(Spacer(1, 16))
    elementos.append(Paragraph(
        "Generado por el Sistema de Gestión de Flota — La Santaniana",
        ParagraphStyle("Pie", fontSize=7.5, textColor=colors.HexColor(GRIS),
                       alignment=TA_CENTER)))

    doc.build(elementos)

    # Limpiar imágenes temporales
    for f in (g_barras, g_torta):
        try:
            os.remove(f)
        except OSError:
            pass

    return ruta_pdf


def _celda_kpi(label, valor, color_hex):
    return Paragraph(
        f'<font size="8" color="{GRIS}">{label}</font><br/>'
        f'<font size="15" color="{color_hex}"><b>{valor}</b></font>',
        ParagraphStyle("KPI", alignment=TA_CENTER, leading=18))


def _pct(parte, total):
    return f"{(parte/total*100):.0f}" if total else "0"


if __name__ == "__main__":
    # Test con datos de ejemplo
    from database import inicializar_db, obtener_vehiculos, obtener_servicios_vehiculo
    from models import kpis_mes, cargar_datos_ejemplo
    cargar_datos_ejemplo()
    v = obtener_vehiculos()[0]
    k = kpis_mes(v["id"], "2024-06")
    servicios = obtener_servicios_vehiculo(v["id"], "2024-06")
    ruta = generar_pdf(v, k, servicios, "2024-06", "mes")
    print(f"PDF generado: {ruta}")


# ════════════════════════════════════════════════════════════════════════════
#  REPORTE GERENCIAL — Resumen ejecutivo de la flota
# ════════════════════════════════════════════════════════════════════════════

def generar_reporte_gerencial_pdf(reporte, ruta_salida):
    """
    Genera un PDF gerencial multi-página:
      Página 1: Resumen ejecutivo (KPIs, costos totales, gráfico, top vehículos, docs)
      Página 2: Detalle de cada OT del período
      Página 3: Personal técnico involucrado
      Página 4: Desglose técnico de costos
    """
    from reportlab.platypus import PageBreak

    doc = SimpleDocTemplate(ruta_salida, pagesize=A4,
                             topMargin=15*mm, bottomMargin=15*mm,
                             leftMargin=15*mm, rightMargin=15*mm)
    styles = getSampleStyleSheet()
    titulo_style = ParagraphStyle('Titulo', parent=styles['Heading1'],
        fontSize=18, textColor=colors.HexColor(AZUL), alignment=TA_CENTER, spaceAfter=4)
    subtitulo_style = ParagraphStyle('Subtitulo', parent=styles['Heading2'],
        fontSize=11, textColor=colors.HexColor("#555555"), alignment=TA_CENTER, spaceAfter=14)
    seccion_style = ParagraphStyle('Seccion', parent=styles['Heading2'],
        fontSize=13, textColor=colors.HexColor(AZUL), spaceAfter=8, spaceBefore=12)
    pagina_titulo_style = ParagraphStyle('PagTit', parent=styles['Heading1'],
        fontSize=15, textColor=colors.HexColor(AZUL), alignment=TA_LEFT, spaceAfter=10)
    normal = styles['Normal']
    small_style = ParagraphStyle('Small', parent=normal, fontSize=8.5, leading=10)

    story = []
    gs = lambda v: "Gs. " + f"{int(v or 0):,}".replace(",", ".")

    # ═══════════════════════════════════════════════════════════════════════
    # PÁGINA 1: RESUMEN EJECUTIVO
    # ═══════════════════════════════════════════════════════════════════════
    story.append(Paragraph("LA SANTANIANA — Reporte Gerencial de Mantenimiento", titulo_style))
    story.append(Paragraph(
        f"Período: {reporte['desde']} → {reporte['hasta']}", subtitulo_style))

    def kpi_cell(label, value, color=AZUL):
        return [
            Paragraph(f"<font size='9' color='#777777'>{label}</font>", normal),
            Paragraph(f"<font size='14' color='{color}'><b>{value}</b></font>", normal),
        ]

    n_ots = len(reporte['ots'])
    pendientes = sum(1 for o in reporte['ots'] if o['estado'] != 'cerrada')

    kpi_data = [[
        kpi_cell("Órdenes de Trabajo", n_ots),
        kpi_cell("OTs pendientes", pendientes, ROJO if pendientes > 0 else VERDE),
        kpi_cell("Preventivos", reporte['preventivos_count'], VERDE),
        kpi_cell("Correctivos", reporte['correctivos_count'], ROJO),
        kpi_cell("Cambios neumáticos", reporte['cambios_neumaticos']),
    ]]
    kpi_tbl = Table(kpi_data, colWidths=[36*mm]*5)
    kpi_tbl.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#F4F7FB")),
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#D9E2EE")),
        ('LINEAFTER', (0,0), (-2,-1), 0.5, colors.HexColor("#D9E2EE")),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
    ]))
    story.append(kpi_tbl)

    # Costos totales
    story.append(Paragraph("Costos del período", seccion_style))
    costos_data = [
        ["Concepto", "Monto"],
        ["Órdenes de Trabajo", gs(reporte['costo_ots'])],
        ["Mantenimientos preventivos", gs(reporte['preventivos_costo'])],
        ["Mantenimientos correctivos", gs(reporte['correctivos_costo'])],
        ["TOTAL", gs(reporte['costo_total'])],
    ]
    costos_tbl = Table(costos_data, colWidths=[110*mm, 60*mm])
    costos_tbl.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor(AZUL)),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('ALIGN', (1,0), (1,-1), 'RIGHT'),
        ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor("#F4F7FB")),
        ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'),
        ('TEXTCOLOR', (0,-1), (-1,-1), colors.HexColor(AZUL)),
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#D9E2EE")),
        ('INNERGRID', (0,0), (-1,-1), 0.25, colors.HexColor("#D9E2EE")),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(costos_tbl)

    # Items por tipo (gráfico)
    if reporte['items_por_tipo']:
        plt = _get_plt()
        story.append(Paragraph("Trabajos por tipo", seccion_style))
        fig, ax = plt.subplots(figsize=(6, 3))
        tipos = [i['tipo'].title() for i in reporte['items_por_tipo']]
        cants = [i['cant'] for i in reporte['items_por_tipo']]
        colors_bar = [ROJO if t.lower()=='correctivo' else VERDE if t.lower()=='preventivo' else AZUL_CLARO for t in tipos]
        ax.bar(tipos, cants, color=colors_bar)
        ax.set_ylabel('Cantidad')
        ax.set_title('Items de OT por tipo', fontsize=10)
        ax.grid(axis='y', alpha=0.3)
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=110, bbox_inches='tight')
        plt.close(fig)
        buf.seek(0)
        story.append(Image(buf, width=170*mm, height=80*mm))

    # Top vehículos
    if reporte['top_vehiculos']:
        story.append(Paragraph("Top vehículos con mayor costo", seccion_style))
        data = [["#", "Patente", "N° int.", "Marca/Modelo", "Costo total"]]
        for i, v in enumerate(reporte['top_vehiculos'], 1):
            marca_mod = f"{v.get('marca') or ''} {v.get('modelo') or ''}".strip() or "—"
            data.append([str(i), v['patente'], v.get('n_interno') or "—",
                         marca_mod[:35], gs(v['costo_total'])])
        top_tbl = Table(data, colWidths=[10*mm, 28*mm, 22*mm, 70*mm, 40*mm])
        top_tbl.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor(AZUL)),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,-1), 8.5),
            ('ALIGN', (0,0), (0,-1), 'CENTER'),
            ('ALIGN', (-1,0), (-1,-1), 'RIGHT'),
            ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#D9E2EE")),
            ('INNERGRID', (0,0), (-1,-1), 0.25, colors.HexColor("#D9E2EE")),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor("#FAFBFD")]),
            ('TOPPADDING', (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ]))
        story.append(top_tbl)

    # Documentos por vencer
    if reporte['docs_proximos']:
        story.append(Paragraph("Documentos próximos a vencer (≤ 30 días)", seccion_style))
        data = [["Patente", "Tipo", "Documento", "Vencimiento", "Días"]]
        for d in reporte['docs_proximos'][:15]:
            dias = d['dias_restantes']
            data.append([d['patente'], d['tipo'],
                (d.get('nombre') or "")[:40], d['fecha_vencimiento'],
                f"{dias} días" if dias >= 0 else f"VENCIDO ({abs(dias)}d)"])
        doc_tbl = Table(data, colWidths=[25*mm, 35*mm, 60*mm, 30*mm, 25*mm])
        doc_tbl.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor(AMARILLO)),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,-1), 8),
            ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#D9E2EE")),
            ('INNERGRID', (0,0), (-1,-1), 0.25, colors.HexColor("#D9E2EE")),
            ('TOPPADDING', (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ]))
        story.append(doc_tbl)

    story.append(Spacer(1, 6*mm))
    story.append(Paragraph(
        f"<font size='8' color='#999999'>Generado el {datetime.date.today().isoformat()} "
        f"— La Santaniana, Sistema de Gestión de Flota</font>", normal))

    # ═══════════════════════════════════════════════════════════════════════
    # PÁGINA 2: DETALLE DE OTs DEL PERÍODO
    # ═══════════════════════════════════════════════════════════════════════
    if reporte.get("ots_detalle"):
        story.append(PageBreak())
        story.append(Paragraph("Detalle de Órdenes de Trabajo", pagina_titulo_style))
        story.append(Paragraph(
            f"<font size='10' color='#666666'>Período: {reporte['desde']} → {reporte['hasta']}</font>",
            normal))
        story.append(Spacer(1, 4*mm))

        for ot in reporte["ots_detalle"]:
            estado_label = {"abierta":"ABIERTA","en_proceso":"EN PROCESO","cerrada":"CERRADA"}.get(ot['estado'], ot['estado'])
            estado_color = ROJO if ot['estado']=='abierta' else AMARILLO if ot['estado']=='en_proceso' else VERDE

            # Encabezado OT
            ot_header_data = [[
                Paragraph(f"<b>OT #{ot['id']}</b> · <b>{ot['patente']}</b>"
                          + (f" · Coche {ot['n_interno']}" if ot.get('n_interno') else ""), normal),
                Paragraph(f"<font color='{estado_color}'><b>{estado_label}</b></font>", normal),
            ]]
            ot_header = Table(ot_header_data, colWidths=[130*mm, 50*mm])
            ot_header.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#F4F7FB")),
                ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor(AZUL)),
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ('ALIGN', (1,0), (1,0), 'RIGHT'),
                ('LEFTPADDING', (0,0), (-1,-1), 8),
                ('RIGHTPADDING', (0,0), (-1,-1), 8),
                ('TOPPADDING', (0,0), (-1,-1), 5),
                ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ]))
            story.append(ot_header)

            # Info adicional
            info = []
            if ot.get('fecha_apertura'): info.append(f"<b>Fecha:</b> {ot['fecha_apertura']}")
            if ot.get('km'): info.append(f"<b>KM:</b> {int(ot['km']):,}".replace(',','.'))
            if ot.get('conductor'): info.append(f"<b>Conductor:</b> {ot['conductor']}")
            if ot.get('procedencia'): info.append(f"<b>Procedencia:</b> {ot['procedencia']}")
            if info:
                story.append(Paragraph(" · ".join(info), small_style))
            story.append(Spacer(1, 2*mm))

            # Items
            if ot.get("items"):
                items_data = [["#", "Descripción", "Tipo", "Estado", "Técnico", "Costo"]]
                for idx, it in enumerate(ot["items"], 1):
                    est_lbl = {"pendiente":"⏳","en_proceso":"🔧","completado":"✓"}.get(it["estado"], "")
                    items_data.append([
                        str(idx),
                        (it["descripcion"] or "")[:60],
                        it["tipo"].title(),
                        f"{est_lbl} {it['estado'][:10]}",
                        (it.get("tecnico") or "—")[:20],
                        gs(it.get("costo", 0))
                    ])
                items_data.append(["", "", "", "", "TOTAL", gs(sum(i.get("costo",0) for i in ot["items"]))])
                items_tbl = Table(items_data, colWidths=[8*mm, 65*mm, 22*mm, 25*mm, 30*mm, 30*mm])
                items_tbl.setStyle(TableStyle([
                    ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#E8EEF7")),
                    ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0,0), (-1,-1), 8),
                    ('ALIGN', (0,0), (0,-1), 'CENTER'),
                    ('ALIGN', (-1,0), (-1,-1), 'RIGHT'),
                    ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor("#F4F7FB")),
                    ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'),
                    ('TEXTCOLOR', (-2,-1), (-1,-1), colors.HexColor(AZUL)),
                    ('BOX', (0,0), (-1,-1), 0.4, colors.HexColor("#D9E2EE")),
                    ('INNERGRID', (0,0), (-1,-1), 0.2, colors.HexColor("#D9E2EE")),
                    ('TOPPADDING', (0,0), (-1,-1), 3),
                    ('BOTTOMPADDING', (0,0), (-1,-1), 3),
                ]))
                story.append(items_tbl)
            story.append(Spacer(1, 6*mm))

    # ═══════════════════════════════════════════════════════════════════════
    # PÁGINA 3: PERSONAL TÉCNICO INVOLUCRADO
    # ═══════════════════════════════════════════════════════════════════════
    if reporte.get("tecnicos"):
        story.append(PageBreak())
        story.append(Paragraph("Personal Técnico — Trabajos realizados", pagina_titulo_style))
        story.append(Paragraph(
            f"<font size='10' color='#666666'>Resumen de trabajos por técnico en el período</font>",
            normal))
        story.append(Spacer(1, 4*mm))

        data = [["#", "Técnico", "Trabajos", "Preventivos", "Correctivos", "Costo total"]]
        for i, t in enumerate(reporte["tecnicos"], 1):
            data.append([
                str(i), t["nombre"],
                str(t["total"]), str(t.get("preventivos", 0)),
                str(t.get("correctivos", 0)), gs(t.get("costo", 0))
            ])
        tec_tbl = Table(data, colWidths=[10*mm, 70*mm, 22*mm, 26*mm, 26*mm, 36*mm])
        tec_tbl.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor(AZUL)),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,-1), 9),
            ('ALIGN', (0,0), (0,-1), 'CENTER'),
            ('ALIGN', (2,0), (-1,-1), 'CENTER'),
            ('ALIGN', (-1,0), (-1,-1), 'RIGHT'),
            ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#D9E2EE")),
            ('INNERGRID', (0,0), (-1,-1), 0.25, colors.HexColor("#D9E2EE")),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor("#FAFBFD")]),
            ('TOPPADDING', (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ]))
        story.append(tec_tbl)

    # ═══════════════════════════════════════════════════════════════════════
    # PÁGINA 4: DESGLOSE TÉCNICO DE COSTOS
    # ═══════════════════════════════════════════════════════════════════════
    story.append(PageBreak())
    story.append(Paragraph("Desglose técnico de costos", pagina_titulo_style))
    story.append(Paragraph(
        f"<font size='10' color='#666666'>Análisis detallado del gasto en mantenimiento</font>",
        normal))
    story.append(Spacer(1, 5*mm))

    # Tabla con todos los costos por vehículo + tipo
    if reporte.get("desglose_por_vehiculo"):
        story.append(Paragraph("Costos por vehículo y tipo de trabajo", seccion_style))
        data = [["Patente", "Coche", "Preventivo", "Correctivo", "Neumáticos", "Otro", "TOTAL"]]
        for d in reporte["desglose_por_vehiculo"]:
            data.append([
                d["patente"], d.get("n_interno") or "—",
                gs(d.get("preventivo", 0)),
                gs(d.get("correctivo", 0)),
                gs(d.get("neumaticos", 0)),
                gs(d.get("otro", 0)),
                gs(d.get("total", 0)),
            ])
        # Fila total
        totales = {k: sum(d.get(k, 0) for d in reporte["desglose_por_vehiculo"])
                   for k in ["preventivo","correctivo","neumaticos","otro","total"]}
        data.append([
            "TOTAL", "",
            gs(totales["preventivo"]), gs(totales["correctivo"]),
            gs(totales["neumaticos"]), gs(totales["otro"]),
            gs(totales["total"]),
        ])
        d_tbl = Table(data, colWidths=[24*mm, 18*mm, 28*mm, 28*mm, 28*mm, 24*mm, 32*mm])
        d_tbl.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor(AZUL)),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,-1), 8),
            ('ALIGN', (2,0), (-1,-1), 'RIGHT'),
            ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor("#E8EEF7")),
            ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'),
            ('TEXTCOLOR', (0,-1), (-1,-1), colors.HexColor(AZUL)),
            ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#D9E2EE")),
            ('INNERGRID', (0,0), (-1,-1), 0.25, colors.HexColor("#D9E2EE")),
            ('ROWBACKGROUNDS', (0,1), (-2,-1), [colors.white, colors.HexColor("#FAFBFD")]),
            ('TOPPADDING', (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ]))
        story.append(d_tbl)

    # Pie final
    story.append(Spacer(1, 10*mm))
    story.append(Paragraph(
        f"<font size='8' color='#999999'>Reporte generado el {datetime.date.today().isoformat()} "
        f"— La Santaniana, Sistema de Gestión de Flota</font>", normal))

    doc.build(story)
    return ruta_salida


# ════════════════════════════════════════════════════════════════════════════
#  PDF de una ORDEN DE TRABAJO individual (adaptable a lo que tenga)
# ════════════════════════════════════════════════════════════════════════════
LABEL_TIPO_OT = {
    "preventivo": "Preventivo", "correctivo": "Correctivo",
    "neumaticos": "Neumáticos", "control": "Control", "otro": "Otro",
}
LABEL_ESTADO_ITEM = {
    "pendiente": "Pendiente", "en_proceso": "En proceso", "completado": "Completado",
}
LABEL_ESTADO_OT = {
    "abierta": "Abierta", "en_proceso": "En proceso", "cerrada": "Cerrada",
}


def _logo_path():
    """Ruta al logo si existe."""
    for ruta in ("static/logo.png", os.path.join(os.path.dirname(__file__), "static", "logo.png")):
        if os.path.exists(ruta):
            return ruta
    return None


def generar_ot_pdf(ot, ruta_salida):
    """
    Genera un PDF formal de UNA orden de trabajo, lista para imprimir.
    Es adaptable: muestra todos los items que tenga la OT (preventivos,
    correctivos, neumáticos, etc.), con su técnico, estado y costo.
    """
    doc = SimpleDocTemplate(ruta_salida, pagesize=A4,
                            topMargin=15*mm, bottomMargin=15*mm,
                            leftMargin=16*mm, rightMargin=16*mm)
    styles = getSampleStyleSheet()
    normal = styles["Normal"]
    gs = lambda v: "Gs. " + f"{int(v or 0):,}".replace(",", ".")

    titulo = ParagraphStyle("OtTit", parent=styles["Heading1"],
        fontSize=17, textColor=colors.HexColor(AZUL), alignment=TA_LEFT, spaceAfter=2)
    sub = ParagraphStyle("OtSub", parent=normal,
        fontSize=9, textColor=colors.HexColor(GRIS), spaceAfter=2)
    seccion = ParagraphStyle("OtSec", parent=styles["Heading2"],
        fontSize=12, textColor=colors.HexColor(AZUL), spaceBefore=10, spaceAfter=6)
    small = ParagraphStyle("OtSmall", parent=normal, fontSize=8.5, leading=11)

    story = []

    # ── Encabezado: logo + título ──
    logo = _logo_path()
    coche = f"Coche {ot.get('n_interno')}" if ot.get("n_interno") else ot.get("patente", "")
    encabezado_txt = [
        Paragraph("<b>LA SANTANIANA</b>", ParagraphStyle("Emp", parent=normal,
            fontSize=13, textColor=colors.HexColor(ROJO))),
        Paragraph("Orden de Trabajo", titulo),
        Paragraph(f"OT N° {ot['id']} &nbsp;·&nbsp; {coche} &nbsp;·&nbsp; {ot.get('patente','')}", sub),
    ]
    if logo:
        try:
            img = Image(logo, width=26*mm, height=18*mm)
            head = Table([[encabezado_txt, img]], colWidths=[140*mm, 28*mm])
            head.setStyle(TableStyle([
                ("VALIGN", (0,0), (-1,-1), "TOP"),
                ("ALIGN", (1,0), (1,0), "RIGHT"),
            ]))
            story.append(head)
        except Exception:
            for x in encabezado_txt: story.append(x)
    else:
        for x in encabezado_txt: story.append(x)

    story.append(Spacer(1, 4*mm))
    # Línea divisoria
    linea = Table([[""]], colWidths=[168*mm])
    linea.setStyle(TableStyle([("LINEBELOW", (0,0), (-1,-1), 1, colors.HexColor(AZUL))]))
    story.append(linea)
    story.append(Spacer(1, 4*mm))

    # ── Datos de la OT (ficha) ──
    veh = f"{ot.get('marca','')} {ot.get('modelo','')}".strip()
    estado_ot = LABEL_ESTADO_OT.get(ot.get("estado",""), ot.get("estado",""))
    datos = [
        [Paragraph("<b>Vehículo</b>", small), Paragraph(f"{coche} — {ot.get('patente','')}", small),
         Paragraph("<b>Estado</b>", small), Paragraph(estado_ot, small)],
        [Paragraph("<b>Marca/Modelo</b>", small), Paragraph(veh or "—", small),
         Paragraph("<b>Fecha apertura</b>", small), Paragraph(ot.get("fecha_apertura","—"), small)],
        [Paragraph("<b>Kilómetros</b>", small), Paragraph(f"{int(ot.get('km',0) or 0):,}".replace(",","."), small),
         Paragraph("<b>Fecha cierre</b>", small), Paragraph(ot.get("fecha_cierre") or "—", small)],
        [Paragraph("<b>Conductor</b>", small), Paragraph(ot.get("conductor") or "—", small),
         Paragraph("<b>Procedencia</b>", small), Paragraph(ot.get("procedencia") or "—", small)],
    ]
    tabla_datos = Table(datos, colWidths=[30*mm, 54*mm, 30*mm, 54*mm])
    tabla_datos.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (0,-1), colors.HexColor(GRIS_CLARO)),
        ("BACKGROUND", (2,0), (2,-1), colors.HexColor(GRIS_CLARO)),
        ("BOX", (0,0), (-1,-1), 0.5, colors.HexColor("#D9E2EE")),
        ("INNERGRID", (0,0), (-1,-1), 0.25, colors.HexColor("#D9E2EE")),
        ("TOPPADDING", (0,0), (-1,-1), 5), ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("LEFTPADDING", (0,0), (-1,-1), 6), ("RIGHTPADDING", (0,0), (-1,-1), 6),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
    ]))
    story.append(tabla_datos)

    # ── Items / trabajos (lo adaptable) ──
    story.append(Paragraph("Trabajos a realizar / realizados", seccion))
    items = ot.get("items", [])
    if items:
        filas = [[
            Paragraph("<b>#</b>", small),
            Paragraph("<b>Descripción</b>", small),
            Paragraph("<b>Tipo</b>", small),
            Paragraph("<b>Estado</b>", small),
            Paragraph("<b>Técnico</b>", small),
            Paragraph("<b>Costo</b>", small),
        ]]
        total = 0
        for i, it in enumerate(items, 1):
            total += (it.get("costo") or 0)
            filas.append([
                Paragraph(str(i), small),
                Paragraph(it.get("descripcion",""), small),
                Paragraph(LABEL_TIPO_OT.get(it.get("tipo",""), it.get("tipo","")), small),
                Paragraph(LABEL_ESTADO_ITEM.get(it.get("estado",""), it.get("estado","")), small),
                Paragraph(it.get("tecnico") or "—", small),
                Paragraph(gs(it.get("costo")), small),
            ])
        # Fila total
        filas.append([
            Paragraph("", small), Paragraph("", small), Paragraph("", small),
            Paragraph("", small), Paragraph("<b>TOTAL</b>", small),
            Paragraph(f"<b>{gs(total)}</b>", small),
        ])
        tabla_items = Table(filas, colWidths=[8*mm, 64*mm, 24*mm, 22*mm, 26*mm, 24*mm])
        tabla_items.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor(AZUL)),
            ("TEXTCOLOR", (0,0), (-1,0), colors.white),
            ("ALIGN", (5,0), (5,-1), "RIGHT"),
            ("ALIGN", (0,0), (0,-1), "CENTER"),
            ("BACKGROUND", (0,-1), (-1,-1), colors.HexColor("#E8EEF7")),
            ("TEXTCOLOR", (0,-1), (-1,-1), colors.HexColor(AZUL)),
            ("BOX", (0,0), (-1,-1), 0.5, colors.HexColor("#D9E2EE")),
            ("INNERGRID", (0,0), (-1,-1), 0.25, colors.HexColor("#D9E2EE")),
            ("ROWBACKGROUNDS", (0,1), (-2,-1), [colors.white, colors.HexColor("#FAFBFD")]),
            ("TOPPADDING", (0,0), (-1,-1), 4), ("BOTTOMPADDING", (0,0), (-1,-1), 4),
            ("LEFTPADDING", (0,0), (-1,-1), 5), ("RIGHTPADDING", (0,0), (-1,-1), 5),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ]))
        story.append(tabla_items)
    else:
        story.append(Paragraph("<i>Esta orden no tiene trabajos cargados.</i>", small))

    # ── Observaciones ──
    if ot.get("observaciones"):
        story.append(Paragraph("Observaciones", seccion))
        story.append(Paragraph(ot["observaciones"], small))

    # ── Firmas ──
    story.append(Spacer(1, 16*mm))
    firmas = Table([
        ["_______________________________", "_______________________________"],
        [Paragraph("<font size='8'>Responsable de Taller</font>", normal),
         Paragraph("<font size='8'>Conformidad / Recibido</font>", normal)],
    ], colWidths=[84*mm, 84*mm])
    firmas.setStyle(TableStyle([
        ("ALIGN", (0,0), (-1,-1), "CENTER"),
        ("TOPPADDING", (0,1), (-1,1), 2),
    ]))
    story.append(firmas)

    # ── Pie ──
    story.append(Spacer(1, 8*mm))
    story.append(Paragraph(
        f"<font size='8' color='#999999'>Documento generado el {datetime.date.today().isoformat()} "
        f"— La Santaniana, Sistema de Gestión de Flota</font>", normal))

    doc.build(story)
    return ruta_salida


# ════════════════════════════════════════════════════════════════════════════
#  PDF de REPORTE por rango de fechas (lo que se hizo en el período)
# ════════════════════════════════════════════════════════════════════════════
def generar_reporte_periodo_pdf(ots, desde, hasta, ruta_salida):
    """
    Genera un PDF con todas las OTs de un rango de fechas.
    Útil para el reporte diario o semanal que pide el gerente.
    """
    doc = SimpleDocTemplate(ruta_salida, pagesize=A4,
                            topMargin=15*mm, bottomMargin=15*mm,
                            leftMargin=16*mm, rightMargin=16*mm)
    styles = getSampleStyleSheet()
    normal = styles["Normal"]
    gs = lambda v: "Gs. " + f"{int(v or 0):,}".replace(",", ".")

    titulo = ParagraphStyle("RpTit", parent=styles["Heading1"],
        fontSize=16, textColor=colors.HexColor(AZUL), alignment=TA_CENTER, spaceAfter=2)
    subt = ParagraphStyle("RpSub", parent=normal,
        fontSize=10, textColor=colors.HexColor(GRIS), alignment=TA_CENTER, spaceAfter=12)
    seccion = ParagraphStyle("RpSec", parent=styles["Heading2"],
        fontSize=12, textColor=colors.HexColor(AZUL), spaceBefore=10, spaceAfter=6)
    small = ParagraphStyle("RpSmall", parent=normal, fontSize=8.5, leading=11)

    story = []

    # Encabezado con logo
    logo = _logo_path()
    cab = [
        Paragraph("<b>LA SANTANIANA</b>", ParagraphStyle("E2", parent=normal,
            fontSize=12, textColor=colors.HexColor(ROJO))),
        Paragraph("Reporte de Trabajos", titulo),
    ]
    if logo:
        try:
            img = Image(logo, width=24*mm, height=17*mm)
            head = Table([[cab, img]], colWidths=[144*mm, 24*mm])
            head.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("ALIGN",(1,0),(1,0),"RIGHT")]))
            story.append(head)
        except Exception:
            for x in cab: story.append(x)
    else:
        for x in cab: story.append(x)

    story.append(Paragraph(f"Período: {desde} &nbsp; al &nbsp; {hasta}", subt))

    # Resumen de totales
    total_ots = len(ots)
    total_costo = sum((o.get("costo_total") or 0) for o in ots)
    abiertas = sum(1 for o in ots if o.get("estado") == "abierta")
    en_proceso = sum(1 for o in ots if o.get("estado") == "en_proceso")
    cerradas = sum(1 for o in ots if o.get("estado") == "cerrada")

    resumen = Table([[
        Paragraph(f"<b>{total_ots}</b><br/><font size='8'>Órdenes</font>", ParagraphStyle("c",parent=normal,alignment=TA_CENTER)),
        Paragraph(f"<b>{abiertas}</b><br/><font size='8'>Abiertas</font>", ParagraphStyle("c",parent=normal,alignment=TA_CENTER)),
        Paragraph(f"<b>{en_proceso}</b><br/><font size='8'>En proceso</font>", ParagraphStyle("c",parent=normal,alignment=TA_CENTER)),
        Paragraph(f"<b>{cerradas}</b><br/><font size='8'>Cerradas</font>", ParagraphStyle("c",parent=normal,alignment=TA_CENTER)),
        Paragraph(f"<b>{gs(total_costo)}</b><br/><font size='8'>Costo total</font>", ParagraphStyle("c",parent=normal,alignment=TA_CENTER)),
    ]], colWidths=[33*mm,33*mm,33*mm,33*mm,36*mm])
    resumen.setStyle(TableStyle([
        ("BOX", (0,0), (-1,-1), 0.5, colors.HexColor("#D9E2EE")),
        ("INNERGRID", (0,0), (-1,-1), 0.25, colors.HexColor("#D9E2EE")),
        ("BACKGROUND", (0,0), (-1,-1), colors.HexColor(GRIS_CLARO)),
        ("TEXTCOLOR", (0,0), (-1,-1), colors.HexColor(AZUL)),
        ("TOPPADDING", (0,0), (-1,-1), 7), ("BOTTOMPADDING", (0,0), (-1,-1), 7),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
    ]))
    story.append(resumen)

    # Detalle de las OTs
    story.append(Paragraph("Detalle de las órdenes", seccion))
    if ots:
        filas = [[
            Paragraph("<b>OT</b>", small), Paragraph("<b>Fecha</b>", small),
            Paragraph("<b>Vehículo</b>", small), Paragraph("<b>Trabajos</b>", small),
            Paragraph("<b>Estado</b>", small), Paragraph("<b>Costo</b>", small),
        ]]
        for o in ots:
            coche = f"Coche {o.get('n_interno')}" if o.get("n_interno") else o.get("patente","")
            trabajos = f"{o.get('items_completados',0)}/{o.get('total_items',0)} completados"
            estado = LABEL_ESTADO_OT.get(o.get("estado",""), o.get("estado",""))
            filas.append([
                Paragraph(f"#{o['id']}", small),
                Paragraph(o.get("fecha_apertura","—"), small),
                Paragraph(f"{coche}<br/><font size='7' color='#888'>{o.get('patente','')}</font>", small),
                Paragraph(trabajos, small),
                Paragraph(estado, small),
                Paragraph(gs(o.get("costo_total")), small),
            ])
        tabla = Table(filas, colWidths=[14*mm, 24*mm, 44*mm, 38*mm, 24*mm, 24*mm])
        tabla.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor(AZUL)),
            ("TEXTCOLOR", (0,0), (-1,0), colors.white),
            ("ALIGN", (5,0), (5,-1), "RIGHT"),
            ("BOX", (0,0), (-1,-1), 0.5, colors.HexColor("#D9E2EE")),
            ("INNERGRID", (0,0), (-1,-1), 0.25, colors.HexColor("#D9E2EE")),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#FAFBFD")]),
            ("TOPPADDING", (0,0), (-1,-1), 4), ("BOTTOMPADDING", (0,0), (-1,-1), 4),
            ("LEFTPADDING", (0,0), (-1,-1), 5), ("RIGHTPADDING", (0,0), (-1,-1), 5),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ]))
        story.append(tabla)
    else:
        story.append(Paragraph("<i>No hay órdenes de trabajo en este período.</i>", small))

    story.append(Spacer(1, 8*mm))
    story.append(Paragraph(
        f"<font size='8' color='#999999'>Reporte generado el {datetime.date.today().isoformat()} "
        f"— La Santaniana, Sistema de Gestión de Flota</font>", normal))

    doc.build(story)
    return ruta_salida


# ════════════════════════════════════════════════════════════════════════════
#  PDF del PLAN DE MANTENIMIENTO PREVENTIVO de un vehículo (con barras)
# ════════════════════════════════════════════════════════════════════════════
# Colores del semáforo gradual (mismos que en pantalla)
_GRAD_COLORES = {
    "optimo":   ("#15803D", "#DCFCE7"),
    "bueno":    ("#65A30D", "#ECFCCB"),
    "regular":  ("#CA8A04", "#FEF9C3"),
    "atencion": ("#EA580C", "#FFEDD5"),
    "vencido":  ("#DC2626", "#FEE2E2"),
}
_LABEL_ESTADO_MANT = {
    "ok": "Al día", "pronto": "Pronto", "vencido": "Vencido", "nunca": "Sin registro",
}


def _barra_progreso(pct, estado_grad, ancho_mm=42):
    """Dibuja una barra de progreso como mini-tabla coloreada para el PDF."""
    from reportlab.platypus import Table as _T, TableStyle as _TS
    color_hex = _GRAD_COLORES.get(estado_grad, ("#999999", "#EEEEEE"))[0]
    bg_hex = _GRAD_COLORES.get(estado_grad, ("#999999", "#EEEEEE"))[1]
    pct = max(0, min(100, pct or 0))
    lleno = max(0.5, ancho_mm * pct / 100.0)
    vacio = max(0.1, ancho_mm - lleno)
    barra = _T([["", ""]], colWidths=[lleno*mm, vacio*mm], rowHeights=[4.5*mm])
    barra.setStyle(_TS([
        ("BACKGROUND", (0,0), (0,0), colors.HexColor(color_hex)),
        ("BACKGROUND", (1,0), (1,0), colors.HexColor(bg_hex)),
        ("LEFTPADDING", (0,0), (-1,-1), 0), ("RIGHTPADDING", (0,0), (-1,-1), 0),
        ("TOPPADDING", (0,0), (-1,-1), 0), ("BOTTOMPADDING", (0,0), (-1,-1), 0),
        ("BOX", (0,0), (-1,-1), 0.5, colors.HexColor("#D9D9D9")),
        ("ROUNDEDCORNERS", [2, 2, 2, 2]),
    ]))
    return barra


def generar_plan_preventivo_pdf(vehiculo, plan, tareas, ruta_salida):
    """
    Genera el PDF del plan de mantenimiento preventivo de UN vehículo,
    con las tareas, las barras de progreso, el km actual y el km del próximo cambio.
    Pensado para imprimir y usar en el taller.
    """
    doc = SimpleDocTemplate(ruta_salida, pagesize=A4,
                            topMargin=15*mm, bottomMargin=15*mm,
                            leftMargin=14*mm, rightMargin=14*mm)
    styles = getSampleStyleSheet()
    normal = styles["Normal"]
    kmf = lambda v: f"{int(v or 0):,}".replace(",", ".")

    titulo = ParagraphStyle("PlTit", parent=styles["Heading1"],
        fontSize=17, textColor=colors.HexColor(AZUL), alignment=TA_LEFT, spaceAfter=2)
    sub = ParagraphStyle("PlSub", parent=normal, fontSize=9, textColor=colors.HexColor(GRIS), spaceAfter=2)
    seccion = ParagraphStyle("PlSec", parent=styles["Heading2"],
        fontSize=12, textColor=colors.HexColor(AZUL), spaceBefore=10, spaceAfter=6)
    small = ParagraphStyle("PlSmall", parent=normal, fontSize=8, leading=10)
    micro = ParagraphStyle("PlMicro", parent=normal, fontSize=7, leading=9, textColor=colors.HexColor(GRIS))

    story = []
    coche = f"Coche {vehiculo.get('n_interno')}" if vehiculo.get("n_interno") else vehiculo.get("patente","")

    # ── Encabezado con logo ──
    cab = [
        Paragraph("<b>LA SANTANIANA</b>", ParagraphStyle("E3", parent=normal, fontSize=13, textColor=colors.HexColor(ROJO))),
        Paragraph("Plan de Mantenimiento Preventivo", titulo),
        Paragraph(f"{coche} &nbsp;·&nbsp; {vehiculo.get('patente','')} &nbsp;·&nbsp; {vehiculo.get('marca','')} {vehiculo.get('modelo','')}", sub),
    ]
    logo = _logo_path()
    if logo:
        try:
            img = Image(logo, width=26*mm, height=18*mm)
            head = Table([[cab, img]], colWidths=[154*mm, 28*mm])
            head.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("ALIGN",(1,0),(1,0),"RIGHT")]))
            story.append(head)
        except Exception:
            for x in cab: story.append(x)
    else:
        for x in cab: story.append(x)

    story.append(Spacer(1, 3*mm))
    linea = Table([[""]], colWidths=[182*mm])
    linea.setStyle(TableStyle([("LINEBELOW", (0,0), (-1,-1), 1, colors.HexColor(AZUL))]))
    story.append(linea)
    story.append(Spacer(1, 3*mm))

    # ── Datos del vehículo y plan ──
    km_actual = tareas[0]["km_actual"] if tareas else 0
    datos = [[
        Paragraph(f"<b>Plan:</b> {plan.get('plan_nombre','—')}", small),
        Paragraph(f"<b>Km actual:</b> {kmf(km_actual)} km", small),
        Paragraph(f"<b>Fecha:</b> {datetime.date.today().isoformat()}", small),
    ]]
    td = Table(datos, colWidths=[80*mm, 56*mm, 46*mm])
    td.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), colors.HexColor(GRIS_CLARO)),
        ("BOX", (0,0), (-1,-1), 0.5, colors.HexColor("#D9E2EE")),
        ("TOPPADDING", (0,0), (-1,-1), 6), ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("LEFTPADDING", (0,0), (-1,-1), 8),
    ]))
    story.append(td)

    # ── Tabla de tareas con barras ──
    story.append(Paragraph("Tareas de mantenimiento", seccion))
    if tareas:
        filas = [[
            Paragraph("<b>Tarea</b>", small),
            Paragraph("<b>Cada</b>", small),
            Paragraph("<b>Último</b>", small),
            Paragraph("<b>Próximo</b>", small),
            Paragraph("<b>Faltan</b>", small),
            Paragraph("<b>Progreso</b>", small),
            Paragraph("<b>Estado</b>", small),
            Paragraph("<b>Hecho ✓</b>", small),
        ]]
        for t in tareas:
            ultimo = kmf(t["ultimo_km"]) + " km" if t["ultimo_km"] is not None else "—"
            restantes = t["km_restantes"]
            faltan = (kmf(restantes) + " km") if restantes >= 0 else ("VENCIDO " + kmf(abs(restantes)))
            color_estado = _GRAD_COLORES.get(t["estado_grad"], ("#999",""))[0]
            filas.append([
                Paragraph(t["tarea"], small),
                Paragraph(kmf(t["intervalo_km"]), micro),
                Paragraph(ultimo, micro),
                Paragraph(kmf(t["proximo_km"]) + " km", micro),
                Paragraph(f"<font color='{color_estado}'>{faltan}</font>", micro),
                _barra_progreso(t["porcentaje_visual"], t["estado_grad"]),
                Paragraph(f"<font color='{color_estado}'><b>{_LABEL_ESTADO_MANT.get(t['estado'], t['estado'])}</b></font>", micro),
                Paragraph("☐", small),  # casillero para tildar a mano
            ])
        tabla = Table(filas, colWidths=[42*mm, 16*mm, 22*mm, 22*mm, 26*mm, 26*mm, 18*mm, 12*mm])
        tabla.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor(AZUL)),
            ("TEXTCOLOR", (0,0), (-1,0), colors.white),
            ("BOX", (0,0), (-1,-1), 0.5, colors.HexColor("#D9E2EE")),
            ("INNERGRID", (0,0), (-1,-1), 0.25, colors.HexColor("#D9E2EE")),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#FAFBFD")]),
            ("TOPPADDING", (0,0), (-1,-1), 4), ("BOTTOMPADDING", (0,0), (-1,-1), 4),
            ("LEFTPADDING", (0,0), (-1,-1), 4), ("RIGHTPADDING", (0,0), (-1,-1), 4),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
            ("ALIGN", (7,0), (7,-1), "CENTER"),
        ]))
        story.append(tabla)

        # Leyenda de colores
        story.append(Spacer(1, 4*mm))
        leyenda = Table([[
            Paragraph("<font color='#15803D'>█</font> Al día", micro),
            Paragraph("<font color='#CA8A04'>█</font> Atención (70-85%)", micro),
            Paragraph("<font color='#EA580C'>█</font> Pronto (85-100%)", micro),
            Paragraph("<font color='#DC2626'>█</font> Vencido", micro),
        ]], colWidths=[40*mm, 50*mm, 50*mm, 40*mm])
        leyenda.setStyle(TableStyle([("TOPPADDING",(0,0),(-1,-1),2),("BOTTOMPADDING",(0,0),(-1,-1),2)]))
        story.append(leyenda)
    else:
        story.append(Paragraph("<i>Este vehículo no tiene un plan de mantenimiento asignado.</i>", small))

    # ── Espacio para notas del taller ──
    story.append(Spacer(1, 8*mm))
    story.append(Paragraph("Notas del taller", seccion))
    notas = Table([[""]], colWidths=[182*mm], rowHeights=[24*mm])
    notas.setStyle(TableStyle([
        ("BOX", (0,0), (-1,-1), 0.5, colors.HexColor("#CCCCCC")),
        ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#FCFCFC")),
    ]))
    story.append(notas)

    # ── Firma ──
    story.append(Spacer(1, 10*mm))
    firmas = Table([
        ["_______________________________", "_______________________________"],
        [Paragraph("<font size='8'>Mecánico responsable</font>", normal),
         Paragraph("<font size='8'>Jefe de Taller</font>", normal)],
    ], colWidths=[91*mm, 91*mm])
    firmas.setStyle(TableStyle([("ALIGN",(0,0),(-1,-1),"CENTER"),("TOPPADDING",(0,1),(-1,1),2)]))
    story.append(firmas)

    story.append(Spacer(1, 6*mm))
    story.append(Paragraph(
        f"<font size='8' color='#999999'>Documento generado el {datetime.date.today().isoformat()} "
        f"— La Santaniana, Sistema de Gestión de Flota</font>", normal))

    doc.build(story)
    return ruta_salida


# ════════════════════════════════════════════════════════════════════════════
#  PDF de CORRECTIVOS (averías y reparaciones) por rango de fechas
# ════════════════════════════════════════════════════════════════════════════
_LABEL_ESTADO_CORR = {
    "pendiente": "Pendiente", "en_reparacion": "En reparación", "completado": "Completado",
}


def generar_correctivos_pdf(correctivos, desde, hasta, ruta_salida):
    """
    Genera un PDF con los correctivos (averías/reparaciones) de un rango de fechas.
    Diseño formal, listo para imprimir.
    """
    doc = SimpleDocTemplate(ruta_salida, pagesize=A4,
                            topMargin=15*mm, bottomMargin=15*mm,
                            leftMargin=14*mm, rightMargin=14*mm)
    styles = getSampleStyleSheet()
    normal = styles["Normal"]
    gs = lambda v: "Gs. " + f"{int(v or 0):,}".replace(",", ".")

    titulo = ParagraphStyle("CoTit", parent=styles["Heading1"],
        fontSize=16, textColor=colors.HexColor(AZUL), alignment=TA_CENTER, spaceAfter=2)
    subt = ParagraphStyle("CoSub", parent=normal, fontSize=10, textColor=colors.HexColor(GRIS), alignment=TA_CENTER, spaceAfter=12)
    seccion = ParagraphStyle("CoSec", parent=styles["Heading2"],
        fontSize=12, textColor=colors.HexColor(AZUL), spaceBefore=10, spaceAfter=6)
    small = ParagraphStyle("CoSmall", parent=normal, fontSize=8, leading=10)
    micro = ParagraphStyle("CoMicro", parent=normal, fontSize=7.5, leading=9.5)

    story = []

    # Encabezado con logo
    cab = [
        Paragraph("<b>LA SANTANIANA</b>", ParagraphStyle("E4", parent=normal, fontSize=12, textColor=colors.HexColor(ROJO))),
        Paragraph("Correctivos — Averías y Reparaciones", titulo),
    ]
    logo = _logo_path()
    if logo:
        try:
            img = Image(logo, width=24*mm, height=17*mm)
            head = Table([[cab, img]], colWidths=[158*mm, 24*mm])
            head.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("ALIGN",(1,0),(1,0),"RIGHT")]))
            story.append(head)
        except Exception:
            for x in cab: story.append(x)
    else:
        for x in cab: story.append(x)

    story.append(Paragraph(f"Período: {desde} &nbsp; al &nbsp; {hasta}", subt))

    # Resumen
    total = len(correctivos)
    total_costo = sum((c.get("costo") or 0) for c in correctivos)
    pendientes = sum(1 for c in correctivos if c.get("estado") == "pendiente")
    en_rep = sum(1 for c in correctivos if c.get("estado") == "en_reparacion")
    completados = sum(1 for c in correctivos if c.get("estado") == "completado")

    resumen = Table([[
        Paragraph(f"<b>{total}</b><br/><font size='8'>Averías</font>", ParagraphStyle("c1",parent=normal,alignment=TA_CENTER)),
        Paragraph(f"<b>{pendientes}</b><br/><font size='8'>Pendientes</font>", ParagraphStyle("c2",parent=normal,alignment=TA_CENTER)),
        Paragraph(f"<b>{en_rep}</b><br/><font size='8'>En reparación</font>", ParagraphStyle("c3",parent=normal,alignment=TA_CENTER)),
        Paragraph(f"<b>{completados}</b><br/><font size='8'>Completados</font>", ParagraphStyle("c4",parent=normal,alignment=TA_CENTER)),
        Paragraph(f"<b>{gs(total_costo)}</b><br/><font size='8'>Costo total</font>", ParagraphStyle("c5",parent=normal,alignment=TA_CENTER)),
    ]], colWidths=[36*mm,36*mm,38*mm,36*mm,36*mm])
    resumen.setStyle(TableStyle([
        ("BOX", (0,0), (-1,-1), 0.5, colors.HexColor("#D9E2EE")),
        ("INNERGRID", (0,0), (-1,-1), 0.25, colors.HexColor("#D9E2EE")),
        ("BACKGROUND", (0,0), (-1,-1), colors.HexColor(GRIS_CLARO)),
        ("TEXTCOLOR", (0,0), (-1,-1), colors.HexColor(AZUL)),
        ("TOPPADDING", (0,0), (-1,-1), 7), ("BOTTOMPADDING", (0,0), (-1,-1), 7),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
    ]))
    story.append(resumen)

    # Detalle
    story.append(Paragraph("Detalle de averías y reparaciones", seccion))
    if correctivos:
        filas = [[
            Paragraph("<b>Fecha</b>", small), Paragraph("<b>Vehículo</b>", small),
            Paragraph("<b>Falla</b>", small), Paragraph("<b>Descripción</b>", small),
            Paragraph("<b>Reparación</b>", small), Paragraph("<b>Estado</b>", small),
            Paragraph("<b>Costo</b>", small),
        ]]
        for c in correctivos:
            coche = f"Coche {c.get('n_interno')}" if c.get("n_interno") else c.get("patente","")
            filas.append([
                Paragraph(c.get("fecha","—"), micro),
                Paragraph(f"{c.get('patente','')}<br/><font size='6.5' color='#888'>{c.get('marca','')}</font>", micro),
                Paragraph(c.get("tipo_falla","—"), micro),
                Paragraph(c.get("descripcion","—"), micro),
                Paragraph(c.get("reparacion") or "—", micro),
                Paragraph(_LABEL_ESTADO_CORR.get(c.get("estado",""), c.get("estado","")), micro),
                Paragraph(gs(c.get("costo")), micro),
            ])
        tabla = Table(filas, colWidths=[18*mm, 26*mm, 26*mm, 40*mm, 35*mm, 20*mm, 17*mm])
        tabla.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor(AZUL)),
            ("TEXTCOLOR", (0,0), (-1,0), colors.white),
            ("ALIGN", (6,0), (6,-1), "RIGHT"),
            ("BOX", (0,0), (-1,-1), 0.5, colors.HexColor("#D9E2EE")),
            ("INNERGRID", (0,0), (-1,-1), 0.25, colors.HexColor("#D9E2EE")),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#FAFBFD")]),
            ("TOPPADDING", (0,0), (-1,-1), 4), ("BOTTOMPADDING", (0,0), (-1,-1), 4),
            ("LEFTPADDING", (0,0), (-1,-1), 4), ("RIGHTPADDING", (0,0), (-1,-1), 4),
            ("VALIGN", (0,0), (-1,-1), "TOP"),
        ]))
        story.append(tabla)
    else:
        story.append(Paragraph("<i>No hay correctivos registrados en este período.</i>", small))

    story.append(Spacer(1, 8*mm))
    story.append(Paragraph(
        f"<font size='8' color='#999999'>Reporte generado el {datetime.date.today().isoformat()} "
        f"— La Santaniana, Sistema de Gestión de Flota</font>", normal))

    doc.build(story)
    return ruta_salida
