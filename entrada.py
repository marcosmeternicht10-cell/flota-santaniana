"""
entrada.py — La bandeja de entrada: lo que otro sistema le manda a La Santaniana

La mitad que faltaba para que la integración sea de ida y vuelta (pensado
para Delta, el sistema de pasajes, pero sirve para cualquiera). El otro
sistema manda cualquier tipo de dato a un solo link:

    POST /api/v1/entrada/<tipo>          con la clave (permiso «recibir»)
    cuerpo: un registro, una lista, o {"registros": [...]}  (JSON)
            o un CSV (Content-Type: text/csv)

  · Lo que el sistema ya entiende se aplica solo:
        combustible   una carga (coche, litros, precio_litro, odometro…)
        kilometraje   el km de un coche (coche, km)
        agencias      alta o cambio de una agencia, por su código de Delta
        fallas        un pedido de OT (coche, descripcion, chofer, km)
        costos        un costo de un coche (coche, mes, tipo, concepto, monto)
  · Cualquier otro tipo (ventas, pasajeros, liquidaciones, servicios…) se
    guarda tal cual, a la vista en Sistema → Integraciones, y se puede leer
    con GET /api/v1/entrada/<tipo>. No se pierde nada.
  · Cada registro puede traer su identificador del otro sistema («id»,
    «id_externo» o «codigo»). Si llega dos veces, no se duplica: si vino
    igual se ignora; si vino cambiado se actualiza (y si ya se había aplicado
    algo que no se puede pisar, queda marcado para revisar).
  · Si el otro sistema solo exporta archivos (Excel o CSV), se suben a mano
    en la misma pantalla y entran por el mismo camino.

Enganche en app.py:
    from entrada import bp_entrada, init_entrada
    init_entrada()
    app.register_blueprint(bp_entrada)
"""

import csv
import io
import json
import re
import unicodedata

from flask import Blueprint, request, jsonify, session, g
from db_compat import get_connection, USE_POSTGRES

from hora_local import ahora_iso
from api_externa import con_clave, ErrorApi, cargar_combustible, informar_km, _vehiculo, _num

bp_entrada = Blueprint("entrada", __name__)

PK = "SERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"

MAX_REGISTROS = 1000          # por pedido
MAX_ARCHIVO = 5 * 1024 * 1024
RE_TIPO = re.compile(r"^[a-z0-9_]{2,40}$")

# Los que se aplican solos, con lo que hace cada uno (se muestra en la pantalla y en la documentación)
CONOCIDOS = {
    "combustible": "Se registra la carga en el coche",
    "kilometraje": "Se actualiza el km del coche",
    "agencias":    "Se crea o actualiza la agencia (por su código)",
    "fallas":      "Entra como pedido de OT en Pedidos de choferes",
    "costos":      "Se suma al costo del coche en ese mes",
}


def init_entrada():
    conn = get_connection()
    try:
        for sql in (
            f"""CREATE TABLE IF NOT EXISTS integ_entrada (
                id {PK},
                origen TEXT DEFAULT '',          -- el nombre de la clave (Delta) o «archivo: …»
                clave_id INTEGER,
                tipo TEXT NOT NULL,
                id_externo TEXT DEFAULT '',
                datos TEXT DEFAULT '',
                estado TEXT DEFAULT 'guardado',  -- aplicado | guardado | revisar | error
                detalle TEXT DEFAULT '',
                ref TEXT DEFAULT '',             -- lo que se creó acá: combustible:12, agencia:5…
                recibido_el TEXT DEFAULT '',
                actualizado_el TEXT DEFAULT '',
                veces INTEGER DEFAULT 1)""",
            "CREATE INDEX IF NOT EXISTS idx_integ_entrada_tipo ON integ_entrada (tipo, id_externo)",
        ):
            conn.execute(sql)
        conn.commit()
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════════
#  Leer lo que llega
# ════════════════════════════════════════════════════════════════════════

def _clave_campo(k):
    """«Nº Interno» → nro_interno; «Fecha Servicio» → fecha_servicio."""
    k = unicodedata.normalize("NFKD", str(k or "")).encode("ascii", "ignore").decode().strip().lower()
    k = k.replace("nº", "nro").replace("n°", "nro")
    return re.sub(r"[^a-z0-9]+", "_", k).strip("_")[:60]


def _normalizar(reg):
    if not isinstance(reg, dict):
        raise ValueError("cada registro tiene que ser un objeto con campos")
    out = {}
    for k, v in reg.items():
        if isinstance(v, str):
            v = v.strip()
        out[_clave_campo(k)] = v
    # Sinónimos comunes para el coche
    for alias in ("interno", "nro_interno", "n_interno", "bus", "bus_interno", "unidad", "coche_nro"):
        if not out.get("coche") and out.get(alias) not in (None, ""):
            out["coche"] = str(out[alias])
    return out


def _id_externo(tipo, reg):
    for k in ("id_externo", "id", "codigo", "numero", "nro"):
        if reg.get(k) not in (None, ""):
            return str(reg[k]).strip()[:80]
    return ""


def registros_del_pedido():
    """Los registros del cuerpo: JSON (uno, lista o {"registros": […]}) o CSV."""
    ctype = (request.content_type or "").lower()
    if "csv" in ctype or "text/plain" in ctype:
        texto = request.get_data(as_text=True)
        return leer_csv(texto)
    d = request.get_json(silent=True)
    if d is None:
        raise ErrorApi(400, "cuerpo_invalido", "Mandá JSON (Content-Type: application/json) o CSV (text/csv).")
    if isinstance(d, dict) and isinstance(d.get("registros"), list):
        d = d["registros"]
    if isinstance(d, dict):
        d = [d]
    if not isinstance(d, list):
        raise ErrorApi(400, "cuerpo_invalido", "Mandá un registro, una lista, o {\"registros\": [...]}.")
    return d


def leer_csv(texto):
    texto = texto.lstrip("﻿")
    muestra = texto[:4000]
    try:
        dialecto = csv.Sniffer().sniff(muestra, delimiters=",;\t|")
    except csv.Error:
        dialecto = csv.excel
    return [dict(f) for f in csv.DictReader(io.StringIO(texto), dialect=dialecto)
            if any(str(v or "").strip() for v in f.values())]


def leer_excel(datos):
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(datos), read_only=True, data_only=True)
    ws = wb.worksheets[0]
    filas = ws.iter_rows(values_only=True)
    cab = None
    salida = []
    for f in filas:
        if cab is None:
            if f and sum(1 for x in f if x not in (None, "")) >= 2:    # la primera fila con títulos
                cab = [str(x or f"col{i + 1}").strip() for i, x in enumerate(f)]
            continue
        if not any(x not in (None, "") for x in f):
            continue
        reg = {}
        for k, v in zip(cab, f):
            if hasattr(v, "isoformat"):
                v = v.isoformat()[:10] if getattr(v, "hour", 0) == 0 and getattr(v, "minute", 0) == 0 else v.isoformat()
            reg[k] = v
        salida.append(reg)
    return salida


# ════════════════════════════════════════════════════════════════════════
#  Aplicar lo que el sistema entiende
# ════════════════════════════════════════════════════════════════════════

def _aplicar_agencia(r, quien):
    import agencias as AG
    cod = str(r.get("codigo") or "").strip().upper()
    if not cod:
        raise ErrorApi(400, "falta_campo", "La agencia tiene que traer su «codigo».")
    datos = {k: r[k] for k in AG.CAMPOS_AGENCIA if k in r and k != "codigo" and r[k] not in (None, "")}
    conn = get_connection()
    try:
        ya = conn.execute("SELECT id FROM agencias WHERE UPPER(COALESCE(codigo,''))=?", (cod,)).fetchone()
    finally:
        conn.close()
    try:
        if ya:
            AG.editar_agencia(ya["id"], datos, quien)
            return f"agencia:{ya['id']}", "Agencia actualizada"
        if not datos.get("nombre"):
            raise ErrorApi(400, "falta_campo", "Para dar de alta una agencia hace falta «nombre».")
        aid = AG.crear_agencia(dict(datos, codigo=cod), quien)
        return f"agencia:{aid}", "Agencia nueva"
    except AG.Error as e:
        raise ErrorApi(400, "agencia_invalida", str(e))


def _aplicar_falla(r, quien):
    import ot_pedidos
    desc = str(r.get("descripcion") or r.get("falla") or r.get("problema") or "").strip()
    if not desc:
        raise ErrorApi(400, "falta_campo", "La falla tiene que traer «descripcion».")
    conn = get_connection()
    try:
        v = _vehiculo(conn, r.get("coche"), r.get("vehiculo_id"))
    finally:
        conn.close()
    try:
        km = float(str(r.get("km") or 0).replace(",", "."))
    except ValueError:
        km = 0
    rid = ot_pedidos.crear_reporte(v["id"], [{"descripcion": desc, "tipo": "correctivo", "estado": "pendiente"}],
                                   str(r.get("chofer") or quien)[:80], km=km)
    return f"pedido:{rid}", f"Pedido de OT del coche {v['n_interno']}"


def _aplicar_costo(r, quien):
    from database import agregar_costo
    mes = str(r.get("mes") or r.get("fecha") or "").strip()[:7]
    if not re.match(r"^\d{4}-\d{2}$", mes):
        raise ErrorApi(400, "campo_invalido", "«mes» va como AAAA-MM (o mandá «fecha»).")
    try:
        monto = float(str(r.get("monto")).replace(".", "").replace(",", ".")) if isinstance(r.get("monto"), str) \
            else float(r.get("monto"))
    except (TypeError, ValueError):
        raise ErrorApi(400, "campo_invalido", "«monto» tiene que ser un número.")
    conn = get_connection()
    try:
        v = _vehiculo(conn, r.get("coche"), r.get("vehiculo_id"))
    finally:
        conn.close()
    agregar_costo(v["id"], mes, str(r.get("tipo") or "otros")[:40],
                  (str(r.get("concepto") or "") + f" ({quien})")[:200], monto)
    return f"costo:{v['id']}:{mes}", f"Costo de {_num(monto)} al coche {v['n_interno']}"


def aplicar(tipo, r, quien):
    """Devuelve (ref, detalle) si se aplicó, o None si es un tipo que solo se guarda."""
    if tipo == "combustible":
        x = cargar_combustible(r, quien)
        return f"combustible:{x['id']}", f"Carga de {x['litros']} L al coche {x['coche']}"
    if tipo == "kilometraje":
        x = informar_km(r, quien)
        return f"km:{x['coche']}", f"Coche {x['coche']}: {x['km_anterior']} → {x['km_actual']} km"
    if tipo == "agencias":
        return _aplicar_agencia(r, quien)
    if tipo == "fallas":
        return _aplicar_falla(r, quien)
    if tipo == "costos":
        return _aplicar_costo(r, quien)
    return None


# Los que se pueden volver a aplicar si llegan cambiados (no duplican nada)
REAPLICABLES = {"agencias", "kilometraje"}


def recibir(tipo, registros, origen, clave_id=None, tope=MAX_REGISTROS):
    """Mete los registros en la bandeja y aplica los que se entienden.
    Devuelve el resumen y el resultado de cada registro. La bandeja se lee y
    se escribe con una sola conexión (la base está lejos: cada consulta cuesta)."""
    if not RE_TIPO.match(tipo):
        raise ErrorApi(400, "tipo_invalido", "El tipo va en minúsculas, sin espacios: ventas, pasajeros, liquidaciones…")
    if len(registros) > tope:
        raise ErrorApi(413, "demasiados", f"Hasta {tope} registros por envío; mandalos en partes.")
    res = {"recibidos": len(registros), "aplicados": 0, "guardados": 0, "repetidos": 0, "revisar": 0, "errores": 0,
           "detalle": []}
    normales = []
    for i, crudo in enumerate(registros):
        try:
            r = _normalizar(crudo)
            normales.append((i, r, _id_externo(tipo, r)))
        except ValueError as e:
            res["errores"] += 1
            res["detalle"].append({"n": i, "estado": "error", "mensaje": str(e)})
    ids = list({ide for _, _, ide in normales if ide})
    previos = {}
    conn = get_connection()
    try:
        for k in range(0, len(ids), 500):
            tanda = ids[k:k + 500]
            for f in conn.execute(f"""SELECT id, id_externo, datos, estado FROM integ_entrada
                                      WHERE tipo=? AND id_externo IN ({','.join('?' * len(tanda))}) ORDER BY id""",
                                  [tipo] + tanda).fetchall():
                previos[f["id_externo"]] = dict(f)
        ahora = ahora_iso()
        for i, r, ide in normales:
            texto = json.dumps(r, ensure_ascii=False, sort_keys=True, default=str)
            previo = previos.get(ide) if ide else None
            if previo and previo["datos"] == texto and previo["estado"] != "error":
                conn.execute("UPDATE integ_entrada SET veces=COALESCE(veces,1)+1, actualizado_el=? WHERE id=?",
                             (ahora, previo["id"]))
                res["repetidos"] += 1
                res["detalle"].append({"n": i, "id_externo": ide, "estado": "repetido"})
                continue
            estado, detalle, ref = "guardado", "Guardado: el sistema todavía no usa este tipo de dato", ""
            if previo and previo["estado"] == "aplicado" and tipo not in REAPLICABLES:
                estado, detalle = "revisar", "Llegó de nuevo con cambios; lo que se había cargado no se tocó. Revisalo."
            elif tipo in CONOCIDOS:
                conn.commit()     # lo de la bandeja va antes: aplicar usa su propia conexión
                try:
                    ref, detalle = aplicar(tipo, r, origen)
                    estado = "aplicado"
                except ErrorApi as e:
                    if e.estado == 409 and e.codigo == "ya_cargada":
                        estado, detalle, ref = "aplicado", "Ya estaba cargada", f"combustible:{e.extra.get('id')}"
                    else:
                        estado, detalle = "error", e.mensaje
                except Exception as e:
                    estado, detalle = "error", f"No se pudo aplicar: {type(e).__name__}"
            if previo:
                conn.execute("""UPDATE integ_entrada SET datos=?, estado=?, detalle=?, ref=COALESCE(NULLIF(?,''), ref),
                                actualizado_el=?, veces=COALESCE(veces,1)+1, origen=? WHERE id=?""",
                             (texto, estado, detalle[:300], ref, ahora, origen[:80], previo["id"]))
                previo.update(datos=texto, estado=estado)
            else:
                cur = conn.execute("""INSERT INTO integ_entrada (origen, clave_id, tipo, id_externo, datos, estado, detalle,
                                                                 ref, recibido_el, actualizado_el, veces)
                                      VALUES (?,?,?,?,?,?,?,?,?,?,1)""",
                                   (origen[:80], clave_id, tipo, ide, texto, estado, detalle[:300], ref, ahora, ahora))
                if ide:   # si el mismo id viene dos veces en el mismo envío, la segunda es repetida o cambio
                    previos[ide] = {"id": cur.lastrowid, "id_externo": ide, "datos": texto, "estado": estado}
            clave = {"aplicado": "aplicados", "guardado": "guardados", "revisar": "revisar", "error": "errores"}[estado]
            res[clave] += 1
            item = {"n": i, "id_externo": ide, "estado": estado}
            if estado in ("error", "revisar"):
                item["mensaje"] = detalle
            if ref:
                item["ref"] = ref
            res["detalle"].append(item)
        conn.commit()
    finally:
        conn.close()
    res["detalle"].sort(key=lambda x: x["n"])
    return res


# ════════════════════════════════════════════════════════════════════════
#  API (con clave)
# ════════════════════════════════════════════════════════════════════════

@bp_entrada.route("/api/v1/entrada/<tipo>", methods=["POST"])
@con_clave("recibir")
def v1_recibir(tipo):
    tipo = tipo.strip().lower()
    regs = registros_del_pedido()
    res = recibir(tipo, regs, g.api_clave["nombre"], g.api_clave["id"])
    g.api_filas = res["recibidos"]
    # 200 si entró todo; 207 si hubo registros con problemas (el resto entró igual)
    return jsonify(res), (207 if res["errores"] or res["revisar"] else 200)


def _fila(f):
    try:
        datos = json.loads(f["datos"] or "{}")
    except ValueError:
        datos = {}
    return {"id": f["id"], "tipo": f["tipo"], "id_externo": f["id_externo"], "estado": f["estado"],
            "detalle": f["detalle"], "ref": f["ref"], "origen": f["origen"], "recibido_el": f["recibido_el"],
            "actualizado_el": f["actualizado_el"], "veces": f["veces"], "datos": datos}


@bp_entrada.route("/api/v1/entrada/<tipo>", methods=["GET"])
@con_clave("recibir")
def v1_lo_recibido(tipo):
    """Lo que ya llegó de ese tipo (para que el otro sistema confirme qué entró)."""
    from api_externa import _paginado, _fecha
    limit, offset = _paginado(request.args)
    desde = _fecha(request.args, "desde")
    where, params = ["tipo=?"], [tipo.strip().lower()]
    if desde:
        where.append("SUBSTR(actualizado_el,1,10) >= ?")
        params.append(desde)
    if request.args.get("estado"):
        where.append("estado=?")
        params.append(request.args["estado"])
    w = " AND ".join(where)
    conn = get_connection()
    try:
        total = conn.execute(f"SELECT COUNT(*) AS n FROM integ_entrada WHERE {w}", params).fetchone()["n"]
        filas = conn.execute(f"SELECT * FROM integ_entrada WHERE {w} ORDER BY id DESC LIMIT ? OFFSET ?",
                             params + [limit, offset]).fetchall()
    finally:
        conn.close()
    g.api_filas = len(filas)
    return jsonify({"datos": [_fila(f) for f in filas], "total": total, "limit": limit, "offset": offset})


# ════════════════════════════════════════════════════════════════════════
#  Pantalla (con sesión, solo admin)
# ════════════════════════════════════════════════════════════════════════

def _admin():
    return session.get("rol") == "admin"


@bp_entrada.route("/api/integ/entrada")
def api_bandeja():
    """Resumen por tipo de lo que llegó."""
    if not _admin():
        return jsonify({"ok": False, "error": "Solo administración"}), 403
    conn = get_connection()
    try:
        filas = conn.execute("""SELECT tipo, estado, COUNT(*) AS n, MAX(actualizado_el) AS ultimo
                                FROM integ_entrada GROUP BY tipo, estado""").fetchall()
        origenes = conn.execute("""SELECT tipo, origen FROM integ_entrada GROUP BY tipo, origen""").fetchall()
    finally:
        conn.close()
    tipos = {}
    for f in filas:
        t = tipos.setdefault(f["tipo"], {"tipo": f["tipo"], "total": 0, "ultimo": "", "origenes": [],
                                         "aplicado": 0, "guardado": 0, "revisar": 0, "error": 0,
                                         "se_aplica": CONOCIDOS.get(f["tipo"], "")})
        t[f["estado"]] = t.get(f["estado"], 0) + f["n"]
        t["total"] += f["n"]
        t["ultimo"] = max(t["ultimo"], f["ultimo"] or "")
    for o in origenes:
        if o["tipo"] in tipos and o["origen"] not in tipos[o["tipo"]]["origenes"]:
            tipos[o["tipo"]]["origenes"].append(o["origen"])
    return jsonify({"tipos": sorted(tipos.values(), key=lambda t: t["ultimo"], reverse=True),
                    "conocidos": [{"tipo": k, "hace": v} for k, v in CONOCIDOS.items()]})


@bp_entrada.route("/api/integ/entrada/<tipo>")
def api_bandeja_tipo(tipo):
    if not _admin():
        return jsonify({"ok": False, "error": "Solo administración"}), 403
    estado = request.args.get("estado") or ""
    conn = get_connection()
    try:
        if estado:
            filas = conn.execute("SELECT * FROM integ_entrada WHERE tipo=? AND estado=? ORDER BY id DESC LIMIT 300",
                                 (tipo, estado)).fetchall()
        else:
            filas = conn.execute("SELECT * FROM integ_entrada WHERE tipo=? ORDER BY id DESC LIMIT 300", (tipo,)).fetchall()
    finally:
        conn.close()
    return jsonify({"registros": [_fila(f) for f in filas]})


@bp_entrada.route("/api/integ/entrada/<int:eid>/reintentar", methods=["POST"])
def api_reintentar(eid):
    """Vuelve a aplicar un registro que dio error (por ejemplo, después de dar
    de alta el coche que faltaba)."""
    if not _admin():
        return jsonify({"ok": False, "error": "Solo administración"}), 403
    conn = get_connection()
    try:
        f = conn.execute("SELECT * FROM integ_entrada WHERE id=?", (eid,)).fetchone()
    finally:
        conn.close()
    if not f:
        return jsonify({"ok": False, "error": "No existe"}), 404
    if f["tipo"] not in CONOCIDOS:
        return jsonify({"ok": False, "error": "Este tipo de dato todavía no se aplica solo: queda guardado."}), 400
    r = json.loads(f["datos"] or "{}")
    quien = session.get("nombre") or session.get("usuario") or "?"
    try:
        ref, detalle = aplicar(f["tipo"], r, f["origen"] or quien)
        estado = "aplicado"
    except ErrorApi as e:
        ref, detalle, estado = "", e.mensaje, "error"
    conn = get_connection()
    try:
        conn.execute("UPDATE integ_entrada SET estado=?, detalle=?, ref=COALESCE(NULLIF(?,''), ref), actualizado_el=? WHERE id=?",
                     (estado, detalle[:300], ref, ahora_iso(), eid))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": estado == "aplicado", "estado": estado, "detalle": detalle})


@bp_entrada.route("/api/integ/entrada/<int:eid>/descartar", methods=["POST"])
def api_descartar(eid):
    if not _admin():
        return jsonify({"ok": False, "error": "Solo administración"}), 403
    conn = get_connection()
    try:
        conn.execute("DELETE FROM integ_entrada WHERE id=?", (eid,))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True})


@bp_entrada.route("/api/integ/entrada/subir", methods=["POST"])
def api_subir():
    """Un archivo exportado del otro sistema (Excel o CSV): cada fila entra
    como un registro del tipo elegido."""
    if not _admin():
        return jsonify({"ok": False, "error": "Solo administración"}), 403
    arch = request.files.get("archivo")
    tipo = _clave_campo(request.form.get("tipo") or "")
    if not arch:
        return jsonify({"ok": False, "error": "Elegí el archivo."}), 400
    if not RE_TIPO.match(tipo or ""):
        return jsonify({"ok": False, "error": "Decí qué tiene el archivo (ventas, agencias, combustible…)."}), 400
    datos = arch.read(MAX_ARCHIVO + 1)
    if len(datos) > MAX_ARCHIVO:
        return jsonify({"ok": False, "error": "El archivo pasa de 5 MB: partilo en dos."}), 400
    nombre = (arch.filename or "archivo").lower()
    try:
        if nombre.endswith((".xlsx", ".xlsm")):
            regs = leer_excel(datos)
        elif nombre.endswith(".xls"):
            return jsonify({"ok": False, "error": "Ese es un Excel viejo (.xls): abrilo y guardalo como .xlsx o .csv."}), 400
        else:
            texto = None
            for enc in ("utf-8-sig", "latin-1"):
                try:
                    texto = datos.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            regs = leer_csv(texto or "")
    except Exception as e:
        return jsonify({"ok": False, "error": f"No se pudo leer el archivo: {type(e).__name__}"}), 400
    if not regs:
        return jsonify({"ok": False, "error": "El archivo no tiene filas con datos."}), 400
    origen = (request.form.get("origen") or "Archivo").strip()[:40] + f" · {arch.filename}"[:40]
    try:
        res = recibir(tipo, regs, origen, tope=MAX_REGISTROS * 5)
    except ErrorApi as e:
        return jsonify({"ok": False, "error": e.mensaje}), 400
    try:
        from database import registrar_auditoria
        registrar_auditoria(usuario=session.get("nombre") or "?", rol="admin", categoria="Sistema",
                            accion=f"Subió un archivo a la bandeja de entrada ({tipo})",
                            detalle=f"{arch.filename}: {res['recibidos']} filas, {res['aplicados']} aplicadas")
    except Exception:
        pass
    res["detalle"] = [d for d in res["detalle"] if d["estado"] in ("error", "revisar")][:50]
    return jsonify({"ok": True, **res})
