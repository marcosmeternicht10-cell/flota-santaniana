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
import repuestos_multi as multi

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


def _puede_proveedores():
    """Quién anota proveedores y precios de un repuesto: también Compras,
    que es la que habla con los proveedores."""
    return session.get("rol") in ("admin", "taller", "compras")


# ─── Catálogo ─────────────────────────────────────────────────────────────────

@bp_repuestos.route("/api/repuestos", methods=["GET"])
def api_repuestos():
    categoria = request.args.get("categoria") or None
    buscar = request.args.get("buscar") or None
    solo_bajos = request.args.get("solo_bajos") in ("1", "true", "si")
    reps = rdb.obtener_repuestos(categoria=categoria, buscar=buscar, solo_bajos=solo_bajos)
    if buscar and len(reps) < 3:   # mal escrito o abreviado: sumar lo que más se parece
        try:
            import buscador
            ya = {r["id"] for r in reps}
            for r, s, m in buscador.buscar_repuestos(buscar, 25):
                if r["id"] in ya or (categoria and r.get("categoria") != categoria):
                    continue
                d = rdb._enriquecer(r)
                if solo_bajos and d["estado_stock"] not in ("bajo", "sin_stock"):
                    continue
                d["parecido"] = True
                reps.append(d)
        except Exception as e:
            print(f"[repuestos] buscador: {e}")
    n = multi.conteos()
    for r in reps:
        r["n_proveedores"] = n.get(r["id"], 1 if r.get("proveedor") else 0)
    return jsonify(reps)


@bp_repuestos.route("/api/repuestos/proveedores", methods=["GET"])
def api_proveedores():
    """Busca en el directorio de proveedores (nombre, RUC o número)."""
    a = request.args
    res = rdb.obtener_proveedores(
        a.get("q"), min(int(a.get("limite") or 30), 100),
        pagina=int(a.get("pagina") or 0), letra=a.get("letra") or "",
        solo_uso=a.get("uso") in ("1", "true"))
    if a.get("q") and not res.get("proveedores"):   # mal escrito: lo que más se parece
        try:
            import buscador
            res["proveedores"] = [dict({k: (p.get(k) or "") for k in rdb.CAMPOS_PROV}, repuestos=0, parecido=True)
                                  for p, s in buscador.buscar_proveedores(a.get("q"), 12)]
            res["coincidencias"] = len(res["proveedores"])
        except Exception as e:
            print(f"[repuestos] buscador proveedores: {e}")
    return jsonify(res)


@bp_repuestos.route("/api/repuestos/proveedores/resumen", methods=["GET"])
def api_proveedores_resumen():
    return jsonify(rdb.resumen_proveedores())


@bp_repuestos.route("/api/repuestos/proveedor", methods=["POST"])
def api_crear_proveedor():
    if session.get("rol") not in ("admin", "taller", "compras"):
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    d = request.json or {}
    ok, msg = rdb.crear_proveedor(d)
    if ok:
        _auditar(f"Agregó el proveedor '{d.get('nombre')}'")
    return jsonify({"ok": ok, "msg": msg}), (200 if ok else 400)


@bp_repuestos.route("/api/repuestos/proveedor", methods=["GET"])
def api_proveedor():
    p = rdb.proveedor_por_nombre(request.args.get("nombre"))
    return jsonify(p or {})


@bp_repuestos.route("/api/repuestos/proveedor", methods=["PATCH"])
def api_editar_proveedor():
    if session.get("rol") not in ("admin", "taller", "compras"):
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    d = request.json or {}
    ok, msg = rdb.editar_proveedor(d.get("nombre"), d)
    if ok:
        _auditar(f"Actualizó el proveedor '{d.get('nombre')}'")
    return jsonify({"ok": ok, "msg": msg}), (200 if ok else 400)


@bp_repuestos.route("/api/repuestos/<int:rid>", methods=["GET"])
def api_repuesto(rid):
    rep = rdb.obtener_repuesto(rid)
    if not rep:
        return jsonify({"error": "Repuesto no encontrado"}), 404
    rep["proveedores"] = multi.lista(rid, rep.get("proveedor"))
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
    # El código ya está cargado: no se rebota, se avisa qué repuesto es para
    # que la pantalla ofrezca sumarle este proveedor (un repuesto, un stock).
    existente = multi.repuesto_por_codigo(codigo)
    if existente:
        return jsonify({"ok": False, "existe": True, "repuesto": existente,
                        "msg": f"El código '{existente['codigo']}' ya está cargado."})
    d["usuario"] = session.get("nombre") or session.get("usuario") or ""
    ok, res = rdb.agregar_repuesto(codigo, descripcion, **{
        k: v for k, v in d.items() if k not in ("codigo", "descripcion")
    })
    if ok:
        multi.sincronizar(res)
        try:
            import ot_inventario
            ot_inventario.guardar_contenido(res, d)
        except Exception:
            pass
        _auditar(f"Creó el repuesto '{codigo}'", f"{descripcion}", f"repuesto:{res}")
        return jsonify({"ok": True, "id": res})
    return jsonify({"ok": False, "msg": res}), 400


@bp_repuestos.route("/api/repuestos/<int:rid>", methods=["PATCH"])
def api_actualizar_repuesto(rid):
    if not _puede_editar():
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    d = request.json or {}
    ok, msg = rdb.actualizar_repuesto(rid, **d)
    if not ok and msg == "Sin campos para actualizar." and any(k in d for k in ("contenido", "contenido_unidad", "envase")):
        ok, msg = True, "Repuesto actualizado."
    if ok:
        try:
            import ot_inventario
            ot_inventario.guardar_contenido(rid, d)
        except Exception:
            pass
        multi.sincronizar(rid)
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

    # Entrada de una compra: con el proveedor elegido se actualiza su precio
    proveedor = (d.get("proveedor") or "").strip() if tipo == "entrada" else ""
    if proveedor and not (d.get("motivo") or "").strip():
        d["motivo"] = f"Compra a {proveedor}"
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
        if proveedor:
            try:
                multi.agregar(rid, proveedor, precio=float(d.get("costo_unitario", 0) or 0))
            except Exception:
                pass
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


# ─── Proveedores de cada repuesto (un código, varios proveedores) ─────────────

@bp_repuestos.route("/api/repuestos/<int:rid>/proveedores", methods=["POST"])
def api_agregar_proveedor_repuesto(rid):
    """Suma un proveedor al repuesto (o le actualiza el precio). Si viene una
    cantidad, además registra la entrada de stock de esa compra."""
    if not _puede_proveedores():
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    d = request.json or {}
    try:
        precio = float(d.get("precio", 0) or 0)
        cantidad = float(d.get("cantidad", 0) or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "msg": "El precio o la cantidad no son números."}), 400
    ok, res = multi.agregar(rid, d.get("proveedor"), precio=precio,
                            codigo_prov=d.get("codigo_prov"),
                            contacto=d.get("contacto"), telefono=d.get("telefono"))
    if not ok:
        return jsonify({"ok": False, "msg": res}), 400
    if cantidad > 0:
        rdb.registrar_movimiento(rid, "entrada", cantidad, motivo=f"Compra a {res['proveedor']}",
                                 costo_unitario=precio,
                                 usuario=session.get("nombre") or session.get("usuario") or "")
    _auditar(f"{'Agregó' if res['nuevo'] else 'Actualizó'} el proveedor '{res['proveedor']}' del repuesto (ID {rid})",
             f"precio {precio:,.0f}".replace(",", ".") + (f" · entraron {cantidad:g}" if cantidad > 0 else ""),
             f"repuesto:{rid}")
    return jsonify({"ok": True, **res})


@bp_repuestos.route("/api/repuestos/oferta/<int:pid>", methods=["PATCH"])
def api_editar_proveedor_repuesto(pid):
    if not _puede_proveedores():
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    d = request.json or {}
    try:
        precio = float(d["precio"]) if d.get("precio") not in (None, "") else None
    except (TypeError, ValueError):
        return jsonify({"ok": False, "msg": "El precio no es un número."}), 400
    ok, res = multi.editar(pid, precio=precio, codigo_prov=d.get("codigo_prov"))
    if ok:
        _auditar(f"Cambió el precio de un proveedor del repuesto (ID {res})", referencia=f"repuesto:{res}")
    return jsonify({"ok": ok, "msg": "" if ok else res}), (200 if ok else 400)


@bp_repuestos.route("/api/repuestos/oferta/<int:pid>", methods=["DELETE"])
def api_quitar_proveedor_repuesto(pid):
    if not _puede_proveedores():
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    ok, res = multi.quitar(pid)
    if ok:
        _auditar(f"Sacó un proveedor del repuesto (ID {res})", referencia=f"repuesto:{res}")
    return jsonify({"ok": ok, "msg": "" if ok else res}), (200 if ok else 400)


@bp_repuestos.route("/api/repuestos/oferta/<int:pid>/principal", methods=["POST"])
def api_principal_proveedor_repuesto(pid):
    if not _puede_proveedores():
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    ok, res = multi.hacer_principal(pid)
    if ok:
        _auditar(f"Cambió el proveedor principal del repuesto (ID {res})", referencia=f"repuesto:{res}")
    return jsonify({"ok": ok, "msg": "" if ok else res}), (200 if ok else 400)
