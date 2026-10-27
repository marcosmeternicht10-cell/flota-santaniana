"""
ot_pendientes.py — Por qué quedó pendiente un trabajo de la OT (La Santaniana)

Un coche tiene una sola OT abierta que junta los trabajos de varios días. Lo
que quedó sin hacer de días anteriores se resalta, y el taller anota por qué
quedó con sus propias palabras ("falta repuesto", "esperando fondos"…). Los
motivos que ya se usaron se ofrecen al escribir, así se escriben igual y se
pueden contar: en la lista de OTs sale cuántos trabajos quedaron por cada
motivo.

  init_ot_pendientes()            las columnas en ot_items
  marcar_atrasados(lista)         a cada fila de la lista de OTs: cuántos
                                  trabajos de días anteriores siguen sin hacer,
                                  desde cuándo y por qué
  PATCH /api/ot_items/<id>/motivo {"motivo": "Falta repuesto", "detalle": "..."}  ("" lo quita)
                                  El motivo es corto (agrupa); el detalle es la
                                  explicación larga, en varios renglones.
  GET   /api/ot_motivos           los motivos ya usados, el más usado primero

Enganche en app.py:
    from ot_pendientes import bp_ot_pend, init_ot_pendientes
    init_ot_pendientes()
    app.register_blueprint(bp_ot_pend)
"""

import re
import unicodedata

from flask import Blueprint, request, jsonify, session
from db_compat import get_connection, USE_POSTGRES

from hora_local import hoy, ahora_iso

bp_ot_pend = Blueprint("ot_pendientes", __name__)

MAX_MOTIVO = 80          # el motivo corto (agrupa en los filtros)
MAX_DETALLE = 2000       # la explicación: lo que pasó, con todas las palabras que hagan falta
SIN_MOTIVO = "Sin motivo"

# La fecha del trabajo: el día en que entró a la OT (o la apertura, si es viejo)
FECHA_ITEM = "COALESCE(NULLIF(SUBSTR(COALESCE(i.fecha,''),1,10),''), SUBSTR(o.fecha_apertura,1,10))"


def _rollback(conn):
    try:
        conn.rollback()
    except Exception:
        pass


def _agregar_columna(conn, tabla, col, tipo):
    try:
        if USE_POSTGRES:
            conn.execute(f"ALTER TABLE {tabla} ADD COLUMN IF NOT EXISTS {col} {tipo}")
        else:
            existentes = {r["name"] for r in conn.execute(f"PRAGMA table_info({tabla})").fetchall()}
            if col not in existentes:
                conn.execute(f"ALTER TABLE {tabla} ADD COLUMN {col} {tipo}")
        conn.commit()
    except Exception:
        _rollback(conn)


def init_ot_pendientes():
    conn = get_connection()
    try:
        for col in ("motivo_pendiente", "motivo_el", "motivo_por", "motivo_detalle"):
            _agregar_columna(conn, "ot_items", col, "TEXT DEFAULT ''")
    finally:
        conn.close()


def _clave(s):
    s = unicodedata.normalize("NFD", str(s or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9ñ]+", " ", s).strip()


def _limpio(s):
    s = re.sub(r"\s+", " ", str(s or "")).strip()[:MAX_MOTIVO]
    return s[:1].upper() + s[1:] if s else ""


def _formas(conn):
    """Cómo se escribe cada motivo: la forma más usada de cada uno."""
    cuenta = {}
    for r in conn.execute("""SELECT motivo_pendiente AS m, COUNT(*) AS n FROM ot_items
                             WHERE COALESCE(motivo_pendiente,'') <> '' GROUP BY motivo_pendiente""").fetchall():
        k = _clave(r["m"])
        if k:
            cuenta.setdefault(k, {})[r["m"]] = int(r["n"])
    return {k: max(v.items(), key=lambda x: x[1])[0] for k, v in cuenta.items()}


def motivos_usados(conn=None):
    """Los motivos que ya se usaron, el más usado primero, con cuántos
    trabajos lo tienen ahora sin hacer."""
    propia = conn is None
    conn = conn or get_connection()
    try:
        formas = _formas(conn)
        usos, abiertos = {}, {}
        for r in conn.execute("""SELECT motivo_pendiente AS m, COALESCE(estado,'') AS e FROM ot_items
                                 WHERE COALESCE(motivo_pendiente,'') <> ''""").fetchall():
            k = _clave(r["m"])
            if not k:
                continue
            usos[k] = usos.get(k, 0) + 1
            if r["e"] != "completado":
                abiertos[k] = abiertos.get(k, 0) + 1
        orden = sorted(usos, key=lambda k: (-abiertos.get(k, 0), -usos[k], formas[k]))
        return [{"motivo": formas[k], "clave": k, "usos": usos[k], "pendientes": abiertos.get(k, 0)}
                for k in orden][:40]
    finally:
        if propia:
            conn.close()


def _detalle_limpio(s):
    """La explicación respeta los renglones; se sacan los espacios de más."""
    lineas = [re.sub(r"[ \t]+", " ", l).strip() for l in str(s or "").replace("\r", "").split("\n")]
    txt = re.sub(r"\n{3,}", "\n\n", "\n".join(lineas)).strip()
    return txt[:MAX_DETALLE]


def poner_motivo(item_id, motivo, quien="", detalle=None):
    """Anota por qué quedó pendiente el trabajo. Si ese motivo ya se escribió
    antes (con otras mayúsculas o sin tilde) se usa la forma de siempre. El
    detalle es la explicación larga (si no viene, no se toca)."""
    motivo = _limpio(motivo)
    conn = get_connection()
    try:
        it = conn.execute("SELECT id FROM ot_items WHERE id=?", (item_id,)).fetchone()
        if not it:
            return None, "Ese trabajo no existe"
        if motivo:
            motivo = _formas(conn).get(_clave(motivo), motivo)
        conn.execute("UPDATE ot_items SET motivo_pendiente=?, motivo_el=?, motivo_por=? WHERE id=?",
                     (motivo, ahora_iso() if motivo else "", (quien or "")[:80] if motivo else "", item_id))
        if detalle is not None or not motivo:
            # Sin motivo no queda explicación suelta
            conn.execute("UPDATE ot_items SET motivo_detalle=? WHERE id=?",
                         (_detalle_limpio(detalle) if motivo else "", item_id))
        conn.commit()
        return motivo, None
    finally:
        conn.close()


def atrasados(ot_ids=None, conn=None):
    """Por OT, los trabajos de días anteriores que siguen sin hacer:
    {ot_id: {"n", "sin_motivo", "desde", "motivos": {clave: n}}}"""
    propia = conn is None
    conn = conn or get_connection()
    try:
        sql = f"""SELECT i.ot_id, COALESCE(i.motivo_pendiente,'') AS m, {FECHA_ITEM} AS f
                  FROM ot_items i JOIN ordenes_trabajo o ON o.id = i.ot_id
                  WHERE COALESCE(o.estado,'') <> 'cerrada' AND COALESCE(i.estado,'') <> 'completado'
                    AND {FECHA_ITEM} < ?"""
        params = [hoy()]
        if ot_ids:
            ot_ids = [int(x) for x in ot_ids]
            sql += f" AND i.ot_id IN ({','.join('?' * len(ot_ids))})"
            params += ot_ids
        salida = {}
        for r in conn.execute(sql, params).fetchall():
            d = salida.setdefault(r["ot_id"], {"n": 0, "sin_motivo": 0, "desde": "", "motivos": {}})
            d["n"] += 1
            if r["f"] and (not d["desde"] or r["f"] < d["desde"]):
                d["desde"] = r["f"]
            k = _clave(r["m"])
            if k:
                d["motivos"][k] = d["motivos"].get(k, 0) + 1
            else:
                d["sin_motivo"] += 1
        return salida
    finally:
        if propia:
            conn.close()


def marcar_atrasados(lista):
    """Suma a cada fila de la lista de OTs (ya agrupada: una fila puede tener
    varios coches) lo que quedó pendiente de días anteriores."""
    conn = get_connection()
    try:
        por_ot = atrasados(conn=conn)
        formas = _formas(conn) if por_ot else {}
    finally:
        conn.close()
    for o in lista:
        ids = [c["id"] for c in o.get("coches") or []] or [o["id"]]
        n = sin = 0
        desde = ""
        mot = {}
        for i in ids:
            d = por_ot.get(i)
            if not d:
                continue
            n += d["n"]
            sin += d["sin_motivo"]
            if d["desde"] and (not desde or d["desde"] < desde):
                desde = d["desde"]
            for k, c in d["motivos"].items():
                mot[k] = mot.get(k, 0) + c
        o["atrasados"] = n
        o["atrasados_sin_motivo"] = sin
        o["atrasados_desde"] = desde
        o["atrasados_motivos"] = [{"clave": k, "motivo": formas.get(k, k), "n": c}
                                  for k, c in sorted(mot.items(), key=lambda x: (-x[1], x[0]))]
    return lista


# ════════════════════════════════════════════════════════════════════════════
# RUTAS
# ════════════════════════════════════════════════════════════════════════════

def _puede():
    return session.get("rol") in ("admin", "taller", "compras")


def _no(msg="No tenés permiso para esto", codigo=403):
    return jsonify({"ok": False, "msg": msg, "error": msg}), codigo


@bp_ot_pend.route("/api/ot_items/<int:item_id>/motivo", methods=["PATCH", "POST"])
def api_motivo(item_id):
    if not _puede():
        return _no()
    d = request.get_json(silent=True) or {}
    if d.get("detalle") and not str(d.get("motivo") or "").strip():
        return _no("Poné también el motivo corto (para agruparlo), además de la explicación", 400)
    motivo, err = poner_motivo(item_id, d.get("motivo"), session.get("nombre") or session.get("usuario") or "",
                               d.get("detalle") if "detalle" in d else None)
    if err:
        return _no(err, 404)
    detalle = ""
    if motivo:
        conn = get_connection()
        try:
            r = conn.execute("SELECT motivo_detalle FROM ot_items WHERE id=?", (item_id,)).fetchone()
            detalle = (r["motivo_detalle"] if r else "") or ""
        finally:
            conn.close()
    return jsonify({"ok": True, "motivo": motivo, "detalle": detalle, "motivos": motivos_usados()})


@bp_ot_pend.route("/api/ot_motivos", methods=["GET"])
def api_motivos():
    if not session.get("rol"):
        return _no("Iniciá sesión", 401)
    return jsonify({"ok": True, "motivos": motivos_usados(), "hoy": hoy()})
