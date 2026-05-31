"""
app.py — Servidor Flask + ventana de escritorio (PyWebView)
Sistema de Gestión de Flota - La Santaniana  ·  v9.2 Multiusuario
Moneda: Guaraní (₲)
"""

import os
import threading
import datetime
from functools import wraps
from flask import (Flask, render_template, request, jsonify, send_file,
                   session, redirect, url_for, make_response)

from database import (
    inicializar_db, agregar_vehiculo, actualizar_vehiculo, obtener_vehiculos, eliminar_vehiculo,
    agregar_servicio, eliminar_servicio, obtener_servicios_vehiculo,
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
    # Documentos:
    agregar_documento, obtener_documentos, actualizar_documento, eliminar_documento,
    documentos_proximos_a_vencer,
    # Neumáticos:
    crear_config_neumaticos, obtener_config_neumaticos_plan, obtener_config_neumaticos_vehiculo,
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
                        generar_plan_preventivo_pdf, generar_correctivos_pdf)

app = Flask(__name__)
# Clave secreta para las sesiones (en producción se toma de variable de entorno)
app.secret_key = os.environ.get("SECRET_KEY", "la-santaniana-flota-2026-cambiar-esto")


# ─── Compresión gzip de respuestas ──────────────────────────────────────────
# Comprime las respuestas JSON/HTML antes de enviarlas. Como los datos viajan
# de EEUU a Paraguay, comprimirlos hace que lleguen más rápido (menos bytes).
import gzip as _gzip
import io as _io

@app.after_request
def _comprimir_respuesta(response):
    # Cachear archivos estáticos (JS/CSS/imágenes) en el navegador 1 día,
    # así no se vuelven a descargar en cada visita.
    try:
        if request.path.startswith("/static/"):
            response.headers["Cache-Control"] = "public, max-age=86400"
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


# Rutas que NO requieren login
RUTAS_PUBLICAS = {"/login", "/api/login", "/static"}

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
    return None



# ─── Páginas ──────────────────────────────────────────────────────────────────

@app.route("/")
@login_requerido
def index():
    # Los choferes ven solo su pantalla simple de carga de OT
    if session.get("rol") == "chofer":
        return redirect(url_for("pantalla_chofer"))
    return render_template("index.html",
                           usuario=session.get("nombre") or session.get("usuario"),
                           rol=session.get("rol"))


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
        # Sesión NO permanente: se cierra al cerrar el navegador (más seguro)
        session.permanent = False
        return jsonify({"ok": True, "usuario": u})
    return jsonify({"ok": False, "msg": "Usuario o contraseña incorrectos"}), 401


@app.route("/api/logout", methods=["POST"])
def api_logout():
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
    ok, msg = crear_usuario(d["usuario"], d["password"],
                            d.get("nombre", ""), d.get("rol", "taller"))
    return jsonify({"ok": ok, "msg": msg})


@app.route("/api/usuarios/<int:uid>", methods=["PATCH"])
@rol_requerido("admin")
def api_actualizar_usuario(uid):
    d = request.json or {}
    actualizar_usuario(uid, **d)
    return jsonify({"ok": True})


@app.route("/api/usuarios/<int:uid>", methods=["DELETE"])
@rol_requerido("admin")
def api_eliminar_usuario(uid):
    if uid == session.get("usuario_id"):
        return jsonify({"ok": False, "msg": "No podés eliminar tu propio usuario"}), 400
    eliminar_usuario(uid)
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


# ─── API: Servicios ───────────────────────────────────────────────────────────

@app.route("/api/servicios/<int:vid>", methods=["GET"])
def api_servicios(vid):
    mes = request.args.get("mes")  # None o "2024-06"
    mes = None if mes in (None, "", "todos") else mes
    return jsonify(obtener_servicios_vehiculo(vid, mes))


@app.route("/api/servicios", methods=["POST"])
def api_agregar_servicio():
    d = request.json
    try:
        agregar_servicio(
            int(d["vehiculo_id"]), d["fecha"],
            float(d.get("km", 0) or 0), float(d.get("horas", 0) or 0),
            float(d.get("ingreso", 0) or 0), d.get("descripcion", "")
        )
        return jsonify({"ok": True})
    except (KeyError, ValueError) as e:
        return jsonify({"ok": False, "msg": str(e)}), 400


@app.route("/api/servicios/<int:sid>", methods=["DELETE"])
def api_eliminar_servicio(sid):
    eliminar_servicio(sid)
    return jsonify({"ok": True})


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
    return jsonify({
        "plan": plan,
        "km_actual": km_actual_vehiculo(vid)
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


@app.route("/api/vehiculos/<int:vid>/neumaticos", methods=["GET"])
def api_neumaticos_vehiculo(vid):
    """Devuelve estado completo de neumáticos del vehículo + configuración."""
    return jsonify(estado_neumaticos_vehiculo(vid) or {})


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
    return jsonify(obtener_ots(estado=estado, vehiculo_id=vid, desde=desde, hasta=hasta))


@app.route("/api/ots/<int:ot_id>", methods=["GET"])
def api_ot(ot_id):
    ot = obtener_ot(ot_id)
    if not ot:
        return jsonify({"error": "no encontrada"}), 404
    # Incluir las fotos (cantidad y datos) para mostrarlas en el taller
    ot["fotos"] = obtener_fotos_ot(ot_id, incluir_datos=True)
    return jsonify(ot)


@app.route("/api/ots", methods=["POST"])
def api_crear_ot():
    d = request.json
    try:
        ot_id = crear_ot(
            int(d["vehiculo_id"]), d["fecha_apertura"],
            km=float(d.get("km", 0) or 0),
            conductor=d.get("conductor", ""),
            procedencia=d.get("procedencia", ""),
            observaciones=d.get("observaciones", ""),
            items=d.get("items", [])
        )
        return jsonify({"ok": True, "ot_id": ot_id})
    except (KeyError, ValueError) as e:
        return jsonify({"ok": False, "msg": str(e)}), 400


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

        hoy = _dt.date.today().isoformat()
        chofer = session.get("nombre") or session.get("usuario") or "Chofer"
        ot_id = crear_ot(
            vehiculo_id, hoy, km=km,
            conductor=chofer, procedencia="WhatsApp/Chofer",
            observaciones=f"Reporte cargado por el chofer.",
            items=items
        )

        # Guardar fotos si el chofer adjuntó (vienen comprimidas en base64)
        fotos = d.get("fotos", [])
        if fotos:
            for i, foto in enumerate(fotos[:3]):  # máximo 3 fotos por reporte
                if foto and len(foto) < 800000:  # límite de seguridad (~600KB c/u)
                    agregar_foto_ot(ot_id, foto, f"foto_{i+1}.jpg")

        return jsonify({"ok": True, "ot_id": ot_id, "items": len(items),
                        "fotos": len(fotos), "msg": "¡Reporte enviado al taller!"})
    except (KeyError, ValueError) as e:
        return jsonify({"ok": False, "msg": "Faltan datos: " + str(e)}), 400


@app.route("/api/chofer/mis_reportes", methods=["GET"])
@login_requerido
def api_chofer_mis_reportes():
    """Reportes cargados desde la pantalla del chofer, con su estado."""
    chofer = session.get("nombre") or session.get("usuario") or "Chofer"
    # Traer las OTs cuya procedencia es del chofer (las últimas 20)
    ots = obtener_ots()
    mias = []
    for o in ots:
        if o.get("procedencia") == "WhatsApp/Chofer":
            mias.append({
                "id": o["id"],
                "fecha": o.get("fecha_apertura", ""),
                "patente": o.get("patente", ""),
                "n_interno": o.get("n_interno", ""),
                "estado": o.get("estado", "abierta"),
                "observaciones": o.get("observaciones", ""),
            })
    mias = mias[:20]
    return jsonify(mias)


@app.route("/api/ots/<int:ot_id>", methods=["PATCH"])
def api_actualizar_ot(ot_id):
    d = request.json or {}
    actualizar_ot(ot_id, **d)
    return jsonify({"ok": True})


@app.route("/api/ots/<int:ot_id>/cerrar", methods=["POST"])
def api_cerrar_ot(ot_id):
    d = request.json or {}
    cerrar_ot(ot_id, fecha_cierre=d.get("fecha_cierre"))
    return jsonify({"ok": True})


@app.route("/api/ots/<int:ot_id>", methods=["DELETE"])
def api_eliminar_ot(ot_id):
    eliminar_ot(ot_id)
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
    actualizar_item_ot(item_id, **d)
    return jsonify({"ok": True})


@app.route("/api/ot_items/<int:item_id>", methods=["DELETE"])
def api_eliminar_item(item_id):
    eliminar_item_ot(item_id)
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
    os.makedirs("reportes", exist_ok=True)
    ruta = f"reportes/OT_{ot_id}.pdf"
    generar_ot_pdf(ot, ruta)
    return send_file(ruta, as_attachment=True, download_name=f"OT_{ot_id}.pdf")


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
except Exception:
    pass


if __name__ == "__main__":
    main()
