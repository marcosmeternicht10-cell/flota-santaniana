"""
trafico_programa.py — Programación semanal del internacional (La Santaniana)

La programación que pasó Marcos (oct 2026): qué sale cada día de la semana,
con qué regreso vuelve cada unidad y en qué orden llegan a Asunción.

Reglas:
  1. Las que salen de Asunción van por orden de llegada: la primera que
     llega es la primera que sale.
  2. De Buenos Aires, el de las 17:00 llega antes que el de las 18:00.
  3. La Plata 13:30 no llega a Asunción: queda de reserva en Villarrica
     (sale el martes o el viernes 9:30 de Villarrica).
  4. La Plata 13:35 (leito) llega junto con el de las 17:00.
  5. La Noria 14:20 termina en Villarrica y vuelve en lastre: llega
     después del de las 18:00.

Con esto el sistema:
  - arma el día del internacional desde la programación (horas y tramos);
  - genera las rotaciones (con qué regreso vuelve cada ida) y las salidas
    por día, así no hay que cargarlas a mano;
  - sabe dónde queda cada unidad (la de La Noria en Asunción, la de La
    Plata 13:30 en Villarrica) y en qué orden llegó, y con eso completa las
    salidas de Asunción con la primera que llegó (y el coche cama con un
    coche cama);
  - pone la misma unidad en las salidas encadenadas (0:20 CDE + 12:30).

Enganche en app.py (después de trafico_patron):
    from trafico_programa import bp_programa, init_trafico_programa
    init_trafico_programa()
    app.register_blueprint(bp_programa)
"""

from datetime import date, datetime, timedelta

from flask import Blueprint, request, jsonify, session
from db_compat import get_connection, USE_POSTGRES

bp_programa = Blueprint("trafico_programa", __name__)

PK = "SERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"
DIAS = {1: "LUNES", 2: "MARTES", 3: "MIÉRCOLES", 4: "JUEVES", 5: "VIERNES", 6: "SÁBADO", 7: "DOMINGO"}
DIAS_L = {1: "lunes", 2: "martes", 3: "miércoles", 4: "jueves", 5: "viernes", 6: "sábado", 7: "domingo"}
CLASES = ("", "CAMA", "LEITO")
# Cómo llega a Asunción un regreso (regla 6)
LLEGADAS = {
    "": "Llega a Asunción a su hora",
    "con_1700": "Llega junto con el de las 17:00",
    "despues_1800": "Termina en Villarrica y vuelve en lastre: llega después del de las 18:00",
    "reserva_vca": "No llega a Asunción: queda de reserva en Villarrica",
}
HORA_EQUIV = {"con_1700": "17:00", "despues_1800": "18:30"}
VIAJE_HORAS = 19          # Buenos Aires → Asunción, aprox. (se cambia en la programación)
TOL = 20                  # minutos para reconocer un regreso de la programación
HORAS_ANTES = {"CDE": 6}  # la unidad sale de Asunción unas horas antes para llegar a CDE

# (día, lado, hora, tramo, clase, sigue a las (misma unidad), vuelve día, vuelve hora, llegada, nota)
PROGRAMA_INICIAL = [
    (1, "ida", "00:20", "CDE / RETIRO", "CAMA", "", 2, "17:00", "", ""),
    (1, "ida", "09:00", "ASUNCION / RETIRO X RUTA 1", "", "", 3, "13:30", "", "El martes queda de reserva en Buenos Aires"),
    (1, "ida", "12:30", "ASUNCION / RETIRO", "CAMA", "", 2, "17:00", "", ""),
    (1, "regreso", "17:00", "RETIRO / ASUNCION", "", "", None, "", "", ""),
    (1, "regreso", "18:00", "RETIRO / ASUNCION X RUTA 1", "", "", None, "", "", ""),

    (2, "ida", "00:20", "CDE / VILLARRICA", "", "09:35", None, "", "", ""),
    (2, "ida", "09:00", "ASUNCION / RETIRO X RUTA 1", "", "", 3, "14:20", "", ""),
    (2, "ida", "09:30", "VILLARRICA / SAN JUSTO", "", "", 3, "18:00", "", "La unidad que quedó de reserva en Villarrica (La Plata 13:30 del domingo)"),
    (2, "ida", "09:35", "VILLARRICA / LA NORIA A LA PLATA", "", "", 4, "18:00", "", "Queda de reserva en Buenos Aires"),
    (2, "regreso", "17:00", "RETIRO / ASUNCION", "CAMA", "", None, "", "", ""),
    (2, "regreso", "17:00", "RETIRO / ASUNCION", "CAMA", "", None, "", "", ""),
    (2, "regreso", "18:00", "RETIRO / ASUNCION X RUTA 1", "", "", None, "", "", ""),

    (3, "ida", "00:20", "CDE / RETIRO", "CAMA", "", 4, "17:00", "", ""),
    (3, "ida", "09:00", "ASUNCION / RETIRO X RUTA 1", "", "", 5, "17:00", "", "Unidad de reserva en Asunción; queda de reserva en Buenos Aires"),
    (3, "ida", "12:30", "ASUNCION / RETIRO", "CAMA", "", 4, "17:00", "", ""),
    (3, "regreso", "13:30", "LA PLATA / VILLARRICA", "", "", None, "", "reserva_vca", ""),
    (3, "regreso", "14:20", "LA NORIA / VILLARRICA", "", "", None, "", "despues_1800", ""),
    (3, "regreso", "18:00", "RETIRO / ASUNCION X RUTA 1", "", "", None, "", "", ""),

    (4, "ida", "00:20", "CDE / ASUNCION", "", "12:30", None, "", "", ""),
    (4, "ida", "09:00", "ASUNCION / RETIRO X RUTA 1", "", "", 5, "18:00", "", ""),
    (4, "ida", "12:30", "ASUNCION / RETIRO", "", "", 6, "17:00", "", "Queda de reserva en Buenos Aires"),
    (4, "regreso", "17:00", "RETIRO / ASUNCION", "CAMA", "", None, "", "", ""),
    (4, "regreso", "17:00", "RETIRO / ASUNCION", "CAMA", "", None, "", "", ""),
    (4, "regreso", "18:00", "RETIRO / ASUNCION X RUTA 1", "", "", None, "", "", ""),

    (5, "ida", "00:20", "CDE / VILLARRICA", "", "09:35", None, "", "", ""),
    (5, "ida", "09:00", "ASUNCION / RETIRO X RUTA 1", "", "", 7, "13:30", "", ""),
    (5, "ida", "09:30", "VILLARRICA / SAN JUSTO", "", "", 6, "18:00", "", "La unidad que quedó de reserva en Villarrica (La Plata 13:30 del miércoles)"),
    (5, "ida", "09:35", "VILLARRICA / LA NORIA A LA PLATA", "", "", 7, "18:00", "", "Queda de reserva en Buenos Aires"),
    (5, "ida", "12:30", "ASUNCION / LINIERS", "CAMA", "", 7, "13:35", "", ""),
    (5, "regreso", "17:00", "RETIRO / ASUNCION", "", "", None, "", "", ""),
    (5, "regreso", "18:00", "RETIRO / ASUNCION X RUTA 1", "", "", None, "", "", ""),

    (6, "ida", "00:20", "CDE / ASUNCION", "", "12:30", None, "", "", ""),
    (6, "ida", "09:00", "ASUNCION / RETIRO X RUTA 1", "", "", 7, "14:20", "", ""),
    (6, "ida", "12:30", "ASUNCION / RETIRO", "", "", 1, "17:00", "", "Queda de reserva en Buenos Aires"),
    (6, "regreso", "17:00", "RETIRO / ASUNCION", "", "", None, "", "", ""),
    (6, "regreso", "18:00", "RETIRO / ASUNCION X RUTA 1", "", "", None, "", "", ""),

    (7, "ida", "00:20", "CDE / ASUNCION", "", "12:30", None, "", "", ""),
    (7, "ida", "09:00", "ASUNCION / RETIRO X RUTA 1", "", "", 1, "18:00", "", ""),
    (7, "ida", "12:30", "ASUNCION / RETIRO", "", "", 2, "18:00", "", "Queda de reserva en Buenos Aires"),
    (7, "regreso", "13:30", "LA PLATA / VILLARRICA", "", "", None, "", "reserva_vca", ""),
    (7, "regreso", "13:35", "LA PLATA / ASUNCION", "LEITO", "", None, "", "con_1700", ""),
    (7, "regreso", "14:20", "LA NORIA / VILLARRICA", "", "", None, "", "despues_1800", ""),
    (7, "regreso", "18:00", "RETIRO / ASUNCION X RUTA 1", "", "", None, "", "", ""),
]


def _ahora():
    try:
        from hora_local import ahora_iso
        return ahora_iso()
    except Exception:
        return datetime.now().isoformat(timespec="seconds")


def _rollback(conn):
    try:
        conn.rollback()
    except Exception:
        pass


# ════════════════════════════════════════════════════════════════════════════
# TABLAS
# ════════════════════════════════════════════════════════════════════════════

def init_trafico_programa():
    conn = get_connection()
    try:
        conn.execute(f"""CREATE TABLE IF NOT EXISTS trafico_programa (
            id {PK},
            tipo TEXT NOT NULL DEFAULT 'internacional',
            dia INTEGER NOT NULL,              -- 1=lunes … 7=domingo
            lado TEXT NOT NULL,                -- ida | regreso
            hora TEXT NOT NULL,
            destino TEXT DEFAULT '',           -- el tramo como lo escriben
            clase TEXT DEFAULT '',             -- '' | CAMA | LEITO
            sigue TEXT DEFAULT '',             -- ida: la misma unidad sigue en la salida de esa hora
            vuelve_dia INTEGER,                -- ida: qué día vuelve…
            vuelve_hora TEXT DEFAULT '',       -- …y en qué regreso
            llegada TEXT DEFAULT '',           -- regreso: '' | con_1700 | despues_1800 | reserva_vca
            nota TEXT DEFAULT '',
            orden INTEGER DEFAULT 0)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS trafico_config (
            clave TEXT PRIMARY KEY, valor TEXT DEFAULT '')""")
        conn.execute("""CREATE TABLE IF NOT EXISTS trafico_semillas (
            clave TEXT PRIMARY KEY, aplicada_el TEXT DEFAULT '')""")
        conn.commit()
        from db_compat import columnas_de_tabla
        if "origen" not in set(columnas_de_tabla(conn, "trafico_rotaciones")):
            conn.execute("ALTER TABLE trafico_rotaciones ADD COLUMN origen TEXT DEFAULT ''")
            conn.commit()
        if not conn.execute("SELECT 1 FROM trafico_semillas WHERE clave='programa_int_v1'").fetchone():
            if not conn.execute("SELECT 1 FROM trafico_programa WHERE tipo='internacional'").fetchone():
                for k, (dia, lado, hora, dest, clase, sigue, vd, vh, lleg, nota) in enumerate(PROGRAMA_INICIAL):
                    conn.execute("""INSERT INTO trafico_programa (tipo, dia, lado, hora, destino, clase, sigue,
                                        vuelve_dia, vuelve_hora, llegada, nota, orden)
                                    VALUES ('internacional',?,?,?,?,?,?,?,?,?,?,?)""",
                                 (dia, lado, hora, dest, clase, sigue, vd, vh, lleg, nota, k))
            # Las rotaciones viejas del internacional (las de Villarrica sin hora)
            # quedan apagadas: ahora las arma la programación
            conn.execute("""UPDATE trafico_rotaciones SET activo=0
                            WHERE COALESCE(NULLIF(tipo,''),'nacional')='internacional' AND COALESCE(origen,'')=''""")
            conn.execute("INSERT INTO trafico_semillas (clave, aplicada_el) VALUES (?, ?) ON CONFLICT (clave) DO NOTHING",
                         ("programa_int_v1", _ahora()))
            conn.commit()
            aplicar(conn, "internacional", "programación semanal")
    except Exception as e:
        _rollback(conn)
        print(f"[trafico_programa] init: {e}")
    finally:
        conn.close()


def config(conn, clave, defecto=""):
    try:
        r = conn.execute("SELECT valor FROM trafico_config WHERE clave=?", (clave,)).fetchone()
        return r["valor"] if r and r["valor"] not in (None, "") else defecto
    except Exception:
        _rollback(conn)
        return defecto


def viaje_horas(conn):
    try:
        return max(1, min(48, int(float(config(conn, "viaje_horas_int", VIAJE_HORAS)))))
    except (TypeError, ValueError):
        return VIAJE_HORAS


# ════════════════════════════════════════════════════════════════════════════
# LECTURA
# ════════════════════════════════════════════════════════════════════════════

def filas(conn=None, tipo="internacional"):
    propia = conn is None
    conn = conn or get_connection()
    try:
        out = []
        for r in conn.execute("SELECT * FROM trafico_programa WHERE tipo=? ORDER BY dia, lado, hora, orden, id",
                              (tipo,)).fetchall():
            r = dict(r)
            r["hora"] = _h(r["hora"])
            r["sigue"] = _h(r.get("sigue") or "")
            r["vuelve_hora"] = _h(r.get("vuelve_hora") or "")
            r["vuelve_dia"] = int(r["vuelve_dia"]) if r.get("vuelve_dia") else None
            r["clase"] = (r.get("clase") or "").upper()
            out.append(r)
        return out
    except Exception:
        _rollback(conn)
        return []
    finally:
        if propia:
            conn.close()


def _h(v):
    from trafico import normalizar_hora
    return normalizar_hora(v) or "" if v else ""


def _min(h):
    h = _h(h)
    if not h:
        return None
    a, b = h.split(":")
    return int(a) * 60 + int(b)


def texto_destino(r):
    return f"{r['destino']} {r['clase']}".strip() if r.get("clase") else (r.get("destino") or "")


def _lugares(r):
    import trafico as T
    return T.tramo_internacional(texto_destino(r), r["lado"], "BUENOS AIRES")


def queda_en(r):
    """Dónde queda la unidad después de un regreso."""
    if r.get("llegada") == "reserva_vca":
        return "VILLARRICA"
    if r.get("llegada") == "despues_1800":
        return "ASU"
    return _lugares(r)[1] or "ASU"


def regreso_de(prog, dia, hora, origen=""):
    """La fila de regreso de la programación para un regreso cargado."""
    m = _min(hora)
    if m is None:
        return None
    mejor = None
    for r in prog:
        if r["lado"] != "regreso" or r["dia"] != dia:
            continue
        d = abs((_min(r["hora"]) or 0) - m)
        if d > TOL:
            continue
        o = _lugares(r)[0]
        pena = 0 if (not origen or o == origen) else 30
        if mejor is None or d + pena < mejor[0]:
            mejor = (d + pena, r)
    return mejor[1] if mejor else None


def ida_de(prog, dia, hora):
    m = _min(hora)
    if m is None:
        return None
    c = [(abs((_min(r["hora"]) or 0) - m), r) for r in prog if r["lado"] == "ida" and r["dia"] == dia]
    c = [x for x in c if x[0] <= 10]
    return min(c, key=lambda x: x[0])[1] if c else None


# ════════════════════════════════════════════════════════════════════════════
# REVISIÓN: que cierre la semana
# ════════════════════════════════════════════════════════════════════════════

def revisar(prog):
    """Avisos y números de la semana: cada ida con su regreso, cada regreso
    con la unidad que vuelve, y que las que salen sean las que llegan."""
    avisos = []
    reg_por = {}
    for r in prog:
        if r["lado"] == "regreso":
            reg_por.setdefault((r["dia"], r["hora"]), []).append(r)
    llegan = {}
    sigue_de = {}          # (día, hora de la que sigue) → fila que la encadena
    for r in prog:
        if r["lado"] == "ida" and r.get("sigue"):
            sigue_de[(r["dia"], r["sigue"])] = r
    for r in prog:
        if r["lado"] != "ida":
            continue
        quien = f"{DIAS_L[r['dia']].capitalize()} {r['hora']}"
        if r.get("sigue"):
            if not any(x["lado"] == "ida" and x["dia"] == r["dia"] and x["hora"] == r["sigue"] for x in prog):
                avisos.append({"nivel": "error", "txt": f"{quien}: sigue a las {r['sigue']}, pero ese día no hay salida a esa hora"})
            continue
        if not r.get("vuelve_dia") or not r.get("vuelve_hora"):
            avisos.append({"nivel": "aviso", "txt": f"{quien}: no dice con qué regreso vuelve"})
            continue
        k = (r["vuelve_dia"], r["vuelve_hora"])
        if k not in reg_por:
            avisos.append({"nivel": "error", "txt": f"{quien}: vuelve el {DIAS_L[k[0]]} {k[1]}, pero ese día no hay regreso a esa hora"})
            continue
        llegan.setdefault(k, []).append(r)
    for k, regs in sorted(reg_por.items()):
        n = len(llegan.get(k, []))
        quien = f"{DIAS_L[k[0]].capitalize()} {k[1]}"
        if n == 0:
            avisos.append({"nivel": "aviso", "txt": f"Regreso del {quien}: ninguna ida dice que vuelve en él"})
        elif n != len(regs):
            avisos.append({"nivel": "error", "txt": f"Regreso del {quien}: hay {len(regs)} cargado{'s' if len(regs) != 1 else ''} y le vuelven {n} unidades"})
    # Cuántas unidades arrancan de cada lado y cuántas llegan
    salen = {"ASU": 0, "VILLARRICA": 0}
    for r in prog:
        if r["lado"] != "ida" or (r["dia"], r["hora"]) in sigue_de:
            continue
        o = _lugares(r)[0]
        salen["VILLARRICA" if o == "VILLARRICA" else "ASU"] += 1
    entran = {"ASU": 0, "VILLARRICA": 0}
    for r in prog:
        if r["lado"] == "regreso":
            entran["VILLARRICA" if queda_en(r) == "VILLARRICA" else "ASU"] += 1
    for lugar, txt in (("ASU", "Asunción"), ("VILLARRICA", "Villarrica")):
        if salen[lugar] != entran[lugar]:
            avisos.append({"nivel": "error",
                           "txt": f"{txt}: por semana salen {salen[lugar]} unidades y llegan {entran[lugar]}"})
    return {"avisos": avisos, "salen": salen, "entran": entran,
            "cierra": not any(a["nivel"] == "error" for a in avisos)}


# ════════════════════════════════════════════════════════════════════════════
# APLICAR: rotaciones y salidas por día salen de la programación
# ════════════════════════════════════════════════════════════════════════════

def aplicar(conn, tipo="internacional", quien=""):
    prog = filas(conn, tipo)
    ahora = _ahora()
    conn.execute("DELETE FROM trafico_rotaciones WHERE COALESCE(NULLIF(tipo,''),'nacional')=? AND origen='programa'", (tipo,))
    n = 0
    for r in prog:
        if r["lado"] != "ida" or r.get("sigue") or not r.get("vuelve_dia") or not r.get("vuelve_hora"):
            continue
        destino_reg = next((x for x in prog if x["lado"] == "regreso" and x["dia"] == r["vuelve_dia"]
                            and x["hora"] == r["vuelve_hora"]), None)
        o_ida = _lugares(r)[0]
        vdesde, va = "", ""
        if destino_reg:
            o_reg, l_reg = _lugares(destino_reg)
            if o_reg in ("LA PLATA", "LA NORIA"):
                vdesde = o_reg
                if l_reg == "VILLARRICA" or o_reg == "LA PLATA":
                    va = l_reg or "ASU"
        dias = (r["vuelve_dia"] - r["dia"]) % 7
        nota = f"Programación: {DIAS_L[r['dia']]} {r['hora']} vuelve el {DIAS_L[r['vuelve_dia']]} {r['vuelve_hora']}"
        conn.execute("""INSERT INTO trafico_rotaciones (corredor, tipo, dias, ida_desde, ida_hora, ida_a,
                            vuelta_hora, vuelta_dias, vuelta_desde, vuelta_a, nota, activo, actualizado_el, actualizado_por, origen)
                        VALUES ('BUENOS AIRES',?,?,?,?,'',?,?,?,?,?,1,?,?,'programa')""",
                     (tipo, str(r["dia"]), o_ida if o_ida not in ("ASU", "") else "", r["hora"], r["vuelve_hora"], dias,
                      vdesde, va, nota[:200], ahora, quien or "programación semanal"))
        n += 1
    # Salidas por día: cuántas lleva cada día, con sus horas
    for dia in range(1, 8):
        for lado in ("ida", "regreso"):
            hs = [r["hora"] for r in prog if r["dia"] == dia and r["lado"] == lado]
            nota = " · ".join(hs)[:80]
            fila = conn.execute("SELECT id FROM trafico_patron WHERE tipo=? AND dia=? AND lado=?", (tipo, dia, lado)).fetchone()
            if fila:
                conn.execute("UPDATE trafico_patron SET cantidad=?, nota=?, actualizado_el=?, actualizado_por=? WHERE id=?",
                             (len(hs), nota, ahora, "programación semanal", fila["id"]))
            else:
                conn.execute("""INSERT INTO trafico_patron (tipo, dia, lado, cantidad, nota, actualizado_el, actualizado_por)
                                VALUES (?,?,?,?,?,?,?)""", (tipo, dia, lado, len(hs), nota, ahora, "programación semanal"))
    conn.commit()
    return n


# ════════════════════════════════════════════════════════════════════════════
# DÓNDE QUEDA Y CUÁNDO LLEGA CADA UNIDAD (para el orden de llegada)
# ════════════════════════════════════════════════════════════════════════════

def ajustar_tramos(conn, tramos):
    """A los regresos del internacional les pone dónde queda de verdad la
    unidad (La Noria vuelve en lastre a Asunción; La Plata 13:30 se queda en
    Villarrica), cuándo llega a Asunción (para el orden de llegada) y la
    clase (coche cama / leito)."""
    import trafico as T
    prog = filas(conn, "internacional")
    viaje = viaje_horas(conn)
    for t in tramos:
        if t.get("tipo") != "internacional":
            continue
        extras = T.partes_destino(t.get("destino") or "")[1]
        t["clase"] = "LEITO" if "LEITO" in extras else "CAMA" if "CAMA" in extras else ""
        if not T.es_argentina(t.get("origen") or ""):
            continue
        try:
            dia = date.fromisoformat(t["fecha"]).isoweekday()
        except ValueError:
            continue
        p = regreso_de(prog, dia, t["hora"], t.get("origen")) if prog else None
        hora_eq = t["hora"]
        if p:
            t["llega"] = queda_en(p)
            hora_eq = HORA_EQUIV.get(p.get("llegada") or "", t["hora"])
            if not t["clase"]:
                t["clase"] = p.get("clase") or ""
            t["programa"] = LLEGADAS.get(p.get("llegada") or "", "")
        try:
            base = datetime.fromisoformat(f"{t['fecha']}T{T.normalizar_hora(hora_eq) or '00:00'}")
            t["llegada"] = (base + timedelta(hours=viaje)).isoformat(timespec="minutes")
        except ValueError:
            pass
    return tramos


# ════════════════════════════════════════════════════════════════════════════
# ARMAR EL DÍA Y COMPLETAR LAS SALIDAS DE ACÁ POR ORDEN DE LLEGADA
# ════════════════════════════════════════════════════════════════════════════

def armar_desde_programa(fecha, quien=""):
    import trafico as T
    dia = date.fromisoformat(fecha).isoweekday()
    conn = get_connection()
    try:
        prog = [r for r in filas(conn, "internacional") if r["dia"] == dia]
        if not prog:
            return False, f"La programación no tiene salidas los {DIAS_L[dia]}."
        dia_id = T.crear_dia(fecha, conn, "internacional")
        T._bloquear_dia(conn, dia_id)
        T.vaciar_dia(conn, dia_id)
        cur = conn.execute("""INSERT INTO trafico_bloques (dia_id, orden, nombre, nota_ida, nota_regreso,
                                reserva_ida_coche, reserva_ida_trip, reserva_regreso_coche, reserva_regreso_trip)
                              VALUES (?,0,'BUENOS AIRES','','','','','','')""", (dia_id,))
        bid = cur.lastrowid or conn.execute("SELECT MAX(id) AS m FROM trafico_bloques WHERE dia_id=?", (dia_id,)).fetchone()["m"]
        for r in sorted(prog, key=lambda x: (x["lado"] != "ida", x["hora"], x["orden"], x["id"])):
            conn.execute("""INSERT INTO trafico_salidas (dia_id, bloque_id, lado, hora, destino, coche, trip1, trip2, nota)
                            VALUES (?,?,?,?,?,'','','','')""", (dia_id, bid, r["lado"], r["hora"], texto_destino(r)))
        T._marcar_modificado(conn, dia_id)
        conn.commit()
        return True, f"Día armado con la programación de los {DIAS_L[dia]}: {len(prog)} salidas."
    finally:
        conn.close()


def _encadenada(prog_dia, hora):
    """La ida de la programación cuya misma unidad sigue a esta hora (o None)."""
    m = _min(hora)
    for r in prog_dia:
        if r["lado"] == "ida" and r.get("sigue") and m is not None and abs((_min(r["sigue"]) or 0) - m) <= 2:
            return r
    return None


def completar_idas(fecha, simular=False):
    """Pone coche en las salidas de acá del internacional que no tienen:
      - la que sigue de otra (0:20 CDE + 12:30) lleva la misma unidad;
      - de Villarrica, la que quedó de reserva en Villarrica;
      - de Asunción (y de CDE), la primera que llegó a Asunción y ya está
        (el coche cama con un coche cama, si hay).
    Devuelve cuántas llenó."""
    import trafico as T
    conn = get_connection()
    try:
        dia = T._dia_por_fecha(conn, fecha, "internacional")
        if not dia:
            return 0
        dow = date.fromisoformat(fecha).isoweekday()
        prog_dia = [r for r in filas(conn, "internacional") if r["dia"] == dow]
        salidas = [dict(x) for x in conn.execute("""SELECT s.*, b.nombre AS corredor FROM trafico_salidas s
                                                    JOIN trafico_bloques b ON b.id=s.bloque_id
                                                    WHERE s.dia_id=? ORDER BY s.hora, s.id""", (dia["id"],)).fetchall()]
        tramos = T._tramos_recientes(conn, fecha)
        ya_hoy = {}
        for s in salidas:
            c = T.limpiar(s["coche"])
            if c.isdigit():
                ya_hoy.setdefault(c, []).append(s["hora"] or "")
        vacias = [s for s in salidas if s["lado"] == "ida" and not T.limpiar(s["coche"]) and s["hora"]]
        if not vacias:
            return 0
        idas_hoy = [s for s in salidas if s["lado"] == "ida"]
        llenadas, tomados = 0, set()
        for s in sorted(vacias, key=lambda x: (x["hora"], x["id"])):
            o, d = T.tramo(s["destino"], "ida", s["corredor"], "internacional")
            coche, t1, t2 = "", "", ""
            # 1) Encadenada: la misma unidad de la salida anterior
            ant = _encadenada(prog_dia, s["hora"])
            if ant:
                previa = next((x for x in idas_hoy if abs((_min(x["hora"]) or 0) - (_min(ant["hora"]) or 0)) <= 2
                               and x["id"] != s["id"]), None)
                c = T.limpiar(previa["coche"]) if previa else ""
                if c.isdigit():
                    coche, t1, t2 = c, previa["trip1"] or "", previa["trip2"] or ""
                elif previa:
                    continue          # se completa cuando tenga coche la primera
            if not coche:
                donde = T.ubicaciones(tramos, fecha, s["hora"])
                # La de CDE tiene que salir antes de Asunción para estar allá a la hora
                antes = HORAS_ANTES.get(o, 0)
                ahora = (datetime.fromisoformat(f"{fecha}T{s['hora']}") - timedelta(hours=antes)).isoformat(timespec="minutes")
                clase = "CAMA" if any(x in T.partes_destino(s["destino"])[1] for x in ("CAMA", "LEITO")) else ""
                cands = []
                for c, u in donde.items():
                    if c in tomados or u.get("tipo") != "internacional" or T.es_argentina(u.get("lugar") or ""):
                        continue
                    if s["hora"] in ya_hoy.get(c, []) or any(h > s["hora"] for h in ya_hoy.get(c, []) if h):
                        continue
                    lugar = u.get("lugar") or ""
                    if o == "VILLARRICA":
                        if lugar != "VILLARRICA":
                            continue
                    elif lugar != "ASU":
                        continue
                    lleg = u.get("llegada") or f"{u['desde_fecha']}T{u['desde_hora']}"
                    if lleg > ahora:
                        continue      # todavía viene en viaje
                    es_cama = bool(u.get("clase"))
                    cands.append(((0 if es_cama == bool(clase) else 1), lleg, c, u))
                if not cands:
                    continue
                cands.sort(key=lambda x: (x[0], x[1], x[2]))
                _, _, coche, u = cands[0]
                t1, t2 = u.get("trip1") or "", u.get("trip2") or ""
            tomados.add(coche)
            ya_hoy.setdefault(coche, []).append(s["hora"])
            s["coche"] = coche
            if not simular:
                conn.execute("UPDATE trafico_salidas SET coche=? WHERE id=?", (coche, s["id"]))
            tramos.append({"id": s["id"], "fecha": fecha, "hora": s["hora"], "coche": coche, "origen": o, "llega": d,
                           "destino": s["destino"], "corredor": s["corredor"], "tipo": "internacional",
                           "trip1": t1, "trip2": t2})
            tramos.sort(key=lambda t: (t["fecha"], t["hora"], t["id"]))
            llenadas += 1
        if not simular and llenadas:
            T._marcar_modificado(conn, dia["id"])
            conn.commit()
        return llenadas
    finally:
        conn.close()


def orden_de_llegada(fecha, hora="23:59"):
    """Las unidades del internacional en Asunción y en Villarrica, en el orden
    en que llegaron (la primera es la que sale primero)."""
    import trafico as T
    conn = get_connection()
    try:
        tramos = T._tramos_recientes(conn, fecha)
    finally:
        conn.close()
    donde = T.ubicaciones(tramos, fecha, hora)
    out = {"ASU": [], "VILLARRICA": [], "viajando": []}
    ahora = f"{fecha}T{hora}"
    for c, u in donde.items():
        if u.get("tipo") != "internacional" or T.es_argentina(u.get("lugar") or ""):
            continue
        lleg = u.get("llegada") or f"{u['desde_fecha']}T{u['desde_hora']}"
        x = {"coche": c, "llegada": lleg, "desde_fecha": u["desde_fecha"], "desde_hora": u["desde_hora"],
             "destino": u["destino"], "clase": u.get("clase") or ""}
        if lleg > ahora:
            out["viajando"].append(x)
        elif u.get("lugar") in ("ASU", "VILLARRICA"):
            out[u["lugar"]].append(x)
    for k in out:
        out[k].sort(key=lambda x: (x["llegada"], x["coche"]))
    return out


# ════════════════════════════════════════════════════════════════════════════
# RUTAS
# ════════════════════════════════════════════════════════════════════════════

def _quien():
    return session.get("nombre") or session.get("usuario") or ""


def _puede_ver():
    return session.get("rol") in ("admin", "taller", "auditor")


def _puede_editar():
    return session.get("rol") in ("admin", "taller")


def _respuesta(conn):
    prog = filas(conn, "internacional")
    return {"ok": True, "filas": prog, "revision": revisar(prog), "viaje_horas": viaje_horas(conn),
            "llegadas": LLEGADAS, "dias": DIAS, "puede_editar": _puede_editar()}


@bp_programa.route("/api/trafico/programa", methods=["GET"])
def api_programa():
    if not _puede_ver():
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    conn = get_connection()
    try:
        return jsonify(_respuesta(conn))
    finally:
        conn.close()


@bp_programa.route("/api/trafico/programa", methods=["PUT", "POST"])
def api_programa_guardar():
    if not _puede_editar():
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    import trafico as T
    d = request.get_json(silent=True) or {}
    nuevas = []
    for k, x in enumerate(d.get("filas") or []):
        try:
            dia = int(x.get("dia"))
        except (TypeError, ValueError):
            continue
        lado = x.get("lado")
        hora = T.normalizar_hora(x.get("hora"))
        if not (1 <= dia <= 7) or lado not in ("ida", "regreso"):
            continue
        if not hora:
            return jsonify({"ok": False, "msg": f"Falta la hora de una salida del {DIAS_L[dia]}"}), 400
        destino = " ".join(str(x.get("destino") or "").upper().split())[:80]
        if not destino:
            return jsonify({"ok": False, "msg": f"Falta el tramo de las {hora} del {DIAS_L[dia]}"}), 400
        clase = str(x.get("clase") or "").upper()
        clase = clase if clase in CLASES else ""
        sigue = T.normalizar_hora(x.get("sigue")) if lado == "ida" else ""
        try:
            vd = int(x.get("vuelve_dia")) if lado == "ida" and x.get("vuelve_dia") and not sigue else None
        except (TypeError, ValueError):
            vd = None
        vh = T.normalizar_hora(x.get("vuelve_hora")) if vd else ""
        lleg = x.get("llegada") if lado == "regreso" and x.get("llegada") in LLEGADAS else ""
        nota = " ".join(str(x.get("nota") or "").split())[:160]
        nuevas.append((dia, lado, hora, destino, clase, sigue or "", vd, vh or "", lleg, nota, k))
    conn = get_connection()
    try:
        conn.execute("DELETE FROM trafico_programa WHERE tipo='internacional'")
        for f in nuevas:
            conn.execute("""INSERT INTO trafico_programa (tipo, dia, lado, hora, destino, clase, sigue,
                                vuelve_dia, vuelve_hora, llegada, nota, orden)
                            VALUES ('internacional',?,?,?,?,?,?,?,?,?,?,?)""", f)
        if d.get("viaje_horas") not in (None, ""):
            try:
                vh = max(1, min(48, int(float(d["viaje_horas"]))))
                conn.execute("""INSERT INTO trafico_config (clave, valor) VALUES ('viaje_horas_int', ?)
                                ON CONFLICT (clave) DO UPDATE SET valor=excluded.valor""", (str(vh),))
            except (TypeError, ValueError):
                pass
        conn.commit()
        n = aplicar(conn, "internacional", _quien())
        try:
            from database import registrar_auditoria
            registrar_auditoria(usuario=_quien() or "?", rol=session.get("rol") or "",
                                accion=f"Cambió la programación semanal del internacional ({len(nuevas)} salidas, {n} rotaciones)",
                                categoria="Tráfico", detalle="")
        except Exception:
            pass
        return jsonify({**_respuesta(conn), "rotaciones": n})
    except Exception as e:
        _rollback(conn)
        return jsonify({"ok": False, "msg": f"No se pudo guardar: {e}"}), 500
    finally:
        conn.close()


@bp_programa.route("/api/trafico/dia/<fecha>/programa", methods=["POST"])
def api_armar_desde_programa(fecha):
    if not _puede_editar():
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    import trafico as T
    fecha = T._fecha_ok(fecha)
    if not fecha:
        return jsonify({"ok": False, "msg": "Fecha inválida"}), 400
    ok, msg = armar_desde_programa(fecha, _quien())
    if not ok:
        return jsonify({"ok": False, "msg": msg}), 400
    regresos = idas = 0
    if (request.get_json(silent=True) or {}).get("completar", True):
        regresos = T.completar_con_ubicacion(fecha, tipo="internacional")
        idas = completar_idas(fecha)
    T._auditar(f"Armó el internacional del {fecha} desde la programación semanal ({regresos} regresos y {idas} salidas con coche)")
    return T._respuesta_dia(fecha, "internacional", completadas=regresos + idas,
                            completadas_regresos=regresos, completadas_idas=idas, msg=msg)


@bp_programa.route("/api/trafico/orden_llegada", methods=["GET"])
def api_orden_llegada():
    if not _puede_ver():
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    import trafico as T
    fecha = T._fecha_ok(request.args.get("fecha") or "") or date.today().isoformat()
    hora = T.normalizar_hora(request.args.get("hora") or "") or "23:59"
    return jsonify({"ok": True, "fecha": fecha, "hora": hora, **orden_de_llegada(fecha, hora)})
