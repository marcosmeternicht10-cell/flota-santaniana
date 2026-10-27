"""
corp_servicios.py — Servicios de corporativos: lo que se hizo de verdad (La Santaniana)

Como la sección Servicios del tráfico, pero para corporativos. La fuente son
las rendiciones de los choferes (lo que se hizo), no la asignación (lo que se
pensaba hacer). Con eso:

  · Cuántos servicios se hicieron, pasajeros, km y lo que costó (lo que se le
    paga al chofer), contra el período anterior del mismo largo.
  · El RANKING POR SERVICIO: cada tramo de cada empresa con las veces que se
    hizo, los pasajeros (total y promedio), los km, lo que costó, el costo por
    pasajero, los suspendidos y quiénes lo hacen.
  · Por empresa, día por día, y los choferes y coches que más servicios hacen.

Un servicio es un tramo de una empresa en un día. Si el entrante lo hizo uno y
el saliente otro, sigue siendo UN servicio; si solo se rindió una mitad, cuenta
como servicio «a medias». Los VARIABLE cuentan cada uno por separado.

Enganche en app.py:
    from corp_servicios import bp_corp_servicios
    app.register_blueprint(bp_corp_servicios)
"""

import io
import re
from datetime import date, timedelta

from flask import Blueprint, jsonify, request, send_file, session

from db_compat import get_connection
from hora_local import hoy as _hoy, ahora_iso
import corporativos as C

bp_corp_servicios = Blueprint("corp_servicios", __name__)

MAX_DIAS = 400
KM_MAX = 1500          # más que esto en un servicio es un error de tipeo
DIAS_TXT = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


def _rollback(conn):
    try:
        conn.rollback()
    except Exception:
        pass


def _fecha(f):
    try:
        return date.fromisoformat(str(f)[:10])
    except ValueError:
        return None


def _corto(tramo):
    try:
        import corp_asignacion as CA
        return CA.tramo_corto(tramo)
    except Exception:
        return tramo


def _hora(tramo):
    try:
        import corp_asignacion as CA
        return CA.info_tramo(tramo).get("hora") or ""
    except Exception:
        return ""


def _km(r):
    try:
        k = float(r["km_final"] or 0) - float(r["km_inicial"] or 0)
    except (TypeError, ValueError):
        return 0.0
    return k if 0 < k <= KM_MAX else 0.0


def _leer(conn, desde, hasta):
    filas = conn.execute("""SELECT id, chofer_usuario, chofer_nombre, cliente, tramo, fecha_servicio, bus_interno,
                                   km_inicial, km_final, pasajeros, estado, monto
                            FROM rendiciones_corp WHERE fecha_servicio >= ? AND fecha_servicio <= ?""",
                         (desde, hasta + "~")).fetchall()
    out = []
    for r in filas:
        r = dict(r)
        cli, tr = C._canonizar(r["cliente"], r["tramo"])
        r["cliente_c"] = cli or (r["cliente"] or "").strip().upper()
        r["tramo_c"] = tr or (r["tramo"] or "").strip()
        r["fecha"] = str(r["fecha_servicio"])[:10]
        r["variable"] = C._es_variable(r["tramo_c"])
        out.append(r)
    return out


def _servicios(rends):
    """Agrupa las rendiciones en servicios: (cliente, tramo, fecha). Un
    VARIABLE es un servicio por rendición."""
    srv = {}
    for r in rends:
        k = (r["cliente_c"], r["tramo_c"], r["fecha"], r["id"] if r["variable"] else 0)
        s = srv.setdefault(k, {"cliente": r["cliente_c"], "tramo": r["tramo_c"], "fecha": r["fecha"],
                               "variable": r["variable"], "rends": []})
        s["rends"].append(r)
    for s in srv.values():
        vivos = [r for r in s["rends"] if r["estado"] != "suspendido"]
        lados = {r["estado"] for r in vivos}
        s["hecho"] = bool(vivos)
        s["completo"] = "completado" in lados or {"entrante", "saliente"} <= lados
        s["suspendido"] = not vivos
        s["pasajeros"] = sum(int(r["pasajeros"] or 0) for r in vivos)
        s["km"] = sum(_km(r) for r in vivos)
        s["costo"] = sum(float(r["monto"] or 0) for r in s["rends"])
    return list(srv.values())


def _totales(servs):
    hechos = [s for s in servs if s["hecho"]]
    pas = sum(s["pasajeros"] for s in hechos)
    costo = sum(s["costo"] for s in servs)
    return {
        "servicios": len(hechos),
        "completos": sum(1 for s in hechos if s["completo"]),
        "a_medias": sum(1 for s in hechos if not s["completo"]),
        "suspendidos": sum(1 for s in servs if s["suspendido"]),
        "pasajeros": pas,
        "pasajeros_prom": round(pas / len(hechos), 1) if hechos else 0,
        "km": round(sum(s["km"] for s in hechos)),
        "costo": round(costo),
        "costo_pasajero": round(costo / pas) if pas else None,
        "dias": len({s["fecha"] for s in hechos}),
    }


def _delta(a, b):
    if b in (None, 0) or a is None:
        return None
    return round((a - b) * 100 / b, 1)


def _ranking(servs, rends):
    por = {}
    for s in servs:
        k = (s["cliente"], s["tramo"])
        x = por.setdefault(k, {"cliente": s["cliente"], "tramo": s["tramo"], "corto": _corto(s["tramo"]),
                               "hora": _hora(s["tramo"]), "variable": s["variable"],
                               "servicios": 0, "completos": 0, "a_medias": 0, "suspendidos": 0,
                               "pasajeros": 0, "km": 0.0, "costo": 0.0, "dias": set(), "ultimo": ""})
        if s["hecho"]:
            x["servicios"] += 1
            x["completos" if s["completo"] else "a_medias"] += 1
            x["pasajeros"] += s["pasajeros"]
            x["km"] += s["km"]
            x["dias"].add(s["fecha"])
            x["ultimo"] = max(x["ultimo"], s["fecha"])
        else:
            x["suspendidos"] += 1
        x["costo"] += s["costo"]
    # Quiénes lo hacen y con qué coches
    gente, coches = {}, {}
    for r in rends:
        if r["estado"] == "suspendido":
            continue
        k = (r["cliente_c"], r["tramo_c"])
        nom = r["chofer_nombre"] or r["chofer_usuario"] or "?"
        gente.setdefault(k, {})[nom] = gente.setdefault(k, {}).get(nom, 0) + 1
        bus = re.sub(r"\D", "", str(r["bus_interno"] or "")).lstrip("0") or str(r["bus_interno"] or "").strip()
        if bus:
            coches.setdefault(k, {})[bus] = coches.setdefault(k, {}).get(bus, 0) + 1
    out = []
    for k, x in por.items():
        n = x["servicios"]
        g = sorted((gente.get(k) or {}).items(), key=lambda kv: (-kv[1], kv[0]))
        c = sorted((coches.get(k) or {}).items(), key=lambda kv: (-kv[1], kv[0]))
        total = n + x["suspendidos"]
        out.append({**{kk: v for kk, v in x.items() if kk != "dias"},
                    "km": round(x["km"]), "costo": round(x["costo"]),
                    "pasajeros_prom": round(x["pasajeros"] / n, 1) if n else 0,
                    "km_prom": round(x["km"] / n) if n else 0,
                    "costo_pasajero": round(x["costo"] / x["pasajeros"]) if x["pasajeros"] else None,
                    "pct_suspendido": round(x["suspendidos"] * 100 / total) if total else 0,
                    "choferes": len(g), "coches": len(c),
                    "choferes_top": [{"nombre": a, "n": b} for a, b in g[:5]],
                    "coches_top": [{"coche": a, "n": b} for a, b in c[:5]]})
    out.sort(key=lambda r: (-r["servicios"], -r["pasajeros"], r["cliente"], r["corto"]))
    for i, r in enumerate(out, 1):
        r["pos"] = i
    return out


def _por_cliente(servs, tot):
    por = {}
    for s in servs:
        x = por.setdefault(s["cliente"], [])
        x.append(s)
    out = []
    for cli, ss in por.items():
        t = _totales(ss)
        t["cliente"] = cli
        t["pct"] = round(t["servicios"] * 100 / tot["servicios"], 1) if tot["servicios"] else 0
        t["tramos"] = len({s["tramo"] for s in ss if s["hecho"]})
        out.append(t)
    out.sort(key=lambda x: -x["servicios"])
    return out


def _serie(servs, desde, hasta):
    d0, d1 = date.fromisoformat(desde), date.fromisoformat(hasta)
    dias = {}
    for s in servs:
        if s["hecho"]:
            x = dias.setdefault(s["fecha"], {})
            x[s["cliente"]] = x.get(s["cliente"], 0) + 1
    out = []
    d = d0
    while d <= d1:
        f = d.isoformat()
        por = dias.get(f, {})
        out.append({"fecha": f, "dia": DIAS_TXT[d.weekday()], "total": sum(por.values()), "por_cliente": por})
        d += timedelta(days=1)
    return out


def _choferes(rends):
    por = {}
    for r in rends:
        nom = r["chofer_nombre"] or r["chofer_usuario"] or "?"
        x = por.setdefault(nom, {"nombre": nom, "servicios": 0.0, "suspendidos": 0, "pasajeros": 0, "costo": 0.0,
                                 "tramos": set(), "clientes": set()})
        if r["estado"] == "suspendido":
            x["suspendidos"] += 1
            continue
        x["servicios"] += 1 if r["estado"] == "completado" or r["variable"] else 0.5
        x["pasajeros"] += int(r["pasajeros"] or 0)
        x["costo"] += float(r["monto"] or 0)
        x["tramos"].add((r["cliente_c"], r["tramo_c"]))
        x["clientes"].add(r["cliente_c"])
    out = [{**{k: v for k, v in x.items() if k not in ("tramos", "clientes")},
            "servicios": round(x["servicios"], 1), "costo": round(x["costo"]),
            "tramos": len(x["tramos"]), "clientes": sorted(x["clientes"])} for x in por.values()]
    out.sort(key=lambda x: (-x["servicios"], x["nombre"]))
    return out


def _coches(rends):
    por = {}
    for r in rends:
        if r["estado"] == "suspendido":
            continue
        bus = re.sub(r"\D", "", str(r["bus_interno"] or "")).lstrip("0") or str(r["bus_interno"] or "").strip()
        if not bus:
            continue
        x = por.setdefault(bus, {"coche": bus, "servicios": 0.0, "km": 0.0, "pasajeros": 0, "clientes": set()})
        x["servicios"] += 1 if r["estado"] == "completado" or r["variable"] else 0.5
        x["km"] += _km(r)
        x["pasajeros"] += int(r["pasajeros"] or 0)
        x["clientes"].add(r["cliente_c"])
    out = [{**{k: v for k, v in x.items() if k != "clientes"}, "servicios": round(x["servicios"], 1),
            "km": round(x["km"]), "clientes": sorted(x["clientes"])} for x in por.values()]
    out.sort(key=lambda x: (-x["servicios"], x["coche"]))
    return out


def panel(desde, hasta, cliente=""):
    hasta = min(hasta, _hoy())
    if desde > hasta:
        desde = hasta
    n = (date.fromisoformat(hasta) - date.fromisoformat(desde)).days + 1
    ant_hasta = (date.fromisoformat(desde) - timedelta(days=1)).isoformat()
    ant_desde = (date.fromisoformat(desde) - timedelta(days=n)).isoformat()
    conn = get_connection()
    try:
        rends = _leer(conn, desde, hasta)
        ant = _leer(conn, ant_desde, ant_hasta)
        primero = conn.execute("SELECT MIN(fecha_servicio) AS f FROM rendiciones_corp").fetchone()
    finally:
        conn.close()
    clientes = sorted({r["cliente_c"] for r in rends} | {r["cliente_c"] for r in ant})
    if cliente:
        rends = [r for r in rends if r["cliente_c"] == cliente]
        ant = [r for r in ant if r["cliente_c"] == cliente]
    servs, servs_ant = _servicios(rends), _servicios(ant)
    tot, tot_ant = _totales(servs), _totales(servs_ant)
    deltas = {k: _delta(tot[k], tot_ant[k]) for k in ("servicios", "pasajeros", "km", "costo", "pasajeros_prom")}
    return {
        "desde": desde, "hasta": hasta, "dias_periodo": n, "cliente": cliente,
        "clientes_disponibles": clientes,
        "anterior": {"desde": ant_desde, "hasta": ant_hasta, **tot_ant},
        "totales": tot, "deltas": deltas,
        "ranking": _ranking(servs, rends),
        "por_cliente": _por_cliente(servs, tot),
        "serie": _serie(servs, desde, hasta),
        "choferes": _choferes(rends),
        "coches": _coches(rends),
        "hay_datos": bool(rends),
        "primer_dia": str((primero or {})["f"] or "")[:10] if primero else "",
    }


# ════════════════════════════════════════════════════════════════════════════
# PDF: el ranking por servicio
# ════════════════════════════════════════════════════════════════════════════

ORDENES = {
    "servicios": ("Más hechos", lambda r: (-r["servicios"], -r["pasajeros"])),
    "pasajeros": ("Más pasajeros", lambda r: (-r["pasajeros"], -r["servicios"])),
    "costo": ("Más plata", lambda r: (-r["costo"], -r["servicios"])),
    "costo_pasajero": ("Más caros por pasajero", lambda r: (-(r["costo_pasajero"] or 0), -r["servicios"])),
    "suspendidos": ("Más suspendidos", lambda r: (-r["suspendidos"], -r["servicios"])),
}


def _gs(n):
    return f"{round(n or 0):,}".replace(",", ".")


def _fdm(f):
    return f"{f[8:10]}/{f[5:7]}/{f[:4]}" if f and len(f) >= 10 else ""


def pdf_ranking(p, orden="servicios"):
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
    from pdf_export import AZUL, ROJO, GRIS, GRIS_CLARO
    from xml.sax.saxutils import escape as e

    LINEA = "#D9E2EE"
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), topMargin=12 * mm, bottomMargin=12 * mm,
                            leftMargin=12 * mm, rightMargin=12 * mm,
                            title="Servicios de corporativos", author="La Santaniana")
    st = getSampleStyleSheet()
    normal = st["Normal"]
    tit = ParagraphStyle("CsTit", parent=st["Heading1"], fontSize=17, textColor=colors.HexColor(AZUL), spaceAfter=2)
    h2 = ParagraphStyle("CsH2", parent=st["Heading2"], fontSize=12, textColor=colors.HexColor(AZUL), spaceBefore=4, spaceAfter=4)
    sub = ParagraphStyle("CsSub", parent=normal, fontSize=9, textColor=colors.HexColor(GRIS))
    sm = ParagraphStyle("CsSm", parent=normal, fontSize=8.3, leading=10)
    smg = ParagraphStyle("CsSmg", parent=sm, textColor=colors.HexColor(GRIS))
    t, d = p["totales"], p["deltas"]
    nombre_orden, clave = ORDENES.get(orden, ORDENES["servicios"])

    def dl(k):
        v = d.get(k)
        if v is None:
            return ""
        return f"<br/><font color='{GRIS}' size=7.5>{'+' if v > 0 else ''}{str(v).replace('.', ',')} % vs. período anterior</font>"

    story = [
        Paragraph("<b>LA SANTANIANA</b>", ParagraphStyle("CsE", parent=normal, fontSize=12, textColor=colors.HexColor(ROJO))),
        Paragraph("Servicios de corporativos" + (f" · {e(p['cliente'])}" if p.get("cliente") else ""), tit),
        Paragraph(f"Del {_fdm(p['desde'])} al {_fdm(p['hasta'])}. Sale de lo que rindieron los choferes: un servicio es "
                  f"un tramo de una empresa en un día (si el entrante y el saliente los hicieron dos choferes, sigue siendo "
                  f"uno). El costo es lo que se le paga al chofer.", sub),
        Spacer(1, 3 * mm),
    ]
    numst = ParagraphStyle("CsNum", parent=normal, fontSize=16, leading=19, fontName="Helvetica-Bold")

    def kpi(num, txt, k=None):
        return [Paragraph(num, numst), Paragraph(txt + (dl(k) if k else ""), sm)]

    kp = Table([[
        kpi(_gs(t["servicios"]), "servicios hechos" + (f" ({t['a_medias']} a medias)" if t["a_medias"] else ""), "servicios"),
        kpi(_gs(t["pasajeros"]), f"pasajeros · {str(t['pasajeros_prom']).replace('.', ',')} por servicio", "pasajeros"),
        kpi(_gs(t["km"]), "km recorridos", "km"),
        kpi(f"Gs. {_gs(t['costo'])}", "costo" + (f" · Gs. {_gs(t['costo_pasajero'])} por pasajero" if t["costo_pasajero"] else ""), "costo"),
        kpi(str(t["suspendidos"]), "suspendidos"),
    ]], colWidths=[54.6 * mm] * 5)
    kp.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(GRIS_CLARO)),
                            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor(LINEA)),
                            ("LINEAFTER", (0, 0), (-2, -1), 0.5, colors.HexColor(LINEA)),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    story += [kp, Spacer(1, 4 * mm), Paragraph(f"Ranking por servicio · {nombre_orden.lower()}", h2)]

    filas = sorted(p["ranking"], key=clave)
    data = [["#", "Servicio", "Empresa", "Veces", "A medias", "Pasajeros", "Prom.", "Km", "Costo (Gs.)",
             "Gs. por pas.", "Susp.", "Choferes que más lo hacen"]]
    for i, r in enumerate(filas, 1):
        quien = ", ".join(f"{e(c['nombre'].split(',')[0].title())} ({c['n']})" for c in r["choferes_top"][:3])
        data.append([str(i), Paragraph(f"<b>{e(r['corto'])}</b>" + (f" <font color='{GRIS}'>{e(r['hora'])}</font>" if r["hora"] else ""), sm),
                     r["cliente"], str(r["servicios"]), str(r["a_medias"] or "—"), _gs(r["pasajeros"]),
                     str(r["pasajeros_prom"]).replace(".", ","), _gs(r["km"]), _gs(r["costo"]),
                     _gs(r["costo_pasajero"]) if r["costo_pasajero"] else "—", str(r["suspendidos"] or "—"),
                     Paragraph(quien or "—", smg)])
    tb = Table(data, colWidths=[8 * mm, 52 * mm, 24 * mm, 14 * mm, 15 * mm, 18 * mm, 13 * mm, 16 * mm, 22 * mm,
                                18 * mm, 12 * mm, 61 * mm], repeatRows=1)
    estilo = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(AZUL)), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
              ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 8.3),
              ("ALIGN", (3, 0), (10, -1), "RIGHT"), ("ALIGN", (0, 0), (0, -1), "CENTER"),
              ("FONTNAME", (3, 1), (3, -1), "Helvetica-Bold"),
              ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
              ("LINEBELOW", (0, 1), (-1, -1), 0.4, colors.HexColor(LINEA)),
              ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5)]
    for i in range(1, min(4, len(data))):
        estilo.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#F3F7FC")))
    tb.setStyle(TableStyle(estilo))
    story.append(tb)

    if p["por_cliente"] and not p.get("cliente"):
        story += [Spacer(1, 4 * mm), Paragraph("Por empresa", h2)]
        data = [["Empresa", "Servicios", "% del total", "Tramos", "Pasajeros", "Prom.", "Km", "Costo (Gs.)", "Gs. por pas.", "Susp."]]
        for c in p["por_cliente"]:
            data.append([c["cliente"], str(c["servicios"]), f"{str(c['pct']).replace('.', ',')} %", str(c["tramos"]),
                         _gs(c["pasajeros"]), str(c["pasajeros_prom"]).replace(".", ","), _gs(c["km"]), _gs(c["costo"]),
                         _gs(c["costo_pasajero"]) if c["costo_pasajero"] else "—", str(c["suspendidos"] or "—")])
        tb = Table(data, colWidths=[40 * mm] + [24 * mm] * 9, repeatRows=1)
        tb.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(AZUL)), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                                ("ALIGN", (1, 0), (-1, -1), "RIGHT"), ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
                                ("LINEBELOW", (0, 1), (-1, -1), 0.4, colors.HexColor(LINEA)),
                                ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        story.append(tb)
    story += [Spacer(1, 3 * mm), Paragraph(f"Impreso el {_fdm(ahora_iso()[:10])} a las {ahora_iso()[11:16]}.", smg)]
    doc.build(story)
    buf.seek(0)
    return buf


# ════════════════════════════════════════════════════════════════════════════
# RUTAS
# ════════════════════════════════════════════════════════════════════════════

def _puede():
    return C._rol_efectivo() in ("admin", "auditor", "operador_corp")


def _periodo():
    hoy = _hoy()
    desde = request.args.get("desde") or (date.fromisoformat(hoy) - timedelta(days=29)).isoformat()
    hasta = request.args.get("hasta") or hoy
    if not _fecha(desde) or not _fecha(hasta):
        raise ValueError("Fechas inválidas")
    if (_fecha(hasta) - _fecha(desde)).days > MAX_DIAS:
        desde = (_fecha(hasta) - timedelta(days=MAX_DIAS)).isoformat()
    return desde[:10], hasta[:10]


@bp_corp_servicios.route("/api/corp/servicios/panel", methods=["GET"])
def api_panel():
    if not _puede():
        return jsonify({"error": "Sin permiso"}), 403
    try:
        desde, hasta = _periodo()
    except ValueError as ex:
        return jsonify({"error": str(ex)}), 400
    return jsonify(panel(desde, hasta, (request.args.get("cliente") or "").strip().upper()))


@bp_corp_servicios.route("/api/corp/servicios/pdf", methods=["GET"])
def api_pdf():
    if not _puede():
        return jsonify({"error": "Sin permiso"}), 403
    try:
        desde, hasta = _periodo()
    except ValueError as ex:
        return jsonify({"error": str(ex)}), 400
    p = panel(desde, hasta, (request.args.get("cliente") or "").strip().upper())
    buf = pdf_ranking(p, request.args.get("orden") or "servicios")
    return send_file(buf, mimetype="application/pdf", as_attachment=False,
                     download_name=f"servicios-corporativos-{p['desde']}-{p['hasta']}.pdf")
