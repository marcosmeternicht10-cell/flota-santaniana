"""
repuestos_routes.py — Endpoints del inventario de repuestos (La Santaniana)

Se registra como Blueprint para no tocar el cuerpo de app.py.
La protección de login se mantiene por el @app.before_request global que ya
existe en app.py (que exige sesión para todo lo que no sea público), así que
acá solo agregamos control de ROL donde corresponde.

Enganche en app.py (ver instrucciones):
    from repuestos_routes import bp_repuestos, init_repuestos_module
    init_repuestos_module(app)          # inicializa las tablas
    app.register_blueprint(bp_repuestos)
"""

from flask import Blueprint, request, jsonify, session
import repuestos_db as rdb

bp_repuestos = Blueprint("repuestos", __name__)


def init_repuestos_module(app):
    """Crea las tablas del inventario al arrancar la app."""
    rdb.inicializar_repuestos()


def _auditar(accion, detalle="", referencia=""):
    """Registra en la auditoría usando el usuario de la sesión.
    Importa database de forma perezosa para evitar import circular."""
    try:
        from database import registrar_auditoria
        registrar_auditoria(
            usuario=session.get("nombre") or session.get("usuario") or "?",
            rol=session.get("rol") or "",
            accion=accion, categoria="Repuestos",
            detalle=detalle, referencia=referencia)
    except Exception:
        pass


def _puede_editar():
    """Sólo admin y taller pueden modificar el inventario.
    Compras puede ver y reponer (entradas)."""
    return session.get("rol") in ("admin", "taller")


# ─── Catálogo ─────────────────────────────────────────────────────────────────

@bp_repuestos.route("/api/repuestos", methods=["GET"])
def api_repuestos():
    categoria = request.args.get("categoria") or None
    buscar = request.args.get("buscar") or None
    solo_bajos = request.args.get("solo_bajos") in ("1", "true", "si")
    return jsonify(rdb.obtener_repuestos(
        categoria=categoria, buscar=buscar, solo_bajos=solo_bajos))


@bp_repuestos.route("/api/repuestos/<int:rid>", methods=["GET"])
def api_repuesto(rid):
    rep = rdb.obtener_repuesto(rid)
    if not rep:
        return jsonify({"error": "Repuesto no encontrado"}), 404
    return jsonify(rep)


@bp_repuestos.route("/api/repuestos", methods=["POST"])
def api_crear_repuesto():
    if not _puede_editar():
        return jsonify({"ok": False, "msg": "Sin permiso para crear repuestos"}), 403
    d = request.json or {}
    codigo = (d.get("codigo") or "").strip()
    descripcion = (d.get("descripcion") or "").strip()
    if not codigo or not descripcion:
        return jsonify({"ok": False, "msg": "Código y descripción son obligatorios"}), 400
    d["usuario"] = session.get("nombre") or session.get("usuario") or ""
    ok, res = rdb.agregar_repuesto(codigo, descripcion, **{
        k: v for k, v in d.items() if k not in ("codigo", "descripcion")
    })
    if ok:
        _auditar(f"Creó el repuesto '{codigo}'", f"{descripcion}", f"repuesto:{res}")
        return jsonify({"ok": True, "id": res})
    return jsonify({"ok": False, "msg": res}), 400


@bp_repuestos.route("/api/repuestos/<int:rid>", methods=["PATCH"])
def api_actualizar_repuesto(rid):
    if not _puede_editar():
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    d = request.json or {}
    ok, msg = rdb.actualizar_repuesto(rid, **d)
    if ok:
        _auditar(f"Modificó el repuesto (ID {rid})", referencia=f"repuesto:{rid}")
    return jsonify({"ok": ok, "msg": msg}), (200 if ok else 400)


@bp_repuestos.route("/api/repuestos/<int:rid>", methods=["DELETE"])
def api_eliminar_repuesto(rid):
    if not _puede_editar():
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    ok, msg = rdb.eliminar_repuesto(rid)
    if ok:
        _auditar(f"Dio de baja el repuesto (ID {rid})", referencia=f"repuesto:{rid}")
    return jsonify({"ok": ok, "msg": msg})


# ─── Movimientos de stock ─────────────────────────────────────────────────────

@bp_repuestos.route("/api/repuestos/<int:rid>/movimientos", methods=["GET"])
def api_movimientos(rid):
    return jsonify(rdb.obtener_movimientos(rid))


@bp_repuestos.route("/api/repuestos/<int:rid>/movimiento", methods=["POST"])
def api_registrar_movimiento(rid):
    # Salidas y ajustes: solo admin/taller. Entradas: también compras.
    d = request.json or {}
    tipo = (d.get("tipo") or "").lower().strip()
    rol = session.get("rol")
    if tipo in ("salida", "ajuste") and rol not in ("admin", "taller"):
        return jsonify({"ok": False, "msg": "Sin permiso para esta operación"}), 403
    if tipo == "entrada" and rol not in ("admin", "taller", "compras"):
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403

    ok, res = rdb.registrar_movimiento(
        rid, tipo, d.get("cantidad", 0),
        motivo=d.get("motivo", ""),
        costo_unitario=float(d.get("costo_unitario", 0) or 0),
        referencia=d.get("referencia", ""),
        usuario=session.get("nombre") or session.get("usuario") or "",
        observaciones=d.get("observaciones", ""),
        fecha=d.get("fecha"),
    )
    if ok:
        cant = d.get("cantidad", 0)
        _auditar(f"Movimiento de stock: {tipo} {cant} (rep. ID {rid})",
                 d.get("motivo", ""), f"repuesto:{rid}")
        return jsonify({"ok": True, **res})
    return jsonify({"ok": False, "msg": res}), 400


@bp_repuestos.route("/api/repuestos/movimientos/<int:mid>", methods=["DELETE"])
def api_eliminar_movimiento(mid):
    if not _puede_editar():
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    ok, msg = rdb.eliminar_movimiento(mid)
    return jsonify({"ok": ok, "msg": msg})


# ─── Dashboard / alertas ──────────────────────────────────────────────────────

@bp_repuestos.route("/api/repuestos/resumen", methods=["GET"])
def api_resumen():
    return jsonify(rdb.resumen_inventario())


@bp_repuestos.route("/api/repuestos/bajo_minimo", methods=["GET"])
def api_bajo_minimo():
    return jsonify(rdb.repuestos_bajo_minimo())


@bp_repuestos.route("/api/repuestos/categorias", methods=["GET"])
def api_categorias():
    return jsonify(rdb.categorias_disponibles())
