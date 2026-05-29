"""
models.py — Lógica de negocio y KPIs v3.0
Sistema de Gestión de Flota - La Santaniana

Dos vistas de KPIs:
  • POR MES        → toma servicios + costos de un mes concreto (YYYY-MM)
  • POR PRODUCCIÓN → acumula TODOS los servicios + costos del vehículo

Estructura de costos:
    INGRESO
    - COSTOS VARIABLES
    = MARGEN DE CONTRIBUCIÓN
    - COSTOS FIJOS DIRECTOS
    - COSTOS FIJOS INDIRECTOS
    = UTILIDAD OPERATIVA
"""

from database import (
    get_connection, obtener_costos, obtener_servicios_vehiculo,
    obtener_vehiculos, resumen_produccion,
)


def _sumar_costos(costos):
    """Separa una lista de costos por tipo y suma."""
    variables = sum(c["monto"] for c in costos if c["tipo"] == "variable")
    directos  = sum(c["monto"] for c in costos if c["tipo"] == "fijo_directo")
    indirectos= sum(c["monto"] for c in costos if c["tipo"] == "fijo_indirecto")
    return variables, directos, indirectos


def _calcular_kpis(servicios, costos):
    """Calcula KPIs dados una lista de servicios y otra de costos."""
    if not servicios:
        return None

    cantidad     = len(servicios)
    total_km     = sum(s["km"] for s in servicios)
    total_horas  = sum(s["horas"] for s in servicios)
    ingreso      = sum(s["ingreso"] for s in servicios)

    c_var, c_dir, c_ind = _sumar_costos(costos)

    margen_contribucion = ingreso - c_var
    utilidad_operativa  = margen_contribucion - c_dir - c_ind

    def safe_div(a, b):
        return a / b if b else 0

    return {
        # Operativos
        "cantidad_servicios": cantidad,
        "total_km": round(total_km, 1),
        "total_horas": round(total_horas, 1),
        "km_promedio": round(safe_div(total_km, cantidad), 1),
        "horas_promedio": round(safe_div(total_horas, cantidad), 1),
        "ingreso_promedio_servicio": round(safe_div(ingreso, cantidad), 0),
        # Estructura de costos
        "ingreso": round(ingreso, 0),
        "costos_variables": round(c_var, 0),
        "margen_contribucion": round(margen_contribucion, 0),
        "costos_fijos_directos": round(c_dir, 0),
        "costos_fijos_indirectos": round(c_ind, 0),
        "utilidad_operativa": round(utilidad_operativa, 0),
        # Ratios
        "ingreso_por_km": round(safe_div(ingreso, total_km), 0),
        "ingreso_por_hora": round(safe_div(ingreso, total_horas), 0),
        "costo_variable_por_km": round(safe_div(c_var, total_km), 0),
        "margen_pct": round(safe_div(margen_contribucion, ingreso) * 100, 1),
        "rentabilidad_pct": round(safe_div(utilidad_operativa, ingreso) * 100, 1),
    }


def kpis_mes(vehiculo_id, mes):
    """KPIs de un vehículo en un mes concreto (YYYY-MM)."""
    servicios = obtener_servicios_vehiculo(vehiculo_id, mes)
    costos    = obtener_costos(vehiculo_id, mes)
    return _calcular_kpis(servicios, costos)


def kpis_produccion(vehiculo_id):
    """KPIs acumulados de toda la producción del vehículo."""
    servicios = obtener_servicios_vehiculo(vehiculo_id)  # todos
    costos    = obtener_costos(vehiculo_id)              # todos
    k = _calcular_kpis(servicios, costos)
    if k:
        prod = resumen_produccion(vehiculo_id)
        k["fecha_inicio"] = prod.get("fecha_inicio")
        k["fecha_fin"] = prod.get("fecha_fin")
    return k


# ── Datos de ejemplo ──────────────────────────────────────────────────────────

def cargar_datos_ejemplo():
    """Carga servicios individuales basados en la clase 1, en guaraníes."""
    from database import (
        inicializar_db, agregar_vehiculo, agregar_servicio, agregar_costo
    )
    import os

    if os.path.exists("flota_santaniana.db"):
        os.remove("flota_santaniana.db")
    inicializar_db()

    print("Cargando datos de ejemplo...")
    agregar_vehiculo("AAA-001", "Mercedes-Benz", "OF 1721", 2018)

    conn = get_connection()
    vid = conn.execute("SELECT id FROM vehiculos WHERE patente='AAA-001'").fetchone()["id"]
    conn.close()

    # 12 servicios en junio 2024 — uno por uno (₲ 7.000.000 c/u, 900 km, 48 hs)
    import datetime
    for i in range(12):
        fecha = (datetime.date(2024, 6, 1) + datetime.timedelta(days=i*2)).isoformat()
        agregar_servicio(vid, fecha, km=900, horas=48,
                         ingreso=7_000_000, descripcion=f"Recorrido {i+1}")
    print("  12 servicios cargados (junio 2024): ₲ 84.000.000")

    # Costos del mes 2024-06
    agregar_costo(vid, "2024-06", "variable", "Combustible",      22_000_000)
    agregar_costo(vid, "2024-06", "variable", "Neumáticos",        5_700_000)
    agregar_costo(vid, "2024-06", "variable", "Lubricantes",       3_100_000)
    agregar_costo(vid, "2024-06", "variable", "Peajes y viáticos", 9_200_000)
    agregar_costo(vid, "2024-06", "fijo_directo", "Seguro",        3_800_000)
    agregar_costo(vid, "2024-06", "fijo_directo", "Patente",       2_400_000)
    agregar_costo(vid, "2024-06", "fijo_indirecto", "Administración",      3_200_000)
    agregar_costo(vid, "2024-06", "fijo_indirecto", "Servicios generales", 2_500_000)
    print("  Costos de junio 2024 cargados.")

    k = kpis_mes(vid, "2024-06")
    print("\nKPIs junio 2024:")
    print(f"  Ingreso:             ₲ {k['ingreso']:>14,.0f}".replace(",", "."))
    print(f"  Costos variables:    ₲ {k['costos_variables']:>14,.0f}".replace(",", "."))
    print(f"  Margen contribución: ₲ {k['margen_contribucion']:>14,.0f}".replace(",", "."))
    print(f"  Costos fijos dir:    ₲ {k['costos_fijos_directos']:>14,.0f}".replace(",", "."))
    print(f"  Costos fijos indir:  ₲ {k['costos_fijos_indirectos']:>14,.0f}".replace(",", "."))
    print(f"  Utilidad operativa:  ₲ {k['utilidad_operativa']:>14,.0f}".replace(",", "."))
    print(f"  Rentabilidad:        {k['rentabilidad_pct']}%")


if __name__ == "__main__":
    cargar_datos_ejemplo()
