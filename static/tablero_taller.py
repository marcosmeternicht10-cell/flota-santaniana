"""
tablero_taller.py — Tablero de control del taller: plan contra real por
técnico (La Santaniana)

Lo mismo que la planilla «Tablero de control» del taller (una fila por
técnico, en celeste lo PLANIFICADO y abajo el INICIO/FIN real de cada OT),
pero que se llena sola:

  PLAN   · lo que el jefe planifica desde el tablero (OT, hora de inicio y de
           fin estimadas, nota), y le asigna los trabajos;
         · los turnos del agendamiento de ese día con ese técnico;
         · hoy: los trabajos que tiene asignados en OTs abiertas.
  REAL   · las horas cargadas en la OT (Horas del personal): primer inicio,
           último fin, horas trabajadas y si está trabajando ahora;
         · los trabajos que terminó.

Cada casillero dice cómo va: terminado (a tiempo o tarde), en curso,
atrasado, sin empezar o no planificado. Sale en PDF y en Excel con el
formato de la planilla.

  init_tablero_taller()
  tablero(fecha)                         los datos de un día
  GET    /api/taller/tablero?fecha=
  POST   /api/taller/tablero/plan        {fecha, personal_id, ot_id, hora_ini, hora_fin, nota, items:[...]}
  DELETE /api/taller/tablero/plan/<id>
  GET    /api/taller/tablero/ots         las OTs abiertas para planificar
  GET    /api/taller/tablero.xlsx | .pdf ?fecha=
"""

import io
import re
from datetime import date, datetime, timedelta

from flask import Blueprint, request, jsonify, session, send_file

from db_compat import get_connection, USE_POSTGRES
from hora_local import hoy as _hoy, ahora_iso

bp_tablero = Blueprint("tablero_taller", __name__)

PK = "SERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"
TOLERANCIA_MIN = 15          # minutos de gracia antes de marcar «atrasado» o «tarde»
DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
         "octubre", "noviembre", "diciembre"]
ESTADOS = {
    "terminado": "Terminado", "tarde": "Terminado tarde", "en_curso": "En curso",
    "atrasado": "Atrasado", "pendiente": "Sin empezar", "no_plan": "No planificado",
}


def _rollback(conn):
    try:
        conn.rollback()
    except Exception:
        pass


def init_tablero_taller():
    conn = get_connection()
    try:
        conn.execute(f"""CREATE TABLE IF NOT EXISTS taller_tablero_plan (
            id {PK},
            fecha TEXT NOT NULL,
            personal_id INTEGER NOT NULL,
            ot_id INTEGER NOT NULL,
            hora_ini TEXT DEFAULT '',
            hora_fin TEXT DEFAULT '',
            nota TEXT DEFAULT '',
            orden INTEGER DEFAULT 0,
            creado_por TEXT DEFAULT '',
            creado_el TEXT DEFAULT '',
            UNIQUE (fecha, personal_id, ot_id))""")
        conn.execute("CREATE INDEX IF NOT EXISTS ix_ttplan_fecha ON taller_tablero_plan (fecha)")
        conn.commit()
    except Exception as e:
        _rollback(conn)
        print(f"[tablero_taller] no se pudo crear la tabla: {e}")
    finally:
        conn.close()


def _hora(v):
    s = str(v or "").strip()
    m = re.fullmatch(r"(\d{1,2})[:.h]?(\d{2})?", s)
    if not m:
        return ""
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    if h > 23 or mi > 59:
        return ""
    return f"{h:02d}:{mi:02d}"


def _fecha(v):
    try:
        return date.fromisoformat(str(v or "")[:10]).isoformat()
    except ValueError:
        return _hoy()


def _ids(txt):
    out = []
    for x in re.split(r"[,\s]+", str(txt or "")):
        if x.strip().isdigit():
            out.append(int(x))
    return out


def _minutos(hhmm):
    try:
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return None


# ════════════════════════════════════════════════════════════════════════════
# LOS DATOS DE UN DÍA
# ════════════════════════════════════════════════════════════════════════════

def tablero(fecha=None):
    fecha = _fecha(fecha)
    hoy = _hoy()
    ahora = ahora_iso()[:16]
    conn = get_connection()
    try:
        personas = [dict(r) for r in conn.execute(
            "SELECT * FROM taller_personal WHERE COALESCE(activo,1)=1 ORDER BY numero").fetchall()]
        pids = {p["id"] for p in personas}
        celdas = {}          # (pid, clave) → celda

        def celda(pid, clave, ot_id=None):
            k = (pid, clave)
            if k not in celdas:
                celdas[k] = {"clave": clave, "ot_id": ot_id, "plan_id": None, "turno_id": None, "hora_ini": "",
                             "hora_fin": "", "nota": "", "orden": 999, "fuentes": set(), "trabajos": [],
                             "tandas": []}
            return celdas[k]

        # 1) lo planificado desde el tablero
        for r in conn.execute("SELECT * FROM taller_tablero_plan WHERE fecha=? ORDER BY orden, hora_ini, id",
                              (fecha,)).fetchall():
            if r["personal_id"] not in pids:
                continue
            c = celda(r["personal_id"], f"ot:{r['ot_id']}", r["ot_id"])
            c.update(plan_id=r["id"], hora_ini=r["hora_ini"] or "", hora_fin=r["hora_fin"] or "",
                     nota=r["nota"] or "", orden=r["orden"] or 0)
            c["fuentes"].add("tablero")

        # 2) los turnos del agendamiento de ese día
        try:
            for r in conn.execute("""SELECT t.id, t.hora, t.tecnicos, t.ot_id, t.notas, t.estado
                                     FROM taller_turnos t WHERE t.fecha=? AND t.estado IN ('agendado','en_ot','cumplido')
                                     AND COALESCE(t.tecnicos,'') <> ''""", (fecha,)).fetchall():
                for pid in _ids(r["tecnicos"]):
                    if pid not in pids:
                        continue
                    clave = f"ot:{r['ot_id']}" if r["ot_id"] else f"turno:{r['id']}"
                    c = celda(pid, clave, r["ot_id"])
                    c["turno_id"] = r["id"]
                    if not c["hora_ini"] and r["hora"]:
                        c["hora_ini"] = _hora(r["hora"])
                    if not c["nota"] and r["notas"]:
                        c["nota"] = r["notas"]
                    c["fuentes"].add("agenda")
        except Exception:
            _rollback(conn)

        # 3) los trabajos asignados: abiertos (si es hoy o futuro cercano) o terminados ese día
        filas = conn.execute("""SELECT ip.personal_id, i.id AS item_id, i.ot_id, i.descripcion, i.estado,
                                       SUBSTR(COALESCE(i.fecha_completado,''),1,10) AS hecho_el,
                                       SUBSTR(COALESCE(i.fecha,''),1,10) AS cargado_el,
                                       o.estado AS ot_estado, SUBSTR(o.fecha_apertura,1,10) AS apertura
                                FROM ot_item_personal ip JOIN ot_items i ON i.id = ip.item_id
                                JOIN ordenes_trabajo o ON o.id = i.ot_id
                                WHERE o.estado <> 'cerrada' OR SUBSTR(COALESCE(i.fecha_completado,''),1,10)=?
                                   OR SUBSTR(COALESCE(o.fecha_cierre,''),1,10)=?""", (fecha, fecha)).fetchall()
        for f in filas:
            if f["personal_id"] not in pids:
                continue
            hecho = f["estado"] == "completado"
            desde = f["cargado_el"] or f["apertura"] or ""
            # hoy: todo lo que tiene asignado y sigue abierto; otro día: lo que terminó ese día
            abierto_ese_dia = fecha == hoy and not hecho and desde <= fecha
            if not (abierto_ese_dia or (hecho and f["hecho_el"] == fecha)):
                continue
            if hecho and f["hecho_el"] and f["hecho_el"] < fecha:
                continue
            c = celda(f["personal_id"], f"ot:{f['ot_id']}", f["ot_id"])
            c["trabajos"].append({"item_id": f["item_id"], "descripcion": f["descripcion"] or "",
                                  "estado": f["estado"] or "pendiente", "hecho_el": f["hecho_el"] or ""})
            c["fuentes"].add("asignado")

        # 4) las horas reales de ese día (aunque no estuviera planificado)
        try:
            for r in conn.execute("""SELECT id, ot_id, personal_id, inicio, fin FROM ot_horas
                                     WHERE SUBSTR(inicio,1,10)=? OR SUBSTR(COALESCE(fin,''),1,10)=?
                                        OR (SUBSTR(inicio,1,10) < ? AND COALESCE(fin,'')='')""",
                                  (fecha, fecha, fecha)).fetchall():
                if r["personal_id"] not in pids:
                    continue
                c = celda(r["personal_id"], f"ot:{r['ot_id']}", r["ot_id"])
                c["tandas"].append({"id": r["id"], "inicio": r["inicio"], "fin": r["fin"] or ""})
                c["fuentes"].add("horas")
        except Exception:
            _rollback(conn)

        # los trabajos de cada OT planificada que no tenían asignados (para mostrar qué incluye)
        ot_ids = sorted({c["ot_id"] for c in celdas.values() if c["ot_id"]})
        ots = {}
        if ot_ids:
            m = ",".join("?" * len(ot_ids))
            for r in conn.execute(f"""SELECT o.id, o.estado, o.vehiculo_id, v.n_interno, v.patente, v.marca, v.modelo
                                      FROM ordenes_trabajo o LEFT JOIN vehiculos v ON v.id = o.vehiculo_id
                                      WHERE o.id IN ({m})""", ot_ids).fetchall():
                ots[r["id"]] = dict(r)
        turnos = {}
        t_ids = sorted({c["turno_id"] for c in celdas.values() if c["turno_id"] and not c["ot_id"]})
        if t_ids:
            m = ",".join("?" * len(t_ids))
            try:
                for r in conn.execute(f"""SELECT t.id, t.tareas, v.n_interno, v.patente FROM taller_turnos t
                                          JOIN vehiculos v ON v.id = t.vehiculo_id WHERE t.id IN ({m})""",
                                      t_ids).fetchall():
                    turnos[r["id"]] = dict(r)
                nombres = {}
                tids = sorted({x for t in turnos.values() for x in _ids(t["tareas"])})
                if tids:
                    for r in conn.execute(f"SELECT id, tarea FROM tareas_plan WHERE id IN ({','.join('?' * len(tids))})",
                                          tids).fetchall():
                        nombres[r["id"]] = r["tarea"]
                for t in turnos.values():
                    t["tareas_txt"] = [nombres[x] for x in _ids(t["tareas"]) if x in nombres]
            except Exception:
                _rollback(conn)
    finally:
        conn.close()

    # armar cada técnico con sus casilleros, ya con su estado
    por = {}
    for (pid, _), c in celdas.items():
        por.setdefault(pid, []).append(c)
    salida, tot = [], {"tecnicos": 0, "planificadas": 0, "terminadas": 0, "en_curso": 0, "atrasadas": 0,
                       "no_plan": 0, "horas": 0.0}
    for p in personas:
        cs = por.get(p["id"], [])
        lista = []
        for c in cs:
            lista.append(_armar_celda(c, ots, turnos, fecha, hoy, ahora))
        lista.sort(key=lambda x: (x["orden"], x["hora_ini"] or "99", x["real_ini"] or "99", x["ot_id"] or 0))
        r = {"id": p["id"], "numero": p["numero"], "nombre": p["nombre"], "puesto": p.get("puesto") or "",
             "turno": p.get("turno") or "", "horario": p.get("horario") or "", "celdas": lista}
        r["resumen"] = {
            "planificadas": sum(1 for x in lista if x["planificado"]),
            "terminadas": sum(1 for x in lista if x["estado"] in ("terminado", "tarde")),
            "en_curso": sum(1 for x in lista if x["estado"] == "en_curso"),
            "atrasadas": sum(1 for x in lista if x["estado"] == "atrasado"),
            "no_plan": sum(1 for x in lista if not x["planificado"]),
            "horas": round(sum(x["horas"] for x in lista), 2),
            "trabajando": any(x["trabajando"] for x in lista),
        }
        pl = r["resumen"]["planificadas"]
        r["resumen"]["cumplimiento"] = round(100 * sum(1 for x in lista if x["planificado"] and x["estado"] in ("terminado", "tarde")) / pl) if pl else None
        if lista:
            tot["tecnicos"] += 1
        for k in ("planificadas", "terminadas", "en_curso", "atrasadas", "no_plan"):
            tot[k] += r["resumen"][k]
        tot["horas"] += r["resumen"]["horas"]
        salida.append(r)
    tot["horas"] = round(tot["horas"], 1)
    tot["cumplimiento"] = round(100 * sum(1 for t in salida for x in t["celdas"] if x["planificado"] and x["estado"] in ("terminado", "tarde")) / tot["planificadas"]) if tot["planificadas"] else None
    d = date.fromisoformat(fecha)
    # las OTs abiertas que nadie tiene ese día: para arrastrarlas a un técnico
    por_planificar = []
    if fecha >= hoy:
        en_tablero = {x["ot_id"] for t in salida for x in t["celdas"] if x["ot_id"]}
        for o in ots_abiertas():
            libres = [i for i in o["trabajos"] if not (i.get("tecnico") or "").strip()]
            if o["id"] in en_tablero or not libres:
                continue
            por_planificar.append({"ot_id": o["id"], "coche": o["coche"], "vehiculo": o["vehiculo"],
                                   "libres": len(libres), "trabajos": [i["descripcion"] for i in libres[:4]]})
    return {"fecha": fecha, "hoy": hoy, "ahora": ahora, "dia_txt": f"{DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]} de {d.year}",
            "tecnicos": salida, "totales": tot, "estados": ESTADOS, "max_celdas": max([len(t["celdas"]) for t in salida] + [0]),
            "por_planificar": por_planificar}


def _armar_celda(c, ots, turnos, fecha, hoy, ahora):
    o = ots.get(c["ot_id"]) if c["ot_id"] else None
    t = turnos.get(c["turno_id"]) if c["turno_id"] and not c["ot_id"] else None
    coche = (o and (o["n_interno"] or o["patente"])) or (t and (t["n_interno"] or t["patente"])) or ""
    tandas = sorted(c["tandas"], key=lambda x: x["inicio"])
    horas, trabajando = 0.0, False
    for x in tandas:
        fin = x["fin"] or (ahora if fecha == hoy else "")
        if x["fin"] == "":
            trabajando = fecha == hoy
        if fin:
            try:
                ini = max(x["inicio"], fecha + "T00:00")
                fn = min(fin, fecha + "T23:59")
                horas += max(0.0, (datetime.fromisoformat(fn) - datetime.fromisoformat(ini)).total_seconds() / 3600)
            except ValueError:
                pass
    real_ini = tandas[0]["inicio"][11:16] if tandas and tandas[0]["inicio"][:10] == fecha else (
        "antes" if tandas else "")
    fines = [x["fin"] for x in tandas if x["fin"]]
    real_fin = max(fines)[11:16] if fines and not trabajando else ""
    trab = c["trabajos"]
    hechos = sum(1 for x in trab if x["estado"] == "completado")
    planificado = bool(c["fuentes"] & {"tablero", "agenda", "asignado"})
    ot_cerrada = bool(o and o["estado"] == "cerrada")
    # el estado del casillero
    todo_hecho = bool(trab) and hechos == len(trab)
    empezado = bool(tandas) or any(x["estado"] == "en_proceso" for x in trab) or hechos > 0
    if trabajando:
        estado = "en_curso"
    elif todo_hecho or ot_cerrada:
        estado = "terminado"
        if c["hora_fin"] and real_fin:
            m_plan, m_real = _minutos(c["hora_fin"]), _minutos(real_fin)
            if m_plan is not None and m_real is not None and m_real > m_plan + TOLERANCIA_MIN:
                estado = "tarde"
    elif fecha < hoy:
        estado = "atrasado"          # el día pasó y quedó sin terminar
    elif empezado:
        estado = "en_curso"
    else:
        estado = "pendiente"
        if fecha == hoy and c["hora_ini"]:
            m_plan, m_now = _minutos(c["hora_ini"]), _minutos(ahora[11:16])
            if m_plan is not None and m_now > m_plan + TOLERANCIA_MIN:
                estado = "atrasado"
    if not planificado and estado in ("pendiente", "atrasado"):
        estado = "no_plan"
    plan_horas = None
    if c["hora_ini"] and c["hora_fin"]:
        a, b = _minutos(c["hora_ini"]), _minutos(c["hora_fin"])
        if a is not None and b is not None and b > a:
            plan_horas = round((b - a) / 60, 2)
    return {
        "clave": c["clave"], "ot_id": c["ot_id"], "plan_id": c["plan_id"], "turno_id": c["turno_id"],
        "coche": str(coche), "vehiculo": o and " ".join(x for x in (o.get("marca"), o.get("modelo")) if x) or "",
        "hora_ini": c["hora_ini"], "hora_fin": c["hora_fin"], "plan_horas": plan_horas, "nota": c["nota"],
        "orden": c["orden"], "fuentes": sorted(c["fuentes"]), "planificado": planificado,
        "trabajos": trab, "hechos": hechos, "tareas_turno": (t or {}).get("tareas_txt", []),
        "real_ini": real_ini, "real_fin": real_fin, "horas": round(horas, 2), "trabajando": trabajando,
        "tandas": tandas, "estado": estado,
        "ot_cerrada": ot_cerrada,
    }


# ════════════════════════════════════════════════════════════════════════════
# PLANIFICAR
# ════════════════════════════════════════════════════════════════════════════

def planificar(d, quien=""):
    fecha = _fecha(d.get("fecha"))
    try:
        pid, ot_id = int(d.get("personal_id") or 0), int(d.get("ot_id") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "msg": "Faltan datos"}
    if not pid or not ot_id:
        return {"ok": False, "msg": "Elegí el técnico y la OT"}
    hi, hf = _hora(d.get("hora_ini")), _hora(d.get("hora_fin"))
    if hi and hf and hf <= hi:
        return {"ok": False, "msg": "La hora de fin tiene que ser después de la de inicio"}
    nota = re.sub(r"\s+", " ", str(d.get("nota") or "")).strip()[:300]
    conn = get_connection()
    try:
        if not conn.execute("SELECT 1 FROM taller_personal WHERE id=?", (pid,)).fetchone():
            return {"ok": False, "msg": "Ese técnico no existe"}
        o = conn.execute("SELECT id, estado FROM ordenes_trabajo WHERE id=?", (ot_id,)).fetchone()
        if not o:
            return {"ok": False, "msg": "Esa OT no existe"}
        ya = conn.execute("SELECT id FROM taller_tablero_plan WHERE fecha=? AND personal_id=? AND ot_id=?",
                          (fecha, pid, ot_id)).fetchone()
        if ya:
            conn.execute("UPDATE taller_tablero_plan SET hora_ini=?, hora_fin=?, nota=? WHERE id=?",
                         (hi, hf, nota, ya["id"]))
            plan_id = ya["id"]
        else:
            orden = conn.execute("SELECT COALESCE(MAX(orden),0)+1 AS n FROM taller_tablero_plan WHERE fecha=? AND personal_id=?",
                                 (fecha, pid)).fetchone()["n"]
            cur = conn.execute("""INSERT INTO taller_tablero_plan (fecha, personal_id, ot_id, hora_ini, hora_fin, nota,
                                  orden, creado_por, creado_el) VALUES (?,?,?,?,?,?,?,?,?)""",
                               (fecha, pid, ot_id, hi, hf, nota, orden, quien[:80], ahora_iso()))
            plan_id = cur.lastrowid
        conn.commit()
        # los trabajos que se le asignan (se suman a los que ya tenía cada trabajo)
        items = []
        for x in d.get("items") or []:
            try:
                items.append(int(x))
            except (TypeError, ValueError):
                pass
        validos = []
        if items:
            m = ",".join("?" * len(items))
            validos = [r["id"] for r in conn.execute(f"SELECT id FROM ot_items WHERE id IN ({m}) AND ot_id=?",
                                                     items + [ot_id]).fetchall()]
        actuales = {}
        if validos:
            m = ",".join("?" * len(validos))
            for r in conn.execute(f"SELECT item_id, personal_id FROM ot_item_personal WHERE item_id IN ({m})", validos).fetchall():
                actuales.setdefault(r["item_id"], []).append(r["personal_id"])
    except Exception as e:
        _rollback(conn)
        return {"ok": False, "msg": f"No se pudo guardar: {e}"}
    finally:
        conn.close()
    asignados = 0
    if validos:
        import personal_taller
        for iid in validos:
            if pid in actuales.get(iid, []):
                continue
            personal_taller.asignar(iid, actuales.get(iid, []) + [pid], quien=quien)
            asignados += 1
    return {"ok": True, "id": plan_id, "asignados": asignados,
            "msg": "Plan guardado" + (f" · {asignados} trabajo{'s' if asignados != 1 else ''} asignado{'s' if asignados != 1 else ''}" if asignados else "")}


def quitar_plan(plan_id):
    conn = get_connection()
    try:
        r = conn.execute("SELECT * FROM taller_tablero_plan WHERE id=?", (plan_id,)).fetchone()
        if not r:
            return {"ok": False, "msg": "Ya no estaba en el plan"}
        conn.execute("DELETE FROM taller_tablero_plan WHERE id=?", (plan_id,))
        conn.commit()
        return {"ok": True, "msg": "Sacado del plan del día (los trabajos asignados en la OT siguen)"}
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════════════
# MOVER LAS PIEZAS (arrastrar en el tablero)
# ════════════════════════════════════════════════════════════════════════════

def _celda_de(fecha, pid, clave):
    for t in tablero(fecha)["tecnicos"]:
        if t["id"] == pid:
            for c in t["celdas"]:
                if c["clave"] == clave:
                    return c
    return None


def mover(d, quien=""):
    """Arrastrar una OT de un técnico a otro.
    modo 'pasar': se la saca a uno y se la da al otro (plan, trabajos sin
    terminar y el turno de la agenda); 'sumar': la tienen los dos."""
    fecha = _fecha(d.get("fecha"))
    try:
        de, a = int(d.get("de") or 0), int(d.get("a") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "msg": "Faltan datos"}
    clave = str(d.get("clave") or "")
    modo = "sumar" if d.get("modo") == "sumar" else "pasar"
    if not de or not a or de == a or not clave:
        return {"ok": False, "msg": "Faltan datos"}
    c = _celda_de(fecha, de, clave)
    if not c:
        return {"ok": False, "msg": "Esa OT ya no está en el tablero de ese técnico"}
    conn = get_connection()
    try:
        nombres = {r["id"]: f"N°{r['numero']} {r['nombre']}" for r in conn.execute(
            "SELECT id, numero, nombre FROM taller_personal WHERE id IN (?,?)", (de, a)).fetchall()}
        if a not in nombres:
            return {"ok": False, "msg": "Ese técnico no existe"}
        # 1) el turno de la agenda (si la pieza viene de ahí)
        if c["turno_id"]:
            t = conn.execute("SELECT tecnicos FROM taller_turnos WHERE id=?", (c["turno_id"],)).fetchone()
            if t:
                ids = _ids(t["tecnicos"])
                if modo == "pasar":
                    ids = [a if x == de else x for x in ids]
                if a not in ids:
                    ids.append(a)
                ids = list(dict.fromkeys(ids))
                conn.execute("UPDATE taller_turnos SET tecnicos=? WHERE id=?", (",".join(str(x) for x in ids), c["turno_id"]))
        # 2) el plan del día
        if c["ot_id"]:
            orden = conn.execute("SELECT COALESCE(MAX(orden),0)+1 AS n FROM taller_tablero_plan WHERE fecha=? AND personal_id=?",
                                 (fecha, a)).fetchone()["n"]
            ya = conn.execute("SELECT id FROM taller_tablero_plan WHERE fecha=? AND personal_id=? AND ot_id=?",
                              (fecha, a, c["ot_id"])).fetchone()
            if not ya:
                conn.execute("""INSERT INTO taller_tablero_plan (fecha, personal_id, ot_id, hora_ini, hora_fin, nota, orden,
                                creado_por, creado_el) VALUES (?,?,?,?,?,?,?,?,?)""",
                             (fecha, a, c["ot_id"], c["hora_ini"], c["hora_fin"], c["nota"], orden, quien[:80], ahora_iso()))
            if modo == "pasar":
                conn.execute("DELETE FROM taller_tablero_plan WHERE fecha=? AND personal_id=? AND ot_id=?",
                             (fecha, de, c["ot_id"]))
        conn.commit()
    except Exception as e:
        _rollback(conn)
        return {"ok": False, "msg": f"No se pudo mover: {e}"}
    finally:
        conn.close()
    # 3) los trabajos sin terminar que tenía asignados
    cambiados = 0
    pendientes = [t["item_id"] for t in c["trabajos"] if t["estado"] != "completado"]
    if pendientes:
        import personal_taller
        conn = get_connection()
        try:
            actuales = {}
            m = ",".join("?" * len(pendientes))
            for r in conn.execute(f"SELECT item_id, personal_id FROM ot_item_personal WHERE item_id IN ({m})", pendientes).fetchall():
                actuales.setdefault(r["item_id"], []).append(r["personal_id"])
        finally:
            conn.close()
        for iid in pendientes:
            ids = actuales.get(iid, [])
            nuevo = [a if x == de else x for x in ids] if modo == "pasar" else ids + [a]
            nuevo = list(dict.fromkeys(nuevo))
            if nuevo != ids:
                personal_taller.asignar(iid, nuevo, quien=quien)
                cambiados += 1
    que = f"OT {c['ot_id']}" if c["ot_id"] else "el turno"
    msg = (f"{que} pasó a {nombres[a]}" if modo == "pasar" else f"{que} ahora la tienen {nombres.get(de, '')} y {nombres[a]}")
    if cambiados:
        msg += f" · {cambiados} trabajo{'s' if cambiados != 1 else ''} reasignado{'s' if cambiados != 1 else ''}"
    return {"ok": True, "msg": msg}


def ordenar(d, quien=""):
    """El orden de las OTs de un técnico (cuál hace primero)."""
    fecha = _fecha(d.get("fecha"))
    try:
        pid = int(d.get("personal_id") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "msg": "Faltan datos"}
    claves = [str(x) for x in (d.get("claves") or [])]
    celdas = {c["clave"]: c for t in tablero(fecha)["tecnicos"] if t["id"] == pid for c in t["celdas"]}
    conn = get_connection()
    try:
        for k, clave in enumerate(claves, start=1):
            c = celdas.get(clave)
            if not c or not c["ot_id"]:
                continue
            ya = conn.execute("SELECT id FROM taller_tablero_plan WHERE fecha=? AND personal_id=? AND ot_id=?",
                              (fecha, pid, c["ot_id"])).fetchone()
            if ya:
                conn.execute("UPDATE taller_tablero_plan SET orden=? WHERE id=?", (k, ya["id"]))
            else:
                conn.execute("""INSERT INTO taller_tablero_plan (fecha, personal_id, ot_id, hora_ini, hora_fin, nota, orden,
                                creado_por, creado_el) VALUES (?,?,?,?,?,?,?,?,?)""",
                             (fecha, pid, c["ot_id"], c["hora_ini"], c["hora_fin"], c["nota"], k, quien[:80], ahora_iso()))
        conn.commit()
    except Exception as e:
        _rollback(conn)
        return {"ok": False, "msg": f"No se pudo ordenar: {e}"}
    finally:
        conn.close()
    return {"ok": True, "msg": "Orden guardado"}


def sacar(d, quien=""):
    """Sacar una pieza del técnico: del plan del día y, si se pide, también
    los trabajos sin terminar que tenía asignados en la OT."""
    fecha = _fecha(d.get("fecha"))
    try:
        pid = int(d.get("personal_id") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "msg": "Faltan datos"}
    c = _celda_de(fecha, pid, str(d.get("clave") or ""))
    if not c:
        return {"ok": False, "msg": "Ya no estaba"}
    conn = get_connection()
    try:
        if c["ot_id"]:
            conn.execute("DELETE FROM taller_tablero_plan WHERE fecha=? AND personal_id=? AND ot_id=?", (fecha, pid, c["ot_id"]))
        if c["turno_id"]:
            t = conn.execute("SELECT tecnicos FROM taller_turnos WHERE id=?", (c["turno_id"],)).fetchone()
            if t:
                conn.execute("UPDATE taller_turnos SET tecnicos=? WHERE id=?",
                             (",".join(str(x) for x in _ids(t["tecnicos"]) if x != pid), c["turno_id"]))
        conn.commit()
    finally:
        conn.close()
    n = 0
    if d.get("desasignar"):
        import personal_taller
        pend = [t["item_id"] for t in c["trabajos"] if t["estado"] != "completado"]
        if pend:
            conn = get_connection()
            try:
                actuales = {}
                for r in conn.execute(f"SELECT item_id, personal_id FROM ot_item_personal WHERE item_id IN ({','.join('?' * len(pend))})",
                                      pend).fetchall():
                    actuales.setdefault(r["item_id"], []).append(r["personal_id"])
            finally:
                conn.close()
            for iid in pend:
                if pid in actuales.get(iid, []):
                    personal_taller.asignar(iid, [x for x in actuales[iid] if x != pid], quien=quien)
                    n += 1
    return {"ok": True, "msg": "Sacado del plan" + (f" y de {n} trabajo{'s' if n != 1 else ''}" if n else "")}


def ots_abiertas(q=""):
    """Las OTs abiertas, con sus trabajos y quién los tiene, para planificar."""
    conn = get_connection()
    try:
        filas = [dict(r) for r in conn.execute("""SELECT o.id, o.estado, SUBSTR(o.fecha_apertura,1,10) AS apertura,
                                                    v.n_interno, v.patente, v.marca, v.modelo
                                                  FROM ordenes_trabajo o LEFT JOIN vehiculos v ON v.id = o.vehiculo_id
                                                  WHERE o.estado <> 'cerrada' ORDER BY o.id DESC LIMIT 300""").fetchall()]
        ids = [f["id"] for f in filas]
        items = {}
        if ids:
            for k in range(0, len(ids), 400):
                tr = ids[k:k + 400]
                m = ",".join("?" * len(tr))
                for r in conn.execute(f"""SELECT i.id, i.ot_id, i.descripcion, i.estado, COALESCE(i.tecnico,'') AS tecnico
                                          FROM ot_items i WHERE i.ot_id IN ({m}) ORDER BY i.id""", tr).fetchall():
                    items.setdefault(r["ot_id"], []).append(dict(r))
    finally:
        conn.close()
    q = str(q or "").strip().lower()
    out = []
    for f in filas:
        its = items.get(f["id"], [])
        pend = [i for i in its if i["estado"] != "completado"]
        if not pend:
            continue
        coche = str(f["n_interno"] or f["patente"] or "")
        txt = f"{f['id']} {coche} {f['patente'] or ''} " + " ".join(i["descripcion"] or "" for i in pend)
        if q and q not in txt.lower():
            continue
        out.append({"id": f["id"], "coche": coche, "patente": f["patente"] or "",
                    "vehiculo": " ".join(x for x in (f["marca"], f["modelo"]) if x), "apertura": f["apertura"],
                    "estado": f["estado"], "trabajos": pend})
    return out


# ════════════════════════════════════════════════════════════════════════════
# EXCEL (el formato de la planilla) Y PDF
# ════════════════════════════════════════════════════════════════════════════

CELESTE = "BDD7EE"
CELESTE_F = "DDEBF7"
COLOR_ESTADO = {"terminado": "C6EFCE", "tarde": "FFEB9C", "en_curso": "BDD7EE", "atrasado": "FFC7CE",
                "pendiente": "FFFFFF", "no_plan": "EDEDED"}


def _txt_plan(x):
    partes = [f"OT {x['ot_id']}" if x["ot_id"] else "Turno"]
    if x["coche"]:
        partes.append(f"C. {x['coche']}")
    h = x["hora_ini"] + (f"-{x['hora_fin']}" if x["hora_fin"] else "") if x["hora_ini"] else ""
    if h:
        partes.append(h)
    return " · ".join(partes)


def _txt_real(x):
    if x["trabajando"]:
        return ("Desde antes" if x["real_ini"] == "antes" else f"Desde {x['real_ini']}") + " · trabajando"
    if x["real_ini"]:
        return f"{x['real_ini']}-{x['real_fin'] or '?'}" + (f" ({_horas_txt(x['horas'])})" if x["horas"] else "")
    if x["estado"] in ("terminado", "tarde"):
        return "Sin horas cargadas"
    return "—"


def _horas_txt(h):
    m = round((h or 0) * 60)
    return f"{m} min" if m < 60 else f"{m // 60}h{m % 60:02d}" if m % 60 else f"{m // 60}h"


def xlsx(d):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    wb = Workbook()
    ws = wb.active
    ws.title = "Tablero de control"
    fino = Side(style="thin", color="000000")
    borde = Border(left=fino, right=fino, top=fino, bottom=fino)
    n_ot = max(12, d["max_celdas"])
    ws["B1"] = f"Tablero de control del taller — {d['dia_txt']}"
    ws["B1"].font = Font(bold=True, size=14)
    t = d["totales"]
    ws["B2"] = (f"Planificadas {t['planificadas']} · terminadas {t['terminadas']} · en curso {t['en_curso']} · "
                f"atrasadas {t['atrasadas']} · no planificadas {t['no_plan']} · {t['horas']} h trabajadas"
                + (f" · cumplimiento {t['cumplimiento']} %" if t["cumplimiento"] is not None else ""))
    ws["B2"].font = Font(italic=True, color="555555")
    cab = ["Numero de tecnico", "Tecnico", "Especialidad", ""]
    for i, v in enumerate(cab):
        c = ws.cell(row=3, column=2 + i, value=v)
        c.font = Font(bold=True)
        c.border = borde
        c.alignment = Alignment(horizontal="center", vertical="center")
    ws.cell(row=3, column=6, value="Ordenes de trabajo").font = Font(bold=True)
    ws.merge_cells(start_row=3, start_column=6, end_row=3, end_column=5 + n_ot)
    ws.cell(row=3, column=6).alignment = Alignment(horizontal="center")
    for col in range(6, 6 + n_ot):
        ws.cell(row=3, column=col).border = borde
    fila = 4
    for tec in d["tecnicos"]:
        for col, v in ((2, tec["numero"]), (3, tec["nombre"]), (4, tec["puesto"])):
            ws.cell(row=fila, column=col, value=v)
            ws.merge_cells(start_row=fila, start_column=col, end_row=fila + 1, end_column=col)
            c = ws.cell(row=fila, column=col)
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            for rr in (fila, fila + 1):
                ws.cell(row=rr, column=col).border = borde
        ws.cell(row=fila, column=5, value="PLAN").border = borde
        ws.cell(row=fila + 1, column=5, value="INICIO/FIN").border = borde
        for k in range(n_ot):
            cp = ws.cell(row=fila, column=6 + k)
            cr = ws.cell(row=fila + 1, column=6 + k)
            cp.fill = PatternFill("solid", fgColor=CELESTE)
            cp.border = cr.border = borde
            cp.alignment = cr.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cp.font = Font(size=9, bold=True)
            cr.font = Font(size=9)
            if k < len(tec["celdas"]):
                x = tec["celdas"][k]
                cp.value = _txt_plan(x) if x["planificado"] else f"OT {x['ot_id']} · C. {x['coche']} (no plan.)"
                cr.value = _txt_real(x)
                cr.fill = PatternFill("solid", fgColor=COLOR_ESTADO.get(x["estado"], "FFFFFF"))
        ws.row_dimensions[fila].height = 30
        ws.row_dimensions[fila + 1].height = 30
        fila += 2
    ws.column_dimensions["A"].width = 2
    ws.column_dimensions["B"].width = 10
    ws.column_dimensions["C"].width = 26
    ws.column_dimensions["D"].width = 20
    ws.column_dimensions["E"].width = 11
    for k in range(n_ot):
        ws.column_dimensions[get_column_letter(6 + k)].width = 17
    ws.freeze_panes = "F4"
    fila += 1
    ws.cell(row=fila, column=2, value="Colores de INICIO/FIN:").font = Font(bold=True)
    for i, (k, txt) in enumerate(ESTADOS.items()):
        c = ws.cell(row=fila + 1 + i, column=2, value=txt)
        c.fill = PatternFill("solid", fgColor=COLOR_ESTADO[k])
        c.border = borde
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToHeight = 0
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def pdf(d):
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.colors import HexColor, white
    import trafico_pdf
    from rend_comb_pdf import _Lienzo, _logo, _ahora_txt, NAVY, TINTA, GRIS, LINEA
    F = trafico_pdf._fuentes()
    W, H = landscape(A4)
    M = 22
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(W, H))
    c.setTitle(f"Tablero de control {d['fecha']}")
    c.setAuthor("La Santaniana")
    L = _Lienzo(c, H, F)
    aw = W - 2 * M
    tecs = d["tecnicos"]
    n_col = max(6, min(10, d["max_celdas"] or 6))
    w_num, w_nom, w_esp, w_et = 30, 104, 78, 46
    w_c = (aw - w_num - w_nom - w_esp - w_et) / n_col
    h_f = 20
    colores = {k: HexColor("#" + v) for k, v in COLOR_ESTADO.items()}
    cel = HexColor("#" + CELESTE)
    t = d["totales"]

    def cabecera(pag):
        logo = _logo()
        if logo:
            c.drawImage(logo, M, H - M - 28, 38, 28, mask="auto", preserveAspectRatio=True)
        L.texto(M + 46, M + 14, "Tablero de control del taller", "D9", 17, NAVY)
        L.texto(M + 46, M + 27, d["dia_txt"] + (f" · hoja {pag}" if pag > 1 else ""), "I5", 8.5, GRIS)
        res = (f"Planificadas {t['planificadas']} · terminadas {t['terminadas']} · en curso {t['en_curso']} · "
               f"atrasadas {t['atrasadas']} · no planificadas {t['no_plan']} · {t['horas']} h"
               + (f" · cumplimiento {t['cumplimiento']} %" if t["cumplimiento"] is not None else ""))
        L.texto(W - M, M + 14, res, "I6", 8, TINTA, "r")
        y = M + 40
        L.rect(M, y, aw, 16, fill=NAVY)
        x = M
        for txt, w in (("N°", w_num), ("TÉCNICO", w_nom), ("ESPECIALIDAD", w_esp), ("", w_et)):
            L.texto(x + 4, y + 11, txt, "I7", 6.6, white)
            x += w
        L.texto(x + (n_col * w_c) / 2, y + 11, "ÓRDENES DE TRABAJO", "I7", 6.6, white, "c")
        return y + 16

    pag = 1
    y = cabecera(pag)
    for tec in tecs:
        filas_tec = max(1, -(-len(tec["celdas"]) // n_col))
        alto = h_f * 2 * filas_tec
        if y + alto > H - 40:
            c.showPage()
            pag += 1
            y = cabecera(pag)
        x = M
        for v, w, f in ((str(tec["numero"]), w_num, "D8"), (tec["nombre"], w_nom, "I6"), (tec["puesto"], w_esp, "I4")):
            L.rect(x, y, w, alto, stroke=LINEA)
            L.texto(x + w / 2, y + alto / 2 + 3, L.cortar(v, f, 8 if f != "D8" else 11, w - 6), f, 8 if f != "D8" else 11, TINTA, "c")
            x += w
        for k in range(filas_tec):
            yy = y + k * h_f * 2
            L.rect(x, yy, w_et, h_f, fill=cel, stroke=LINEA)
            L.texto(x + 4, yy + 13, "PLAN", "I7", 7, NAVY)
            L.rect(x, yy + h_f, w_et, h_f, stroke=LINEA)
            L.texto(x + 4, yy + h_f + 13, "INICIO/FIN", "I6", 6.4, TINTA)
            for j in range(n_col):
                idx = k * n_col + j
                cx = x + w_et + j * w_c
                L.rect(cx, yy, w_c, h_f, fill=cel, stroke=LINEA)
                if idx < len(tec["celdas"]):
                    it = tec["celdas"][idx]
                    L.rect(cx, yy + h_f, w_c, h_f, fill=colores.get(it["estado"], white), stroke=LINEA)
                    l1 = (f"OT {it['ot_id']}" if it["ot_id"] else "Turno") + (f" · C.{it['coche']}" if it["coche"] else "")
                    l2 = (it["hora_ini"] + (f"-{it['hora_fin']}" if it["hora_fin"] else "")) if it["hora_ini"] else ("no planificado" if not it["planificado"] else "")
                    L.texto(cx + 3, yy + 8.5, L.cortar(l1, "I7", 6.8, w_c - 6), "I7", 6.8, NAVY)
                    L.texto(cx + 3, yy + 16.5, L.cortar(l2, "I4", 6.3, w_c - 6), "I4", 6.3, TINTA)
                    L.texto(cx + 3, yy + h_f + 8.5, L.cortar(_txt_real(it), "I6", 6.6, w_c - 6), "I6", 6.6, TINTA)
                    L.texto(cx + 3, yy + h_f + 16.5, L.cortar(ESTADOS.get(it["estado"], ""), "I4", 6.1, w_c - 6), "I4", 6.1, GRIS)
                else:
                    L.rect(cx, yy + h_f, w_c, h_f, stroke=LINEA)
        y += alto
    # referencias
    y += 10
    x = M
    for k, txt in ESTADOS.items():
        L.rect(x, y, 10, 8, fill=colores[k], stroke=LINEA)
        L.texto(x + 13, y + 7, txt, "I4", 7, TINTA)
        x += 13 + L.ancho(txt, "I4", 7) + 14
    L.texto(W - M, H - 12, f"La Santaniana · impreso {_ahora_txt()}", "I4", 6.5, GRIS, "r")
    c.save()
    buf.seek(0)
    return buf


# ════════════════════════════════════════════════════════════════════════════
# RUTAS
# ════════════════════════════════════════════════════════════════════════════

def _puede_ver():
    return session.get("rol") in ("admin", "taller", "compras", "auditor")


def _puede_editar():
    return session.get("rol") in ("admin", "taller")


def _quien():
    return session.get("nombre") or session.get("usuario") or ""


@bp_tablero.route("/api/taller/tablero", methods=["GET"])
def api_tablero():
    if not _puede_ver():
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    d = tablero(request.args.get("fecha"))
    d["puede"] = _puede_editar()
    return jsonify({"ok": True, **d})


@bp_tablero.route("/api/taller/tablero/plan", methods=["POST"])
def api_plan():
    if not _puede_editar():
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    r = planificar(request.get_json(silent=True) or {}, _quien())
    if r.get("ok"):
        try:
            from database import registrar_auditoria
            d = request.get_json(silent=True) or {}
            registrar_auditoria(usuario=_quien() or "?", rol=session.get("rol") or "", accion="Planificó en el tablero del taller",
                                categoria="OT", detalle=f"OT #{d.get('ot_id')} técnico {d.get('personal_id')} {d.get('fecha')}")
        except Exception:
            pass
    return jsonify(r), (200 if r.get("ok") else 400)


@bp_tablero.route("/api/taller/tablero/plan/<int:plan_id>", methods=["DELETE"])
def api_plan_quitar(plan_id):
    if not _puede_editar():
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    r = quitar_plan(plan_id)
    return jsonify(r), (200 if r.get("ok") else 400)


@bp_tablero.route("/api/taller/tablero/<accion>", methods=["POST"])
def api_mover(accion):
    if accion not in ("mover", "orden", "sacar"):
        return jsonify({"ok": False, "msg": "No existe"}), 404
    if not _puede_editar():
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    d = request.get_json(silent=True) or {}
    r = {"mover": mover, "orden": ordenar, "sacar": sacar}[accion](d, _quien())
    if r.get("ok") and accion != "orden":
        try:
            from database import registrar_auditoria
            registrar_auditoria(usuario=_quien() or "?", rol=session.get("rol") or "", accion="Tablero del taller",
                                categoria="OT", detalle=r.get("msg", "")[:200])
        except Exception:
            pass
    return jsonify(r), (200 if r.get("ok") else 400)


@bp_tablero.route("/api/taller/tablero/ots", methods=["GET"])
def api_ots():
    if not _puede_ver():
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    return jsonify({"ok": True, "ots": ots_abiertas(request.args.get("q", ""))})


@bp_tablero.route("/api/taller/tablero.xlsx", methods=["GET"])
def api_xlsx():
    if not _puede_ver():
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    d = tablero(request.args.get("fecha"))
    return send_file(xlsx(d), as_attachment=True, download_name=f"Tablero de control {d['fecha']}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@bp_tablero.route("/api/taller/tablero.pdf", methods=["GET"])
def api_pdf():
    if not _puede_ver():
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    d = tablero(request.args.get("fecha"))
    return send_file(pdf(d), mimetype="application/pdf", download_name=f"Tablero de control {d['fecha']}.pdf")
