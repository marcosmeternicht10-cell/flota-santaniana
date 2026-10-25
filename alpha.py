"""
alpha.py — Lo que Alpha (la venta de pasajes) toma del tráfico (La Santaniana)

Alpha no inventa los servicios: salen del tráfico de cada día, nacional e
internacional. De ahí saca, para cada corredor (Concepción, Pedro Juan,
Buenos Aires...), las salidas de ida y de regreso con su hora, el tramo tal
como lo escriben, el coche asignado y la tripulación.

  - Si el tráfico de ese día ya está armado (publicado o no), se usa tal cual.
  - Si todavía no se armó (se venden pasajes para mañana o pasado), se toman
    los horarios del último tráfico del mismo día de la semana. El coche queda
    "a confirmar" y se muestra el que suele hacer esa salida, para saber qué
    plano de asientos vender.

Por ahora es solo lectura y solo para administración: Alpha es una maqueta y
las ventas de prueba quedan en el navegador.

Enganche en app.py:
    from alpha import bp_alpha
    app.register_blueprint(bp_alpha)
"""

import re
from datetime import date, timedelta

from flask import Blueprint, jsonify, session

from db_compat import get_connection
import trafico as tr

bp_alpha = Blueprint("alpha", __name__)

# Cómo se muestra cada lugar en la pantalla y en el boleto
NOMBRES = {
    "ASU": "Asunción", "COP": "Concepción", "LOT": "Loreto", "PJC": "Pedro Juan Caballero",
    "CDE": "Ciudad del Este", "ATQ": "Antequera", "SAN PEDRO": "San Pedro", "TACUATI": "Tacuatí",
    "SAN VICENTE": "San Vicente", "VILLARRICA": "Villarrica", "CARAPEGUA": "Carapeguá",
    "ROQUE GONZALEZ": "Roque González", "RETIRO": "Retiro", "LA PLATA": "La Plata",
    "LA NORIA": "La Noria", "SAN JUSTO": "San Justo", "LINIERS": "Liniers",
    "BUENOS AIRES": "Buenos Aires", "CLORINDA": "Clorinda",
}
SEMANAS_ATRAS = 5          # hasta cuántas semanas atrás se busca un tráfico de referencia
DIAS_HABITUAL = 21         # para el coche que suele hacer cada salida


def nombre_lugar(sigla):
    s = str(sigla or "").strip()
    if not s:
        return ""
    return NOMBRES.get(s.upper()) or s.title()


def _hora_ok(h):
    return bool(re.fullmatch(r"\d{2}:\d{2}", str(h or "")))


def _coche(txt):
    """El número interno si es un número; 'A CONF' y vacíos no son coche."""
    t = str(txt or "").strip()
    return t if re.fullmatch(r"\d{2,6}", t) else ""


def _salidas_de(conn, dia_id):
    return [dict(r) for r in conn.execute("""
        SELECT s.id, s.lado, s.hora, s.destino, s.coche, s.trip1, s.trip2, s.nota,
               b.nombre AS corredor, b.orden
        FROM trafico_salidas s JOIN trafico_bloques b ON b.id = s.bloque_id
        WHERE s.dia_id = ? ORDER BY b.orden, b.id, s.lado, s.hora, s.id""", (dia_id,)).fetchall()]


def _con_salidas(conn, dia_id):
    r = conn.execute("SELECT COUNT(*) AS n FROM trafico_salidas WHERE dia_id=?", (dia_id,)).fetchone()
    return int(r["n"] or 0) > 0


def _referencia(conn, fecha, tipo):
    """Un tráfico ya armado para tomar los horarios: el último del mismo día
    de la semana; si no hay, el último que haya antes de esa fecha."""
    f = date.fromisoformat(fecha)
    for k in range(1, SEMANAS_ATRAS + 1):
        d = tr._dia_por_fecha(conn, (f - timedelta(days=7 * k)).isoformat(), tipo)
        if d and _con_salidas(conn, d["id"]):
            return d
    for r in conn.execute("""SELECT * FROM trafico_dias WHERE fecha < ? AND COALESCE(tipo,'nacional') = ?
                             ORDER BY fecha DESC LIMIT 15""", (fecha, tipo)).fetchall():
        if _con_salidas(conn, r["id"]):
            return dict(r)
    return None


def _habituales(conn, fecha, tipo):
    """(corredor, lado, hora) → el último coche que hizo esa salida."""
    desde = (date.fromisoformat(fecha) - timedelta(days=DIAS_HABITUAL)).isoformat()
    out = {}
    for r in conn.execute("""
        SELECT d.fecha, b.nombre AS corredor, s.lado, s.hora, s.coche
        FROM trafico_salidas s JOIN trafico_dias d ON d.id = s.dia_id
        JOIN trafico_bloques b ON b.id = s.bloque_id
        WHERE COALESCE(d.tipo,'nacional') = ? AND d.fecha >= ? AND d.fecha <= ?
        ORDER BY d.fecha""", (tipo, desde, fecha)).fetchall():
        c = _coche(r["coche"])
        if c:
            out[(tr._sin_tildes(tr.limpiar(r["corredor"])), r["lado"], r["hora"])] = c
    return out


def _tripulacion(s):
    """Los tripulantes escritos. 'CHOFER 21027' es cómo marcan que va el
    chofer fijo de ese coche: se muestra tal cual."""
    return [t.strip() for t in (s.get("trip1"), s.get("trip2")) if t and t.strip()]


def dia_para_alpha(fecha):
    conn = get_connection()
    try:
        flota = tr._flota(conn)

        def modelo(c):
            v = flota.get(c)
            return " ".join(x for x in ((v or {}).get("marca"), (v or {}).get("modelo")) if x).strip() if v else ""

        corredores = []
        for tipo in ("nacional", "internacional"):
            d = tr._dia_por_fecha(conn, fecha, tipo)
            fuente = {"tipo": tipo}
            if d and _con_salidas(conn, d["id"]):
                filas = _salidas_de(conn, d["id"])
                version = int(d.get("version") or 0)
                fuente.update(estado=("publicado" if version and not int(d.get("modificado") or 0)
                                      else "cambios" if version else "borrador"),
                              version=version, publicado_el=d.get("publicado_el") or "")
                es_ref = False
            else:
                ref = _referencia(conn, fecha, tipo)
                if not ref:
                    continue
                filas = _salidas_de(conn, ref["id"])
                fuente.update(estado="referencia", fecha_ref=ref["fecha"])
                es_ref = True
            hab = _habituales(conn, fecha, tipo)

            por = {}
            for s in filas:
                if not _hora_ok(s["hora"]) or s["lado"] not in tr.LADOS:
                    continue
                corr = (s["corredor"] or "").strip()
                clave_corr = tr._sin_tildes(tr.limpiar(corr))
                c = por.get(clave_corr)
                if c is None:
                    lugar = (tr._lugar_ar(corr) or "BUENOS AIRES") if tipo == "internacional" else tr.lugar_del_corredor(corr)
                    c = por[clave_corr] = {
                        "clave": f"{tipo}|{clave_corr}", "tipo": tipo, "corredor": corr,
                        "lugar": lugar, "titulo": nombre_lugar(lugar) if lugar and lugar != "ASU" else corr.title(),
                        "fuente": fuente, "ida": [], "regreso": [],
                    }
                o, dst = tr.tramo(s["destino"], s["lado"], corr, tipo)
                base, extras = tr.partes_destino(s["destino"])
                coche = "" if es_ref else _coche(s["coche"])
                habitual = "" if coche else hab.get((clave_corr, s["lado"], s["hora"]), "")
                c[s["lado"]].append({
                    "id": None if es_ref else s["id"],
                    "clave": f"{tipo}|{clave_corr}|{s['lado']}|{s['hora']}|{tr._sin_tildes(tr.limpiar(s['destino']))}",
                    "hora": s["hora"], "destino": s["destino"] or "", "tramo": base, "extras": extras,
                    "origen": o, "llega": dst, "origen_nombre": nombre_lugar(o), "llega_nombre": nombre_lugar(dst),
                    "coche": coche, "modelo": modelo(coche),
                    "a_confirmar": not coche and str(s.get("coche") or "").strip().upper().startswith("A CONF"),
                    "habitual": habitual, "habitual_modelo": modelo(habitual),
                    "tripulacion": [] if es_ref else _tripulacion(s),
                    "nota": "" if es_ref else (s.get("nota") or ""),
                })
            for c in por.values():
                for lado in tr.LADOS:
                    c[lado].sort(key=lambda x: x["hora"])
                corredores.append(c)
        return {"fecha": fecha, "corredores": corredores}
    finally:
        conn.close()


@bp_alpha.route("/api/alpha/dia/<fecha>", methods=["GET"])
def api_alpha_dia(fecha):
    if session.get("rol") != "admin":
        return jsonify({"ok": False, "error": "Alpha la ve solo administración"}), 403
    try:
        date.fromisoformat(fecha)
    except ValueError:
        return jsonify({"ok": False, "error": "Fecha inválida"}), 400
    return jsonify(dia_para_alpha(fecha))
