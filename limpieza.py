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
    "rendiciones_corp",           # servicios corporativos reales
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
}


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
        })
    protegido = {}
    for t in ("vehiculos", "usuarios", "rendiciones_corp"):
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
