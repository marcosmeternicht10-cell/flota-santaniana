"""
api_externa.py — La API para que otros sistemas lean y carguen datos (La Santaniana)

Para conectar la contabilidad, un tablero de Power BI / Excel, el sistema de
otra empresa o un script propio, sin entrar con usuario y contraseña.

  · Cada sistema que se conecta tiene su CLAVE (ls_...). La crea el admin en
    Sistema → API e integraciones, eligiendo qué puede ver o cargar. La clave se
    muestra UNA sola vez; en la base queda solo su huella (sha256), así que si
    alguien copia la base no se lleva las claves.
  · Se manda en cada pedido:  Authorization: Bearer ls_...   (o X-API-Key: ls_...)
  · Límite: 120 pedidos por minuto por clave. Cada pedido queda anotado
    (qué clave, qué pidió, cuándo, desde dónde) para ver quién usa qué.
  · Una clave se puede revocar al toque: deja de andar en el próximo pedido.
  · La documentación con ejemplos está en /api/v1/docs (no necesita clave).

Rutas (todas devuelven JSON):
  GET  /api/v1/estado                  probar la clave
  GET  /api/v1/vehiculos               flota, con el km actual         [flota]
  GET  /api/v1/ots                     órdenes de trabajo con ítems    [ots]
  GET  /api/v1/ots/<id>                una OT                          [ots]
  GET  /api/v1/combustible             cargas de combustible           [combustible]
  GET  /api/v1/rendiciones             rendiciones de corporativos     [rendiciones]
  GET  /api/v1/pagos                   pagos de plus a choferes        [rendiciones]
  GET  /api/v1/trafico/<fecha>         el tráfico publicado del día    [trafico]
  GET  /api/v1/costos                  costos por coche y mes          [costos]
  POST /api/v1/combustible             cargar una carga                [combustible:escribir]
  POST /api/v1/kilometraje             informar el km de un coche      [km:escribir]
  GET  /api/v1/planilla/<link>.csv     una planilla para Excel / Google Sheets / Power BI

Los links de planilla son claves de tipo «planilla»: leen UN conjunto de datos
con los filtros que se eligieron al crearlo, y no sirven para nada más. La
clave va en el link porque Excel y Google Sheets no saben mandar encabezados;
por eso ese link sí se guarda (para poder volver a copiarlo) y la de
programadores no. Cualquier lista acepta ?formato=csv.

Enganche en app.py:
    from api_externa import bp_api_externa, init_api_externa
    init_api_externa()
    app.register_blueprint(bp_api_externa)
  y en proteger_rutas, antes de pedir sesión:
    if p.startswith("/api/v1/"): return None     # tiene su propia clave
"""

import hashlib
import json
import re
import secrets
import threading
import time
from collections import deque
from datetime import date, datetime, timedelta
from functools import wraps

from flask import Blueprint, request, jsonify, session, g, render_template, url_for
from db_compat import get_connection, USE_POSTGRES, columnas_de_tabla

from hora_local import ahora_iso, hoy as _hoy_txt

bp_api_externa = Blueprint("api_externa", __name__)

PK = "SERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"

VERSION = "1.0"
LIMITE_POR_MINUTO = 120
LIMITE_FILAS = 500          # máximo por página
FILAS_POR_DEFECTO = 100
DIAS_DE_REGISTRO = 90       # el registro de uso se guarda 3 meses

# Lo que puede tener una clave. El orden es el de la pantalla.
PERMISOS = [
    ("flota",                "Flota",                  "Coches: número interno, chapa, modelo y km actual"),
    ("ots",                  "Órdenes de trabajo",     "Las OT con sus ítems, técnicos, costos y estado"),
    ("combustible",          "Combustible",            "Las cargas: litros, precio, odómetro, estación"),
    ("rendiciones",          "Rendiciones y pagos",    "Rendiciones de corporativos y pagos de plus"),
    ("trafico",              "Tráfico y asignación",   "El tráfico y la asignación de corporativos, tal como se publicaron"),
    ("costos",               "Costos",                 "Costos cargados por coche y mes"),
    ("agencias",             "Agencias",               "Las agencias de venta: código, datos de contacto y estado"),
    ("combustible:escribir", "Cargar combustible",     "Puede registrar cargas (por ejemplo, desde el surtidor)"),
    ("km:escribir",          "Informar kilometraje",   "Puede actualizar el km de un coche (por ejemplo, desde el GPS)"),
    ("recibir",              "Enviar cualquier dato",  "Bandeja de entrada: ventas, agencias, fallas, costos… lo que el sistema entiende se aplica solo"),
]
CODIGOS = {p[0] for p in PERMISOS}


# ════════════════════════════════════════════════════════════════════════
#  Tablas
# ════════════════════════════════════════════════════════════════════════

def init_api_externa():
    conn = get_connection()
    try:
        for sql in (
            f"""CREATE TABLE IF NOT EXISTS api_claves (
                id {PK},
                nombre TEXT NOT NULL,
                prefijo TEXT NOT NULL,          -- lo que se ve: ls_ab12cd34…
                huella TEXT NOT NULL UNIQUE,    -- sha256 de la clave entera
                permisos TEXT DEFAULT '[]',     -- JSON: ["ots","combustible"]
                nota TEXT DEFAULT '',
                activa INTEGER DEFAULT 1,
                creada_el TEXT DEFAULT '',
                creada_por TEXT DEFAULT '',
                revocada_el TEXT DEFAULT '',
                revocada_por TEXT DEFAULT '',
                ultimo_uso TEXT DEFAULT '',
                ultima_ip TEXT DEFAULT '',
                usos INTEGER DEFAULT 0,
                tipo TEXT DEFAULT 'clave',      -- clave (programadores) | planilla (un link)
                config TEXT DEFAULT '')         -- planilla: el dato, sus filtros y el link (JSON)""",
            f"""CREATE TABLE IF NOT EXISTS api_registro (
                id {PK},
                clave_id INTEGER,
                momento TEXT DEFAULT '',
                metodo TEXT DEFAULT '',
                ruta TEXT DEFAULT '',
                consulta TEXT DEFAULT '',
                estado INTEGER DEFAULT 0,
                filas INTEGER DEFAULT 0,
                ms INTEGER DEFAULT 0,
                ip TEXT DEFAULT '')""",
            "CREATE INDEX IF NOT EXISTS idx_api_registro_clave ON api_registro (clave_id, momento)",
        ):
            conn.execute(sql)
        conn.commit()
        cols = set(columnas_de_tabla(conn, "api_claves"))
        for col, ddl in (("tipo", "TEXT DEFAULT 'clave'"), ("config", "TEXT DEFAULT ''")):
            if col not in cols:
                try:
                    conn.execute(f"ALTER TABLE api_claves ADD COLUMN {col} {ddl}")
                    conn.commit()
                except Exception:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
    finally:
        conn.close()


def _huella(clave):
    return hashlib.sha256(clave.encode("utf-8")).hexdigest()


def _permisos_de(fila):
    try:
        return [p for p in json.loads(fila["permisos"] or "[]") if p in CODIGOS]
    except (ValueError, TypeError):
        return []


# ════════════════════════════════════════════════════════════════════════
#  Respuestas y errores (siempre el mismo formato)
# ════════════════════════════════════════════════════════════════════════

class ErrorApi(Exception):
    def __init__(self, estado, codigo, mensaje, **extra):
        super().__init__(mensaje)
        self.estado, self.codigo, self.mensaje, self.extra = estado, codigo, mensaje, extra


def _error(estado, codigo, mensaje, **extra):
    cuerpo = {"error": {"codigo": codigo, "mensaje": mensaje, **extra}}
    return jsonify(cuerpo), estado


@bp_api_externa.errorhandler(ErrorApi)
def _manejar_error(e):
    if not request.path.startswith("/api/v1"):      # la pantalla de admin usa el formato de siempre
        return jsonify({"ok": False, "error": e.mensaje}), e.estado
    return _error(e.estado, e.codigo, e.mensaje, **e.extra)


# ════════════════════════════════════════════════════════════════════════
#  Límite de pedidos por minuto (en memoria, por clave)
# ════════════════════════════════════════════════════════════════════════

_ventanas = {}
_candado = threading.Lock()


def _pasa_limite(clave_id):
    """True si la clave todavía tiene pedidos este minuto. Devuelve también
    cuántos le quedan y en cuántos segundos se libera uno."""
    ahora = time.monotonic()
    with _candado:
        v = _ventanas.setdefault(clave_id, deque())
        while v and ahora - v[0] >= 60:
            v.popleft()
        if len(v) >= LIMITE_POR_MINUTO:
            return False, 0, max(1, int(60 - (ahora - v[0])) + 1)
        v.append(ahora)
        return True, LIMITE_POR_MINUTO - len(v), 0


def _ip():
    fwd = request.headers.get("X-Forwarded-For", "")
    return (fwd.split(",")[0].strip() if fwd else request.remote_addr) or ""


def _clave_del_pedido():
    aut = request.headers.get("Authorization", "")
    if aut[:7].lower() == "bearer ":
        return aut[7:].strip()
    return (request.headers.get("X-API-Key") or "").strip()


def _anotar(clave_id, estado, filas, inicio):
    """Deja el pedido en el registro y suma el uso de la clave. Si falla, el
    pedido igual se responde: el registro no puede tumbar la API."""
    try:
        conn = get_connection()
        try:
            momento = ahora_iso()
            conn.execute("""INSERT INTO api_registro (clave_id, momento, metodo, ruta, consulta, estado, filas, ms, ip)
                            VALUES (?,?,?,?,?,?,?,?,?)""",
                         (clave_id, momento, request.method, request.path,
                          request.query_string.decode("utf-8", "replace")[:300],
                          estado, filas, int((time.monotonic() - inicio) * 1000), _ip()[:60]))
            conn.execute("UPDATE api_claves SET ultimo_uso=?, ultima_ip=?, usos=COALESCE(usos,0)+1 WHERE id=?",
                         (momento, _ip()[:60], clave_id))
            # De vez en cuando se borra lo de hace más de 3 meses
            if secrets.randbelow(200) == 0:
                corte = (datetime.now() - timedelta(days=DIAS_DE_REGISTRO)).strftime("%Y-%m-%d")
                conn.execute("DELETE FROM api_registro WHERE momento < ?", (corte,))
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


def con_clave(permiso=None):
    """Decorador de cada ruta /api/v1: valida la clave, el permiso y el límite,
    y anota el pedido."""
    def deco(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            inicio = time.monotonic()
            clave = _clave_del_pedido()
            if not clave:
                return _error(401, "falta_clave",
                              "Falta la clave. Mandala en el encabezado: Authorization: Bearer ls_...")
            conn = get_connection()
            try:
                fila = conn.execute("SELECT * FROM api_claves WHERE huella=?", (_huella(clave),)).fetchone()
            finally:
                conn.close()
            if not fila or (fila["tipo"] or "clave") != "clave":
                return _error(401, "clave_invalida", "La clave no existe. Revisá que esté completa.")
            if not fila["activa"]:
                _anotar(fila["id"], 401, 0, inicio)
                return _error(401, "clave_revocada", "Esta clave fue revocada. Solicitá una nueva al administrador.")
            permisos = _permisos_de(fila)
            if permiso and permiso not in permisos:
                _anotar(fila["id"], 403, 0, inicio)
                nombre = next((p[1] for p in PERMISOS if p[0] == permiso), permiso)
                return _error(403, "sin_permiso",
                              f"Esta clave no tiene el permiso «{nombre}» ({permiso}).",
                              permiso_necesario=permiso, permisos_de_la_clave=permisos)
            ok, quedan, espera = _pasa_limite(fila["id"])
            if not ok:
                _anotar(fila["id"], 429, 0, inicio)
                resp, est = _error(429, "demasiados_pedidos",
                                   f"Se pasó el límite de {LIMITE_POR_MINUTO} pedidos por minuto. Probá en {espera} s.",
                                   reintentar_en=espera)
                resp.headers["Retry-After"] = str(espera)
                return resp, est
            g.api_clave = {"id": fila["id"], "nombre": fila["nombre"], "permisos": permisos}
            g.api_filas = 0
            try:
                resultado = f(*args, **kwargs)
            except ErrorApi as e:
                _anotar(fila["id"], e.estado, 0, inicio)
                return _error(e.estado, e.codigo, e.mensaje, **e.extra)
            except Exception as e:
                _anotar(fila["id"], 500, 0, inicio)
                return _error(500, "error_interno", "Algo falló de nuestro lado. Ya quedó anotado.",
                              detalle=type(e).__name__)
            resp, estado = (resultado if isinstance(resultado, tuple) else (resultado, 200))
            if not hasattr(resp, "headers"):
                resp = jsonify(resp)
            resp.headers["X-RateLimit-Limit"] = str(LIMITE_POR_MINUTO)
            resp.headers["X-RateLimit-Remaining"] = str(quedan)
            resp.headers["Cache-Control"] = "no-store"
            _anotar(fila["id"], estado, g.get("api_filas", 0), inicio)
            return resp, estado
        return wrapper
    return deco


# ════════════════════════════════════════════════════════════════════════
#  Ayudas para leer parámetros
# ════════════════════════════════════════════════════════════════════════
# Cada conjunto de datos (ds_*) recibe los parámetros como un dict: así lo
# usa igual la API (request.args) que un link de planilla (lo que se eligió
# al crearlo).

_RE_FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RE_MES = re.compile(r"^\d{4}-\d{2}$")


def _fecha(a, nombre):
    v = str(a.get(nombre) or "").strip()
    if not v:
        # «dias=90»: los últimos 90 días, contados desde hoy (sirve para una
        # planilla que siempre muestre lo reciente)
        if nombre == "desde" and a.get("dias") not in (None, ""):
            try:
                n = int(a.get("dias"))
            except (TypeError, ValueError):
                raise ErrorApi(400, "parametro_invalido", "«dias» tiene que ser un número entero.")
            if n < 0 or n > 3650:
                raise ErrorApi(400, "parametro_invalido", "«dias» tiene que estar entre 0 y 3650.")
            return (date.fromisoformat(_hoy_txt()) - timedelta(days=n)).isoformat()
        return None
    if not _RE_FECHA.match(v):
        raise ErrorApi(400, "fecha_invalida", f"«{nombre}» tiene que ser AAAA-MM-DD, por ejemplo 2026-11-01.")
    try:
        date.fromisoformat(v)
    except ValueError:
        raise ErrorApi(400, "fecha_invalida", f"«{nombre}»: {v} no es una fecha que exista.")
    return v


def _entero(a, nombre, defecto, minimo=0, maximo=None):
    v = a.get(nombre)
    if v in (None, ""):
        return defecto
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise ErrorApi(400, "parametro_invalido", f"«{nombre}» tiene que ser un número entero.")
    if n < minimo or (maximo is not None and n > maximo):
        tope = f" y {maximo}" if maximo is not None else ""
        raise ErrorApi(400, "parametro_invalido", f"«{nombre}» tiene que estar entre {minimo}{tope}.")
    return n


def _paginado(a):
    # _tope solo lo pone el link de planilla (un int); lo que llega por la URL es texto y no cuenta
    tope = a.get("_tope") if isinstance(a.get("_tope"), int) else None
    return (_entero(a, "limit", tope or FILAS_POR_DEFECTO, 1, tope or LIMITE_FILAS), _entero(a, "offset", 0, 0))


def _solo(fila, campos):
    return {c: fila[c] for c in campos if c in fila.keys()}


_cache_cols = {}


def _cols(conn, tabla, deseadas):
    """Las columnas pedidas que existen en esta base (las migraciones agregan
    columnas de a poco; la API no se rompe si falta una)."""
    if tabla not in _cache_cols:
        _cache_cols[tabla] = set(columnas_de_tabla(conn, tabla))
    return [c for c in deseadas if c in _cache_cols[tabla]]


def _vehiculo(conn, coche=None, vehiculo_id=None, obligatorio=True):
    """Busca el coche por su número interno (lo que usa todo el mundo), su
    chapa o su id."""
    if vehiculo_id not in (None, ""):
        try:
            vid = int(vehiculo_id)
        except (ValueError, TypeError):
            raise ErrorApi(400, "parametro_invalido", "«vehiculo_id» tiene que ser un número.")
        v = conn.execute("SELECT id, n_interno, patente FROM vehiculos WHERE id=?", (vid,)).fetchone()
        if not v:
            raise ErrorApi(404, "coche_no_existe", f"No hay ningún coche con id {vid}.")
        return v
    coche = str(coche or "").strip()
    if not coche:
        if obligatorio:
            raise ErrorApi(400, "falta_coche", "Falta el coche: «coche» (número interno o chapa) o «vehiculo_id».")
        return None
    v = conn.execute("SELECT id, n_interno, patente FROM vehiculos WHERE n_interno=? ORDER BY activo DESC, id",
                     (coche,)).fetchone()
    if not v:
        v = conn.execute("SELECT id, n_interno, patente FROM vehiculos WHERE UPPER(REPLACE(patente,' ',''))=?",
                         (coche.upper().replace(" ", ""),)).fetchone()
    if not v:
        raise ErrorApi(404, "coche_no_existe", f"No hay ningún coche con número interno o chapa «{coche}».")
    return v


def _filtro_coche(conn, a, where, params, columna="vehiculo_id"):
    if a.get("coche") or a.get("vehiculo_id"):
        v = _vehiculo(conn, a.get("coche"), a.get("vehiculo_id"))
        where.append(f"{columna}=?")
        params.append(v["id"])


def _filtro_fechas(a, where, params, columna):
    desde, hasta = _fecha(a, "desde"), _fecha(a, "hasta")
    if desde:
        where.append(f"SUBSTR({columna},1,10) >= ?")
        params.append(desde)
    if hasta:
        where.append(f"SUBSTR({columna},1,10) <= ?")
        params.append(hasta)


def _internos(conn):
    return {r["id"]: (r["n_interno"] or "") for r in conn.execute("SELECT id, n_interno FROM vehiculos").fetchall()}


def _num(v):
    """Los REAL que en realidad son enteros salen como enteros (12500 y no 12500.0)."""
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def _limpiar(d):
    return {k: _num(v) for k, v in d.items()}


def _w(where):
    return ("WHERE " + " AND ".join(where)) if where else ""


# ════════════════════════════════════════════════════════════════════════
#  LOS DATOS (los usa la API y los links de planilla)
# ════════════════════════════════════════════════════════════════════════

CAMPOS_VEH = ["id", "n_interno", "patente", "marca", "modelo", "año", "chasis", "asientos", "ejes", "tipo",
              "activo", "fecha_registro"]


def ds_vehiculos(a):
    from database import km_actual_flota
    limit, offset = _paginado(a)
    conn = get_connection()
    try:
        where, params = [], []
        if str(a.get("activos", "1")) not in ("0", "todos"):
            where.append("activo=1")
        if a.get("coche"):
            where.append("n_interno=?")
            params.append(str(a["coche"]).strip())
        total = conn.execute(f"SELECT COUNT(*) AS n FROM vehiculos {_w(where)}", params).fetchone()["n"]
        cols = _cols(conn, "vehiculos", CAMPOS_VEH)
        filas = conn.execute(f"SELECT {', '.join(cols)} FROM vehiculos {_w(where)} ORDER BY id LIMIT ? OFFSET ?",
                             params + [limit, offset]).fetchall()
        km = km_actual_flota(conn, [f["id"] for f in filas]) if filas else {}
    finally:
        conn.close()
    datos = []
    for f in filas:
        d = _limpiar(_solo(f, cols))
        d["anio"] = d.pop("año", None)
        d["activo"] = bool(d.get("activo"))
        d["km_actual"] = _num(round(float(km.get(f["id"], 0) or 0)))
        datos.append(d)
    return {"datos": datos, "total": total, "limit": limit, "offset": offset}


CAMPOS_OT = ["id", "vehiculo_id", "fecha_apertura", "fecha_cierre", "km", "conductor", "procedencia", "estado",
             "observaciones", "estado_compras", "proveedor_compras"]
CAMPOS_ITEM = ["id", "ot_id", "descripcion", "tipo", "estado", "prioridad", "costo", "precio_compras",
               "estado_pago", "material_pedido", "tecnico", "tecnico_otro", "fecha", "fecha_completado",
               "hecho_afuera", "taller_externo", "origen", "reportado_por", "observaciones"]


def _items_de(conn, ot_ids):
    if not ot_ids:
        return {}
    cols = _cols(conn, "ot_items", CAMPOS_ITEM)
    salida = {}
    ids = list(ot_ids)
    for i in range(0, len(ids), 500):
        tanda = ids[i:i + 500]
        for f in conn.execute(f"SELECT {', '.join(cols)} FROM ot_items WHERE ot_id IN ({','.join('?' * len(tanda))}) ORDER BY id",
                              tanda).fetchall():
            d = _limpiar(_solo(f, cols))
            if "hecho_afuera" in d:
                d["hecho_afuera"] = bool(d["hecho_afuera"])
            salida.setdefault(f["ot_id"], []).append(d)
    return salida


def _armar_ot(f, cols, internos, items):
    d = _limpiar(_solo(f, cols))
    d["coche"] = internos.get(f["vehiculo_id"], "")
    d["items"] = items.get(f["id"], [])
    d["costo_total"] = _num(round(sum(float(i.get("costo") or 0) for i in d["items"]), 2))
    return d


def una_ot(ot_id):
    """Una OT con sus ítems, en el formato de la API (también la usan los avisos)."""
    conn = get_connection()
    try:
        cols = _cols(conn, "ordenes_trabajo", CAMPOS_OT)
        f = conn.execute(f"SELECT {', '.join(cols)} FROM ordenes_trabajo WHERE id=?", (ot_id,)).fetchone()
        if not f:
            return None
        return _armar_ot(f, cols, _internos(conn), _items_de(conn, [ot_id]))
    finally:
        conn.close()


def ds_ots(a):
    limit, offset = _paginado(a)
    estado = str(a.get("estado") or "").strip().lower()
    if estado and estado not in ("abierta", "en_proceso", "cerrada"):
        raise ErrorApi(400, "parametro_invalido", "«estado» puede ser abierta, en_proceso o cerrada.")
    conn = get_connection()
    try:
        where, params = [], []
        # fecha_apertura puede traer la hora: se compara por los 10 primeros caracteres
        _filtro_fechas(a, where, params, "fecha_apertura")
        if estado:
            where.append("estado=?")
            params.append(estado)
        _filtro_coche(conn, a, where, params)
        total = conn.execute(f"SELECT COUNT(*) AS n FROM ordenes_trabajo {_w(where)}", params).fetchone()["n"]
        cols = _cols(conn, "ordenes_trabajo", CAMPOS_OT)
        filas = conn.execute(f"""SELECT {', '.join(cols)} FROM ordenes_trabajo {_w(where)}
                                 ORDER BY fecha_apertura DESC, id DESC LIMIT ? OFFSET ?""",
                             params + [limit, offset]).fetchall()
        items = _items_de(conn, [f["id"] for f in filas])
        internos = _internos(conn)
    finally:
        conn.close()
    return {"datos": [_armar_ot(f, cols, internos, items) for f in filas], "total": total,
            "limit": limit, "offset": offset}


CAMPOS_COMB = ["id", "vehiculo_id", "fecha", "odometro", "litros", "precio_litro", "costo_total", "estacion",
               "emblema", "lugar_carga", "chofer", "tanque_lleno", "origen", "cliente", "observaciones",
               "registrado_por", "cargado_el"]


def _armar_carga(f, cols, internos):
    d = _limpiar(_solo(f, cols))
    d["coche"] = internos.get(f["vehiculo_id"], "")
    if "tanque_lleno" in d:
        d["tanque_lleno"] = bool(d["tanque_lleno"])
    return d


def una_carga(cid):
    conn = get_connection()
    try:
        cols = _cols(conn, "combustible", CAMPOS_COMB)
        f = conn.execute(f"SELECT {', '.join(cols)} FROM combustible WHERE id=?", (cid,)).fetchone()
        return _armar_carga(f, cols, _internos(conn)) if f else None
    finally:
        conn.close()


def ds_combustible(a):
    limit, offset = _paginado(a)
    origen = str(a.get("origen") or "").strip().lower()
    if origen and origen not in ("taller", "corporativo", "rendicion"):
        raise ErrorApi(400, "parametro_invalido", "«origen» puede ser taller, corporativo o rendicion.")
    conn = get_connection()
    try:
        where, params = [], []
        _filtro_fechas(a, where, params, "fecha")
        if origen:
            where.append("origen=?")
            params.append(origen)
        _filtro_coche(conn, a, where, params)
        tot = conn.execute(f"""SELECT COUNT(*) AS n, COALESCE(SUM(litros),0) AS l, COALESCE(SUM(costo_total),0) AS m
                               FROM combustible {_w(where)}""", params).fetchone()
        cols = _cols(conn, "combustible", CAMPOS_COMB)
        filas = conn.execute(f"""SELECT {', '.join(cols)} FROM combustible {_w(where)}
                                 ORDER BY fecha DESC, id DESC LIMIT ? OFFSET ?""",
                             params + [limit, offset]).fetchall()
        internos = _internos(conn)
    finally:
        conn.close()
    return {"datos": [_armar_carga(f, cols, internos) for f in filas], "total": tot["n"],
            "limit": limit, "offset": offset,
            "litros_total": _num(round(float(tot["l"] or 0), 2)), "monto_total": _num(round(float(tot["m"] or 0)))}


CAMPOS_REND = ["id", "fecha_servicio", "cliente", "tramo", "chofer_usuario", "chofer_nombre", "bus_interno",
               "hora_inicio", "hora_fin", "km_inicial", "km_final", "pasajeros", "monto", "estado",
               "liquidado", "fecha_liquidacion", "liquidado_por", "observacion", "cargado_el"]


def _armar_rend(f, cols):
    d = _limpiar(_solo(f, cols))
    if "km_inicial" in d and "km_final" in d:
        try:
            d["km_recorridos"] = _num(max(0.0, float(d["km_final"] or 0) - float(d["km_inicial"] or 0)))
        except (TypeError, ValueError):
            d["km_recorridos"] = None
    d["liquidado"] = bool(d.get("liquidado"))
    return d


def una_rendicion(rid):
    conn = get_connection()
    try:
        cols = _cols(conn, "rendiciones_corp", CAMPOS_REND)
        f = conn.execute(f"SELECT {', '.join(cols)} FROM rendiciones_corp WHERE id=?", (rid,)).fetchone()
        return _armar_rend(f, cols) if f else None
    finally:
        conn.close()


def ds_rendiciones(a):
    limit, offset = _paginado(a)
    conn = get_connection()
    try:
        where, params = [], []
        _filtro_fechas(a, where, params, "fecha_servicio")
        if a.get("cliente"):
            where.append("UPPER(cliente)=?")
            params.append(str(a["cliente"]).strip().upper())
        if a.get("chofer"):
            where.append("chofer_usuario=?")
            params.append(str(a["chofer"]).strip())
        liq = a.get("liquidado")
        if str(liq) in ("0", "1"):
            where.append("COALESCE(liquidado,0)=?")
            params.append(int(liq))
        elif liq not in (None, ""):
            raise ErrorApi(400, "parametro_invalido", "«liquidado» puede ser 0 o 1.")
        tot = conn.execute(f"SELECT COUNT(*) AS n, COALESCE(SUM(monto),0) AS m FROM rendiciones_corp {_w(where)}",
                           params).fetchone()
        cols = _cols(conn, "rendiciones_corp", CAMPOS_REND)
        filas = conn.execute(f"""SELECT {', '.join(cols)} FROM rendiciones_corp {_w(where)}
                                 ORDER BY fecha_servicio DESC, id DESC LIMIT ? OFFSET ?""",
                             params + [limit, offset]).fetchall()
    finally:
        conn.close()
    return {"datos": [_armar_rend(f, cols) for f in filas], "total": tot["n"], "limit": limit, "offset": offset,
            "monto_total": _num(float(tot["m"] or 0))}   # de todo el filtro, no solo de esta página


def ds_pagos(a):
    limit, offset = _paginado(a)
    conn = get_connection()
    try:
        where, params = [], []
        _filtro_fechas(a, where, params, "fecha_pago")
        if a.get("chofer"):
            where.append("chofer_usuario=?")
            params.append(str(a["chofer"]).strip())
        tot = conn.execute(f"SELECT COUNT(*) AS n, COALESCE(SUM(monto),0) AS m FROM pagos_plus {_w(where)}",
                           params).fetchone()
        filas = conn.execute(f"""SELECT id, chofer_usuario, chofer_nombre, anio, semana_iso, monto, fecha_pago, pagado_por
                                 FROM pagos_plus {_w(where)} ORDER BY fecha_pago DESC, id DESC LIMIT ? OFFSET ?""",
                             params + [limit, offset]).fetchall()
    finally:
        conn.close()
    return {"datos": [_limpiar(dict(f)) for f in filas], "total": tot["n"], "limit": limit, "offset": offset,
            "monto_total": _num(float(tot["m"] or 0))}


def ds_costos(a):
    limit, offset = _paginado(a)
    mes_desde, mes_hasta = str(a.get("desde") or "").strip()[:7], str(a.get("hasta") or "").strip()[:7]
    if not mes_desde and a.get("meses") not in (None, ""):
        n = _entero(a, "meses", 0, 0, 240)
        y, m = map(int, _hoy_txt()[:7].split("-"))
        m -= n
        while m <= 0:
            m += 12
            y -= 1
        mes_desde = f"{y:04d}-{m:02d}"
    for nombre, v in (("desde", mes_desde), ("hasta", mes_hasta)):
        if v and not _RE_MES.match(v):
            raise ErrorApi(400, "parametro_invalido", f"«{nombre}» va como mes: AAAA-MM, por ejemplo 2026-10.")
    conn = get_connection()
    try:
        where, params = [], []
        if mes_desde:
            where.append("SUBSTR(mes,1,7) >= ?")
            params.append(mes_desde)
        if mes_hasta:
            where.append("SUBSTR(mes,1,7) <= ?")
            params.append(mes_hasta)
        if a.get("tipo"):
            where.append("tipo=?")
            params.append(str(a["tipo"]).strip())
        _filtro_coche(conn, a, where, params)
        tot = conn.execute(f"SELECT COUNT(*) AS n, COALESCE(SUM(monto),0) AS m FROM costos {_w(where)}", params).fetchone()
        filas = conn.execute(f"""SELECT id, vehiculo_id, mes, tipo, concepto, monto FROM costos {_w(where)}
                                 ORDER BY mes DESC, id DESC LIMIT ? OFFSET ?""", params + [limit, offset]).fetchall()
        internos = _internos(conn)
    finally:
        conn.close()
    return {"datos": [dict(_limpiar(dict(f)), coche=internos.get(f["vehiculo_id"], "")) for f in filas],
            "total": tot["n"], "limit": limit, "offset": offset, "monto_total": _num(float(tot["m"] or 0))}


def trafico_publicado(fecha, tipo="nacional"):
    """El tráfico de un día tal como se publicó (la última versión), o None."""
    conn = get_connection()
    try:
        dia = conn.execute("""SELECT id, version, publicado_el, publicado_por, modificado FROM trafico_dias
                              WHERE fecha=? AND tipo=?""", (fecha, tipo)).fetchone()
        v = None
        if dia and dia["version"]:
            v = conn.execute("SELECT * FROM trafico_versiones WHERE dia_id=? AND version=?",
                             (dia["id"], dia["version"])).fetchone()
    finally:
        conn.close()
    if not v:
        return None
    foto = json.loads(v["datos"] or "{}")
    salidas = []
    for b in foto.get("bloques", []):
        for lado in ("ida", "regreso"):
            for s in b.get(lado, []):
                salidas.append({"fecha": fecha, "corredor": b.get("nombre", ""), "lado": lado, "hora": s.get("hora", ""),
                                "destino": s.get("destino", ""), "coche": s.get("coche", ""),
                                "tripulante1": s.get("trip1", ""), "tripulante2": s.get("trip2", ""),
                                "nota": s.get("nota", "")})
    try:
        cambios = [c.get("txt", "") for c in json.loads(v["cambios"] or "[]")]
    except (ValueError, TypeError, AttributeError):
        cambios = []
    return {"fecha": fecha, "tipo": tipo, "titulo": foto.get("titulo", ""),
            "version": v["version"], "publicado_el": v["publicado_el"], "publicado_por": v["publicado_por"],
            "hay_cambios_sin_publicar": bool(dia["modificado"]), "cambios": cambios, "salidas": salidas}


def asignacion_publicada(fecha):
    """La asignación de corporativos de un día tal como se publicó (la última versión), o None."""
    conn = get_connection()
    try:
        dia = conn.execute("SELECT id, version, publicado_el, publicado_por, modificado FROM corp_asig_dias WHERE fecha=?",
                           (fecha,)).fetchone()
        v = None
        if dia and dia["version"]:
            v = conn.execute("SELECT * FROM corp_asig_versiones WHERE dia_id=? AND version=?",
                             (dia["id"], dia["version"])).fetchone()
    finally:
        conn.close()
    if not v:
        return None
    foto = json.loads(v["datos"] or "{}")
    filas = foto.get("filas", foto) if isinstance(foto, dict) else foto
    servicios = []
    for f in (filas if isinstance(filas, list) else []):
        servicios.append({"fecha": fecha, "cliente": f.get("cliente", ""), "tramo": f.get("tramo", ""),
                          "lado": f.get("lado", ""), "hora": f.get("hora", ""), "chofer": f.get("chofer_nombre", ""),
                          "chofer_usuario": f.get("chofer_usuario", ""), "coche": f.get("coche", ""),
                          "corre": f.get("lado") != "no_corre", "nota": f.get("nota", "") or f.get("detalle", "")})
    try:
        cambios = [c.get("txt", "") for c in json.loads(v["cambios"] or "[]")]
    except (ValueError, TypeError, AttributeError):
        cambios = []
    return {"fecha": fecha, "version": v["version"], "publicado_el": v["publicado_el"],
            "publicado_por": v["publicado_por"], "hay_cambios_sin_publicar": bool(dia["modificado"]),
            "cambios": cambios, "servicios": servicios}


def _fecha_trafico(txt):
    txt = str(txt or "").strip().lower()
    base = date.fromisoformat(_hoy_txt())
    if txt in ("", "hoy"):
        return base.isoformat()
    if txt in ("manana", "mañana"):
        return (base + timedelta(days=1)).isoformat()
    if txt == "ayer":
        return (base - timedelta(days=1)).isoformat()
    if not _RE_FECHA.match(txt):
        raise ErrorApi(400, "fecha_invalida", "La fecha va como AAAA-MM-DD (o hoy, mañana, ayer).")
    return txt


def ds_trafico(a):
    """Para la planilla: las salidas publicadas de hoy en adelante (por defecto
    hoy y mañana), una fila por salida."""
    tipo = str(a.get("tipo") or "nacional").strip().lower()
    if tipo not in ("nacional", "internacional"):
        raise ErrorApi(400, "parametro_invalido", "«tipo» puede ser nacional o internacional.")
    dias = _entero(a, "proximos", 2, 1, 14)
    base = date.fromisoformat(_hoy_txt())
    datos = []
    for i in range(dias):
        t = trafico_publicado((base + timedelta(days=i)).isoformat(), tipo)
        if t:
            datos += [dict(s, version=t["version"]) for s in t["salidas"]]
    return {"datos": datos, "total": len(datos), "limit": len(datos), "offset": 0}


CAMPOS_AGENCIA = ["id", "codigo", "nombre", "razon_social", "ruc", "representante", "telefono", "whatsapp", "email",
                  "direccion", "ciudad", "estado", "estado_motivo", "actualizado_el"]


def ds_agencias(a):
    limit, offset = _paginado(a)
    conn = get_connection()
    try:
        where, params = [], []
        if a.get("estado"):
            where.append("estado=?")
            params.append(str(a["estado"]).strip())
        if a.get("codigo"):
            where.append("UPPER(COALESCE(codigo,''))=?")
            params.append(str(a["codigo"]).strip().upper())
        total = conn.execute(f"SELECT COUNT(*) AS n FROM agencias {_w(where)}", params).fetchone()["n"]
        cols = _cols(conn, "agencias", CAMPOS_AGENCIA)
        filas = conn.execute(f"SELECT {', '.join(cols)} FROM agencias {_w(where)} ORDER BY nombre LIMIT ? OFFSET ?",
                             params + [limit, offset]).fetchall()
    finally:
        conn.close()
    return {"datos": [_limpiar(_solo(f, cols)) for f in filas], "total": total, "limit": limit, "offset": offset}


# Lo que se puede pedir como planilla: código → (nombre, permiso, función, filtros que se ofrecen)
DATOS = {
    "vehiculos":   ("Flota (coches y km)",                "flota",       ds_vehiculos),
    "ots":         ("Órdenes de trabajo, un ítem por fila", "ots",       ds_ots),
    "ots_resumen": ("Órdenes de trabajo, una OT por fila",  "ots",       ds_ots),
    "combustible": ("Cargas de combustible",              "combustible", ds_combustible),
    "rendiciones": ("Rendiciones de corporativos",        "rendiciones", ds_rendiciones),
    "pagos":       ("Pagos de plus a choferes",           "rendiciones", ds_pagos),
    "costos":      ("Costos por coche y mes",             "costos",      ds_costos),
    "trafico":     ("Tráfico publicado (hoy y mañana)",   "trafico",     ds_trafico),
    "agencias":    ("Agencias de venta",                  "agencias",    ds_agencias),
}


# ════════════════════════════════════════════════════════════════════════
#  CSV (para Excel, Google Sheets y Power BI)
# ════════════════════════════════════════════════════════════════════════

def _filas_planas(dato, datos):
    """Una tabla plana: las OT se abren en un ítem por fila (o se resumen)."""
    if dato == "ots":
        salida = []
        for o in datos:
            cab = {"ot": o.get("id"), "coche": o.get("coche"), "fecha_apertura": o.get("fecha_apertura"),
                   "fecha_cierre": o.get("fecha_cierre"), "estado_ot": o.get("estado"), "km": o.get("km"),
                   "conductor": o.get("conductor"), "procedencia": o.get("procedencia")}
            items = o.get("items") or [{}]
            for it in items:
                salida.append(dict(cab, item=it.get("id"), descripcion=it.get("descripcion"), tipo=it.get("tipo"),
                                   estado_item=it.get("estado"), prioridad=it.get("prioridad"),
                                   tecnico=it.get("tecnico") or it.get("tecnico_otro"), costo=it.get("costo"),
                                   fecha_item=it.get("fecha"), completado=it.get("fecha_completado"),
                                   hecho_afuera=it.get("hecho_afuera"), taller_externo=it.get("taller_externo")))
        return salida
    if dato == "ots_resumen":
        return [{k: v for k, v in o.items() if k != "items"} | {"items": len(o.get("items") or [])} for o in datos]
    return datos


def a_csv(dato, datos):
    import csv
    import io
    filas = _filas_planas(dato, datos)
    columnas = []
    for f in filas:
        for k in f.keys():
            if k not in columnas:
                columnas.append(k)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(columnas or ["sin_datos"])
    for f in filas:
        fila = []
        for c in columnas:
            v = f.get(c)
            if isinstance(v, bool):
                v = "si" if v else "no"
            elif v is None:
                v = ""
            elif isinstance(v, (dict, list)):
                v = json.dumps(v, ensure_ascii=False)
            fila.append(v)
        w.writerow(fila)
    return buf.getvalue()


def _responder(dato, r):
    """La respuesta de una lista: JSON (con el enlace a la página siguiente) o
    CSV si se pidió ?formato=csv."""
    from flask import Response
    g.api_filas = len(r["datos"])
    if str(request.args.get("formato") or "").lower() == "csv":
        return Response(a_csv(dato, r["datos"]), mimetype="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f"inline; filename={dato}.csv"})
    siguiente = None
    if r["offset"] + len(r["datos"]) < r["total"]:
        args = request.args.to_dict()
        args.pop("clave", None)
        args.update(limit=r["limit"], offset=r["offset"] + r["limit"])
        siguiente = request.base_url + "?" + "&".join(f"{k}={v}" for k, v in args.items())
    return jsonify(dict(r, siguiente=siguiente))


# ════════════════════════════════════════════════════════════════════════
#  LECTURA
# ════════════════════════════════════════════════════════════════════════

@bp_api_externa.route("/api/v1/estado")
@con_clave()
def v1_estado():
    c = g.api_clave
    return jsonify({"ok": True, "sistema": "La Santaniana", "version_api": VERSION,
                    "clave": c["nombre"], "permisos": c["permisos"],
                    "hora_servidor": ahora_iso(), "limite_por_minuto": LIMITE_POR_MINUTO,
                    "documentacion": request.host_url.rstrip("/") + "/api/v1/docs"})


@bp_api_externa.route("/api/v1/vehiculos")
@con_clave("flota")
def v1_vehiculos():
    return _responder("vehiculos", ds_vehiculos(request.args))


@bp_api_externa.route("/api/v1/ots")
@con_clave("ots")
def v1_ots():
    return _responder("ots", ds_ots(request.args))


@bp_api_externa.route("/api/v1/ots/<int:ot_id>")
@con_clave("ots")
def v1_ot(ot_id):
    d = una_ot(ot_id)
    if not d:
        raise ErrorApi(404, "no_existe", f"No hay ninguna OT con el número {ot_id}.")
    g.api_filas = 1
    return jsonify(d)


@bp_api_externa.route("/api/v1/combustible")
@con_clave("combustible")
def v1_combustible():
    return _responder("combustible", ds_combustible(request.args))


@bp_api_externa.route("/api/v1/rendiciones")
@con_clave("rendiciones")
def v1_rendiciones():
    return _responder("rendiciones", ds_rendiciones(request.args))


@bp_api_externa.route("/api/v1/pagos")
@con_clave("rendiciones")
def v1_pagos():
    return _responder("pagos", ds_pagos(request.args))


@bp_api_externa.route("/api/v1/costos")
@con_clave("costos")
def v1_costos():
    return _responder("costos", ds_costos(request.args))


@bp_api_externa.route("/api/v1/asignacion/<fecha>")
@con_clave("trafico")
def v1_asignacion(fecha):
    fecha = _fecha_trafico(fecha)
    a = asignacion_publicada(fecha)
    if not a:
        raise ErrorApi(404, "sin_publicar", f"La asignación de corporativos del {fecha} todavía no se publicó.")
    g.api_filas = len(a["servicios"])
    return jsonify(a)


@bp_api_externa.route("/api/v1/agencias")
@con_clave("agencias")
def v1_agencias():
    return _responder("agencias", ds_agencias(request.args))


@bp_api_externa.route("/api/v1/trafico/<fecha>")
@con_clave("trafico")
def v1_trafico(fecha):
    fecha = _fecha_trafico(fecha)
    tipo = (request.args.get("tipo") or "nacional").strip().lower()
    if tipo not in ("nacional", "internacional"):
        raise ErrorApi(400, "parametro_invalido", "«tipo» puede ser nacional o internacional.")
    t = trafico_publicado(fecha, tipo)
    if not t:
        raise ErrorApi(404, "sin_publicar", f"El tráfico {tipo} del {fecha} todavía no se publicó.")
    g.api_filas = len(t["salidas"])
    if str(request.args.get("formato") or "").lower() == "csv":
        from flask import Response
        return Response(a_csv("trafico", t["salidas"]), mimetype="text/csv; charset=utf-8")
    return jsonify(t)


# ════════════════════════════════════════════════════════════════════════
#  LINKS DE PLANILLA (Excel, Google Sheets, Power BI)
# ════════════════════════════════════════════════════════════════════════
# Un link es una clave de un solo uso posible: leer UN conjunto de datos con
# los filtros que se eligieron al crearlo. La clave va en el link mismo,
# porque Excel y Google Sheets no saben mandar encabezados.

TOPE_PLANILLA = 20000


@bp_api_externa.route("/api/v1/planilla/<token>.csv")
def v1_planilla(token):
    from flask import Response
    inicio = time.monotonic()
    conn = get_connection()
    try:
        fila = conn.execute("SELECT * FROM api_claves WHERE huella=?", (_huella(token),)).fetchone()
    finally:
        conn.close()
    if not fila or (fila["tipo"] or "clave") != "planilla":
        return Response("error\nEste link no existe. Solicitá uno nuevo al administrador.\n", 404, mimetype="text/csv")
    if not fila["activa"]:
        _anotar(fila["id"], 401, 0, inicio)
        return Response("error\nEste link fue desactivado. Solicitá uno nuevo al administrador.\n", 401, mimetype="text/csv")
    ok, _, espera = _pasa_limite(fila["id"])
    if not ok:
        _anotar(fila["id"], 429, 0, inicio)
        return Response(f"error\nDemasiados pedidos: probá en {espera} segundos.\n", 429, mimetype="text/csv",
                        headers={"Retry-After": str(espera)})
    try:
        conf = json.loads(fila["config"] or "{}")
    except ValueError:
        conf = {}
    dato = conf.get("dato")
    if dato not in DATOS:
        _anotar(fila["id"], 500, 0, inicio)
        return Response("error\nEl link está mal armado: crealo de nuevo.\n", 500, mimetype="text/csv")
    a = {k: v for k, v in (conf.get("filtros") or {}).items() if v not in (None, "")}
    a["_tope"] = TOPE_PLANILLA
    try:
        r = DATOS[dato][2](a)
    except ErrorApi as e:
        _anotar(fila["id"], e.estado, 0, inicio)
        return Response(f"error\n{e.mensaje}\n", e.estado, mimetype="text/csv")
    _anotar(fila["id"], 200, len(r["datos"]), inicio)
    return Response(a_csv(dato, r["datos"]), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"inline; filename={dato}.csv", "Cache-Control": "no-store"})


# ════════════════════════════════════════════════════════════════════════
#  ESCRITURA
# ════════════════════════════════════════════════════════════════════════

def _cuerpo():
    d = request.get_json(silent=True)
    if not isinstance(d, dict):
        raise ErrorApi(400, "json_invalido", "El cuerpo tiene que ser JSON (Content-Type: application/json).")
    return d


def _numero(d, nombre, obligatorio=False, minimo=None):
    v = d.get(nombre)
    if v in (None, ""):
        if obligatorio:
            raise ErrorApi(400, "falta_campo", f"Falta «{nombre}».")
        return None
    try:
        n = float(str(v).replace(",", "."))
    except ValueError:
        raise ErrorApi(400, "campo_invalido", f"«{nombre}» tiene que ser un número.")
    if minimo is not None and n < minimo:
        raise ErrorApi(400, "campo_invalido", f"«{nombre}» no puede ser menor a {minimo}.")
    return n


def cargar_combustible(d, quien):
    """Registra una carga que llega de otro sistema. Devuelve lo cargado o
    tira ErrorApi (409 si ya estaba: un reintento no la duplica)."""
    from database import registrar_carga_combustible
    fecha = str(d.get("fecha") or _hoy_txt()).strip()[:10]
    if not _RE_FECHA.match(fecha):
        raise ErrorApi(400, "fecha_invalida", "«fecha» tiene que ser AAAA-MM-DD.")
    if fecha > _hoy_txt():
        raise ErrorApi(400, "fecha_invalida", "La fecha no puede ser futura.")
    litros = _numero(d, "litros", obligatorio=True, minimo=0.01)
    if litros > 2000:
        raise ErrorApi(400, "campo_invalido", "«litros»: más de 2.000 litros en una carga no es posible.")
    precio = _numero(d, "precio_litro", minimo=0) or 0
    costo = _numero(d, "costo_total", minimo=0) or 0
    odometro = _numero(d, "odometro", minimo=0) or 0
    origen = str(d.get("origen") or "taller").strip().lower()
    if origen not in ("taller", "corporativo"):
        raise ErrorApi(400, "campo_invalido", "«origen» puede ser taller o corporativo.")
    conn = get_connection()
    try:
        v = _vehiculo(conn, d.get("coche"), d.get("vehiculo_id"))
        repetida = conn.execute("""SELECT id FROM combustible WHERE vehiculo_id=? AND fecha=?
                                   AND ABS(litros-?)<0.01 AND ABS(COALESCE(odometro,0)-?)<0.5""",
                                (v["id"], fecha, litros, odometro)).fetchone()
    finally:
        conn.close()
    if repetida:
        raise ErrorApi(409, "ya_cargada", "Esa carga ya está registrada (mismo coche, fecha, litros y odómetro).",
                       id=repetida["id"])
    cid = registrar_carga_combustible({
        "vehiculo_id": v["id"], "fecha": fecha, "odometro": odometro, "litros": litros,
        "precio_litro": precio, "costo_total": costo,
        "estacion": str(d.get("estacion") or "")[:120], "emblema": str(d.get("emblema") or "")[:60],
        "lugar_carga": str(d.get("lugar_carga") or "")[:120], "chofer": str(d.get("chofer") or "")[:120],
        "tanque_lleno": d.get("tanque_lleno", True) not in (False, 0, "0", "no", "false"),
        "observaciones": str(d.get("observaciones") or "")[:500],
        "registrado_por": f"API · {quien}"[:120],
        "origen": origen, "cliente": str(d.get("cliente") or "")[:120],
    })
    return {"ok": True, "id": cid, "coche": v["n_interno"], "fecha": fecha, "litros": _num(litros)}


def informar_km(d, quien):
    """Actualiza el km de un coche. No baja el km ni acepta saltos raros sin «forzar»."""
    from database import guardar_km_manual, km_actual_vehiculo
    km = _numero(d, "km", obligatorio=True, minimo=0)
    conn = get_connection()
    try:
        v = _vehiculo(conn, d.get("coche"), d.get("vehiculo_id"))
    finally:
        conn.close()
    antes = float(km_actual_vehiculo(v["id"]) or 0)
    forzar = d.get("forzar") in (True, 1, "1", "true", "si", "sí")
    # El odómetro no va para atrás: un número menor casi siempre es un error de carga
    if km < antes and not forzar:
        raise ErrorApi(409, "km_menor", f"El coche ya tiene {int(antes):,} km; no se baja el km sin «forzar»: true."
                       .replace(",", "."), km_actual=_num(round(antes)))
    if km > antes + 5000 and not forzar:
        raise ErrorApi(409, "km_salto", f"Son {int(km - antes):,} km más que el último registro; si es correcto mandá «forzar»: true."
                       .replace(",", "."), km_actual=_num(round(antes)))
    guardar_km_manual(v["id"], km)
    try:
        from database import registrar_auditoria
        registrar_auditoria(usuario=f"API · {quien}", rol="api",
                            accion=f"Informó el km del coche {v['n_interno']}", categoria="Vehículos",
                            detalle=f"{int(antes):,} → {int(km):,} km".replace(",", "."))
    except Exception:
        pass
    return {"ok": True, "coche": v["n_interno"], "km_anterior": _num(round(antes)),
            "km_actual": _num(round(float(km_actual_vehiculo(v["id"]) or 0)))}


@bp_api_externa.route("/api/v1/combustible", methods=["POST"])
@con_clave("combustible:escribir")
def v1_cargar_combustible():
    r = cargar_combustible(_cuerpo(), g.api_clave["nombre"])
    g.api_filas = 1
    return jsonify(r), 201


@bp_api_externa.route("/api/v1/kilometraje", methods=["POST"])
@con_clave("km:escribir")
def v1_kilometraje():
    r = informar_km(_cuerpo(), g.api_clave["nombre"])
    g.api_filas = 1
    return jsonify(r)


@bp_api_externa.route("/api/v1/<path:resto>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def v1_no_existe(resto):
    return _error(404, "ruta_no_existe", f"No existe /api/v1/{resto}. La lista está en /api/v1/docs.")


# ════════════════════════════════════════════════════════════════════════
#  DOCUMENTACIÓN (pública, sin clave)
# ════════════════════════════════════════════════════════════════════════

@bp_api_externa.route("/api/v1/docs")
@bp_api_externa.route("/api/v1/")
@bp_api_externa.route("/api/v1")
def v1_docs():
    return render_template("api_docs.html", base=request.host_url.rstrip("/"), permisos=PERMISOS,
                           limite=LIMITE_POR_MINUTO, max_filas=LIMITE_FILAS, por_defecto=FILAS_POR_DEFECTO,
                           version=VERSION)


# ════════════════════════════════════════════════════════════════════════
#  ADMINISTRACIÓN DE CLAVES (con sesión, solo admin)
# ════════════════════════════════════════════════════════════════════════

def _solo_admin():
    if session.get("rol") != "admin":
        raise ErrorApi(403, "sin_permiso", "Solo administración maneja las claves de la API.")


def _quien():
    return session.get("nombre") or session.get("usuario") or "?"


def _clave_publica(f, uso7=None):
    tipo = f["tipo"] or "clave"
    extra = {}
    if tipo == "planilla":
        try:
            conf = json.loads(f["config"] or "{}")
        except ValueError:
            conf = {}
        extra = {"dato": conf.get("dato"), "dato_nombre": DATOS.get(conf.get("dato"), ("",))[0],
                 "filtros": conf.get("filtros") or {},
                 "url": _url_planilla(conf["token"]) if conf.get("token") and f["activa"] else ""}
    return {**extra, "tipo": tipo, "id": f["id"], "nombre": f["nombre"], "prefijo": f["prefijo"], "permisos": _permisos_de(f),
            "nota": f["nota"] or "", "activa": bool(f["activa"]), "creada_el": f["creada_el"],
            "creada_por": f["creada_por"], "revocada_el": f["revocada_el"] or "",
            "revocada_por": f["revocada_por"] or "", "ultimo_uso": f["ultimo_uso"] or "",
            "ultima_ip": f["ultima_ip"] or "", "usos": f["usos"] or 0,
            "usos_7_dias": (uso7 or {}).get(f["id"], 0)}


@bp_api_externa.route("/api/api_claves")
def admin_claves():
    _solo_admin()
    corte = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    conn = get_connection()
    try:
        filas = conn.execute("SELECT * FROM api_claves ORDER BY activa DESC, id DESC").fetchall()
        uso7 = {r["clave_id"]: r["n"] for r in conn.execute(
            "SELECT clave_id, COUNT(*) AS n FROM api_registro WHERE momento >= ? GROUP BY clave_id", (corte,)).fetchall()}
    finally:
        conn.close()
    return jsonify({"claves": [_clave_publica(f, uso7) for f in filas],
                    "permisos": [{"codigo": c, "nombre": n, "detalle": det} for c, n, det in PERMISOS],
                    "datos": [{"codigo": k, "nombre": v[0]} for k, v in DATOS.items()],
                    "docs": request.host_url.rstrip("/") + "/api/v1/docs", "base": request.host_url.rstrip("/")})


@bp_api_externa.route("/api/api_claves", methods=["POST"])
def admin_crear_clave():
    """Crea una clave para programadores (tipo=clave, con permisos) o un link
    de planilla (tipo=planilla, con el dato y sus filtros)."""
    _solo_admin()
    d = request.get_json(silent=True) or {}
    nombre = str(d.get("nombre") or "").strip()[:80]
    if not nombre:
        return jsonify({"ok": False, "error": "Poné un nombre: para qué es (ej.: Contabilidad, Power BI gerencia)."}), 400
    tipo = "planilla" if d.get("tipo") == "planilla" else "clave"
    config = ""
    if tipo == "planilla":
        dato = d.get("dato")
        if dato not in DATOS:
            return jsonify({"ok": False, "error": "Elegí qué datos va a tener la planilla."}), 400
        permitidos = {"dias", "meses", "estado", "origen", "coche", "cliente", "liquidado", "tipo", "proximos", "activos"}
        filtros = {k: str(v).strip()[:40] for k, v in (d.get("filtros") or {}).items()
                   if k in permitidos and v not in (None, "")}
        try:   # que el link funcione antes de entregarlo
            DATOS[dato][2](dict(filtros, limit=1))
        except ErrorApi as e:
            return jsonify({"ok": False, "error": e.mensaje}), 400
        permisos = [DATOS[dato][1]]
    else:
        permisos = [p for p in (d.get("permisos") or []) if p in CODIGOS]
        if not permisos:
            return jsonify({"ok": False, "error": "Marcá al menos un permiso."}), 400
    clave = ("lp_" if tipo == "planilla" else "ls_") + secrets.token_urlsafe(30).replace("-", "x").replace("_", "y")
    if tipo == "planilla":
        # El link se puede volver a copiar (la clave del link no sirve para
        # nada más que leer esa planilla); la de programadores no se guarda.
        config = json.dumps({"dato": dato, "filtros": filtros, "token": clave}, ensure_ascii=False)
    conn = get_connection()
    try:
        cur = conn.execute("""INSERT INTO api_claves (nombre, prefijo, huella, permisos, nota, activa, creada_el,
                                                      creada_por, tipo, config)
                              VALUES (?,?,?,?,?,1,?,?,?,?)""",
                           (nombre, clave[:11], _huella(clave), json.dumps(permisos), str(d.get("nota") or "")[:300],
                            ahora_iso(), _quien(), tipo, config))
        conn.commit()
        cid = cur.lastrowid
    finally:
        conn.close()
    _auditar(f"Creó {'el link de planilla' if tipo == 'planilla' else 'la clave de API'} «{nombre}»", ", ".join(permisos))
    salida = {"ok": True, "id": cid, "prefijo": clave[:11], "tipo": tipo}
    if tipo == "planilla":
        salida["url"] = _url_planilla(clave)
    else:
        salida["clave"] = clave
    return jsonify(salida)


def _url_planilla(token):
    return request.host_url.rstrip("/") + f"/api/v1/planilla/{token}.csv"


@bp_api_externa.route("/api/api_claves/<int:cid>/revocar", methods=["POST"])
def admin_revocar_clave(cid):
    _solo_admin()
    conn = get_connection()
    try:
        f = conn.execute("SELECT nombre, activa FROM api_claves WHERE id=?", (cid,)).fetchone()
        if not f:
            return jsonify({"ok": False, "error": "Esa clave no existe."}), 404
        conn.execute("UPDATE api_claves SET activa=0, revocada_el=?, revocada_por=? WHERE id=?",
                     (ahora_iso(), _quien(), cid))
        conn.commit()
    finally:
        conn.close()
    with _candado:
        _ventanas.pop(cid, None)
    _auditar(f"Revocó la clave de API «{f['nombre']}»")
    return jsonify({"ok": True})


@bp_api_externa.route("/api/api_claves/<int:cid>/permisos", methods=["POST"])
def admin_permisos_clave(cid):
    _solo_admin()
    d = request.get_json(silent=True) or {}
    permisos = [p for p in (d.get("permisos") or []) if p in CODIGOS]
    if not permisos:
        return jsonify({"ok": False, "error": "Marcá al menos un permiso."}), 400
    conn = get_connection()
    try:
        f = conn.execute("SELECT nombre FROM api_claves WHERE id=?", (cid,)).fetchone()
        if not f:
            return jsonify({"ok": False, "error": "Esa clave no existe."}), 404
        conn.execute("UPDATE api_claves SET permisos=? WHERE id=?", (json.dumps(permisos), cid))
        conn.commit()
    finally:
        conn.close()
    _auditar(f"Cambió los permisos de la clave de API «{f['nombre']}»", ", ".join(permisos))
    return jsonify({"ok": True})


@bp_api_externa.route("/api/api_claves/<int:cid>/registro")
def admin_registro_clave(cid):
    _solo_admin()
    conn = get_connection()
    try:
        filas = conn.execute("""SELECT momento, metodo, ruta, consulta, estado, filas, ms, ip FROM api_registro
                                WHERE clave_id=? ORDER BY id DESC LIMIT 100""", (cid,)).fetchall()
    finally:
        conn.close()
    return jsonify({"registro": [dict(f) for f in filas]})


def _auditar(accion, detalle=""):
    try:
        from database import registrar_auditoria
        registrar_auditoria(usuario=_quien(), rol=session.get("rol") or "", accion=accion,
                            categoria="Sistema", detalle=detalle)
    except Exception:
        pass
