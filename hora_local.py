"""
hora_local.py — La hora de Paraguay para todo el sistema

El servidor de Render corre en UTC, así que un pago hecho a las 9:39 de la
mañana quedaba guardado como 12:39. Este módulo centraliza la hora local para
que todo el sistema (pagos, entregas, auditoría, fotos) registre la hora real
de Paraguay.

Se usa la zona horaria oficial en vez de restar horas a mano: si el país
cambia la regla en el futuro, se ajusta solo.

Uso:
    from hora_local import ahora, hoy, ahora_iso
    fecha = ahora_iso()          # "2026-08-12T09:39:00"
    dia   = hoy()                # "2026-08-12"
"""

from datetime import datetime, timedelta, timezone

ZONA_PY = "America/Asuncion"
# Respaldo si el sistema no tiene la base de zonas horarias instalada.
# Paraguay usa UTC-3 desde que dejó de cambiar la hora en 2024.
OFFSET_PY = timezone(timedelta(hours=-3))

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo(ZONA_PY)
except Exception:
    _TZ = OFFSET_PY


def ahora():
    """Fecha y hora actual en Paraguay (con zona horaria)."""
    return datetime.now(_TZ)


def ahora_iso(con_segundos=True):
    """Fecha y hora local en texto, como se guarda en la base.
    Sin la marca de zona, para no romper las comparaciones ya existentes."""
    d = ahora().replace(tzinfo=None)
    return d.isoformat(timespec="seconds" if con_segundos else "minutes")


def hoy():
    """La fecha de hoy en Paraguay, en formato AAAA-MM-DD."""
    return ahora().date().isoformat()


def a_local(texto):
    """Convierte un horario que quedó guardado en UTC a hora de Paraguay.
    Sirve para corregir lo que ya está en la base. Si el texto no es una
    fecha válida, lo devuelve tal cual."""
    if not texto:
        return texto
    try:
        d = datetime.fromisoformat(str(texto).replace("Z", ""))
    except Exception:
        return texto
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(_TZ).replace(tzinfo=None).isoformat(timespec="seconds")
