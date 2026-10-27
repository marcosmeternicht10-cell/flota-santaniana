"""
ot_horas.py — La hora de inicio y fin de cada técnico en cada OT (La Santaniana)

En la OT, cada técnico que trabaja en ella tiene sus horas: cuándo empezó y
cuándo terminó. Puede tener varias tandas (empezó, cortó y siguió otro día:
lo que en la hoja de papel es el «intermedio»). Con eso se sabe cuántas horas
llevó la OT y cuántas trabajó cada uno.

  · Los técnicos de la OT salen de los trabajos (el número que se pone en cada
    ítem) y además se puede agregar a otro.
  · «Empezó ahora» abre una tanda con la hora actual y «Terminó ahora» la
    cierra; también se cargan o corrigen a mano.
  · Si el mismo técnico tiene horas que se pisan con otra OT, se avisa (no se
    bloquea: puede pasar que ayude en dos coches a la vez).

Enganche en app.py:
    from ot_horas import bp_ot_horas, init_ot_horas
    init_ot_horas()
    app.register_blueprint(bp_ot_horas)
"""

import re
from datetime import datetime

from flask import Blueprint, jsonify, request, session

from db_compat import get_connection, USE_POSTGRES
from hora_local import ahora_iso

bp_ot_horas = Blueprint("ot_horas", __name__)

PK = "SERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"
MAX_HORAS_TANDA = 24          # una tanda más larga es un error de carga


def _rollback(conn):
    try:
        conn.rollback()
    except Exception:
        pass


def init_ot_horas():
    conn = get_connection()
    for sql in (f"""CREATE TABLE IF NOT EXISTS ot_horas (
                        id {PK},
                        ot_id INTEGER NOT NULL,
                        personal_id INTEGER NOT NULL,
                        inicio TEXT NOT NULL,
                        fin TEXT DEFAULT '',
                        nota TEXT DEFAULT '',
                        cargado_por TEXT DEFAULT '',
                        cargado_el TEXT DEFAULT '')""",
                "CREATE INDEX IF NOT EXISTS ix_oth_ot ON ot_horas (ot_id)",
                "CREATE INDEX IF NOT EXISTS ix_oth_pers ON ot_horas (personal_id)"):
        try:
            conn.execute(sql)
            conn.commit()
        except Exception:
            _rollback(conn)
    conn.close()


class Error(Exception):
    pass


def _ahora():
    return ahora_iso()[:16]


def _fh(v, campo):
    """'2026-10-27T14:05' (o con espacio, o con segundos) → '2026-10-27T14:05'."""
    t = str(v or "").strip().replace(" ", "T")[:16]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", t):
        raise Error(f"Falta la fecha y hora de {campo}")
    try:
        datetime.fromisoformat(t)
    except ValueError:
        raise Error(f"La fecha u hora de {campo} no es válida")
    return t


def _horas(inicio, fin):
    if not inicio or not fin:
        return 0.0
    return round((datetime.fromisoformat(fin) - datetime.fromisoformat(inicio)).total_seconds() / 3600, 2)


def _validar(inicio, fin):
    if fin:
        if fin <= inicio:
            raise Error("El fin tiene que ser después del inicio")
        if _horas(inicio, fin) > MAX_HORAS_TANDA:
            raise Error(f"Más de {MAX_HORAS_TANDA} horas seguidas: revisá las fechas (si cortó y siguió otro día, cargá dos tandas)")
    if inicio > _ahora() and inicio[:10] > _ahora()[:10]:
        raise Error("El inicio no puede ser de un día que todavía no llegó")


def _persona(conn, pid):
    r = conn.execute("SELECT id, numero, nombre, puesto, activo FROM taller_personal WHERE id=?", (int(pid),)).fetchone()
    if not r:
        raise Error("Ese técnico no está en la lista del personal")
    return dict(r)


def _ot_ok(conn, ot_id):
    r = conn.execute("SELECT id, estado FROM ordenes_trabajo WHERE id=?", (int(ot_id),)).fetchone()
    if not r:
        raise Error("La OT no existe")
    return dict(r)


def _pisadas(conn, pid, inicio, fin, salvo=None):
    """Otras tandas del mismo técnico (en otras OT) que se pisan con esta."""
    fin_c = fin or _ahora()
    out = []
    for r in conn.execute("SELECT * FROM ot_horas WHERE personal_id=?", (int(pid),)).fetchall():
        r = dict(r)
        if salvo and r["id"] == salvo:
            continue
        f2 = r["fin"] or _ahora()
        if r["inicio"] < fin_c and inicio < f2:
            out.append(r)
    return out


def horas_de_ot(ot_id):
    conn = get_connection()
    try:
        ot = _ot_ok(conn, ot_id)
        # Los técnicos de la OT: los de los trabajos y los que ya tienen horas
        en_items = {r["personal_id"]: r["n"] for r in conn.execute(
            """SELECT ip.personal_id, COUNT(*) AS n FROM ot_item_personal ip
               JOIN ot_items i ON i.id = ip.item_id WHERE i.ot_id=? GROUP BY ip.personal_id""", (ot["id"],)).fetchall()}
        tandas = [dict(r) for r in conn.execute("SELECT * FROM ot_horas WHERE ot_id=? ORDER BY inicio, id",
                                                (ot["id"],)).fetchall()]
        ids = set(en_items) | {t["personal_id"] for t in tandas}
        gente = {}
        for pid in ids:
            r = conn.execute("SELECT id, numero, nombre, puesto, activo FROM taller_personal WHERE id=?", (pid,)).fetchone()
            if r:
                gente[pid] = dict(r)
        # Avisos de horas que se pisan con otras OT
        avisos = {}
        for t in tandas:
            otras = [x for x in _pisadas(conn, t["personal_id"], t["inicio"], t["fin"], t["id"]) if x["ot_id"] != ot["id"]]
            if otras:
                avisos[t["id"]] = sorted({x["ot_id"] for x in otras})
    finally:
        conn.close()
    out = []
    for pid, p in gente.items():
        mis = [t for t in tandas if t["personal_id"] == pid]
        lista = [{"id": t["id"], "inicio": t["inicio"], "fin": t["fin"] or "", "nota": t["nota"] or "",
                  "horas": _horas(t["inicio"], t["fin"]), "abierta": not t["fin"],
                  "pisa_ots": avisos.get(t["id"], [])} for t in mis]
        abierta = next((t for t in lista if t["abierta"]), None)
        out.append({"personal_id": pid, "numero": p["numero"], "nombre": p["nombre"], "puesto": p["puesto"] or "",
                    "activo": bool(p["activo"]), "trabajos": en_items.get(pid, 0), "tandas": lista,
                    "horas": round(sum(t["horas"] for t in lista), 2),
                    "trabajando_desde": abierta["inicio"] if abierta else ""})
    out.sort(key=lambda x: (x["trabajando_desde"] == "", x["numero"]))
    return {"ot_id": ot["id"], "estado": ot["estado"], "tecnicos": out, "ahora": _ahora(),
            "horas": round(sum(x["horas"] for x in out), 2),
            "trabajando": sum(1 for x in out if x["trabajando_desde"])}


def agregar(ot_id, d, quien=""):
    conn = get_connection()
    try:
        _ot_ok(conn, ot_id)
        p = _persona(conn, d.get("personal_id"))
        inicio = _fh(d.get("inicio"), "inicio")
        fin = _fh(d.get("fin"), "fin") if d.get("fin") else ""
        _validar(inicio, fin)
        if not fin and conn.execute("SELECT 1 FROM ot_horas WHERE ot_id=? AND personal_id=? AND COALESCE(fin,'')=''",
                                    (int(ot_id), p["id"])).fetchone():
            raise Error(f"N°{p['numero']} ya tiene una tanda sin terminar en esta OT: cerrala primero")
        conn.execute("""INSERT INTO ot_horas (ot_id, personal_id, inicio, fin, nota, cargado_por, cargado_el)
                        VALUES (?,?,?,?,?,?,?)""", (int(ot_id), p["id"], inicio, fin, str(d.get("nota") or "")[:120],
                                                    quien[:80], ahora_iso()))
        conn.commit()
        return p
    finally:
        conn.close()


def empezar(ot_id, d, quien=""):
    return agregar(ot_id, {"personal_id": d.get("personal_id"), "inicio": _ahora()}, quien)


def terminar(ot_id, d, quien=""):
    conn = get_connection()
    try:
        p = _persona(conn, d.get("personal_id"))
        r = conn.execute("""SELECT * FROM ot_horas WHERE ot_id=? AND personal_id=? AND COALESCE(fin,'')=''
                            ORDER BY inicio DESC""", (int(ot_id), p["id"])).fetchone()
        if not r:
            raise Error(f"N°{p['numero']} no tiene una tanda empezada en esta OT")
        fin = _ahora()
        if fin <= r["inicio"]:
            raise Error("Empezó hace menos de un minuto: esperá un poco o cargalo a mano")
        _validar(r["inicio"], fin)
        conn.execute("UPDATE ot_horas SET fin=? WHERE id=?", (fin, r["id"]))
        conn.commit()
        return p
    finally:
        conn.close()


def editar(hid, d):
    conn = get_connection()
    try:
        r = conn.execute("SELECT * FROM ot_horas WHERE id=?", (int(hid),)).fetchone()
        if not r:
            raise Error("Esa tanda ya no existe")
        inicio = _fh(d.get("inicio", r["inicio"]), "inicio")
        fin_txt = d.get("fin", r["fin"])
        fin = _fh(fin_txt, "fin") if fin_txt else ""
        _validar(inicio, fin)
        conn.execute("UPDATE ot_horas SET inicio=?, fin=? WHERE id=?", (inicio, fin, r["id"]))
        conn.commit()
        return dict(r)
    finally:
        conn.close()


def borrar(hid):
    conn = get_connection()
    try:
        r = conn.execute("SELECT * FROM ot_horas WHERE id=?", (int(hid),)).fetchone()
        if not r:
            raise Error("Esa tanda ya no existe")
        conn.execute("DELETE FROM ot_horas WHERE id=?", (r["id"],))
        conn.commit()
        return dict(r)
    finally:
        conn.close()


def horas_por_persona(desde, hasta):
    """{personal_id: horas} de las tandas cerradas que empiezan en el período
    (para Personal de taller)."""
    conn = get_connection()
    try:
        filas = conn.execute("""SELECT personal_id, inicio, fin FROM ot_horas
                                WHERE COALESCE(fin,'') <> '' AND inicio >= ? AND inicio <= ?""",
                             (desde, hasta + "T23:59")).fetchall()
    except Exception:
        _rollback(conn)
        filas = []
    finally:
        conn.close()
    out = {}
    for r in filas:
        out[r["personal_id"]] = round(out.get(r["personal_id"], 0) + _horas(r["inicio"], r["fin"]), 2)
    return out


# ════════════════════════════════════════════════════════════════════════════
# RUTAS
# ════════════════════════════════════════════════════════════════════════════

def _puede_ver():
    return session.get("rol") in ("admin", "taller", "compras", "auditor")


def _puede_editar():
    return session.get("rol") in ("admin", "taller", "compras")


def _quien():
    return session.get("nombre") or session.get("usuario") or ""


def _auditar(accion, detalle=""):
    try:
        from database import registrar_auditoria
        registrar_auditoria(usuario=_quien() or "?", rol=session.get("rol") or "", accion=accion,
                            categoria="OT", detalle=str(detalle)[:200])
    except Exception:
        pass


def _resp(ot_id, msg=""):
    return jsonify({"ok": True, "msg": msg, **horas_de_ot(ot_id)})


@bp_ot_horas.route("/api/ots/<int:ot_id>/horas", methods=["GET"])
def api_horas(ot_id):
    if not _puede_ver():
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    try:
        return jsonify({"ok": True, **horas_de_ot(ot_id)})
    except Error as e:
        return jsonify({"ok": False, "msg": str(e)}), 404
    except Exception as e:
        # Una conexión cortada o la base ocupada: se avisa (la pantalla reintenta sola)
        import traceback
        traceback.print_exc()
        return jsonify({"ok": False, "msg": f"Error del servidor ({type(e).__name__})"}), 500


@bp_ot_horas.route("/api/ots/<int:ot_id>/horas/<accion>", methods=["POST"])
def api_horas_accion(ot_id, accion):
    if not _puede_editar():
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    d = request.get_json(silent=True) or {}
    try:
        if accion == "empezar":
            p = empezar(ot_id, d, _quien())
            msg = f"N°{p['numero']} empezó a las {_ahora()[11:16]}"
        elif accion == "terminar":
            p = terminar(ot_id, d, _quien())
            msg = f"N°{p['numero']} terminó a las {_ahora()[11:16]}"
        elif accion == "agregar":
            p = agregar(ot_id, d, _quien())
            msg = f"Horas de N°{p['numero']} cargadas"
        else:
            return jsonify({"ok": False, "msg": "No sé qué hacer con eso"}), 400
    except Error as e:
        return jsonify({"ok": False, "msg": str(e)}), 400
    _auditar(f"Horas en OT #{ot_id}", msg)
    return _resp(ot_id, msg)


@bp_ot_horas.route("/api/ot_horas/<int:hid>", methods=["PATCH", "DELETE"])
def api_tanda(hid):
    if not _puede_editar():
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    try:
        if request.method == "DELETE":
            r = borrar(hid)
            msg = "Tanda borrada"
        else:
            r = editar(hid, request.get_json(silent=True) or {})
            msg = "Horas corregidas"
    except Error as e:
        return jsonify({"ok": False, "msg": str(e)}), 400
    _auditar(f"Horas en OT #{r['ot_id']}", msg)
    return _resp(r["ot_id"], msg)
