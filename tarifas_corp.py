"""
tarifas_corp.py — Tarifas editables de las rendiciones de corporativos.

Reemplaza las constantes fijas de corporativos.py por una tabla que se edita
desde la pantalla "Corporativos → Resumen de rendiciones".

Reglas que respeta:
  - cada tramo tiene un monto de viaje completo
  - entrante o saliente = la mitad exacta de ese monto
  - suspendido = 0

Para engancharlo:
  1. from tarifas_corp import tarifas_bp, init_tarifas, monto_rendicion
  2. app.register_blueprint(tarifas_bp)
  3. init_tarifas()  -> crea la tabla y la siembra la primera vez
  4. en corporativos.py, donde hoy calcula el monto, llamar a monto_rendicion()

OJO con los dos imports de abajo: ajustá los nombres a los que realmente usás
(la función de conexión y el diccionario de tramos por cliente).
"""

from flask import Blueprint, jsonify, request, session

from db_compat import get_conn          # <-- ajustar si tu helper se llama distinto
from corporativos import TRAMOS_POR_CLIENTE   # <-- ajustar al nombre real del catálogo

tarifas_bp = Blueprint("tarifas_corp", __name__)

TARIFA_ADMIN_DEFAULT = 150_000
TARIFA_COMUN_DEFAULT = 75_000

# Cache en memoria: {(cliente, tramo): monto_completo}
_tarifas = None


# ── Siembra inicial ────────────────────────────────────────────────────────

def _parece_administrativo(tramo: str) -> bool:
    """Heurística SOLO para la siembra inicial.

    Después Marcos corrige lo que haga falta desde el panel, así que no
    necesita ser perfecta. Acierta con ADM RUTA 1, ADMIN. SAJONIA, HOTEL 1,
    y descarta TURNO A RUTA 1 o TRAMO 3 porque no arrancan con ADM.
    """
    t = (tramo or "").strip().upper()
    return t.startswith("ADM") or t.startswith("HOTEL")


def init_tarifas():
    """Crea la tabla si no existe y la siembra con el catálogo de tramos."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tarifas_corp (
                id              SERIAL PRIMARY KEY,
                cliente         TEXT NOT NULL,
                tramo           TEXT NOT NULL,
                monto_completo  INTEGER NOT NULL,
                actualizado_en  TIMESTAMP,
                actualizado_por TEXT,
                UNIQUE (cliente, tramo)
            )
        """)

        for cliente, tramos in TRAMOS_POR_CLIENTE.items():
            for tramo in tramos:
                monto = (TARIFA_ADMIN_DEFAULT if _parece_administrativo(tramo)
                         else TARIFA_COMUN_DEFAULT)
                cur.execute("""
                    INSERT INTO tarifas_corp (cliente, tramo, monto_completo)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (cliente, tramo) DO NOTHING
                """, (cliente, tramo, monto))

        conn.commit()
    _invalidar_cache()


# ── Lectura ────────────────────────────────────────────────────────────────

def _invalidar_cache():
    global _tarifas
    _tarifas = None


def _cargar():
    global _tarifas
    if _tarifas is None:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT cliente, tramo, monto_completo FROM tarifas_corp")
            _tarifas = {(c, t): m for c, t, m in cur.fetchall()}
    return _tarifas


def monto_rendicion(cliente: str, tramo: str, estado: str) -> int:
    """Monto de una rendición según cliente, tramo y estado.

    estado: completado | entrante | saliente | suspendido
    """
    if estado == "suspendido":
        return 0

    base = _cargar().get((cliente, tramo))
    if base is None:
        # Tramo nuevo que todavía no está en la tabla: no lo inventamos alto.
        base = TARIFA_COMUN_DEFAULT

    return base if estado == "completado" else base // 2


# ── Endpoints ──────────────────────────────────────────────────────────────

def _es_admin():
    return session.get("rol") == "admin"   # <-- ajustar a tu control de roles


@tarifas_bp.route("/api/corp/tarifas", methods=["GET"])
def listar_tarifas():
    if not _es_admin():
        return jsonify({"error": "Solo el administrador puede ver las tarifas"}), 403

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT cliente, tramo, monto_completo
            FROM tarifas_corp
            ORDER BY cliente, tramo
        """)
        filas = cur.fetchall()

    por_cliente = {}
    for cliente, tramo, monto in filas:
        por_cliente.setdefault(cliente, []).append({
            "tramo": tramo,
            "monto_completo": monto,
            "monto_mitad": monto // 2,
        })

    return jsonify({"clientes": por_cliente})


@tarifas_bp.route("/api/corp/tarifas", methods=["POST"])
def guardar_tarifas():
    if not _es_admin():
        return jsonify({"error": "Solo el administrador puede cambiar las tarifas"}), 403

    cambios = (request.get_json(silent=True) or {}).get("cambios", [])
    if not cambios:
        return jsonify({"guardados": 0, "mensaje": "No hubo cambios"})

    usuario = session.get("usuario", "?")
    guardados = 0

    with get_conn() as conn:
        cur = conn.cursor()
        for c in cambios:
            try:
                monto = int(c["monto_completo"])
            except (KeyError, TypeError, ValueError):
                continue
            if monto < 0 or monto > 5_000_000:
                continue          # descarta un cero de más pegado sin querer

            cur.execute("""
                UPDATE tarifas_corp
                SET monto_completo = %s,
                    actualizado_en = CURRENT_TIMESTAMP,
                    actualizado_por = %s
                WHERE cliente = %s AND tramo = %s
            """, (monto, usuario, c.get("cliente"), c.get("tramo")))
            guardados += cur.rowcount

        conn.commit()

    _invalidar_cache()
    return jsonify({
        "guardados": guardados,
        "mensaje": f"{guardados} tarifa(s) actualizada(s)",
    })
