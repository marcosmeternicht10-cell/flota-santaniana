"""Programación semanal de servicios internacionales de La Santaniana.

Plantilla recurrente de rotación: representa las reglas de continuidad entre
servicios, permite asociar una unidad real a cada rotación y propaga esa unidad
a todos los movimientos conectados. No crea ni publica tráficos diarios por sí
sola; funciona como patrón operativo editable por Tráfico/Administración.
"""
import csv
import io
from datetime import datetime

from flask import Blueprint, Response, jsonify, render_template, request, session
from db_compat import get_connection

bp_programacion_semanal = Blueprint("programacion_semanal", __name__)

DIAS = [
    {"id": 1, "nombre": "Lunes"},
    {"id": 2, "nombre": "Martes"},
    {"id": 3, "nombre": "Miércoles"},
    {"id": 4, "nombre": "Jueves"},
    {"id": 5, "nombre": "Viernes"},
    {"id": 6, "nombre": "Sábado"},
    {"id": 7, "nombre": "Domingo"},
]

REGLAS = [
    {
        "titulo": "Salida desde Asunción",
        "detalle": "Las unidades disponibles se asignan por orden de llegada: la primera que llega es la primera que sale.",
    },
    {
        "titulo": "Llegadas desde Buenos Aires",
        "detalle": "Cuando coinciden servicios del mismo día, el de Buenos Aires 17:00 llega antes que el de las 18:00.",
    },
    {
        "titulo": "La Plata 13:30",
        "detalle": "No llega a Asunción; termina en Villarrica y queda de reserva.",
    },
    {
        "titulo": "La Plata 13:35 — leito",
        "detalle": "Llega a Asunción junto con el servicio de Buenos Aires 17:00.",
    },
    {
        "titulo": "La Noria 14:20",
        "detalle": "Termina en Villarrica y vuelve en lastre a Asunción; llega después que Buenos Aires 18:00.",
    },
    {
        "titulo": "Orden operativo de llegada a Asunción",
        "detalle": "Primero: Buenos Aires 17:00 y La Plata 13:35 leito. Después: Buenos Aires 18:00. Último: La Noria 14:20, con regreso en lastre desde Villarrica.",
    },
]

ROTACIONES = [
    {"id": "SAB_CDE", "nombre": "Sábado CDE 00:20 + ASU 12:30", "detalle": "Misma unidad; vuelve lunes 17:00 desde Buenos Aires."},
    {"id": "DOM_ASU_0900", "nombre": "Domingo ASU 09:00", "detalle": "Vuelve lunes 18:00 desde Buenos Aires."},
    {"id": "LUN_ASU_0020", "nombre": "Lunes ASU 00:20 cama", "detalle": "Vuelve martes 17:00 desde Buenos Aires."},
    {"id": "LUN_ASU_0900", "nombre": "Lunes ASU 09:00", "detalle": "Miércoles La Plata 13:30; queda en Villarrica y sale viernes 09:30; vuelve sábado 18:00 desde Buenos Aires."},
    {"id": "LUN_ASU_1230", "nombre": "Lunes ASU 12:30 cama", "detalle": "Vuelve martes 17:00 desde Buenos Aires."},
    {"id": "DOM_CDE", "nombre": "Domingo CDE 00:20 + ASU 12:30", "detalle": "Misma unidad; vuelve martes 18:00 desde Buenos Aires."},
    {"id": "MAR_VCA_0020", "nombre": "Martes ASU 00:20 + Villarrica 09:35", "detalle": "Misma unidad; queda de reserva en Buenos Aires y vuelve jueves 18:00."},
    {"id": "MAR_ASU_0900", "nombre": "Martes ASU 09:00", "detalle": "Vuelve miércoles 14:20 desde La Noria; termina en Villarrica y vuelve en lastre a Asunción."},
    {"id": "VIE_ASU_0900", "nombre": "Viernes ASU 09:00", "detalle": "Domingo La Plata 13:30; reserva en Villarrica para martes 09:30; vuelve miércoles 18:00 desde Buenos Aires."},
    {"id": "MIE_ASU_0020", "nombre": "Miércoles ASU 00:20 cama", "detalle": "Vuelve jueves 17:00 desde Buenos Aires."},
    {"id": "MIE_ASU_0900", "nombre": "Miércoles ASU 09:00", "detalle": "Unidad de reserva en Asunción; queda de reserva en Buenos Aires y vuelve viernes 17:00."},
    {"id": "MIE_ASU_1230", "nombre": "Miércoles ASU 12:30 cama", "detalle": "Vuelve jueves 17:00 desde Buenos Aires."},
    {"id": "JUE_CDE", "nombre": "Jueves CDE 00:20 + ASU 12:30", "detalle": "Misma unidad; queda de reserva y vuelve sábado 17:00 desde Buenos Aires."},
    {"id": "JUE_ASU_0900", "nombre": "Jueves ASU 09:00", "detalle": "Vuelve viernes 18:00 desde Buenos Aires."},
    {"id": "VIE_VCA_0020", "nombre": "Viernes ASU 00:20 + Villarrica 09:35", "detalle": "Misma unidad; queda de reserva en Buenos Aires y vuelve domingo 18:00."},
    {"id": "VIE_ASU_1230_LEITO", "nombre": "Viernes ASU 12:30 cama / leito", "detalle": "Vuelve domingo 13:35 desde La Plata; llega a Asunción junto con Buenos Aires 17:00."},
    {"id": "SAB_ASU_0900", "nombre": "Sábado ASU 09:00", "detalle": "Vuelve domingo 14:20 desde La Noria; termina en Villarrica y vuelve en lastre a Asunción."},
]

def _servicio(id_, dia, lado, hora, servicio, rotacion, nota="", orden_llegada=0):
    return {
        "id": id_, "dia_id": dia, "dia": DIAS[dia - 1]["nombre"],
        "lado": lado, "hora": hora, "servicio": servicio,
        "rotacion_id": rotacion, "nota": nota,
        "orden_llegada": orden_llegada,
    }

SERVICIOS = [
    # LUNES
    _servicio("LUN-I-0020", 1, "Ida", "00:20", "Asunción → Buenos Aires", "LUN_ASU_0020", "Coche cama; vuelve martes 17:00."),
    _servicio("LUN-I-0900", 1, "Ida", "09:00", "Asunción → Buenos Aires", "LUN_ASU_0900", "Queda de reserva el martes; sale miércoles 13:30 desde La Plata."),
    _servicio("LUN-I-1230", 1, "Ida", "12:30", "Asunción → Buenos Aires", "LUN_ASU_1230", "Coche cama; vuelve martes 17:00."),
    _servicio("LUN-V-1700", 1, "Vuelta", "17:00", "Buenos Aires → Asunción", "SAB_CDE", "Unidad del sábado 00:20 CDE + 12:30 ASU; es la misma unidad.", 1),
    _servicio("LUN-V-1800", 1, "Vuelta", "18:00", "Buenos Aires → Asunción", "DOM_ASU_0900", "Unidad del domingo 09:00.", 2),

    # MARTES
    _servicio("MAR-I-0020", 2, "Ida", "00:20 + 09:35", "Asunción 00:20 + Villarrica 09:35 → Buenos Aires", "MAR_VCA_0020", "Misma unidad en ambos horarios; queda de reserva en Buenos Aires y vuelve jueves 18:00."),
    _servicio("MAR-I-0900", 2, "Ida", "09:00", "Asunción → Buenos Aires", "MAR_ASU_0900", "Vuelve miércoles 14:20 desde La Noria; termina en Villarrica y regresa en lastre a Asunción."),
    _servicio("MAR-I-0930", 2, "Ida", "09:30", "Villarrica → Buenos Aires", "VIE_ASU_0900", "Unidad que hizo viernes 09:00 y domingo La Plata 13:30; quedó de reserva en Villarrica."),
    _servicio("MAR-V-1700-A", 2, "Vuelta", "17:00", "Buenos Aires → Asunción", "LUN_ASU_0020", "Coche cama que salió el lunes 00:20.", 1),
    _servicio("MAR-V-1700-B", 2, "Vuelta", "17:00", "Buenos Aires → Asunción", "LUN_ASU_1230", "Coche cama que salió el lunes 12:30.", 1),
    _servicio("MAR-V-1800", 2, "Vuelta", "18:00", "Buenos Aires → Asunción", "DOM_CDE", "Unidad del domingo 00:20 CDE + 12:30 ASU; misma unidad.", 2),

    # MIÉRCOLES
    _servicio("MIE-I-0020", 3, "Ida", "00:20", "Asunción → Buenos Aires", "MIE_ASU_0020", "Coche cama; vuelve jueves 17:00."),
    _servicio("MIE-I-0900", 3, "Ida", "09:00", "Asunción → Buenos Aires", "MIE_ASU_0900", "Unidad de reserva en Asunción; queda de reserva en Buenos Aires y vuelve viernes 17:00."),
    _servicio("MIE-I-1230", 3, "Ida", "12:30", "Asunción → Buenos Aires", "MIE_ASU_1230", "Coche cama; vuelve jueves 17:00."),
    _servicio("MIE-V-1330", 3, "Vuelta", "13:30", "La Plata → Villarrica", "LUN_ASU_0900", "Unidad del lunes 09:00; no llega a Asunción, queda en Villarrica para el viernes 09:30."),
    _servicio("MIE-V-1420", 3, "Vuelta", "14:20", "La Noria → Villarrica → Asunción (lastre)", "MAR_ASU_0900", "Unidad del martes 09:00; termina en Villarrica y vuelve vacía a Asunción.", 3),
    _servicio("MIE-V-1800", 3, "Vuelta", "18:00", "Buenos Aires → Asunción", "VIE_ASU_0900", "Unidad del viernes 09:00: pasó por La Plata el domingo y Villarrica el martes.", 2),

    # JUEVES
    _servicio("JUE-I-0020", 4, "Ida", "00:20", "Ciudad del Este → Buenos Aires", "JUE_CDE", "Misma unidad que sale de Asunción a las 12:30."),
    _servicio("JUE-I-0900", 4, "Ida", "09:00", "Asunción → Buenos Aires", "JUE_ASU_0900", "Vuelve viernes 18:00."),
    _servicio("JUE-I-1230", 4, "Ida", "12:30", "Asunción → Buenos Aires", "JUE_CDE", "Continuación de la unidad que salió de Ciudad del Este a las 00:20; queda de reserva y vuelve sábado 17:00."),
    _servicio("JUE-V-1700-A", 4, "Vuelta", "17:00", "Buenos Aires → Asunción", "MIE_ASU_0020", "Coche cama que salió el miércoles 00:20.", 1),
    _servicio("JUE-V-1700-B", 4, "Vuelta", "17:00", "Buenos Aires → Asunción", "MIE_ASU_1230", "Coche cama que salió el miércoles 12:30.", 1),
    _servicio("JUE-V-1800", 4, "Vuelta", "18:00", "Buenos Aires → Asunción", "MAR_VCA_0020", "Unidad del martes 00:20 + Villarrica 09:35; misma unidad.", 2),

    # VIERNES
    _servicio("VIE-I-0020", 5, "Ida", "00:20 + 09:35", "Asunción 00:20 + Villarrica 09:35 → Buenos Aires", "VIE_VCA_0020", "Misma unidad en ambos horarios; queda de reserva y vuelve domingo 18:00."),
    _servicio("VIE-I-0900", 5, "Ida", "09:00", "Asunción → Buenos Aires", "VIE_ASU_0900", "Vuelve domingo 13:30 desde La Plata; queda de reserva en Villarrica para el martes 09:30."),
    _servicio("VIE-I-0930", 5, "Ida", "09:30", "Villarrica → Buenos Aires", "LUN_ASU_0900", "Unidad del miércoles 13:30 La Plata, que había salido de Asunción el lunes 09:00; vuelve sábado 18:00."),
    _servicio("VIE-I-1230", 5, "Ida", "12:30", "Asunción → Buenos Aires", "VIE_ASU_1230_LEITO", "Coche cama/leito; vuelve domingo 13:35 desde La Plata."),
    _servicio("VIE-V-1700", 5, "Vuelta", "17:00", "Buenos Aires → Asunción", "MIE_ASU_0900", "Unidad del miércoles 09:00.", 1),
    _servicio("VIE-V-1800", 5, "Vuelta", "18:00", "Buenos Aires → Asunción", "JUE_ASU_0900", "Unidad del jueves 09:00.", 2),

    # SÁBADO
    _servicio("SAB-I-0020", 6, "Ida", "00:20", "Ciudad del Este → Buenos Aires", "SAB_CDE", "Misma unidad que sale de Asunción a las 12:30; vuelve lunes 17:00."),
    _servicio("SAB-I-0900", 6, "Ida", "09:00", "Asunción → Buenos Aires", "SAB_ASU_0900", "Vuelve domingo 14:20 desde La Noria; termina en Villarrica y vuelve en lastre a Asunción."),
    _servicio("SAB-I-1230", 6, "Ida", "12:30", "Asunción → Buenos Aires", "SAB_CDE", "Continuación de la unidad que salió de Ciudad del Este a las 00:20."),
    _servicio("SAB-V-1700", 6, "Vuelta", "17:00", "Buenos Aires → Asunción", "JUE_CDE", "Unidad del jueves 00:20 CDE + 12:30 ASU; misma unidad.", 1),
    _servicio("SAB-V-1800", 6, "Vuelta", "18:00", "Buenos Aires → Asunción", "LUN_ASU_0900", "Unidad que hizo viernes 09:30 desde Villarrica; ciclo iniciado el lunes 09:00.", 2),

    # DOMINGO
    _servicio("DOM-I-0020", 7, "Ida", "00:20", "Ciudad del Este → Buenos Aires", "DOM_CDE", "Misma unidad que sale de Asunción a las 12:30; vuelve martes 18:00."),
    _servicio("DOM-I-0900", 7, "Ida", "09:00", "Asunción → Buenos Aires", "DOM_ASU_0900", "Vuelve lunes 18:00."),
    _servicio("DOM-I-1230", 7, "Ida", "12:30", "Asunción → Buenos Aires", "DOM_CDE", "Continuación de la unidad que salió de Ciudad del Este a las 00:20."),
    _servicio("DOM-V-1330", 7, "Vuelta", "13:30", "La Plata → Villarrica", "VIE_ASU_0900", "Unidad del viernes 09:00; queda de reserva en Villarrica para el martes 09:30."),
    _servicio("DOM-V-1335", 7, "Vuelta", "13:35", "La Plata → Asunción (leito)", "VIE_ASU_1230_LEITO", "Coche cama/leito del viernes 12:30; llega con Buenos Aires 17:00.", 1),
    _servicio("DOM-V-1420", 7, "Vuelta", "14:20", "La Noria → Villarrica → Asunción (lastre)", "SAB_ASU_0900", "Unidad del sábado 09:00; llega después de Buenos Aires 18:00.", 3),
    _servicio("DOM-V-1800", 7, "Vuelta", "18:00", "Buenos Aires → Asunción", "VIE_VCA_0020", "Unidad del viernes 00:20 + Villarrica 09:35; misma unidad.", 2),
]

_ROTACION_IDS = {r["id"] for r in ROTACIONES}
_SERVICIO_IDS = {s["id"] for s in SERVICIOS}


def _puede_ver():
    return session.get("rol") in ("admin", "taller", "auditor")


def _puede_editar():
    return session.get("rol") in ("admin", "taller")


def _ahora():
    try:
        from hora_local import ahora_iso
        return ahora_iso()
    except Exception:
        return datetime.now().isoformat(timespec="seconds")


def init_programacion_semanal():
    conn = get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trafico_programacion_asignaciones (
                rotacion_id TEXT PRIMARY KEY,
                unidad TEXT NOT NULL DEFAULT '',
                actualizado_por TEXT DEFAULT '',
                actualizado_en TEXT DEFAULT ''
            )
        """)
        conn.commit()
    finally:
        conn.close()


def _asignaciones():
    conn = get_connection()
    try:
        return {
            str(r["rotacion_id"]): {
                "unidad": str(r["unidad"] or ""),
                "actualizado_por": str(r["actualizado_por"] or ""),
                "actualizado_en": str(r["actualizado_en"] or ""),
            }
            for r in conn.execute(
                "SELECT rotacion_id, unidad, actualizado_por, actualizado_en FROM trafico_programacion_asignaciones"
            ).fetchall()
        }
    finally:
        conn.close()


def _rotaciones_con_asignacion(asignaciones=None):
    asignaciones = asignaciones if asignaciones is not None else _asignaciones()
    out = []
    for rot in ROTACIONES:
        a = asignaciones.get(rot["id"], {})
        out.append({**rot, "unidad": a.get("unidad", ""), "actualizado_por": a.get("actualizado_por", ""),
                    "actualizado_en": a.get("actualizado_en", "")})
    return out


def _servicios_con_unidad(asignaciones=None):
    asignaciones = asignaciones if asignaciones is not None else _asignaciones()
    out = []
    for s in SERVICIOS:
        a = asignaciones.get(s["rotacion_id"], {})
        out.append({**s, "unidad": a.get("unidad", "")})
    return out


def _denegado():
    return jsonify({"ok": False, "msg": "Sin permiso para acceder a la programación semanal."}), 403


@bp_programacion_semanal.route("/trafico/programacion-semanal", methods=["GET"])
def pagina_programacion_semanal():
    if not _puede_ver():
        return ("Sin permiso para acceder a la programación semanal.", 403)
    asignaciones = _asignaciones()
    return render_template(
        "programacion_semanal.html",
        dias=DIAS, reglas=REGLAS,
        rotaciones=_rotaciones_con_asignacion(asignaciones),
        servicios=_servicios_con_unidad(asignaciones),
        puede_editar=_puede_editar(),
    )


@bp_programacion_semanal.route("/api/trafico/programacion-semanal", methods=["GET"])
def api_programacion_semanal():
    if not _puede_ver():
        return _denegado()
    asignaciones = _asignaciones()
    return jsonify({
        "ok": True,
        "dias": DIAS,
        "reglas": REGLAS,
        "rotaciones": _rotaciones_con_asignacion(asignaciones),
        "servicios": _servicios_con_unidad(asignaciones),
        "puede_editar": _puede_editar(),
    })


@bp_programacion_semanal.route("/api/trafico/programacion-semanal/asignaciones/<rotacion_id>", methods=["PUT"])
def api_guardar_asignacion(rotacion_id):
    if not _puede_editar():
        return _denegado()
    if rotacion_id not in _ROTACION_IDS:
        return jsonify({"ok": False, "msg": "Rotación desconocida."}), 404
    data = request.get_json(silent=True) or {}
    unidad = " ".join(str(data.get("unidad") or "").split())[:40]
    quien = str(session.get("nombre") or session.get("usuario") or "?")[:120]
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO trafico_programacion_asignaciones
                (rotacion_id, unidad, actualizado_por, actualizado_en)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (rotacion_id) DO UPDATE SET
                unidad=excluded.unidad,
                actualizado_por=excluded.actualizado_por,
                actualizado_en=excluded.actualizado_en
        """, (rotacion_id, unidad, quien, _ahora()))
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return jsonify({"ok": False, "msg": "No se pudo guardar la asignación. Revisá la conexión e intentá de nuevo."}), 500
    finally:
        conn.close()
    try:
        from database import registrar_auditoria
        registrar_auditoria(
            usuario=quien, rol=session.get("rol") or "",
            accion="Actualizó unidad de programación semanal",
            categoria="Tráfico",
            detalle=f"Rotación {rotacion_id}: {unidad or 'sin asignar'}",
        )
    except Exception:
        pass
    return jsonify({"ok": True, "rotacion_id": rotacion_id, "unidad": unidad})


@bp_programacion_semanal.route("/api/trafico/programacion-semanal.csv", methods=["GET"])
def exportar_programacion_semanal():
    if not _puede_ver():
        return _denegado()
    filas = _servicios_con_unidad()
    salida = io.StringIO()
    salida.write("\ufeff")
    writer = csv.writer(salida, delimiter=";")
    writer.writerow(["Día", "Lado", "Hora", "Servicio", "Unidad asignada", "Rotación", "Continuidad / observaciones", "Orden de llegada"])
    for s in filas:
        writer.writerow([
            s["dia"], s["lado"], s["hora"], s["servicio"], s["unidad"],
            s["rotacion_id"], s["nota"], s["orden_llegada"] or "",
        ])
    return Response(
        salida.getvalue(), mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="programacion_semanal_internacional.csv"'},
    )
