"""
compras_motivo.py — Por qué no se trae todavía el repuesto (Compras)

Una OT presupuestada (o en espera) puede quedar días sin que el repuesto
llegue: falta la plata, el proveedor no tiene, se espera otra cotización…
Compras lo anota acá con sus palabras: un motivo corto (para agrupar) y la
explicación larga. El taller lo ve en la OT, así no tiene que llamar a
preguntar.

  init_compras_motivo()                 las columnas en ordenes_trabajo
  GET  /api/compras/<ot_id>/motivo      el motivo de la OT (cualquiera que vea la OT)
  POST /api/compras/<ot_id>/motivo      {"motivo": "...", "detalle": "..."}  ("" lo quita)
  GET  /api/compras/motivos             los motivos ya usados + los de siempre

En una OT de varios coches el motivo va en la OT principal (la del grupo).
"""

import re

from flask import Blueprint, request, jsonify, session

from db_compat import get_connection, USE_POSTGRES
from hora_local import ahora_iso

bp_compras_motivo = Blueprint("compras_motivo", __name__)

MAX_MOTIVO = 80
MAX_DETALLE = 2000
# Los de siempre: se ofrecen aunque nadie los haya usado todavía
MOTIVOS_BASE = [
    "Esperando fondos de Tesorería",
    "Sin stock en el proveedor",
    "Esperando cotización",
    "Repuesto pedido, todavía no llegó",
    "Esperando autorización",
    "Buscando otro proveedor",
]
COLUMNAS = [
    ("compras_motivo", "TEXT DEFAULT ''"),
    ("compras_motivo_detalle", "TEXT DEFAULT ''"),
    ("compras_motivo_el", "TEXT DEFAULT ''"),
    ("compras_motivo_por", "TEXT DEFAULT ''"),
]


def _rollback(conn):
    try:
        conn.rollback()
    except Exception:
        pass


def init_compras_motivo():
    conn = get_connection()
    try:
        if USE_POSTGRES:
            for col, tipo in COLUMNAS:
                conn.execute(f"ALTER TABLE ordenes_trabajo ADD COLUMN IF NOT EXISTS {col} {tipo}")
        else:
            ya = {r["name"] for r in conn.execute("PRAGMA table_info(ordenes_trabajo)").fetchall()}
            for col, tipo in COLUMNAS:
                if col not in ya:
                    conn.execute(f"ALTER TABLE ordenes_trabajo ADD COLUMN {col} {tipo}")
        conn.commit()
    except Exception as e:
        _rollback(conn)
        print(f"[compras_motivo] no se pudieron agregar las columnas: {e}")
    finally:
        conn.close()


def _motivo_limpio(v):
    return re.sub(r"\s+", " ", str(v or "")).strip()[:MAX_MOTIVO]


def _detalle_limpio(v):
    s = str(v or "").replace("\r", "")
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()[:MAX_DETALLE]


def _cabeza(conn, ot_id):
    try:
        import ot_materiales as om
        ids = om.ids_grupo(conn, ot_id)
        return ids[0] if ids else None
    except Exception:
        _rollback(conn)
        r = conn.execute("SELECT id FROM ordenes_trabajo WHERE id=?", (ot_id,)).fetchone()
        return r["id"] if r else None


def _fila(r):
    return {
        "ot_id": r["id"],
        "estado_compras": r["estado_compras"] or "",
        "motivo": r["compras_motivo"] or "",
        "detalle": r["compras_motivo_detalle"] or "",
        "el": r["compras_motivo_el"] or "",
        "por": r["compras_motivo_por"] or "",
    }


def motivo_de(ot_id):
    conn = get_connection()
    try:
        h = _cabeza(conn, ot_id)
        if h is None:
            return None
        r = conn.execute("""SELECT id, estado_compras, compras_motivo, compras_motivo_detalle,
                                   compras_motivo_el, compras_motivo_por
                            FROM ordenes_trabajo WHERE id=?""", (h,)).fetchone()
        return _fila(r) if r else None
    finally:
        conn.close()


def poner_motivo(ot_id, motivo, detalle, quien):
    """Guarda (o quita, con motivo vacío) por qué no se trae el repuesto."""
    motivo, detalle = _motivo_limpio(motivo), _detalle_limpio(detalle)
    if detalle and not motivo:
        return {"ok": False, "msg": "Poné también el motivo corto, así se puede agrupar"}
    conn = get_connection()
    try:
        h = _cabeza(conn, ot_id)
        if h is None:
            return {"ok": False, "msg": "No existe esa OT"}
        r = conn.execute("SELECT estado_compras FROM ordenes_trabajo WHERE id=?", (h,)).fetchone()
        if not r or not (r["estado_compras"] or ""):
            return {"ok": False, "msg": "Esa OT no está en Compras"}
        el = ahora_iso() if motivo else ""
        conn.execute("""UPDATE ordenes_trabajo SET compras_motivo=?, compras_motivo_detalle=?,
                        compras_motivo_el=?, compras_motivo_por=? WHERE id=?""",
                     (motivo, detalle if motivo else "", el, quien if motivo else "", h))
        conn.commit()
    except Exception as e:
        _rollback(conn)
        return {"ok": False, "msg": f"No se pudo guardar: {e}"}
    finally:
        conn.close()
    res = motivo_de(h) or {}
    res.update({"ok": True, "motivos": motivos_usados()})
    return res


def motivos_usados():
    """Los ya usados (el más usado primero) y después los de siempre."""
    conn = get_connection()
    try:
        filas = conn.execute("""SELECT compras_motivo AS m, COUNT(*) AS n,
                                       SUM(CASE WHEN estado_compras IN ('en_espera','presupuestado') THEN 1 ELSE 0 END) AS ahora
                                FROM ordenes_trabajo
                                WHERE COALESCE(compras_motivo,'') != ''
                                GROUP BY compras_motivo ORDER BY COUNT(*) DESC""").fetchall()
    except Exception:
        _rollback(conn)
        filas = []
    finally:
        conn.close()
    lista, vistos = [], set()
    for f in filas:
        k = f["m"].strip().lower()
        if k in vistos:
            continue
        vistos.add(k)
        lista.append({"motivo": f["m"], "usos": f["n"] or 0, "ahora": f["ahora"] or 0})
    for m in MOTIVOS_BASE:
        if m.lower() not in vistos:
            lista.append({"motivo": m, "usos": 0, "ahora": 0})
    return lista


def _puede_escribir():
    rol = session.get("rol")
    if rol in ("admin", "compras"):
        return True
    if rol == "taller":
        try:
            from database import secciones_de_usuario
            secs = secciones_de_usuario(session.get("usuario_id"))
            return not secs or "compras" in secs
        except Exception:
            return False
    return False


@bp_compras_motivo.route("/api/compras/<int:ot_id>/motivo", methods=["GET"])
def api_motivo_ver(ot_id):
    if "usuario_id" not in session:
        return jsonify({"error": "No autenticado", "login": True}), 401
    m = motivo_de(ot_id)
    if m is None:
        return jsonify({"ok": False, "msg": "No existe esa OT"}), 404
    m.update({"ok": True, "puede": _puede_escribir()})
    return jsonify(m)


@bp_compras_motivo.route("/api/compras/<int:ot_id>/motivo", methods=["POST", "PATCH"])
def api_motivo_poner(ot_id):
    if "usuario_id" not in session:
        return jsonify({"error": "No autenticado", "login": True}), 401
    if not _puede_escribir():
        return jsonify({"ok": False, "msg": "Solo Compras puede anotar el motivo"}), 403
    d = request.get_json(silent=True) or {}
    quien = session.get("nombre") or session.get("usuario") or ""
    r = poner_motivo(ot_id, d.get("motivo"), d.get("detalle"), quien)
    if r.get("ok"):
        try:
            from database import registrar_auditoria
            registrar_auditoria(usuario=quien or "?", rol=session.get("rol") or "",
                                accion=("Anotó por qué no se trae el repuesto" if r.get("motivo")
                                        else "Quitó el motivo de por qué no se trae el repuesto"),
                                categoria="compras", detalle=f"OT #{r.get('ot_id')}: {r.get('motivo') or ''}",
                                referencia=f"compras:{r.get('ot_id')}")
        except Exception:
            pass
    return jsonify(r), (200 if r.get("ok") else 400)


@bp_compras_motivo.route("/api/compras/motivos", methods=["GET"])
def api_motivos():
    if "usuario_id" not in session:
        return jsonify({"error": "No autenticado", "login": True}), 401
    return jsonify({"ok": True, "motivos": motivos_usados()})
