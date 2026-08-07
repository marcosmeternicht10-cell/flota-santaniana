"""
limpieza.py — Borrado selectivo de datos de prueba (La Santaniana)

Cuando el sistema pasa de la etapa de pruebas al uso real, hay que sacar lo
que se cargó para probar sin perder lo que ya es información verdadera.

Este módulo NO borra la base entera. Trabaja por grupos, muestra cuánto va a
borrar antes de hacerlo, y tiene una lista de tablas que jamás toca — aunque
alguien lo pida.

Enganche en app.py:
    from limpieza import bp_limpieza
    app.register_blueprint(bp_limpieza)
"""

from flask import Blueprint, request, jsonify, session
from db_compat import get_connection

try:
    from database import auditar
except Exception:
    def auditar(*a, **k):
        pass

bp_limpieza = Blueprint("limpieza", __name__)


# ════════════════════════════════════════════════════════════════════════════
# TABLAS PROTEGIDAS — nunca se borran, pase lo que pase
# ════════════════════════════════════════════════════════════════════════════
# La flota, las cuentas de la gente, las rendiciones reales de corporativos y
# la configuración del sistema. Si un grupo intentara incluir una de estas,
# se filtra igual antes de ejecutar.

TABLAS_PROTEGIDAS = {
    "vehiculos",                  # los 89 coches
    "usuarios",                   # cuentas (admin, taller, compras, choferes)
    "planes_mantenimiento",       # configuración de planes
    "tareas_plan",
    "vehiculo_plan",
    "config_neumaticos",
    "config_neumaticos_vehiculo",
    "config_turismo",
    "auditoria",                  # registro de quién hizo qué
}


# ════════════════════════════════════════════════════════════════════════════
# GRUPOS QUE SE PUEDEN LIMPIAR
# ════════════════════════════════════════════════════════════════════════════
# Cada grupo agrupa las tablas que van juntas. El orden dentro de cada grupo
# importa: primero los hijos, después los padres (para no romper referencias).

GRUPOS = {
    "ots": {
        "nombre": "Órdenes de trabajo y compras",
        "detalle": "OTs con sus ítems, fotos, presupuestos y entregas de compras",
        "tablas": ["ot_fotos", "compras_evidencia", "ot_items", "ordenes_trabajo"],
        "conteo": "ordenes_trabajo",
    },
    "correctivos": {
        "nombre": "Correctivos",
        "detalle": "Fallas y reparaciones cargadas",
        "tablas": ["correctivos"],
        "conteo": "correctivos",
    },
    "servicios": {
        "nombre": "Servicios y mantenimientos realizados",
        "detalle": "Servicios prestados y mantenimientos preventivos ejecutados",
        "tablas": ["servicios", "mantenimientos_realizados"],
        "conteo": "servicios",
    },
    "costos": {
        "nombre": "Costos cargados",
        "detalle": "Costos fijos y variables por vehículo",
        "tablas": ["costos"],
        "conteo": "costos",
    },
    "combustible": {
        "nombre": "Cargas de combustible",
        "detalle": "Registros de litros, precio y odómetro",
        "tablas": ["combustible"],
        "conteo": "combustible",
    },
    "neumaticos": {
        "nombre": "Neumáticos",
        "detalle": "Stock de cubiertas, instalaciones y truckies",
        "tablas": ["truckies", "instalaciones_neumaticos", "neumaticos"],
        "conteo": "neumaticos",
    },
    "historial": {
        "nombre": "Historial retroactivo",
        "detalle": "Eventos cargados desde las planillas de papel",
        "tablas": ["historial_eventos"],
        "conteo": "historial_eventos",
    },
    "fuera_servicio": {
        "nombre": "Períodos fuera de servicio",
        "detalle": "Coches marcados como parados",
        "tablas": ["fuera_servicio"],
        "conteo": "fuera_servicio",
    },
    "repuestos": {
        "nombre": "Inventario de repuestos",
        "detalle": "Depósito completo con sus movimientos",
        "tablas": ["repuestos_movimientos", "repuestos"],
        "conteo": "repuestos",
    },
    "documentos": {
        "nombre": "Documentos de vehículos",
        "detalle": "Habilitaciones, seguros y vencimientos",
        "tablas": ["documentos"],
        "conteo": "documentos",
    },
    "turismo": {
        "nombre": "Presupuestos de turismo",
        "detalle": "Cotizaciones de viajes",
        "tablas": ["presupuestos_turismo"],
        "conteo": "presupuestos_turismo",
    },
    "rendiciones_corp": {
        "nombre": "Rendiciones de corporativos",
        "detalle": "Servicios que cargaron los choferes desde el celular. "
                   "Las cuentas de los choferes NO se borran, solo los servicios.",
        "tablas": ["rendiciones_corp"],
        "conteo": "rendiciones_corp",
        "delicado": True,          # la interfaz lo destaca aparte
    },
}


def reinicio_total(usuario_admin=""):
    """Deja el sistema como recién instalado: sin datos, con todos los módulos
    funcionando.

    Borra en orden de dependencias (primero lo que apunta a otras tablas,
    después las tablas apuntadas), para que no falle por referencias.

    Dos cosas sobreviven siempre:
      - La cuenta del admin que ejecuta el reinicio. Si se borrara, nadie
        podría volver a entrar al sistema.
      - La configuración interna que los módulos necesitan para arrancar.
    """
    # Orden importante: hijos antes que padres.
    ORDEN = [
        # Servicios corporativos
        "rendiciones_corp",
        # Taller y compras
        "ot_fotos", "compras_evidencia", "ot_items", "ordenes_trabajo",
        "correctivos", "mantenimientos_realizados", "servicios",
        # Neumáticos
        "truckies", "instalaciones_neumaticos", "neumaticos",
        "config_neumaticos_vehiculo", "config_neumaticos",
        # Depósito
        "repuestos_movimientos", "repuestos",
        # Registros por vehículo
        "combustible", "costos", "documentos", "fuera_servicio",
        "historial_eventos", "presupuestos_turismo",
        # Planes de mantenimiento
        "vehiculo_plan", "tareas_plan", "planes_mantenimiento",
        # Y por último la flota
        "vehiculos",
    ]

    detalle, errores = [], []
    for tabla in ORDEN:
        conn = get_connection()
        n = _contar(conn, tabla)
        if n is None or n == 0:
            conn.close()
            continue
        try:
            conn.execute(f"DELETE FROM {tabla}")
            conn.commit()
            detalle.append({"tabla": tabla, "borrados": n})
        except Exception as e:
            conn.rollback()
            errores.append(f"{tabla}: {str(e).splitlines()[0][:110]}")
        finally:
            conn.close()

    # Usuarios: se borran todos MENOS el admin que está ejecutando esto
    conn = get_connection()
    try:
        n = conn.execute("SELECT COUNT(*) AS c FROM usuarios WHERE usuario<>?",
                         (usuario_admin,)).fetchone()["c"]
        if n:
            conn.execute("DELETE FROM usuarios WHERE usuario<>?", (usuario_admin,))
            conn.commit()
            detalle.append({"tabla": "usuarios", "borrados": n})
    except Exception as e:
        conn.rollback()
        errores.append(f"usuarios: {str(e).splitlines()[0][:110]}")
    finally:
        conn.close()

    # Los planes de mantenimiento y las configs de neumáticos son parte del
    # sistema, no datos de la empresa: se vuelven a sembrar acá para que los
    # módulos de preventivo y neumáticos queden usables sin reiniciar el
    # servicio.
    planes_ok = False
    try:
        from mantenimiento_seed import cargar_planes_default
        cargar_planes_default()
        planes_ok = True
    except Exception as e:
        errores.append(f"planes de mantenimiento: {str(e).splitlines()[0][:110]}")

    # Verificación honesta: recontar todo lo que debía quedar vacío
    conn = get_connection()
    sobrantes = []
    for tabla in ORDEN:
        # Los planes se acaban de regenerar a propósito: no son "sobrantes"
        if tabla in ("planes_mantenimiento", "tareas_plan",
                     "config_neumaticos", "config_neumaticos_vehiculo"):
            continue
        n = _contar(conn, tabla)
        if n:
            sobrantes.append(f"{tabla} ({n})")
    admins = _contar(conn, "usuarios") or 0
    conn.close()

    total = sum(d["borrados"] for d in detalle)
    return {"total": total, "detalle": detalle, "errores": errores,
            "sobrantes": sobrantes, "usuarios_restantes": admins,
            "planes_regenerados": planes_ok}


def _contar(conn, tabla):
    """Cuántas filas tiene una tabla. Si no existe, devuelve None."""
    try:
        return conn.execute(f"SELECT COUNT(*) AS c FROM {tabla}").fetchone()["c"]
    except Exception:
        return None


def vista_previa():
    """Cuántos registros hay en cada grupo — lo que se vería borrado.
    También informa lo protegido, para que quede claro qué NO se toca."""
    conn = get_connection()
    grupos = []
    for clave, g in GRUPOS.items():
        n = _contar(conn, g["conteo"])
        if n is None:
            continue                       # tabla no existe en esta base
        grupos.append({
            "clave": clave,
            "nombre": g["nombre"],
            "detalle": g["detalle"],
            "registros": n,
            "delicado": g.get("delicado", False),
        })
    protegido = {}
    for t in ("vehiculos", "usuarios"):
        n = _contar(conn, t)
        if n is not None:
            protegido[t] = n
    conn.close()
    return {"grupos": grupos, "protegido": protegido}


def limpiar(claves):
    """Borra los grupos indicados y VERIFICA que hayan quedado vacíos.

    Cada tabla se confirma por separado: si una falla, las demás se borran
    igual (antes un solo error deshacía todo el trabajo sin avisar). Al final
    cuenta de nuevo para informar lo que realmente pasó, no lo que se esperaba.
    """
    resultado = []
    for clave in claves:
        g = GRUPOS.get(clave)
        if not g:
            continue

        conn = get_connection()
        antes = _contar(conn, g["conteo"]) or 0
        conn.close()

        errores = []
        for tabla in g["tablas"]:
            if tabla in TABLAS_PROTEGIDAS:
                continue                   # blindaje: nunca se borra
            conn = get_connection()
            if _contar(conn, tabla) is None:
                conn.close()
                continue                   # la tabla no existe en esta base
            try:
                conn.execute(f"DELETE FROM {tabla}")
                conn.commit()              # cada tabla se guarda sola
            except Exception as e:
                conn.rollback()
                errores.append(f"{tabla}: {str(e).splitlines()[0][:110]}")
            finally:
                conn.close()

        # Verificación real: ¿quedó vacío de verdad?
        conn = get_connection()
        quedan = _contar(conn, g["conteo"]) or 0
        conn.close()

        resultado.append({
            "grupo": g["nombre"],
            "borrados": antes - quedan,
            "quedan": quedan,
            "errores": errores,
        })
    return resultado


# ════════════════════════════════════════════════════════════════════════════
# ENDPOINTS — solo admin
# ════════════════════════════════════════════════════════════════════════════

@bp_limpieza.route("/api/limpieza/reinicio_total", methods=["POST"])
def api_limpieza_reinicio():
    """Deja el sistema en cero: sin flota, sin usuarios (salvo el admin que lo
    ejecuta), sin ningún dato. Todos los módulos siguen funcionando."""
    if session.get("rol") != "admin":
        return jsonify({"error": "Sin permiso"}), 403
    d = request.json or {}
    if (d.get("confirmacion") or "").strip().upper() != "REINICIAR TODO":
        return jsonify({"ok": False,
                        "msg": "Escribí REINICIAR TODO para confirmar."}), 400

    yo = session.get("usuario", "")
    res = reinicio_total(usuario_admin=yo)
    auditar(f"Reinició el sistema completo ({res['total']} registros)",
            "Sistema", f"Conservó la cuenta '{yo}'")

    if res["errores"] or res["sobrantes"]:
        problemas = res["errores"] + [f"quedaron: {', '.join(res['sobrantes'])}"
                                      if res["sobrantes"] else ""]
        return jsonify({"ok": False, **res,
                        "msg": "Se borró casi todo, pero hubo problemas: " +
                               " · ".join(p for p in problemas if p)})
    return jsonify({"ok": True, **res,
                    "msg": f"Sistema reiniciado. Se borraron {res['total']} "
                           f"registro(s). Tu cuenta '{yo}' quedó activa."})


@bp_limpieza.route("/api/limpieza/preview", methods=["GET"])
def api_limpieza_preview():
    """Cuánto hay de cada cosa, antes de decidir."""
    if session.get("rol") != "admin":
        return jsonify({"error": "Sin permiso"}), 403
    return jsonify(vista_previa())


@bp_limpieza.route("/api/limpieza/ejecutar", methods=["POST"])
def api_limpieza_ejecutar():
    """Borra los grupos elegidos. Pide una confirmación escrita para que no
    pueda dispararse por un clic accidental."""
    if session.get("rol") != "admin":
        return jsonify({"error": "Sin permiso"}), 403
    d = request.json or {}
    claves = d.get("grupos", [])
    confirmacion = (d.get("confirmacion") or "").strip().upper()
    if not claves:
        return jsonify({"ok": False, "msg": "No elegiste nada para borrar."}), 400
    if confirmacion != "BORRAR":
        return jsonify({"ok": False,
                        "msg": "Escribí BORRAR para confirmar."}), 400

    resultado = limpiar(claves)
    total = sum(r["borrados"] for r in resultado)
    fallaron = [r for r in resultado if r["quedan"] > 0 or r["errores"]]
    detalle = ", ".join(f"{r['grupo']}: {r['borrados']}" for r in resultado)
    auditar(f"Limpió datos de prueba ({total} registros)", "Sistema", detalle)

    if fallaron:
        problemas = []
        for r in fallaron:
            if r["errores"]:
                problemas.append(f"{r['grupo']} — {r['errores'][0]}")
            else:
                problemas.append(f"{r['grupo']}: quedaron {r['quedan']} sin borrar")
        return jsonify({"ok": False, "total": total, "detalle": resultado,
                        "msg": f"Se borraron {total}, pero hubo problemas: " +
                               " · ".join(problemas)})

    return jsonify({"ok": True, "total": total, "detalle": resultado,
                    "msg": f"Se borraron {total} registro(s)."})
