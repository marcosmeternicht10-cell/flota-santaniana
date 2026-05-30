"""
mantenimiento_seed.py — Carga planes de mantenimiento predefinidos
basados en las fichas técnicas de motores comunes.

Se ejecuta una sola vez al instalar o se puede llamar manualmente.
"""

from database import get_connection, crear_plan, agregar_tarea


# ──────────────────────────────────────────────────────────────────────────
# PLANES SCANIA — Buses
# ──────────────────────────────────────────────────────────────────────────
# Todos los chasis Scania serie K (motor trasero) usan el mismo motor base
# (DC9 / DC11 / DC12 / DC13) con distintas potencias. Por eso los intervalos
# de mantenimiento son IGUALES en toda la gama. Cambia solo la designación
# del motor y los datos de torque/potencia.

# Tareas de mantenimiento Scania (sirven para toda la serie K)
TAREAS_SCANIA_K = [
    # Cada 15.000 km — Servicio básico
    ("Aceite de motor",                     15000, "Lubricación"),
    ("Filtro de aceite de motor",           15000, "Filtros"),
    ("Filtro primario de combustible",      15000, "Filtros"),
    ("Filtro racor (separador de agua)",    15000, "Filtros"),
    ("Filtro de aire primario (x2)",        15000, "Filtros"),
    ("Filtro de aire secundario",           15000, "Filtros"),
    ("Mantenimiento purificador centrífugo",15000, "Lubricación"),
    ("Engrase general",                     15000, "Lubricación"),

    # Cada 60.000 km — Servicio intermedio
    ("Filtro de cabina",                    60000, "Filtros"),
    ("Filtro y aceite de dirección",        60000, "Lubricación"),
    ("Filtro y aceite de retarder",         60000, "Lubricación"),
    ("Filtro secador de aire",              60000, "Sistema de aire"),
    ("Filtro SCR / AdBlue",                 60000, "Emisiones"),
    ("Líquido de frenos",                   60000, "Frenos"),

    # Cada 120.000 km — Servicio mayor
    ("Aceite y filtro de diferenciales",    120000, "Transmisión"),
    ("Aceite y filtro de caja de cambios",  120000, "Transmisión"),
    ("Calibración de válvulas (taqués)",    120000, "Motor"),
]

PLAN_SCANIA_K310 = {
    "nombre": "Scania K310 / DC9 310 HP",
    "descripcion": "Plan para chasis Scania K310 con motor DC9 de 9 litros, 310 HP. Bus mediano/regional.",
    "tareas": TAREAS_SCANIA_K,
}

PLAN_SCANIA_K340 = {
    "nombre": "Scania K340 / DC11 340 HP",
    "descripcion": "Plan para chasis Scania K340 con motor DC11 de 10,6 litros, 340 HP.",
    "tareas": TAREAS_SCANIA_K,
}

PLAN_SCANIA_K360 = {
    "nombre": "Scania K360 / DC9 360 HP",
    "descripcion": "Plan para chasis Scania K360 con motor DC9, 360 HP. Bus de media/larga distancia.",
    "tareas": TAREAS_SCANIA_K,
}

PLAN_SCANIA_K380 = {
    "nombre": "Scania K380 / DC12 380 HP",
    "descripcion": "Plan para chasis Scania K380 con motor DC12 16 de 11,7 litros, 380 HP. Coche cama / doble piso.",
    "tareas": TAREAS_SCANIA_K,
}

PLAN_SCANIA_K410 = {
    "nombre": "Scania K410 / DC13 410 HP",
    "descripcion": "Plan para chasis Scania K410 con motor DC13 de 12,7 litros, 410 HP. Larga distancia, doble piso.",
    "tareas": TAREAS_SCANIA_K,
}

PLAN_SCANIA_K420 = {
    "nombre": "Scania K420 / DC12 420 HP",
    "descripcion": "Plan para chasis Scania K420 con motor DC12 06 de 11,7 litros, 420 HP. Doble piso premium.",
    "tareas": TAREAS_SCANIA_K,
}

PLAN_SCANIA_K124 = {
    "nombre": "Scania K124 / DC11 360 HP",
    "descripcion": "Plan para chasis Scania K124 (Serie 4) con motor DC11. Buses antiguos años 2000s.",
    "tareas": TAREAS_SCANIA_K,
}

# ──────────────────────────────────────────────────────────────────────────
# PLANES MERCEDES-BENZ
# ──────────────────────────────────────────────────────────────────────────
# El motor Mercedes-Benz OM 457 LA es el que va en los chasis O 500 RS/RSD/RSDH.
# Es un 12.0 L, 6 cilindros en línea, con potencias entre 354 y 422 HP.
# Plan de mantenimiento similar al Scania por ser bus interurbano.

TAREAS_MERCEDES_OM457 = [
    # Cada 20.000 km (intervalo Mercedes para buses interurbanos con aceite mineral)
    ("Aceite de motor",                     20000, "Lubricación"),
    ("Filtro de aceite de motor",           20000, "Filtros"),
    ("Filtro primario de combustible",      20000, "Filtros"),
    ("Filtro de combustible (separador)",   20000, "Filtros"),
    ("Filtro de aire",                      20000, "Filtros"),
    ("Engrase general",                     20000, "Lubricación"),

    # Cada 60.000 km
    ("Filtro de cabina",                    60000, "Filtros"),
    ("Aceite y filtro de dirección",        60000, "Lubricación"),
    ("Filtro secador de aire",              60000, "Sistema de aire"),
    ("Filtro AdBlue/SCR (si Euro V)",       60000, "Emisiones"),
    ("Líquido de frenos",                   60000, "Frenos"),

    # Cada 120.000 km
    ("Aceite y filtro de diferencial",      120000, "Transmisión"),
    ("Aceite y filtro caja MB GO 210-6",    120000, "Transmisión"),
    ("Calibración de válvulas",             120000, "Motor"),
]

PLAN_MB_O500RS = {
    "nombre": "Mercedes-Benz O500 RS / OM457 354 HP",
    "descripcion": "Plan para chasis Mercedes O500 RS 4x2 con motor OM 457 LA de 354 HP. Bus interurbano.",
    "tareas": TAREAS_MERCEDES_OM457,
}

PLAN_MB_O500RSD_360 = {
    "nombre": "Mercedes-Benz O500 RSD / OM457 360 HP",
    "descripcion": "Plan para chasis Mercedes O500 RSD 6x2 con motor OM 457 LA de 360 HP (RSD/2036 y RSD/2436). Doble piso.",
    "tareas": TAREAS_MERCEDES_OM457,
}

PLAN_MB_O500RSD_410 = {
    "nombre": "Mercedes-Benz O500 RSD / OM457 410 HP",
    "descripcion": "Plan para chasis Mercedes O500 RSD 6x2 con motor OM 457 LA de 410 HP (RSD/2441) Euro V. Doble piso.",
    "tareas": TAREAS_MERCEDES_OM457,
}

PLAN_MB_O500RSD_422 = {
    "nombre": "Mercedes-Benz O500 RSD / OM457 422 HP",
    "descripcion": "Plan para chasis Mercedes O500 RSD 6x2 (adaptable 8x2) con motor OM 457 LA de 422 HP (RSD/2442). Doble piso premium.",
    "tareas": TAREAS_MERCEDES_OM457,
}

PLAN_MB_SPRINTER = {
    "nombre": "Mercedes-Benz Sprinter / OM651 / OM642",
    "descripcion": "Plan para minibuses Mercedes-Benz Sprinter (modelos 415/515/516). Motores OM651 2.1L o OM642 3.0L V6.",
    "tareas": [
        ("Aceite de motor (Mercedes 229.51)",   20000, "Lubricación"),
        ("Filtro de aceite",                    20000, "Filtros"),
        ("Filtro de combustible",               20000, "Filtros"),
        ("Filtro de aire",                      40000, "Filtros"),
        ("Filtro de cabina",                    40000, "Filtros"),
        ("Líquido de frenos",                   60000, "Frenos"),
        ("Filtro de AdBlue (si aplica)",        60000, "Emisiones"),
        ("Aceite caja de cambios",              80000, "Transmisión"),
        ("Aceite diferencial",                  80000, "Transmisión"),
    ],
}

# ──────────────────────────────────────────────────────────────────────────
# PLANES VOLVO
# ──────────────────────────────────────────────────────────────────────────
# Motor Volvo D11A (10.8 L, 6 cil, 430 HP) - usado en B430R 6x2 y 8x2.
# Caja I-Shift de 12 marchas.

TAREAS_VOLVO_D11A = [
    # Cada 30.000 km - Volvo permite intervalos largos con aceite VDS-3/VDS-4
    ("Aceite de motor (Volvo VDS-4)",       30000, "Lubricación"),
    ("Filtro de aceite",                    30000, "Filtros"),
    ("Filtro primario de combustible",      30000, "Filtros"),
    ("Filtro racor (separador agua)",       30000, "Filtros"),
    ("Filtro de aire",                      30000, "Filtros"),
    ("Engrase general",                     30000, "Lubricación"),

    # Cada 60.000 km
    ("Filtro de cabina",                    60000, "Filtros"),
    ("Filtro secador de aire",              60000, "Sistema de aire"),
    ("Líquido de frenos",                   60000, "Frenos"),

    # Cada 120.000 km
    ("Aceite y filtro de diferencial",      120000, "Transmisión"),
    ("Aceite caja I-Shift AT2612D",         120000, "Transmisión"),
    ("Calibración de válvulas",             120000, "Motor"),
    ("Inspección freno motor VEB",          120000, "Frenos"),
]

PLAN_VOLVO_B430R = {
    "nombre": "Volvo B430R / D11A 430 HP",
    "descripcion": "Plan para chasis Volvo B430R 6x2/8x2 con motor D11A de 10,8 L, 430 HP. Caja I-Shift 12 marchas.",
    "tareas": TAREAS_VOLVO_D11A,
}

PLAN_VOLVO_B420R = {
    "nombre": "Volvo B420R / D11A 410 HP",
    "descripcion": "Plan para chasis Volvo B420R 6x2/8x2 con motor D11A Euro V de 410 HP, 1.989 Nm.",
    "tareas": TAREAS_VOLVO_D11A,
}

# ──────────────────────────────────────────────────────────────────────────
# OTROS - Volkswagen Senior, Agrale Volare, Hyundai
# ──────────────────────────────────────────────────────────────────────────

PLAN_VW_SENIOR = {
    "nombre": "Volkswagen 9.150 / 9.160 OD (Senior)",
    "descripcion": "Plan para minibuses VW carrozados como Senior. Motor MWM 4.12 TCA Euro III.",
    "tareas": [
        ("Aceite de motor",                     15000, "Lubricación"),
        ("Filtro de aceite",                    15000, "Filtros"),
        ("Filtro de combustible",               15000, "Filtros"),
        ("Filtro de aire",                      30000, "Filtros"),
        ("Filtro de cabina",                    30000, "Filtros"),
        ("Líquido de frenos",                   60000, "Frenos"),
        ("Aceite caja de cambios",              80000, "Transmisión"),
        ("Aceite diferencial",                  80000, "Transmisión"),
        ("Engrase general",                     15000, "Lubricación"),
    ],
}

PLAN_AGRALE_VOLARE = {
    "nombre": "Agrale Volare W / WL",
    "descripcion": "Plan para microbuses Agrale Volare W/WL/W9. Motor Cummins ISF 3.8 Euro V.",
    "tareas": [
        ("Aceite de motor",                     15000, "Lubricación"),
        ("Filtro de aceite",                    15000, "Filtros"),
        ("Filtro de combustible",               15000, "Filtros"),
        ("Filtro de aire",                      30000, "Filtros"),
        ("Filtro de cabina",                    30000, "Filtros"),
        ("Filtro AdBlue/SCR",                   60000, "Emisiones"),
        ("Líquido de frenos",                   60000, "Frenos"),
        ("Aceite caja de cambios",              80000, "Transmisión"),
        ("Aceite diferencial",                  80000, "Transmisión"),
    ],
}

PLAN_HYUNDAI_H350 = {
    "nombre": "Hyundai H350 / H1 (minibús)",
    "descripcion": "Plan para minibuses Hyundai H350 (motor D4CB 2.5 CRDi) y H1 (D4CB 2.5).",
    "tareas": [
        ("Aceite de motor (5W-30 ACEA C3)",     15000, "Lubricación"),
        ("Filtro de aceite",                    15000, "Filtros"),
        ("Filtro de combustible",               20000, "Filtros"),
        ("Filtro de aire",                      30000, "Filtros"),
        ("Filtro de cabina",                    30000, "Filtros"),
        ("Líquido de frenos",                   40000, "Frenos"),
        ("Aceite caja de cambios",              60000, "Transmisión"),
        ("Correa de distribución",              90000, "Motor"),
    ],
}


PLANES_PREDEFINIDOS = [
    PLAN_SCANIA_K310, PLAN_SCANIA_K340, PLAN_SCANIA_K360,
    PLAN_SCANIA_K380, PLAN_SCANIA_K410, PLAN_SCANIA_K420,
    PLAN_SCANIA_K124,
    PLAN_MB_O500RS, PLAN_MB_O500RSD_360, PLAN_MB_O500RSD_410, PLAN_MB_O500RSD_422,
    PLAN_MB_SPRINTER,
    PLAN_VOLVO_B430R, PLAN_VOLVO_B420R,
    PLAN_VW_SENIOR, PLAN_AGRALE_VOLARE, PLAN_HYUNDAI_H350,
]


def cargar_plan(plan_def):
    """Carga un plan en la base de datos. Si ya existe, no hace nada."""
    conn = get_connection()
    existe = conn.execute(
        "SELECT id FROM planes_mantenimiento WHERE nombre=?", (plan_def["nombre"],)
    ).fetchone()
    conn.close()
    if existe:
        return False, existe["id"]

    ok, plan_id = crear_plan(plan_def["nombre"], plan_def["descripcion"])
    if not ok:
        return False, plan_id

    for tarea, intervalo, categoria in plan_def["tareas"]:
        agregar_tarea(plan_id, tarea, intervalo, categoria)

    return True, plan_id


def cargar_planes_default():
    """Carga todos los planes predefinidos + sus configs de neumáticos."""
    from database import crear_config_neumaticos

    print("Cargando planes de mantenimiento predefinidos...")

    # Config de neumáticos por modelo (datos típicos por chasis)
    configs_neumaticos = {
        # Scania serie K
        "Scania K310 / DC9 310 HP":  {"config": "4x2", "medida": "275/80 R22.5", "vida_km": 120000, "presion_dir": 110, "presion_trac": 120},
        "Scania K340 / DC11 340 HP": {"config": "6x2", "medida": "295/80 R22.5", "vida_km": 130000, "presion_dir": 110, "presion_trac": 120},
        "Scania K360 / DC9 360 HP":  {"config": "6x2", "medida": "295/80 R22.5", "vida_km": 130000, "presion_dir": 110, "presion_trac": 120},
        "Scania K380 / DC12 380 HP": {"config": "4patas", "medida": "295/80 R22.5", "vida_km": 130000, "presion_dir": 115, "presion_trac": 113},
        "Scania K410 / DC13 410 HP": {"config": "4patas", "medida": "295/80 R22.5", "vida_km": 140000, "presion_dir": 115, "presion_trac": 113},
        "Scania K420 / DC12 420 HP": {"config": "4patas", "medida": "295/80 R22.5", "vida_km": 140000, "presion_dir": 115, "presion_trac": 113},
        "Scania K124 / DC11 360 HP": {"config": "4x2", "medida": "295/80 R22.5", "vida_km": 110000, "presion_dir": 110, "presion_trac": 120},

        # Mercedes
        "Mercedes-Benz O500 RS / OM457 354 HP":   {"config": "4x2", "medida": "295/80 R22.5", "vida_km": 120000, "presion_dir": 110, "presion_trac": 120},
        "Mercedes-Benz O500 RSD / OM457 360 HP":  {"config": "4patas", "medida": "295/80 R22.5", "vida_km": 130000, "presion_dir": 115, "presion_trac": 113},
        "Mercedes-Benz O500 RSD / OM457 410 HP":  {"config": "4patas", "medida": "295/80 R22.5", "vida_km": 140000, "presion_dir": 115, "presion_trac": 113},
        "Mercedes-Benz O500 RSD / OM457 422 HP":  {"config": "4patas", "medida": "295/80 R22.5", "vida_km": 140000, "presion_dir": 115, "presion_trac": 113},
        "Mercedes-Benz Sprinter / OM651 / OM642": {"config": "4x2", "medida": "225/75 R16", "vida_km": 80000, "presion_dir": 65, "presion_trac": 80},

        # Volvo
        "Volvo B430R / D11A 430 HP": {"config": "4patas", "medida": "295/80 R22.5", "vida_km": 150000, "presion_dir": 115, "presion_trac": 113},
        "Volvo B420R / D11A 410 HP": {"config": "6x2", "medida": "295/80 R22.5", "vida_km": 140000, "presion_dir": 115, "presion_trac": 125},

        # Otros
        "Volkswagen 9.150 / 9.160 OD (Senior)": {"config": "4x2", "medida": "215/75 R17.5", "vida_km": 100000, "presion_dir": 90, "presion_trac": 100},
        "Agrale Volare W / WL":                 {"config": "4x2", "medida": "215/75 R17.5", "vida_km": 90000, "presion_dir": 90, "presion_trac": 100},
        "Hyundai H350 / H1 (minibús)":          {"config": "4x2", "medida": "195/75 R16", "vida_km": 70000, "presion_dir": 50, "presion_trac": 65},
    }

    for plan in PLANES_PREDEFINIDOS:
        nuevo, plan_id = cargar_plan(plan)
        estado = "creado" if nuevo else "ya existía"
        print(f"  · {plan['nombre']} → {estado} (id={plan_id})")

        # Configurar neumáticos para este plan
        nc = configs_neumaticos.get(plan["nombre"])
        if nc:
            crear_config_neumaticos(
                plan_id, nc["config"], nc["medida"],
                nc["presion_dir"], nc["presion_trac"], nc["vida_km"]
            )


if __name__ == "__main__":
    from database import inicializar_db
    inicializar_db()
    cargar_planes_default()
