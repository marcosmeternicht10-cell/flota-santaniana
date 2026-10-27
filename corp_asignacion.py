"""
corp_asignacion.py — La asignación diaria de corporativos (La Santaniana)

Así como el tráfico arma las salidas de cada día, acá se arma quién cubre
cada tramo de los clientes corporativos y con qué coche:

  · Todos los días aparecen TODOS los tramos del catálogo de cada cliente (el
    mismo que usa el chofer para rendir), también los fines de semana: el que
    no se hace se quita a mano (queda como «no corre» y no cuenta como
    faltante). Con el historial se marca cuáles no suelen correr ese día de la
    semana, y se pueden quitar todos esos de una vez.
  · Cada tramo lo hace un chofer completo, o se divide: el entrante uno y el
    saliente otro (igual que en la rendición). Si un día no corre, se marca.
    Los servicios variables se agregan aparte.
  · Se puede copiar de otro día (ayer, el mismo día de la semana pasada) y
    cambiar lo que haga falta.
  · Se publica con versión, como el tráfico: PDF o imagen para el grupo, con
    lo que cambió marcado.
  · Asignado contra rendido: con las rendiciones de ese día se ve quién rindió
    lo suyo, quién con otro coche, qué tramo lo rindió otro chofer, quién no
    rindió y quién rindió algo sin estar asignado.
  · El horario de un tramo se puede cambiar SOLO para un día (corp_asig_horarios):
    ese día se ve, se ordena, se controla y sale en el PDF con el horario nuevo,
    y al publicar figura como cambio. Los demás días siguen con el de siempre
    (el que dice el nombre del tramo), y copiar un día no copia estos cambios.

Enganche en app.py:
    from corp_asignacion import bp_corp_asig, init_corp_asignacion
    init_corp_asignacion()
    app.register_blueprint(bp_corp_asig)
"""

import json
import re
import unicodedata
from datetime import date, timedelta
from functools import lru_cache

from flask import Blueprint, request, jsonify, session, Response
from db_compat import get_connection, USE_POSTGRES

from hora_local import hoy as _hoy, ahora_iso
import corporativos as C

bp_corp_asig = Blueprint("corp_asignacion", __name__)

PK = "SERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"

LADOS_TRAMO = ("completo", "entrante", "saliente")
NOMBRE_LADO = {"completo": "completo", "entrante": "entrante", "saliente": "saliente"}
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]
DIAS_HISTORIAL = 120          # cuánto historial se mira para saber qué tramos corren


# ════════════════════════════════════════════════════════════════════════════
# TABLAS
# ════════════════════════════════════════════════════════════════════════════

def _rollback(conn):
    try:
        conn.rollback()
    except Exception:
        pass


def init_corp_asignacion():
    conn = get_connection()
    for sql in (
        f"""CREATE TABLE IF NOT EXISTS corp_asig_dias (
            id {PK},
            fecha TEXT NOT NULL UNIQUE,
            version INTEGER DEFAULT 0,
            modificado INTEGER DEFAULT 0,
            publicado_el TEXT DEFAULT '',
            publicado_por TEXT DEFAULT '',
            nota TEXT DEFAULT '',
            creado_el TEXT DEFAULT '',
            creado_por TEXT DEFAULT '')""",
        # lado: completo | entrante | saliente | no_corre | variable
        f"""CREATE TABLE IF NOT EXISTS corp_asig (
            id {PK},
            dia_id INTEGER NOT NULL,
            cliente TEXT NOT NULL,
            tramo TEXT NOT NULL,
            lado TEXT NOT NULL DEFAULT 'completo',
            chofer_usuario TEXT DEFAULT '',
            chofer_nombre TEXT DEFAULT '',
            coche TEXT DEFAULT '',
            hora TEXT DEFAULT '',
            detalle TEXT DEFAULT '',
            nota TEXT DEFAULT '',
            actualizado_el TEXT DEFAULT '',
            actualizado_por TEXT DEFAULT '')""",
        f"""CREATE TABLE IF NOT EXISTS corp_asig_versiones (
            id {PK},
            dia_id INTEGER NOT NULL,
            version INTEGER NOT NULL,
            publicado_el TEXT DEFAULT '',
            publicado_por TEXT DEFAULT '',
            datos TEXT DEFAULT '',
            cambios TEXT DEFAULT '')""",
        # El horario de un tramo cambiado solo para ese día
        f"""CREATE TABLE IF NOT EXISTS corp_asig_horarios (
            id {PK},
            dia_id INTEGER NOT NULL,
            cliente TEXT NOT NULL,
            tramo TEXT NOT NULL,
            hora TEXT DEFAULT '',
            hora_fin TEXT DEFAULT '',
            cambiado_el TEXT DEFAULT '',
            cambiado_por TEXT DEFAULT '')""",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_corpasigh ON corp_asig_horarios (dia_id, cliente, tramo)",
        "CREATE INDEX IF NOT EXISTS ix_corpasig_dia ON corp_asig (dia_id)",
        "CREATE INDEX IF NOT EXISTS ix_corpasigv_dia ON corp_asig_versiones (dia_id)",
        "CREATE INDEX IF NOT EXISTS ix_rendcorp_fecha ON rendiciones_corp (fecha_servicio)",
    ):
        try:
            conn.execute(sql)
            conn.commit()
        except Exception:
            _rollback(conn)
    conn.close()


# ════════════════════════════════════════════════════════════════════════════
# CATÁLOGO: clientes, tramos y horarios
# ════════════════════════════════════════════════════════════════════════════

def clientes_activos():
    return [c for c in C.CLIENTES_TRAMOS if c not in C.CLIENTES_INACTIVOS]


def tramo_corto(t):
    """'ADM RUTA 1 - 7:00 A 17:00' → 'ADM RUTA 1'; el horario va aparte."""
    s = str(t or "")
    s = re.sub(r"\(\s*\d{1,2}[:.]\d{2}[^)]*\)", " ", s)
    s = re.sub(r"\d{1,2}[:.]\d{2}\s*(?:(?:A|/|-)\s*\d{1,2}[:.]\d{2})?\s*(?:HS\.?)?", " ", s, flags=re.I)
    s = re.sub(r"\s*[-/]\s*(?=[-/]|$)", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" -/")
    s = re.sub(r"\s*/\s*-\s*", " · ", s)
    s = re.sub(r"\s+-\s+", " · ", s)
    s = re.sub(r"\s*/\s*$", "", s)
    return s.strip(" -/·") or str(t or "")


def _hhmm(h):
    if h is None:
        return ""
    h = h % 24
    hh, mm = int(h), int(round((h - int(h)) * 60))
    if mm == 60:
        hh, mm = (hh + 1) % 24, 0
    return f"{hh:02d}:{mm:02d}"


def _con_horario(tramo, h):
    """El tramo con el horario cambiado para ese día, para calcular con él
    (la clave sigue siendo el nombre real del tramo). Sin cambio, el mismo."""
    if not h or not h.get("hora"):
        return tramo
    return f"{tramo_corto(tramo)} {h['hora']}" + (f"/{h['hora_fin']}" if h.get("hora_fin") else "")


def info_tramo(tramo, h=None):
    """Horario del tramo: el de siempre (el que dice su nombre) o, si se pasa
    h, el cambiado para ese día."""
    efectivo = _con_horario(tramo, h)
    horas = C._horas_del_tramo(efectivo)
    ini = horas[0] if horas else None
    fin = horas[1] if len(horas) > 1 else None
    dur = None
    if ini is not None and fin is not None:
        dur = fin - ini if fin > ini else 24 - ini + fin
    out = {"corto": tramo_corto(tramo), "ini": ini, "fin": fin,
           "hora": _hhmm(ini), "hora_fin": _hhmm(fin),
           "jornada": bool(dur is not None and dur >= C.HORAS_JORNADA_COMPLETA),
           "horario_cambiado": efectivo != tramo}
    if efectivo != tramo:
        normal = info_tramo(tramo)
        out["hora_normal"], out["hora_fin_normal"] = normal["hora"], normal["hora_fin"]
    return out


def _txt_horario(hora, fin):
    return (f"{hora} a {fin}" if fin else hora) if hora else "sin horario"


def _orden_tramo(tramo, idx, h=None):
    i = info_tramo(tramo, h)
    if i["ini"] is not None:
        return (i["ini"], idx)
    t = tramo.upper()
    # Los administrativos sin horario en el nombre son de la mañana
    return (7.0 if t.startswith("ADM") else 99.0, idx)


ESTADO_DE_LADO = {"completo": "completado", "entrante": "entrante", "saliente": "saliente"}


def rango(fila, h=None):
    """El horario que ocupa una asignación (como lo controla la rendición),
    con el horario de ese día si se cambió."""
    if fila["lado"] == "variable":
        hs = C._horas_del_tramo(fila.get("hora") or "")
        return (hs[0], hs[0] + 1.0) if hs else None
    return C.rango_horario(_con_horario(fila["tramo"], h), estado=ESTADO_DE_LADO.get(fila["lado"], "completado"))


def nombre_lindo(n):
    """'PEREZ, WALTER' → 'Walter Perez' (como se lee en la pantalla)."""
    s = str(n or "").strip()
    if not s:
        return ""
    t = lambda x: " ".join(w[:1].upper() + w[1:].lower() for w in x.split())
    if "," in s:
        ap, no = s.split(",", 1)
        return f"{t(no.strip())} {t(ap.strip())}".strip()
    return t(s)


def _norm(s):
    s = unicodedata.normalize("NFD", str(s or "").upper())
    return "".join(ch for ch in s if unicodedata.category(ch) != "Mn").strip()


def _coche_norm(c):
    c = re.sub(r"\s+", "", str(c or "").upper())
    d = re.sub(r"\D", "", c)
    return d.lstrip("0") or c


# ════════════════════════════════════════════════════════════════════════════
# QUÉ TRAMOS CORREN (del historial de rendiciones)
# ════════════════════════════════════════════════════════════════════════════

@lru_cache(maxsize=4096)
def _canon(cliente, tramo):
    """Cliente y tramo como figuran en el catálogo (hay pocos pares distintos:
    se calcula una vez cada uno)."""
    return C._canonizar(cliente, tramo)


def _actividad(conn, fecha):
    """Por cliente y tramo: cuántas veces se rindió en días hábiles, sábados y
    domingos (últimos meses). Con eso se sabe qué tramos corren cada día."""
    desde = (date.fromisoformat(fecha) - timedelta(days=DIAS_HISTORIAL)).isoformat()
    act, con_hist = {}, set()
    for r in conn.execute("""SELECT cliente, tramo, fecha_servicio FROM rendiciones_corp
                             WHERE fecha_servicio >= ? AND fecha_servicio < ?""", (desde, fecha)).fetchall():
        cli, tr = _canon(r["cliente"], r["tramo"])
        if not cli or not tr or C._es_variable(tr):
            continue
        try:
            w = date.fromisoformat(str(r["fecha_servicio"])[:10]).weekday()
        except ValueError:
            continue
        a = act.setdefault((cli, tr), [0, 0, 0])
        a[0 if w < 5 else 1 if w == 5 else 2] += 1
        con_hist.add(cli)
    return act, con_hist


def corre(cliente, tramo, w, act, con_hist):
    """Si se espera que ese tramo corra ese día de la semana (0 = lunes)."""
    if cliente in C.CLIENTES_SOLO_HABILES and w >= 5:
        return False
    if cliente not in con_hist:
        return True                       # sin historial: se propone todo el catálogo
    a = act.get((cliente, tramo))
    if not a:
        return False
    return a[0 if w < 5 else 1 if w == 5 else 2] > 0


# ════════════════════════════════════════════════════════════════════════════
# EL DÍA
# ════════════════════════════════════════════════════════════════════════════

def _dia(conn, fecha):
    r = conn.execute("SELECT * FROM corp_asig_dias WHERE fecha=?", (fecha,)).fetchone()
    return dict(r) if r else None


def _crear_dia(conn, fecha, quien=""):
    d = _dia(conn, fecha)
    if d:
        return d["id"]
    conn.execute("""INSERT INTO corp_asig_dias (fecha, version, modificado, creado_el, creado_por)
                    VALUES (?,0,1,?,?) ON CONFLICT (fecha) DO NOTHING""", (fecha, ahora_iso(), quien[:80]))
    return _dia(conn, fecha)["id"]


def _marcar(conn, dia_id):
    conn.execute("UPDATE corp_asig_dias SET modificado=1 WHERE id=?", (dia_id,))


def _filas(conn, dia_id):
    if not dia_id:
        return []
    return [dict(r) for r in conn.execute("SELECT * FROM corp_asig WHERE dia_id=? ORDER BY id", (dia_id,)).fetchall()]


def _horarios(conn, dia_id):
    """{(cliente, tramo): {"hora", "hora_fin"}} de los tramos con el horario
    cambiado ese día."""
    if not dia_id:
        return {}
    try:
        rows = conn.execute("SELECT cliente, tramo, hora, hora_fin FROM corp_asig_horarios WHERE dia_id=?",
                            (dia_id,)).fetchall()
    except Exception:
        _rollback(conn)
        return {}
    return {(r["cliente"], r["tramo"]): {"hora": r["hora"] or "", "hora_fin": r["hora_fin"] or ""}
            for r in rows if r["hora"]}


def choferes():
    return [{"usuario": c["usuario"], "nombre": c["nombre"]} for c in C.choferes_corp_registrados()]


def _nombre_dia(fecha):
    d = date.fromisoformat(fecha)
    return f"{DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]}"


def armar_dia(fecha, con_control=True):
    conn = get_connection()
    try:
        dia = _dia(conn, fecha)
        filas = _filas(conn, dia["id"] if dia else None)
        horarios = _horarios(conn, dia["id"] if dia else None)
        act = _actividad(conn, fecha)
        rends = _rendiciones(conn, fecha) if con_control and fecha <= _hoy() else None
    finally:
        conn.close()
    return _armar(fecha, dia, filas, act, rends, horarios)


def _armar(fecha, dia, filas, act, rends, horarios=None):
    """El día armado a partir de lo leído (sin tocar la base)."""
    act, con_hist = act
    horarios = horarios or {}
    w = date.fromisoformat(fecha).weekday()
    por_tramo = {}
    for f in filas:
        por_tramo.setdefault((f["cliente"], f["tramo"]), []).append(f)

    clientes, todos_slots = [], []
    for cliente in clientes_activos():
        opera = not (cliente in C.CLIENTES_SOLO_HABILES and w >= 5)
        tramos, otros = [], []
        fijos = C.tramos_fijos(cliente)
        for idx, t in sorted(enumerate(fijos), key=lambda x: _orden_tramo(x[1], x[0], horarios.get((cliente, x[1])))):
            mis = [f for f in por_tramo.get((cliente, t), []) if f["lado"] != "variable"]
            # Todos los tramos, todos los días: el que no se hace se quita a mano.
            # «esperado» solo avisa si suele correr ese día de la semana.
            esperado = corre(cliente, t, w, act, con_hist)
            h = horarios.get((cliente, t))
            tr = _armar_tramo(cliente, t, mis, esperado, h)
            tramos.append(tr)
            todos_slots += tr["slots"]
        variables = []
        for f in filas:
            if f["cliente"] == cliente and f["lado"] == "variable":
                s = _slot(f)
                s["tramo_corto"] = tramo_corto(f["tramo"])
                variables.append(s)
                todos_slots.append(s)
        variables.sort(key=lambda s: (s.get("hora") or "99", s["id"]))
        if not tramos and not variables and not opera:
            clientes.append({"cliente": cliente, "opera": False, "tramos": [], "variables": [],
                             "otros": otros, "tipos_variable": _tipos_variable(cliente), "cuenta": _cuenta([])})
            continue
        clientes.append({"cliente": cliente, "opera": opera, "tramos": tramos, "variables": variables,
                         "otros": otros, "tipos_variable": _tipos_variable(cliente),
                         "cuenta": _cuenta(tramos)})

    control = _control(fecha, clientes, rends) if rends is not None else None

    tramos = [t for c in clientes for t in c["tramos"]]
    con_chofer = [s for s in todos_slots if s.get("chofer_usuario")]
    resumen = {
        "tramos": len([t for t in tramos if t["estado"] != "no_corre"]),
        "listos": len([t for t in tramos if t["estado"] == "listo"]),
        "incompletos": len([t for t in tramos if t["estado"] == "incompleto"]),
        "sin_asignar": len([t for t in tramos if t["estado"] == "vacio"]),
        "no_corre": len([t for t in tramos if t["estado"] == "no_corre"]),
        "variables": sum(len(c["variables"]) for c in clientes),
        "choferes": len({s["chofer_usuario"] for s in con_chofer}),
        "coches": len({_coche_norm(s["coche"]) for s in todos_slots if s.get("coche")}),
    }
    borrador = bool(dia and (dia["modificado"] or not dia["version"]))
    return {
        "fecha": fecha, "hoy": _hoy(), "nombre_dia": _nombre_dia(fecha), "dia_semana": w,
        "existe": bool(dia), "dia": dia, "borrador": borrador if dia else True,
        "clientes": clientes, "resumen": resumen, "control": control,
    }


def _tipos_variable(cliente):
    return [t for t in C.CLIENTES_TRAMOS.get(cliente, []) if C._es_variable(t)] or [C.TRAMO_VARIABLE]


def _slot(f, h=None):
    return {"id": f["id"], "lado": f["lado"], "cliente": f["cliente"], "tramo": f["tramo"],
            "chofer_usuario": f.get("chofer_usuario") or "", "chofer_nombre": f.get("chofer_nombre") or "",
            "coche": f.get("coche") or "", "hora": f.get("hora") or "", "detalle": f.get("detalle") or "",
            "nota": f.get("nota") or "", "rango": rango(f, h)}


def _armar_tramo(cliente, tramo, filas, esperado, h=None):
    info = info_tramo(tramo, h)
    no_corre = next((f for f in filas if f["lado"] == "no_corre"), None)
    base = {"cliente": cliente, "tramo": tramo, **info, "esperado": esperado}
    if no_corre:
        return {**base, "modo": "no_corre", "estado": "no_corre", "nota": no_corre.get("nota") or "",
                "id_no_corre": no_corre["id"], "slots": [], "falta": []}
    por_lado = {f["lado"]: f for f in filas if f["lado"] in LADOS_TRAMO}
    if "entrante" in por_lado or "saliente" in por_lado:
        modo = "dividido"
        slots = []
        for lado in ("entrante", "saliente"):
            f = por_lado.get(lado) or {"id": None, "lado": lado, "cliente": cliente, "tramo": tramo}
            slots.append(_slot(f, h))
    else:
        f = por_lado.get("completo") or {"id": None, "lado": "completo", "cliente": cliente, "tramo": tramo}
        modo = "completo" if f.get("id") else "vacio"
        slots = [_slot(f, h)]
    falta = []
    for s in slots:
        if not s["chofer_usuario"]:
            falta.append(f"chofer{'' if s['lado'] == 'completo' else ' del ' + s['lado']}")
        if not s["coche"]:
            falta.append(f"coche{'' if s['lado'] == 'completo' else ' del ' + s['lado']}")
    if all(not s["chofer_usuario"] and not s["coche"] for s in slots):
        estado = "vacio"
    elif falta:
        estado = "incompleto"
    else:
        estado = "listo"
    return {**base, "modo": modo, "estado": estado, "slots": slots, "falta": falta}


def _cuenta(tramos):
    vivos = [t for t in tramos if t["estado"] != "no_corre"]
    return {"tramos": len(vivos), "listos": len([t for t in vivos if t["estado"] == "listo"]),
            "no_corre": len(tramos) - len(vivos)}


def _con_cliente(cliente, corto):
    """'ADM' + 'ADM RUTA 1' → 'ADM RUTA 1' (sin repetir el cliente)."""
    return corto if _norm(corto).startswith(_norm(cliente)) else f"{cliente} {corto}"


def _desc_slot(s):
    t = tramo_corto(s["tramo"]) if s["lado"] != "variable" else (s.get("detalle") or "variable")
    lado = "" if s["lado"] in ("completo", "variable") else f" ({s['lado']})"
    hora = info_tramo(s["tramo"])["hora"] if s["lado"] != "variable" else (s.get("hora") or "")
    return _con_cliente(s["cliente"], t) + (f" {hora}" if hora else "") + lado


# ════════════════════════════════════════════════════════════════════════════
# ASIGNADO CONTRA RENDIDO
# ════════════════════════════════════════════════════════════════════════════

def _rendiciones(conn, fecha, hasta=None):
    """Las rendiciones de un día (o de un rango, si viene hasta)."""
    out = []
    for r in conn.execute("""SELECT id, chofer_usuario, chofer_nombre, cliente, tramo, estado, bus_interno,
                                    hora_inicio, hora_fin, fecha_servicio
                             FROM rendiciones_corp WHERE fecha_servicio >= ? AND fecha_servicio <= ?""",
                          (fecha, hasta or fecha)).fetchall():
        r = dict(r)
        cli, tr = _canon(r["cliente"], r["tramo"])
        r["cliente_c"] = cli or r["cliente"]
        r["tramo_c"] = tr or r["tramo"]
        out.append(r)
    return out


CUBRE = {"completo": ("completado",), "entrante": ("entrante", "completado"),
         "saliente": ("saliente", "completado")}


def _control(fecha, clientes, rends):
    """Compara cada asignación con lo que se rindió ese día."""
    hoy = _hoy()
    pasado = fecha < hoy
    usadas = set()
    cuenta = {"ok": 0, "otro_coche": 0, "otro_chofer": 0, "parcial": 0, "suspendido": 0,
              "sin_rendir": 0, "pendiente": 0, "corrio": 0}
    por_tramo = {}
    for r in rends:
        por_tramo.setdefault((r["cliente_c"], r["tramo_c"]), []).append(r)

    def nom(r):
        return nombre_lindo(r.get("chofer_nombre") or r.get("chofer_usuario")) or "?"

    def poner(s, estado, txt, rend=None, corto=None):
        s["control"] = {"estado": estado, "txt": txt, "corto": corto or txt,
                        "rendicion_id": rend["id"] if rend else None}
        cuenta[estado] = cuenta.get(estado, 0) + 1

    for c in clientes:
        for t in c["tramos"]:
            rs = por_tramo.get((t["cliente"], t["tramo"]), [])
            asignados = {s["chofer_usuario"] for s in t["slots"] if s.get("chofer_usuario")}
            if t["estado"] == "no_corre":
                vivos = [r for r in rs if r["estado"] != "suspendido"]
                for r in rs:
                    usadas.add(r["id"])
                if vivos:
                    t["control"] = {"estado": "corrio", "txt": "Estaba como «no corre» pero lo rindió " +
                                    ", ".join(sorted({nom(r) for r in vivos}))}
                    cuenta["corrio"] += 1
                continue
            for s in t["slots"]:
                if not s.get("chofer_usuario"):
                    s["control"] = None
                    continue
                lado = s["lado"]
                mias = [r for r in rs if r["chofer_usuario"] == s["chofer_usuario"]]
                cubre = [r for r in mias if r["estado"] in CUBRE[lado]]
                if cubre:
                    r = cubre[0]
                    usadas.add(r["id"])
                    if s.get("coche") and _coche_norm(r["bus_interno"]) != _coche_norm(s["coche"]):
                        poner(s, "otro_coche", f"Rindió con el coche {r['bus_interno']} (estaba el {s['coche']})", r,
                              f"Fue con el {r['bus_interno']}")
                    else:
                        poner(s, "ok", "Rendido", r)
                    continue
                medias = [r for r in mias if r["estado"] in ("entrante", "saliente")]
                if lado == "completo" and medias:
                    for r in medias:
                        usadas.add(r["id"])
                    hechas = sorted({r["estado"] for r in medias})
                    falta = "saliente" if hechas == ["entrante"] else "entrante" if hechas == ["saliente"] else ""
                    otros = [r for r in rs if r["chofer_usuario"] != s["chofer_usuario"] and r["estado"] == falta]
                    txt = f"Rindió solo el {hechas[0]}" if len(hechas) == 1 else "Rindió entrante y saliente por separado"
                    if otros:
                        txt += f"; el {falta} lo rindió {nom(otros[0])}"
                        usadas.add(otros[0]["id"])
                    poner(s, "parcial" if len(hechas) == 1 else "ok", txt, medias[0],
                          f"Solo el {hechas[0]}" if len(hechas) == 1 else "Rendido en dos partes")
                    continue
                susp = [r for r in mias if r["estado"] == "suspendido"]
                if susp:
                    usadas.add(susp[0]["id"])
                    poner(s, "suspendido", "Lo rindió como suspendido", susp[0], "Suspendido")
                    continue
                otro = [r for r in rs if r["chofer_usuario"] not in asignados and r["estado"] in CUBRE[lado]]
                if otro:
                    usadas.add(otro[0]["id"])
                    poner(s, "otro_chofer", f"Lo rindió {nom(otro[0])}" +
                          (f" con el coche {otro[0]['bus_interno']}" if otro[0].get("bus_interno") else ""), otro[0],
                          f"Lo rindió {nom(otro[0])}")
                    continue
                if pasado:
                    poner(s, "sin_rendir", "No lo rindió")
                else:
                    poner(s, "pendiente", "Todavía no lo rindió", corto="Falta rendir")
        # Variables: se busca una rendición variable del mismo chofer y cliente
        for s in c["variables"]:
            if not s.get("chofer_usuario"):
                s["control"] = None
                continue
            rs = [r for r in rends if r["cliente_c"] == s["cliente"] and C._es_variable(r["tramo_c"])
                  and r["chofer_usuario"] == s["chofer_usuario"] and r["id"] not in usadas]
            if rs:
                r = rs[0]
                usadas.add(r["id"])
                if r["estado"] == "suspendido":
                    poner(s, "suspendido", "Lo rindió como suspendido", r, "Suspendido")
                elif s.get("coche") and _coche_norm(r["bus_interno"]) != _coche_norm(s["coche"]):
                    poner(s, "otro_coche", f"Rindió con el coche {r['bus_interno']} (estaba el {s['coche']})", r,
                          f"Fue con el {r['bus_interno']}")
                else:
                    poner(s, "ok", "Rendido", r)
            else:
                poner(s, "sin_rendir" if pasado else "pendiente", "No lo rindió" if pasado else "Todavía no lo rindió",
                      corto="No lo rindió" if pasado else "Falta rendir")

    # Lo que se rindió y no estaba asignado a ese chofer
    asig = {}
    for c in clientes:
        for t in c["tramos"]:
            asig[(t["cliente"], t["tramo"])] = t
    sueltas = []
    for r in rends:
        if r["id"] in usadas:
            continue
        t = asig.get((r["cliente_c"], r["tramo_c"]))
        en_lugar = ""
        if t and t["estado"] != "no_corre":
            otros = sorted({nombre_lindo(s["chofer_nombre"]) for s in t["slots"] if s.get("chofer_usuario")})
            if otros:
                en_lugar = "en lugar de " + " y ".join(otros)
            else:
                en_lugar = "el tramo estaba sin asignar"
        elif not t and not C._es_variable(r["tramo_c"]):
            en_lugar = "el tramo no estaba en la asignación"
        sueltas.append({"id": r["id"], "chofer": nom(r), "chofer_usuario": r["chofer_usuario"],
                        "cliente": r["cliente_c"], "tramo": r["tramo_c"], "tramo_corto": tramo_corto(r["tramo_c"]),
                        "estado": r["estado"], "coche": r.get("bus_interno") or "", "en_lugar": en_lugar})
    sueltas.sort(key=lambda x: (x["cliente"], x["tramo"], x["chofer"]))
    asignadas = sum(v for k, v in cuenta.items() if k != "corrio")
    return {"pasado": pasado, "hoy": fecha == hoy, "rendiciones": len(rends), "asignadas": asignadas,
            "cuenta": cuenta, "no_asignadas": sueltas,
            "diferencias": cuenta["otro_coche"] + cuenta["otro_chofer"] + cuenta["parcial"] + cuenta["sin_rendir"]
                           + cuenta["corrio"] + len(sueltas)}


# ════════════════════════════════════════════════════════════════════════════
# CAMBIOS (desde la pantalla)
# ════════════════════════════════════════════════════════════════════════════

class Error(Exception):
    pass


def _tramo_ok(cliente, tramo, variable=False):
    cli, tr = C._canonizar(cliente, tramo)
    if not cli:
        raise Error("Ese cliente no existe")
    if not tr:
        raise Error("Ese tramo no es de ese cliente")
    if variable != C._es_variable(tr):
        raise Error("Ese tramo no es un variable" if variable else "Los variables se agregan aparte")
    return cli, tr


def _chofer_ok(usuario):
    usuario = str(usuario or "").strip()
    if not usuario:
        return "", ""
    for c in choferes():
        if c["usuario"] == usuario:
            return c["usuario"], c["nombre"]
    raise Error("Ese chofer no está en la lista de corporativos")


def _coche_ok(coche):
    return re.sub(r"\s+", " ", str(coche or "")).strip().upper()[:20]


def _hora_ok(h):
    h = str(h or "").strip()
    if not h:
        return ""
    m = re.fullmatch(r"(\d{1,2})[:.]?(\d{2})", h)
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise Error("La hora no se entiende (ej: 06:30)")
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def _fecha_ok(f):
    try:
        return date.fromisoformat(str(f)[:10]).isoformat()
    except ValueError:
        raise Error("Fecha inválida")


def _vacia(f):
    return not (f.get("chofer_usuario") or f.get("coche"))


def _iguales(a, b):
    return (a.get("chofer_usuario") or "") == (b.get("chofer_usuario") or "") and \
        _coche_norm(a.get("coche")) == _coche_norm(b.get("coche"))


def _normalizar_tramo(conn, dia_id, cli, tr, quien=""):
    """La entrada y la salida se ven siempre por separado, pero si quedan con
    el mismo chofer y el mismo coche se guardan como un tramo completo (así
    las compara el control con lo rendido). Si las dos quedan vacías, no se
    guarda nada."""
    filas = [f for f in _filas(conn, dia_id) if f["cliente"] == cli and f["tramo"] == tr]
    ent = next((f for f in filas if f["lado"] == "entrante"), None)
    sal = next((f for f in filas if f["lado"] == "saliente"), None)
    if not ent and not sal:
        return
    ent, sal = ent or {"lado": "entrante"}, sal or {"lado": "saliente"}
    if _vacia(ent) and _vacia(sal):
        for f in (ent, sal):
            if f.get("id"):
                conn.execute("DELETE FROM corp_asig WHERE id=?", (f["id"],))
        return
    if _iguales(ent, sal):
        base = ent if ent.get("id") else sal
        conn.execute("UPDATE corp_asig SET lado='completo', nota=? WHERE id=?",
                     ((ent.get("nota") or sal.get("nota") or ""), base["id"]))
        otra = sal if base is ent else ent
        if otra.get("id"):
            conn.execute("DELETE FROM corp_asig WHERE id=?", (otra["id"],))


def guardar_slot(fecha, d, quien=""):
    """Chofer, coche o nota de la entrada o la salida de un tramo (o del tramo
    completo, como mandaban las pantallas de antes).

    La primera vez que se elige algo en una mitad, la otra (si está vacía)
    queda igual: casi siempre el mismo chofer hace las dos. Si la otra la hace
    otro, se cambia solo esa."""
    cli, tr = _tramo_ok(d.get("cliente"), d.get("tramo"))
    lado = d.get("lado") or "completo"
    if lado not in LADOS_TRAMO:
        raise Error("Lado inválido")
    conn = get_connection()
    try:
        dia_id = _crear_dia(conn, fecha, quien)
        filas = [f for f in _filas(conn, dia_id) if f["cliente"] == cli and f["tramo"] == tr]
        if any(f["lado"] == "no_corre" for f in filas):
            for f in filas:
                if f["lado"] == "no_corre":
                    conn.execute("DELETE FROM corp_asig WHERE id=?", (f["id"],))
            filas = [f for f in filas if f["lado"] != "no_corre"]
        divid = any(f["lado"] in ("entrante", "saliente") for f in filas)
        if lado == "completo" and divid:
            raise Error("Ese tramo tiene la entrada y la salida separadas: elegí cuál")
        ahora = ahora_iso()
        if lado != "completo" and not divid:
            # Se separa: las dos mitades arrancan con lo que tenía el tramo completo
            comp = next((f for f in filas if f["lado"] == "completo"), None)
            if comp:
                conn.execute("UPDATE corp_asig SET lado='entrante' WHERE id=?", (comp["id"],))
                comp["lado"] = "entrante"
            base = comp or {}
            nuevas = ["saliente"] if comp else ["entrante", "saliente"]
            for ld in nuevas:
                cur = conn.execute("""INSERT INTO corp_asig (dia_id, cliente, tramo, lado, chofer_usuario, chofer_nombre,
                                                             coche, nota, actualizado_el, actualizado_por)
                                      VALUES (?,?,?,?,?,?,?,?,?,?)""",
                                   (dia_id, cli, tr, ld, base.get("chofer_usuario") or "", base.get("chofer_nombre") or "",
                                    base.get("coche") or "", base.get("nota") or "", ahora, quien[:80]))
                filas.append({**base, "id": cur.lastrowid, "lado": ld,
                              "chofer_usuario": base.get("chofer_usuario") or "", "coche": base.get("coche") or ""})
        f = next((x for x in filas if x["lado"] == lado), None)
        cambios = {}
        if "chofer_usuario" in d:
            cambios["chofer_usuario"], cambios["chofer_nombre"] = _chofer_ok(d.get("chofer_usuario"))
        if "coche" in d:
            cambios["coche"] = _coche_ok(d.get("coche"))
        if "nota" in d:
            cambios["nota"] = str(d.get("nota") or "").strip()[:120]
        sello = {"actualizado_el": ahora, "actualizado_por": quien[:80]}
        if f:
            todo = {**cambios, **sello}
            conn.execute(f"UPDATE corp_asig SET {', '.join(k + '=?' for k in todo)} WHERE id=?",
                         tuple(todo.values()) + (f["id"],))
            fid = f["id"]
        else:
            todo = {**cambios, **sello}
            cols = ["dia_id", "cliente", "tramo", "lado"] + list(todo)
            cur = conn.execute(f"INSERT INTO corp_asig ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                               (dia_id, cli, tr, lado) + tuple(todo.values()))
            fid = cur.lastrowid
        if lado != "completo":
            # Lo que todavía falta en la otra mitad se completa con esto: el
            # chofer, si allá no hay chofer (y el coche es el mismo o no hay);
            # el coche, si allá no hay coche y lo hace el mismo chofer. Lo que
            # la otra mitad ya tiene distinto no se toca.
            otra = next((x for x in filas if x["lado"] == ("saliente" if lado == "entrante" else "entrante")), None)
            esta = {**(f or {}), **cambios}
            copia = {}
            if otra and otra.get("id"):
                if cambios.get("chofer_usuario") and not otra.get("chofer_usuario") and \
                        (not otra.get("coche") or _coche_norm(otra.get("coche")) == _coche_norm(esta.get("coche"))):
                    copia["chofer_usuario"], copia["chofer_nombre"] = cambios["chofer_usuario"], cambios["chofer_nombre"]
                chofer_otra = copia.get("chofer_usuario", otra.get("chofer_usuario")) or ""
                if cambios.get("coche") and not otra.get("coche") and chofer_otra == (esta.get("chofer_usuario") or ""):
                    copia["coche"] = cambios["coche"]
            if copia:
                conn.execute(f"UPDATE corp_asig SET {', '.join(k + '=?' for k in copia)} WHERE id=?",
                             tuple(copia.values()) + (otra["id"],))
            _normalizar_tramo(conn, dia_id, cli, tr, quien)
        # Un completo que quedó vacío no hace falta guardarlo
        if lado == "completo" and fid:
            r = conn.execute("SELECT * FROM corp_asig WHERE id=?", (fid,)).fetchone()
            if r and not (r["chofer_usuario"] or r["coche"] or r["nota"]):
                conn.execute("DELETE FROM corp_asig WHERE id=?", (fid,))
        _marcar(conn, dia_id)
        conn.commit()
    finally:
        conn.close()


def poner_horario(fecha, d, quien=""):
    """Cambia el horario de un tramo SOLO para ese día (o lo vuelve al de
    siempre con normal=True, o poniendo el mismo horario de siempre)."""
    cli, tr = _tramo_ok(d.get("cliente"), d.get("tramo"))
    normal = info_tramo(tr)
    if d.get("normal"):
        hora = fin = ""
    else:
        hora, fin = _hora_ok(d.get("hora")), _hora_ok(d.get("hora_fin"))
        if not hora:
            raise Error("Poné al menos la hora de salida (ej: 06:30)")
        if fin and fin == hora:
            raise Error("La hora de fin no puede ser igual a la de salida")
        if hora == normal["hora"] and fin == normal["hora_fin"]:
            hora = fin = ""           # es el de siempre: no queda como cambio
    conn = get_connection()
    try:
        dia_id = _crear_dia(conn, fecha, quien)
        antes = _horarios(conn, dia_id).get((cli, tr))
        conn.execute("DELETE FROM corp_asig_horarios WHERE dia_id=? AND cliente=? AND tramo=?", (dia_id, cli, tr))
        if hora:
            conn.execute("""INSERT INTO corp_asig_horarios (dia_id, cliente, tramo, hora, hora_fin, cambiado_el, cambiado_por)
                            VALUES (?,?,?,?,?,?,?)""", (dia_id, cli, tr, hora, fin, ahora_iso(), quien[:80]))
        _marcar(conn, dia_id)
        conn.commit()
    finally:
        conn.close()
    era = _txt_horario(antes["hora"], antes["hora_fin"]) if antes else _txt_horario(normal["hora"], normal["hora_fin"])
    queda = _txt_horario(hora, fin) if hora else _txt_horario(normal["hora"], normal["hora_fin"])
    return {"cliente": cli, "tramo": tr, "corto": _con_cliente(cli, tramo_corto(tr)),
            "era": era, "queda": queda, "de_siempre": not hora}


def dividir(fecha, d, quien="", unir=False):
    cli, tr = _tramo_ok(d.get("cliente"), d.get("tramo"))
    conn = get_connection()
    try:
        dia_id = _crear_dia(conn, fecha, quien)
        filas = [f for f in _filas(conn, dia_id) if f["cliente"] == cli and f["tramo"] == tr and f["lado"] in LADOS_TRAMO]
        ahora = ahora_iso()
        if unir:
            ent = next((f for f in filas if f["lado"] == "entrante"), None)
            sal = next((f for f in filas if f["lado"] == "saliente"), None)
            base = ent if ent and (ent["chofer_usuario"] or ent["coche"]) else sal
            for f in filas:
                conn.execute("DELETE FROM corp_asig WHERE id=?", (f["id"],))
            if base and (base["chofer_usuario"] or base["coche"]):
                conn.execute("""INSERT INTO corp_asig (dia_id, cliente, tramo, lado, chofer_usuario, chofer_nombre, coche,
                                                       nota, actualizado_el, actualizado_por)
                                VALUES (?,?,?,'completo',?,?,?,?,?,?)""",
                             (dia_id, cli, tr, base["chofer_usuario"], base["chofer_nombre"], base["coche"],
                              base["nota"], ahora, quien[:80]))
        else:
            comp = next((f for f in filas if f["lado"] == "completo"), None)
            if comp:
                conn.execute("UPDATE corp_asig SET lado='entrante' WHERE id=?", (comp["id"],))
            elif not any(f["lado"] == "entrante" for f in filas):
                conn.execute("""INSERT INTO corp_asig (dia_id, cliente, tramo, lado, actualizado_el, actualizado_por)
                                VALUES (?,?,?,'entrante',?,?)""", (dia_id, cli, tr, ahora, quien[:80]))
            if not any(f["lado"] == "saliente" for f in filas):
                conn.execute("""INSERT INTO corp_asig (dia_id, cliente, tramo, lado, actualizado_el, actualizado_por)
                                VALUES (?,?,?,'saliente',?,?)""", (dia_id, cli, tr, ahora, quien[:80]))
        _marcar(conn, dia_id)
        conn.commit()
    finally:
        conn.close()


def no_corre(fecha, d, quien=""):
    """Marca (o desmarca) que el tramo no corre ese día."""
    cli, tr = _tramo_ok(d.get("cliente"), d.get("tramo"))
    marcar = bool(d.get("no_corre", True))
    conn = get_connection()
    try:
        dia_id = _crear_dia(conn, fecha, quien)
        filas = [f for f in _filas(conn, dia_id) if f["cliente"] == cli and f["tramo"] == tr and f["lado"] != "variable"]
        for f in filas:
            conn.execute("DELETE FROM corp_asig WHERE id=?", (f["id"],))
        if marcar:
            conn.execute("""INSERT INTO corp_asig (dia_id, cliente, tramo, lado, nota, actualizado_el, actualizado_por)
                            VALUES (?,?,?,'no_corre',?,?,?)""",
                         (dia_id, cli, tr, str(d.get("nota") or "").strip()[:120], ahora_iso(), quien[:80]))
        _marcar(conn, dia_id)
        conn.commit()
    finally:
        conn.close()


def quitar_varios(fecha, d, quien=""):
    """Quita de una vez los tramos de un cliente que no tienen nada asignado
    (los que no suelen correr ese día). Los que tienen chofer o coche no se tocan."""
    cli = d.get("cliente")
    tramos = d.get("tramos") or []
    if not isinstance(tramos, list) or not tramos:
        raise Error("No hay tramos para quitar")
    conn = get_connection()
    try:
        dia_id = _crear_dia(conn, fecha, quien)
        ya = {(f["cliente"], f["tramo"]) for f in _filas(conn, dia_id) if f["lado"] != "variable"}
        n = 0
        for t in tramos[:200]:
            c2, t2 = _tramo_ok(cli, t)
            if (c2, t2) in ya:
                continue
            conn.execute("""INSERT INTO corp_asig (dia_id, cliente, tramo, lado, nota, actualizado_el, actualizado_por)
                            VALUES (?,?,?,'no_corre','',?,?)""", (dia_id, c2, t2, ahora_iso(), quien[:80]))
            n += 1
        _marcar(conn, dia_id)
        conn.commit()
        return n
    finally:
        conn.close()


def agregar_tramo(fecha, d, quien=""):
    """Un tramo que no suele correr ese día pero hoy sí: se agrega vacío
    (queda como completo sin chofer hasta que se asigne)."""
    cli, tr = _tramo_ok(d.get("cliente"), d.get("tramo"))
    conn = get_connection()
    try:
        dia_id = _crear_dia(conn, fecha, quien)
        filas = [f for f in _filas(conn, dia_id) if f["cliente"] == cli and f["tramo"] == tr and f["lado"] != "variable"]
        if not filas:
            conn.execute("""INSERT INTO corp_asig (dia_id, cliente, tramo, lado, nota, actualizado_el, actualizado_por)
                            VALUES (?,?,?,'completo','',?,?)""", (dia_id, cli, tr, ahora_iso(), quien[:80]))
        _marcar(conn, dia_id)
        conn.commit()
    finally:
        conn.close()


def guardar_variable(fecha, d, quien="", fid=None):
    conn = get_connection()
    try:
        if fid:
            f = conn.execute("SELECT * FROM corp_asig WHERE id=? AND lado='variable'", (fid,)).fetchone()
            if not f:
                raise Error("Ese variable ya no existe")
            dia_id = f["dia_id"]
            cambios = {}
            if "tramo" in d:
                cambios["tramo"] = _tramo_ok(f["cliente"], d.get("tramo"), variable=True)[1]
            if "hora" in d:
                cambios["hora"] = _hora_ok(d.get("hora"))
            if "detalle" in d:
                cambios["detalle"] = str(d.get("detalle") or "").strip()[:80]
            if "chofer_usuario" in d:
                cambios["chofer_usuario"], cambios["chofer_nombre"] = _chofer_ok(d.get("chofer_usuario"))
            if "coche" in d:
                cambios["coche"] = _coche_ok(d.get("coche"))
            if cambios:
                cambios["actualizado_el"], cambios["actualizado_por"] = ahora_iso(), quien[:80]
                conn.execute(f"UPDATE corp_asig SET {', '.join(k + '=?' for k in cambios)} WHERE id=?",
                             tuple(cambios.values()) + (fid,))
        else:
            cli, tr = _tramo_ok(d.get("cliente"), d.get("tramo") or C.TRAMO_VARIABLE, variable=True)
            dia_id = _crear_dia(conn, fecha, quien)
            usuario, nombre = _chofer_ok(d.get("chofer_usuario"))
            cur = conn.execute("""INSERT INTO corp_asig (dia_id, cliente, tramo, lado, chofer_usuario, chofer_nombre,
                                                         coche, hora, detalle, actualizado_el, actualizado_por)
                                  VALUES (?,?,?,'variable',?,?,?,?,?,?,?)""",
                               (dia_id, cli, tr, usuario, nombre, _coche_ok(d.get("coche")), _hora_ok(d.get("hora")),
                                str(d.get("detalle") or "").strip()[:80], ahora_iso(), quien[:80]))
            fid = cur.lastrowid
        _marcar(conn, dia_id)
        conn.commit()
        return fid
    finally:
        conn.close()


def borrar_fila(fid):
    conn = get_connection()
    try:
        f = conn.execute("SELECT * FROM corp_asig WHERE id=?", (fid,)).fetchone()
        if not f:
            return
        conn.execute("DELETE FROM corp_asig WHERE id=?", (fid,))
        _marcar(conn, f["dia_id"])
        conn.commit()
    finally:
        conn.close()


def copiar(fecha, desde, quien="", reemplazar=False, con_variables=False):
    """Trae la asignación de otro día tal cual, también los tramos quitados
    (copiar el sábado pasado trae los quitados del sábado)."""
    if desde == fecha:
        raise Error("Elegí otro día para copiar")
    conn = get_connection()
    try:
        origen = _dia(conn, desde)
        filas = _filas(conn, origen["id"] if origen else None)
        if not filas:
            raise Error(f"El {_nombre_dia(desde)} no tiene asignación para copiar")
        dia_id = _crear_dia(conn, fecha, quien)
        ya = _filas(conn, dia_id)
        if ya and not reemplazar:
            return {"necesita_confirmar": True, "ya_tiene": len(ya)}
        for f in ya:
            conn.execute("DELETE FROM corp_asig WHERE id=?", (f["id"],))
        copiadas, salteadas = 0, set()
        ahora = ahora_iso()
        for f in filas:
            if f["lado"] == "variable" and not con_variables:
                continue
            conn.execute("""INSERT INTO corp_asig (dia_id, cliente, tramo, lado, chofer_usuario, chofer_nombre, coche,
                                                   hora, detalle, nota, actualizado_el, actualizado_por)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                         (dia_id, f["cliente"], f["tramo"], f["lado"], f["chofer_usuario"], f["chofer_nombre"],
                          f["coche"], f["hora"], f["detalle"], f["nota"],
                          ahora, quien[:80]))
            copiadas += 1
        # Los choferes que ya no están en la lista no se copian
        activos = {c["usuario"] for c in choferes()}
        for f in _filas(conn, dia_id):
            if f["chofer_usuario"] and f["chofer_usuario"] not in activos:
                conn.execute("UPDATE corp_asig SET chofer_usuario='', chofer_nombre='' WHERE id=?", (f["id"],))
        _marcar(conn, dia_id)
        conn.commit()
        return {"copiadas": copiadas, "salteadas": len(salteadas),
                "salteadas_lista": [f"{_con_cliente(c, tramo_corto(t))} {info_tramo(t)['hora']}".strip()
                                    for c, t in sorted(salteadas, key=lambda x: (x[0], _orden_tramo(x[1], 0)))]}
    finally:
        conn.close()


def vaciar(fecha):
    conn = get_connection()
    try:
        d = _dia(conn, fecha)
        if not d:
            return 0
        n = conn.execute("SELECT COUNT(*) AS n FROM corp_asig WHERE dia_id=?", (d["id"],)).fetchone()["n"]
        conn.execute("DELETE FROM corp_asig WHERE dia_id=?", (d["id"],))
        try:
            conn.execute("DELETE FROM corp_asig_horarios WHERE dia_id=?", (d["id"],))
        except Exception:
            pass
        if not d["version"]:
            conn.execute("DELETE FROM corp_asig_dias WHERE id=?", (d["id"],))
        else:
            _marcar(conn, d["id"])
        conn.commit()
        return n
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════════════
# PUBLICAR: versiones y cambios
# ════════════════════════════════════════════════════════════════════════════

def _clave(s):
    if s["lado"] == "variable":
        return f"var|{s['id']}"
    return f"{s['cliente']}|{s['tramo']}|{s['lado']}"


def foto(d):
    filas = []
    for c in d["clientes"]:
        for t in c["tramos"]:
            if t["estado"] == "no_corre":
                filas.append({"k": f"{t['cliente']}|{t['tramo']}|no_corre", "cliente": t["cliente"], "tramo": t["tramo"],
                              "lado": "no_corre", "nota": t.get("nota") or ""})
                continue
            for s in t["slots"]:
                if s.get("id"):
                    filas.append({"k": _clave(s), **{k: s.get(k, "") for k in (
                        "cliente", "tramo", "lado", "chofer_usuario", "chofer_nombre", "coche", "nota")}})
        for s in c["variables"]:
            filas.append({"k": _clave(s), **{k: s.get(k, "") for k in (
                "cliente", "tramo", "lado", "chofer_usuario", "chofer_nombre", "coche", "hora", "detalle", "nota")}})
    horarios = {f"{t['cliente']}|{t['tramo']}": {"hora": t["hora"], "hora_fin": t["hora_fin"]}
                for c in d["clientes"] for t in c["tramos"] if t.get("horario_cambiado")}
    return {"fecha": d["fecha"], "filas": filas, "horarios": horarios}


NOMBRE_MITAD = {"entrante": "entrada", "saliente": "salida"}


def _desc_k(f, con_lado=True, horarios=None):
    if f["lado"] == "variable":
        return f"{f['cliente']} variable {f.get('hora') or ''} {f.get('detalle') or ''}".replace("  ", " ").strip()
    i = info_tramo(f["tramo"], (horarios or {}).get(f"{f['cliente']}|{f['tramo']}"))
    hora = (i["hora_fin"] or i["hora"]) if f["lado"] == "saliente" and con_lado else i["hora"]
    lado = f" ({NOMBRE_MITAD[f['lado']]})" if con_lado and f["lado"] in NOMBRE_MITAD else ""
    return f"{_con_cliente(f['cliente'], tramo_corto(f['tramo']))}{(' ' + hora) if hora else ''}{lado}"


def _por_mitad(filas):
    """Un tramo completo cuenta como su entrada y su salida con lo mismo: así
    separar una mitad no aparece como 'se quitó el tramo y se agregaron dos'."""
    out = {}
    for f in filas:
        if f["lado"] == "completo":
            for ld in ("entrante", "saliente"):
                g = {**f, "lado": ld, "k": f"{f['cliente']}|{f['tramo']}|{ld}"}
                out[g["k"]] = g
        else:
            out[f["k"]] = f
    return out


def _partes(v, f):
    partes = []
    if v.get("chofer_usuario") != f.get("chofer_usuario"):
        if not f.get("chofer_usuario"):
            partes.append(f"sale {nombre_lindo(v['chofer_nombre'])}, queda sin chofer")
        elif not v.get("chofer_usuario"):
            partes.append(f"va {nombre_lindo(f['chofer_nombre'])}")
        else:
            partes.append(f"chofer {nombre_lindo(v['chofer_nombre'])} → {nombre_lindo(f['chofer_nombre'])}")
    if _coche_norm(v.get("coche")) != _coche_norm(f.get("coche")):
        if not f.get("coche"):
            partes.append(f"se sacó el coche {v['coche']}")
        elif not v.get("coche"):
            partes.append(f"va el coche {f['coche']}")
        else:
            partes.append(f"coche {v['coche']} → {f['coche']}")
    if f["lado"] == "variable" and (v.get("hora") != f.get("hora") or v.get("detalle") != f.get("detalle")):
        partes.append("cambió el horario o el detalle")
    return partes


def _cambios_de_horario(antes, ahora):
    """Los tramos a los que se les cambió (o se les devolvió) el horario del día."""
    ha, hn = antes.get("horarios") or {}, ahora.get("horarios") or {}
    out = []
    for k in sorted(set(ha) | set(hn)):
        a, n = ha.get(k), hn.get(k)
        if (a or {}) == (n or {}):
            continue
        cliente, tramo = k.split("|", 1)
        normal = info_tramo(tramo)
        txt_a = _txt_horario(a["hora"], a["hora_fin"]) if a else _txt_horario(normal["hora"], normal["hora_fin"])
        nombre = _con_cliente(cliente, tramo_corto(tramo))
        if n:
            txt = f"{nombre}: cambia el horario, {txt_a} → {_txt_horario(n['hora'], n['hora_fin'])}"
        else:
            txt = f"{nombre}: vuelve al horario de siempre ({_txt_horario(normal['hora'], normal['hora_fin'])})"
        out.append({"k": k, "cliente": cliente, "txt": txt})
    return out


def comparar(antes, ahora):
    if not antes:
        return []
    hn = ahora.get("horarios") or {}
    ha = antes.get("horarios") or {}
    va = _por_mitad(antes["filas"])
    vn = _por_mitad(ahora["filas"])
    tramo_k = lambda f: f"{f['cliente']}|{f['tramo']}" if f["lado"] != "variable" else f["k"]
    vacio = {"chofer_usuario": "", "chofer_nombre": "", "coche": ""}
    # Lo que cambió en cada mitad (o en cada variable)
    por_k = {}
    for k in list(vn) + [k for k in va if k not in vn]:
        f, v = vn.get(k), va.get(k)
        ref = f or v
        if ref["lado"] == "no_corre":
            if f and not v:
                por_k[k] = ("no_corre", f)
            elif v and not f:
                por_k[k] = ("vuelve", v)
            continue
        if ref["lado"] == "variable":
            if f and not v:
                por_k[k] = ("nuevo_var", f)
            elif v and not f:
                por_k[k] = ("quitado_var", v)
            else:
                p = _partes(v, f)
                if p:
                    por_k[k] = ("cambio", f, p)
            continue
        p = _partes(v or {**vacio, "lado": ref["lado"]}, f or {**vacio, "lado": ref["lado"]})
        if p:
            por_k[k] = ("cambio", ref, p)
    cambios, hechos = [], set()
    for k, x in por_k.items():
        if k in hechos:
            continue
        hechos.add(k)
        f = x[1]
        base = {"k": tramo_k(f), "cliente": f["cliente"]}
        if x[0] == "no_corre":
            cambios.append({**base, "txt": f"{_desc_k(f, False, hn if f in vn.values() else ha)}: no corre" + (f" ({f['nota']})" if f.get("nota") else "")})
        elif x[0] == "vuelve":
            cambios.append({**base, "txt": f"{_desc_k(f, False, hn if f in vn.values() else ha)}: vuelve a correr"})
        elif x[0] == "nuevo_var":
            partes = []
            if f.get("chofer_nombre"):
                partes.append(f"va {nombre_lindo(f['chofer_nombre'])}")
            if f.get("coche"):
                partes.append(f"con el {f['coche']}")
            cambios.append({**base, "txt": f"{_desc_k(f, horarios=hn if f in vn.values() else ha)}: " + (" ".join(partes) or "se agregó")})
        elif x[0] == "quitado_var":
            cambios.append({**base, "txt": f"Se quitó el {_desc_k(f, horarios=hn if f in vn.values() else ha)}"})
        else:
            partes = x[2]
            # Si la entrada y la salida cambiaron igual, va en un solo renglón
            if f["lado"] in NOMBRE_MITAD:
                otra = f"{f['cliente']}|{f['tramo']}|{'saliente' if f['lado'] == 'entrante' else 'entrante'}"
                y = por_k.get(otra)
                if y and y[0] == "cambio" and y[2] == partes:
                    hechos.add(otra)
                    cambios.append({**base, "txt": f"{_desc_k(f, False, hn if f in vn.values() else ha)}: " + "; ".join(partes)})
                    continue
            cambios.append({**base, "txt": f"{_desc_k(f, horarios=hn if f in vn.values() else ha)}: " + "; ".join(partes)})
    return _cambios_de_horario(antes, ahora) + cambios


def publicar(fecha, quien=""):
    d = armar_dia(fecha, con_control=False)
    if not d["existe"]:
        return None, "Todavía no hay nada asignado ese día"
    conn = get_connection()
    try:
        dia = d["dia"]
        ultima = conn.execute("SELECT * FROM corp_asig_versiones WHERE dia_id=? ORDER BY version DESC LIMIT 1",
                              (dia["id"],)).fetchone()
        f = foto(d)
        cambios = comparar(json.loads(ultima["datos"]) if ultima else None, f)
        if ultima and not cambios and not dia["modificado"]:
            return {"version": dia["version"], "cambios": [], "sin_cambios": True}, None
        version = (dia["version"] or 0) + 1
        cuando = ahora_iso()
        conn.execute("""INSERT INTO corp_asig_versiones (dia_id, version, publicado_el, publicado_por, datos, cambios)
                        VALUES (?,?,?,?,?,?)""",
                     (dia["id"], version, cuando, quien[:80], json.dumps(f, ensure_ascii=False),
                      json.dumps(cambios, ensure_ascii=False)))
        conn.execute("UPDATE corp_asig_dias SET version=?, publicado_el=?, publicado_por=?, modificado=0 WHERE id=?",
                     (version, cuando, quien[:80], dia["id"]))
        conn.commit()
        return {"version": version, "cambios": cambios, "publicado_el": cuando}, None
    finally:
        conn.close()


def versiones(fecha):
    conn = get_connection()
    try:
        d = _dia(conn, fecha)
        if not d:
            return []
        return [{**dict(r), "cambios": json.loads(r["cambios"] or "[]")} for r in conn.execute(
            """SELECT version, publicado_el, publicado_por, cambios FROM corp_asig_versiones
               WHERE dia_id=? ORDER BY version DESC""", (d["id"],)).fetchall()]
    finally:
        conn.close()


def _dia_desde_foto(foto_d, fecha):
    """Una versión publicada como si fuera el día armado (para su PDF)."""
    w = date.fromisoformat(fecha).weekday()
    por_cli = {}
    for f in foto_d["filas"]:
        por_cli.setdefault(f["cliente"], []).append(f)
    hs = foto_d.get("horarios") or {}
    clientes = []
    for cliente in clientes_activos():
        filas = por_cli.get(cliente, [])
        tramos = []
        por_tramo = {}
        for f in filas:
            if f["lado"] != "variable":
                por_tramo.setdefault(f["tramo"], []).append({**f, "id": f["k"]})
        fijos = C.tramos_fijos(cliente)
        orden = {t: _orden_tramo(t, i, hs.get(f"{cliente}|{t}")) for i, t in enumerate(fijos)}
        for t in sorted(por_tramo, key=lambda x: orden.get(x, (99, 999))):
            tramos.append(_armar_tramo(cliente, t, por_tramo[t], True, hs.get(f"{cliente}|{t}")))
        variables = [{**_slot({**f, "id": f["k"]}), "tramo_corto": tramo_corto(f["tramo"])}
                     for f in filas if f["lado"] == "variable"]
        clientes.append({"cliente": cliente, "opera": not (cliente in C.CLIENTES_SOLO_HABILES and w >= 5),
                         "tramos": tramos, "variables": variables, "otros": [], "cuenta": _cuenta(tramos)})
    return clientes


def datos_para_pdf(fecha, version=None, cliente=None):
    """Lo que va en la hoja. Con cliente, solo esa empresa (y sus cambios)."""
    d = armar_dia(fecha, con_control=False)
    if not d["existe"]:
        return None
    dia = d["dia"]
    info = {"fecha": fecha, "nombre_dia": d["nombre_dia"].upper(), "version": dia["version"],
            "borrador": d["borrador"], "publicado_el": dia["publicado_el"], "publicado_por": dia["publicado_por"],
            "cambios": [], "clientes": d["clientes"], "resumen": d["resumen"]}
    conn = get_connection()
    try:
        if version:
            v = conn.execute("SELECT * FROM corp_asig_versiones WHERE dia_id=? AND version=?",
                             (dia["id"], int(version))).fetchone()
            if v:
                info["clientes"] = _dia_desde_foto(json.loads(v["datos"]), fecha)
                # Si suele correr ese día sale del historial (la versión no lo guarda)
                esp = {(t["cliente"], t["tramo"]): t.get("esperado", True) for c in d["clientes"] for t in c["tramos"]}
                for c in info["clientes"]:
                    for t in c["tramos"]:
                        t["esperado"] = esp.get((t["cliente"], t["tramo"]), True)
                info.update(version=v["version"], borrador=False, publicado_el=v["publicado_el"],
                            publicado_por=v["publicado_por"], cambios=json.loads(v["cambios"] or "[]"))
                info["resumen"] = _resumen_de(info["clientes"])
        elif not info["borrador"]:
            v = conn.execute("SELECT cambios FROM corp_asig_versiones WHERE dia_id=? AND version=?",
                             (dia["id"], dia["version"])).fetchone()
            if v:
                info["cambios"] = json.loads(v["cambios"] or "[]")
        elif dia["version"]:
            v = conn.execute("SELECT datos FROM corp_asig_versiones WHERE dia_id=? AND version=?",
                             (dia["id"], dia["version"])).fetchone()
            if v:
                info["cambios"] = comparar(json.loads(v["datos"]), foto(d))
    finally:
        conn.close()
    if cliente:
        cli = next((c for c in info["clientes"] if _norm(c["cliente"]) == _norm(cliente)), None)
        if not cli:
            return None
        info["clientes"] = [cli]
        info["cliente"] = cli["cliente"]
        # Los cambios de esa empresa (los de versiones viejas no traen la
        # empresa: se reconocen porque el texto empieza con su nombre)
        info["cambios"] = [c for c in info["cambios"]
                           if (c.get("cliente") == cli["cliente"]) or
                           (not c.get("cliente") and _norm(c.get("txt")).startswith(_norm(cli["cliente"])))]
        info["resumen"] = _resumen_de(info["clientes"])
    info["cambiadas"] = {c["k"] for c in info["cambios"]}
    return info


def _resumen_de(clientes):
    tramos = [t for c in clientes for t in c["tramos"]]
    slots = [s for t in tramos for s in t["slots"]] + [s for c in clientes for s in c["variables"]]
    return {"tramos": len([t for t in tramos if t["estado"] != "no_corre"]),
            "listos": len([t for t in tramos if t["estado"] == "listo"]),
            "sin_asignar": len([t for t in tramos if t["estado"] == "vacio"]),
            "incompletos": len([t for t in tramos if t["estado"] == "incompleto"]),
            "variables": sum(len(c["variables"]) for c in clientes),
            "choferes": len({s["chofer_usuario"] for s in slots if s.get("chofer_usuario")}),
            "coches": len({_coche_norm(s["coche"]) for s in slots if s.get("coche")})}


# ════════════════════════════════════════════════════════════════════════════
# LA TIRA DE DÍAS (estado de cada día)
# ════════════════════════════════════════════════════════════════════════════

def tira(desde, hasta):
    out = []
    d0, d1 = date.fromisoformat(desde), date.fromisoformat(hasta)
    if (d1 - d0).days > 40:
        d1 = d0 + timedelta(days=40)
    hoy = _hoy()
    # Todo en pocas consultas (con la base lejos, cada una cuesta)
    conn = get_connection()
    try:
        dias = {r["fecha"]: dict(r) for r in conn.execute(
            "SELECT * FROM corp_asig_dias WHERE fecha >= ? AND fecha <= ?", (d0.isoformat(), d1.isoformat())).fetchall()}
        filas = {}
        if dias:
            ids = [x["id"] for x in dias.values()]
            for r in conn.execute(f"SELECT * FROM corp_asig WHERE dia_id IN ({','.join('?' * len(ids))}) ORDER BY id",
                                  tuple(ids)).fetchall():
                filas.setdefault(r["dia_id"], []).append(dict(r))
            act = _actividad(conn, d1.isoformat())
            ult = min(d1.isoformat(), hoy)
            rends = {}
            if d0.isoformat() <= ult:
                for r in _rendiciones(conn, d0.isoformat(), ult):
                    rends.setdefault(str(r["fecha_servicio"])[:10], []).append(r)
    finally:
        conn.close()
    d = d0
    while d <= d1:
        f = d.isoformat()
        x = dias.get(f)
        item = {"fecha": f, "existe": bool(x), "version": x["version"] if x else 0,
                "modificado": bool(x and x["modificado"]), "diferencias": None, "sin_asignar": None}
        if x:
            a = _armar(f, x, filas.get(x["id"], []), act, rends.get(f, []) if f <= hoy else None)
            item["sin_asignar"] = a["resumen"]["sin_asignar"] + a["resumen"]["incompletos"]
            if a["control"]:
                item["diferencias"] = a["control"]["diferencias"]
        out.append(item)
        d += timedelta(days=1)
    return out


# ════════════════════════════════════════════════════════════════════════════
# API
# ════════════════════════════════════════════════════════════════════════════

def _puede_ver():
    return session.get("rol") in ("admin", "taller", "auditor")


def _puede_editar():
    return session.get("rol") in ("admin", "taller")


def _quien():
    return session.get("nombre") or session.get("usuario") or ""


def _no():
    return jsonify({"ok": False, "msg": "No tenés permiso para esto"}), 403


def _auditar(accion, detalle=""):
    try:
        from database import registrar_auditoria
        registrar_auditoria(usuario=_quien() or "?", rol=session.get("rol") or "", accion=accion,
                            categoria="Corporativos", detalle=str(detalle)[:200], referencia="")
    except Exception:
        pass


def _respuesta(fecha, **extra):
    return jsonify({"ok": True, "dia": armar_dia(fecha), **extra})


def _cambio(fn):
    """Envoltorio de los endpoints que cambian algo: permiso, fecha y errores."""
    def envuelto(fecha, *a, **k):
        if not _puede_editar():
            return _no()
        try:
            fecha = _fecha_ok(fecha)
            return fn(fecha, *a, **k)
        except Error as e:
            return jsonify({"ok": False, "msg": str(e)}), 400
    envuelto.__name__ = fn.__name__
    return envuelto


@bp_corp_asig.route("/api/corp/asig/dia/<fecha>", methods=["GET"])
def api_dia(fecha):
    if not _puede_ver():
        return _no()
    try:
        fecha = _fecha_ok(fecha)
    except Error as e:
        return jsonify({"ok": False, "msg": str(e)}), 400
    return jsonify(armar_dia(fecha))


@bp_corp_asig.route("/api/corp/asig/dias", methods=["GET"])
def api_dias():
    if not _puede_ver():
        return _no()
    try:
        desde = _fecha_ok(request.args.get("desde"))
        hasta = _fecha_ok(request.args.get("hasta"))
    except Error as e:
        return jsonify({"ok": False, "msg": str(e)}), 400
    return jsonify(tira(desde, hasta))


@bp_corp_asig.route("/api/corp/asig/listas", methods=["GET"])
def api_listas():
    if not _puede_ver():
        return _no()
    conn = get_connection()
    try:
        coches = [{"n": str(r["n_interno"]).strip(), "patente": r["patente"] or "", "marca": r["marca"] or "",
                   "modelo": r["modelo"] or ""}
                  for r in conn.execute("""SELECT n_interno, patente, marca, modelo FROM vehiculos
                                           WHERE COALESCE(activo,1)=1 AND COALESCE(n_interno,'') <> ''""").fetchall()]
    finally:
        conn.close()
    coches.sort(key=lambda c: (len(c["n"]), c["n"]))
    return jsonify({"choferes": choferes(), "coches": coches})


@bp_corp_asig.route("/api/corp/asig/dia/<fecha>/slot", methods=["POST"])
@_cambio
def api_slot(fecha):
    guardar_slot(fecha, request.get_json(silent=True) or {}, _quien())
    return _respuesta(fecha)


@bp_corp_asig.route("/api/corp/asig/dia/<fecha>/horario", methods=["POST"])
@_cambio
def api_horario(fecha):
    r = poner_horario(fecha, request.get_json(silent=True) or {}, _quien())
    _auditar(f"Cambió el horario de un tramo de corporativos solo para el {fecha}",
             f"{r['corto']}: {r['era']} → {r['queda']}")
    return _respuesta(fecha, horario=r)


@bp_corp_asig.route("/api/corp/asig/dia/<fecha>/dividir", methods=["POST"])
@_cambio
def api_dividir(fecha):
    d = request.get_json(silent=True) or {}
    dividir(fecha, d, _quien(), unir=bool(d.get("unir")))
    return _respuesta(fecha)


@bp_corp_asig.route("/api/corp/asig/dia/<fecha>/no_corre", methods=["POST"])
@_cambio
def api_no_corre(fecha):
    no_corre(fecha, request.get_json(silent=True) or {}, _quien())
    return _respuesta(fecha)


@bp_corp_asig.route("/api/corp/asig/dia/<fecha>/quitar_varios", methods=["POST"])
@_cambio
def api_quitar_varios(fecha):
    n = quitar_varios(fecha, request.get_json(silent=True) or {}, _quien())
    return _respuesta(fecha, quitados=n)


@bp_corp_asig.route("/api/corp/asig/dia/<fecha>/tramo", methods=["POST"])
@_cambio
def api_agregar_tramo(fecha):
    agregar_tramo(fecha, request.get_json(silent=True) or {}, _quien())
    return _respuesta(fecha)


@bp_corp_asig.route("/api/corp/asig/dia/<fecha>/variable", methods=["POST"])
@_cambio
def api_variable(fecha):
    fid = guardar_variable(fecha, request.get_json(silent=True) or {}, _quien())
    return _respuesta(fecha, nuevo=fid)


@bp_corp_asig.route("/api/corp/asig/fila/<int:fid>", methods=["PATCH", "DELETE"])
def api_fila(fid):
    if not _puede_editar():
        return _no()
    conn = get_connection()
    try:
        f = conn.execute("""SELECT a.*, d.fecha FROM corp_asig a JOIN corp_asig_dias d ON d.id = a.dia_id
                            WHERE a.id=?""", (fid,)).fetchone()
    finally:
        conn.close()
    if not f:
        return jsonify({"ok": False, "msg": "Ya no existe"}), 404
    try:
        if request.method == "DELETE":
            borrar_fila(fid)
        else:
            guardar_variable(f["fecha"], request.get_json(silent=True) or {}, _quien(), fid=fid)
    except Error as e:
        return jsonify({"ok": False, "msg": str(e)}), 400
    return _respuesta(f["fecha"])


@bp_corp_asig.route("/api/corp/asig/dia/<fecha>/copiar", methods=["POST"])
@_cambio
def api_copiar(fecha):
    d = request.get_json(silent=True) or {}
    r = copiar(fecha, _fecha_ok(d.get("desde")), _quien(), reemplazar=bool(d.get("reemplazar")),
               con_variables=bool(d.get("variables")))
    if r.get("necesita_confirmar"):
        return jsonify({"ok": False, "confirmar": True, "ya_tiene": r["ya_tiene"],
                        "msg": f"Ese día ya tiene {r['ya_tiene']} asignaciones"}), 409
    _auditar("Copió la asignación corporativa", f"{d.get('desde')} → {fecha} ({r['copiadas']})")
    return _respuesta(fecha, copia=r)


@bp_corp_asig.route("/api/corp/asig/dia/<fecha>", methods=["DELETE"])
@_cambio
def api_vaciar(fecha):
    n = vaciar(fecha)
    _auditar("Vació la asignación corporativa", f"{fecha} ({n})")
    return _respuesta(fecha, borradas=n)


@bp_corp_asig.route("/api/corp/asig/dia/<fecha>/publicar", methods=["POST"])
@_cambio
def api_publicar(fecha):
    r, err = publicar(fecha, _quien())
    if err:
        return jsonify({"ok": False, "msg": err}), 400
    if not r.get("sin_cambios"):
        _auditar("Publicó la asignación corporativa", f"{fecha} versión {r['version']}")
    return _respuesta(fecha, publicado=r)


@bp_corp_asig.route("/api/corp/asig/dia/<fecha>/versiones", methods=["GET"])
def api_versiones(fecha):
    if not _puede_ver():
        return _no()
    try:
        return jsonify(versiones(_fecha_ok(fecha)))
    except Error as e:
        return jsonify({"ok": False, "msg": str(e)}), 400


def _archivo(fecha, tipo):
    if not _puede_ver():
        return _no()
    try:
        fecha = _fecha_ok(fecha)
    except Error as e:
        return jsonify({"ok": False, "msg": str(e)}), 400
    cliente = (request.args.get("cliente") or "").strip()
    info = datos_para_pdf(fecha, request.args.get("v"), cliente or None)
    if not info:
        return jsonify({"ok": False, "msg": "No hay asignación de esa empresa ese día" if cliente
                        else "No hay asignación ese día"}), 404
    import corp_asig_pdf
    quien = re.sub(r"[^A-Za-z0-9]+", "-", info.get("cliente") or "").strip("-").lower()
    nombre = f"corporativos-{quien + '-' if quien else ''}{fecha}" + \
        (f"-v{info['version']}" if not info["borrador"] and info["version"] else "-borrador")
    if tipo == "imagen":
        return Response(corp_asig_pdf.generar_imagen(info), mimetype="image/png",
                        headers={"Content-Disposition": f'inline; filename="{nombre}.png"'})
    return Response(corp_asig_pdf.generar_pdf(info), mimetype="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{nombre}.pdf"'})


@bp_corp_asig.route("/api/corp/asig/dia/<fecha>/pdf", methods=["GET"])
def api_pdf(fecha):
    return _archivo(fecha, "pdf")


@bp_corp_asig.route("/api/corp/asig/dia/<fecha>/imagen", methods=["GET"])
def api_imagen(fecha):
    return _archivo(fecha, "imagen")
