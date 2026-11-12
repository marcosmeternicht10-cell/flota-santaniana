"""
corp_ranking.py — Ranking de choferes de corporativos (La Santaniana)

Un puntaje de 0 a 100 por chofer, en el período elegido, armado con cuatro
cosas que dependen de él (no del volumen de trabajo que le tocó):

  · Cumplimiento (35)  de lo que se le asignó en días publicados, cuánto rindió
                       él. «No lo rindió» y «lo hizo otro» restan; hacerlo con
                       otro coche o que el servicio se suspendiera, no.
  · A tiempo (25)      rendiciones cargadas el mismo día o al día siguiente.
  · Prolijidad (20)    rendiciones sin observaciones: dos servicios a la misma
                       hora, kilometraje o pasajeros imposibles, o que la
                       oficina tuvo que corregir.
  · Consumo (20)       cuánto gasta de más o de menos en los coches que maneja,
                       contra lo normal de cada coche (del control de
                       combustible). 0 % o menos = 100 puntos; 30 % o más = 0.

Si una de las cuatro no tiene datos (no hubo asignación publicada, no se pudo
medir el consumo), el puntaje se arma con las otras. Para entrar al ranking
hacen falta al menos MIN_SERVICIOS servicios en el período; los demás salen
aparte.

Rutas:
  GET /api/corp/ranking_choferes?desde&hasta&cliente
  GET /api/corp/ranking_choferes/pdf?desde&hasta&cliente
"""

import re
import time
import unicodedata
from datetime import date, timedelta

from flask import Blueprint, jsonify, request, send_file

from db_compat import get_connection
from hora_local import hoy as _hoy
from nombres import apellido_primero
import corporativos as C

bp_corp_ranking = Blueprint("corp_ranking", __name__)

MIN_SERVICIOS = 5
PESOS = {"cumplimiento": 35, "a_tiempo": 25, "prolijidad": 20, "consumo": 20}
NOMBRE_PARTE = {"cumplimiento": "Cumplimiento", "a_tiempo": "Carga a tiempo", "prolijidad": "Prolijidad",
                "consumo": "Consumo"}
CONSUMO_CERO = 30.0       # % de consumo de más que ya da 0 puntos
KM_MAX = 1500
_memo = {}


def _norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"^n\s*°?\s*\d+\s*", "", s)
    return " ".join(sorted(re.findall(r"[a-z]+", s)))


def _dias(a, b):
    try:
        return (date.fromisoformat(str(b)[:10]) - date.fromisoformat(str(a)[:10])).days
    except ValueError:
        return None


def _leer(desde, hasta, cliente):
    conn = get_connection()
    try:
        filas = [dict(r) for r in conn.execute("""
            SELECT id, chofer_usuario, chofer_nombre, cliente, tramo, fecha_servicio, bus_interno,
                   hora_inicio, km_inicial, km_final, pasajeros, estado, cargado_el, fecha_carga,
                   editado_por
            FROM rendiciones_corp WHERE fecha_servicio >= ? AND fecha_servicio <= ?""",
            (desde, hasta + "~")).fetchall()]
        asientos = {str(r["n_interno"]): int(r["asientos"] or 0) for r in conn.execute(
            "SELECT n_interno, asientos FROM vehiculos WHERE n_interno <> ''").fetchall()}
        dias_pub = [r["fecha"] for r in conn.execute(
            """SELECT fecha FROM corp_asig_dias WHERE fecha >= ? AND fecha <= ?
               AND COALESCE(publicado_el,'') <> '' ORDER BY fecha""", (desde, hasta)).fetchall()]
    finally:
        conn.close()
    for r in filas:
        cli, tr = C._canonizar(r["cliente"], r["tramo"])
        r["cliente_c"] = cli or (r["cliente"] or "").strip().upper()
        r["tramo_c"] = tr or (r["tramo"] or "").strip()
        r["fecha"] = str(r["fecha_servicio"])[:10]
        r["chofer_usuario"] = (r["chofer_usuario"] or "").strip().lower()
    if cliente:
        filas = [r for r in filas if r["cliente_c"] == cliente]
    return filas, asientos, dias_pub


def _asignacion(dias_pub, hoy, cliente):
    """Por chofer: lo asignado en días ya pasados y cómo lo rindió."""
    import corp_asignacion as CA
    out = {}
    for f in dias_pub:
        if f >= hoy:
            continue
        try:
            d = CA.armar_dia(f)
        except Exception as e:
            print(f"[corp_ranking] asignación {f}: {e}")
            continue
        acuses = d.get("acuses") or {}
        vistos = set()
        for c in d.get("clientes") or []:
            if cliente and c["cliente"] != cliente:
                continue
            for s in [x for t in c["tramos"] for x in t["slots"]] + c["variables"]:
                u = (s.get("chofer_usuario") or "").strip().lower()
                ctl = s.get("control")
                if not u or not ctl:
                    continue
                x = out.setdefault(u, {"asignados": 0, "hechos": 0.0, "sin_rendir": 0, "otro_chofer": 0,
                                       "dias": 0, "confirmo": 0, "detalle": []})
                x["asignados"] += 1
                e = ctl["estado"]
                if e in ("ok", "otro_coche", "suspendido"):
                    x["hechos"] += 1
                elif e == "parcial":
                    x["hechos"] += 0.5
                elif e in ("sin_rendir", "otro_chofer"):
                    x[e] += 1
                    if len(x["detalle"]) < 12:
                        x["detalle"].append(f"{f}: {c['cliente']} {s.get('tramo_corto') or CA.tramo_corto(s.get('tramo') or '')}"
                                            f" — {ctl['txt']}")
                if u not in vistos:
                    vistos.add(u)
                    x["dias"] += 1
                    if (acuses.get(u) or {}).get("confirmado_el"):
                        x["confirmo"] += 1
    return out


def _consumo(desde, hasta):
    """Desvío de consumo por chofer (por nombre), del control de combustible."""
    try:
        from database import control_estadistico_combustible
        r = control_estadistico_combustible(desde=desde, hasta=hasta)
    except Exception as e:
        print(f"[corp_ranking] consumo: {e}")
        return {}
    return {_norm(x["chofer"]): x for x in r.get("choferes") or []
            if x.get("desvio_pct") is not None and (x.get("medidos") or 0) >= 2}


def _observaciones(rends, asientos):
    """Ids de rendiciones con algo que no cierra, y el motivo de cada una."""
    obs = {}
    por = {}
    for r in rends:
        if r["estado"] != "suspendido":
            por.setdefault((r["chofer_usuario"], r["fecha"]), []).append(r)
        ki, kf = float(r["km_inicial"] or 0), float(r["km_final"] or 0)
        if ki and kf and (kf < ki or kf - ki > KM_MAX):
            obs.setdefault(r["id"], "kilometraje que no cierra")
        cap = asientos.get(str(r["bus_interno"] or "").strip(), 0)
        if int(r["pasajeros"] or 0) and cap and int(r["pasajeros"]) > cap * 1.6:
            obs.setdefault(r["id"], f"{r['pasajeros']} pasajeros en un coche de {cap} asientos")
        if (r.get("editado_por") or "").strip():
            obs.setdefault(r["id"], "la corrigió la oficina")
    for grupo in por.values():
        if len(grupo) > 1:
            ids, _ = C._pares_que_se_pisan([{**g, "tramo": g["tramo_c"]} for g in grupo])
            for i in ids:
                obs.setdefault(i, "dos servicios a la misma hora")
    return obs


def ranking(desde, hasta, cliente=""):
    hoy = _hoy()
    hasta = min(hasta, hoy)
    clave = (desde, hasta, cliente)
    m = _memo.get(clave)
    if m and time.time() - m[0] < 120:
        return m[1]
    rends, asientos, dias_pub = _leer(desde, hasta, cliente)
    asig = _asignacion(dias_pub, hoy, cliente)
    consumo = _consumo(desde, hasta)
    obs = _observaciones(rends, asientos)

    por = {}
    for r in rends:
        u = r["chofer_usuario"] or _norm(r["chofer_nombre"])
        x = por.setdefault(u, {"usuario": u, "nombre": r["chofer_nombre"] or u, "servicios": 0.0, "rendiciones": 0,
                               "suspendidos": 0, "pasajeros": 0, "km": 0.0, "dias": set(), "clientes": set(),
                               "con_carga": 0, "a_tiempo": 0, "atraso_max": 0, "observadas": [], "ultimo": ""})
        x["rendiciones"] += 1
        x["clientes"].add(r["cliente_c"])
        x["ultimo"] = max(x["ultimo"], r["fecha"])
        if r["estado"] == "suspendido":
            x["suspendidos"] += 1
        else:
            x["servicios"] += 1 if r["estado"] == "completado" or C._es_variable(r["tramo_c"]) else 0.5
            x["pasajeros"] += int(r["pasajeros"] or 0)
            k = float(r["km_final"] or 0) - float(r["km_inicial"] or 0)
            x["km"] += k if 0 < k <= KM_MAX else 0
            x["dias"].add(r["fecha"])
        cargado = (r.get("cargado_el") or r.get("fecha_carga") or "")[:10]
        if cargado:
            d = _dias(r["fecha"], cargado)
            if d is not None:
                x["con_carga"] += 1
                if d <= C.DIAS_ATRAS_PERMITIDOS:
                    x["a_tiempo"] += 1
                x["atraso_max"] = max(x["atraso_max"], d)
        if r["id"] in obs:
            x["observadas"].append({"fecha": r["fecha"], "tramo": f"{r['cliente_c']} · {r['tramo_c']}",
                                    "motivo": obs[r["id"]]})

    out, pocos = [], []
    for u, x in por.items():
        partes = {}
        a = asig.get(u)
        if a and a["asignados"]:
            partes["cumplimiento"] = 100 * a["hechos"] / a["asignados"]
        if x["con_carga"]:
            partes["a_tiempo"] = 100 * x["a_tiempo"] / x["con_carga"]
        if x["rendiciones"]:
            partes["prolijidad"] = max(0.0, 100 - 300 * len(x["observadas"]) / x["rendiciones"])
        cons = consumo.get(_norm(x["nombre"]))
        if cons:
            partes["consumo"] = max(0.0, min(100.0, 100 * (1 - cons["desvio_pct"] / CONSUMO_CERO)))
        peso = sum(PESOS[k] for k in partes)
        puntaje = round(sum(partes[k] * PESOS[k] for k in partes) / peso) if peso else None
        # Lo que más le baja el puntaje, para explicarlo
        flojo = sorted(((k, v) for k, v in partes.items() if v < 80), key=lambda kv: kv[1] - PESOS[kv[0]] / 10)
        motivos = []
        for k, _ in flojo[:2]:
            if k == "cumplimiento":
                motivos.append(f"no rindió {a['sin_rendir']} de {a['asignados']} servicios asignados"
                               + (f" y {a['otro_chofer']} los hizo otro" if a["otro_chofer"] else ""))
            elif k == "a_tiempo":
                motivos.append(f"cargó {x['con_carga'] - x['a_tiempo']} rendiciones con atraso (hasta {x['atraso_max']} días)")
            elif k == "prolijidad":
                motivos.append(f"{len(x['observadas'])} rendiciones con observaciones")
            elif k == "consumo":
                motivos.append(f"consume {cons['desvio_pct']:+.0f} % contra lo normal de sus coches")
        fila = {
            "usuario": u, "nombre": apellido_primero(x["nombre"]),
            "servicios": round(x["servicios"], 1), "rendiciones": x["rendiciones"], "suspendidos": x["suspendidos"],
            "pasajeros": x["pasajeros"], "km": round(x["km"]), "dias": len(x["dias"]),
            "clientes": sorted(x["clientes"]), "ultimo": x["ultimo"],
            "puntaje": puntaje, "partes": {k: round(v) for k, v in partes.items()},
            "asignacion": ({k: v for k, v in a.items() if k != "detalle"} | {"detalle": a["detalle"]}) if a else None,
            "a_tiempo": {"cargadas": x["con_carga"], "a_tiempo": x["a_tiempo"], "atraso_max": x["atraso_max"]},
            "observadas": sorted(x["observadas"], key=lambda o: o["fecha"], reverse=True)[:15],
            "n_observadas": len(x["observadas"]),
            "consumo": ({"desvio_pct": cons["desvio_pct"], "medidos": cons["medidos"], "alertas": cons.get("alertas", 0)}
                        if cons else None),
            "motivos": motivos,
        }
        (out if x["servicios"] >= MIN_SERVICIOS and puntaje is not None else pocos).append(fila)
    out.sort(key=lambda f: (-f["puntaje"], -f["servicios"], f["nombre"]))
    for i, f in enumerate(out, 1):
        f["pos"] = i
    pocos.sort(key=lambda f: (-f["servicios"], f["nombre"]))
    prom = round(sum(f["puntaje"] for f in out) / len(out)) if out else None
    res = {"desde": desde, "hasta": hasta, "cliente": cliente, "hoy": hoy,
           "ranking": out, "pocos_servicios": pocos, "min_servicios": MIN_SERVICIOS,
           "pesos": PESOS, "promedio": prom, "dias_publicados": len([f for f in dias_pub if f < hoy]),
           "clientes_disponibles": sorted({r["cliente_c"] for r in rends}) if not cliente else [],
           "con_consumo": sum(1 for f in out if f["consumo"])}
    _memo[clave] = (time.time(), res)
    if len(_memo) > 20:
        _memo.pop(next(iter(_memo)))
    return res


# ─── Rutas ──────────────────────────────────────────────────────────────────

def _periodo():
    hoy = _hoy()
    desde = request.args.get("desde") or (date.fromisoformat(hoy) - timedelta(days=29)).isoformat()
    hasta = request.args.get("hasta") or hoy
    d0, d1 = date.fromisoformat(desde[:10]), date.fromisoformat(hasta[:10])
    if d1 < d0:
        raise ValueError("La fecha «hasta» es anterior a «desde»")
    if (d1 - d0).days > 370:
        raise ValueError("El período es de más de un año")
    return desde[:10], hasta[:10]


def _puede():
    return C._rol_efectivo() in ("admin", "auditor", "operador_corp")


@bp_corp_ranking.route("/api/corp/ranking_choferes", methods=["GET"])
def api_ranking():
    if not _puede():
        return jsonify({"error": "Sin permiso"}), 403
    try:
        desde, hasta = _periodo()
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(ranking(desde, hasta, (request.args.get("cliente") or "").strip().upper()))


@bp_corp_ranking.route("/api/corp/ranking_choferes/pdf", methods=["GET"])
def api_ranking_pdf():
    if not _puede():
        return jsonify({"error": "Sin permiso"}), 403
    try:
        desde, hasta = _periodo()
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    d = ranking(desde, hasta, (request.args.get("cliente") or "").strip().upper())
    buf = pdf_ranking(d)
    return send_file(buf, mimetype="application/pdf", as_attachment=False,
                     download_name=f"ranking_choferes_corporativos_{desde}_a_{hasta}.pdf")


# ─── PDF ────────────────────────────────────────────────────────────────────

def pdf_ranking(d):
    import io
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.colors import white
    import trafico_pdf
    from rend_comb_pdf import (_Lienzo, _logo, _dmy, _ahora_txt, NAVY, AZUL, ROJO, TINTA, GRIS, GRIS2, LINEA,
                               SUAVE, CEBRA, VERDE, VERDE_F, AMBAR, AMBAR_F, ROJO_F)
    from cajas_pdf import _partir, _pie

    def color(p):
        if p is None:
            return GRIS, SUAVE
        return (VERDE, VERDE_F) if p >= 85 else (AMBAR, AMBAR_F) if p >= 70 else (ROJO, ROJO_F)

    def dibujar(c, total):
        F = trafico_pdf._fuentes()
        W, H = landscape(A4)
        M = 30
        aw = W - 2 * M
        L = _Lienzo(c, H, F)
        pag = [1]
        sub = f"Corporativos · del {_dmy(d['desde'])} al {_dmy(d['hasta'])}" + (f" · {d['cliente']}" if d["cliente"] else "")
        pie = f"Ranking de choferes de corporativos · impreso el {_ahora_txt()}"
        y = L.encabezado(W, M, "Ranking de choferes", sub, "PROMEDIO",
                         f"{d['promedio']} pts" if d["promedio"] is not None else "—", _logo())
        expl = ("Puntaje de 0 a 100: cumplimiento de lo asignado (35), rendiciones cargadas a tiempo (25), "
                "rendiciones sin observaciones (20) y consumo de combustible contra lo normal de cada coche (20). "
                f"Entran al ranking los que hicieron al menos {d['min_servicios']} servicios.")
        for i, ln in enumerate(_partir(L, expl, "I4", 7.6, aw)):
            L.texto(M, y + 4 + 10 * i, ln, "I4", 7.6, GRIS)
        y += 26
        cols = [("#", 26), ("CHOFER", 0), ("PUNTAJE", 62), ("SERVICIOS", 58), ("CUMPLIMIENTO", 78),
                ("A TIEMPO", 62), ("OBSERV.", 52), ("CONSUMO", 60), ("A MEJORAR", 230)]
        cols[1] = ("CHOFER", aw - sum(w for _, w in cols))
        xs = [M]
        for _, w in cols[:-1]:
            xs.append(xs[-1] + w)

        def cab(y):
            L.rect(M, y, aw, 17, fill=NAVY, r=3)
            for (t, w), x in zip(cols, xs):
                L.texto(x + 6, y + 11.5, t, "I7", 6.6, white)
            return y + 17

        y = cab(y)
        for i, f in enumerate(d["ranking"]):
            mot = _partir(L, "; ".join(f["motivos"]) or "—", "I4", 7.3, cols[8][1] - 10)[:3]
            alto = max(20, 8 + 9.5 * len(mot) + 3)
            if y + alto > H - 40:
                _pie(L, W, M, H, pie, pag[0], total)
                c.showPage()
                pag[0] += 1
                y = cab(M)
            if i % 2:
                L.rect(M, y, aw, alto, fill=CEBRA)
            col, fon = color(f["puntaje"])
            L.texto(xs[0] + 6, y + 13.5, str(f["pos"]), "D8", 11, NAVY)
            L.texto(xs[1] + 6, y + 13, L.cortar(f["nombre"], "I6", 8.6, cols[1][1] - 12), "I6", 8.6, TINTA)
            L.rect(xs[2] + 5, y + 4, 44, 13, fill=fon, r=6)
            L.texto(xs[2] + 27, y + 13.5, str(f["puntaje"]), "D8", 10.5, col, "c")
            L.texto(xs[3] + 6, y + 13, f"{f['servicios']:g}", "I5", 8.4, TINTA)
            p = f["partes"]
            for j, k in ((4, "cumplimiento"), (5, "a_tiempo"), (6, None), (7, "consumo")):
                if k is None:
                    txt = str(f["n_observadas"]) if f["n_observadas"] else "—"
                elif k == "consumo":
                    txt = f"{f['consumo']['desvio_pct']:+.0f} %" if f["consumo"] else "—"
                else:
                    txt = f"{p[k]} %" if k in p else "—"
                L.texto(xs[j] + 6, y + 13, txt, "I5", 8.4, TINTA)
            for k, ln in enumerate(mot):
                L.texto(xs[8] + 6, y + 12 + 9.5 * k, ln, "I4", 7.3, GRIS)
            L.linea(M, y + alto, M + aw, y + alto, LINEA, 0.4)
            y += alto
        if not d["ranking"]:
            L.texto(M + aw / 2, y + 26, "No hay choferes con suficientes servicios en este período.", "I5", 10, GRIS, "c")
            y += 40
        if d["pocos_servicios"]:
            y += 14
            if y > H - 70:
                _pie(L, W, M, H, pie, pag[0], total)
                c.showPage()
                pag[0] += 1
                y = M
            txt = (f"Con menos de {d['min_servicios']} servicios (no entran al ranking): "
                   + ", ".join(f"{f['nombre']} ({f['servicios']:g})" for f in d["pocos_servicios"]))
            for k, ln in enumerate(_partir(L, txt, "I4", 7.6, aw)[:6]):
                L.texto(M, y + 10 * k, ln, "I4", 7.6, GRIS)
        _pie(L, W, M, H, pie, pag[0], total)
        return pag[0]

    total = dibujar(canvas.Canvas(io.BytesIO(), pagesize=landscape(A4)), 0)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=landscape(A4))
    c.setTitle(f"Ranking de choferes de corporativos {d['desde']} a {d['hasta']}")
    c.setAuthor("La Santaniana")
    dibujar(c, total)
    c.save()
    buf.seek(0)
    return buf
