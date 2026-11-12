"""Permisos por sección.

Un usuario del rol Taller puede tener acceso a todo (como siempre) o solo a
las secciones que el administrador le tilde. La lista vacía quiere decir
"todo": así los usuarios que ya existían siguen viendo exactamente lo mismo.

El menú se arma desde acá y el servidor también controla desde acá: ocultar
un botón no alcanza, porque cualquiera puede pedir los datos directamente. Los
módulos donde se mueve plata o información sensible (corporativos, turismo,
compras, reportes) se bloquean también en el servidor. Flota y Taller usan
datos compartidos por todo el sistema (la lista de coches, por ejemplo), así
que ahí alcanza con no mostrarlos.
"""

# Las secciones que se pueden habilitar, agrupadas igual que el menú.
# Auditoría y Sistema no están: son exclusivas de administración y auditoría.
GRUPOS_SECCIONES = [
    ("General", [
        ("dashboard", "Dashboard"),
        ("vehiculos", "Vehículos"),
        ("documentos", "Documentos"),
    ]),
    ("Operación", [
        ("trafico", "Tráfico"),
        ("servicios", "Servicios"),
        ("comb_rendicion", "Rendición de combustible"),
    ]),
    ("Taller", [
        ("ots", "Órdenes de Trabajo"),
        ("personal", "Órdenes: pestaña Personal de taller"),
        ("tablero_taller", "Órdenes: pestaña Tablero de control (plan vs real)"),
        ("coches", "Coches: ficha de cada coche (historial, preventivo, neumáticos) y agenda del taller"),
        ("costos", "Coches: pestaña Costos"),
        ("kpis", "Coches: pestaña KPIs"),
    ]),
    ("Contabilidad", [
        ("contabilidad", "Contabilidad y tesorería"),
    ]),
    ("Compras", [
        ("compras", "Compras / Depósito"),
        ("repuestos", "Inventario Repuestos"),
        ("proveedores", "Proveedores"),
        ("inventario_neu", "Inventario de neumáticos"),
    ]),
    ("Tesorería", [
        ("cajas", "Tesorería: cajas, flujo, pagos, cheques y conciliación"),
    ]),
    ("Reportes", [
        ("gerencial", "Reporte gerencial"),
        ("oee", "OEE de flota"),
    ]),
    ("Corporativos", [
        ("corp_asignacion", "Asignación del día"),
        ("corp_resumen", "Resumen de rendiciones"),
        ("corp_historial", "Histórico de pagos"),
        ("corp_empresas", "Control por empresa"),
        ("corp_servicios", "Servicios"),
        ("corp_ranking", "Ranking de choferes"),
        ("corp_combustible", "Combustible corporativos"),
        ("corp_cargas", "Cargas"),
    ]),
    ("Turismo", [
        ("turismo_agenda", "Agenda de servicios"),
        ("turismo_rendiciones", "Rendiciones de viaje"),
        ("turismo", "Presupuestos"),
    ]),
    ("Comercial", [
        ("agencias", "Agencias y contratos"),
    ]),
]

# Taller quedó en tres secciones. Lo que antes eran secciones sueltas por coche
# ahora vive adentro de "Coches": quien tenía alguna de las viejas, tiene Coches.
SECCIONES_VIEJAS = {"mantenimientos": "coches", "mantenimiento": "coches", "neumaticos": "coches",
                    "correctivos": "coches", "planes": "coches", "historial_carga": "coches"}

SECCIONES_VALIDAS = {clave for _, secs in GRUPOS_SECCIONES for clave, _ in secs}
ORDEN = [clave for _, secs in GRUPOS_SECCIONES for clave, _ in secs]

SECCIONES_CORP = {"corp_asignacion", "corp_resumen", "corp_historial", "corp_empresas", "corp_servicios", "corp_ranking",
                  "corp_combustible", "corp_cargas"}

# Rutas de la API que pertenecen a cada módulo sensible. Si el usuario no
# tiene ninguna sección del módulo, el servidor le niega esas rutas.
MODULOS_API = [
    (SECCIONES_CORP,
     ("/api/corp/", "/api/combustible/control", "/api/consumo/")),
    ({"turismo_agenda", "turismo_rendiciones", "turismo"},
     ("/api/turismo",)),
    ({"trafico"},
     ("/api/trafico",)),
    ({"servicios"},
     ("/api/servicios",)),
    ({"comb_rendicion"},
     ("/api/comb_rend",)),
    ({"contabilidad"}, ("/api/contabilidad",)),
    ({"compras", "repuestos", "proveedores"},
     ("/api/compras", "/api/repuestos")),
    ({"agencias"},
     ("/api/agencias",)),
    ({"cajas"},
     ("/api/cajas", "/api/teso/")),
    ({"gerencial", "oee"},
     ("/api/reporte_gerencial", "/api/exportar_reporte_gerencial",
      "/api/dossier", "/api/oee")),
]


def normalizar(secciones):
    """Deja solo secciones que existen, sin repetir y en el orden del menú."""
    if isinstance(secciones, str):
        secciones = [s for s in secciones.split(",")]
    pedidas = {str(s).strip() for s in (secciones or []) if str(s).strip()}
    pedidas = {SECCIONES_VIEJAS.get(s, s) for s in pedidas}
    return [s for s in ORDEN if s in pedidas]


def a_texto(secciones):
    return ",".join(normalizar(secciones))


def desde_texto(texto):
    return normalizar(texto or "")


def ruta_permitida(path, secciones):
    """Si un usuario con esas secciones puede usar esa ruta de la API.

    Sin secciones (lista vacía) no hay restricción: acceso completo.
    """
    if not secciones:
        return True
    tiene = set(secciones)
    for secs_modulo, prefijos in MODULOS_API:
        if any(path.startswith(p) for p in prefijos):
            return bool(secs_modulo & tiene)
    return True


def tiene_corp(secciones):
    return bool(SECCIONES_CORP & set(secciones or []))
