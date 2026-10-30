"""
ot_inventario.py — La OT conectada con el depósito (La Santaniana)

Desde la OT se saca del inventario lo que se usa en el coche: se busca el
repuesto, se pone cuánto, baja el stock y queda anotado "OT #45 · coche 112".
El costo de lo sacado se ve en la OT. Si se sacó de más o se equivocaron, se
devuelve desde la misma OT y el stock vuelve a sumar.

Productos por envase (aceite, refrigerante, grasa…): cada envase es un producto
('Aceite 15W40 bidón 20 L', 'Aceite 15W40 tambor 200 L'), con su contenido
(20 L, 200 L). El stock se cuenta en envases y el sistema muestra los litros.
Desde la OT se puede sacar en litros: 30 L de un tambor de 200 L dejan 0,85
tambor (170 L).

Enganche en app.py (después del inventario):
    from ot_inventario import bp_ot_inv, init_ot_inventario
    init_ot_inventario()
    app.register_blueprint(bp_ot_inv)
"""

from flask import Blueprint, request, jsonify, session
from db_compat import get_connection, USE_POSTGRES

import repuestos_db as rdb

bp_ot_inv = Blueprint("ot_inventario", __name__)

UNIDADES_CONTENIDO = ("litros", "kg", "metros")


def init_ot_inventario():
    conn = get_connection()
    for tabla, cols in (
        ("repuestos", [("contenido", "REAL DEFAULT 0"),          # cuánto trae cada envase (20 → 20 L)
                       ("contenido_unidad", "TEXT DEFAULT ''"),  # litros | kg | metros
                       ("envase", "TEXT DEFAULT ''")]),          # bidón, tambor, balde, botella…
        ("repuestos_movimientos", [("ot_id", "INTEGER"), ("ot_item_id", "INTEGER")]),
    ):
        for col, tipo in cols:
            try:
                if USE_POSTGRES:
                    conn.execute(f"ALTER TABLE {tabla} ADD COLUMN IF NOT EXISTS {col} {tipo}")
                else:
                    existentes = {r["name"] for r in conn.execute(f"PRAGMA table_info({tabla})").fetchall()}
                    if col not in existentes:
                        conn.execute(f"ALTER TABLE {tabla} ADD COLUMN {col} {tipo}")
                conn.commit()
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS ix_repmov_ot ON repuestos_movimientos (ot_id)")
        conn.commit()
    except Exception:
        pass
    conn.close()


def _num(v):
    if v is None or v == "":
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(" ", "")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def limpiar_contenido(d):
    """Los campos de envase que vienen del formulario del inventario."""
    out = {}
    if "contenido" in d:
        out["contenido"] = max(0.0, round(_num(d.get("contenido")), 3))
    if "contenido_unidad" in d:
        u = str(d.get("contenido_unidad") or "").strip().lower()
        out["contenido_unidad"] = u if u in UNIDADES_CONTENIDO else ""
    if "envase" in d:
        out["envase"] = " ".join(str(d.get("envase") or "").split())[:30].lower()
    if out.get("contenido") and not out.get("contenido_unidad", "x"):
        out["contenido_unidad"] = "litros"
    return out


def guardar_contenido(rid, d):
    campos = limpiar_contenido(d)
    if not campos:
        return
    conn = get_connection()
    try:
        conn.execute(f"UPDATE repuestos SET {', '.join(k + '=?' for k in campos)} WHERE id=?",
                     list(campos.values()) + [rid])
        conn.commit()
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════════════
# LO QUE SE SACÓ PARA UNA OT
# ════════════════════════════════════════════════════════════════════════════

def _ot(conn, ot_id):
    r = conn.execute("""SELECT o.id, o.estado, v.patente, v.n_interno
                        FROM ordenes_trabajo o LEFT JOIN vehiculos v ON v.id = o.vehiculo_id
                        WHERE o.id=?""", (ot_id,)).fetchone()
    return dict(r) if r else None


def usados_en_ot(ot_id):
    conn = get_connection()
    try:
        filas = [dict(r) for r in conn.execute("""
            SELECT m.id, m.repuesto_id, m.fecha, m.cantidad, m.costo_unitario, m.usuario, m.ot_item_id,
                   r.codigo, r.descripcion, r.unidad, r.contenido, r.contenido_unidad, r.envase, r.stock_actual,
                   i.descripcion AS item_desc
            FROM repuestos_movimientos m
            JOIN repuestos r ON r.id = m.repuesto_id
            LEFT JOIN ot_items i ON i.id = m.ot_item_id
            WHERE m.ot_id=? AND m.tipo='salida'
            ORDER BY m.id""", (ot_id,)).fetchall()]
    finally:
        conn.close()
    total = 0.0
    for f in filas:
        f["costo"] = round(float(f["cantidad"] or 0) * float(f["costo_unitario"] or 0))
        f["contenido_sacado"] = round(float(f["cantidad"] or 0) * float(f["contenido"] or 0), 2) if f["contenido"] else 0
        total += f["costo"]
    return {"usados": filas, "total": round(total)}


def buscar_para_ot(q, limite=25):
    """Lo del depósito para elegir desde la OT: primero lo que tiene stock."""
    reps = rdb.obtener_repuestos(buscar=q or None)
    reps.sort(key=lambda r: (float(r.get("stock_actual") or 0) <= 0, r.get("descripcion") or ""))
    if q and len(reps) < 5:   # mal escrito o abreviado: lo que más se parece
        try:
            import buscador
            ya = {r["id"] for r in reps}
            for r, s, m in buscador.buscar_repuestos(q, limite):
                if r["id"] not in ya:
                    reps.append(dict(rdb._enriquecer(r), parecido=True))
        except Exception:
            pass
    out = []
    for r in reps[:limite]:
        out.append({k: r.get(k) for k in ("id", "codigo", "descripcion", "marca", "aplicacion", "categoria", "unidad",
                                          "stock_actual", "costo_unitario", "contenido", "contenido_unidad", "envase", "contenido_total",
                                          "ubicacion", "estado_stock", "parecido")})
    return out


def sacar_para_ot(ot_id, repuesto_id, cantidad, en="envases", item_id=None, usuario=""):
    """en='envases' (o unidades) | 'contenido' (litros, kg… de un producto por envase)."""
    cantidad = _num(cantidad)
    if cantidad <= 0:
        return False, "Poné cuánto se sacó."
    conn = get_connection()
    try:
        ot = _ot(conn, ot_id)
        rep = conn.execute("SELECT * FROM repuestos WHERE id=? AND activo=1", (repuesto_id,)).fetchone()
        item = None
        if item_id:
            item = conn.execute("SELECT id, descripcion FROM ot_items WHERE id=? AND ot_id=?", (item_id, ot_id)).fetchone()
    finally:
        conn.close()
    if not ot:
        return False, "La OT no existe."
    if not rep:
        return False, "Ese repuesto no está en el inventario."
    rep = dict(rep)
    contenido = float(rep.get("contenido") or 0)
    if en == "contenido":
        if not contenido:
            return False, "Ese producto no tiene cargado cuánto trae cada envase."
        envases = round(cantidad / contenido, 4)
    else:
        envases = cantidad
    coche = f"coche {ot['n_interno']}" if ot.get("n_interno") else (ot.get("patente") or "")
    motivo = " · ".join(x for x in (f"OT #{ot_id}", coche, item and item["descripcion"]) if x)
    ok, res = rdb.registrar_movimiento(repuesto_id, "salida", envases, motivo=motivo[:200],
                                       costo_unitario=float(rep.get("costo_unitario") or 0),
                                       referencia=f"OT:{ot_id}", usuario=usuario)
    if not ok:
        if contenido and "insuficiente" in str(res).lower():
            stk = float(rep.get("stock_actual") or 0)
            env = rep.get("envase") or "envase"
            if abs(stk - 1) > 1e-9:
                env = env[:-2] + "ones" if env.endswith("ón") else env + ("s" if env[-1:] in "aeiou" else "es")
            n = lambda x: f"{x:,.2f}".rstrip("0").rstrip(".").replace(",", "X").replace(".", ",").replace("X", ".")
            res = f"No alcanza: en el depósito hay {n(stk * contenido)} {rep.get('contenido_unidad') or 'litros'} ({n(stk)} {env})."
        return False, res
    # Se marca a qué OT (e ítem) fue
    conn = get_connection()
    try:
        m = conn.execute("""SELECT id FROM repuestos_movimientos WHERE repuesto_id=? AND referencia=? AND tipo='salida'
                            ORDER BY id DESC LIMIT 1""", (repuesto_id, f"OT:{ot_id}")).fetchone()
        if m:
            conn.execute("UPDATE repuestos_movimientos SET ot_id=?, ot_item_id=? WHERE id=?",
                         (ot_id, item["id"] if item else None, m["id"]))
            conn.commit()
    finally:
        conn.close()
    return True, {"stock_actual": res["stock_actual"], "envases": envases}


def devolver_de_ot(ot_id, mov_id):
    conn = get_connection()
    try:
        m = conn.execute("SELECT id, ot_id FROM repuestos_movimientos WHERE id=?", (mov_id,)).fetchone()
    finally:
        conn.close()
    if not m or m["ot_id"] != ot_id:
        return False, "Eso no se sacó para esta OT."
    return rdb.eliminar_movimiento(mov_id)


# ════════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ════════════════════════════════════════════════════════════════════════════

def _puede_ver():
    return session.get("rol") in ("admin", "taller", "compras", "auditor")


def _puede_sacar():
    # Es lo que sale del depósito para un coche, con la OT como respaldo
    return session.get("rol") in ("admin", "taller", "compras")


def _quien():
    return session.get("nombre") or session.get("usuario") or ""


def _auditar(accion, detalle="", referencia=""):
    try:
        from database import registrar_auditoria
        registrar_auditoria(usuario=_quien() or "?", rol=session.get("rol") or "", accion=accion,
                            categoria="Inventario", detalle=str(detalle)[:200], referencia=referencia)
    except Exception:
        pass


@bp_ot_inv.route("/api/ots/repuestos_buscar", methods=["GET"])
def api_buscar():
    if not _puede_ver():
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    return jsonify(buscar_para_ot(request.args.get("q", "").strip()))


@bp_ot_inv.route("/api/ots/<int:ot_id>/repuestos", methods=["GET"])
def api_usados(ot_id):
    if not _puede_ver():
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    return jsonify({"ok": True, "puede_sacar": _puede_sacar(), **usados_en_ot(ot_id)})


@bp_ot_inv.route("/api/ots/<int:ot_id>/repuestos", methods=["POST"])
def api_sacar(ot_id):
    if not _puede_sacar():
        return jsonify({"ok": False, "msg": "Sin permiso para sacar del depósito"}), 403
    d = request.json or {}
    try:
        rid = int(d.get("repuesto_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "msg": "Elegí el repuesto."}), 400
    item = d.get("item_id")
    item = int(item) if str(item or "").isdigit() else None
    ok, res = sacar_para_ot(ot_id, rid, d.get("cantidad"), d.get("en") or "envases", item, _quien())
    if not ok:
        return jsonify({"ok": False, "msg": res}), 400
    _auditar(f"Sacó del depósito para la OT #{ot_id}", f"repuesto {rid} · {res['envases']:g}", f"repuesto:{rid}")
    return jsonify({"ok": True, "stock_actual": res["stock_actual"], **usados_en_ot(ot_id)})


@bp_ot_inv.route("/api/ots/<int:ot_id>/repuestos/<int:mov_id>", methods=["DELETE"])
def api_devolver(ot_id, mov_id):
    if not _puede_sacar():
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    ok, msg = devolver_de_ot(ot_id, mov_id)
    if not ok:
        return jsonify({"ok": False, "msg": msg}), 400
    _auditar(f"Devolvió al depósito lo sacado para la OT #{ot_id}", f"movimiento {mov_id}")
    return jsonify({"ok": True, **usados_en_ot(ot_id)})
