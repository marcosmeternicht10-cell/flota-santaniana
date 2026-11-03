"""
informe_coche.py — Informe completo de un coche, en PDF (La Santaniana)

Todo lo que se le hizo a un coche y cómo anduvo, en un solo documento para
imprimir o mandar:

  1. Ficha: marca, modelo, patente, plan, km actual.
  2. Los números del período: OTs, trabajos, correctivos, preventivos, costo,
     costo por km, horas de taller, días parado, consumo contra su motor,
     servicios hechos.
  3. Gráficos por mes: costo de mantenimiento y cantidad de trabajos.
  4. Lo que más se le rompe y el diagnóstico (el del dossier).
  5. La historia completa, de lo más nuevo a lo más viejo: cada OT con sus
     trabajos, técnicos y repuestos; correctivos; preventivos del plan; lo
     cargado en el libro; cambios de cubiertas.
  6. Repuestos usados, combustible, días fuera de servicio y documentos.

Sin fechas, toma toda la historia del coche (desde el primer registro).

  GET /api/vehiculos/<vid>/informe.pdf?desde=AAAA-MM-DD&hasta=AAAA-MM-DD
"""

import io
from datetime import date, timedelta

from flask import Blueprint, jsonify, request, send_file, session

from db_compat import get_connection
from hora_local import hoy as _hoy, ahora_iso
from nombres import apellido_primero_varios

bp_informe_coche = Blueprint("informe_coche", __name__)

MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
MESES_L = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
           "octubre", "noviembre", "diciembre"]
ROLES = ("admin", "taller", "gerente", "auditor", "compras", "contabilidad")


def _f(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def gs(n):
    return "Gs. " + f"{round(_f(n)):,}".replace(",", ".")


def miles(n):
    return f"{round(_f(n)):,}".replace(",", ".")


def dmy(f):
    f = str(f or "")[:10]
    return f"{f[8:10]}/{f[5:7]}/{f[:4]}" if len(f) == 10 else (f or "—")


def _q(conn, sql, params=()):
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return []


# ════════════════════════════════════════════════════════════════════════════
# LOS DATOS
# ════════════════════════════════════════════════════════════════════════════

def _primer_registro(conn, vid):
    fechas = []
    for sql in ("SELECT MIN(substr(fecha_apertura,1,10)) AS f FROM ordenes_trabajo WHERE vehiculo_id=?",
                "SELECT MIN(fecha) AS f FROM correctivos WHERE vehiculo_id=?",
                "SELECT MIN(fecha) AS f FROM mantenimientos_realizados WHERE vehiculo_id=? AND COALESCE(origen,'manual') <> 'inicial'",
                "SELECT MIN(fecha) AS f FROM historial_eventos WHERE vehiculo_id=?",
                "SELECT MIN(substr(fecha,1,10)) AS f FROM combustible WHERE vehiculo_id=?"):
        r = _q(conn, sql, (vid,))
        if r and r[0].get("f"):
            fechas.append(str(r[0]["f"])[:10])
    return min(fechas) if fechas else (date.fromisoformat(_hoy()) - timedelta(days=365)).isoformat()


def datos(vid, desde=None, hasta=None):
    from ot_horas import horas_trabajadas
    hoy = _hoy()
    conn = get_connection()
    try:
        veh = _q(conn, "SELECT * FROM vehiculos WHERE id=?", (vid,))
        if not veh:
            return None
        veh = veh[0]
        hasta = (hasta or hoy)[:10]
        desde = (desde or _primer_registro(conn, vid))[:10]
        if desde > hasta:
            desde, hasta = hasta, desde
        plan = _q(conn, """SELECT p.nombre FROM vehiculo_plan vp JOIN planes_mantenimiento p ON p.id = vp.plan_id
                           WHERE vp.vehiculo_id=?""", (vid,))
        num = str(veh.get("n_interno") or "").strip()

        # ── Órdenes de trabajo con sus trabajos, repuestos y horas ──
        ots = _q(conn, """SELECT * FROM ordenes_trabajo WHERE vehiculo_id=?
                          AND substr(fecha_apertura,1,10) >= ? AND substr(fecha_apertura,1,10) <= ?
                          ORDER BY fecha_apertura DESC""", (vid, desde, hasta))
        ids = [o["id"] for o in ots]
        items, mats, horas = {}, {}, {}
        if ids:
            marcas = ",".join("?" * len(ids))
            for it in _q(conn, f"SELECT * FROM ot_items WHERE ot_id IN ({marcas}) ORDER BY id", ids):
                items.setdefault(it["ot_id"], []).append(it)
            for m in _q(conn, f"SELECT * FROM ot_materiales WHERE ot_id IN ({marcas}) ORDER BY id", ids):
                mats.setdefault(m["ot_id"], []).append(m)
            for h in _q(conn, f"SELECT ot_id, inicio, fin FROM ot_horas WHERE ot_id IN ({marcas})", ids):
                horas[h["ot_id"]] = horas.get(h["ot_id"], 0) + horas_trabajadas(h["inicio"], h["fin"])
        repuestos = []
        for o in ots:
            o["items"] = items.get(o["id"], [])
            o["materiales"] = mats.get(o["id"], [])
            cm = sum(_f(m.get("cantidad") or 1) * _f(m.get("precio_unit")) for m in o["materiales"])
            o["costo"] = cm or sum(_f(i.get("precio_compras")) or _f(i.get("costo")) for i in o["items"])
            o["horas"] = round(horas.get(o["id"], 0), 1)
            o["tecnicos"] = sorted({apellido_primero_varios(i["tecnico"]) for i in o["items"] if (i.get("tecnico") or "").strip()})
            for m in o["materiales"]:
                repuestos.append({"fecha": str(o["fecha_apertura"])[:10], "ot": o["id"], "descripcion": m.get("descripcion") or "",
                                  "cantidad": _f(m.get("cantidad") or 1), "precio": _f(m.get("precio_unit")),
                                  "proveedor": m.get("proveedor") or ""})

        correctivos = _q(conn, """SELECT * FROM correctivos WHERE vehiculo_id=? AND fecha >= ? AND fecha <= ?
                                  ORDER BY fecha DESC""", (vid, desde, hasta))
        # Los «inicial» son el punto de partida que se cargó al asignar el plan, no trabajos hechos
        preventivos = _q(conn, """SELECT m.*, t.tarea, t.categoria FROM mantenimientos_realizados m
                                  LEFT JOIN tareas_plan t ON t.id = m.tarea_plan_id
                                  WHERE m.vehiculo_id=? AND m.fecha >= ? AND m.fecha <= ?
                                  AND COALESCE(m.origen,'manual') <> 'inicial' ORDER BY m.fecha DESC""",
                         (vid, desde, hasta))
        primero = _primer_registro(conn, vid)
        eventos = _q(conn, """SELECT * FROM historial_eventos WHERE vehiculo_id=? AND fecha >= ? AND fecha <= ?
                              ORDER BY fecha DESC""", (vid, desde, hasta))
        cubiertas = _q(conn, """SELECT i.*, n.codigo, n.marca, n.medida FROM instalaciones_neumaticos i
                                LEFT JOIN neumaticos n ON n.id = i.neumatico_id
                                WHERE i.vehiculo_id=? AND (
                                  (i.fecha_instalacion >= ? AND i.fecha_instalacion <= ?) OR
                                  (COALESCE(i.fecha_retiro,'') >= ? AND COALESCE(i.fecha_retiro,'') <= ?))
                                ORDER BY i.fecha_instalacion DESC""", (vid, desde, hasta, desde, hasta))
        cubiertas_puestas = _q(conn, """SELECT i.posicion, n.codigo, n.marca, n.medida, i.fecha_instalacion, i.km_instalacion
                                        FROM instalaciones_neumaticos i LEFT JOIN neumaticos n ON n.id = i.neumatico_id
                                        WHERE i.vehiculo_id=? AND (i.fecha_retiro IS NULL OR i.fecha_retiro='')
                                        ORDER BY i.posicion""", (vid,))
        parado = _q(conn, """SELECT * FROM fuera_servicio WHERE vehiculo_id=? AND fecha_desde <= ?
                             AND COALESCE(NULLIF(fecha_hasta,''), ?) >= ? ORDER BY fecha_desde DESC""",
                    (vid, hasta, hoy, desde))
        documentos = _q(conn, """SELECT * FROM documentos WHERE vehiculo_id=? AND reemplazado_por IS NULL
                                 ORDER BY fecha_vencimiento""", (vid,))
        costos = _q(conn, """SELECT * FROM costos WHERE vehiculo_id=? AND mes >= ? AND mes <= ? ORDER BY mes""",
                    (vid, desde[:7], hasta[:7]))
        # Servicios: lo que salió en tráfico y en turismo con este coche
        servs = []
        if num:
            try:
                from servicios import leer_servicios
                servs = [s for s in leer_servicios(conn, desde, min(hasta, hoy)) if s["coche"] == num]
            except Exception:
                servs = []
        turismo = _q(conn, """SELECT fecha, fecha_fin, cliente, salida, destino, estado FROM agenda_turismo
                              WHERE (coche_interno=? OR coche_interno_2=? OR coche_interno_3=?)
                              AND COALESCE(estado,'') <> 'cancelado' AND fecha >= ? AND fecha <= ?
                              ORDER BY fecha DESC""", (num, num, num, desde, hasta)) if num else []
    finally:
        conn.close()

    # Combustible, km y diagnóstico: funciones que ya existen
    comb, consumo, comparacion, km_actual, dossier = [], {}, {}, None, {}
    try:
        from database import obtener_cargas_combustible, consumo_promedio, comparar_con_referencia, km_actual_vehiculo
        comb = obtener_cargas_combustible(vehiculo_id=vid, desde=desde, hasta=hasta, limite=5000) or []
        consumo = consumo_promedio(comb)
        comparacion = comparar_con_referencia(vid, consumo) or {}
        km = km_actual_vehiculo(vid)
        km_actual = km.get("km") if isinstance(km, dict) else km
    except Exception as e:
        print("informe coche (combustible/km):", e)
    try:
        from dossier_db import generar_dossier
        dossier = generar_dossier(vid, desde, hasta) or {}
    except Exception as e:
        print("informe coche (dossier):", e)

    # ── Números ──
    hoy_d = date.fromisoformat(hoy)
    dias_parado = 0
    for p in parado:
        a = max(date.fromisoformat(str(p["fecha_desde"])[:10]), date.fromisoformat(desde))
        b = min(date.fromisoformat(str(p.get("fecha_hasta") or hoy)[:10] or hoy), date.fromisoformat(hasta), hoy_d)
        p["dias"] = max(0, (b - a).days + 1)
        dias_parado += p["dias"]
    trabajos = sum(len(o["items"]) for o in ots)
    hechos = sum(1 for o in ots for i in o["items"] if (i.get("estado") or "") in ("completado", "hecho", "terminado"))
    c_ots = sum(o["costo"] for o in ots)
    c_corr = sum(_f(c.get("costo")) for c in correctivos)
    c_prev = sum(_f(p.get("costo")) for p in preventivos if not p.get("ot_id"))
    c_ev = sum(_f(e.get("costo")) for e in eventos)
    costo_mant = c_ots + c_corr + c_prev + c_ev
    km_serv = sum(s["km"] or 0 for s in servs)
    km_rec = (dossier.get("metricas") or {}).get("km_recorridos") or consumo.get("km_totales") or km_serv
    litros = sum(_f(c.get("litros")) for c in comb)
    c_comb = sum(_f(c.get("costo_total")) for c in comb)

    # ── Por mes ──
    meses = []
    d = date.fromisoformat(desde[:7] + "-01")
    fin = date.fromisoformat(hasta[:7] + "-01")
    while d <= fin and len(meses) < 120:
        meses.append(d.isoformat()[:7])
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    por_mes = {m: {"costo": 0, "trabajos": 0, "correctivos": 0, "litros": 0, "servicios": 0} for m in meses}

    def sumar(f, k, v):
        m = str(f or "")[:7]
        if m in por_mes:
            por_mes[m][k] += v
    for o in ots:
        sumar(o["fecha_apertura"], "costo", o["costo"])
        sumar(o["fecha_apertura"], "trabajos", len(o["items"]) or 1)
    for c in correctivos:
        sumar(c["fecha"], "costo", _f(c.get("costo")))
        sumar(c["fecha"], "correctivos", 1)
    for p in preventivos:
        if not p.get("ot_id"):
            sumar(p["fecha"], "costo", _f(p.get("costo")))
    for e in eventos:
        sumar(e["fecha"], "costo", _f(e.get("costo")))
    for c in comb:
        sumar(c.get("fecha"), "litros", _f(c.get("litros")))
    for s in servs:
        sumar(s["fecha"], "servicios", 1)

    # ── La historia completa, de lo más nuevo a lo más viejo ──
    hist = []
    for o in ots:
        trab = [i.get("descripcion") or "" for i in o["items"]]
        det = f"OT #{o['id']}" + (f" · {o['procedencia']}" if o.get("procedencia") else "")
        hist.append({"fecha": str(o["fecha_apertura"])[:10], "tipo": "OT", "titulo": det,
                     "detalle": "; ".join(t for t in trab if t) or (o.get("observaciones") or ""),
                     "extra": " · ".join(x for x in (
                         ("Técnicos: " + ", ".join(o["tecnicos"])) if o["tecnicos"] else "",
                         f"{len(o['materiales'])} repuesto(s)" if o["materiales"] else "",
                         f"{o['horas']} h de taller" if o["horas"] else "",
                         f"cerrada {dmy(o['fecha_cierre'])}" if o.get("fecha_cierre") else (o.get("estado") or "")) if x),
                     "km": o.get("km"), "costo": o["costo"]})
    for c in correctivos:
        hist.append({"fecha": c["fecha"], "tipo": "Correctivo", "titulo": c.get("tipo_falla") or "Correctivo",
                     "detalle": " · ".join(x for x in (c.get("descripcion"), c.get("reparacion")) if x),
                     "extra": c.get("taller") or "", "km": c.get("km"), "costo": _f(c.get("costo"))})
    # Los preventivos del mismo día y la misma OT (o el mismo km) van juntos en una fila
    grupos = {}
    for p in preventivos:
        if (p.get("origen") or "") == "ot":
            continue                          # ya figura dentro de su OT
        k = (p["fecha"], p.get("ot_id") or "", p.get("km") or "")
        g = grupos.setdefault(k, {"fecha": p["fecha"], "ot": p.get("ot_id"), "km": p.get("km"), "tareas": [], "costo": 0, "obs": []})
        g["tareas"].append(p.get("tarea") or "Tarea del plan")
        g["costo"] += 0 if p.get("ot_id") else _f(p.get("costo"))
        if p.get("observaciones"):
            g["obs"].append(p["observaciones"])
    for g in grupos.values():
        hist.append({"fecha": g["fecha"], "tipo": "Preventivo",
                     "titulo": g["tareas"][0] if len(g["tareas"]) == 1 else f"Preventivo del plan · {len(g['tareas'])} tareas",
                     "detalle": "; ".join(g["tareas"]) if len(g["tareas"]) > 1 else "; ".join(g["obs"]),
                     "extra": f"OT #{g['ot']}" if g["ot"] else "", "km": g["km"], "costo": g["costo"]})
    for e in eventos:
        hist.append({"fecha": e["fecha"], "tipo": (e.get("tipo") or "Libro").capitalize(),
                     "titulo": e.get("categoria") or "Registro", "detalle": e.get("descripcion") or "",
                     "extra": e.get("taller") or "", "km": e.get("km"), "costo": _f(e.get("costo"))})
    for n in cubiertas:
        if n.get("fecha_instalacion") and desde <= str(n["fecha_instalacion"])[:10] <= hasta:
            hist.append({"fecha": str(n["fecha_instalacion"])[:10], "tipo": "Cubierta", "titulo": f"Se puso {n.get('codigo') or 'una cubierta'}",
                         "detalle": f"Posición {n.get('posicion') or '—'}" + (f" · {n['marca']}" if n.get("marca") else ""),
                         "extra": "", "km": n.get("km_instalacion"), "costo": 0})
        if n.get("fecha_retiro") and desde <= str(n["fecha_retiro"])[:10] <= hasta:
            hist.append({"fecha": str(n["fecha_retiro"])[:10], "tipo": "Cubierta", "titulo": f"Se sacó {n.get('codigo') or 'una cubierta'}",
                         "detalle": f"Posición {n.get('posicion') or '—'}" + (f" · {n['motivo_retiro']}" if n.get("motivo_retiro") else ""),
                         "extra": "", "km": n.get("km_retiro"), "costo": 0})
    hist.sort(key=lambda x: (x["fecha"] or "", x["tipo"]), reverse=True)

    # Lo que más se repite (por descripción de los trabajos y tipo de falla)
    cuenta = {}
    for o in ots:
        for i in o["items"]:
            k = " ".join(str(i.get("descripcion") or "").strip().split()).capitalize()
            if k:
                cuenta[k] = cuenta.get(k, 0) + 1
    for c in correctivos:
        k = (c.get("tipo_falla") or "").strip().capitalize()
        if k:
            cuenta[k] = cuenta.get(k, 0) + 1
    repetidos = sorted(({"que": k, "n": n} for k, n in cuenta.items() if n >= 2), key=lambda x: -x["n"])[:8]

    rep_tot = {}
    for r in repuestos:
        k = " ".join(r["descripcion"].split()).upper()
        x = rep_tot.setdefault(k, {"descripcion": r["descripcion"], "cantidad": 0, "total": 0, "veces": 0, "ultima": ""})
        x["cantidad"] += r["cantidad"]
        x["total"] += r["cantidad"] * r["precio"]
        x["veces"] += 1
        x["ultima"] = max(x["ultima"], r["fecha"])
    rep_tot = sorted(rep_tot.values(), key=lambda x: -x["total"])

    for doc in documentos:
        v = str(doc.get("fecha_vencimiento") or "")[:10]
        doc["estado"] = "Sin fecha" if not v else "Vencido" if v < hoy else \
            "Vence pronto" if v <= (hoy_d + timedelta(days=30)).isoformat() else "Vigente"

    return {
        "vehiculo": veh, "plan": plan[0]["nombre"] if plan else "", "desde": desde, "hasta": hasta, "hoy": hoy,
        "primer_registro": primero,
        "km_actual": km_actual, "ots": ots, "correctivos": correctivos, "preventivos": preventivos,
        "eventos": eventos, "cubiertas_puestas": cubiertas_puestas, "parado": parado, "documentos": documentos,
        "costos": costos, "servicios": servs, "turismo": turismo, "historia": hist, "repetidos": repetidos,
        "repuestos": rep_tot, "repuestos_lineas": len(repuestos), "por_mes": [{"mes": m, **v} for m, v in por_mes.items()],
        "consumo": consumo, "comparacion": comparacion, "dossier": dossier,
        "numeros": {
            "ots": len(ots), "trabajos": trabajos, "hechos": hechos, "correctivos": len(correctivos),
            "preventivos": len(preventivos), "eventos": len(eventos), "costo_mant": costo_mant,
            "costo_ots": c_ots, "costo_correctivos": c_corr, "costo_otros": c_prev + c_ev,
            "costo_km": (costo_mant / km_rec) if km_rec else 0, "km_recorridos": km_rec,
            "horas": round(sum(o["horas"] for o in ots), 1), "dias_parado": dias_parado,
            "servicios": len(servs), "km_servicios": round(km_serv), "turismo": len(turismo),
            "litros": litros, "costo_combustible": c_comb, "cargas": len(comb),
            "costos_extra": sum(_f(c.get("monto")) for c in costos),
        },
    }


# ════════════════════════════════════════════════════════════════════════════
# EL PDF
# ════════════════════════════════════════════════════════════════════════════

def generar_pdf(d, generado_por=""):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import (BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle,
                                    KeepTogether, CondPageBreak)
    from reportlab.graphics.shapes import Drawing, Rect, String, Line
    from trafico_pdf import _fuentes, NAVY, AZUL, ROJO, TINTA, GRIS, GRIS2, LINEA, CEBRA, VERDE, AMBAR, AMBAR_F, ROJO_F
    import os

    F = _fuentes()
    W, H = A4
    M = 14 * mm
    AW = W - 2 * M
    v = d["vehiculo"]
    n = d["numeros"]
    num = v.get("n_interno") or v.get("patente") or "—"
    periodo = f"Del {dmy(d['desde'])} al {dmy(d['hasta'])}"
    logo = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "logo.png")
    esc = lambda t: str(t if t is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    st = {
        "sec": ParagraphStyle("sec", fontName=F["D8"], fontSize=15, leading=18, textColor=NAVY, spaceBefore=10, spaceAfter=6),
        "sub": ParagraphStyle("sub", fontName=F["I4"], fontSize=8.5, leading=11.5, textColor=GRIS, spaceAfter=6),
        "p": ParagraphStyle("p", fontName=F["I4"], fontSize=8.5, leading=11.5, textColor=TINTA),
        "pb": ParagraphStyle("pb", fontName=F["I6"], fontSize=8.5, leading=11.5, textColor=TINTA),
        "chico": ParagraphStyle("chico", fontName=F["I4"], fontSize=7.4, leading=9.6, textColor=GRIS),
        "th": ParagraphStyle("th", fontName=F["I6"], fontSize=7, leading=9, textColor=GRIS),
        "num": ParagraphStyle("num", fontName=F["D9"], fontSize=20, leading=22, textColor=NAVY),
        "numl": ParagraphStyle("numl", fontName=F["I5"], fontSize=7.4, leading=9.2, textColor=GRIS),
    }

    def pie(c, doc):
        c.saveState()
        # Franja de arriba
        c.setFillColor(NAVY)
        c.rect(0, H - 22 * mm, W, 22 * mm, stroke=0, fill=1)
        c.setFillColor(ROJO)
        p = c.beginPath()
        p.moveTo(W - 46 * mm, H); p.lineTo(W - 34 * mm, H); p.lineTo(W - 44 * mm, H - 22 * mm); p.lineTo(W - 56 * mm, H - 22 * mm)
        p.close(); c.drawPath(p, stroke=0, fill=1)
        if os.path.exists(logo):
            c.setFillColor(colors.white)
            c.roundRect(M, H - 18 * mm, 14 * mm, 14 * mm, 3 * mm, stroke=0, fill=1)
            c.drawImage(logo, M + 1.5 * mm, H - 16.5 * mm, 11 * mm, 11 * mm, preserveAspectRatio=True, mask="auto")
        x = M + 18 * mm
        c.setFillColor(colors.white)
        c.setFont(F["D9"], 17)
        c.drawString(x, H - 10.5 * mm, f"INFORME DEL COCHE {num}")
        c.setFont(F["I4"], 8)
        c.setFillColor(colors.HexColor("#A9C4E3"))
        c.drawString(x, H - 15.5 * mm, f"{periodo} · {' '.join(str(t) for t in (v.get('marca'), v.get('modelo')) if t)} · {v.get('patente') or ''}")
        # Pie
        c.setFont(F["I4"], 7)
        c.setFillColor(GRIS2)
        c.drawString(M, 9 * mm, f"La Santaniana · Gestión de Flota · generado el {dmy(ahora_iso()[:10])} {ahora_iso()[11:16]}"
                                + (f" por {generado_por}" if generado_por else ""))
        c.drawRightString(W - M, 9 * mm, f"Hoja {doc.page}")
        c.restoreState()

    salida = io.BytesIO()
    doc = BaseDocTemplate(salida, pagesize=A4, leftMargin=M, rightMargin=M, topMargin=28 * mm, bottomMargin=16 * mm,
                          title=f"Informe del coche {num}", author="La Santaniana")
    doc.addPageTemplates([PageTemplate(id="h", frames=[Frame(M, 16 * mm, AW, H - 44 * mm, id="f", leftPadding=0,
                                                              rightPadding=0, topPadding=0, bottomPadding=0)], onPage=pie)])
    el = []

    def tabla(filas, anchos, cab=True, cebra=True, alinear=None):
        t = Table(filas, colWidths=anchos, repeatRows=1 if cab else 0)
        s = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
             ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5)]
        if cab:
            s += [("LINEBELOW", (0, 0), (-1, 0), 0.8, NAVY), ("BOTTOMPADDING", (0, 0), (-1, 0), 5)]
        if cebra:
            for i in range(1 if cab else 0, len(filas)):
                if i % 2 == 0:
                    s.append(("BACKGROUND", (0, i), (-1, i), CEBRA))
        for c in (alinear or []):
            s.append(("ALIGN", (c, 0), (c, -1), "RIGHT"))
        t.setStyle(TableStyle(s))
        return t

    P = lambda t, s="p": Paragraph(esc(t), st[s])
    TH = lambda t: Paragraph(esc(t).upper(), st["th"])

    # ── Ficha y números ──
    ficha = [("Coche", f"{num}"), ("Patente", v.get("patente") or "—"),
             ("Marca y modelo", " ".join(str(t) for t in (v.get("marca"), v.get("modelo")) if t) or "—"),
             ("Año", str(v.get("año") or v.get("anio") or "—")), ("Asientos", str(v.get("asientos") or "—")),
             ("Plan de mantenimiento", d["plan"] or "Sin plan asignado"),
             ("Km actual", f"{miles(d['km_actual'])} km" if d["km_actual"] else "—"),
             ("Estado", "Activo" if (v.get("activo") in (1, True, None)) else "Dado de baja")]
    ft = Table([[Paragraph(esc(k).upper(), st["th"]), Paragraph(esc(val), st["pb"])] for k, val in ficha],
               colWidths=[42 * mm, AW / 2 - 42 * mm])
    ft.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.4, LINEA), ("TOPPADDING", (0, 0), (-1, -1), 3.2),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 3.2), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    dg = (d["dossier"] or {}).get("diagnostico") or {}
    oee = ((d["dossier"] or {}).get("oee") or {}).get("oee")
    resumen = [Paragraph("Cómo anduvo", st["sec"]),
               Paragraph(esc(dg.get("resumen") or "Resumen del período con todo lo registrado en el sistema."), st["p"])]
    if oee:
        resumen.append(Spacer(1, 4))
        resumen.append(Paragraph(f"<font name='{F['D9']}' size='22' color='#1D344E'>{round(oee)}%</font>"
                                 f"  <font name='{F['I5']}' size='7.5' color='#5B6B7F'>OEE DEL PERÍODO (DISPONIBILIDAD × RENDIMIENTO × CALIDAD)</font>", st["p"]))
    cab = Table([[ [Paragraph("Ficha", st["sec"]), ft], resumen ]], colWidths=[AW / 2, AW / 2])
    cab.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                             ("RIGHTPADDING", (0, 0), (0, 0), 10), ("RIGHTPADDING", (1, 0), (1, 0), 0)]))
    el.append(cab)

    cons = d["consumo"] or {}
    comp = d["comparacion"] or {}
    l100 = cons.get("litros_100km")
    ref = comp.get("esperado_litros_100km") or comp.get("referencia")
    kp = [
        (miles(n["ots"]), "órdenes de trabajo"), (miles(n["trabajos"]), "trabajos en esas OTs"),
        (miles(n["correctivos"]), "correctivos"), (miles(n["preventivos"]), "preventivos del plan"),
        (gs(n["costo_mant"]).replace("Gs. ", "Gs "), "costo de mantenimiento"),
        (f"Gs {miles(n['costo_km'])}" if n["costo_km"] >= 1 else "—", "costo de mantenimiento por km"),
        (f"{n['horas']:g} h" if n["horas"] else "—", "horas de taller"), (miles(n["dias_parado"]), "días fuera de servicio"),
        (f"{l100:.1f}".replace(".", ",") if l100 else "—", "litros cada 100 km" + (f" (su motor: {str(ref).replace('.', ',')})" if ref else "")),
        (miles(n["servicios"] + n["turismo"]), "servicios hechos (línea y turismo)"),
        (f"{miles(n['km_recorridos'])}" if n["km_recorridos"] else "—", "km recorridos"),
        (miles(n["repuestos_lineas"] if "repuestos_lineas" in n else d["repuestos_lineas"]), "repuestos cargados"),
    ]
    celdas = [[Paragraph(esc(a), st["num"]), Paragraph(esc(b), st["numl"])] for a, b in kp]
    filas = []
    for i in range(0, len(celdas), 4):
        fila = [celdas[i + k] if i + k < len(celdas) else "" for k in range(4)]
        filas.append(fila)
    kt = Table(filas, colWidths=[AW / 4] * 4)
    kt.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, LINEA), ("INNERGRID", (0, 0), (-1, -1), 0.6, LINEA),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 7),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 8), ("LEFTPADDING", (0, 0), (-1, -1), 8)]))
    aviso = (f" El primer registro de este coche en el sistema es del {dmy(d['primer_registro'])}: lo anterior "
             "(libro de a bordo, papeles) se suma desde Historial por coche → «Cargar del papel».")
    el += [Spacer(1, 6), Paragraph("Los números", st["sec"]),
           Paragraph(esc(periodo) + ". El costo suma OTs (repuestos), correctivos y lo cargado en el libro; el combustible va aparte."
                     + esc(aviso), st["sub"]), kt]

    # ── Gráficos por mes ──
    pm = d["por_mes"][-18:]
    if pm and any(x["costo"] or x["trabajos"] or x["correctivos"] for x in pm):
        def barras(titulo, serie, color, fmt):
            dw, dh = AW / 2 - 6, 54 * mm
            g = Drawing(dw, dh)
            g.add(String(0, dh - 9, titulo.upper(), fontName=F["I6"], fontSize=7, fillColor=GRIS))
            base, alto = 14, dh - 30
            mx = max(serie) or 1
            ancho = (dw - 4) / len(serie)
            g.add(Line(0, base, dw, base, strokeColor=LINEA, strokeWidth=0.6))
            imax = serie.index(max(serie))
            for i, (m, val) in enumerate(zip(pm, serie)):
                hb = alto * val / mx
                x = 2 + i * ancho + ancho * 0.18
                if val:
                    g.add(Rect(x, base, ancho * 0.64, max(hb, 0.8), fillColor=color, strokeColor=None, rx=1.5, ry=1.5))
                if i == imax and val:
                    g.add(String(x + ancho * 0.32, base + hb + 3, fmt(val), fontName=F["I6"], fontSize=6.5,
                                 fillColor=TINTA, textAnchor="middle"))
                if len(pm) <= 12 or i % 2 == 0:
                    g.add(String(x + ancho * 0.32, base - 9, MESES[int(m["mes"][5:7]) - 1] + "'" + m["mes"][2:4],
                                 fontName=F["I4"], fontSize=5.8, fillColor=GRIS2, textAnchor="middle"))
            return g
        g1 = barras("Costo de mantenimiento por mes", [x["costo"] for x in pm], NAVY, lambda v_: "Gs " + miles(v_))
        g2 = barras("Trabajos y correctivos por mes", [x["trabajos"] + x["correctivos"] for x in pm], AZUL, lambda v_: miles(v_))
        gt = Table([[g1, g2]], colWidths=[AW / 2, AW / 2])
        gt.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
        el += [Spacer(1, 4), KeepTogether([Paragraph("Mes a mes", st["sec"]), gt])]

    # ── Lo que más se repite y diagnóstico ──
    bloque = []
    if d["repetidos"]:
        mx = d["repetidos"][0]["n"]
        filas = [[TH("Qué"), TH("Veces"), ""]]
        for r in d["repetidos"]:
            barra = Drawing(60 * mm, 6)
            barra.add(Rect(0, 1, 60 * mm * r["n"] / mx, 4, fillColor=ROJO, strokeColor=None, rx=2, ry=2))
            filas.append([P(r["que"]), P(str(r["n"]), "pb"), barra])
        bloque += [Paragraph("Lo que más se repite", st["sec"]),
                   Paragraph("Trabajos y fallas que aparecen dos veces o más: ahí suele estar el problema de fondo.", st["sub"]),
                   tabla(filas, [AW - 82 * mm, 18 * mm, 64 * mm], cebra=False)]
    focos = dg.get("focos") or []
    if focos or dg.get("fortalezas"):
        bloque.append(Paragraph("Diagnóstico", st["sec"]))
        for fz in dg.get("fortalezas") or []:
            bloque.append(Paragraph(f"<font color='#2F7C46'>●</font> {esc(fz)}", st["p"]))
        for fo in focos:
            bloque.append(Spacer(1, 3))
            bloque.append(Paragraph(f"<b>{esc(fo.get('area'))}.</b> {esc(fo.get('porque'))} <i>{esc(fo.get('sugerencia'))}</i>", st["p"]))
    if bloque:
        el += [Spacer(1, 4)] + bloque

    # ── La historia completa ──
    el += [CondPageBreak(60 * mm), Paragraph("Todo lo que se le hizo", st["sec"]),
           Paragraph(f"{len(d['historia'])} registro(s), de lo más nuevo a lo más viejo.", st["sub"])]
    COL = {"OT": "#1E5A96", "Correctivo": "#DC2641", "Preventivo": "#2F7C46", "Cubierta": "#5B6B7F"}
    if d["historia"]:
        filas = [[TH("Fecha"), TH("Qué"), TH("Detalle"), TH("Km"), TH("Costo")]]
        for h_ in d["historia"]:
            color = COL.get(h_["tipo"], "#B26A00")
            que = Paragraph(f"<font color='{color}' name='{F['I7']}' size='6.8'>{esc(h_['tipo']).upper()}</font><br/>"
                            f"{esc(h_['titulo'])}", st["p"])
            det = Paragraph(esc(h_["detalle"]) + (f"<br/><font color='#5B6B7F' size='7'>{esc(h_['extra'])}</font>" if h_["extra"] else ""), st["p"])
            filas.append([P(dmy(h_["fecha"])[:6] + dmy(h_["fecha"])[8:]), que, det, P(miles(h_["km"]) if h_["km"] else "—"),
                          P(miles(h_["costo"]) if h_["costo"] else "—")])
        el.append(tabla(filas, [17 * mm, 38 * mm, AW - 17 * mm - 38 * mm - 17 * mm - 22 * mm, 17 * mm, 22 * mm], alinear=[3, 4]))
    else:
        el.append(P("No hay nada cargado en el período."))

    # ── Repuestos ──
    if d["repuestos"]:
        filas = [[TH("Repuesto"), TH("Veces"), TH("Cantidad"), TH("Última"), TH("Total")]]
        for r in d["repuestos"][:60]:
            filas.append([P(r["descripcion"]), P(str(r["veces"])), P(f"{r['cantidad']:g}".replace(".", ",")),
                          P(dmy(r["ultima"])), P(miles(r["total"]) if r["total"] else "—")])
        el += [CondPageBreak(40 * mm), Paragraph("Repuestos usados", st["sec"]),
               Paragraph(f"Agrupados por repuesto, del más caro al más barato. Total: {gs(sum(r['total'] for r in d['repuestos']))}.", st["sub"]),
               tabla(filas, [AW - 74 * mm, 14 * mm, 18 * mm, 20 * mm, 22 * mm], alinear=[1, 2, 4])]

    # ── Combustible ──
    if n["cargas"]:
        txt = (f"{miles(n['cargas'])} cargas · {miles(n['litros'])} litros"
               + (f" · {gs(n['costo_combustible'])}" if n["costo_combustible"] else "")
               + (f" · consumo medido {l100:.1f} L cada 100 km".replace(".", ",") if l100 else " · sin consumo medido (faltan cargas con km)")
               + (f" contra {str(ref).replace('.', ',')} de su motor" if ref and l100 else "") + ".")
        el += [CondPageBreak(30 * mm), Paragraph("Combustible", st["sec"]), P(txt)]

    # ── Servicios ──
    if n["servicios"] or n["turismo"]:
        cor = {}
        for s in d["servicios"]:
            from choferes_app import _lindo
            k = f"{_lindo(s['origen']) or '?'} – {_lindo(s['llega']) or '?'}"
            cor[k] = cor.get(k, 0) + 1
        top = sorted(cor.items(), key=lambda x: -x[1])[:6]
        txt = f"{miles(n['servicios'])} servicios de línea" + (f" ({miles(n['km_servicios'])} km)" if n["km_servicios"] else "") + \
              (f" y {miles(n['turismo'])} de turismo" if n["turismo"] else "") + "."
        el += [CondPageBreak(30 * mm), Paragraph("Servicios que hizo", st["sec"]), P(txt)]
        if top:
            el.append(Spacer(1, 4))
            el.append(P("Tramos más hechos: " + " · ".join(f"{k} ({v_})" for k, v_ in top), "chico"))

    # ── Días fuera de servicio ──
    if d["parado"]:
        filas = [[TH("Desde"), TH("Hasta"), TH("Días"), TH("Motivo")]]
        for p in d["parado"]:
            filas.append([P(dmy(p["fecha_desde"])), P(dmy(p.get("fecha_hasta")) if p.get("fecha_hasta") else "sigue"),
                          P(str(p.get("dias", ""))), P(p.get("motivo") or "")])
        el += [CondPageBreak(30 * mm), Paragraph("Fuera de servicio", st["sec"]),
               tabla(filas, [22 * mm, 22 * mm, 14 * mm, AW - 58 * mm], alinear=[2])]

    # ── Cubiertas puestas ahora y documentos ──
    if d["cubiertas_puestas"]:
        filas = [[TH("Posición"), TH("Cubierta"), TH("Marca y medida"), TH("Puesta el")]]
        for c_ in d["cubiertas_puestas"]:
            filas.append([P(c_.get("posicion") or ""), P(c_.get("codigo") or ""),
                          P(" ".join(x for x in (c_.get("marca"), c_.get("medida")) if x)), P(dmy(c_.get("fecha_instalacion")))])
        el += [CondPageBreak(30 * mm), Paragraph("Cubiertas puestas hoy", st["sec"]),
               tabla(filas, [26 * mm, 34 * mm, AW - 86 * mm, 26 * mm])]
    if d["documentos"]:
        COLD = {"Vencido": "#DC2641", "Vence pronto": "#B26A00", "Vigente": "#2F7C46"}
        filas = [[TH("Documento"), TH("Vence"), TH("Estado")]]
        for doc_ in d["documentos"]:
            filas.append([P(" · ".join(x for x in (doc_.get("tipo"), doc_.get("nombre")) if x)), P(dmy(doc_.get("fecha_vencimiento"))),
                          Paragraph(f"<font color='{COLD.get(doc_['estado'], '#5B6B7F')}'><b>{esc(doc_['estado'])}</b></font>", st["p"])])
        el += [CondPageBreak(30 * mm), Paragraph("Documentos", st["sec"]), tabla(filas, [AW - 56 * mm, 26 * mm, 30 * mm])]

    doc.build(el)
    return salida.getvalue()


# ════════════════════════════════════════════════════════════════════════════
# RUTA
# ════════════════════════════════════════════════════════════════════════════

@bp_informe_coche.route("/api/vehiculos/<int:vid>/informe.pdf", methods=["GET"])
def api_informe(vid):
    if session.get("rol") not in ROLES:
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    desde = (request.args.get("desde") or "").strip()[:10] or None
    hasta = (request.args.get("hasta") or "").strip()[:10] or None
    d = datos(vid, desde, hasta)
    if not d:
        return jsonify({"ok": False, "msg": "Ese coche no existe"}), 404
    pdf = generar_pdf(d, session.get("nombre") or session.get("usuario") or "")
    num = d["vehiculo"].get("n_interno") or d["vehiculo"].get("patente") or vid
    return send_file(io.BytesIO(pdf), mimetype="application/pdf", as_attachment=False,
                     download_name=f"Informe coche {num}.pdf")
