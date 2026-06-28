"""
dossier_db.py — Dossier completo por coche (La Santaniana)

Junta TODO el historial de un vehículo en una sola hoja: correctivos,
neumáticos, órdenes de trabajo, costos, y el OEE del período. Encima de eso,
un motor de reglas genera un diagnóstico con tono constructivo y orientado a
la acción (la "IA" que apoya; las decisiones las toman las personas).

No reinventa el cálculo de OEE: reusa calcular_oee_vehiculo() de database.py.
"""

from db_compat import get_connection
import datetime as _dt


def _dias_entre(desde, hasta):
    try:
        d1 = _dt.date.fromisoformat(desde)
        d2 = _dt.date.fromisoformat(hasta)
        return max(1, (d2 - d1).days + 1)
    except Exception:
        return 1


def generar_dossier(vehiculo_id, desde, hasta):
    """
    Arma el dossier completo de un coche en un período.
    Devuelve un dict con todas las secciones + el diagnóstico.
    """
    from database import calcular_oee_vehiculo

    conn = get_connection()
    veh = conn.execute("SELECT * FROM vehiculos WHERE id=?", (vehiculo_id,)).fetchone()
    if not veh:
        conn.close()
        return None
    veh = dict(veh)

    # ── 1. OEE del período (reusa la función existente) ──
    oee = calcular_oee_vehiculo(vehiculo_id, desde, hasta) or {}

    # ── 2. Correctivos del período ──
    correctivos = conn.execute("""
        SELECT fecha, km, tipo_falla, descripcion, reparacion, costo, taller, estado
        FROM correctivos
        WHERE vehiculo_id=? AND fecha BETWEEN ? AND ?
        ORDER BY fecha DESC
    """, (vehiculo_id, desde, hasta)).fetchall()
    correctivos = [dict(c) for c in correctivos]

    # Agrupar fallas por tipo (para ver el patrón: ¿qué se rompe más?)
    fallas_por_tipo = {}
    costo_correctivos = 0
    for c in correctivos:
        t = (c.get("tipo_falla") or "Otros").strip()
        if t not in fallas_por_tipo:
            fallas_por_tipo[t] = {"tipo": t, "cantidad": 0, "costo": 0}
        fallas_por_tipo[t]["cantidad"] += 1
        fallas_por_tipo[t]["costo"] += float(c.get("costo") or 0)
        costo_correctivos += float(c.get("costo") or 0)
    fallas_ranking = sorted(fallas_por_tipo.values(), key=lambda x: -x["cantidad"])

    # ── 3. Órdenes de trabajo del período ──
    ots = conn.execute("""
        SELECT o.id, o.fecha_apertura, o.fecha_cierre, o.km, o.estado, o.procedencia,
            (SELECT COUNT(*) FROM ot_items WHERE ot_id=o.id) AS items,
            (SELECT COALESCE(SUM(costo),0) FROM ot_items WHERE ot_id=o.id) AS costo
        FROM ordenes_trabajo o
        WHERE o.vehiculo_id=? AND o.fecha_apertura BETWEEN ? AND ?
        ORDER BY o.fecha_apertura DESC
    """, (vehiculo_id, desde, hasta)).fetchall()
    ots = [dict(o) for o in ots]
    costo_ots = sum(float(o.get("costo") or 0) for o in ots)

    # Items de OT por tipo
    items_tipo = conn.execute("""
        SELECT i.tipo, COUNT(*) AS cant, COALESCE(SUM(i.costo),0) AS costo
        FROM ot_items i JOIN ordenes_trabajo o ON o.id=i.ot_id
        WHERE o.vehiculo_id=? AND o.fecha_apertura BETWEEN ? AND ?
        GROUP BY i.tipo ORDER BY cant DESC
    """, (vehiculo_id, desde, hasta)).fetchall()
    items_tipo = [dict(i) for i in items_tipo]

    # ── 4. Neumáticos: historial de movimientos del período ──
    neu_movimientos = conn.execute("""
        SELECT i.fecha_instalacion, i.fecha_retiro, i.posicion, i.km_instalacion,
               i.km_retiro, i.motivo_retiro, n.codigo, n.marca
        FROM instalaciones_neumaticos i
        JOIN neumaticos n ON n.id = i.neumatico_id
        WHERE i.vehiculo_id=?
          AND (i.fecha_instalacion BETWEEN ? AND ?
               OR (i.fecha_retiro IS NOT NULL AND i.fecha_retiro BETWEEN ? AND ?))
        ORDER BY i.fecha_instalacion DESC
    """, (vehiculo_id, desde, hasta, desde, hasta)).fetchall()
    neu_movimientos = [dict(n) for n in neu_movimientos]

    # Neumáticos actualmente instalados
    neu_actuales = conn.execute("""
        SELECT i.posicion, i.km_instalacion, n.codigo, n.marca, n.km_acumulados
        FROM instalaciones_neumaticos i
        JOIN neumaticos n ON n.id = i.neumatico_id
        WHERE i.vehiculo_id=? AND i.fecha_retiro IS NULL
        ORDER BY i.posicion
    """, (vehiculo_id,)).fetchall()
    neu_actuales = [dict(n) for n in neu_actuales]

    # ── 5. Costos del período ──
    costos = conn.execute("""
        SELECT tipo, COALESCE(SUM(monto),0) AS total
        FROM costos
        WHERE vehiculo_id=?
        GROUP BY tipo ORDER BY total DESC
    """, (vehiculo_id,)).fetchall()
    costos = [dict(c) for c in costos]
    costo_total_general = costo_correctivos + costo_ots

    conn.close()

    # ── 6. Métricas derivadas ──
    km_recorridos = oee.get("km_recorridos", 0) or 0
    costo_por_km = (costo_total_general / km_recorridos) if km_recorridos else 0
    cant_correctivos = len(correctivos)
    km_entre_fallas = (km_recorridos / cant_correctivos) if cant_correctivos else km_recorridos

    metricas = {
        "km_recorridos": km_recorridos,
        "costo_total": round(costo_total_general),
        "costo_correctivos": round(costo_correctivos),
        "costo_ots": round(costo_ots),
        "costo_por_km": round(costo_por_km),
        "cant_correctivos": cant_correctivos,
        "cant_ots": len(ots),
        "km_entre_fallas": round(km_entre_fallas),
        "dias_fuera": oee.get("dias_fuera", 0),
        "dias_operativo": oee.get("dias_operativo", 0),
    }

    # ── 7. Diagnóstico (el motor de reglas) ──
    diagnostico = generar_diagnostico(veh, oee, metricas, fallas_ranking)

    return {
        "vehiculo": {
            "id": veh["id"], "patente": veh.get("patente"),
            "n_interno": veh.get("n_interno"), "marca": veh.get("marca"),
            "modelo": veh.get("modelo"), "anio": veh.get("año"),
            "km_actual": veh.get("km_manual") or 0,
        },
        "periodo": {"desde": desde, "hasta": hasta, "dias": _dias_entre(desde, hasta)},
        "oee": oee,
        "metricas": metricas,
        "correctivos": correctivos,
        "fallas_ranking": fallas_ranking,
        "ots": ots,
        "items_tipo": items_tipo,
        "neumaticos_movimientos": neu_movimientos,
        "neumaticos_actuales": neu_actuales,
        "costos": costos,
        "diagnostico": diagnostico,
    }


def generar_diagnostico(veh, oee, metricas, fallas_ranking):
    """
    Motor de reglas que genera un diagnóstico con tono constructivo.
    NO reemplaza el criterio humano: ilumina el problema y sugiere áreas de
    enfoque, dejando que el equipo decida las acciones concretas.

    Devuelve:
      - resumen: una frase de cabecera honesta pero esperanzadora
      - nivel: 'excelente' | 'bueno' | 'atencion' | 'critico'
      - fortalezas: lista de cosas que están bien (siempre buscar al menos una)
      - focos: lista de áreas a mejorar, cada una con su 'porque' y 'sugerencia'
    """
    disp = oee.get("disponibilidad", 0)
    rend = oee.get("rendimiento", 0)
    cal = oee.get("calidad", 0)
    oee_val = oee.get("oee", 0)
    faltantes = oee.get("faltantes", [])

    fortalezas = []
    focos = []

    # ── Buscar fortalezas (siempre destacar lo bueno primero) ──
    if disp >= 85:
        fortalezas.append(f"El coche estuvo disponible el {disp:.0f}% del tiempo — muy pocas paradas. Eso es base sólida.")
    if cal >= 85:
        fortalezas.append(f"Pocas fallas en el período (calidad {cal:.0f}%). El coche viene confiable.")
    if rend >= 80 and rend <= 110:
        fortalezas.append(f"El rendimiento de kilometraje ({rend:.0f}%) está en línea con lo esperado.")
    if metricas["cant_correctivos"] == 0:
        fortalezas.append("Cero correctivos en el período. El preventivo está haciendo su trabajo.")

    # ── Detectar focos de mejora (con tono de solución) ──
    if disp < 70 and disp > 0:
        focos.append({
            "area": "Disponibilidad",
            "porque": f"El coche estuvo parado {metricas['dias_fuera']} días, bajando la disponibilidad al {disp:.0f}%.",
            "sugerencia": "Revisar qué generó las paradas más largas. Si fueron esperas de repuestos, adelantar el stock de los críticos puede recuperar varios días.",
        })
    if cal < 70 and cal > 0:
        top_falla = fallas_ranking[0] if fallas_ranking else None
        extra = ""
        if top_falla and top_falla["cantidad"] >= 2:
            extra = f" La falla más repetida fue \"{top_falla['tipo']}\" ({top_falla['cantidad']} veces) — ahí hay un patrón para atacar."
        focos.append({
            "area": "Confiabilidad",
            "porque": f"Se registraron {metricas['cant_correctivos']} correctivos, lo que bajó la calidad al {cal:.0f}%.{extra}",
            "sugerencia": "Concentrar el análisis en la falla más frecuente. Resolver la causa raíz de esa sola puede mover el indicador más que muchos arreglos sueltos.",
        })
    if metricas["costo_por_km"] > 0 and metricas["km_recorridos"] > 1000:
        # Umbral de referencia configurable; acá uso un valor orientativo en Gs/km
        if metricas["costo_por_km"] > 2000:
            focos.append({
                "area": "Costo por kilómetro",
                "porque": f"El mantenimiento costó Gs. {metricas['costo_por_km']:,}/km en el período, un valor alto.",
                "sugerencia": "Comparar este coche con otros del mismo modelo. Si está muy por encima, puede ser momento de evaluar reparaciones mayores vs. su rendimiento.",
            })
    if metricas["km_entre_fallas"] > 0 and metricas["cant_correctivos"] >= 3:
        focos.append({
            "area": "Frecuencia de fallas",
            "porque": f"El coche promedió una falla cada {metricas['km_entre_fallas']:,} km, lo que indica una racha de problemas.",
            "sugerencia": "Una inspección general programada puede adelantarse a las próximas fallas y cortar la racha antes de que escale.",
        })

    # ── Determinar nivel y resumen (honesto pero motivador) ──
    if oee_val >= 75:
        nivel = "excelente"
        resumen = f"Este coche está rindiendo muy bien (OEE {oee_val:.0f}%). Mantener el ritmo y cuidar lo que ya funciona."
    elif oee_val >= 55:
        nivel = "bueno"
        resumen = f"El coche está en buen camino (OEE {oee_val:.0f}%). Con un par de ajustes puntuales puede dar el salto al siguiente nivel."
    elif oee_val >= 35:
        nivel = "atencion"
        resumen = f"Hay margen de mejora claro (OEE {oee_val:.0f}%), pero la buena noticia es que los focos están identificados y son atacables."
    elif oee_val > 0:
        nivel = "critico"
        resumen = f"El coche necesita atención (OEE {oee_val:.0f}%), y acá está la oportunidad: cada foco que se resuelva va a notarse rápido en el indicador."
    else:
        nivel = "sin_datos"
        resumen = "Todavía no hay datos suficientes para un diagnóstico completo. Cargando más registros, el reporte se vuelve mucho más útil."

    # Si no hay fortalezas detectadas, buscar algo rescatable igual
    if not fortalezas and nivel != "sin_datos":
        mejor = max([("disponibilidad", disp), ("confiabilidad", cal), ("rendimiento", rend)], key=lambda x: x[1])
        if mejor[1] > 0:
            fortalezas.append(f"Lo más fuerte del coche ahora mismo es su {mejor[0]} ({mejor[1]:.0f}%) — un punto de apoyo para construir.")

    # Mensaje de cierre orientado a la acción humana
    cierre = "Estos números son una guía. El paso siguiente lo dan ustedes: priorizar un foco, asignar responsable y volver a medir el próximo período."

    return {
        "nivel": nivel,
        "resumen": resumen,
        "fortalezas": fortalezas,
        "focos": focos,
        "cierre": cierre,
        "faltantes": faltantes,
    }
