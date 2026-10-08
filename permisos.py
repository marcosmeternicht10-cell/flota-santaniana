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
    ("Vehículo", [
        ("servicios", "Servicios"),
        ("costos", "Costos"),
        ("kpis", "KPIs"),
    ]),
    ("Taller", [
        ("ots", "Órdenes de Trabajo"),
        ("mantenimientos", "Mantenimientos"),
        ("mantenimiento", "Preventivo"),
        ("neumaticos", "Neumáticos"),
        ("correctivos", "Correctivos"),
        ("planes", "Planes"),
        ("inventario_neu", "Inventario neumáticos"),
        ("historial_carga", "Historial por coche"),
    ]),
    ("Compras", [
        ("compras", "Compras / Depósito"),
        ("repuestos", "Inventario Repuestos"),
        ("proveedores", "Proveedores"),
    ]),
    ("Reportes", [
        ("gerencial", "Reporte gerencial"),
        ("oee", "OEE de flota"),
    ]),
    ("Corporativos", [
        ("corp_resumen", "Resumen de rendiciones"),
        ("corp_historial", "Histórico de pagos"),
        ("corp_empresas", "Control por empresa"),
        ("corp_combustible", "Combustible corporativos"),
        ("corp_cargas", "Cargas"),
    ]),
    ("Turismo", [
        ("turismo_agenda", "Agenda de servicios"),
        ("turismo", "Presupuestos"),
    ]),
]

SECCIONES_VALIDAS = {clave for _, secs in GRUPOS_SECCIONES for clave, _ in secs}
ORDEN = [clave for _, secs in GRUPOS_SECCIONES for clave, _ in secs]

SECCIONES_CORP = {"corp_resumen", "corp_historial", "corp_empresas", "corp_combustible", "corp_cargas"}

# Rutas de la API que pertenecen a cada módulo sensible. Si el usuario no
# tiene ninguna sección del módulo, el servidor le niega esas rutas.
MODULOS_API = [
    (SECCIONES_CORP,
     ("/api/corp/", "/api/combustible/control", "/api/consumo/")),
    ({"turismo_agenda", "turismo"},
     ("/api/turismo",)),
    ({"compras", "repuestos", "proveedores"},
     ("/api/compras", "/api/repuestos")),
    ({"gerencial", "oee"},
     ("/api/reporte_gerencial", "/api/exportar_reporte_gerencial",
      "/api/dossier", "/api/oee")),
]


def normalizar(secciones):
    """Deja solo secciones que existen, sin repetir y en el orden del menú."""
    if isinstance(secciones, str):
        secciones = [s for s in secciones.split(",")]
    pedidas = {str(s).strip() for s in (secciones or []) if str(s).strip()}
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
