"""
trafico_patron.py — Cuántas salidas lleva cada día de la semana (La Santaniana)

El internacional no es igual todos los días (lo que contó Marcos, oct 2026):

    De acá (Paraguay):  2 salidas de Asunción todos los días; los martes y
                        los viernes se suman las 2 de Villarrica → 4.
    De allá (Bs. As.):  2 regresos por día; los miércoles y los domingos,
                        4 (vuelven los de Villarrica).

Con eso el tráfico del día avisa si falta alguna salida (un martes armado
desde el lunes queda sin las de Villarrica) y el día vacío se arma desde el
mismo día de la semana pasada, que trae las salidas que corresponden.

El patrón se cambia desde Tráfico → ⋯ → Salidas por día (temporada, feriados).

Enganche en app.py:
    from trafico_patron import bp_patron, init_trafico_patron
    init_trafico_patron()
    app.register_blueprint(bp_patron)
"""

from datetime import date

from flask import Blueprint, request, jsonify, session
from db_compat import get_connection, USE_POSTGRES

bp_patron = Blueprint("trafico_patron", __name__)

PK = "SERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"
LADOS = ("ida", "regreso")
DIAS = {1: "LUNES", 2: "MARTES", 3: "MIÉRCOLES", 4: "JUEVES", 5: "VIERNES", 6: "SÁBADO", 7: "DOMINGO"}

# (día 1=lunes … 7=domingo, salidas de acá, nota, regresos de allá, nota)
PATRON_INICIAL_INT = [
    (1, 2, "de Asunción", 2, ""),
    (2, 4, "2 de Asunción y 2 de Villarrica", 2, ""),
    (3, 2, "de Asunción", 4, "vuelven los de Villarrica del martes"),
    (4, 2, "de Asunción", 2, ""),
    (5, 4, "2 de Asunción y 2 de Villarrica", 2, ""),
    (6, 2, "de Asunción", 2, ""),
    (7, 2, "de Asunción", 4, "vuelven los de Villarrica del viernes"),
]


def _ahora():
    try:
        from hora_local import ahora_iso
        return ahora_iso()
    except Exception:
        from datetime import datetime
        return datetime.now().isoformat(timespec="seconds")


def init_trafico_patron():
    conn = get_connection()
    try:
        conn.execute(f"""CREATE TABLE IF NOT EXISTS trafico_patron (
            id {PK},
            tipo TEXT NOT NULL,
            dia INTEGER NOT NULL,              -- 1=lunes … 7=domingo
            lado TEXT NOT NULL,                -- ida (de acá) | regreso (de allá)
            cantidad INTEGER DEFAULT 0,        -- 0 = ese día no se controla
            nota TEXT DEFAULT '',
            actualizado_el TEXT DEFAULT '',
            actualizado_por TEXT DEFAULT '',
            UNIQUE (tipo, dia, lado))""")
        conn.commit()
        conn.execute("""CREATE TABLE IF NOT EXISTS trafico_semillas (
            clave TEXT PRIMARY KEY, aplicada_el TEXT DEFAULT '')""")
        conn.commit()
        # El del internacional entra una sola vez (si después lo cambian, queda lo de ellos)
        if not conn.execute("SELECT 1 FROM trafico_semillas WHERE clave='patron_internacional'").fetchone():
            for dia, ida, nota_ida, reg, nota_reg in PATRON_INICIAL_INT:
                for lado, cant, nota in (("ida", ida, nota_ida), ("regreso", reg, nota_reg)):
                    conn.execute("""INSERT INTO trafico_patron (tipo, dia, lado, cantidad, nota, actualizado_el, actualizado_por)
                                    VALUES ('internacional',?,?,?,?,?,?) ON CONFLICT (tipo, dia, lado) DO NOTHING""",
                                 (dia, lado, cant, nota, _ahora(), "lo que contó Marcos"))
            conn.execute("INSERT INTO trafico_semillas (clave, aplicada_el) VALUES (?, ?) ON CONFLICT (clave) DO NOTHING",
                         ("patron_internacional", _ahora()))
            conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        conn.close()


def patron(tipo, conn=None):
    """{dia: {lado: {"cantidad", "nota"}}} del tráfico (vacío si no tiene)."""
    propia = conn is None
    conn = conn or get_connection()
    try:
        out = {}
        for r in conn.execute("SELECT dia, lado, cantidad, nota FROM trafico_patron WHERE tipo=? ORDER BY dia",
                              (tipo,)).fetchall():
            out.setdefault(int(r["dia"]), {})[r["lado"]] = {"cantidad": int(r["cantidad"] or 0), "nota": r["nota"] or ""}
        return out
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return {}
    finally:
        if propia:
            conn.close()


def control_del_dia(fecha, tipo, bloques):
    """Cuántas salidas de acá y regresos de allá lleva el día y cuántos hay
    cargados (sin contar los refuerzos). None si el tráfico no tiene patrón."""
    p = patron(tipo)
    if not p:
        return None
    dia = date.fromisoformat(fecha).isoweekday()
    esperado = p.get(dia) or {}
    out = {"dia": DIAS[dia], "dia_n": dia}
    algo = False
    for lado in LADOS:
        e = esperado.get(lado) or {}
        hay = sum(1 for b in bloques or [] for s in b.get(lado) or []
                  if "REFUERZO" not in (s.get("destino_extras") or []))
        cant = int(e.get("cantidad") or 0)
        out[lado] = {"esperadas": cant, "hay": hay, "nota": e.get("nota") or "",
                     "faltan": max(0, cant - hay), "sobran": max(0, hay - cant) if cant else 0}
        algo = algo or cant > 0
    return out if algo else None


def esperado_del_dia(fecha, tipo):
    """Lo que lleva ese día de la semana (para el día vacío)."""
    p = patron(tipo)
    if not p:
        return None
    dia = date.fromisoformat(fecha).isoweekday()
    e = p.get(dia) or {}
    if not any((e.get(l) or {}).get("cantidad") for l in LADOS):
        return None
    return {"dia": DIAS[dia], **{l: e.get(l) or {"cantidad": 0, "nota": ""} for l in LADOS}}


# ════════════════════════════════════════════════════════════════════════════
# RUTAS
# ════════════════════════════════════════════════════════════════════════════

def _tipo():
    t = str(request.args.get("tipo") or (request.get_json(silent=True) or {}).get("tipo") or "").lower()
    return t if t in ("nacional", "internacional") else "internacional"


@bp_patron.route("/api/trafico/patron", methods=["GET"])
def api_patron():
    if session.get("rol") not in ("admin", "taller", "auditor"):
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    tipo = _tipo()
    p = patron(tipo)
    dias = [{"dia": d, "nombre": DIAS[d], **{l: (p.get(d) or {}).get(l) or {"cantidad": 0, "nota": ""} for l in LADOS}}
            for d in range(1, 8)]
    return jsonify({"ok": True, "tipo": tipo, "dias": dias,
                    "puede_editar": session.get("rol") in ("admin", "taller")})


@bp_patron.route("/api/trafico/patron", methods=["PUT", "POST"])
def api_patron_guardar():
    if session.get("rol") not in ("admin", "taller"):
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    d = request.get_json(silent=True) or {}
    tipo = _tipo()
    quien = session.get("nombre") or session.get("usuario") or ""
    conn = get_connection()
    try:
        for x in d.get("dias") or []:
            try:
                dia = int(x.get("dia"))
            except (TypeError, ValueError):
                continue
            if not 1 <= dia <= 7:
                continue
            for lado in LADOS:
                if lado not in x:
                    continue
                v = x[lado] or {}
                try:
                    cant = max(0, min(30, int(v.get("cantidad") or 0)))
                except (TypeError, ValueError):
                    return jsonify({"ok": False, "msg": f"Revisá el número del {DIAS[dia].lower()}"}), 400
                nota = " ".join(str(v.get("nota") or "").split())[:80]
                fila = conn.execute("SELECT id FROM trafico_patron WHERE tipo=? AND dia=? AND lado=?",
                                    (tipo, dia, lado)).fetchone()
                if fila:
                    conn.execute("""UPDATE trafico_patron SET cantidad=?, nota=?, actualizado_el=?, actualizado_por=?
                                    WHERE id=?""", (cant, nota, _ahora(), quien, fila["id"]))
                else:
                    conn.execute("""INSERT INTO trafico_patron (tipo, dia, lado, cantidad, nota, actualizado_el, actualizado_por)
                                    VALUES (?,?,?,?,?,?,?)""", (tipo, dia, lado, cant, nota, _ahora(), quien))
        conn.commit()
    finally:
        conn.close()
    try:
        from database import registrar_auditoria
        registrar_auditoria(usuario=quien or "?", rol=session.get("rol") or "", accion=f"Cambió las salidas por día del tráfico {tipo}",
                            categoria="Tráfico", detalle="")
    except Exception:
        pass
    return api_patron()
