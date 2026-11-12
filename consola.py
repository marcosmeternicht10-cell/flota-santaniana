"""
consola.py — Los números y los avisos de la vista «consola»

La vista consola (static/consola.js) muestra el sistema como el inicio de una
PlayStation: las divisiones arriba, y adentro de cada una sus subdivisiones
como tarjetas con un dato en vivo. Arriba de todo, una fila de avisos con lo
que hay que resolver hoy.

Cada usuario ve SU sector: las divisiones, los números y los avisos de las
secciones que tiene habilitadas (el de compras ve compras y taller, el
auditor ve corporativos y combustible, un usuario de taller con secciones
elegidas ve solo esas). Eso se decide acá, no en el navegador: ocultar una
tarjeta no alcanza, los números tampoco tienen que viajar.

Cada número se calcula por separado: si una tabla no existe o una consulta
falla, ese dato queda vacío y los demás se muestran igual.

Enganche en app.py:
    from consola import bp_consola
    app.register_blueprint(bp_consola)
"""

import time
from datetime import date, timedelta

from flask import Blueprint, jsonify, session

from db_compat import get_connection
from hora_local import hoy, ahora

bp_consola = Blueprint("consola", __name__)

# Se guarda unos segundos: la consola pide los números al abrir y cada minuto,
# y varios usuarios con la consola abierta no tienen que multiplicar las consultas.
_memo = {"t": 0.0, "datos": None}
_MEMO_SEG = 30

# ── Qué ve cada uno ──────────────────────────────────────────────────────────
TODAS = {
    "dashboard", "vehiculos", "documentos", "trafico", "servicios", "comb_rendicion", "costos", "kpis",
    "ots", "pedidos_ot", "coches",
    "inventario_neu", "personal", "tablero_taller", "contabilidad", "compras",
    "repuestos", "proveedores", "cajas", "gerencial", "oee", "corp_asignacion", "corp_resumen",
    "corp_historial", "corp_empresas", "corp_servicios", "corp_combustible", "corp_cargas",
    "turismo_agenda", "turismo_rendiciones", "turismo", "agencias", "combustible", "historial",
    "alpha", "controles", "integraciones", "limpieza", "salud",
}
SOLO_ADMIN = {"alpha", "controles", "integraciones", "limpieza", "contabilidad", "historial", "combustible", "salud"}
# Lo mismo que muestra el menú (static/app.js) a cada rol
SECCIONES_COMPRAS = {"compras", "ots", "repuestos", "proveedores", "inventario_neu", "coches", "personal", "cajas",
                     "tablero_taller"}
SECCIONES_AUDITOR = {"combustible", "corp_asignacion", "corp_resumen", "corp_historial", "corp_empresas",
                     "corp_servicios", "corp_combustible", "corp_cargas", "turismo_rendiciones",
                     "comb_rendicion", "agencias", "cajas"}
CORP = {"corp_asignacion", "corp_resumen", "corp_historial", "corp_empresas", "corp_servicios",
        "corp_combustible", "corp_cargas"}


def secciones_del_usuario():
    """Las secciones que ve el usuario logueado (las mismas de su menú)."""
    rol = session.get("rol")
    if rol == "admin":
        return set(TODAS)
    if rol == "compras":
        return set(SECCIONES_COMPRAS)
    if rol == "auditor":
        return set(SECCIONES_AUDITOR)
    if rol == "taller":
        try:
            import permisos
            propias = set(permisos.desde_texto(",".join(session.get("secciones") or [])))
        except Exception:
            propias = set(session.get("secciones") or [])
        ve = propias or (TODAS - SOLO_ADMIN)
        if "ots" in ve:
            ve = ve | {"pedidos_ot"}
        return ve
    return set()


# Cada dato del resumen, y qué secciones hacen falta para verlo
DATO_SECCIONES = {
    "flota": TODAS,                                   # cuántos coches hay: lo ve cualquiera
    "trafico": {"trafico"},
    "turismo_hoy": {"turismo_agenda", "turismo"},
    "corp_hoy": CORP,
    "corp_pend": {"corp_resumen", "corp_historial"},
    "ots": {"ots", "compras", "tablero_taller"},
    "pedidos": {"pedidos_ot"},
    "correctivos": {"coches", "ots"},
    "docs": {"documentos"},
    "combustible": {"combustible", "comb_rendicion", "corp_combustible"},
    "turismo_rend": {"turismo_rendiciones"},
    "alpha_hoy": {"alpha"},
    "integ_revisar": {"integraciones"},
    "preventivo": {"coches"},
    "errores_sin_ver": {"salud"},
}


def _uno(conn, sql, params=(), campo="n", defecto=None):
    """Un número suelto. Si falla, se deshace la consulta y se sigue."""
    try:
        r = conn.execute(sql, params).fetchone()
        if r is None:
            return defecto
        v = r[campo]
        return v if v is not None else defecto
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return defecto


def _calcular():
    """Todos los números y avisos, para todos. Después se filtra por usuario."""
    f = date.fromisoformat(hoy())
    hoy_txt = f.isoformat()
    manana = f + timedelta(days=1)
    en7 = (f + timedelta(days=7)).isoformat()
    en30 = (f + timedelta(days=30)).isoformat()
    mes = hoy_txt[:7]
    hora = ahora().strftime("%H:%M")
    d = {"fecha": hoy_txt, "hora": hora}
    avisos = []

    def aviso(sec, nivel, icono, titulo, detalle=""):
        avisos.append({"sec": sec, "nivel": nivel, "icono": icono, "titulo": titulo, "detalle": detalle})

    # Lo del día (lo mismo que ve el gerente): tráfico, turismo, corporativos, flota
    try:
        import gerencia
        op = gerencia.operacion_del_dia(f)
        t, tu, co, fl = op["trafico"], op["turismo"], op["corporativos"], op["flota"]
        d["trafico"] = {"total": t["total"], "salieron": t["salieron"], "por_salir": t["por_salir"],
                        "sin_coche": t["sin_coche"], "internacional": t["internacional"], "existe": t["existe"]}
        d["turismo_hoy"] = {"total": tu["total"], "en_viaje": len(tu.get("en_viaje") or []),
                            "sin_asignar": tu["sin_asignar"]}
        d["corp_hoy"] = {"servicios": co["servicios"], "completos": co["completos"], "medios": co["medios"]}
        d["flota"] = {"activos": fl["activos"], "disponibles": fl["disponibles"],
                      "en_taller": fl["en_taller"], "fuera_servicio": fl["fuera_servicio"]}
        if not t["existe"]:
            aviso("trafico", "aviso", "ti-route-off", "No hay tráfico cargado para hoy")
        elif t["sin_coche"]:
            aviso("trafico", "alerta", "ti-bus-off",
                  f"{t['sin_coche']} {'salida' if t['sin_coche'] == 1 else 'salidas'} de hoy sin coche",
                  f"{t['por_salir']} por salir")
        if tu["sin_asignar"]:
            aviso("turismo_agenda", "alerta", "ti-calendar-exclamation",
                  f"{tu['sin_asignar']} {'viaje' if tu['sin_asignar'] == 1 else 'viajes'} de turismo de hoy sin coche o chofer")
        try:
            tm = gerencia.turismo_del_dia(manana)
            if tm["sin_asignar"]:
                aviso("turismo_agenda", "aviso", "ti-calendar-event",
                      f"{tm['sin_asignar']} {'viaje' if tm['sin_asignar'] == 1 else 'viajes'} de mañana sin asignar")
        except Exception:
            pass
    except Exception:
        pass

    conn = get_connection()
    try:
        # El tráfico de mañana, después de las 16
        if hora >= "16:00" and "trafico" in d:
            n = _uno(conn, "SELECT COUNT(*) AS n FROM trafico_dias WHERE fecha = ?", (manana.isoformat(),), defecto=None)
            if n == 0:
                aviso("trafico", "aviso", "ti-calendar-time", "Falta cargar el tráfico de mañana")

        # Taller
        d["ots"] = {
            "abiertas": _uno(conn, """SELECT COUNT(DISTINCT COALESCE(ot_grupo, id)) AS n FROM ordenes_trabajo
                                      WHERE estado <> 'cerrada'""", defecto=0),
            "en_compras": _uno(conn, """SELECT COUNT(*) AS n FROM ordenes_trabajo WHERE estado <> 'cerrada'
                                        AND COALESCE(estado_compras,'') IN ('en_espera','presupuestado','en_camino')""", defecto=0),
            "esperando_pedido": _uno(conn, """SELECT COUNT(*) AS n FROM ordenes_trabajo WHERE estado <> 'cerrada'
                                              AND COALESCE(estado_compras,'') = 'en_espera'""", defecto=0),
            "cerradas_mes": _uno(conn, """SELECT COUNT(*) AS n FROM ordenes_trabajo WHERE estado = 'cerrada'
                                          AND substr(COALESCE(fecha_cierre,''),1,7) = ?""", (mes,), defecto=0),
        }
        if d["ots"]["esperando_pedido"]:
            n = d["ots"]["esperando_pedido"]
            aviso("compras", "aviso", "ti-shopping-cart-exclamation",
                  f"{n} {'pedido' if n == 1 else 'pedidos'} del taller sin presupuestar")
        d["correctivos"] = _uno(conn, "SELECT COUNT(*) AS n FROM correctivos WHERE estado IN ('pendiente','en_reparacion')", defecto=0)

        # Documentos de los coches
        d["docs"] = {
            "vencidos": _uno(conn, """SELECT COUNT(*) AS n FROM documentos WHERE reemplazado_por IS NULL
                                      AND COALESCE(fecha_vencimiento,'') <> '' AND fecha_vencimiento < ?""", (hoy_txt,), defecto=0),
            "por_vencer": _uno(conn, """SELECT COUNT(*) AS n FROM documentos WHERE reemplazado_por IS NULL
                                        AND COALESCE(fecha_vencimiento,'') <> '' AND fecha_vencimiento >= ? AND fecha_vencimiento <= ?""",
                               (hoy_txt, en30), defecto=0),
            "semana": _uno(conn, """SELECT COUNT(*) AS n FROM documentos WHERE reemplazado_por IS NULL
                                    AND COALESCE(fecha_vencimiento,'') <> '' AND fecha_vencimiento >= ? AND fecha_vencimiento <= ?""",
                           (hoy_txt, en7), defecto=0),
        }
        if d["docs"]["vencidos"]:
            n = d["docs"]["vencidos"]
            aviso("documentos", "alerta", "ti-file-alert", f"{n} {'documento vencido' if n == 1 else 'documentos vencidos'}",
                  "Habilitaciones, seguros o VTV")
        if d["docs"]["semana"]:
            n = d["docs"]["semana"]
            aviso("documentos", "aviso", "ti-file-time", f"{n} {'documento vence' if n == 1 else 'documentos vencen'} esta semana")

        # Combustible del mes
        d["combustible"] = {
            "litros_mes": round(float(_uno(conn, "SELECT SUM(litros) AS n FROM combustible WHERE substr(fecha,1,7) = ?", (mes,), defecto=0) or 0)),
            "cargas_hoy": _uno(conn, "SELECT COUNT(*) AS n FROM combustible WHERE substr(fecha,1,10) = ?", (hoy_txt,), defecto=0),
        }

        # Corporativos: lo que falta liquidar
        d["corp_pend"] = {
            "servicios": _uno(conn, """SELECT COUNT(*) AS n FROM rendiciones_corp
                                       WHERE COALESCE(liquidado,0)=0 AND estado <> 'suspendido'""", defecto=0),
            "monto": round(float(_uno(conn, """SELECT SUM(monto) AS n FROM rendiciones_corp
                                               WHERE COALESCE(liquidado,0)=0 AND estado <> 'suspendido'""", defecto=0) or 0)),
        }

        # Turismo: rendiciones que esperan revisión
        d["turismo_rend"] = _uno(conn, "SELECT COUNT(*) AS n FROM turismo_rendiciones WHERE estado = 'presentada'", defecto=0)
        if d["turismo_rend"]:
            n = d["turismo_rend"]
            aviso("turismo_rendiciones", "aviso", "ti-receipt-2",
                  f"{n} {'rendición de viaje' if n == 1 else 'rendiciones de viaje'} para aprobar")

        # Pasajes (Alpha): lo vendido hoy
        d["alpha_hoy"] = {
            "boletos": _uno(conn, """SELECT COUNT(*) AS n FROM alpha_ventas WHERE estado = 'vendido'
                                     AND substr(COALESCE(creado_el,''),1,10) = ?""", (hoy_txt,), defecto=0),
            "total": round(float(_uno(conn, """SELECT SUM(total) AS n FROM alpha_ventas WHERE estado = 'vendido'
                                               AND substr(COALESCE(creado_el,''),1,10) = ?""", (hoy_txt,), defecto=0) or 0)),
        }

        # Integraciones: lo que llegó y hay que mirar, y los avisos que se cortaron
        d["integ_revisar"] = _uno(conn, "SELECT COUNT(*) AS n FROM integ_entrada WHERE estado IN ('revisar','error')", defecto=0)
        if d["integ_revisar"]:
            n = d["integ_revisar"]
            aviso("integraciones", "alerta", "ti-inbox", f"{n} {'dato recibido' if n == 1 else 'datos recibidos'} de otro sistema para revisar")
        pausados = _uno(conn, "SELECT COUNT(*) AS n FROM integ_avisos WHERE COALESCE(activo,1)=0 AND COALESCE(fallos_seguidos,0) >= 30",
                        defecto=0)
        if pausados:
            aviso("integraciones", "alerta", "ti-plug-connected-x",
                  f"{pausados} {'aviso automático pausado' if pausados == 1 else 'avisos automáticos pausados'} por fallas")
    finally:
        try:
            conn.close()
        except Exception:
            pass

    # Pedidos de los choferes sin decidir
    try:
        import ot_pedidos
        p = ot_pedidos.pendientes()
        d["pedidos"] = {"nuevos": p.get("nuevos", 0), "urgentes": p.get("urgentes", 0), "a_revisar": p.get("a_revisar", 0)}
        if p.get("urgentes"):
            aviso("pedidos_ot", "alerta", "ti-urgent", f"{p['urgentes']} {'pedido urgente' if p['urgentes'] == 1 else 'pedidos urgentes'} de choferes")
        if p.get("nuevos"):
            aviso("pedidos_ot", "aviso", "ti-inbox", f"{p['nuevos']} {'pedido nuevo' if p['nuevos'] == 1 else 'pedidos nuevos'} de choferes",
                  "Sin decidir si van a la OT")
    except Exception:
        pass

    # Preventivo vencido
    try:
        import plan_preventivo
        prev = plan_preventivo.resumen_para_dashboard()
        venc = sum(1 for v in prev.values() if v.get("estado") == "vencido")
        pronto = sum(1 for v in prev.values() if v.get("estado") == "pronto")
        d["preventivo"] = {"vencidos": venc, "pronto": pronto}
        if venc:
            aviso("coches", "alerta", "ti-calendar-x", f"{venc} {'coche' if venc == 1 else 'coches'} con el preventivo vencido")
        if pronto:
            aviso("coches", "aviso", "ti-calendar-due", f"{pronto} {'coche' if pronto == 1 else 'coches'} con el preventivo por vencer")
    except Exception:
        pass

    # La agenda del taller: turnos que ya pasaron y no se hicieron
    try:
        import plan_preventivo
        sin = plan_preventivo.agenda_sin_cumplir(30)
        if sin:
            avisos.append({"sec": "coches", "nivel": "alerta", "icono": "ti-calendar-exclamation", "ir": "agenda",
                           "titulo": f"{sin} {'turno del taller no se hizo' if sin == 1 else 'turnos del taller no se hicieron'}",
                           "detalle": "Agenda de los últimos 30 días"})
    except Exception:
        pass

    # Corporativos: servicios que se pisan en horario, sin liquidar
    try:
        import corporativos
        s = corporativos.rendiciones_sospechosas()
        choques = [x for x in s.get("misma_franja", []) if not x.get("justificado")]
        if choques:
            n = len(choques)
            aviso("corp_resumen", "alerta", "ti-clock-exclamation",
                  f"{n} {'choque' if n == 1 else 'choques'} de horario en rendiciones",
                  "Servicios que se pisan · revisar antes de liquidar")
    except Exception:
        pass

    # Errores del sistema sin mirar (Salud del sistema)
    try:
        import vigilancia
        n = vigilancia.sin_ver()
        if n is not None:
            d["errores_sin_ver"] = n
            if n:
                aviso("salud", "alerta", "ti-bug", f"{n} {'error del sistema' if n == 1 else 'errores del sistema'} sin mirar",
                      "Salud del sistema")
    except Exception:
        pass

    if d.get("correctivos"):
        n = d["correctivos"]
        aviso("coches", "aviso", "ti-alert-triangle", f"{n} {'correctivo pendiente' if n == 1 else 'correctivos pendientes'}")

    # Primero lo urgente
    avisos.sort(key=lambda a: 0 if a["nivel"] == "alerta" else 1)
    d["avisos"] = avisos
    return d


def resumen_para(secciones):
    """Lo que le corresponde ver a alguien con esas secciones."""
    ahora_s = time.time()
    if not _memo["datos"] or ahora_s - _memo["t"] > _MEMO_SEG:
        _memo["datos"] = _calcular()
        _memo["t"] = ahora_s
    todo = _memo["datos"]
    out = {"fecha": todo["fecha"], "hora": todo["hora"]}
    for clave, necesita in DATO_SECCIONES.items():
        if clave in todo and (necesita & secciones):
            out[clave] = todo[clave]
    out["avisos"] = [a for a in todo.get("avisos", []) if a["sec"] in secciones]
    return out


@bp_consola.route("/api/consola/resumen", methods=["GET"])
def api_consola_resumen():
    secs = secciones_del_usuario()
    if not secs:
        return jsonify({"error": "Sin acceso"}), 403
    return jsonify(resumen_para(secs))
