"""
alpha.py — Lo que Alpha (la venta de pasajes) toma del tráfico (La Santaniana)

Alpha no inventa los servicios: salen del tráfico de cada día, nacional e
internacional. De ahí saca, para cada corredor (Concepción, Pedro Juan,
Buenos Aires...), las salidas de ida y de regreso con su hora, el tramo tal
como lo escriben, el coche asignado y la tripulación.

  - Si el tráfico de ese día ya está armado (publicado o no), se usa tal cual.
  - Si todavía no se armó (se venden pasajes para mañana o pasado), se toman
    los horarios del último tráfico del mismo día de la semana. El coche queda
    "a confirmar" y se muestra el que suele hacer esa salida, para saber qué
    plano de asientos vender.

La configuración de Alpha sí va a la base (tabla alpha_config, un JSON por
tema), porque es real y la usan todas las computadoras:

  - planos: el plano de asientos de cada modelo de coche (pisos, filas, clase)
  - coche_plano: qué plano usa cada coche (si no está, se deduce del modelo)
  - recorridos: las paradas de cada corredor, en orden de ida (puede haber
    más de un recorrido: "X 25", "X CHACO")
  - tarifas: el precio de cada tramo entre dos paradas, en diferencial y cama
  - descuentos: menor (hasta 8 años), jubilado...

Las ventas siguen siendo de prueba y quedan en el navegador (falta lo fiscal).
Todo es solo para administración.

Enganche en app.py:
    from alpha import bp_alpha, init_alpha
    init_alpha()
    app.register_blueprint(bp_alpha)
"""

import json
import re
from datetime import date, timedelta

from flask import Blueprint, jsonify, session, request

from db_compat import get_connection
from hora_local import ahora_iso
import trafico as tr

bp_alpha = Blueprint("alpha", __name__)

# Cómo se muestra cada lugar en la pantalla y en el boleto
NOMBRES = {
    "ASU": "Asunción", "COP": "Concepción", "LOT": "Loreto", "PJC": "Pedro Juan Caballero",
    "CDE": "Ciudad del Este", "ATQ": "Antequera", "SAN PEDRO": "San Pedro", "TACUATI": "Tacuatí",
    "SAN VICENTE": "San Vicente", "VILLARRICA": "Villarrica", "CARAPEGUA": "Carapeguá",
    "ROQUE GONZALEZ": "Roque González", "RETIRO": "Retiro", "LA PLATA": "La Plata",
    "LA NORIA": "La Noria", "SAN JUSTO": "San Justo", "LINIERS": "Liniers",
    "BUENOS AIRES": "Buenos Aires", "CLORINDA": "Clorinda",
}
SEMANAS_ATRAS = 5          # hasta cuántas semanas atrás se busca un tráfico de referencia
DIAS_HABITUAL = 21         # para el coche que suele hacer cada salida


def nombre_lugar(sigla):
    s = str(sigla or "").strip()
    if not s:
        return ""
    return NOMBRES.get(s.upper()) or s.title()


def _hora_ok(h):
    return bool(re.fullmatch(r"\d{2}:\d{2}", str(h or "")))


def _coche(txt):
    """El número interno si es un número; 'A CONF' y vacíos no son coche."""
    t = str(txt or "").strip()
    return t if re.fullmatch(r"\d{2,6}", t) else ""


def _salidas_de(conn, dia_id):
    return [dict(r) for r in conn.execute("""
        SELECT s.id, s.lado, s.hora, s.destino, s.coche, s.trip1, s.trip2, s.nota,
               b.nombre AS corredor, b.orden
        FROM trafico_salidas s JOIN trafico_bloques b ON b.id = s.bloque_id
        WHERE s.dia_id = ? ORDER BY b.orden, b.id, s.lado, s.hora, s.id""", (dia_id,)).fetchall()]


def _con_salidas(conn, dia_id):
    r = conn.execute("SELECT COUNT(*) AS n FROM trafico_salidas WHERE dia_id=?", (dia_id,)).fetchone()
    return int(r["n"] or 0) > 0


def _referencia(conn, fecha, tipo):
    """Un tráfico ya armado para tomar los horarios: el último del mismo día
    de la semana; si no hay, el último que haya antes de esa fecha."""
    f = date.fromisoformat(fecha)
    for k in range(1, SEMANAS_ATRAS + 1):
        d = tr._dia_por_fecha(conn, (f - timedelta(days=7 * k)).isoformat(), tipo)
        if d and _con_salidas(conn, d["id"]):
            return d
    for r in conn.execute("""SELECT * FROM trafico_dias WHERE fecha < ? AND COALESCE(tipo,'nacional') = ?
                             ORDER BY fecha DESC LIMIT 15""", (fecha, tipo)).fetchall():
        if _con_salidas(conn, r["id"]):
            return dict(r)
    return None


def _habituales(conn, fecha, tipo):
    """(corredor, lado, hora) → el último coche que hizo esa salida."""
    desde = (date.fromisoformat(fecha) - timedelta(days=DIAS_HABITUAL)).isoformat()
    out = {}
    for r in conn.execute("""
        SELECT d.fecha, b.nombre AS corredor, s.lado, s.hora, s.coche
        FROM trafico_salidas s JOIN trafico_dias d ON d.id = s.dia_id
        JOIN trafico_bloques b ON b.id = s.bloque_id
        WHERE COALESCE(d.tipo,'nacional') = ? AND d.fecha >= ? AND d.fecha <= ?
        ORDER BY d.fecha""", (tipo, desde, fecha)).fetchall():
        c = _coche(r["coche"])
        if c:
            out[(tr._sin_tildes(tr.limpiar(r["corredor"])), r["lado"], r["hora"])] = c
    return out


def _tripulacion(s):
    """Los tripulantes escritos. 'CHOFER 21027' es cómo marcan que va el
    chofer fijo de ese coche: se muestra tal cual."""
    return [t.strip() for t in (s.get("trip1"), s.get("trip2")) if t and t.strip()]


def dia_para_alpha(fecha):
    conn = get_connection()
    try:
        flota = tr._flota(conn)

        def modelo(c):
            v = flota.get(c)
            return " ".join(x for x in ((v or {}).get("marca"), (v or {}).get("modelo")) if x).strip() if v else ""

        corredores = []
        for tipo in ("nacional", "internacional"):
            d = tr._dia_por_fecha(conn, fecha, tipo)
            fuente = {"tipo": tipo}
            if d and _con_salidas(conn, d["id"]):
                filas = _salidas_de(conn, d["id"])
                version = int(d.get("version") or 0)
                fuente.update(estado=("publicado" if version and not int(d.get("modificado") or 0)
                                      else "cambios" if version else "borrador"),
                              version=version, publicado_el=d.get("publicado_el") or "")
                es_ref = False
            else:
                ref = _referencia(conn, fecha, tipo)
                if not ref:
                    continue
                filas = _salidas_de(conn, ref["id"])
                fuente.update(estado="referencia", fecha_ref=ref["fecha"])
                es_ref = True
            hab = _habituales(conn, fecha, tipo)

            por = {}
            for s in filas:
                if not _hora_ok(s["hora"]) or s["lado"] not in tr.LADOS:
                    continue
                corr = (s["corredor"] or "").strip()
                clave_corr = tr._sin_tildes(tr.limpiar(corr))
                c = por.get(clave_corr)
                if c is None:
                    lugar = (tr._lugar_ar(corr) or "BUENOS AIRES") if tipo == "internacional" else tr.lugar_del_corredor(corr)
                    c = por[clave_corr] = {
                        "clave": f"{tipo}|{clave_corr}", "tipo": tipo, "corredor": corr,
                        "lugar": lugar, "titulo": nombre_lugar(lugar) if lugar and lugar != "ASU" else corr.title(),
                        "fuente": fuente, "ida": [], "regreso": [],
                    }
                o, dst = tr.tramo(s["destino"], s["lado"], corr, tipo)
                base, extras = tr.partes_destino(s["destino"])
                coche = "" if es_ref else _coche(s["coche"])
                habitual = "" if coche else hab.get((clave_corr, s["lado"], s["hora"]), "")
                c[s["lado"]].append({
                    "id": None if es_ref else s["id"],
                    "clave": f"{tipo}|{clave_corr}|{s['lado']}|{s['hora']}|{tr._sin_tildes(tr.limpiar(s['destino']))}",
                    "hora": s["hora"], "destino": s["destino"] or "", "tramo": base, "extras": extras,
                    "origen": o, "llega": dst, "origen_nombre": nombre_lugar(o), "llega_nombre": nombre_lugar(dst),
                    "coche": coche, "modelo": modelo(coche),
                    "a_confirmar": not coche and str(s.get("coche") or "").strip().upper().startswith("A CONF"),
                    "habitual": habitual, "habitual_modelo": modelo(habitual),
                    "tripulacion": [] if es_ref else _tripulacion(s),
                    "nota": "" if es_ref else (s.get("nota") or ""),
                })
            for c in por.values():
                for lado in tr.LADOS:
                    c[lado].sort(key=lambda x: x["hora"])
                corredores.append(c)
        return {"fecha": fecha, "corredores": corredores}
    finally:
        conn.close()


@bp_alpha.route("/api/alpha/dia/<fecha>", methods=["GET"])
def api_alpha_dia(fecha):
    if session.get("rol") != "admin":
        return jsonify({"ok": False, "error": "Alpha la ve solo administración"}), 403
    try:
        date.fromisoformat(fecha)
    except ValueError:
        return jsonify({"ok": False, "error": "Fecha inválida"}), 400
    return jsonify(dia_para_alpha(fecha))


# ════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN (planos, recorridos, tarifas, descuentos)
# ════════════════════════════════════════════════════════════════════════════

def _filas(desde, n, huecos=None):
    """Filas desde el frente: [ventanilla izq, pasillo izq, (pasillo), pasillo der, ventanilla der]."""
    huecos, out, k = huecos or {}, [], desde
    for i in range(n):
        if huecos.get(i) == "izq":
            out.append([k, k + 1, None, None, None]); k += 2
        else:
            out.append([k, k + 1, None, k + 3, k + 2]); k += 4
    return out


# Los planos de Delta (los mismos que tenía la maqueta)
PLANOS_INICIALES = {
    "AO01": {"nombre": "Doble piso con cama abajo", "tipo": "Doble piso", "parados": 10, "pisos": [
        {"nombre": "Piso alto", "clase": "CO", "filas": _filas(1, 13, {2: "izq", 3: "izq"})},
        {"nombre": "Piso bajo", "clase": "CA", "filas": [[49, 50, None, None, 51], [52, 53, None, None, 54],
                                                         [55, 56, None, None, 57], [58, 59, None, None, 60]]},
    ]},
    "AO03": {"nombre": "Doble piso, todo diferencial", "tipo": "Doble piso", "parados": 10, "pisos": [
        {"nombre": "Piso alto", "clase": "CO", "filas": _filas(1, 14, {3: "izq", 4: "izq"})},
        {"nombre": "Piso bajo", "clase": "CO", "filas": _filas(53, 4)},
    ]},
    "ACXC": {"nombre": "Un piso", "tipo": "Un piso", "parados": 0, "pisos": [
        {"nombre": "Planta única", "clase": "CO", "filas": _filas(1, 12, {11: "izq"})},
    ]},
}
# El recorrido de Concepción que ya se veía en la maqueta. Los demás se cargan
# en Tarifas → Recorridos.
RECORRIDOS_INICIALES = {
    "nacional|CONCEPCION": [
        {"nombre": "Por Ruta 3", "variante": "X 25", "paradas": [
            {"nombre": "Asunción"}, {"nombre": "Santaní"}, {"nombre": "Santa Rosa del Aguaray"},
            {"nombre": "Yby Yaú"}, {"nombre": "Horqueta"}, {"nombre": "Concepción"}]},
    ],
}
TARIFAS_INICIALES = {
    "nacional|CONCEPCION": {"Asunción|Concepción": {"CO": 150000, "CA": 180000}},
}
DESCUENTOS_INICIALES = [
    {"id": "general", "nombre": "General", "factor": 1},
    {"id": "menor", "nombre": "Menor (hasta 8 años)", "factor": 0.5},
    {"id": "jubilado", "nombre": "Jubilado", "factor": 0.75},
]
INICIALES = {"planos": PLANOS_INICIALES, "coche_plano": {}, "recorridos": RECORRIDOS_INICIALES,
             "tarifas": TARIFAS_INICIALES, "descuentos": DESCUENTOS_INICIALES}
MAX_JSON = 400_000


def init_alpha():
    conn = get_connection()
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS alpha_config (
            clave TEXT PRIMARY KEY,
            valor TEXT NOT NULL,
            actualizado_el TEXT DEFAULT '',
            actualizado_por TEXT DEFAULT '')""")
        conn.commit()
        hay = {r["clave"] for r in conn.execute("SELECT clave FROM alpha_config").fetchall()}
        for k, v in INICIALES.items():
            if k not in hay:
                conn.execute("INSERT INTO alpha_config (clave, valor, actualizado_el) VALUES (?,?,?) ON CONFLICT (clave) DO NOTHING",
                             (k, json.dumps(v, ensure_ascii=False), ahora_iso()))
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        conn.close()


def leer_config():
    conn = get_connection()
    try:
        out = {k: json.loads(json.dumps(v)) for k, v in INICIALES.items()}
        meta = {}
        for r in conn.execute("SELECT clave, valor, actualizado_el, actualizado_por FROM alpha_config").fetchall():
            try:
                out[r["clave"]] = json.loads(r["valor"])
                meta[r["clave"]] = {"el": r["actualizado_el"] or "", "por": r["actualizado_por"] or ""}
            except ValueError:
                pass
        out["meta"] = meta
        # Los coches de la flota (para elegir el plano de cada uno)
        out["coches"] = [{"coche": n, "marca": v.get("marca") or "", "modelo": v.get("modelo") or "",
                          "patente": v.get("patente") or ""}
                         for n, v in sorted(tr._flota(conn).items(), key=lambda kv: (len(kv[0]), kv[0]))
                         if int(v.get("activo") or 0) == 1]
        # Los corredores que aparecen en el tráfico de los últimos dos meses
        desde = (date.fromisoformat(ahora_iso()[:10]) - timedelta(days=60)).isoformat()
        vistos = {}
        for r in conn.execute("""SELECT DISTINCT COALESCE(d.tipo,'nacional') AS tipo, b.nombre
                                 FROM trafico_bloques b JOIN trafico_dias d ON d.id = b.dia_id
                                 WHERE d.fecha >= ?""", (desde,)).fetchall():
            corr = (r["nombre"] or "").strip()
            clave = f"{r['tipo']}|{tr._sin_tildes(tr.limpiar(corr))}"
            if corr and clave not in vistos:
                lugar = (tr._lugar_ar(corr) or "BUENOS AIRES") if r["tipo"] == "internacional" else tr.lugar_del_corredor(corr)
                vistos[clave] = {"clave": clave, "tipo": r["tipo"], "corredor": corr,
                                 "titulo": nombre_lugar(lugar) if lugar and lugar != "ASU" else corr.title()}
        for clave in list(out.get("recorridos", {})) + list(out.get("tarifas", {})):
            if clave not in vistos and "|" in clave:
                tipo, corr = clave.split("|", 1)
                vistos[clave] = {"clave": clave, "tipo": tipo, "corredor": corr, "titulo": corr.title()}
        out["corredores"] = sorted(vistos.values(), key=lambda c: (c["tipo"] != "nacional", c["titulo"]))
        return out
    finally:
        conn.close()


def _valido(clave, valor):
    """Revisa lo mínimo para que Alpha no se rompa con un dato mal cargado."""
    if clave == "planos":
        if not isinstance(valor, dict) or not valor:
            return "Tiene que haber al menos un plano"
        for cod, p in valor.items():
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,12}", str(cod)):
                return f"El código «{cod}» no sirve: letras y números, hasta 12"
            if not isinstance(p, dict) or not isinstance(p.get("pisos"), list) or not p["pisos"]:
                return f"El plano {cod} no tiene pisos"
            vistos = set()
            for piso in p["pisos"]:
                if piso.get("clase") not in ("CO", "CA"):
                    return f"En el plano {cod} hay un piso sin clase"
                for fila in piso.get("filas") or []:
                    if not isinstance(fila, list) or len(fila) != 5:
                        return f"En el plano {cod} hay una fila mal armada"
                    for n in fila:
                        if n is None:
                            continue
                        if not isinstance(n, int) or not 1 <= n <= 199:
                            return f"En el plano {cod} hay un asiento con número inválido"
                        if n in vistos:
                            return f"En el plano {cod} el asiento {n} está dos veces"
                        vistos.add(n)
            if not vistos:
                return f"El plano {cod} no tiene asientos"
            try:
                if not 0 <= int(p.get("parados") or 0) <= 40:
                    return f"En el plano {cod}, los parados van de 0 a 40"
            except (TypeError, ValueError):
                return f"En el plano {cod}, los parados tienen que ser un número"
    elif clave == "coche_plano":
        if not isinstance(valor, dict):
            return "Formato inválido"
    elif clave == "recorridos":
        if not isinstance(valor, dict):
            return "Formato inválido"
        for corr, lista in valor.items():
            if not isinstance(lista, list):
                return "Formato inválido"
            for r in lista:
                ps = r.get("paradas") if isinstance(r, dict) else None
                if not isinstance(ps, list) or len(ps) < 2:
                    return f"Cada recorrido necesita al menos dos paradas ({corr})"
                nombres = [str(x.get("nombre") or "").strip() for x in ps]
                if any(not n for n in nombres):
                    return "Hay una parada sin nombre"
                if len({n.lower() for n in nombres}) != len(nombres):
                    return f"En el recorrido «{r.get('nombre') or corr}» hay una parada repetida"
    elif clave == "tarifas":
        if not isinstance(valor, dict):
            return "Formato inválido"
        for corr, pares in valor.items():
            if not isinstance(pares, dict):
                return "Formato inválido"
            for par, pr in pares.items():
                for cl in ("CO", "CA"):
                    x = (pr or {}).get(cl)
                    if x in (None, ""):
                        continue
                    if not isinstance(x, (int, float)) or x < 0 or x > 50_000_000:
                        return f"El precio de {par.replace('|', ' a ')} no es válido"
    elif clave == "descuentos":
        if not isinstance(valor, list) or not valor:
            return "Tiene que haber al menos una tarifa"
        for d in valor:
            try:
                f = float(d.get("factor"))
            except (TypeError, ValueError, AttributeError):
                return "Un descuento tiene un porcentaje inválido"
            if not 0 <= f <= 1 or not str(d.get("nombre") or "").strip():
                return "Revisá los descuentos: nombre y porcentaje entre 0 y 100"
    else:
        return "Eso no se puede guardar"
    return None


def guardar_config(clave, valor, quien=""):
    err = _valido(clave, valor)
    if err:
        return False, err
    txt = json.dumps(valor, ensure_ascii=False)
    if len(txt) > MAX_JSON:
        return False, "Es demasiado grande para guardar"
    conn = get_connection()
    try:
        conn.execute("""INSERT INTO alpha_config (clave, valor, actualizado_el, actualizado_por) VALUES (?,?,?,?)
                        ON CONFLICT (clave) DO UPDATE SET valor=excluded.valor,
                        actualizado_el=excluded.actualizado_el, actualizado_por=excluded.actualizado_por""",
                     (clave, txt, ahora_iso(), (quien or "")[:80]))
        conn.commit()
    finally:
        conn.close()
    return True, "Guardado"


@bp_alpha.route("/api/alpha/config", methods=["GET"])
def api_alpha_config():
    if session.get("rol") != "admin":
        return jsonify({"ok": False, "error": "Alpha la ve solo administración"}), 403
    return jsonify(leer_config())


@bp_alpha.route("/api/alpha/config/<clave>", methods=["PUT"])
def api_alpha_guardar(clave):
    if session.get("rol") != "admin":
        return jsonify({"ok": False, "error": "Alpha la ve solo administración"}), 403
    d = request.get_json(silent=True) or {}
    quien = session.get("nombre") or session.get("usuario") or ""
    ok, msg = guardar_config(clave, d.get("valor"), quien)
    if not ok:
        return jsonify({"ok": False, "msg": msg, "error": msg}), 400
    try:
        from database import registrar_auditoria
        nombres = {"planos": "los planos de asientos", "coche_plano": "el plano de los coches",
                   "recorridos": "los recorridos", "tarifas": "las tarifas", "descuentos": "los descuentos"}
        registrar_auditoria(usuario=quien or "?", rol=session.get("rol") or "",
                            accion=f"Alpha: cambió {nombres.get(clave, clave)}", categoria="Alpha", detalle="")
    except Exception:
        pass
    return jsonify({"ok": True, "msg": msg})
