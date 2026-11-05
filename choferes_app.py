"""
choferes_app.py — La app del chofer de línea y de turismo (La Santaniana)

Cada chofer de tráfico (nacional e internacional) y de turismo entra desde el
celular y ve:
  · el servicio que le toca (lo que la oficina ya PUBLICÓ, nunca el borrador),
  · lo que viene en los próximos días,
  (la pestaña «Mi mes» se sacó: los choferes no ven su producción).
Y le llega una notificación al celular cuando se publica su servicio.

Quién es quién: en las planillas el chofer figura por nombre ("JUAN PEREZ",
"PEREZ, JUAN", "PEREZ JUAN"...). Cada usuario de rol 'tripulante' tiene su
nombre y una lista de "también figura como" (alias_planilla, separados con ;)
para los que están escritos distinto o con un error de tipeo. La comparación
no mira el orden ni las tildes (nombres.clave_persona).

Usuarios: los crea el admin de una vez desde Usuarios → "Choferes de línea y
turismo". Usuario = nombre de pila; clave = la misma (fácil de recordar).

Corporativos: el chofer de corporativos también tiene esta app (además de su
pantalla de rendiciones). Ve sus servicios de tráfico y turismo y su
asignación corporativa publicada. Si una misma persona quedó con dos usuarios
(uno corporativo y uno de línea), desde Usuarios → "Choferes y la app" se
unen: queda el corporativo (que tiene las rendiciones) con todo lo del otro.

Avisos (push.py):
  · Tráfico: al publicar el día, a cada chofer que tiene servicio. Si se vuelve
    a publicar, solo a los que les cambió algo (o se les sacó el servicio).
  · Corporativos: al publicar la asignación, a cada chofer asignado (mismo
    criterio). Su pantalla (/corp) no cambia: solo se le suma el aviso.
  · Turismo: no tiene "publicar"; desde la ventana de la asignación de turismo
    el botón "Avisar a los choferes" les manda su servicio.

Enganche en app.py:
    from choferes_app import bp_choferes_app, init_choferes_app
    init_choferes_app()
    app.register_blueprint(bp_choferes_app)
"""

import json
import re
from datetime import date, timedelta

from flask import Blueprint, jsonify, make_response, render_template, request, session

from db_compat import get_connection, USE_POSTGRES
from hora_local import hoy as _hoy_local
from nombres import apellido_primero, clave_persona, separar_personas, _llano

bp_choferes_app = Blueprint("choferes_app", __name__)

ROL = "tripulante"
CORP = "chofer_corp"
ROLES_APP = (ROL, CORP)                # los que tienen la app del chofer
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
DIAS_CORTOS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]
DIAS_ADELANTE = 14                     # cuánto de lo que viene se muestra

LUGAR_TXT = {
    "ASU": "Asunción", "COP": "Concepción", "LOT": "Loreto", "PJC": "Pedro Juan Caballero",
    "CDE": "Ciudad del Este", "ATQ": "Antequera", "SAN PEDRO": "San Pedro", "TACUATI": "Tacuatí",
    "SAN VICENTE": "San Vicente", "VILLARRICA": "Villarrica", "CARAPEGUA": "Carapeguá",
    "ROQUE GONZALEZ": "Roque González", "BUENOS AIRES": "Buenos Aires", "LA PLATA": "La Plata",
    "LA NORIA": "La Noria", "SAN JUSTO": "San Justo", "LINIERS": "Liniers", "RETIRO": "Retiro",
    "CLORINDA": "Clorinda",
}


def init_choferes_app():
    conn = get_connection()
    pk = "SERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"
    for sql in ("ALTER TABLE usuarios ADD COLUMN alias_planilla TEXT DEFAULT ''",
                # El chofer confirma que recibió su asignación corporativa de cada día.
                # firma = lo que tenía asignado cuando confirmó: si después cambia, confirma de nuevo.
                f"""CREATE TABLE IF NOT EXISTS corp_asig_acuses (
                    id {pk}, fecha TEXT NOT NULL, chofer_usuario TEXT NOT NULL, firma TEXT DEFAULT '',
                    confirmado_el TEXT DEFAULT '', usuario_id INTEGER, equipo TEXT DEFAULT '')""",
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_corp_acuse ON corp_asig_acuses (fecha, chofer_usuario)"):
        try:
            conn.execute(sql)
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
    conn.close()


# ════════════════════════════════════════════════════════════════════════════
# QUIÉN ES QUIÉN
# ════════════════════════════════════════════════════════════════════════════

def _claves_de(nombre, alias=""):
    ks = {clave_persona(nombre)} | {clave_persona(a) for a in str(alias or "").split(";") if a.strip()}
    return {k for k in ks if k}


def coincide(nombre, claves):
    """Si el nombre de la planilla es de esta persona. Además de la forma exacta
    acepta que en la planilla tenga algo de más: un segundo nombre o segundo
    apellido ("VICTOR HUGO AMARILLA" es de "AMARILLA, VICTOR"), o un número
    o una letra suelta ("AMARILLA V. 0981…"). Hacen falta al menos nombre y
    apellido completos, y como mucho dos palabras de más."""
    k = clave_persona(nombre)
    if not k:
        return False
    if k in claves:
        return True
    tk = {x for x in k.split() if not any(ch.isdigit() for ch in x) and len(x) > 1}
    for c in claves:
        tc = set(c.split())
        if len(tc) >= 2 and tc <= tk and len(tk - tc) <= 2:
            return True
    return False


def tripulantes(conn, solo_activos=True, con_corp=False):
    """Los usuarios choferes de línea y turismo con sus claves de nombre.
    con_corp: también los de corporativos (para avisarles si les toca un
    servicio de tráfico o de turismo; el aviso les abre su pantalla)."""
    roles = (ROL, "chofer_corp") if con_corp else (ROL,)
    filas = conn.execute(f"""SELECT id, usuario, nombre, rol, COALESCE(alias_planilla,'') AS alias, activo, ultimo_acceso,
                                    COALESCE(app_confirmado_el,'') AS app_confirmado_el, COALESCE(app_modo,'') AS app_modo
                             FROM usuarios WHERE rol IN ({",".join("?" * len(roles))})
                             {"AND COALESCE(activo,1)=1" if solo_activos else ""}
                             ORDER BY rol DESC, nombre""", roles).fetchall()
    out = []
    for f in filas:
        d = dict(f)
        d["claves"] = _claves_de(d["nombre"], d["alias"])
        out.append(d)
    return out


def _indice(trips):
    """{clave de nombre: usuario} para buscar rápido a quién le toca cada salida."""
    idx = {}
    for t in trips:
        for k in t["claves"]:
            idx.setdefault(k, t)
    return idx


def _lindo(txt):
    t = str(txt or "").strip()
    if not t:
        return ""
    if t.upper() in LUGAR_TXT:
        return LUGAR_TXT[t.upper()]
    return " ".join(w if len(w) <= 3 and w.isupper() and w not in ("DEL", "LAS", "LOS") else w.capitalize()
                    for w in t.lower().split()).replace(" De ", " de ").replace(" Del ", " del ")


def _dia_txt(fecha, hoy):
    try:
        d = date.fromisoformat(fecha[:10])
        h = date.fromisoformat(hoy)
    except Exception:
        return fecha
    n = (d - h).days
    base = f"{DIAS[d.weekday()]} {d.day}/{d.month}"
    return "hoy" if n == 0 else "mañana" if n == 1 else "ayer" if n == -1 else base


def _dia_largo(fecha):
    d = date.fromisoformat(fecha[:10])
    return f"{DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]}"


# ════════════════════════════════════════════════════════════════════════════
# TRÁFICO PUBLICADO
# ════════════════════════════════════════════════════════════════════════════

def _fotos(conn, desde, hasta, version_menos=0):
    """[(fecha, tipo, foto)] de lo publicado en el rango (la última versión;
    con version_menos=1, la anterior, para saber qué cambió)."""
    filas = conn.execute("""
        SELECT d.fecha, COALESCE(d.tipo,'nacional') AS tipo, v.datos
        FROM trafico_dias d JOIN trafico_versiones v ON v.dia_id = d.id AND v.version = d.version - ?
        WHERE d.fecha >= ? AND d.fecha <= ? AND COALESCE(d.publicado_el,'') <> ''
        ORDER BY d.fecha""", (version_menos, desde, hasta)).fetchall()
    out = []
    for f in filas:
        try:
            out.append((f["fecha"], f["tipo"], json.loads(f["datos"])))
        except Exception:
            pass
    return out


def _salidas_foto(fecha, tipo, foto):
    """Cada salida publicada del día, con lo que hace falta mostrar."""
    from trafico import tramo, partes_destino, LADOS
    for b in foto.get("bloques") or []:
        corredor = b.get("nombre") or ""
        for lado in LADOS:
            for s in b.get(lado) or []:
                trips = [t for t in (s.get("trip1"), s.get("trip2")) if (t or "").strip()]
                if not trips:
                    continue
                base, extras = partes_destino(s.get("destino") or "")
                o, l = tramo(s.get("destino") or "", lado, corredor, tipo)
                if o and l and o == l:
                    o, l = ("ASU", corredor) if lado == "ida" else (corredor, "ASU")
                yield {
                    "origen": "trafico", "id": f"t{s.get('id')}", "fecha": fecha, "hora": s.get("hora") or "",
                    "tipo": tipo, "lado": lado, "corredor": _lindo(corredor),
                    "desde": _lindo(o) if o else "", "hasta": _lindo(l) if l else _lindo(base),
                    "destino": s.get("destino") or "", "extras": extras,
                    "refuerzo": "REFUERZO" in extras,
                    "coche": (s.get("coche") or "").strip(), "nota": s.get("nota") or "",
                    "trips": trips,
                }
            rt = (b.get(f"reserva_{lado}_trip") or "").strip()
            if rt:
                yield {"origen": "reserva", "id": f"r{b.get('id')}{lado}", "fecha": fecha, "hora": "",
                       "tipo": tipo, "lado": lado, "corredor": _lindo(corredor), "desde": "", "hasta": "",
                       "destino": "", "extras": [], "refuerzo": False,
                       "coche": (b.get(f"reserva_{lado}_coche") or "").strip(), "nota": "", "trips": [rt]}


def _para(item, claves):
    """Si el item es de esta persona; le pone el compañero."""
    mios = [t for t in item["trips"] if coincide(t, claves)]
    if not mios:
        return None
    it = {k: v for k, v in item.items() if k != "trips"}
    it["con"] = [apellido_primero(t) for t in item["trips"] if not coincide(t, claves)]
    return it


# ════════════════════════════════════════════════════════════════════════════
# TURISMO
# ════════════════════════════════════════════════════════════════════════════

def _turismo(conn, desde, hasta):
    """Los servicios de turismo que tocan el rango (los de varios días cuentan
    mientras duran), uno por coche con su tripulación."""
    filas = conn.execute("""
        SELECT * FROM agenda_turismo
        WHERE COALESCE(estado,'') <> 'cancelado' AND fecha <= ?
          AND COALESCE(NULLIF(fecha_fin,''), fecha) >= ?
        ORDER BY fecha, hora""", (hasta, desde)).fetchall()
    for f in filas:
        f = dict(f)
        for suf in ("", "_2", "_3"):
            trip = f.get("tripulacion" + suf) or ""
            personas = separar_personas(trip)
            if not personas:
                continue
            yield {
                "origen": "turismo", "id": f"u{f['id']}{suf}", "fecha": f["fecha"],
                "fecha_fin": f.get("fecha_fin") or "", "hora": f.get("hora") or "",
                "tipo": "turismo", "cliente": _lindo(f.get("cliente") or ""), "ot": f.get("ot_nr") or "",
                "desde": f.get("salida") or "", "hasta": f.get("destino") or "",
                "coche": str(f.get("coche_interno" + suf) or "").strip(),
                "pasajeros": f.get("pasajeros") or None, "estado": f.get("estado") or "",
                "nota": f.get("observaciones") or "", "extras": [], "refuerzo": False,
                "trips": personas,
            }


# ════════════════════════════════════════════════════════════════════════════
# CORPORATIVOS (lo publicado de la asignación)
# ════════════════════════════════════════════════════════════════════════════

LADO_CORP = {"completo": "", "entrante": "entrada", "saliente": "salida", "variable": ""}


def es_mio_corp(x, usuario, claves):
    """Si una fila de la asignación corporativa es de esta persona: por el
    usuario con que se la asignó, o por el nombre (así le aparece aunque entre
    con otro usuario, o si se la asignaron a su usuario viejo)."""
    u = (x.get("chofer_usuario") or "").strip().lower()
    if usuario and u and u == usuario:
        return True
    n = x.get("chofer_nombre") or ""
    return bool(claves and n.strip() and coincide(n, claves))


def _corp(conn, usuario, desde, hasta, claves=None, publicado=True):
    """La asignación corporativa PUBLICADA de esta persona en el rango.
    publicado=False: lo que está cargado ahora (borrador incluido), para la revisión."""
    usuario = str(usuario or "").strip().lower()
    if not usuario and not claves:
        return
    try:
        import corp_asignacion as CA
        if publicado:
            filas = conn.execute("""
                SELECT d.fecha, v.datos FROM corp_asig_dias d
                JOIN corp_asig_versiones v ON v.dia_id = d.id AND v.version = d.version
                WHERE d.fecha >= ? AND d.fecha <= ? AND COALESCE(d.publicado_el,'') <> ''
                ORDER BY d.fecha""", (desde, hasta)).fetchall()
        else:
            filas = []
            for r in conn.execute("SELECT id, fecha FROM corp_asig_dias WHERE fecha >= ? AND fecha <= ? ORDER BY fecha",
                                  (desde, hasta)).fetchall():
                fs = [dict(x) for x in conn.execute("SELECT * FROM corp_asig WHERE dia_id=?", (r["id"],)).fetchall()]
                filas.append({"fecha": r["fecha"], "datos": json.dumps({"filas": fs, "horarios": {}})})
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return
    for f in filas:
        try:
            foto = json.loads(f["datos"])
        except Exception:
            continue
        horarios = foto.get("horarios") or {}
        for k, x in enumerate(foto.get("filas") or []):
            if x.get("lado") == "no_corre" or not es_mio_corp(x, usuario, claves):
                continue
            h = horarios.get(f"{x.get('cliente')}|{x.get('tramo')}")
            hora = hora_fin = ""
            try:
                r = CA.rango(x, h)
                if r:
                    hora = CA._hhmm(r[0])
                    dur = (r[1] - r[0]) % 24
                    if dur >= 2:                 # "6:00/6:30" son dos horas de salida, no un horario
                        hora_fin = CA._hhmm(r[1])
            except Exception:
                pass
            tramo = CA.tramo_corto(x.get("tramo") or "")
            cli = (x.get("cliente") or "").strip()
            yield {
                "origen": "corp", "id": f"c{f['fecha']}{k}", "fecha": f["fecha"], "hora": hora, "hora_fin": hora_fin,
                "tipo": "corporativo", "cliente": cli if len(cli) <= 4 else _lindo(cli), "tramo": tramo,
                "tramo_completo": x.get("tramo") or "",
                "lado": LADO_CORP.get(x.get("lado"), ""), "desde": "", "hasta": tramo,
                "coche": str(x.get("coche") or "").strip(), "nota": x.get("nota") or x.get("detalle") or "",
                "extras": [], "refuerzo": False, "con": [],
                "chofer_usuario": (x.get("chofer_usuario") or "").strip().lower(),
            }


# ── «Recibí mi asignación» ───────────────────────────────────────────────────

def _firma_corp(items):
    return "|".join(sorted(f"{i.get('hora')}~{i.get('cliente')}~{i.get('tramo')}~{i.get('lado')}~{i.get('coche')}"
                           for i in items))


def _acuses(conn, fechas):
    if not fechas:
        return {}
    try:
        filas = conn.execute(f"""SELECT fecha, chofer_usuario, firma, confirmado_el FROM corp_asig_acuses
                                 WHERE fecha IN ({",".join("?" * len(fechas))})""", list(fechas)).fetchall()
    except Exception:
        conn.rollback()
        return {}
    return {(r["fecha"], r["chofer_usuario"]): dict(r) for r in filas}


def acuses_pendientes(conn, usuario, claves, hoy):
    """Las asignaciones publicadas (de hoy en adelante) que este chofer todavía
    no confirmó que recibió, o que cambiaron después de confirmarlas."""
    hasta = (date.fromisoformat(hoy) + timedelta(days=DIAS_ADELANTE)).isoformat()
    grupos = {}
    for it in _corp(conn, usuario, hoy, hasta, claves):
        grupos.setdefault((it["fecha"], it["chofer_usuario"] or (usuario or "")), []).append(it)
    hechos = _acuses(conn, {f for f, _ in grupos})
    out = []
    for (fecha, u), its in sorted(grupos.items()):
        firma = _firma_corp(its)
        a = hechos.get((fecha, u))
        if a and a["firma"] == firma:
            continue
        its.sort(key=lambda i: i.get("hora") or "99")
        out.append({"fecha": fecha, "chofer_usuario": u, "firma": firma, "cambio": bool(a),
                    "dia_txt": _dia_txt(fecha, hoy), "dia_largo": _dia_largo(fecha),
                    "items": [{"hora": i["hora"], "hora_fin": i.get("hora_fin") or "", "cliente": i["cliente"],
                               "tramo": i["tramo"], "lado": i["lado"], "coche": i["coche"]} for i in its]})
    return out


def estado_acuses(fecha):
    """Para la pantalla de la asignación: quién confirmó que recibió lo
    publicado ese día. {usuario: {confirmado_el, al_dia}}"""
    conn = get_connection()
    try:
        fila = conn.execute("""SELECT v.datos FROM corp_asig_dias d
                               JOIN corp_asig_versiones v ON v.dia_id = d.id AND v.version = d.version
                               WHERE d.fecha=? AND COALESCE(d.publicado_el,'') <> ''""", (fecha,)).fetchone()
        if not fila:
            return {}
        usuarios = {(x.get("chofer_usuario") or "").strip().lower()
                    for x in (json.loads(fila["datos"]).get("filas") or []) if x.get("chofer_usuario")}
        actual = {}
        for u in usuarios:
            actual[u] = _firma_corp(list(_corp(conn, u, fecha, fecha, None)))
        hechos = _acuses(conn, {fecha})
    finally:
        conn.close()
    out = {}
    for u, firma in actual.items():
        a = hechos.get((fecha, u))
        out[u] = {"confirmado_el": a["confirmado_el"] if a else "", "al_dia": bool(a and a["firma"] == firma)}
    return out


# ════════════════════════════════════════════════════════════════════════════
# LO QUE LE TOCA Y SU MES
# ════════════════════════════════════════════════════════════════════════════

def proximos(conn, claves, hoy, usuario_corp=None):
    hasta = (date.fromisoformat(hoy) + timedelta(days=DIAS_ADELANTE)).isoformat()
    items = []
    for fecha, tipo, foto in _fotos(conn, hoy, hasta):
        for s in _salidas_foto(fecha, tipo, foto):
            it = _para(s, claves)
            if it:
                items.append(it)
    for s in _turismo(conn, hoy, hasta):
        it = _para(s, claves)
        if it:
            items.append(it)
    items.extend(_corp(conn, usuario_corp, hoy, hasta, claves))
    items.sort(key=lambda x: (x["fecha"], x["hora"] or "99", x["origen"]))
    return items


def _mes_rango(mes):
    a, m = int(mes[:4]), int(mes[5:7])
    ini = date(a, m, 1)
    fin = date(a + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
    return ini, fin


def _mes_anterior(mes):
    a, m = int(mes[:4]), int(mes[5:7])
    return f"{a - (m == 1)}-{(m - 2) % 12 + 1:02d}"


def produccion(conn, claves, mes, hoy, hasta_dia=None, usuario_corp=None):
    """Lo que hizo en el mes (hasta hoy) y lo que ya tiene programado.
    hasta_dia: cortar en ese día del mes (para comparar contra el mes anterior
    a la misma altura, no contra el mes entero)."""
    from servicios import leer_servicios
    from trafico import TOPE_VIAJES_INT
    ini, fin = _mes_rango(mes)
    tope_hecho = min(fin.isoformat(), hoy)
    if hasta_dia:
        tope_hecho = min(tope_hecho, (ini + timedelta(days=min(hasta_dia, fin.day) - 1)).isoformat())
    hechos, por_dia, tramos = [], {}, {}
    if ini.isoformat() <= tope_hecho:
        for s in leer_servicios(conn, ini.isoformat(), tope_hecho):
            if not any(coincide(t, claves) for t in s["trips"]):
                continue
            hechos.append(s)
            por_dia[s["fecha"]] = por_dia.get(s["fecha"], 0) + 1
            if s["origen"] and s["llega"]:
                k = f"{_lindo(s['origen'])} → {_lindo(s['llega'])}"
                tramos[k] = tramos.get(k, 0) + 1
    # Lo publicado que falta del mes
    programados = []
    if fin.isoformat() > hoy:
        manana = (date.fromisoformat(hoy) + timedelta(days=1)).isoformat()
        for fecha, tipo, foto in _fotos(conn, max(manana, ini.isoformat()), fin.isoformat()):
            for s in _salidas_foto(fecha, tipo, foto):
                if s["origen"] == "trafico" and any(coincide(t, claves) for t in s["trips"]):
                    programados.append({"fecha": fecha, "tipo": tipo, "lado": s["lado"]})
    # Internacional: un viaje = ida + vuelta
    int_h = [s for s in hechos if s["trafico"] == "internacional"]
    int_p = [s for s in programados if s["tipo"] == "internacional"]
    viajes = max(sum(1 for s in int_h + int_p if s["lado"] == "ida"),
                 sum(1 for s in int_h + int_p if s["lado"] == "regreso"))
    viajes_hechos = max(sum(1 for s in int_h if s["lado"] == "ida"), sum(1 for s in int_h if s["lado"] == "regreso"))
    # Turismo del mes
    tur = []
    for s in _turismo(conn, ini.isoformat(), fin.isoformat()):
        it = _para(s, claves)
        if not it:
            continue
        a = max(date.fromisoformat(it["fecha"]), ini)
        b = min(date.fromisoformat((it["fecha_fin"] or it["fecha"])[:10]), fin)
        it["dias"] = max(1, (b - a).days + 1)
        it["hecho"] = (it["fecha_fin"] or it["fecha"]) <= tope_hecho or (it["estado"] == "completado" and it["fecha"] <= tope_hecho)
        tur.append(it)
        d = a
        while d <= b and d.isoformat() <= tope_hecho:
            por_dia[d.isoformat()] = por_dia.get(d.isoformat(), 0) + 1
            d += timedelta(days=1)
    # Corporativos: lo asignado y publicado (hasta hoy cuenta como hecho)
    corp_h = corp_p = 0
    for it in _corp(conn, usuario_corp, ini.isoformat(), fin.isoformat(), claves):
        if it["fecha"] <= tope_hecho:
            corp_h += 1
            por_dia[it["fecha"]] = por_dia.get(it["fecha"], 0) + 1
        elif not hasta_dia:
            corp_p += 1
    km_conocidos = [s["km"] for s in hechos if s["km"]]
    return {
        "mes": mes, "mes_txt": f"{MESES[ini.month - 1].capitalize()} {ini.year}",
        "servicios": len(hechos) + sum(1 for t in tur if t["hecho"]) + corp_h,
        "linea": len(hechos), "turismo": sum(1 for t in tur if t["hecho"]), "corp": corp_h,
        "km": round(sum(km_conocidos)), "km_completo": len(km_conocidos) == len(hechos),
        "dias": len(por_dia), "refuerzos": sum(1 for s in hechos if s["refuerzo"]),
        "coches": len({s["coche"] for s in hechos if s["coche"]}),
        "programados": len(programados) + sum(1 for t in tur if not t["hecho"]) + corp_p,
        "internacional": {"viajes": viajes, "hechos": viajes_hechos, "tope": TOPE_VIAJES_INT} if (int_h or int_p) else None,
        "tramos": sorted(({"tramo": k, "n": n} for k, n in tramos.items()), key=lambda x: -x["n"])[:5],
        "por_dia": por_dia, "turismo_lista": [{k: t[k] for k in ("fecha", "fecha_fin", "hora", "cliente", "desde",
                                                                   "hasta", "coche", "dias", "hecho")} for t in tur],
        "desde": ini.isoformat(), "hasta": fin.isoformat(), "hoy": hoy,
    }


def _sin_km(p):
    """Los corporativos no ven los km recorridos ni el calendario de días."""
    if p:
        p["km"], p["km_completo"], p["por_dia"] = None, True, {}
    return p


def _resumen_corto(p, a_la_altura=False):
    return {k: p[k] for k in ("servicios", "km", "dias", "refuerzos")} | {"mes_txt": p["mes_txt"], "a_la_altura": a_la_altura}


def _comparar(conn, claves, mes, hoy, usuario_corp=None):
    """El mes anterior: si el mes que se mira está en curso, hasta el mismo día
    (así no se compara una semana contra un mes entero)."""
    en_curso = mes == hoy[:7]
    a = produccion(conn, claves, _mes_anterior(mes), hoy, hasta_dia=int(hoy[8:10]) if en_curso else None,
                   usuario_corp=usuario_corp)
    return _resumen_corto(a, en_curso)


# ════════════════════════════════════════════════════════════════════════════
# AVISOS
# ════════════════════════════════════════════════════════════════════════════

def _firma(items):
    return sorted((i.get("hora") or "", i.get("desde") or "", i.get("hasta") or "", i.get("coche") or "",
                   i.get("lado") or "", i.get("corredor") or "", tuple(sorted(i.get("con") or []))) for i in items)


def _linea_corp(it):
    return " · ".join(x for x in (it.get("hora"), f"{it.get('cliente')} {it.get('tramo')}".strip(), it.get("lado"),
                                  f"coche {it['coche']}" if it.get("coche") else "") if x)


def _linea_aviso(it):
    if it["origen"] == "reserva":
        return f"Reserva {it['corredor']} ({'ida' if it['lado'] == 'ida' else 'vuelta'})" + \
               (f" · Coche {it['coche']}" if it["coche"] else "")
    ruta = f"{it['desde']} → {it['hasta']}" if it["desde"] else it["hasta"]
    partes = [x for x in (it.get("hora"), ruta) if x]
    txt = " ".join(partes)
    if it.get("coche"):
        txt += f" · Coche {it['coche']}"
    return txt


def avisar_trafico(fecha, tipo="nacional"):
    """Después de publicar el tráfico de un día: avisa a cada chofer lo suyo.
    Devuelve {avisados, sin_app} para mostrar en pantalla."""
    import push
    hoy = _hoy_local()
    conn = get_connection()
    try:
        trips = tripulantes(conn, con_corp=True)
        nuevas = [x for x in _fotos(conn, fecha, fecha) if x[1] == tipo]
        viejas = [x for x in _fotos(conn, fecha, fecha, version_menos=1) if x[1] == tipo]
    finally:
        conn.close()
    if not nuevas:
        return {"avisados": 0, "sin_app": []}
    nuevos = [i for i in _salidas_foto(*nuevas[0])]
    viejos = [i for i in _salidas_foto(*viejas[0])] if viejas else []
    avisos, sin_app = [], []
    con_cel = push.con_avisos()
    for t in trips:
        mios = [x for x in (_para(i, t["claves"]) for i in nuevos) if x]
        antes = [x for x in (_para(i, t["claves"]) for i in viejos) if x]
        if not mios and not antes:
            continue
        if viejas and _firma(mios) == _firma(antes):
            continue                                  # a este no le cambió nada
        dia = _dia_txt(fecha, hoy)
        if not mios:
            titulo, cuerpo = f"Ya no tenés servicio {dia if dia in ('hoy', 'mañana') else 'el ' + dia}", \
                             "Se sacó tu servicio de la planilla. Tocá para ver lo que te queda."
        else:
            titulo = (f"Cambió tu servicio · {dia}" if antes else f"Tu servicio · {dia}")
            cuerpo = "\n".join(_linea_aviso(i) for i in mios[:3]) + (f"\n+{len(mios) - 3} más" if len(mios) > 3 else "")
        avisos.append((t["id"], titulo, cuerpo, "/mi", f"trafico-{fecha}-{tipo}"))
        if not con_cel.get(t["id"]):
            sin_app.append(t["nombre"])
    push.enviar_varios(avisos)
    return {"avisados": len(avisos) - len(sin_app), "sin_app": sin_app}


def avisar_corp(fecha):
    """Después de publicar la asignación de corporativos: a cada chofer lo suyo."""
    import push
    hoy = _hoy_local()
    conn = get_connection()
    try:
        vs = conn.execute("""SELECT v.version, v.datos FROM corp_asig_versiones v JOIN corp_asig_dias d ON d.id=v.dia_id
                             WHERE d.fecha=? ORDER BY v.version DESC LIMIT 2""", (fecha,)).fetchall()
        usuarios = {r["usuario"]: r["id"] for r in conn.execute(
            "SELECT id, usuario FROM usuarios WHERE COALESCE(activo,1)=1").fetchall()}
        trips = tripulantes(conn, con_corp=True)
    finally:
        conn.close()
    if not vs:
        return {"avisados": 0, "sin_app": []}
    nueva = json.loads(vs[0]["datos"])
    vieja = json.loads(vs[1]["datos"]) if len(vs) > 1 else None

    def por_chofer(f):
        d = {}
        for x in (f or {}).get("filas") or []:
            u = (x.get("chofer_usuario") or "").strip().lower()
            if u:
                d.setdefault(u, []).append(x)
        return d

    pn, pv = por_chofer(nueva), por_chofer(vieja)
    # La misma persona con otro usuario (el de línea): le llega también, por el nombre
    otros = {}
    for x in ((nueva or {}).get("filas") or []) + ((vieja or {}).get("filas") or []):
        u = (x.get("chofer_usuario") or "").strip().lower()
        if not u or u in otros:
            continue
        otros[u] = [t["id"] for t in trips if t["usuario"].lower() != u and x.get("chofer_nombre")
                    and coincide(x["chofer_nombre"], t["claves"])]
    con_cel = push.con_avisos()
    nombres = {}
    for x in ((nueva or {}).get("filas") or []):
        if x.get("chofer_usuario"):
            nombres[x["chofer_usuario"].strip().lower()] = x.get("chofer_nombre") or x["chofer_usuario"]
    firma = lambda xs: sorted((x.get("cliente"), x.get("tramo"), x.get("lado"), x.get("coche"), x.get("hora", "")) for x in xs)
    avisos, sin_app = [], []
    dia = _dia_txt(fecha, hoy)
    for u in set(pn) | set(pv):
        uid = usuarios.get(u)
        if not uid or (vieja is not None and firma(pn.get(u, [])) == firma(pv.get(u, []))):
            continue
        mios = pn.get(u, [])
        if not mios:
            titulo, cuerpo = f"Se cambió tu asignación · {dia}", "Ya no tenés servicio asignado ese día."
        else:
            titulo = f"{'Cambió tu' if u in pv else 'Tu'} asignación · {dia}"
            lineas = []
            for x in mios[:3]:
                lado = {"entrante": " (entrada)", "saliente": " (salida)"}.get(x.get("lado"), "")
                lineas.append(f"{x.get('cliente')} · {x.get('tramo')}{lado}" +
                              (f" · Coche {x['coche']}" if x.get("coche") else ""))
            cuerpo = "\n".join(lineas) + "\nTocá para confirmar que la recibiste."
        avisos.append((uid, titulo, cuerpo, "/mi", f"corp-{fecha}"))
        for o in otros.get(u, []):
            avisos.append((o, titulo, cuerpo, "/mi", f"corp-{fecha}"))
        if not con_cel.get(uid) and not any(con_cel.get(o) for o in otros.get(u, [])):
            sin_app.append(nombres.get(u) or u)
    push.enviar_varios(avisos)
    return {"avisados": len(avisos) - len(sin_app), "sin_app": sorted(sin_app)}


def avisar_turismo(servicios_por_fecha):
    """servicios de turismo [{fecha, hora, cliente, salida, destino, coches:[{coche, tripulacion}]}]
    → un aviso por chofer con lo suyo."""
    import push
    hoy = _hoy_local()
    conn = get_connection()
    try:
        trips = tripulantes(conn, con_corp=True)
    finally:
        conn.close()
    idx = _indice(trips)
    por_uid, sin_usuario = {}, {}
    for s in servicios_por_fecha:
        for c in s.get("coches") or []:
            personas = separar_personas(c.get("tripulacion") or "")
            for p in personas:
                t = idx.get(clave_persona(p)) or next((x for x in trips if coincide(p, x["claves"])), None)
                if not t:
                    sin_usuario.setdefault(clave_persona(p), apellido_primero(p))
                    continue
                por_uid.setdefault(t["id"], {"t": t, "items": []})["items"].append({
                    "fecha": s["fecha"], "hora": s.get("hora") or "", "cliente": _lindo(s.get("cliente") or ""),
                    "desde": s.get("salida") or "", "hasta": s.get("destino") or "", "coche": c.get("coche") or ""})
    con_cel = push.con_avisos()
    avisos, sin_app = [], []
    for uid, d in por_uid.items():
        its = sorted(d["items"], key=lambda x: (x["fecha"], x["hora"]))
        if len({i["fecha"] for i in its}) == 1:
            titulo = f"Turismo · {_dia_txt(its[0]['fecha'], hoy)}"
        else:
            titulo = f"Turismo · {len(its)} servicios"
        lineas = []
        for i in its[:3]:
            ruta = f"{i['desde']} → {i['hasta']}" if i["desde"] and i["hasta"] else (i["hasta"] or i["desde"])
            pre = "" if len({x['fecha'] for x in its}) == 1 else f"{_dia_txt(i['fecha'], hoy).capitalize()} "
            lineas.append(f"{pre}{i['hora'] + ' ' if i['hora'] else ''}{ruta}" +
                          (f" · {i['cliente']}" if i["cliente"] else "") + (f" · Coche {i['coche']}" if i["coche"] else ""))
        avisos.append((uid, titulo, "\n".join(lineas), "/mi", "turismo"))
        if not con_cel.get(uid):
            sin_app.append(d["t"]["nombre"])
    push.enviar_varios(avisos)
    return {"avisados": len(avisos) - len(sin_app), "sin_app": sin_app, "sin_usuario": sorted(sin_usuario.values())}


# ════════════════════════════════════════════════════════════════════════════
# ALTA DE USUARIOS
# ════════════════════════════════════════════════════════════════════════════

def _distancia(a, b, tope=3):
    if abs(len(a) - len(b)) > tope:
        return tope + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def candidatos(conn):
    """Los choferes que figuran en tráfico y turismo y todavía no tienen usuario,
    agrupando las formas distintas de escribir a la misma persona."""
    nombres = {}
    for r in conn.execute("SELECT nombre, COALESCE(usos,0) AS usos FROM trafico_tripulantes").fetchall():
        for p in separar_personas(r["nombre"]):
            nombres[p] = nombres.get(p, 0) + int(r["usos"] or 0) + 1
    for r in conn.execute("""SELECT tripulacion, tripulacion_2, tripulacion_3 FROM agenda_turismo
                             WHERE COALESCE(estado,'') <> 'cancelado'""").fetchall():
        for campo in ("tripulacion", "tripulacion_2", "tripulacion_3"):
            for p in separar_personas(r[campo]):
                nombres[p] = nombres.get(p, 0) + 1
    # Ya tienen usuario: los tripulantes y también los choferes de corporativos y de taller
    tomadas, personas = set(), []
    for r in conn.execute("""SELECT nombre, COALESCE(alias_planilla,'') AS alias FROM usuarios
                             WHERE rol IN ('tripulante', 'chofer_corp', 'chofer')""").fetchall():
        ks = _claves_de(r["nombre"], r["alias"])
        tomadas |= ks
        personas.append(ks)
    # Agrupar: misma clave, o casi igual (un error de tipeo)
    grupos = []
    for n, usos in sorted(nombres.items(), key=lambda x: -x[1]):
        k = clave_persona(n)
        if not k:
            continue
        g = next((g for g in grupos if k in g["claves"] or any(
            len(k) >= 8 and _distancia(k, x, 2) <= (1 if len(k) < 12 else 2) for x in g["claves"])), None)
        if g:
            g["claves"].add(k)
            g["variantes"].append(n)
            g["usos"] += usos
        else:
            grupos.append({"nombre": n, "claves": {k}, "variantes": [n], "usos": usos})
    out = []
    for g in grupos:
        if g["claves"] & tomadas or any(_distancia(k, t, 2) <= 1 for k in g["claves"] for t in tomadas if len(k) >= 8):
            continue
        if any(misma_persona(g["claves"], ks) for ks in personas):
            continue                            # ya tiene usuario (con un segundo nombre de más o de menos)
        alias = sorted({v for v in g["variantes"] if clave_persona(v) != clave_persona(g["nombre"])})
        out.append({"nombre": apellido_primero(g["nombre"]).upper(), "alias": alias, "usos": g["usos"]})
    out.sort(key=lambda x: x["nombre"])
    return out


def _usuario_para(nombre, ocupados):
    pila = nombre.split(",", 1)[-1].strip() if "," in nombre else nombre.split()[0]
    base = re.sub(r"[^a-z]", "", _llano(pila.split()[0] if pila.split() else pila)) or "chofer"
    ape = nombre.split(",", 1)[0].strip() if "," in nombre else nombre.split()[-1]
    ini = re.sub(r"[^a-z]", "", _llano(ape))[:1] or "x"
    for c in [base, base + ini, base + re.sub(r"[^a-z]", "", _llano(ape))] + [f"{base}{ini}{n}" for n in range(2, 30)]:
        if c not in ocupados:
            return c
    return None


def crear_usuarios(nombres=None):
    """Crea los usuarios que faltan (o solo los nombres pedidos). Usuario y clave
    iguales: el nombre de pila, en minúscula."""
    from database import crear_usuario
    conn = get_connection()
    try:
        cands = candidatos(conn)
        ocupados = {r["usuario"].lower() for r in conn.execute("SELECT usuario FROM usuarios").fetchall()}
    finally:
        conn.close()
    if nombres:
        quiero = {clave_persona(n) for n in nombres}
        cands = [c for c in cands if clave_persona(c["nombre"]) in quiero]
    creados = []
    for c in cands:
        u = _usuario_para(c["nombre"], ocupados)
        if not u:
            continue
        ok, _ = crear_usuario(u, u, nombre=c["nombre"], rol=ROL)
        if not ok:
            continue
        ocupados.add(u)
        if c["alias"]:
            conn = get_connection()
            try:
                conn.execute("UPDATE usuarios SET alias_planilla=? WHERE usuario=?", ("; ".join(c["alias"]), u))
                conn.commit()
            finally:
                conn.close()
        creados.append({"nombre": c["nombre"], "usuario": u, "clave": u})
    return creados


# ════════════════════════════════════════════════════════════════════════════
# LA MISMA PERSONA CON DOS USUARIOS (corporativo + línea)
# ════════════════════════════════════════════════════════════════════════════

def misma_persona(ka, kb):
    """Si dos juegos de claves de nombre son de la misma persona: igual, uno
    con un segundo nombre o apellido de más, o con un error de tipeo."""
    if not ka or not kb:
        return False
    if ka & kb:
        return True
    if any(coincide(x, kb) for x in ka) or any(coincide(x, ka) for x in kb):
        return True
    return any(len(x) >= 8 and len(y) >= 8 and _distancia(x, y, 2) <= 1 for x in ka for y in kb)


def _cual_queda(a, b):
    """De dos usuarios de la misma persona, cuál queda: el corporativo (tiene
    las rendiciones y la asignación); si no, el que ya entró o confirmó la app."""
    if (a["rol"] == CORP) != (b["rol"] == CORP):
        return (a, b) if a["rol"] == CORP else (b, a)
    puntaje = lambda u: (bool(u.get("app_confirmado_el")), u.get("ultimo_acceso") or "", -u["id"])
    return (a, b) if puntaje(a) >= puntaje(b) else (b, a)


def duplicados(conn):
    """Las personas que quedaron con dos usuarios de chofer."""
    us = tripulantes(conn, con_corp=True)
    pares, vistos = [], set()
    for i, a in enumerate(us):
        for b in us[i + 1:]:
            if a["rol"] == CORP and b["rol"] == CORP:
                continue                    # dos corporativos: cada uno con sus rendiciones, no se tocan
            if a["id"] in vistos or b["id"] in vistos:
                continue
            if misma_persona(a["claves"], b["claves"]):
                q, s_ = _cual_queda(a, b)
                pares.append({"queda": _ficha(q), "sale": _ficha(s_)})
                vistos.add(s_["id"])
    return pares


def _ficha(u):
    return {"id": u["id"], "usuario": u["usuario"], "nombre": u["nombre"], "rol": u["rol"],
            "ultimo_acceso": u.get("ultimo_acceso") or "", "confirmado": bool(u.get("app_confirmado_el"))}


def unir(queda_id, sale_id, quien=""):
    """Junta dos usuarios de la misma persona en uno: el que queda se lleva el
    nombre del otro como «también figura como», sus celulares con avisos y la
    confirmación de la app. El otro se borra."""
    if not queda_id or not sale_id or queda_id == sale_id:
        return None, "Elegí dos usuarios distintos"
    conn = get_connection()
    try:
        filas = {r["id"]: dict(r) for r in conn.execute(
            f"""SELECT id, usuario, nombre, rol, COALESCE(alias_planilla,'') AS alias, ultimo_acceso,
                       COALESCE(app_confirmado_el,'') AS app_confirmado_el, COALESCE(app_modo,'') AS app_modo
                FROM usuarios WHERE id IN (?,?)""", (queda_id, sale_id)).fetchall()}
        q, s_ = filas.get(queda_id), filas.get(sale_id)
        if not q or not s_:
            return None, "Uno de los dos usuarios ya no existe"
        if q["rol"] not in ROLES_APP or s_["rol"] not in ROLES_APP:
            return None, "Solo se unen usuarios de choferes"
        if q["rol"] == CORP and s_["rol"] == CORP:
            return None, "Los dos son corporativos y cada uno tiene sus rendiciones: no se pueden unir"
        if s_["rol"] == CORP:                    # siempre queda el corporativo
            q, s_ = s_, q
        # «También figura como»: el nombre y los alias del que sale
        propias = _claves_de(q["nombre"])
        alias, ks = [], set()
        for a in [x.strip() for x in q["alias"].split(";")] + [s_["nombre"]] + [x.strip() for x in s_["alias"].split(";")]:
            k = clave_persona(a)
            if a and k and k not in propias and k not in ks:
                ks.add(k)
                alias.append(a.upper())
        conn.execute("""UPDATE usuarios SET alias_planilla=?, app_confirmado_el=?, app_modo=?, ultimo_acceso=? WHERE id=?""",
                     ("; ".join(alias)[:500], q["app_confirmado_el"] or s_["app_confirmado_el"],
                      q["app_modo"] or s_["app_modo"],
                      max(q["ultimo_acceso"] or "", s_["ultimo_acceso"] or "") or None, q["id"]))
        try:
            conn.execute("UPDATE push_subs SET usuario_id=? WHERE usuario_id=?", (q["id"], s_["id"]))
        except Exception:
            conn.rollback()
            raise
        conn.execute("DELETE FROM usuarios WHERE id=?", (s_["id"],))
        conn.commit()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return None, f"No se pudo unir: {e}"
    finally:
        conn.close()
    try:
        from database import registrar_auditoria
        registrar_auditoria(usuario=quien or "?", rol="admin", accion="Unió dos usuarios de la misma persona",
                            categoria="Usuarios", detalle=f"Quedó {q['usuario']} ({q['nombre']}); se borró {s_['usuario']} ({s_['nombre']})")
    except Exception:
        pass
    return {"queda": {"id": q["id"], "usuario": q["usuario"], "nombre": q["nombre"], "rol": q["rol"]},
            "sale": {"usuario": s_["usuario"], "nombre": s_["nombre"]}}, None


# ════════════════════════════════════════════════════════════════════════════
# RUTAS
# ════════════════════════════════════════════════════════════════════════════

def _pila(nombre):
    n = str(nombre or "").strip() or "?"
    p = (n.split(",", 1)[-1] if "," in n else n.split()[0]).strip().split() or ["?"]
    return p[0].capitalize()


def _es_admin():
    return session.get("rol") == "admin"


def _yo():
    """El usuario que se mira: el propio, o el que elige el admin (?u=) para ver
    la app como la ve ese chofer. El admin puede mover el día (?hoy=) para probar."""
    hoy = _hoy_local()
    if _es_admin():
        if request.args.get("hoy") and re.match(r"^\d{4}-\d{2}-\d{2}$", request.args["hoy"]):
            hoy = request.args["hoy"]
        uid = request.args.get("u", type=int)
    else:
        uid = session.get("usuario_id")
    conn = get_connection()
    try:
        u = conn.execute("""SELECT id, usuario, nombre, rol, COALESCE(alias_planilla,'') AS alias FROM usuarios
                            WHERE id=?""", (uid or 0,)).fetchone()
    finally:
        conn.close()
    if not u or u["rol"] not in ROLES_APP:
        return None, hoy
    d = dict(u)
    d["claves"] = _claves_de(d["nombre"], d["alias"])
    d["corp"] = d["usuario"] if d["rol"] == CORP else None
    return d, hoy


@bp_choferes_app.route("/mi")
def pantalla_mi():
    if session.get("rol") not in (ROL, CORP, "admin"):
        from flask import redirect
        return redirect("/")
    from app_movil import COLOR_TEMA
    html = render_template("mi.html", nombre=session.get("nombre") or "", tema=COLOR_TEMA,
                           admin=_es_admin(), es_corp=session.get("rol") == CORP)
    r = make_response(html)
    r.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return r


@bp_choferes_app.route("/api/mi/inicio", methods=["GET"])
def api_inicio():
    yo, hoy = _yo()
    if not yo:
        return jsonify({"ok": False, "msg": "Elegí un chofer para ver su app" if _es_admin() else "Sin permiso"}), 403
    conn = get_connection()
    try:
        prox = proximos(conn, yo["claves"], hoy, yo["corp"])
        acuses = acuses_pendientes(conn, yo["corp"], yo["claves"], hoy)
    finally:
        conn.close()
    pila = _pila(yo["nombre"])
    from hora_local import ahora as _ahora_local
    ahora = _ahora_local().strftime("%H:%M") if hoy == _hoy_local() else "00:00"
    return jsonify({"ok": True, "hoy": hoy, "ahora": ahora, "hoy_txt": _dia_largo(hoy), "nombre": yo["nombre"],
                    "pila": pila.capitalize(), "usuario_id": yo["id"], "corp": bool(yo["corp"]),
                    "proximos": [dict(i, dia_txt=_dia_txt(i["fecha"], hoy), dia_largo=_dia_largo(i["fecha"]))
                                 for i in prox],
                    "acuses": acuses})


@bp_choferes_app.route("/api/mi/asignacion", methods=["GET"])
def api_acuses():
    """Las asignaciones que el chofer tiene que confirmar que recibió."""
    yo, hoy = _yo()
    if not yo:
        return jsonify({"ok": False, "pendientes": []}), 403
    conn = get_connection()
    try:
        pend = acuses_pendientes(conn, yo["corp"], yo["claves"], hoy)
    finally:
        conn.close()
    return jsonify({"ok": True, "pendientes": pend, "pila": _pila(yo["nombre"])})


@bp_choferes_app.route("/api/mi/asignacion/recibido", methods=["POST"])
def api_acuse_recibido():
    """El chofer toca «Recibí mi asignación»: queda confirmada lo que tiene
    asignado ahora (si después cambia, se le vuelve a pedir)."""
    if _es_admin():
        return jsonify({"ok": False, "msg": "La vista previa no confirma por el chofer"}), 400
    yo, hoy = _yo()
    if not yo:
        return jsonify({"ok": False}), 403
    from hora_local import ahora_iso
    import push
    equipo = push._equipo(request.headers.get("User-Agent"))
    cuando = ahora_iso()
    conn = get_connection()
    try:
        pend = acuses_pendientes(conn, yo["corp"], yo["claves"], hoy)
        for p in pend:
            conn.execute("DELETE FROM corp_asig_acuses WHERE fecha=? AND chofer_usuario=?", (p["fecha"], p["chofer_usuario"]))
            conn.execute("""INSERT INTO corp_asig_acuses (fecha, chofer_usuario, firma, confirmado_el, usuario_id, equipo)
                            VALUES (?,?,?,?,?,?)""", (p["fecha"], p["chofer_usuario"], p["firma"], cuando, yo["id"], equipo))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return jsonify({"ok": True, "confirmadas": len(pend)})


# ── Para el admin: los accesos ──────────────────────────────────────────────

@bp_choferes_app.route("/api/choferes_app/accesos", methods=["GET"])
def api_accesos():
    if not _es_admin():
        return jsonify({"ok": False, "msg": "Solo administración"}), 403
    import push
    hoy = _hoy_local()
    conn = get_connection()
    try:
        trips = tripulantes(conn, solo_activos=False)
        cands = candidatos(conn)
        dups = duplicados(conn)
        from servicios import leer_servicios
        servs = leer_servicios(conn, hoy[:7] + "-01", hoy)
    finally:
        conn.close()
    cel = push.con_avisos()
    lista = []
    for t in trips:
        n = sum(1 for s in servs if any(coincide(x, t["claves"]) for x in s["trips"]))
        lista.append({"id": t["id"], "usuario": t["usuario"], "nombre": t["nombre"], "alias": t["alias"],
                      "activo": bool(t["activo"] if t["activo"] is not None else 1),
                      "ultimo_acceso": t["ultimo_acceso"] or "", "avisos": cel.get(t["id"], 0),
                      "confirmado_el": t["app_confirmado_el"], "modo": t["app_modo"],
                      "servicios_mes": n})
    # Los de corporativos: solo si confirmaron la app y si tienen los avisos
    conn = get_connection()
    try:
        corp = [dict(r) for r in conn.execute("""
            SELECT id, usuario, nombre, ultimo_acceso, COALESCE(app_confirmado_el,'') AS confirmado_el,
                   COALESCE(app_modo,'') AS modo, COALESCE(alias_planilla,'') AS alias
            FROM usuarios WHERE rol='chofer_corp' AND COALESCE(activo,1)=1 ORDER BY nombre""").fetchall()]
    finally:
        conn.close()
    for c in corp:
        c["avisos"] = cel.get(c["id"], 0)
    activos = [x for x in lista if x["activo"]]
    return jsonify({"ok": True, "choferes": lista, "faltan": cands, "corp": corp, "duplicados": dups,
                    "con_avisos": sum(1 for x in lista if x["avisos"]),
                    "confirmaron": sum(1 for x in activos if x["confirmado_el"]), "activos": len(activos),
                    "corp_confirmaron": sum(1 for x in corp if x["confirmado_el"]),
                    "mes_txt": MESES[int(hoy[5:7]) - 1]})


@bp_choferes_app.route("/api/choferes_app/crear", methods=["POST"])
def api_crear():
    if not _es_admin():
        return jsonify({"ok": False, "msg": "Solo administración"}), 403
    d = request.get_json(silent=True) or {}
    creados = crear_usuarios(d.get("nombres") or None)
    try:
        from database import registrar_auditoria
        registrar_auditoria(usuario=session.get("nombre") or session.get("usuario") or "?", rol="admin",
                            accion="Creó usuarios de choferes de línea y turismo", categoria="Usuarios",
                            detalle=f"{len(creados)} usuario(s)")
    except Exception:
        pass
    return jsonify({"ok": True, "creados": creados})


@bp_choferes_app.route("/api/choferes_app/unir", methods=["POST"])
def api_unir():
    """Une dos usuarios de la misma persona. Con {todos: true}, todos los que
    se detectaron solos."""
    if not _es_admin():
        return jsonify({"ok": False, "msg": "Solo administración"}), 403
    d = request.get_json(silent=True) or {}
    quien = session.get("nombre") or session.get("usuario") or ""
    if d.get("todos"):
        conn = get_connection()
        try:
            pares = duplicados(conn)
        finally:
            conn.close()
        hechos, errores = [], []
        for p in pares:
            r, err = unir(p["queda"]["id"], p["sale"]["id"], quien)
            (hechos.append(r) if r else errores.append(f"{p['sale']['nombre']}: {err}"))
        return jsonify({"ok": True, "unidos": hechos, "errores": errores})
    try:
        q, s_ = int(d.get("queda") or 0), int(d.get("sale") or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "msg": "Faltan datos"}), 400
    r, err = unir(q, s_, quien)
    if not r:
        return jsonify({"ok": False, "msg": err}), 400
    return jsonify({"ok": True, "unidos": [r]})


@bp_choferes_app.route("/api/choferes_app/<int:uid>/alias", methods=["POST"])
def api_alias(uid):
    if not _es_admin():
        return jsonify({"ok": False, "msg": "Solo administración"}), 403
    alias = str((request.get_json(silent=True) or {}).get("alias") or "")
    alias = "; ".join(x.strip().upper() for x in re.split(r"[;\n]", alias) if x.strip())[:500]
    conn = get_connection()
    try:
        conn.execute("UPDATE usuarios SET alias_planilla=? WHERE id=? AND rol IN (?,?)", (alias, uid, ROL, CORP))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True, "alias": alias})


@bp_choferes_app.route("/api/choferes_app/<int:uid>/clave", methods=["POST"])
def api_reset_clave(uid):
    """Vuelve la clave a la fácil (igual al usuario), si el chofer se la olvidó."""
    if not _es_admin():
        return jsonify({"ok": False, "msg": "Solo administración"}), 403
    from database import _hash_password
    conn = get_connection()
    try:
        u = conn.execute("SELECT usuario FROM usuarios WHERE id=? AND rol IN (?,?)", (uid, ROL, CORP)).fetchone()
        if not u:
            return jsonify({"ok": False, "msg": "No existe"}), 404
        conn.execute("UPDATE usuarios SET password_hash=? WHERE id=?", (_hash_password(u["usuario"]), uid))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True, "clave": u["usuario"]})


@bp_choferes_app.route("/api/choferes_app/avisar_prueba/<int:uid>", methods=["POST"])
def api_avisar_prueba(uid):
    """El admin le manda un aviso de prueba a un chofer para ver si le llega."""
    if not _es_admin():
        return jsonify({"ok": False, "msg": "Solo administración"}), 403
    import push
    r = push.enviar_ya([uid], "Hola desde La Santaniana", "Este es un aviso de prueba de la oficina.", "/mi", "prueba")
    return jsonify({"ok": bool(r["enviados"]), **r,
                    "msg": "" if r["enviados"] else "Ese chofer no tiene los avisos activados en su celular."})


@bp_choferes_app.route("/api/mi/choferes", methods=["GET"])
def api_lista_choferes():
    """Para el admin: a quién mirar en la vista previa de la app."""
    if not _es_admin():
        return jsonify({"ok": False}), 403
    conn = get_connection()
    try:
        filas = conn.execute("""SELECT id, nombre, usuario, rol FROM usuarios WHERE rol IN (?,?) AND COALESCE(activo,1)=1
                                ORDER BY nombre""", (ROL, CORP)).fetchall()
    finally:
        conn.close()
    return jsonify({"ok": True, "choferes": [dict(f) for f in filas]})


# ── Turismo: avisar desde la ventana de la asignación ───────────────────────

@bp_choferes_app.route("/api/turismo/asignacion/avisar", methods=["POST"])
def api_avisar_turismo():
    if session.get("rol") not in ("admin", "taller"):
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    import turismo_asig_pdf as tap
    a = request.args
    hoy = _hoy_local()
    desde, hasta = a.get("desde") or hoy, a.get("hasta") or a.get("desde") or hoy
    if hasta < desde:
        desde, hasta = hasta, desde
    fechas = [x for x in (a.get("fechas") or "").split(",") if x] or None
    info = tap.datos(desde, hasta, cliente=a.get("cliente") or None, cancelados=False, fechas=fechas)
    servs = []
    for d in info.get("dias") or []:
        for s in d.get("servicios") or []:
            if s.get("estado") == "cancelado":
                continue
            servs.append({"fecha": d.get("fecha") or s.get("fecha"), "hora": s.get("hora"), "cliente": s.get("cliente"),
                          "salida": s.get("salida"), "destino": s.get("destino"),
                          "coches": [{"coche": c.get("coche") or c.get("coche_interno") or "",
                                      "tripulacion": c.get("tripulacion") or ""} for c in s.get("coches") or []]})
    r = avisar_turismo(servs)
    return jsonify({"ok": True, **r})



# ════════════════════════════════════════════════════════════════════════════
# ¿POR QUÉ NO LE APARECE? (para la oficina)
# ════════════════════════════════════════════════════════════════════════════

def _parecido(nombre, claves):
    """Un nombre de la planilla que se parece pero no alcanza: comparte el
    apellido o el nombre, o está escrito con un error."""
    k = clave_persona(nombre)
    if not k or coincide(nombre, claves):
        return False
    tk = set(k.split())
    for c in claves:
        tc = set(c.split())
        if len(tk & tc) >= 1 and len(tc) >= 2 and (len(tk & tc) >= len(tc) - 1):
            return True
        if len(k) >= 8 and _distancia(k, c, 3) <= 2:
            return True
    return False


def revisar(uid, dias=3):
    """Revisa, día por día, por qué un chofer no ve su servicio: si el día
    está armado, si está publicado, si después se cambió y no se volvió a
    publicar, si figura en la planilla, y si figura escrito de otra forma."""
    from trafico import LADOS
    hoy = _hoy_local()
    conn = get_connection()
    try:
        u = conn.execute("""SELECT id, usuario, nombre, rol, COALESCE(alias_planilla,'') AS alias, COALESCE(activo,1) AS activo
                            FROM usuarios WHERE id=?""", (uid,)).fetchone()
        if not u:
            return None
        u = dict(u)
        claves = _claves_de(u["nombre"], u["alias"])
        res = {"nombre": u["nombre"], "usuario": u["usuario"], "rol": u["rol"], "alias": u["alias"],
               "como_lo_busca": sorted(claves), "dias": [], "avisos": []}
        if u["rol"] not in ROLES_APP:
            res["avisos"].append("Este usuario no es chofer: no tiene la app de choferes.")
        if not u["activo"]:
            res["avisos"].append("El usuario está desactivado.")
        for n in range(dias):
            fecha = (date.fromisoformat(hoy) + timedelta(days=n)).isoformat()
            for tipo in ("nacional", "internacional"):
                dia = conn.execute("""SELECT id, version, COALESCE(publicado_el,'') AS publicado_el, COALESCE(modificado,0) AS modificado
                                      FROM trafico_dias WHERE fecha=? AND COALESCE(tipo,'nacional')=?""", (fecha, tipo)).fetchone()
                if not dia:
                    continue
                dia = dict(dia)
                # Lo que está en la planilla ahora (borrador incluido)
                filas = conn.execute("""SELECT s.hora, s.destino, s.lado, s.coche, s.trip1, s.trip2, b.nombre AS corredor
                                        FROM trafico_salidas s JOIN trafico_bloques b ON b.id = s.bloque_id
                                        WHERE s.dia_id=?""", (dia["id"],)).fetchall()
                bloques = conn.execute("SELECT * FROM trafico_bloques WHERE id IN (SELECT DISTINCT bloque_id FROM trafico_salidas WHERE dia_id=?)",
                                       (dia["id"],)).fetchall()
                ahora, parecidos = [], set()
                for f in filas:
                    for t in (f["trip1"], f["trip2"]):
                        if not (t or "").strip():
                            continue
                        if coincide(t, claves):
                            ahora.append(f"{f['hora'] or '--:--'} {f['destino'] or ''} · coche {f['coche'] or 'a confirmar'}".strip())
                        elif _parecido(t, claves):
                            parecidos.add(t.strip())
                for b in bloques:
                    b = dict(b)
                    for lado in LADOS:
                        t = b.get(f"reserva_{lado}_trip") or ""
                        if t.strip() and coincide(t, claves):
                            ahora.append(f"Reserva {b.get('nombre')} ({lado})")
                        elif t.strip() and _parecido(t, claves):
                            parecidos.add(t.strip())
                # Lo publicado
                publicado = []
                for fe, ti, foto in _fotos(conn, fecha, fecha):
                    if ti == tipo:
                        publicado = [x for x in (_para(i, claves) for i in _salidas_foto(fe, ti, foto)) if x]
                estado, que_hacer = "ok", ""
                if not ahora and not publicado:
                    if parecidos:
                        estado = "escrito_distinto"
                        que_hacer = ("En la planilla figura escrito de otra forma. Agregá ese nombre en «También figura como» "
                                     "(lápiz en la lista de choferes) y le aparece al toque.")
                    else:
                        estado = "no_figura"
                        que_hacer = "Ese día no figura en la planilla de tráfico " + tipo + "."
                elif not dia["publicado_el"]:
                    estado = "sin_publicar"
                    que_hacer = "Figura en la planilla pero el día todavía no se publicó. Publicalo en Tráfico y le llega."
                elif ahora and not publicado:
                    estado = "cambio_sin_publicar"
                    que_hacer = "Se lo agregó después de publicar y no se volvió a publicar. Publicá de nuevo el día."
                elif dia["modificado"]:
                    estado = "hay_cambios"
                    que_hacer = "Ve lo publicado. Hay cambios en la planilla sin publicar: publicá de nuevo para que vea lo último."
                res["dias"].append({"fecha": fecha, "dia": _dia_txt(fecha, hoy), "tipo": tipo, "existe": True,
                                    "publicado": bool(dia["publicado_el"]), "version": dia["version"],
                                    "en_planilla": ahora, "en_lo_publicado": [_linea_aviso(i) for i in publicado],
                                    "parecidos": sorted(parecidos), "estado": estado, "que_hacer": que_hacer})
        # Turismo de esos días
        hasta = (date.fromisoformat(hoy) + timedelta(days=dias - 1)).isoformat()
        tur, tur_par = [], set()
        for s_ in _turismo(conn, hoy, hasta):
            if any(coincide(t, claves) for t in s_["trips"]):
                tur.append(f"{s_['fecha']} {s_['hora'] or ''} {s_['desde']} → {s_['hasta']}".strip())
            for t in s_["trips"]:
                if _parecido(t, claves):
                    tur_par.add(t)
        res["turismo"] = tur
        res["turismo_parecidos"] = sorted(tur_par)
        # Asignación corporativa de esos días
        usu = u["usuario"].lower()
        corp = []
        for n in range(dias):
            fecha = (date.fromisoformat(hoy) + timedelta(days=n)).isoformat()
            try:
                dia = conn.execute("""SELECT id, version, COALESCE(publicado_el,'') AS publicado_el, COALESCE(modificado,0) AS modificado
                                      FROM corp_asig_dias WHERE fecha=?""", (fecha,)).fetchone()
            except Exception:
                conn.rollback()
                dia = None
            if not dia:
                continue
            ahora_ = [_linea_corp(i) for i in _corp(conn, usu, fecha, fecha, claves, publicado=False)]
            publ = [_linea_corp(i) for i in _corp(conn, usu, fecha, fecha, claves)]
            par = set()
            for f_ in conn.execute("SELECT chofer_usuario, chofer_nombre FROM corp_asig WHERE dia_id=?", (dia["id"],)).fetchall():
                if f_["chofer_nombre"] and not es_mio_corp(dict(f_), usu, claves) and _parecido(f_["chofer_nombre"], claves):
                    par.add(f"{f_['chofer_nombre']} (usuario {f_['chofer_usuario']})")
            estado, que_hacer = "ok", ""
            if not ahora_ and not publ:
                estado, que_hacer = ("escrito_distinto", "En la asignación hay alguien parecido. Si es él, unilos (botón de unir) "
                                     "o agregá ese nombre en «También figura como».") if par else ("no_figura", "No tiene asignación corporativa ese día.")
            elif not dia["publicado_el"]:
                estado, que_hacer = "sin_publicar", "Tiene asignación pero el día no se publicó. Publicalo en Asignación de corporativos."
            elif ahora_ and not publ:
                estado, que_hacer = "cambio_sin_publicar", "Se lo asignó después de publicar. Publicá de nuevo la asignación."
            elif dia["modificado"]:
                estado, que_hacer = "hay_cambios", "Ve lo publicado. Hay cambios sin publicar: publicá de nuevo para que vea lo último."
            if estado == "no_figura" and not par:
                continue
            corp.append({"fecha": fecha, "dia": _dia_txt(fecha, hoy), "tipo": "corporativo", "existe": True,
                         "publicado": bool(dia["publicado_el"]), "version": dia["version"], "en_planilla": ahora_,
                         "en_lo_publicado": publ, "parecidos": sorted(par), "estado": estado, "que_hacer": que_hacer})
        res["dias"].extend(corp)
        res["dias"].sort(key=lambda x: (x["fecha"], x["tipo"]))
        import push
        res["celulares_con_avisos"] = push.con_avisos([uid]).get(uid, 0)
    finally:
        conn.close()
    return res


@bp_choferes_app.route("/api/choferes_app/<int:uid>/revisar", methods=["GET"])
def api_revisar(uid):
    if not _es_admin():
        return jsonify({"ok": False, "msg": "Solo administración"}), 403
    r = revisar(uid, dias=max(1, min(7, request.args.get("dias", 3, type=int))))
    if not r:
        return jsonify({"ok": False, "msg": "No existe"}), 404
    return jsonify({"ok": True, **r})



# ════════════════════════════════════════════════════════════════════════════
# LA LISTA DE CHOFERES PARA ELEGIR EN TRÁFICO
# ════════════════════════════════════════════════════════════════════════════

def nombre_planilla(nombre):
    """'AMARILLA, VICTOR' → 'VICTOR AMARILLA', como se escribe en la planilla
    de tráfico (el PDF igual lo imprime con el apellido primero)."""
    n = " ".join(str(nombre or "").split()).upper()
    if "," in n:
        ape, nom = [x.strip() for x in n.split(",", 1)]
        return f"{nom} {ape}".strip()
    return n


@bp_choferes_app.route("/api/trafico/choferes", methods=["GET"])
def api_choferes_trafico():
    """Los choferes con usuario, para elegirlos en la planilla: así el nombre
    queda igual al del usuario y el viaje le aparece en la app seguro."""
    if session.get("rol") not in ("admin", "taller", "auditor"):
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    import push
    conn = get_connection()
    try:
        filas = conn.execute("""SELECT id, usuario, nombre, rol, COALESCE(alias_planilla,'') AS alias,
                                       COALESCE(app_confirmado_el,'') AS conf
                                FROM usuarios WHERE rol IN ('tripulante','chofer_corp') AND COALESCE(activo,1)=1
                                ORDER BY nombre""").fetchall()
    finally:
        conn.close()
    cel = push.con_avisos()
    return jsonify({"ok": True, "choferes": [{
        "id": f["id"], "n": nombre_planilla(f["nombre"]), "nombre": f["nombre"], "usuario": f["usuario"],
        "corp": f["rol"] == "chofer_corp", "app": bool(f["conf"]), "avisos": bool(cel.get(f["id"])),
        "alias": [a.strip() for a in f["alias"].split(";") if a.strip()]} for f in filas]})
