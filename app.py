"""
app.py — Servidor Flask + ventana de escritorio (PyWebView)
Sistema de Gestión de Flota - La Santaniana  ·  v9.2 Multiusuario
Moneda: Guaraní (₲)
"""

import os
import re
import threading
import datetime
from functools import wraps
from hora_local import ahora, ahora_iso, hoy
from flask import (Flask, render_template, request, jsonify, send_file,
                   session, redirect, url_for, make_response)

from database import (
    inicializar_db, agregar_vehiculo, actualizar_vehiculo, obtener_vehiculos, eliminar_vehiculo,
    obtener_servicios_vehiculo,
    agregar_costo, eliminar_costo, obtener_costos,
    meses_con_servicios, resumen_por_mes,
    # Mantenimiento:
    crear_plan, obtener_planes, obtener_plan, eliminar_plan,
    agregar_tarea, obtener_tareas_plan, eliminar_tarea,
    asignar_plan, obtener_plan_vehiculo, desasignar_plan,
    km_actual_vehiculo, registrar_mantenimiento, eliminar_mantenimiento,
    obtener_historial_mantenimiento, estado_mantenimiento,
    # Correctivos:
    agregar_correctivo, obtener_correctivos, actualizar_correctivo, eliminar_correctivo,
    obtener_correctivos_por_ot,
    # Documentos:
    agregar_documento, obtener_documentos, actualizar_documento, eliminar_documento,
    documentos_proximos_a_vencer,
    # Neumáticos:
    crear_config_neumaticos, obtener_config_neumaticos_plan, obtener_config_neumaticos_vehiculo,
    guardar_config_vehiculo, asignar_configs_automaticas,
    calcular_oee_vehiculo, registrar_fuera_servicio, cerrar_fuera_servicio, obtener_fuera_servicio,
    guardar_meta_km, guardar_km_manual, guardar_horario_salida, guardar_consumo_vehiculo,
    obtener_config_turismo, guardar_config_turismo, calcular_presupuesto_turismo,
    registrar_auditoria, obtener_auditoria, estadisticas_auditoria,
    registrar_carga_combustible, obtener_cargas_combustible,
    eliminar_carga_combustible, estadisticas_combustible,
    guardar_presupuesto_turismo, obtener_presupuestos_turismo, obtener_presupuesto_turismo,
    eliminar_presupuesto_turismo,
    agregar_neumatico, obtener_neumaticos, obtener_neumatico, eliminar_neumatico,
    actualizar_neumatico, instalar_neumatico, retirar_neumatico,
    obtener_neumaticos_vehiculo, historial_neumatico, estado_neumaticos_vehiculo,
    POSICIONES_POR_CONFIG, NOMBRE_POSICIONES,
    # Dashboard:
    dashboard_resumen,
    # Órdenes de trabajo:
    crear_ot, obtener_ot, obtener_ots, agregar_item_ot, actualizar_item_ot,
    eliminar_item_ot, actualizar_ot, cerrar_ot, eliminar_ot,
    agregar_foto_ot, obtener_fotos_ot, contar_fotos_ot, eliminar_foto_ot,
    enviar_ot_a_compras, guardar_presupuesto_compras, guardar_proveedor_compras, registrar_entrega_compras,
    obtener_evidencia_compras, obtener_ots_compras, marcar_en_camino_compras,
    # Cubiertas auxiliares (trucky):
    asignar_trucky, obtener_truckies_vehiculo, usar_trucky, retirar_trucky,
    # Reporte gerencial:
    reporte_gerencial,
    # Usuarios:
    crear_usuario, autenticar_usuario, obtener_usuarios, actualizar_usuario,
    eliminar_usuario, contar_usuarios, crear_admin_por_defecto,
)
from models import kpis_mes, kpis_produccion
from pdf_export import (generar_pdf, generar_reporte_gerencial_pdf,
                        generar_ot_pdf, generar_reporte_periodo_pdf,
                        generar_plan_preventivo_pdf, generar_correctivos_pdf,
                        generar_documentos_pdf)

app = Flask(__name__)
# Clave secreta para las sesiones (en producción se toma de variable de entorno)
app.secret_key = os.environ.get("SECRET_KEY", "la-santaniana-flota-2026-cambiar-esto")

# ─── Módulo de Contabilidad y Tesorería ─────────────────────────────────────
from contabilidad import bp_contabilidad, init_contabilidad
init_contabilidad(app)
app.register_blueprint(bp_contabilidad)

# ─── Módulo de Inventario de Repuestos ───────────────────────────────────────
# Se engancha como blueprint aparte (repuestos_db.py + repuestos_routes.py).
# init_repuestos_module crea las tablas del inventario al arrancar.
# Primero las tablas base del sistema (vehiculos, ots, etc.), después los
# módulos que dependen de ellas — el orden importa en una base nueva.
inicializar_db()
from repuestos_routes import bp_repuestos, init_repuestos_module
init_repuestos_module(app)
app.register_blueprint(bp_repuestos)

# ─── La OT conectada con el depósito ─────────────────────────────────────────
# Desde la OT se saca del inventario lo que se usa (y se devuelve si sobra).
# También los productos por envase (aceite en bidón, tambor…) con sus litros.
from ot_inventario import bp_ot_inv, init_ot_inventario
init_ot_inventario()
app.register_blueprint(bp_ot_inv)

# ─── Cargar repuestos al inventario desde un Excel ───────────────────────────
from repuestos_importar import bp_rep_imp
app.register_blueprint(bp_rep_imp)

# ─── Varios materiales por trabajo y OTs con varios coches ───────────────────
from ot_materiales import bp_ot_mat, init_ot_materiales
init_ot_materiales()
app.register_blueprint(bp_ot_mat)

# ─── Módulo de Carga de Historial Retroactivo ────────────────────────────────
# El historial en papel de cada bus se tipea acá con fecha retroactiva.
from historial_carga import bp_historial, init_historial_module
init_historial_module(app)
app.register_blueprint(bp_historial)

# ─── Plan preventivo por km ──────────────────────────────────────────────────
# Estado de cada coche y de la flota, "cada cuánto" propio por coche, agenda
# del taller con turnos y cupos, conexión con la OT (un cambio de aceite
# completado se carga solo en el preventivo) y cumplimiento.
from plan_preventivo import bp_prev, init_plan_preventivo
init_plan_preventivo()
app.register_blueprint(bp_prev)

# ─── Personal de taller ──────────────────────────────────────────────────────
# Cada uno con su número; en la OT se pone el número de quién hizo cada ítem y
# de ahí sale quién trabaja más, en qué coches y lo que quedó sin número.
from personal_taller import bp_personal, init_personal_taller
init_personal_taller()
app.register_blueprint(bp_personal)

# ─── Módulo de Servicios Corporativos ────────────────────────────────────────
# Choferes de corporativos cargan rendiciones desde el celular; admin las
# resume. init crea la tabla; el seed de choferes se corre desde /api/corp/seed.
from corporativos import bp_corp, init_corporativos_module
init_corporativos_module(app)
app.register_blueprint(bp_corp)

# ─── Corporativos: asignación del día ────────────────────────────────────────
# Quién cubre cada tramo y con qué coche (como el tráfico), con versiones,
# PDF/imagen para el grupo y el control de asignado contra rendido.
from corp_asignacion import bp_corp_asig, init_corp_asignacion
init_corp_asignacion()
app.register_blueprint(bp_corp_asig)

# ─── Limpieza de datos de prueba ─────────────────────────────────────────────
# Borrado selectivo por grupos, con vista previa. Nunca toca la flota, las
# cuentas de usuario ni las rendiciones de corporativos.
from limpieza import bp_limpieza
app.register_blueprint(bp_limpieza)

# ─── Agenda de servicios de turismo ──────────────────────────────────────────
from turismo_agenda import bp_turismo, init_turismo_agenda
init_turismo_agenda(app)
app.register_blueprint(bp_turismo)

# ─── Rendiciones de turismo ──────────────────────────────────────────────────
# El anticipo que se le da al chofer contra los gastos del viaje (combustible,
# peajes, hotel, DINATRAN...). Lo carga la oficina y lo aprueba administración.
from turismo_rendiciones import bp_rendiciones, init_rendiciones
init_rendiciones()
app.register_blueprint(bp_rendiciones)

# ─── Rendición de combustible por sobre ──────────────────────────────────────
# Como el sistema que usaba la oficina de Concepción: un sobre por coche con
# los comprobantes de la cuenta de la estación, del km inicial al final. Cada
# comprobante suma como carga del coche (consumo y control de robos).
from rendicion_combustible import bp_rend_comb, init_rendicion_combustible
init_rendicion_combustible()
app.register_blueprint(bp_rend_comb)

# ─── Tráfico nacional ────────────────────────────────────────────────────────
# Las salidas del día (lo que antes era el Excel del grupo de WhatsApp): se
# arma acá, el sistema sabe dónde quedó cada coche y sale un PDF único.
from trafico import bp_trafico, init_trafico
init_trafico()
app.register_blueprint(bp_trafico)

# Alpha (venta de pasajes, maqueta): los servicios salen del tráfico
from alpha import bp_alpha, init_alpha
init_alpha()
app.register_blueprint(bp_alpha)
# Las ventas de Alpha (todas las agencias), la caja y las liquidaciones
from alpha_ventas import bp_alpha_ventas, init_alpha_ventas
init_alpha_ventas()
app.register_blueprint(bp_alpha_ventas)
# Cuántas salidas lleva cada día de la semana (el internacional cambia según el día)
from trafico_patron import bp_patron, init_trafico_patron
init_trafico_patron()
app.register_blueprint(bp_patron)

# ─── Servicios ───────────────────────────────────────────────────────────────
# Cada salida del tráfico es un servicio: los indicadores salen de ahí, sin
# cargar nada aparte (reemplaza la carga a mano de servicios por coche).
from servicios import bp_servicios, init_servicios
init_servicios()
app.register_blueprint(bp_servicios)

# ─── Una sola OT abierta por coche ───────────────────────────────────────────
# Lo nuevo de un coche se suma a su OT abierta (separado por fecha) y las OTs
# pendientes que tenía se juntan en una. Va al final: toca tablas de varios
# módulos (preventivo, depósito, materiales).
from ot_unica import init_ot_unica
init_ot_unica()
# Por qué quedó pendiente cada trabajo (lo de días anteriores se resalta)
from ot_pendientes import bp_ot_pend, init_ot_pendientes
init_ot_pendientes()
app.register_blueprint(bp_ot_pend)
# Trabajos hechos fuera del taller: para completarlos hace falta la foto de la factura
from ot_afuera import bp_ot_afuera, init_ot_afuera
init_ot_afuera()
app.register_blueprint(bp_ot_afuera)
# Lo que reportan los choferes queda como pedido: los encargados deciden y priorizan
from ot_pedidos import bp_ot_pedidos, init_ot_pedidos
init_ot_pedidos()
app.register_blueprint(bp_ot_pedidos)
# Cuándo sale el coche que está en el taller (tráfico, corporativos y turismo)
from ot_salidas import bp_ot_salidas
app.register_blueprint(bp_ot_salidas)
# Hora de inicio y fin de cada técnico en cada OT
from ot_horas import bp_ot_horas, init_ot_horas
init_ot_horas()
app.register_blueprint(bp_ot_horas)

from compras_motivo import bp_compras_motivo, init_compras_motivo
from cajas import bp_cajas, init_cajas
from compras_repuestos import bp_compras_rep, init_compras_repuestos
from buscador import init_buscador
init_buscador()
init_compras_repuestos()
app.register_blueprint(bp_compras_rep)
init_cajas()
app.register_blueprint(bp_cajas)
init_compras_motivo()
app.register_blueprint(bp_compras_motivo)
# Servicios de corporativos: el ranking por servicio sacado de las rendiciones
from corp_servicios import bp_corp_servicios
app.register_blueprint(bp_corp_servicios)
# Agencias de venta de pasajes: fichas, contratos con versiones, papeles y vencimientos
from agencias import bp_agencias, init_agencias
init_agencias()
app.register_blueprint(bp_agencias)
# Panel del gerente: operación del día y plata del mes, solo lectura
from gerencia import bp_gerencia
app.register_blueprint(bp_gerencia)
# No dejar que Flask ponga su propio caché largo en los estáticos: lo manejamos
# nosotros con revalidación + versionado (ver _comprimir_respuesta y version_assets).
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0


# ─── Compresión gzip de respuestas ──────────────────────────────────────────
# Comprime las respuestas JSON/HTML antes de enviarlas. Como los datos viajan
# de EEUU a Paraguay, comprimirlos hace que lleguen más rápido (menos bytes).
import gzip as _gzip
import io as _io

@app.after_request
def _comprimir_respuesta(response):
    # Control de caché de los archivos estáticos (JS/CSS/imágenes).
    # Usamos 'no-cache' (que NO significa "no cachear", sino "revalidar siempre"):
    # el navegador puede guardar el archivo, pero ANTES de usarlo le pregunta al
    # servidor si cambió. Si cambió, lo baja de nuevo. Combinado con el ?v= que
    # cambia solo, esto hace que los usuarios SIEMPRE tengan la versión actual
    # sin tener que limpiar el caché manualmente.
    try:
        if request.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
    except Exception:
        pass
    try:
        acepta = request.headers.get("Accept-Encoding", "")
        if "gzip" not in acepta.lower():
            return response
        # Solo comprimir respuestas de texto/json de cierto tamaño
        ctype = response.content_type or ""
        if not any(t in ctype for t in ("application/json", "text/", "javascript")):
            return response
        if response.direct_passthrough or response.status_code >= 300:
            return response
        data = response.get_data()
        if len(data) < 500:  # no vale la pena comprimir cositas chicas
            return response
        comprimido = _gzip.compress(data, compresslevel=6)
        response.set_data(comprimido)
        response.headers["Content-Encoding"] = "gzip"
        response.headers["Content-Length"] = str(len(comprimido))
        response.headers["Vary"] = "Accept-Encoding"
    except Exception:
        pass
    return response


# ─── Autenticación ──────────────────────────────────────────────────────────

def login_requerido(f):
    """Decorador: exige que haya sesión iniciada."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "usuario_id" not in session:
            if request.path.startswith("/api/"):
                return jsonify({"error": "No autenticado", "login": True}), 401
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return wrapper


def rol_requerido(*roles):
    """Decorador: exige que el usuario tenga uno de los roles dados."""
    def deco(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if "usuario_id" not in session:
                return jsonify({"error": "No autenticado", "login": True}), 401
            if session.get("rol") not in roles:
                return jsonify({"error": "Sin permiso para esta acción"}), 403
            return f(*args, **kwargs)
        return wrapper
    return deco


def auditar(accion, categoria="", detalle="", referencia=""):
    """Helper: registra una acción en el historial usando el usuario de la sesión actual.
    'referencia' vincula el registro con su evidencia (foto), ej: 'compras:45'."""
    registrar_auditoria(
        usuario=session.get("nombre") or session.get("usuario") or "?",
        rol=session.get("rol") or "",
        accion=accion, categoria=categoria, detalle=detalle, referencia=referencia)


def compras_requerido(f):
    """Las rutas de Compras: el rol Compras, administración y los usuarios de
    taller que tienen la sección Compras habilitada (o acceso completo). Antes
    solo dejaba pasar a los dos primeros: al de taller con la sección le
    aparecía en el menú, entraba y la pantalla le contestaba "Sin permiso"."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "usuario_id" not in session:
            return jsonify({"error": "No autenticado", "login": True}), 401
        rol = session.get("rol")
        if rol == "taller":
            from database import secciones_de_usuario
            secs = secciones_de_usuario(session.get("usuario_id"))
            if secs and "compras" not in secs:
                return jsonify({"error": "No tenés habilitada la sección Compras"}), 403
        elif rol not in ("admin", "compras"):
            return jsonify({"error": "Sin permiso para esta acción"}), 403
        return f(*args, **kwargs)
    return wrapper


# Rutas que NO requieren login
RUTAS_PUBLICAS = {"/login", "/api/login", "/static"}

def _puede_borrar_ots_sesion():
    try:
        from database import puede_borrar_ots
        return puede_borrar_ots(session.get("usuario_id"), session.get("rol"))
    except Exception:
        return session.get("rol") == "admin"


def _puede_editar_km_sesion():
    try:
        from database import puede_editar_km
        return puede_editar_km(session.get("usuario_id"), session.get("rol"))
    except Exception:
        return session.get("rol") in ("admin", "taller")


@app.route("/api/me/permisos", methods=["GET"])
def api_mis_permisos():
    """Permisos de acción del usuario, leídos de la base al momento (si el
    administrador se los cambia, rigen sin volver a entrar)."""
    return jsonify({"borra_ots": _puede_borrar_ots_sesion(), "edita_km": _puede_editar_km_sesion()})


@app.before_request
def proteger_rutas():
    """Exige login para todo, excepto las rutas públicas y archivos estáticos."""
    p = request.path
    if p == "/login" or p == "/api/login":
        return None
    if p.startswith("/static/"):
        return None
    if "usuario_id" not in session:
        if p.startswith("/api/"):
            return jsonify({"error": "No autenticado", "login": True}), 401
        return redirect(url_for("login_page"))

    # El chofer SOLO puede acceder a su pantalla y sus endpoints (seguridad).
    if session.get("rol") == "chofer":
        permitido = (
            p == "/" or p == "/chofer" or
            p.startswith("/api/chofer/") or
            p == "/api/logout"
        )
        if not permitido:
            if p.startswith("/api/"):
                return jsonify({"error": "Sin permiso"}), 403
            return redirect(url_for("pantalla_chofer"))

    # Usuario de taller con acceso solo a algunas secciones: se leen de la
    # base en cada pedido (si el admin se las cambia, rige al toque) y el
    # servidor le niega las rutas de los módulos que no tiene. Ocultar el
    # botón del menú no alcanza: los datos se pueden pedir directo.
    if session.get("rol") == "taller":
        from database import secciones_de_usuario
        from permisos import ruta_permitida
        secs = secciones_de_usuario(session.get("usuario_id"))
        session["secciones"] = secs
        if not ruta_permitida(p, secs):
            if p.startswith("/api/"):
                return jsonify({"error": "No tenés acceso a esta sección"}), 403
            return redirect("/")

    # El auditor consulta, no modifica: se le bloquean los endpoints que
    # escriben, aunque llegue por fuera de la pantalla.
    if session.get("rol") == "auditor" and request.method in ("POST", "PUT", "PATCH", "DELETE"):
        permitidos_auditor = (p == "/api/logout" or p.startswith("/api/combustible")
                              # salvo que se le haya habilitado corregir el km
                              or (re.fullmatch(r"/api/ots/\d+/(km|conductor)", p) is not None and _puede_editar_km_sesion()))
        if not permitidos_auditor:
            return jsonify({"error": "El rol auditor no puede modificar datos"}), 403

    # La agencia de pasajes: solo la boletería (Alpha). Todo lo demás del
    # sistema (flota, taller, tráfico, choferes, tarifas) le queda cerrado
    # también en el servidor, no solo en la pantalla.
    if session.get("rol") == "agencia":
        permitido = (
            p in ("/", "/boleteria", "/api/logout") or
            p.startswith("/api/alpha/")       # cada ruta de Alpha controla qué puede la agencia
        )
        if not permitido:
            if p.startswith("/api/"):
                return jsonify({"error": "Sin permiso"}), 403
            return redirect("/boleteria")

    # El chofer de corporativos: solo su pantalla de rendiciones (celular).
    if session.get("rol") == "chofer_corp":
        permitido = (
            p == "/" or p == "/corp" or
            p.startswith("/api/corp/") or
            p.startswith("/static/") or
            p == "/api/logout" or p == "/api/me" or
            p.startswith("/api/vehiculos")  # buscador de bus por Nº interno
        )
        if not permitido:
            if p.startswith("/api/"):
                return jsonify({"error": "Sin permiso"}), 403
            return redirect(url_for("pantalla_corp"))

    # El gerente: solo su panel, y solo para mirar. Cualquier pedido que
    # escriba se rechaza, aunque llegue por fuera de la pantalla.
    if session.get("rol") == "gerente":
        if request.method not in ("GET", "HEAD") and p != "/api/logout":
            return jsonify({"error": "El panel del gerente es de solo lectura"}), 403
        permitido = (
            p in ("/", "/gerencia", "/api/logout", "/api/me", "/api/usuario_actual") or
            p.startswith("/api/gerencia/")
        )
        if not permitido:
            if p.startswith("/api/"):
                return jsonify({"error": "Sin permiso"}), 403
            return redirect("/gerencia")

    # Contabilidad: acceso aislado al módulo financiero. No alcanza con ocultar el menú;
    # también se bloquean por servidor las rutas operativas de flota/taller/compras.
    if session.get("rol") == "contabilidad":
        permitido = (
            p in ("/", "/contabilidad", "/api/logout", "/api/me", "/api/me/permisos", "/api/usuario_actual")
            or p.startswith("/api/contabilidad/")
            or p.startswith("/static/")
        )
        if not permitido:
            if p.startswith("/api/"):
                return jsonify({"error": "Tu usuario solo tiene acceso al módulo de Contabilidad"}), 403
            return redirect("/contabilidad")

    # El rol Compras accede a la app principal pero solo a sus endpoints + lectura básica.
    if session.get("rol") == "compras":
        permitido = (
            p == "/" or
            p.startswith("/api/compras/") or
            p.startswith("/api/cajas") or        # cajas: débitos y créditos varios
            p.startswith("/static/") or
            p == "/api/logout" or p == "/api/me" or p == "/api/me/permisos" or
            p.startswith("/api/ots") or          # ver y CREAR OTs (compras carga las órdenes)
            p.startswith("/api/ot_items") or     # asignar el técnico y anotar el material
            p.startswith("/api/personal") or     # el personal de taller (números para la OT)
            p.startswith("/api/vehiculos") or    # lista de coches para el formulario de OT
            p.startswith("/api/repuestos") or    # inventario del depósito (reponer stock)
            p.startswith("/api/historial_carga") or  # carga de historial retroactivo
            p == "/api/dashboard"
        )
        if not permitido:
            if p.startswith("/api/"):
                return jsonify({"error": "Sin permiso"}), 403
            return redirect(url_for("index"))
    return None



# ─── Páginas ──────────────────────────────────────────────────────────────────

def version_assets():
    """
    Genera un número de versión para los archivos estáticos (CSS/JS) basado en
    la fecha de modificación más reciente. Así, cada vez que se sube un archivo
    nuevo, el número cambia solo y el navegador carga la versión nueva
    automáticamente, sin que nadie tenga que limpiar el caché.
    """
    try:
        archivos = [
            os.path.join(app.static_folder, "style.css"),
            os.path.join(app.static_folder, "app.js"),
            os.path.join(app.static_folder, "alpha.js"),
            os.path.join(app.static_folder, "alpha.css"),
            os.path.join(app.static_folder, "controles.js"),
            os.path.join(app.static_folder, "gerencia.js"),
            os.path.join(app.static_folder, "gerencia.css"),
            os.path.join(app.static_folder, "contabilidad.css"),
        ]
        ultima = max(os.path.getmtime(a) for a in archivos if os.path.exists(a))
        return str(int(ultima))  # timestamp como número de versión
    except Exception:
        return "1"


@app.route("/")
@login_requerido
def index():
    if session.get("rol") == "contabilidad":
        return redirect("/contabilidad")
    # Los choferes ven solo su pantalla simple de carga de OT
    if session.get("rol") == "chofer":
        return redirect(url_for("pantalla_chofer"))
    if session.get("rol") == "chofer_corp":
        return redirect(url_for("pantalla_corp"))
    if session.get("rol") == "agencia":
        return redirect("/boleteria")
    if session.get("rol") == "gerente":
        return redirect("/gerencia")
    html = render_template("index.html",
                           usuario=session.get("nombre") or session.get("usuario"),
                           rol=session.get("rol"),
                           secciones=(session.get("secciones") or []
                                      if session.get("rol") == "taller" else []),
                           borra_ots=_puede_borrar_ots_sesion(),
                           v=version_assets())
    resp = make_response(html)
    # El HTML NUNCA se cachea: siempre se pide fresco, así trae la versión
    # correcta de CSS/JS. Los archivos estáticos sí se cachean pero con el ?v=.
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.route("/boleteria")
@login_requerido
def pantalla_boleteria():
    """La boletería de una agencia: solo Alpha (vender, sus pasajes y su caja).
    Administración también puede abrirla para ver lo mismo que ve la agencia."""
    if session.get("rol") not in ("agencia", "admin"):
        return redirect("/")
    html = render_template("boleteria.html",
                           usuario=session.get("nombre") or session.get("usuario"),
                           rol=session.get("rol"), agencia=session.get("agencia") or "",
                           v=version_assets())
    resp = make_response(html)
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.route("/gerencia")
@login_requerido
def pantalla_gerencia():
    """El panel del gerente: cómo viene el día y la plata del mes, en una
    sola pantalla para la compu o el celular. Administración también la abre."""
    from gerencia import puede_ver
    if not puede_ver():
        return redirect("/")
    html = render_template("gerencia.html",
                           usuario=session.get("nombre") or session.get("usuario"),
                           rol=session.get("rol"), v=version_assets())
    resp = make_response(html)
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.route("/chofer")
@login_requerido
def pantalla_chofer():
    """Pantalla simplificada para que el chofer cargue su reporte/OT."""
    html = render_template("chofer.html",
                           usuario=session.get("nombre") or session.get("usuario"))
    resp = make_response(html)
    # Forzar que el navegador (sobre todo Safari/iPhone) no use caché viejo
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.route("/corp")
@login_requerido
def pantalla_corp():
    """Pantalla de celular para que el chofer de corporativos cargue rendiciones."""
    html = render_template("corp.html",
                           usuario=session.get("nombre") or session.get("usuario"),
                           v=version_assets())
    resp = make_response(html)
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.route("/api/corp/seed", methods=["POST"])
@rol_requerido("admin")
def api_corp_seed():
    """Da de alta a los 31 choferes de corporativos (usuario=nombre, pass=nombre).
    Idempotente: los que ya existen se saltean."""
    from corporativos import seed_choferes_corp
    res = seed_choferes_corp()
    auditar(f"Ejecutó el alta de choferes corporativos ({res['creados']} nuevos)",
            "Corporativos", f"{res['saltados']} ya existían")
    return jsonify({"ok": True, **res})


@app.route("/tablero")
@login_requerido
def pantalla_tablero():
    """Pantalla de monitoreo tipo McDonald's para mostrar en una tele.
    Muestra el estado de las OTs activas, identificadas por número de coche."""
    html = render_template("tablero.html")
    resp = make_response(html)
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.route("/api/tablero")
@login_requerido
def api_tablero():
    """Datos para la pantalla de monitoreo: OTs activas (no cerradas) con sus estados.
    Ordenadas por urgencia de horario de salida (el que sale antes, primero)."""
    from database import _orden_urgencia_horario
    todas = obtener_ots()
    activas = [o for o in todas if o.get("estado") != "cerrada"]
    # Ordenar por horario de salida: el más urgente (sale antes) primero
    activas.sort(key=_orden_urgencia_horario)
    return jsonify({"ots": activas, "actualizado": ahora().strftime("%H:%M:%S")})


@app.route("/login", methods=["GET"])
def login_page():
    if "usuario_id" in session:
        return redirect(url_for("index"))
    return render_template("login.html")


@app.route("/api/login", methods=["POST"])
def api_login():
    d = request.json or {}
    usuario = d.get("usuario", "")
    password = d.get("password", "")
    u = autenticar_usuario(usuario, password)
    if u:
        session["usuario_id"] = u["id"]
        session["usuario"] = u["usuario"]
        session["nombre"] = u["nombre"]
        session["rol"] = u["rol"]
        session["secciones"] = u.get("secciones") or []
        session["agencia_id"] = u.get("agencia_id")
        session["agencia"] = ""
        if u["rol"] == "agencia" and u.get("agencia_id"):
            try:
                from db_compat import get_connection as _gc
                _c = _gc()
                _r = _c.execute("SELECT nombre FROM agencias WHERE id=?", (u["agencia_id"],)).fetchone()
                _c.close()
                session["agencia"] = (_r["nombre"] if _r else "") or ""
            except Exception:
                pass
        # Sesión NO permanente: se cierra al cerrar el navegador (más seguro)
        session.permanent = False
        auditar("Inició sesión", "Acceso")
        return jsonify({"ok": True, "usuario": u})
    # Registrar intento fallido (sin sesión, lo hacemos directo)
    registrar_auditoria(usuario=usuario or "?", rol="", accion="Intento de acceso fallido",
                        categoria="Acceso", detalle="Usuario o contraseña incorrectos")
    return jsonify({"ok": False, "msg": "Usuario o contraseña incorrectos"}), 401


@app.route("/api/logout", methods=["POST"])
def api_logout():
    auditar("Cerró sesión", "Acceso")
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/usuario_actual", methods=["GET"])
def api_usuario_actual():
    if "usuario_id" in session:
        return jsonify({
            "usuario": session.get("usuario"),
            "nombre": session.get("nombre"),
            "rol": session.get("rol"),
        })
    return jsonify({"error": "No autenticado"}), 401


# ─── API: Gestión de usuarios (solo admin) ────────────────────────────────────

@app.route("/api/usuarios", methods=["GET"])
@rol_requerido("admin")
def api_usuarios():
    return jsonify(obtener_usuarios())


@app.route("/api/usuarios", methods=["POST"])
@rol_requerido("admin")
def api_crear_usuario():
    d = request.json or {}
    if not d.get("usuario") or not d.get("password"):
        return jsonify({"ok": False, "msg": "Usuario y contraseña obligatorios"}), 400
    if d.get("rol") == "agencia" and not str(d.get("agencia_id") or "").isdigit():
        return jsonify({"ok": False, "msg": "Elegí a qué agencia pertenece"}), 400
    ok, msg = crear_usuario(d["usuario"], d["password"],
                            d.get("nombre", ""), d.get("rol", "taller"),
                            d.get("secciones") or [], d.get("agencia_id"))
    if ok:
        from permisos import normalizar
        secs = normalizar(d.get("secciones") or []) if d.get("rol", "taller") == "taller" else []
        auditar(f"Creó el usuario '{d['usuario']}'", "Usuarios",
                f"Rol: {d.get('rol','taller')}"
                + (f" · secciones: {', '.join(secs)}" if secs else ""))
    return jsonify({"ok": ok, "msg": msg})


@app.route("/api/permisos/secciones", methods=["GET"])
@rol_requerido("admin")
def api_catalogo_secciones():
    """Las secciones que se pueden habilitar, agrupadas como el menú."""
    from permisos import GRUPOS_SECCIONES
    return jsonify([{"grupo": g, "secciones": [{"clave": k, "nombre": n} for k, n in secs]}
                    for g, secs in GRUPOS_SECCIONES])


@app.route("/api/usuarios/<int:uid>", methods=["PATCH"])
@rol_requerido("admin")
def api_actualizar_usuario(uid):
    d = request.json or {}

    # Frenos para no quedarse afuera del sistema:
    nuevo_rol = d.get("rol")
    if nuevo_rol == "agencia" and not str(d.get("agencia_id") or "").isdigit():
        return jsonify({"ok": False, "msg": "Elegí a qué agencia pertenece"}), 400
    if nuevo_rol and nuevo_rol != "admin":
        if uid == session.get("usuario_id"):
            return jsonify({"ok": False,
                            "msg": "No podés sacarte a vos mismo el rol de administrador."}), 400
        from database import contar_admins_activos
        if contar_admins_activos(excluir=uid) == 0:
            return jsonify({"ok": False,
                            "msg": "Es el único administrador activo. Nombrá otro antes de cambiarle el rol."}), 400
    if d.get("activo") == 0 and uid == session.get("usuario_id"):
        return jsonify({"ok": False,
                        "msg": "No podés desactivar tu propio usuario."}), 400

    actualizar_usuario(uid, **d)

    # Si se corrigió el nombre, hay que actualizarlo también en las rendiciones
    # ya cargadas: ahí queda guardado el nombre con el que se registró cada
    # servicio, y si no se sincroniza, los PDF y las liquidaciones siguen
    # mostrando el nombre viejo.
    nuevo_nombre = (d.get("nombre") or "").strip()
    filas_corp = 0
    if nuevo_nombre:
        try:
            from db_compat import get_connection
            conn = get_connection()
            u = conn.execute("SELECT usuario FROM usuarios WHERE id=?", (uid,)).fetchone()
            if u:
                filas_corp = conn.execute(
                    "SELECT COUNT(*) AS c FROM rendiciones_corp WHERE chofer_usuario=?",
                    (u["usuario"],)).fetchone()["c"]
                if filas_corp:
                    conn.execute("""UPDATE rendiciones_corp SET chofer_nombre=?
                                    WHERE chofer_usuario=?""", (nuevo_nombre, u["usuario"]))
                    conn.commit()
            conn.close()
        except Exception:
            pass

    detalle = ""
    if nuevo_rol:
        detalle = f"rol: {nuevo_rol}"
    elif "secciones" in d:
        from permisos import normalizar
        secs = normalizar(d.get("secciones") or [])
        detalle = "secciones: " + (", ".join(secs) if secs else "acceso completo")
    elif nuevo_nombre:
        detalle = f"nombre: {nuevo_nombre}"
    elif "borra_ots" in d:
        detalle = "puede eliminar OTs: " + ("sí" if d.get("borra_ots") in (1, True, "1", "true") else "no")
    elif "edita_km" in d:
        detalle = "puede corregir el km: " + ("sí" if d.get("edita_km") in (1, True, "1", "true") else "no")
    auditar(f"Modificó un usuario (ID {uid})", "Usuarios", detalle)
    msg = "Usuario actualizado."
    if filas_corp:
        msg += f" Se corrigió el nombre en {filas_corp} rendición(es) ya cargada(s)."
    return jsonify({"ok": True, "msg": msg})


@app.route("/api/usuarios/<int:uid>", methods=["DELETE"])
@rol_requerido("admin")
def api_eliminar_usuario(uid):
    if uid == session.get("usuario_id"):
        return jsonify({"ok": False, "msg": "No podés eliminar tu propio usuario"}), 400
    eliminar_usuario(uid)
    auditar(f"Eliminó un usuario (ID {uid})", "Usuarios")
    return jsonify({"ok": True})


@app.route("/api/cargar_flota_inicial", methods=["POST"])
@rol_requerido("admin")
def api_cargar_flota_inicial():
    """
    Carga la flota desde el Excel. Acepta parámetro 'paso':
      - 'vehiculos' (default): carga solo los vehículos + planes
      - 'documentos': carga los documentos (seguros, habilitaciones)
    Separado en pasos para no exceder el tiempo límite en la nube.
    """
    d = request.json or {}
    paso = d.get("paso", "vehiculos")

    # Buscar el Excel en la carpeta
    nombres_posibles = [
        "FLOTA_SANTANIANA_GENERAL_LS-_HABILITACIONES_V_E_2026_.xlsx.xlsx",
        "FLOTA_SANTANIANA_GENERAL_LS-_HABILITACIONES_V_E_2026_.xlsx",
        "FLOTA SANTANIANA GENERAL LS- HABILITACIONES V.E 2026 .xlsx",
        "flota.xlsx",
    ]
    ruta = None
    for n in nombres_posibles:
        if os.path.exists(n):
            ruta = n
            break
    if not ruta:
        for f in os.listdir("."):
            if f.lower().endswith(".xlsx"):
                ruta = f
                break

    if not ruta:
        return jsonify({"ok": False, "msg": "No se encontró el archivo Excel de la flota en el servidor. Subilo al repositorio."}), 404

    try:
        if paso == "documentos":
            from flota_seed import cargar_documentos_desde_xlsx
            antes_docs = len(obtener_documentos())
            cargar_documentos_desde_xlsx(ruta, verbose=False)
            despues_docs = len(obtener_documentos())
            return jsonify({"ok": True,
                "msg": f"Documentos cargados: {despues_docs - antes_docs} nuevos.",
                "creados": despues_docs - antes_docs, "total_docs": despues_docs})
        else:
            from flota_seed import cargar_flota_desde_xlsx
            antes = len(obtener_vehiculos(solo_activos=False))
            cargar_flota_desde_xlsx(ruta, verbose=False)
            despues = len(obtener_vehiculos(solo_activos=False))
            # Asignar configuración de neumáticos automática por ejes (para verificar)
            try:
                asignar_configs_automaticas()
            except Exception:
                pass
            return jsonify({"ok": True,
                "msg": f"Vehículos: {despues} en total ({despues - antes} nuevos).",
                "creados": despues - antes, "total": despues})
    except Exception as e:
        return jsonify({"ok": False, "msg": f"Error al cargar: {str(e)}"}), 500


# ─── API: Vehículos ───────────────────────────────────────────────────────────

@app.route("/api/vehiculos", methods=["GET"])
@login_requerido
def api_vehiculos():
    return jsonify(obtener_vehiculos())


@app.route("/api/vehiculos", methods=["POST"])
def api_agregar_vehiculo():
    d = request.json
    año = d.get("año")
    ok, msg = agregar_vehiculo(
        d.get("patente", ""),
        d.get("marca", ""),
        d.get("modelo", ""),
        int(año) if año and str(año).isdigit() else None,
        chasis=d.get("chasis", ""),
        n_interno=d.get("n_interno", ""),
        asientos=int(d.get("asientos") or 0),
        ejes=int(d.get("ejes") or 0),
        tipo=d.get("tipo", ""),
    )
    # Si se creó y vino un plan, asignar automáticamente
    if ok and d.get("plan_id"):
        try:
            from database import obtener_vehiculos as _ov
            v = next((x for x in _ov() if x["patente"] == d.get("patente", "").upper().strip()), None)
            if v:
                km_inicial = float(d.get("km_inicial", 0) or 0)
                asignar_plan(v["id"], int(d["plan_id"]), km_inicial)
        except Exception as e:
            print(f"Aviso: no se pudo asignar plan: {e}")
    return jsonify({"ok": ok, "msg": msg})


@app.route("/api/vehiculos/<int:vid>", methods=["PATCH"])
def api_actualizar_vehiculo(vid):
    d = request.json or {}
    # Solo campos válidos
    permitidos = {"patente", "marca", "modelo", "año", "chasis",
                  "n_interno", "asientos", "ejes", "tipo"}
    campos = {k: v for k, v in d.items() if k in permitidos}
    if not campos:
        return jsonify({"ok": False, "msg": "Sin campos para actualizar"}), 400
    try:
        # Convertir tipos numéricos
        if "año" in campos and campos["año"]:
            campos["año"] = int(campos["año"])
        if "asientos" in campos:
            campos["asientos"] = int(campos["asientos"] or 0)
        if "ejes" in campos:
            campos["ejes"] = int(campos["ejes"] or 0)
        actualizar_vehiculo(vid, **campos)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 400


@app.route("/api/vehiculos/<int:vid>", methods=["DELETE"])
def api_eliminar_vehiculo(vid):
    eliminar_vehiculo(vid)
    return jsonify({"ok": True})


# La carga manual de servicios por coche se reemplazó por la sección Servicios
# (servicios.py), que sale directo del Tráfico. Lo cargado a mano antes sigue
# en la base y lo siguen usando los KPIs por coche.

@app.route("/api/meses/<int:vid>", methods=["GET"])
def api_meses(vid):
    return jsonify(meses_con_servicios(vid))


# ─── API: Costos ──────────────────────────────────────────────────────────────

@app.route("/api/costos/<int:vid>", methods=["GET"])
def api_costos(vid):
    return jsonify(obtener_costos(vid))


@app.route("/api/costos", methods=["POST"])
def api_agregar_costo():
    d = request.json
    try:
        agregar_costo(
            int(d["vehiculo_id"]), d["mes"], d["tipo"],
            d.get("concepto", ""), float(d.get("monto", 0) or 0)
        )
        return jsonify({"ok": True})
    except (KeyError, ValueError) as e:
        return jsonify({"ok": False, "msg": str(e)}), 400


@app.route("/api/costos/<int:cid>", methods=["DELETE"])
def api_eliminar_costo(cid):
    eliminar_costo(cid)
    return jsonify({"ok": True})


# ─── API: KPIs ────────────────────────────────────────────────────────────────

@app.route("/api/kpis/<int:vid>", methods=["GET"])
def api_kpis(vid):
    modo = request.args.get("modo", "mes")
    if modo == "produccion":
        k = kpis_produccion(vid)
    else:
        mes = request.args.get("mes")
        if not mes:
            meses = meses_con_servicios(vid)
            mes = meses[0] if meses else None
        k = kpis_mes(vid, mes) if mes else None
    return jsonify(k or {})


@app.route("/api/resumen_mensual/<int:vid>", methods=["GET"])
def api_resumen_mensual(vid):
    return jsonify(resumen_por_mes(vid))


# ─── API: Mantenimiento ───────────────────────────────────────────────────────

@app.route("/api/planes", methods=["GET"])
def api_planes():
    return jsonify(obtener_planes())


@app.route("/api/planes", methods=["POST"])
def api_crear_plan():
    d = request.json
    ok, res = crear_plan(d.get("nombre", ""), d.get("descripcion", ""))
    return jsonify({"ok": ok, "id" if ok else "msg": res})


@app.route("/api/planes/<int:pid>", methods=["DELETE"])
def api_eliminar_plan(pid):
    ok, msg = eliminar_plan(pid)
    return jsonify({"ok": ok, "msg": msg})


@app.route("/api/planes/<int:pid>/tareas", methods=["GET"])
def api_tareas_plan(pid):
    return jsonify(obtener_tareas_plan(pid))


@app.route("/api/planes/<int:pid>/tareas", methods=["POST"])
def api_agregar_tarea(pid):
    d = request.json
    try:
        agregar_tarea(pid, d.get("tarea", ""), int(d.get("intervalo_km", 0)),
                      d.get("categoria", ""))
        return jsonify({"ok": True})
    except (ValueError, KeyError) as e:
        return jsonify({"ok": False, "msg": str(e)}), 400


@app.route("/api/tareas/<int:tid>", methods=["DELETE"])
def api_eliminar_tarea(tid):
    eliminar_tarea(tid)
    return jsonify({"ok": True})


@app.route("/api/vehiculos/<int:vid>/plan", methods=["GET"])
def api_plan_vehiculo(vid):
    plan = obtener_plan_vehiculo(vid)
    from database import km_verificacion
    return jsonify({
        "plan": plan,
        "km_actual": km_actual_vehiculo(vid),
        "km_verif": km_verificacion(vid),
    })


@app.route("/api/vehiculos/<int:vid>/plan", methods=["POST"])
def api_asignar_plan(vid):
    d = request.json
    asignar_plan(vid, int(d["plan_id"]), float(d.get("km_inicial", 0)))
    return jsonify({"ok": True})


@app.route("/api/vehiculos/<int:vid>/plan", methods=["DELETE"])
def api_desasignar_plan(vid):
    desasignar_plan(vid)
    return jsonify({"ok": True})


@app.route("/api/vehiculos/<int:vid>/mantenimientos", methods=["GET"])
def api_historial(vid):
    return jsonify(obtener_historial_mantenimiento(vid))


@app.route("/api/mantenimientos", methods=["POST"])
def api_registrar_mantenimiento():
    d = request.json
    try:
        registrar_mantenimiento(
            int(d["vehiculo_id"]), int(d["tarea_plan_id"]),
            d["fecha"], float(d["km"]),
            float(d.get("costo", 0) or 0),
            d.get("observaciones", "")
        )
        return jsonify({"ok": True})
    except (KeyError, ValueError) as e:
        return jsonify({"ok": False, "msg": str(e)}), 400


@app.route("/api/mantenimientos/<int:mid>", methods=["DELETE"])
def api_eliminar_mantenimiento(mid):
    eliminar_mantenimiento(mid)
    return jsonify({"ok": True})


@app.route("/api/vehiculos/<int:vid>/estado_mantenimiento", methods=["GET"])
def api_estado_mantenimiento(vid):
    estado = estado_mantenimiento(vid)
    return jsonify({"estado": estado, "km_actual": km_actual_vehiculo(vid)})


@app.route("/api/vehiculos/<int:vid>/plan_pdf", methods=["GET"])
def api_plan_preventivo_pdf(vid):
    """Exporta el plan de mantenimiento preventivo de un vehículo a PDF (con barras)."""
    # Datos del vehículo
    vehiculo = next((v for v in obtener_vehiculos(solo_activos=False) if v["id"] == vid), None)
    if not vehiculo:
        return jsonify({"ok": False, "msg": "Vehículo no encontrado"}), 404
    plan = obtener_plan_vehiculo(vid) or {}
    tareas = estado_mantenimiento(vid) or []
    try:
        import plan_preventivo
        ficha = plan_preventivo.ficha_coche(vid) or {}
        plan["km_dia"] = ficha.get("km_dia")
        plan["turno"] = ficha.get("turno")
    except Exception:
        pass
    os.makedirs("reportes", exist_ok=True)
    patente = vehiculo.get("patente", str(vid))
    ruta = f"reportes/Plan_Preventivo_{patente}.pdf"
    generar_plan_preventivo_pdf(vehiculo, plan, tareas, ruta)
    return send_file(ruta, as_attachment=True, download_name=f"Plan_Preventivo_{patente}.pdf")


# ─── API: Dashboard ───────────────────────────────────────────────────────────

@app.route("/api/dashboard", methods=["GET"])
def api_dashboard():
    return jsonify(dashboard_resumen())


# ─── API: Correctivos ────────────────────────────────────────────────────────

@app.route("/api/correctivos_por_ot", methods=["GET"])
@login_requerido
def api_correctivos_por_ot():
    """Devuelve los items correctivos agrupados por su OT."""
    desde = request.args.get("desde")
    hasta = request.args.get("hasta")
    return jsonify(obtener_correctivos_por_ot(desde=desde, hasta=hasta))


@app.route("/api/correctivos", methods=["GET"])
def api_correctivos_todos():
    estado = request.args.get("estado")
    vid = request.args.get("vehiculo_id", type=int)
    return jsonify(obtener_correctivos(vehiculo_id=vid, estado=estado))


@app.route("/api/correctivos", methods=["POST"])
def api_agregar_correctivo():
    d = request.json
    try:
        agregar_correctivo(
            int(d["vehiculo_id"]), d["fecha"], float(d.get("km", 0) or 0),
            d["tipo_falla"], d["descripcion"],
            d.get("reparacion", ""), float(d.get("costo", 0) or 0),
            d.get("taller", ""), d.get("estado", "pendiente")
        )
        return jsonify({"ok": True})
    except (KeyError, ValueError) as e:
        return jsonify({"ok": False, "msg": str(e)}), 400


@app.route("/api/correctivos/<int:cid>", methods=["PATCH"])
def api_actualizar_correctivo(cid):
    d = request.json or {}
    actualizar_correctivo(cid, **d)
    return jsonify({"ok": True})


@app.route("/api/correctivos/<int:cid>", methods=["DELETE"])
def api_eliminar_correctivo(cid):
    eliminar_correctivo(cid)
    return jsonify({"ok": True})


# ─── API: Documentos ─────────────────────────────────────────────────────────

@app.route("/api/documentos", methods=["GET"])
def api_documentos_todos():
    vid = request.args.get("vehiculo_id", type=int)
    return jsonify(obtener_documentos(vehiculo_id=vid))


@app.route("/api/documentos", methods=["POST"])
def api_agregar_documento():
    d = request.json
    try:
        agregar_documento(
            int(d["vehiculo_id"]), d["tipo"], d["fecha_vencimiento"],
            d.get("nombre", ""), d.get("fecha_emision"),
            d.get("proveedor", ""), float(d.get("costo", 0) or 0),
            d.get("observaciones", "")
        )
        return jsonify({"ok": True})
    except (KeyError, ValueError) as e:
        return jsonify({"ok": False, "msg": str(e)}), 400


@app.route("/api/documentos/<int:did>", methods=["PATCH"])
def api_actualizar_documento(did):
    d = request.json or {}
    actualizar_documento(did, **d)
    return jsonify({"ok": True})


@app.route("/api/documentos/<int:did>/renovar", methods=["POST"])
@rol_requerido("admin", "taller")
def api_renovar_documento(did):
    """Renueva un documento: crea el nuevo y archiva el anterior, para que el
    vencido deje de figurar en las alertas."""
    from database import renovar_documento
    d = request.json or {}
    venc = (d.get("fecha_vencimiento") or "").strip()
    if not venc:
        return jsonify({"ok": False, "msg": "Falta la nueva fecha de vencimiento."}), 400
    try:
        costo = float(str(d.get("costo", 0)).replace(".", "").replace(",", ".") or 0)
    except Exception:
        costo = 0
    ok, msg, nuevo_id = renovar_documento(
        did, venc, fecha_emision=d.get("fecha_emision") or None, costo=costo,
        proveedor=d.get("proveedor"), observaciones=d.get("observaciones"))
    if ok:
        auditar(f"Renovó un documento (ID {did})", "Documentos", msg)
    return jsonify({"ok": ok, "msg": msg, "id": nuevo_id}), (200 if ok else 400)


@app.route("/api/documentos/<int:did>/historial", methods=["GET"])
@login_requerido
def api_historial_documento(did):
    """Todas las renovaciones de ese documento, para ver qué se pagó cada año."""
    from database import historial_documento
    from db_compat import get_connection
    conn = get_connection()
    row = conn.execute("SELECT vehiculo_id, tipo FROM documentos WHERE id=?", (did,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "No encontrado"}), 404
    return jsonify(historial_documento(row["vehiculo_id"], row["tipo"]))


@app.route("/api/documentos/<int:did>", methods=["DELETE"])
def api_eliminar_documento(did):
    eliminar_documento(did)
    return jsonify({"ok": True})


# ─── API: Neumáticos ──────────────────────────────────────────────────────────

@app.route("/api/neumaticos", methods=["GET"])
def api_neumaticos():
    estado = request.args.get("estado")
    return jsonify(obtener_neumaticos(estado=estado))


@app.route("/api/neumaticos", methods=["POST"])
def api_agregar_neumatico():
    d = request.json
    try:
        ok, res = agregar_neumatico(
            d.get("codigo", ""), d.get("marca", ""), d.get("modelo", ""),
            d.get("medida", ""), d.get("dot", ""),
            d.get("fecha_compra"), float(d.get("costo_compra", 0) or 0),
            float(d.get("profundidad_mm", 0) or 0), d.get("observaciones", "")
        )
        return jsonify({"ok": ok, "id" if ok else "msg": res})
    except (KeyError, ValueError) as e:
        return jsonify({"ok": False, "msg": str(e)}), 400


@app.route("/api/neumaticos/<int:nid>", methods=["GET"])
def api_obtener_neumatico(nid):
    n = obtener_neumatico(nid)
    if not n:
        return jsonify({"error": "no encontrado"}), 404
    n["historial"] = historial_neumatico(nid)
    return jsonify(n)


@app.route("/api/neumaticos/<int:nid>", methods=["DELETE"])
def api_eliminar_neumatico(nid):
    ok, msg = eliminar_neumatico(nid)
    return jsonify({"ok": ok, "msg": msg})


@app.route("/api/neumaticos/<int:nid>/instalar", methods=["POST"])
def api_instalar(nid):
    d = request.json
    try:
        ok, msg = instalar_neumatico(
            nid, int(d["vehiculo_id"]), d["posicion"],
            d["fecha"], float(d.get("km_instalacion", 0) or 0)
        )
        return jsonify({"ok": ok, "msg": msg})
    except (KeyError, ValueError) as e:
        return jsonify({"ok": False, "msg": str(e)}), 400


@app.route("/api/neumaticos/<int:nid>/retirar", methods=["POST"])
def api_retirar(nid):
    d = request.json
    try:
        ok, msg = retirar_neumatico(
            nid, d["fecha_retiro"], float(d["km_retiro"]),
            d.get("motivo", ""), d.get("nuevo_estado", "disponible")
        )
        return jsonify({"ok": ok, "msg": msg})
    except (KeyError, ValueError) as e:
        return jsonify({"ok": False, "msg": str(e)}), 400


@app.route("/api/neumaticos/<int:nid>/rotar", methods=["POST"])
def api_rotar(nid):
    """Mueve un neumático de una posición a otra del mismo vehículo (drag entre ruedas)."""
    from database import rotar_neumatico
    d = request.json or {}
    try:
        ok, msg = rotar_neumatico(
            nid, int(d["vehiculo_id"]), d["nueva_posicion"],
            d.get("fecha", ""), float(d.get("km_vehiculo", 0) or 0)
        )
        return jsonify({"ok": ok, "msg": msg})
    except (KeyError, ValueError) as e:
        return jsonify({"ok": False, "msg": str(e)}), 400


@app.route("/api/vehiculos/<int:vid>/neumaticos", methods=["GET"])
def api_neumaticos_vehiculo(vid):
    """Devuelve estado completo de neumáticos del vehículo + configuración."""
    return jsonify(estado_neumaticos_vehiculo(vid) or {})


@app.route("/api/configs_neumaticos", methods=["GET"])
def api_configs_disponibles():
    """Lista de configuraciones de neumáticos disponibles para elegir."""
    from database import CONFIGS_DISPONIBLES, LABEL_CONFIG, POSICIONES_POR_CONFIG
    return jsonify([
        {"valor": c, "label": LABEL_CONFIG.get(c, c), "ruedas": len(POSICIONES_POR_CONFIG.get(c, []))}
        for c in CONFIGS_DISPONIBLES
    ])


@app.route("/api/vehiculos/<int:vid>/config_neumaticos", methods=["POST"])
def api_set_config_vehiculo(vid):
    """Cambia la configuración de neumáticos de ESTE vehículo (queda confirmada)."""
    d = request.json or {}
    cfg = d.get("configuracion")
    if not cfg:
        return jsonify({"ok": False, "msg": "Falta la configuración"}), 400
    guardar_config_vehiculo(vid, cfg, verificado=1)
    return jsonify({"ok": True})


@app.route("/api/asignar_configs_auto", methods=["POST"])
@rol_requerido("admin", "taller")
def api_asignar_configs_auto():
    """Asigna configs automáticas por ejes a los vehículos que no tengan (para verificar)."""
    n = asignar_configs_automaticas()
    return jsonify({"ok": True, "asignadas": n})


@app.route("/api/planes/<int:pid>/config_neumaticos", methods=["GET"])
def api_get_config_neu(pid):
    return jsonify(obtener_config_neumaticos_plan(pid) or {})


@app.route("/api/planes/<int:pid>/config_neumaticos", methods=["POST"])
def api_set_config_neu(pid):
    d = request.json
    try:
        crear_config_neumaticos(
            pid, d.get("configuracion", "6x2"), d.get("medida", ""),
            float(d.get("presion_dir", 110) or 110),
            float(d.get("presion_trac", 120) or 120),
            int(d.get("vida_util_km", 100000) or 100000)
        )
        return jsonify({"ok": True})
    except (KeyError, ValueError) as e:
        return jsonify({"ok": False, "msg": str(e)}), 400


# ─── API: Órdenes de Trabajo ──────────────────────────────────────────────────

@app.route("/api/ots", methods=["GET"])
def api_ots():
    estado = request.args.get("estado")
    vid = request.args.get("vehiculo_id", type=int)
    desde = request.args.get("desde")
    hasta = request.args.get("hasta")
    ots = obtener_ots(estado=estado, vehiculo_id=vid, desde=desde, hasta=hasta)
    if not vid:
        # Una fila por OT: los coches agregados van en la fila de la principal
        from ot_materiales import agrupar_lista
        ots = agrupar_lista(ots)
    # Lo que quedó pendiente de días anteriores, y por qué
    try:
        from ot_pendientes import marcar_atrasados
        marcar_atrasados(ots)
    except Exception:
        pass
    return jsonify(ots)


@app.route("/api/ots/<int:ot_id>", methods=["GET"])
def api_ot(ot_id):
    ot = obtener_ot(ot_id)
    if not ot:
        return jsonify({"error": "no encontrada"}), 404
    # Incluir las fotos (cantidad y datos) para mostrarlas en el taller
    ot["fotos"] = obtener_fotos_ot(ot_id, incluir_datos=True)
    # Kilometraje: lo que tiene el coche en el sistema y la última verificación
    from database import km_verificacion
    ot["km_coche"] = km_actual_vehiculo(ot["vehiculo_id"])
    ot["km_verif"] = km_verificacion(ot["vehiculo_id"])
    ot["puede_verificar_km"] = _puede_editar_km_sesion()
    ot["puede_corregir_chofer"] = ot["puede_verificar_km"]
    # El día de hoy (Paraguay): lo de días anteriores sin hacer va resaltado
    ot["hoy"] = hoy()
    # Los trabajos hechos afuera, con su factura
    try:
        from ot_afuera import marcar_items
        marcar_items(ot.get("items"))
    except Exception:
        pass
    return jsonify(ot)


@app.route("/api/ots/<int:ot_id>/conductor", methods=["POST"])
def api_corregir_conductor_ot(ot_id):
    """Corrige el nombre del chofer de la OT (si se cargó mal). Lo pueden hacer
    los mismos que corrigen el km: administración, taller y quien tenga
    habilitado "Corrige km y chofer" en el panel de Usuarios."""
    if not _puede_editar_km_sesion():
        return jsonify({"ok": False, "msg": "No tenés permiso para corregir el chofer"}), 403
    nombre = re.sub(r"\s+", " ", str((request.json or {}).get("conductor") or "")).strip()[:80]
    ot = obtener_ot(ot_id)
    if not ot:
        return jsonify({"ok": False, "msg": "La OT no existe."}), 404
    antes = (ot.get("conductor") or "").strip()
    if nombre == antes:
        return jsonify({"ok": True, "conductor": nombre})
    actualizar_ot(ot_id, conductor=nombre)
    auditar(f"Corrigió el chofer de la OT #{ot_id}", "Órdenes de Trabajo",
            f"Coche {ot.get('n_interno') or ot.get('patente')}: {antes or '(sin chofer)'} → {nombre or '(sin chofer)'}")
    return jsonify({"ok": True, "conductor": nombre})


@app.route("/api/ots/conductores", methods=["GET"])
def api_conductores_ot():
    """Los nombres de choferes ya usados (en OTs y en el tráfico), para
    elegirlos al escribir y no cargar el mismo chofer con otra letra."""
    from database import nombres_de_choferes
    return jsonify(nombres_de_choferes())


@app.route("/api/ots/<int:ot_id>/km", methods=["POST"])
def api_verificar_km_ot(ot_id):
    """El taller miró el tablero al abrir la OT y confirma o corrige el km.
    Esa lectura pasa a ser el km del coche (también para el Preventivo).
    Lo pueden hacer administración, taller y quien tenga habilitado
    "Corrige km" en el panel de Usuarios."""
    if not _puede_editar_km_sesion():
        return jsonify({"ok": False, "error": "No tenés permiso para corregir el kilometraje"}), 403
    from database import verificar_km_en_ot
    d = request.json or {}
    try:
        km = float(str(d.get("km", "")).replace(".", "").replace(",", ".") if isinstance(d.get("km"), str) else d.get("km"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "msg": "Poné el kilometraje en números."}), 400
    if km <= 0:
        return jsonify({"ok": False, "msg": "Poné el kilometraje del tablero."}), 400
    if km > 5_000_000:
        return jsonify({"ok": False, "msg": "Ese kilometraje no es posible: revisá el número."}), 400
    ot = obtener_ot(ot_id)
    if not ot:
        return jsonify({"ok": False, "msg": "La OT no existe."}), 404
    antes = km_actual_vehiculo(ot["vehiculo_id"])
    ok, res = verificar_km_en_ot(ot_id, km, session.get("nombre") or session.get("usuario") or "")
    if not ok:
        return jsonify({"ok": False, "msg": res}), 400
    auditar(f"Verificó el km en la OT #{ot_id}", "Órdenes de Trabajo",
            f"Coche {ot.get('n_interno') or ot.get('patente')}: {int(antes):,} → {int(km):,} km".replace(",", "."))
    return jsonify({"ok": True, "km_actual": res["km_actual"], "antes": antes})


@app.route("/api/ots", methods=["POST"])
@rol_requerido("admin", "taller", "compras")
def api_crear_ot():
    d = request.json
    try:
        import ot_unica
        from db_compat import get_connection as _gc
        # Los otros coches de la misma OT (cada uno con sus trabajos)
        extra, vistos = [], {int(d["vehiculo_id"])}
        for c in d.get("coches_extra") or []:
            try:
                vid = int(c.get("vehiculo_id"))
            except (TypeError, ValueError):
                continue
            if vid in vistos:
                return jsonify({"ok": False, "msg": "Hay un coche repetido en la OT."}), 400
            vistos.add(vid)
            extra.append((vid, float(c.get("km", 0) or 0), (c.get("conductor") or "").strip(), c.get("items") or []))
        conn = _gc()
        try:
            abierta = ot_unica.ot_abierta_de(conn, int(d["vehiculo_id"]))
        finally:
            conn.close()
        sumadas = []
        if abierta:
            # El coche ya tiene su OT abierta: los trabajos se suman ahí (con la
            # fecha de hoy) en vez de abrir otra
            ot_id = abierta
            ot_unica.agregar_items(ot_id, d.get("items", []), origen="taller",
                                   reportado_por=d.get("conductor", ""), fecha=d.get("fecha_apertura"))
            conn = _gc()
            try:
                ot_unica.subir_km(conn, ot_id, d.get("km"))
                conn.commit()
            finally:
                conn.close()
            sumadas.append(ot_id)
        else:
            ot_id = crear_ot(
                int(d["vehiculo_id"]), d["fecha_apertura"],
                km=float(d.get("km", 0) or 0),
                conductor=d.get("conductor", ""),
                procedencia=d.get("procedencia", ""),
                observaciones=d.get("observaciones", ""),
                items=d.get("items", [])
            )
        from ot_materiales import grupo_ids
        cabeza = (grupo_ids(ot_id) or [ot_id])[0]
        for vid, km, cond, its in extra:
            conn = _gc()
            try:
                otra = ot_unica.ot_abierta_de(conn, vid)
            finally:
                conn.close()
            if otra:
                # Ese coche también tiene su OT abierta: sus trabajos van ahí y,
                # si está suelta, esa OT pasa a ser parte de esta (varios coches)
                ot_unica.agregar_items(otra, its, origen="taller", reportado_por=cond, fecha=d.get("fecha_apertura"))
                conn = _gc()
                try:
                    ot_unica.sumar_al_grupo(conn, cabeza, otra)
                    conn.commit()
                finally:
                    conn.close()
                sumadas.append(otra)
                continue
            crear_ot(vid, d["fecha_apertura"], km=km, conductor=cond,
                     procedencia=d.get("procedencia", ""), observaciones=d.get("observaciones", ""),
                     items=its, ot_grupo=cabeza)
        n_items = len(d.get("items", [])) + sum(len(e[3]) for e in extra)
        auditar((f"Sumó trabajos a la OT #{cabeza}" if abierta else f"Creó la OT #{ot_id}"), "Órdenes de Trabajo",
                f"Vehículo ID {d.get('vehiculo_id')}"
                + (f" y {len(extra)} coche(s) más" if extra else "")
                + f", {n_items} trabajo(s), km {d.get('km','?')}"
                + (" · el coche ya tenía la OT abierta" if abierta else ""))
        return jsonify({"ok": True, "ot_id": ot_id, "numero": cabeza, "coches": 1 + len(extra),
                        "sumada": bool(abierta), "sumadas": sumadas})
    except (KeyError, ValueError) as e:
        return jsonify({"ok": False, "msg": str(e)}), 400


@app.route("/api/ots/abierta", methods=["GET"])
def api_ot_abierta():
    """La OT abierta de un coche (para avisar en 'Nueva OT' que se suma ahí)."""
    import ot_unica
    vid = request.args.get("vehiculo_id", type=int)
    if not vid:
        return jsonify(None)
    return jsonify(ot_unica.abierta(vid))


# ─── Endpoints para los CHOFERES ────────────────────────────────────────────
def _detectar_tipo_reporte(texto):
    """Detecta automáticamente el tipo de trabajo según lo que escribió el chofer.
    Así el chofer solo escribe el problema y el sistema lo clasifica.
    Prioridad: una falla (correctivo) gana aunque mencione otras palabras."""
    import re
    d = (texto or "").lower()

    # 1. CORRECTIVO tiene prioridad: si hay señal de falla/problema, es correctivo
    #    (aunque mencione "aceite" o "revisar", si algo está fallando es correctivo)
    falla = re.search(
        r"freno|fren[aá]|rotur|romp|roto|rota|fuga|p[eé]rdida|perd[ií]|fall|"
        r"no anda|no func|no arranc|no enciend|no frena|se apaga|ruido|golpe|"
        r"vibra|humo|calienta|recalent|temperatura|se prende la luz|luz del|"
        r"testigo|foco quemad|bater[ií]a|no carga|motor|caja|embrague|cloch|"
        r"patina|direcci[oó]n|suspensi[oó]n|amortig|escape|pastilla|disco|"
        r"averi|problema|anda mal|funciona mal|dura|duro|flojo|suelto", d)
    if falla:
        return "correctivo"

    # 2. Neumáticos
    if re.search(r"cubierta|neum[aá]tic|llanta|goma|trucky|reencauch|pinchad|"
                 r"pinch[oó]|rueda|aro|v[aá]lvula|presi[oó]n de aire", d):
        return "neumaticos"

    # 3. Preventivo / service programado
    if re.search(r"aceite|filtro|engrase|lubric|service|servís|grasa|correa|"
                 r"buj[ií]a|refrigerante|cambio de|mantenimiento program|"
                 r"service de|km|kil[oó]metr", d):
        return "preventivo"

    # 4. Control / revisión simple
    if re.search(r"revisar|revis[aá]|controlar|control|verificar|chequear|"
                 r"inspeccion|fijarse|mirar|ver si", d):
        return "control"

    return "otro"


@app.route("/api/chofer/vehiculos", methods=["GET"])
@login_requerido
def api_chofer_vehiculos():
    """Lista simple de vehículos para que el chofer elija el suyo."""
    vehiculos = obtener_vehiculos(solo_activos=True)
    # Solo lo necesario, ordenado por número de coche
    simple = [{
        "id": v["id"],
        "patente": v["patente"],
        "n_interno": v.get("n_interno", ""),
        "marca": v.get("marca", ""),
        "modelo": v.get("modelo", ""),
    } for v in vehiculos]
    simple.sort(key=lambda x: (str(x["n_interno"]) or "zzz", x["patente"]))
    return jsonify(simple)


@app.route("/api/chofer/en_taller", methods=["GET"])
@login_requerido
def api_chofer_en_taller():
    """Los coches que el taller tiene en la mano: OT abierta (con lo que falta
    hacer), esperando repuestos, fuera de servicio o con avisos que el taller
    todavía está revisando. Sirve para que el chofer sepa qué coche está
    parado y no vuelva a avisar algo que ya se sabe."""
    from db_compat import get_connection as _gc
    hoy_txt = hoy()
    conn = _gc()
    coches = {}

    def _coche(f):
        return coches.setdefault(f["vehiculo_id"], {
            "vehiculo_id": f["vehiculo_id"], "n_interno": f["n_interno"] or "",
            "patente": f["patente"] or "", "marca": f["marca"] or "",
            "estado": "pendiente", "desde": "", "ots": [], "trabajos": [],
            "hechos": 0, "repuestos": "", "fuera": None, "avisos": []})
    try:
        ots = [dict(r) for r in conn.execute("""
            SELECT o.id, o.ot_grupo, o.vehiculo_id, o.fecha_apertura, o.estado,
                   COALESCE(o.estado_compras, '') AS estado_compras,
                   v.patente, v.n_interno, v.marca
            FROM ordenes_trabajo o JOIN vehiculos v ON v.id = o.vehiculo_id
            WHERE o.estado <> 'cerrada' AND COALESCE(v.activo, 1) = 1""").fetchall()]
        items = {}
        if ots:
            marcas = ",".join("?" * len(ots))
            for r in conn.execute(f"""SELECT ot_id, descripcion, estado FROM ot_items
                                      WHERE ot_id IN ({marcas}) ORDER BY id""",
                                  [o["id"] for o in ots]).fetchall():
                items.setdefault(r["ot_id"], []).append(dict(r))
        for o in ots:
            c = _coche(o)
            c["ots"].append(o.get("ot_grupo") or o["id"])
            if not c["desde"] or (o["fecha_apertura"] or "") < c["desde"]:
                c["desde"] = o["fecha_apertura"] or ""
            for it in items.get(o["id"], []):
                if it["estado"] == "completado":
                    c["hechos"] += 1
                    continue
                igual = next((t for t in c["trabajos"] if t["txt"].strip().lower() == (it["descripcion"] or "").strip().lower()), None)
                if igual:  # el mismo trabajo anotado dos veces: se muestra una
                    if it["estado"] == "en_proceso":
                        igual["estado"] = "en_proceso"
                else:
                    c["trabajos"].append({"txt": it["descripcion"], "estado": it["estado"] or "pendiente"})
            if o["estado"] == "en_proceso" or any(it["estado"] == "en_proceso" for it in items.get(o["id"], [])):
                c["estado"] = "trabajando"
            if o["estado_compras"] in ("en_espera", "presupuestado", "en_camino"):
                c["repuestos"] = o["estado_compras"]

        for r in conn.execute("""
            SELECT f.vehiculo_id, f.fecha_desde, f.fecha_hasta, f.motivo,
                   v.patente, v.n_interno, v.marca
            FROM fuera_servicio f JOIN vehiculos v ON v.id = f.vehiculo_id
            WHERE f.fecha_desde <= ? AND (f.fecha_hasta IS NULL OR f.fecha_hasta = '' OR f.fecha_hasta >= ?)
            ORDER BY f.fecha_desde""", (hoy_txt, hoy_txt)).fetchall():
            c = _coche(dict(r))
            c["fuera"] = {"desde": r["fecha_desde"], "hasta": r["fecha_hasta"] or "", "motivo": r["motivo"] or ""}

        try:
            for r in conn.execute("""
                SELECT p.vehiculo_id, p.descripcion, v.patente, v.n_interno, v.marca
                FROM ot_pedidos p JOIN vehiculos v ON v.id = p.vehiculo_id
                WHERE p.estado = 'nuevo' ORDER BY p.id""").fetchall():
                c = _coche(dict(r))
                ya = {t["txt"].strip().lower() for t in c["trabajos"]} | {a.strip().lower() for a in c["avisos"]}
                if (r["descripcion"] or "").strip().lower() not in ya:
                    c["avisos"].append(r["descripcion"])
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
    finally:
        conn.close()

    orden = {"fuera": 0, "trabajando": 1, "repuestos": 2, "pendiente": 3, "aviso": 4}
    salida = []
    for c in coches.values():
        if c["fuera"]:
            c["estado"] = "fuera"
        elif c["estado"] != "trabajando" and c["repuestos"]:
            c["estado"] = "repuestos"
        elif not c["ots"]:
            c["estado"] = "aviso"
        elif c["estado"] == "pendiente" and not c["trabajos"] and not c["avisos"]:
            continue  # OT abierta pero ya con todo hecho: no hay nada que contar
        salida.append(c)

    def _num(c):
        n = str(c["n_interno"])
        return (0, int(n), "") if n.isdigit() else (1, 0, n or c["patente"])
    salida.sort(key=lambda c: (orden[c["estado"]], _num(c)))
    return jsonify({"coches": salida, "hoy": hoy_txt})


@app.route("/api/chofer/reportar", methods=["POST"])
@login_requerido
def api_chofer_reportar():
    """El chofer carga su reporte (solo escribe el problema).
    Si escribe varios problemas (uno por línea), se separan en items
    y cada uno se clasifica por separado automáticamente."""
    import datetime as _dt
    d = request.json or {}
    try:
        vehiculo_id = int(d["vehiculo_id"])
        descripcion = (d.get("descripcion") or "").strip()
        km = float(d.get("km", 0) or 0)
        if not descripcion:
            return jsonify({"ok": False, "msg": "Escribí qué le pasa al vehículo."}), 400

        # Separar el reporte en líneas: cada problema es un item con su propio tipo
        import re
        lineas = [l.strip() for l in descripcion.split("\n") if l.strip()]
        items = []
        for linea in lineas:
            # Sacar guiones, asteriscos, viñetas, números iniciales
            limpia = re.sub(r"^[-*•·\d\.\)]+\s*", "", linea).strip()
            if limpia:
                items.append({
                    "descripcion": limpia,
                    "tipo": _detectar_tipo_reporte(limpia),
                    "estado": "pendiente"
                })

        # Si no quedó ningún item (texto raro), usar todo como uno solo
        if not items:
            items = [{"descripcion": descripcion,
                      "tipo": _detectar_tipo_reporte(descripcion),
                      "estado": "pendiente"}]

        chofer = session.get("nombre") or session.get("usuario") or "Chofer"
        # No entra directo a la OT: queda como pedido para que los encargados
        # lo revisen, decidan si se hace y con qué prioridad
        import ot_pedidos
        fotos = [f for f in (d.get("fotos") or [])[:3] if f and len(f) < 800000]
        rid = ot_pedidos.crear_reporte(vehiculo_id, items, chofer, km=km, fotos=fotos)
        auditar(f"Chofer mandó un pedido de OT (#{rid})", "Reportes de chofer",
                f"{len(items)} problema(s), km {int(km):,}".replace(",", ".") + (f", {len(fotos)} foto(s)" if fotos else ""))
        return jsonify({"ok": True, "pedido": rid, "items": len(items), "fotos": len(fotos),
                        "msg": "¡Reporte enviado! El taller lo va a revisar."})
    except (KeyError, ValueError) as e:
        return jsonify({"ok": False, "msg": "Faltan datos: " + str(e)}), 400


@app.route("/api/chofer/mis_reportes", methods=["GET"])
@login_requerido
def api_chofer_mis_reportes():
    """Lo que reportó este chofer, por día y coche, con cómo va: en espera,
    en taller o resuelto. Como un coche tiene una sola OT abierta, el reporte
    puede haber quedado sumado a una OT que ya estaba."""
    from db_compat import get_connection as _gc
    chofer = session.get("nombre") or session.get("usuario") or "Chofer"
    # Los reportes nuevos son pedidos: cada problema con lo que decidió el taller
    import ot_pedidos
    pedidos = []
    for r in ot_pedidos.reportes_del_chofer(chofer):
        est = [p["estado"] for p in r["problemas"]]
        r["estado"] = ("en_revision" if "en_revision" in est else "en_taller" if "en_taller" in est
                       else "mas_adelante" if "mas_adelante" in est else "resuelto" if "resuelto" in est
                       else "no_se_hace")
        r["trabajos"] = len(est)
        r["orden"] = r.get("creado_el") or r["fecha"]
        pedidos.append(r)
    conn = _gc()
    try:
        filas = conn.execute("""
            SELECT i.ot_id, i.fecha, i.estado, o.estado AS estado_ot, v.patente, v.n_interno
            FROM ot_items i JOIN ordenes_trabajo o ON o.id = i.ot_id
            JOIN vehiculos v ON v.id = o.vehiculo_id
            WHERE i.origen = 'chofer' AND i.reportado_por = ?
              AND i.id NOT IN (SELECT item_id FROM ot_pedidos WHERE item_id IS NOT NULL)
            ORDER BY i.fecha DESC, i.id DESC
        """, (chofer,)).fetchall()
    finally:
        conn.close()
    grupos = {}
    for f in filas:
        k = (f["ot_id"], f["fecha"])
        g = grupos.setdefault(k, {"id": f["ot_id"], "fecha": f["fecha"], "patente": f["patente"],
                                  "n_interno": f["n_interno"], "estados": []})
        g["estados"].append(f["estado"])
        g["estado_ot"] = f["estado_ot"]
    mias = []
    for g in grupos.values():
        est = g.pop("estados")
        if all(e == "completado" for e in est):
            g["estado"] = "cerrada"
        elif any(e in ("en_proceso", "completado") for e in est):
            g["estado"] = "en_proceso"
        else:
            g["estado"] = "abierta"
        g["trabajos"] = len(est)
        g.pop("estado_ot", None)
        g["orden"] = g["fecha"] or ""
        mias.append(g)
    todos = sorted(pedidos + mias, key=lambda x: str(x.get("orden") or ""), reverse=True)
    for x in todos:
        x.pop("orden", None)
    return jsonify(todos[:20])


@app.route("/api/ots/<int:ot_id>", methods=["PATCH"])
def api_actualizar_ot(ot_id):
    d = request.json or {}
    # Solo estos campos: el chofer y el km tienen su propia ruta, con permiso
    campos = {k: v for k, v in d.items() if k in ("estado", "fecha_cierre", "observaciones", "procedencia")}
    import ot_unica
    if campos.get("estado") == "cerrada":
        motivo = ot_unica.motivo_para_no_cerrar(ot_id)
        if motivo:
            return jsonify({"ok": False, "msg": motivo}), 400
    elif campos.get("estado") in ("abierta", "en_proceso"):
        motivo = ot_unica.motivo_para_no_reabrir(ot_id)
        if motivo:
            return jsonify({"ok": False, "msg": motivo}), 400
    if campos:
        actualizar_ot(ot_id, **campos)
    return jsonify({"ok": True})


@app.route("/api/ots/<int:ot_id>/cerrar", methods=["POST"])
def api_cerrar_ot(ot_id):
    d = request.json or {}
    # Se cierra recién cuando están todos los trabajos completados
    import ot_unica
    motivo = ot_unica.motivo_para_no_cerrar(ot_id)
    if motivo:
        return jsonify({"ok": False, "msg": motivo}), 400
    cerrar_ot(ot_id, fecha_cierre=d.get("fecha_cierre"))
    auditar(f"Cerró la OT #{ot_id}", "Órdenes de Trabajo")
    return jsonify({"ok": True})


@app.route("/api/ots/<int:ot_id>", methods=["DELETE"])
def api_eliminar_ot(ot_id):
    """Elimina una OT en cualquier fase. Lo puede hacer administración y los
    usuarios a los que se les habilitó en el panel de Usuarios."""
    from database import puede_borrar_ots
    if not puede_borrar_ots(session.get("usuario_id"), session.get("rol")):
        return jsonify({"ok": False, "error": "No tenés permiso para eliminar órdenes de trabajo"}), 403
    ot = obtener_ot(ot_id)
    if not ot:
        return jsonify({"ok": False, "error": "Esa OT ya no existe"}), 404
    # Se borra la OT entera, con todos sus coches
    from database import eliminar_ot_completa
    grupo = ot.get("grupo") or []
    eliminar_ot_completa(ot_id)
    fase = ot.get("estado") or ""
    if ot.get("estado_compras"):
        fase += f" · compras: {ot['estado_compras']}"
    coches = ", ".join(str(g.get("n_interno") or g.get("patente") or "") for g in grupo) \
        or f"{ot.get('n_interno') or ''} {ot.get('patente') or ''}"
    n_items = sum(int(g.get("items") or 0) for g in grupo) if grupo else len(ot.get("items") or [])
    auditar(f"Eliminó la OT #{ot.get('numero') or ot_id}", "Órdenes de Trabajo",
            f"Coche{'s' if len(grupo) > 1 else ''} {coches} · {ot.get('fecha_apertura') or ''}"
            f" · {n_items} ítem(s) · {fase}")
    return jsonify({"ok": True})


@app.route("/api/ots/<int:ot_id>/items", methods=["POST"])
def api_agregar_item_ot(ot_id):
    d = request.json
    try:
        agregar_item_ot(ot_id, d["descripcion"], d.get("tipo", "control"),
                        float(d.get("costo", 0) or 0), d.get("observaciones", ""))
        return jsonify({"ok": True})
    except (KeyError, ValueError) as e:
        return jsonify({"ok": False, "msg": str(e)}), 400


@app.route("/api/ot_items/<int:item_id>", methods=["PATCH"])
def api_actualizar_item(item_id):
    d = request.json or {}
    # Convertir costo si viene
    if "costo" in d:
        try: d["costo"] = float(d["costo"] or 0)
        except: d["costo"] = 0
    # El técnico ahora va por número (personal de taller). Si llega como texto
    # (una pantalla vieja en caché), los números se vinculan y el resto queda
    # escrito tal cual.
    if "tecnico" in d:
        texto = d.pop("tecnico")
        d.pop("tecnico_otro", None)
        try:
            import personal_taller
            personal_taller.asignar_texto(item_id, texto, session.get("nombre") or session.get("usuario") or "")
        except Exception:
            d["tecnico"] = texto
    d.pop("tecnico_otro", None)
    # Un trabajo hecho afuera no se completa sin la foto de la factura
    if d.get("estado") == "completado":
        try:
            from ot_afuera import falta_factura
            falta = falta_factura(item_id)
        except Exception:
            falta = None
        if falta:
            return jsonify({"ok": False, "msg": falta, "error": falta, "falta_factura": True}), 400
    if d:
        actualizar_item_ot(item_id, **d)
    return jsonify({"ok": True})


@app.route("/api/ot_items/<int:item_id>", methods=["DELETE"])
def api_eliminar_item(item_id):
    eliminar_item_ot(item_id)
    try:
        from ot_afuera import al_borrar_item
        al_borrar_item(item_id)
    except Exception:
        pass
    return jsonify({"ok": True})


# ─── API: Cubiertas auxiliares (Trucky) ──────────────────────────────────────

@app.route("/api/vehiculos/<int:vid>/truckies", methods=["GET"])
def api_truckies_vehiculo(vid):
    return jsonify(obtener_truckies_vehiculo(vid))


@app.route("/api/vehiculos/<int:vid>/truckies", methods=["POST"])
def api_asignar_trucky(vid):
    d = request.json
    try:
        ok, msg = asignar_trucky(
            vid, int(d["neumatico_id"]), d["fecha_asignacion"],
            float(d.get("km_asignacion", 0) or 0), d.get("observaciones", "")
        )
        return jsonify({"ok": ok, "msg": msg})
    except (KeyError, ValueError) as e:
        return jsonify({"ok": False, "msg": str(e)}), 400


@app.route("/api/truckies/<int:tid>/usar", methods=["POST"])
def api_usar_trucky(tid):
    d = request.json
    ok, msg = usar_trucky(tid, d.get("fecha_uso", ""),
                          float(d.get("km_uso", 0) or 0), d.get("motivo", ""))
    return jsonify({"ok": ok, "msg": msg})


@app.route("/api/truckies/<int:tid>/retirar", methods=["POST"])
def api_retirar_trucky(tid):
    ok, msg = retirar_trucky(tid)
    return jsonify({"ok": ok, "msg": msg})


# ─── API: Reporte gerencial ──────────────────────────────────────────────────

@app.route("/api/reporte_gerencial", methods=["GET"])
def api_reporte_gerencial():
    desde = request.args.get("desde")
    hasta = request.args.get("hasta")
    if not desde or not hasta:
        return jsonify({"error": "Faltan parámetros desde/hasta"}), 400
    return jsonify(reporte_gerencial(desde, hasta))


@app.route("/api/dossier/<int:vid>", methods=["GET"])
def api_dossier(vid):
    """Dossier completo de un coche: historial + OEE + diagnóstico."""
    from dossier_db import generar_dossier
    desde = request.args.get("desde")
    hasta = request.args.get("hasta")
    if not desde or not hasta:
        return jsonify({"error": "Faltan parámetros desde/hasta"}), 400
    d = generar_dossier(vid, desde, hasta)
    if d is None:
        return jsonify({"error": "Vehículo no encontrado"}), 404
    return jsonify(d)


# ─── API: Exportar PDF ────────────────────────────────────────────────────────

@app.route("/api/exportar_pdf/<int:vid>", methods=["GET"])
def api_exportar_pdf(vid):
    modo = request.args.get("modo", "mes")
    mes = request.args.get("mes")
    vehiculo = next((v for v in obtener_vehiculos(solo_activos=False) if v["id"] == vid), None)
    if not vehiculo:
        return jsonify({"ok": False, "msg": "Vehículo no encontrado"}), 404

    if modo == "produccion":
        k = kpis_produccion(vid)
        titulo_periodo = "Producción total"
    else:
        if not mes:
            meses = meses_con_servicios(vid)
            mes = meses[0] if meses else None
        k = kpis_mes(vid, mes) if mes else None
        titulo_periodo = mes or "—"

    if not k:
        return jsonify({"ok": False, "msg": "Sin datos para exportar"}), 400

    servicios = obtener_servicios_vehiculo(vid, mes if modo != "produccion" else None)
    ruta = generar_pdf(vehiculo, k, servicios, titulo_periodo, modo)
    return send_file(ruta, as_attachment=True,
                     download_name=f"Reporte_{vehiculo['patente']}_{titulo_periodo}.pdf")


@app.route("/api/exportar_reporte_gerencial", methods=["GET"])
def api_exportar_reporte_gerencial():
    desde = request.args.get("desde")
    hasta = request.args.get("hasta")
    if not desde or not hasta:
        return jsonify({"ok": False, "msg": "Faltan parámetros desde/hasta"}), 400
    reporte = reporte_gerencial(desde, hasta)
    os.makedirs("reportes", exist_ok=True)
    ruta = f"reportes/Reporte_Gerencial_{desde}_a_{hasta}.pdf"
    generar_reporte_gerencial_pdf(reporte, ruta)
    return send_file(ruta, as_attachment=True,
                     download_name=f"Reporte_Gerencial_{desde}_a_{hasta}.pdf")


@app.route("/api/ots/<int:ot_id>/pdf", methods=["GET"])
def api_ot_pdf(ot_id):
    """Exporta una orden de trabajo individual a PDF (adaptable a lo que tenga)."""
    ot = obtener_ot(ot_id)
    if not ot:
        return jsonify({"ok": False, "msg": "OT no encontrada"}), 404
    # Con varios coches sale la OT entera: un bloque por coche
    numero = ot.get("numero") or ot_id
    coches = [obtener_ot(g["id"]) for g in (ot.get("grupo") or [])] or [ot]
    coches = [c for c in coches if c]
    os.makedirs("reportes", exist_ok=True)
    ruta = f"reportes/OT_{numero}.pdf"
    generar_ot_pdf(coches[0], ruta, coches=coches)
    return send_file(ruta, as_attachment=True, download_name=f"OT_{numero}.pdf")


@app.route("/api/reporte_trabajos_pdf", methods=["GET"])
def api_reporte_trabajos_pdf():
    """Exporta a PDF todas las OTs de un rango de fechas (reporte diario/semanal)."""
    desde = request.args.get("desde")
    hasta = request.args.get("hasta")
    if not desde or not hasta:
        return jsonify({"ok": False, "msg": "Elegí las fechas desde y hasta"}), 400
    ots = obtener_ots(desde=desde, hasta=hasta)
    os.makedirs("reportes", exist_ok=True)
    ruta = f"reportes/Reporte_Trabajos_{desde}_a_{hasta}.pdf"
    generar_reporte_periodo_pdf(ots, desde, hasta, ruta)
    return send_file(ruta, as_attachment=True,
                     download_name=f"Reporte_Trabajos_{desde}_a_{hasta}.pdf")


@app.route("/api/correctivos_pdf", methods=["GET"])
def api_correctivos_pdf():
    """Exporta a PDF los correctivos de un rango de fechas."""
    desde = request.args.get("desde")
    hasta = request.args.get("hasta")
    if not desde or not hasta:
        return jsonify({"ok": False, "msg": "Elegí las fechas desde y hasta"}), 400
    # Traer todos y filtrar por fecha en el rango
    todos = obtener_correctivos()
    corr = [c for c in todos if desde <= (c.get("fecha") or "") <= hasta]
    os.makedirs("reportes", exist_ok=True)
    ruta = f"reportes/Correctivos_{desde}_a_{hasta}.pdf"
    generar_correctivos_pdf(corr, desde, hasta, ruta)
    return send_file(ruta, as_attachment=True,
                     download_name=f"Correctivos_{desde}_a_{hasta}.pdf")


@app.route("/api/documentos_pdf", methods=["GET"])
def api_documentos_pdf():
    """Exporta a PDF los documentos que vencen hasta una fecha (incluye vencidos)."""
    import datetime as _dt
    hasta = request.args.get("hasta")
    if not hasta:
        return jsonify({"ok": False, "msg": "Elegí la fecha límite"}), 400
    fecha_hoy = ahora().date()
    docs = obtener_documentos()
    seleccionados = []
    for d in docs:
        venc = d.get("fecha_vencimiento")
        if not venc:
            continue
        # Incluir si vence hasta la fecha elegida (incluye los ya vencidos)
        if venc <= hasta:
            try:
                fv = _dt.date.fromisoformat(venc)
                d["dias"] = (fv - fecha_hoy).days
            except ValueError:
                d["dias"] = 0
            seleccionados.append(d)
    # Ordenar por urgencia (más urgente primero)
    seleccionados.sort(key=lambda x: x.get("dias", 0))
    os.makedirs("reportes", exist_ok=True)
    ruta = f"reportes/Documentos_por_vencer_{hasta}.pdf"
    generar_documentos_pdf(seleccionados, hasta, ruta)
    return send_file(ruta, as_attachment=True,
                     download_name=f"Documentos_por_vencer_{hasta}.pdf")


# ─── API: OEE (Eficiencia General de la Flota) ─────────────────────────────────
@app.route("/api/oee/<int:vid>", methods=["GET"])
@login_requerido
def api_oee_vehiculo(vid):
    """Calcula el OEE de un vehículo en un rango de fechas."""
    desde = request.args.get("desde")
    hasta = request.args.get("hasta")
    if not desde or not hasta:
        return jsonify({"ok": False, "msg": "Elegí las fechas desde y hasta"}), 400
    resultado = calcular_oee_vehiculo(vid, desde, hasta)
    if not resultado:
        return jsonify({"ok": False, "msg": "No se pudo calcular"}), 404
    return jsonify(resultado)


@app.route("/api/oee_flota", methods=["GET"])
@login_requerido
def api_oee_flota():
    """Calcula el OEE de toda la flota (promedio) en un rango de fechas."""
    desde = request.args.get("desde")
    hasta = request.args.get("hasta")
    if not desde or not hasta:
        return jsonify({"ok": False, "msg": "Elegí las fechas desde y hasta"}), 400
    vehiculos = obtener_vehiculos(solo_activos=True)
    from database import cargar_datos_oee
    datos = cargar_datos_oee(desde, hasta)     # toda la flota en cinco consultas
    resultados = []
    for v in vehiculos:
        r = calcular_oee_vehiculo(v["id"], desde, hasta, datos.get(v["id"], {}))
        if r:
            resultados.append(r)
    if not resultados:
        return jsonify({"ok": True, "vehiculos": [], "promedio": {}})
    # Promedios de la flota
    n = len(resultados)
    prom = {
        "disponibilidad": round(sum(r["disponibilidad"] for r in resultados) / n, 1),
        "rendimiento": round(sum(r["rendimiento"] for r in resultados) / n, 1),
        "calidad": round(sum(r["calidad"] for r in resultados) / n, 1),
        "oee": round(sum(r["oee"] for r in resultados) / n, 1),
    }
    # Ordenar peor a mejor (para ver los problemáticos primero)
    resultados.sort(key=lambda x: x["oee"])
    return jsonify({"ok": True, "vehiculos": resultados, "promedio": prom, "desde": desde, "hasta": hasta})


@app.route("/api/vehiculos/<int:vid>/consumo", methods=["POST"])
@rol_requerido("admin", "taller")
def api_set_consumo(vid):
    """Define el consumo (km/litro) de un vehículo, para presupuestos de turismo."""
    d = request.json or {}
    try:
        consumo = float(d.get("consumo_km_litro", 0) or 0)
    except (ValueError, TypeError):
        return jsonify({"ok": False, "msg": "Consumo inválido"}), 400
    guardar_consumo_vehiculo(vid, consumo)
    return jsonify({"ok": True})


@app.route("/api/vehiculos/<int:vid>/horario_salida", methods=["POST"])
@rol_requerido("admin", "taller")
def api_set_horario_salida(vid):
    """Define el horario de salida fijo de un vehículo."""
    d = request.json or {}
    horario = (d.get("horario") or "").strip()
    # Validar formato HH:MM si viene algo
    if horario:
        import re
        if not re.match(r"^([01]?\d|2[0-3]):[0-5]\d$", horario):
            return jsonify({"ok": False, "msg": "Horario inválido (usá HH:MM, ej: 06:00)"}), 400
    guardar_horario_salida(vid, horario)
    return jsonify({"ok": True})


@app.route("/api/vehiculos/<int:vid>/km_manual", methods=["POST"])
def api_set_km_manual(vid):
    """Corrige a mano el odómetro de un vehículo."""
    if not _puede_editar_km_sesion():
        return jsonify({"ok": False, "error": "No tenés permiso para corregir el kilometraje"}), 403
    d = request.json or {}
    try:
        km = float(d.get("km", 0) or 0)
    except (ValueError, TypeError):
        return jsonify({"ok": False, "msg": "Km inválido"}), 400
    if km < 0:
        return jsonify({"ok": False, "msg": "El km no puede ser negativo"}), 400
    guardar_km_manual(vid, km)
    auditar(f"Corrigió el km del vehículo (ID {vid})", "Vehículos", f"Nuevo km: {int(km):,}".replace(",", "."))
    return jsonify({"ok": True, "km_actual": km_actual_vehiculo(vid)})


@app.route("/api/vehiculos/<int:vid>/meta_km", methods=["POST"])
@rol_requerido("admin", "taller")
def api_set_meta_km(vid):
    """Define la meta de km mensual de un vehículo (para el rendimiento del OEE)."""
    d = request.json or {}
    try:
        meta = int(d.get("meta_km_mensual", 0) or 0)
    except ValueError:
        return jsonify({"ok": False, "msg": "Meta inválida"}), 400
    guardar_meta_km(vid, meta)
    return jsonify({"ok": True})


@app.route("/api/vehiculos/<int:vid>/fuera_servicio", methods=["GET", "POST"])
@login_requerido
def api_fuera_servicio(vid):
    if request.method == "GET":
        return jsonify(obtener_fuera_servicio(vid))
    d = request.json or {}
    desde = d.get("fecha_desde")
    if not desde:
        return jsonify({"ok": False, "msg": "Falta la fecha de inicio"}), 400
    registrar_fuera_servicio(vid, desde, d.get("fecha_hasta"), d.get("motivo", ""))
    return jsonify({"ok": True})


# ─── API: Flujo de Compras / Depósito ──────────────────────────────────────────
@app.route("/api/ots/<int:ot_id>/enviar_compras", methods=["POST"])
@rol_requerido("admin", "taller")
def api_enviar_compras(ot_id):
    """El taller envía la OT a Compras (queda en espera)."""
    d = request.json or {}
    enviar_ot_a_compras(ot_id, d.get("nota", ""))
    auditar(f"Envió la OT #{ot_id} a Compras", "Compras")
    return jsonify({"ok": True})


@app.route("/api/compras/ots", methods=["GET"])
@compras_requerido
def api_compras_ots():
    """Lista las OTs en el circuito de compras (para la pantalla de Compras)."""
    estado = request.args.get("estado") or None
    return jsonify(obtener_ots_compras(estado))


@app.route("/api/compras/<int:ot_id>/presupuesto", methods=["POST"])
@compras_requerido
def api_compras_presupuesto(ot_id):
    """Compras carga el precio de cada item. La OT pasa a presupuestado."""
    d = request.json or {}
    precios = d.get("precios") or {}            # {item_id: precio} (trabajos sin materiales)
    materiales = d.get("materiales") or {}      # {material_id: precio por unidad}
    proveedores_items = d.get("proveedores_items") or {}
    proveedores_materiales = d.get("proveedores_materiales") or {}
    if not precios and not materiales:
        return jsonify({"ok": False, "msg": "Cargá al menos un precio"}), 400
    guardar_presupuesto_compras(ot_id, precios, materiales, proveedores_items, proveedores_materiales)
    try:   # depósito sin precio y el último precio de cada proveedor en la ficha del repuesto
        import compras_repuestos
        compras_repuestos.guardar_presupuesto(ot_id, d, session.get("nombre") or session.get("usuario") or "")
    except Exception as e:
        print(f"[compras_repuestos] presupuesto OT {ot_id}: {e}")
    ot = obtener_ot(ot_id) or {}
    try:
        from ot_materiales import grupo_ids
        ids = grupo_ids(ot_id)
    except Exception:
        ids = [ot_id]
    total = 0
    for i in ids:
        o = obtener_ot(i) or {}
        total += sum(float(it.get("precio_compras") or 0) for it in o.get("items") or [])
    auditar(f"Presupuestó la OT #{ot.get('numero') or ot_id}", "Compras",
            f"{len(precios) + len(materiales)} precio(s), total Gs. {int(total):,}".replace(",", "."))
    return jsonify({"ok": True, "total": round(total)})


@app.route("/api/compras/<int:ot_id>/firmar", methods=["POST"])
@compras_requerido
def api_compras_firmar(ot_id):
    """Tesorería firma el presupuesto: se habilitan los ítems que puede cubrir y
    el resto queda esperando fondos. La OT avanza con lo habilitado."""
    from database import firmar_presupuesto
    d = request.json or {}
    ids = d.get("habilitados", [])
    ok, msg = firmar_presupuesto(ot_id, ids)
    if not ok:
        return jsonify({"ok": False, "msg": msg}), 400
    auditar(f"Firmó el presupuesto de la OT #{ot_id}", "Compras", msg,
            referencia=f"compras:{ot_id}")
    return jsonify({"ok": True, "msg": msg})


@app.route("/api/compras/cola_espera", methods=["GET"])
@compras_requerido
def api_compras_cola_espera():
    """Ítems esperando fondos: la cola de tesorería, más viejos primero."""
    from database import cola_espera_fondos
    return jsonify(cola_espera_fondos())


@app.route("/api/compras/liberar", methods=["POST"])
@compras_requerido
def api_compras_liberar():
    """Tesorería libera ítems de la cola cuando hay fondos."""
    from database import liberar_items
    d = request.json or {}
    ids = d.get("items", [])
    if not ids:
        return jsonify({"ok": False, "msg": "No seleccionaste ítems"}), 400
    ok, msg = liberar_items(ids)
    auditar("Liberó ítems que esperaban fondos", "Compras", msg)
    return jsonify({"ok": ok, "msg": msg})


@app.route("/api/compras/<int:ot_id>/en_camino", methods=["POST"])
@compras_requerido
def api_compras_en_camino(ot_id):
    """Compras marca que fue a buscar los repuestos (en camino)."""
    marcar_en_camino_compras(ot_id)
    auditar(f"Marcó en camino la OT #{ot_id}", "Compras")
    return jsonify({"ok": True})


@app.route("/api/compras/<int:ot_id>/entregar", methods=["POST"])
@compras_requerido
def api_compras_entregar(ot_id):
    """Compras entrega el material. Lo obligatorio es QUIÉN recibe (transfiere
    la responsabilidad). La foto de evidencia es opcional pero recomendada."""
    d = request.json or {}
    recibido_por = (d.get("recibido_por") or "").strip()
    if not recibido_por:
        return jsonify({"ok": False, "msg": "Indicá quién recibió el material"}), 400
    foto = d.get("foto")
    if foto and len(foto) > 800000:
        return jsonify({"ok": False, "msg": "La foto es muy grande"}), 400
    taller = (d.get("taller_entrega") or "Taller propio").strip()
    registrar_entrega_compras(ot_id, foto, taller_entrega=taller, recibido_por=recibido_por)
    auditar(f"Registró la entrega de la OT #{ot_id}", "Compras",
            f"Entregado en {taller} — recibió {recibido_por}" + (" (con foto)" if foto else ""),
            referencia=f"compras:{ot_id}")
    stock = {"movidos": 0, "problemas": []}
    try:   # lo del depósito sale y lo comprado entra al inventario y sale para la OT
        import compras_repuestos
        stock = compras_repuestos.al_entregar(ot_id, session.get("nombre") or session.get("usuario") or "")
    except Exception as e:
        stock["problemas"].append(f"No se pudo mover el stock: {e}")
    return jsonify({"ok": True, "stock": stock})


@app.route("/api/compras/talleres", methods=["GET"])
@compras_requerido
def api_compras_talleres():
    """Talleres externos ya usados en entregas, para autocompletar."""
    from database import talleres_usados
    return jsonify(talleres_usados())


@app.route("/api/compras/<int:ot_id>/evidencia", methods=["GET"])
@rol_requerido("admin", "compras", "taller")
def api_compras_evidencia(ot_id):
    """Devuelve las fotos de evidencia de entrega."""
    return jsonify(obtener_evidencia_compras(ot_id))


@app.route("/api/compras/<int:ot_id>/proveedor", methods=["POST"])
@compras_requerido
def api_compras_proveedor(ot_id):
    """Guarda el proveedor asociado a una OT presupuestada."""
    if not obtener_ot(ot_id):
        return jsonify({"ok": False, "msg": "OT no encontrada"}), 404
    d = request.json or {}
    proveedor = d.get("proveedor", "")
    if not isinstance(proveedor, str):
        return jsonify({"ok": False, "msg": "El proveedor debe ser texto"}), 400
    proveedor = proveedor.strip()[:160]
    if not guardar_proveedor_compras(ot_id, proveedor):
        return jsonify({"ok": False, "msg": "No se pudo guardar el proveedor"}), 400
    auditar(f"Actualizó proveedor de la OT #{ot_id}", "Compras", proveedor or "Proveedor borrado",
            referencia=f"compras:{ot_id}")
    return jsonify({"ok": True, "proveedor": proveedor})


@app.route("/api/compras/<int:ot_id>/presupuesto_pdf", methods=["GET"])
@compras_requerido
def api_compras_presupuesto_pdf(ot_id):
    """El pedido de fondos para Tesorería: por coche y por trabajo, cada
    material con cantidad y precio, el total en números y en letras, y las
    firmas de quien pide, quien autoriza y Tesorería."""
    ot = obtener_ot(ot_id)
    if not ot:
        return jsonify({"ok": False, "msg": "OT no encontrada"}), 404
    from tesoreria_pdf import datos_pedido, pdf_pedido_fondos
    d = datos_pedido(ot_id, session.get("nombre") or session.get("usuario") or "")
    buf = pdf_pedido_fondos(d)
    return send_file(buf, mimetype="application/pdf", as_attachment=False,
                     download_name=f"Tesoreria_OT_{d['numero']}.pdf")


# ─── API: Turismo (presupuestos) ───────────────────────────────────────────────
@app.route("/api/turismo/config", methods=["GET", "POST"])
@rol_requerido("admin", "taller")
def api_turismo_config():
    if request.method == "GET":
        return jsonify(obtener_config_turismo())
    guardar_config_turismo(request.json or {})
    return jsonify({"ok": True})


@app.route("/api/turismo/calcular", methods=["POST"])
@login_requerido
def api_turismo_calcular():
    """Calcula un presupuesto de turismo (sin guardarlo). Para el cálculo en vivo."""
    resultado = calcular_presupuesto_turismo(request.json or {})
    return jsonify(resultado)


@app.route("/api/turismo/presupuestos", methods=["GET", "POST"])
@login_requerido
def api_turismo_presupuestos():
    if request.method == "GET":
        return jsonify(obtener_presupuestos_turismo())
    d = request.json or {}
    datos = d.get("datos", {})
    resultado = calcular_presupuesto_turismo(datos)
    pid = guardar_presupuesto_turismo(datos, resultado)
    auditar(f"Creó presupuesto de turismo #{pid}", "Turismo",
            f"{datos.get('destino','?')} — Gs. {int(resultado.get('precio_final',0)):,}".replace(",", "."))
    return jsonify({"ok": True, "id": pid})


@app.route("/api/turismo/presupuestos/<int:pid>", methods=["GET", "DELETE"])
@login_requerido
def api_turismo_presupuesto(pid):
    if request.method == "DELETE":
        eliminar_presupuesto_turismo(pid)
        return jsonify({"ok": True})
    p = obtener_presupuesto_turismo(pid)
    if not p:
        return jsonify({"ok": False, "msg": "No encontrado"}), 404
    return jsonify(p)


@app.route("/api/turismo/presupuestos/<int:pid>/pdf", methods=["GET"])
@login_requerido
def api_turismo_pdf(pid):
    """Genera el PDF del presupuesto de turismo para el cliente."""
    p = obtener_presupuesto_turismo(pid)
    if not p:
        return jsonify({"ok": False, "msg": "No encontrado"}), 404
    os.makedirs("reportes", exist_ok=True)
    ruta = f"reportes/Presupuesto_Turismo_{pid}.pdf"
    from pdf_export import generar_presupuesto_turismo_pdf
    generar_presupuesto_turismo_pdf(p, ruta)
    return send_file(ruta, as_attachment=True, download_name=f"Presupuesto_{p.get('destino','viaje')}_{pid}.pdf")


# ─── API: Historial de auditoría (SOLO ADMIN) ──────────────────────────────────
@app.route("/api/auditoria", methods=["GET"])
@rol_requerido("admin", "auditor")
def api_auditoria():
    """Devuelve el historial de acciones. Lo ven admin y auditor."""
    desde = request.args.get("desde")
    hasta = request.args.get("hasta")
    categoria = request.args.get("categoria") or None
    usuario = request.args.get("usuario") or None
    registros = obtener_auditoria(desde=desde, hasta=hasta, categoria=categoria, usuario=usuario)
    stats = estadisticas_auditoria(desde=desde, hasta=hasta)
    return jsonify({"registros": registros, "stats": stats})


@app.route("/api/auditoria/evidencia", methods=["GET"])
@rol_requerido("admin", "auditor")
def api_auditoria_evidencia():
    """Devuelve las fotos vinculadas a un registro del historial, según su referencia.
    La referencia tiene el formato 'tipo:id' (ej: 'compras:45' o 'chofer_ot:45')."""
    ref = request.args.get("ref", "")
    if ":" not in ref:
        return jsonify({"fotos": []})
    tipo, _, ident = ref.partition(":")
    try:
        ot_id = int(ident)
    except (ValueError, TypeError):
        return jsonify({"fotos": []})
    if tipo == "compras":
        fotos = obtener_evidencia_compras(ot_id)
        return jsonify({"fotos": [{"datos": f.get("datos"), "tipo": "Entrega de compras"} for f in fotos]})
    elif tipo == "chofer_ot":
        fotos = obtener_fotos_ot(ot_id, incluir_datos=True)
        return jsonify({"fotos": [{"datos": f.get("datos"), "tipo": "Reporte de chofer"} for f in fotos]})
    return jsonify({"fotos": []})


# ─── API: Combustible (admin y auditor) ────────────────────────────────────────
@app.route("/api/combustible", methods=["GET", "POST"])
@rol_requerido("admin", "auditor")
def api_combustible():
    if request.method == "GET":
        vid = request.args.get("vehiculo_id", type=int)
        desde = request.args.get("desde")
        hasta = request.args.get("hasta")
        cargas = obtener_cargas_combustible(vehiculo_id=vid, desde=desde, hasta=hasta)
        stats = estadisticas_combustible(desde=desde, hasta=hasta)
        return jsonify({"cargas": cargas, "stats": stats})
    # POST: registrar nueva carga
    d = request.json or {}
    if not d.get("vehiculo_id"):
        return jsonify({"ok": False, "msg": "Falta el vehículo"}), 400
    if not d.get("litros") or float(d.get("litros", 0) or 0) <= 0:
        return jsonify({"ok": False, "msg": "Cargá los litros"}), 400
    d["registrado_por"] = session.get("nombre") or session.get("usuario") or ""
    cid = registrar_carga_combustible(d)
    auditar(f"Cargó combustible (carga #{cid})", "Combustible",
            f"{d.get('litros')} litros, odómetro {d.get('odometro','?')}")
    return jsonify({"ok": True, "id": cid})


@app.route("/api/consumo/referencias", methods=["GET"])
@login_requerido
def api_referencias_consumo():
    """El consumo esperado de cada modelo y motor de la flota."""
    from database import referencias_consumo
    return jsonify(referencias_consumo())


@app.route("/api/consumo/referencias/<int:plan_id>", methods=["PATCH"])
@rol_requerido("admin")
def api_guardar_referencia(plan_id):
    """Corrige el consumo esperado de un modelo, con lo que mida la flota."""
    from database import guardar_referencia_consumo
    d = request.json or {}
    ok, msg = guardar_referencia_consumo(plan_id, d.get("litros_100km"))
    if ok:
        auditar(f"Actualizó el consumo de referencia (plan {plan_id})", "Combustible", msg)
    return jsonify({"ok": ok, "msg": msg}), (200 if ok else 400)


@app.route("/api/consumo/referencias_coche", methods=["GET"])
@login_requerido
def api_referencias_coche():
    """El consumo esperado de cada coche: el de su modelo y, si tiene, el propio."""
    from database import referencias_por_coche
    return jsonify(referencias_por_coche())


@app.route("/api/consumo/referencias_coche/<int:vid>", methods=["PATCH"])
@rol_requerido("admin")
def api_guardar_referencia_coche(vid):
    """Le pone a un coche su propio consumo esperado (o se lo saca)."""
    from database import guardar_referencia_coche
    d = request.json or {}
    ok, msg = guardar_referencia_coche(vid, d.get("litros_100km"))
    if ok:
        auditar(f"Cambió el consumo de referencia del coche (ID {vid})", "Combustible", msg)
    return jsonify({"ok": ok, "msg": msg}), (200 if ok else 400)


@app.route("/api/consumo/vehiculo/<int:vid>", methods=["GET"])
@login_requerido
def api_consumo_vehiculo(vid):
    """Cómo viene consumiendo ese bus contra lo esperado para su motor."""
    from database import (obtener_cargas_combustible, consumo_promedio,
                          comparar_con_referencia, referencia_de_vehiculo)
    cargas = obtener_cargas_combustible(vehiculo_id=vid, limite=1000)
    real = consumo_promedio(cargas)
    return jsonify({
        "consumo": real,
        "referencia": referencia_de_vehiculo(vid),
        "comparacion": comparar_con_referencia(vid, real),
        "cargas": len(cargas),
    })


@app.route("/api/combustible/<int:carga_id>", methods=["GET"])
@login_requerido
def api_ver_combustible(carga_id):
    """Una carga puntual, para abrirla y corregirla."""
    from database import obtener_carga_combustible
    c = obtener_carga_combustible(carga_id)
    if not c:
        return jsonify({"error": "No encontrada"}), 404
    return jsonify(c)


@app.route("/api/combustible/<int:carga_id>", methods=["PATCH"])
@rol_requerido("admin")
def api_editar_combustible(carga_id):
    """Corrige una carga mal cargada. Solo admin: tocar el odómetro o los
    litros cambia el rendimiento calculado del coche."""
    from database import actualizar_carga_combustible
    from rendicion_combustible import sobre_de_carga
    de = sobre_de_carga(carga_id)
    if de and de[1]:
        return jsonify({"ok": False, "msg": f"Esta carga es un comprobante del sobre {de[0]}: "
                                             "corregila desde Rendición de combustible."}), 400
    ok, msg = actualizar_carga_combustible(carga_id, request.json or {})
    if ok:
        auditar(f"Corrigió una carga de combustible (#{carga_id})", "Combustible", msg)
    return jsonify({"ok": ok, "msg": msg}), (200 if ok else 400)


@app.route("/api/combustible/<int:carga_id>", methods=["DELETE"])
@rol_requerido("admin")
def api_eliminar_combustible(carga_id):
    """Borra una carga. Solo admin — el auditor consulta, no modifica."""
    from rendicion_combustible import sobre_de_carga, soltar_carga
    de = sobre_de_carga(carga_id)
    if de and de[1]:
        return jsonify({"ok": False, "msg": f"Esta carga es un comprobante del sobre {de[0]}: "
                                             "sacala desde Rendición de combustible."}), 400
    if de:
        soltar_carga(carga_id)
    eliminar_carga_combustible(carga_id)
    auditar(f"Eliminó una carga de combustible (#{carga_id})", "Combustible")
    return jsonify({"ok": True, "msg": "Carga eliminada."})


# ─── Arranque ─────────────────────────────────────────────────────────────────

def iniciar_servidor():
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)


def main():
    inicializar_db()
    # Cargar planes de mantenimiento predefinidos (si no existen)
    try:
        from mantenimiento_seed import cargar_planes_default
        cargar_planes_default()
    except Exception as e:
        print(f"Aviso: no se pudieron cargar planes default: {e}")

    # Crear usuario admin por defecto si no hay usuarios
    cred = crear_admin_por_defecto()
    if cred:
        print("\n" + "=" * 55)
        print("  USUARIO ADMINISTRADOR CREADO")
        print(f"  Usuario:    {cred[0]}")
        print(f"  Contraseña: {cred[1]}")
        print("  ⚠ Cambiá esta contraseña después de entrar")
        print("=" * 55 + "\n")

    # Modo servidor (nube / red local) vs escritorio
    modo_servidor = os.environ.get("MODO_SERVIDOR", "").lower() in ("1", "true", "si")

    if modo_servidor:
        # Modo nube/red: solo servidor web, sin ventana de escritorio
        puerto = int(os.environ.get("PORT", 5000))
        print(f"Servidor corriendo en modo web — puerto {puerto}")
        app.run(host="0.0.0.0", port=puerto)
        return

    # Modo escritorio local (PyWebView)
    threading.Thread(target=iniciar_servidor, daemon=True).start()
    try:
        import webview
        webview.create_window(
            "Gestión de Flota — La Santaniana",
            "http://127.0.0.1:5000",
            width=1280, height=820, min_size=(1000, 700)
        )
        webview.start()
    except ImportError:
        import webbrowser
        print("PyWebView no instalado. Abriendo en el navegador...")
        print("App corriendo en http://127.0.0.1:5000")
        webbrowser.open("http://127.0.0.1:5000")
        iniciar_servidor()


# Para servidores de producción (gunicorn): inicializar la BD al importar
inicializar_db()
try:
    from mantenimiento_seed import cargar_planes_default
    cargar_planes_default()
    crear_admin_por_defecto()
    # El consumo esperado se cuelga de los planes, así que se siembra recién
    # cuando los planes ya existen.
    from database import sembrar_referencias_consumo, reasignar_mercedes_lo915
    sembrar_referencias_consumo()
    reasignar_mercedes_lo915()
except Exception:
    pass


if __name__ == "__main__":
    main()
