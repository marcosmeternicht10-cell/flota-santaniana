"""
ot_afuera.py — Trabajos de la OT hechos fuera del taller, con su factura (La Santaniana)

Cuando un trabajo se hace afuera (una rectificadora, un electricista, una
gomería en ruta), se marca en el trabajo y se anota dónde. Para darlo por
completado hay que subir la foto de la factura: es el aval de que se hizo y
de lo que se pagó. Sin la foto, el trabajo no se puede completar (y por lo
tanto la OT no se puede cerrar).

  ot_items.hecho_afuera   1 si el trabajo se hizo afuera
  ot_items.taller_externo dónde (nombre del taller)
  ot_facturas             la foto de la factura de cada trabajo (una por
                          trabajo; subir otra la reemplaza)

Enganche en app.py:
    from ot_afuera import bp_ot_afuera, init_ot_afuera
    init_ot_afuera()
    app.register_blueprint(bp_ot_afuera)
"""

import re

from flask import Blueprint, request, jsonify, session
from db_compat import get_connection, USE_POSTGRES

from hora_local import ahora_iso

bp_ot_afuera = Blueprint("ot_afuera", __name__)

PK = "SERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"
MAX_FOTO = 3_000_000          # una foto comprimida pesa ~150 KB; esto frena lo que no es una foto


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
            ya = {r["name"] for r in conn.execute(f"PRAGMA table_info({tabla})").fetchall()}
            if col not in ya:
                conn.execute(f"ALTER TABLE {tabla} ADD COLUMN {col} {tipo}")
        conn.commit()
    except Exception:
        _rollback(conn)


def init_ot_afuera():
    conn = get_connection()
    try:
        _agregar_columna(conn, "ot_items", "hecho_afuera", "INTEGER DEFAULT 0")
        _agregar_columna(conn, "ot_items", "taller_externo", "TEXT DEFAULT ''")
        try:
            conn.execute(f"""CREATE TABLE IF NOT EXISTS ot_facturas (
                id {PK},
                item_id INTEGER NOT NULL,
                foto TEXT NOT NULL,
                nro TEXT DEFAULT '',
                subida_el TEXT DEFAULT '',
                subida_por TEXT DEFAULT '')""")
            conn.execute("CREATE INDEX IF NOT EXISTS ix_ot_facturas_item ON ot_facturas (item_id)")
            conn.commit()
        except Exception:
            _rollback(conn)
    finally:
        conn.close()


def _limpio(s, n=80):
    return re.sub(r"\s+", " ", str(s or "")).strip()[:n]


def datos_afuera(item_ids, conn=None):
    """{item_id: {"afuera", "taller", "factura": {id, nro, subida_el, subida_por} | None}}"""
    ids = [int(i) for i in item_ids or [] if str(i).isdigit() or isinstance(i, int)]
    if not ids:
        return {}
    propia = conn is None
    conn = conn or get_connection()
    try:
        m = ",".join("?" * len(ids))
        out = {}
        for r in conn.execute(f"""SELECT id, COALESCE(hecho_afuera,0) AS afuera, COALESCE(taller_externo,'') AS taller
                                  FROM ot_items WHERE id IN ({m})""", ids).fetchall():
            out[r["id"]] = {"afuera": bool(r["afuera"]), "taller": r["taller"], "factura": None}
        for r in conn.execute(f"""SELECT id, item_id, nro, subida_el, subida_por FROM ot_facturas
                                  WHERE item_id IN ({m}) ORDER BY id""", ids).fetchall():
            if r["item_id"] in out:
                out[r["item_id"]]["factura"] = {"id": r["id"], "nro": r["nro"] or "",
                                                "subida_el": r["subida_el"] or "", "subida_por": r["subida_por"] or ""}
        return out
    except Exception:
        _rollback(conn)
        return {}
    finally:
        if propia:
            conn.close()


def marcar_items(items):
    """Le agrega a cada trabajo de la OT si se hizo afuera, dónde y su factura."""
    datos = datos_afuera([it["id"] for it in items or []])
    for it in items or []:
        d = datos.get(it["id"]) or {"afuera": False, "taller": "", "factura": None}
        it["afuera"], it["taller_externo"], it["factura"] = d["afuera"], d["taller"], d["factura"]
    return items


def falta_factura(item_id):
    """El motivo por el que no se puede completar (o None)."""
    d = datos_afuera([item_id]).get(int(item_id))
    if d and d["afuera"] and not d["factura"]:
        donde = f" en {d['taller']}" if d["taller"] else " afuera"
        return f"Este trabajo se hizo{donde}: para completarlo subí la foto de la factura."
    return None


def al_borrar_item(item_id):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM ot_facturas WHERE item_id=?", (int(item_id),))
        conn.commit()
    except Exception:
        _rollback(conn)
    finally:
        conn.close()


def talleres_usados():
    """Los talleres de afuera ya anotados (en trabajos y en entregas de Compras)."""
    conn = get_connection()
    nombres = {}
    try:
        for sql in ("SELECT taller_externo AS t FROM ot_items WHERE COALESCE(taller_externo,'') <> ''",
                    "SELECT taller_entrega AS t FROM ordenes_trabajo WHERE COALESCE(taller_entrega,'') NOT IN ('', 'Taller propio')"):
            try:
                for r in conn.execute(sql).fetchall():
                    t = _limpio(r["t"])
                    if t:
                        k = t.upper()
                        nombres.setdefault(k, [t, 0])[1] += 1
            except Exception:
                _rollback(conn)
    finally:
        conn.close()
    return [v[0] for v in sorted(nombres.values(), key=lambda x: (-x[1], x[0].upper()))][:60]


# ════════════════════════════════════════════════════════════════════════════
# RUTAS
# ════════════════════════════════════════════════════════════════════════════

def _puede():
    return session.get("rol") in ("admin", "taller", "compras")


def _quien():
    return session.get("nombre") or session.get("usuario") or ""


def _no(msg="No tenés permiso para esto", codigo=403):
    return jsonify({"ok": False, "msg": msg, "error": msg}), codigo


def _item(conn, iid):
    r = conn.execute("SELECT id, ot_id, estado, descripcion FROM ot_items WHERE id=?", (iid,)).fetchone()
    return dict(r) if r else None


def _auditar(accion, detalle=""):
    try:
        from database import registrar_auditoria
        registrar_auditoria(usuario=_quien() or "?", rol=session.get("rol") or "", accion=accion,
                            categoria="Órdenes de Trabajo", detalle=detalle[:200])
    except Exception:
        pass


@bp_ot_afuera.route("/api/ot_items/<int:iid>/afuera", methods=["PATCH", "POST"])
def api_afuera(iid):
    if not _puede():
        return _no()
    d = request.get_json(silent=True) or {}
    conn = get_connection()
    try:
        it = _item(conn, iid)
        if not it:
            return _no("Ese trabajo no existe", 404)
        cambios = {}
        if "afuera" in d:
            cambios["hecho_afuera"] = 1 if d.get("afuera") in (1, True, "1", "true") else 0
        if "taller" in d:
            cambios["taller_externo"] = _limpio(d.get("taller"))
        if cambios.get("hecho_afuera") == 0:
            cambios["taller_externo"] = ""
        if cambios:
            conn.execute(f"UPDATE ot_items SET {', '.join(k + '=?' for k in cambios)} WHERE id=?",
                         list(cambios.values()) + [iid])
            conn.commit()
    finally:
        conn.close()
    if "hecho_afuera" in cambios:
        _auditar(f"Marcó un trabajo de la OT #{it['ot_id']} como hecho {'afuera' if cambios['hecho_afuera'] else 'en el taller'}",
                 it["descripcion"] or "")
    return jsonify({"ok": True, **(datos_afuera([iid]).get(iid) or {})})


@bp_ot_afuera.route("/api/ot_items/<int:iid>/factura", methods=["POST"])
def api_factura_subir(iid):
    if not _puede():
        return _no()
    d = request.get_json(silent=True) or {}
    foto = str(d.get("foto") or "")
    if not foto.startswith("data:image/") or len(foto) > MAX_FOTO:
        return _no("Falta la foto de la factura (o no es una imagen)", 400)
    conn = get_connection()
    try:
        it = _item(conn, iid)
        if not it:
            return _no("Ese trabajo no existe", 404)
        conn.execute("DELETE FROM ot_facturas WHERE item_id=?", (iid,))
        conn.execute("""INSERT INTO ot_facturas (item_id, foto, nro, subida_el, subida_por)
                        VALUES (?,?,?,?,?)""", (iid, foto, _limpio(d.get("nro"), 40), ahora_iso(), _quien()[:80]))
        # Subir la factura confirma que se hizo afuera
        conn.execute("UPDATE ot_items SET hecho_afuera=1 WHERE id=?", (iid,))
        if "taller" in d and _limpio(d.get("taller")):
            conn.execute("UPDATE ot_items SET taller_externo=? WHERE id=?", (_limpio(d.get("taller")), iid))
        conn.commit()
    finally:
        conn.close()
    _auditar(f"Subió la factura de un trabajo hecho afuera (OT #{it['ot_id']})", it["descripcion"] or "")
    return jsonify({"ok": True, **(datos_afuera([iid]).get(iid) or {})})


@bp_ot_afuera.route("/api/ot_items/<int:iid>/factura", methods=["GET"])
def api_factura_ver(iid):
    if not session.get("rol") or session.get("rol") in ("chofer", "chofer_corp"):
        return _no()
    conn = get_connection()
    try:
        r = conn.execute("SELECT foto, nro, subida_el, subida_por FROM ot_facturas WHERE item_id=? ORDER BY id DESC",
                         (iid,)).fetchone()
    finally:
        conn.close()
    if not r:
        return _no("Este trabajo no tiene factura", 404)
    return jsonify({"ok": True, **dict(r)})


@bp_ot_afuera.route("/api/ot_items/<int:iid>/factura", methods=["DELETE"])
def api_factura_quitar(iid):
    if not _puede():
        return _no()
    conn = get_connection()
    try:
        it = _item(conn, iid)
        if not it:
            return _no("Ese trabajo no existe", 404)
        if it["estado"] == "completado":
            return _no("El trabajo ya está completado con esta factura: para cambiarla subí otra.", 400)
        conn.execute("DELETE FROM ot_facturas WHERE item_id=?", (iid,))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True, **(datos_afuera([iid]).get(iid) or {})})


@bp_ot_afuera.route("/api/ot_talleres_externos", methods=["GET"])
def api_talleres_externos():
    if not _puede():
        return _no()
    return jsonify({"ok": True, "talleres": talleres_usados()})
