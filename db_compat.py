"""
db_compat.py — Capa de compatibilidad SQLite ←→ PostgreSQL

Permite que el mismo código funcione con:
  - SQLite  (local, para desarrollo en tu PC)
  - PostgreSQL (en la nube / Render, para producción)

La detección es automática:
  - Si existe la variable de entorno DATABASE_URL → usa PostgreSQL
  - Si no → usa SQLite (archivo local)

Traduce automáticamente:
  - Placeholders:  ?  →  %s   (PostgreSQL usa %s)
  - row_factory para acceso por nombre de columna (como sqlite3.Row)
  - lastrowid  →  RETURNING id
"""

import os
import re

# ¿Tenemos PostgreSQL configurado?
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USE_POSTGRES = bool(DATABASE_URL)

if USE_POSTGRES:
    try:
        import psycopg2
        import psycopg2.extras
        import psycopg2.pool
    except ImportError:
        raise ImportError(
            "DATABASE_URL está configurada (modo PostgreSQL) pero psycopg2 no está "
            "instalado. Ejecutá: pip install psycopg2-binary"
        )
    # Render a veces da la URL como "postgres://" pero psycopg2 quiere "postgresql://"
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

    # Pool de conexiones: reutiliza conexiones ya abiertas en vez de crear una
    # nueva en cada consulta. Abrir una conexión a través del océano (Brasil)
    # es lo más lento; el pool elimina ese costo y acelera mucho el sistema.
    _POOL = None
    def _get_pool():
        global _POOL
        if _POOL is None:
            _POOL = psycopg2.pool.ThreadedConnectionPool(
                minconn=1, maxconn=6, dsn=DATABASE_URL,
                # keepalives: mantienen viva la conexión para que Supabase no la
                # corte por inactividad (evita reconexiones lentas).
                keepalives=1, keepalives_idle=30,
                keepalives_interval=10, keepalives_count=5,
                connect_timeout=10,
            )
        return _POOL
else:
    import sqlite3
    DB_PATH = os.environ.get("DB_PATH", "flota_santaniana.db")


# ───────────────────────────────────────────────────────────────────────────
#  Wrappers que imitan la API de sqlite3 pero funcionan con ambos motores
# ───────────────────────────────────────────────────────────────────────────

def _traducir_sql(sql):
    """Convierte SQL de SQLite a PostgreSQL cuando hace falta."""
    if not USE_POSTGRES:
        return sql

    # 1. Placeholders ? → %s
    #    (cuidado de no tocar ? dentro de strings, pero en este proyecto
    #     no hay ? literales en strings SQL, así que es seguro)
    sql = sql.replace("?", "%s")

    # 2. AUTOINCREMENT → (PostgreSQL usa SERIAL)
    sql = re.sub(r"INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT",
                 "SERIAL PRIMARY KEY", sql, flags=re.IGNORECASE)

    # 3. date('now') → CURRENT_DATE  ;  datetime('now') → CURRENT_TIMESTAMP
    sql = re.sub(r"date\('now'\)", "CURRENT_DATE", sql, flags=re.IGNORECASE)
    sql = re.sub(r"datetime\('now'\)", "CURRENT_TIMESTAMP", sql, flags=re.IGNORECASE)

    # 4. julianday(a) - julianday(b)  →  diferencia de días en PostgreSQL
    #    julianday(fecha) - julianday('now')  →  (fecha::date - CURRENT_DATE)
    #    Lo manejamos con un patrón específico:
    sql = re.sub(
        r"julianday\(([^)]+)\)\s*-\s*julianday\('now'\)",
        r"(\1)::date - CURRENT_DATE",
        sql, flags=re.IGNORECASE)
    sql = re.sub(
        r"CAST\(\s*julianday\(([^)]+)\)\s*-\s*julianday\('now'\)\s*AS\s+INTEGER\)",
        r"((\1)::date - CURRENT_DATE)",
        sql, flags=re.IGNORECASE)

    # 5. INSERT OR IGNORE / INSERT OR REPLACE
    sql = re.sub(r"INSERT\s+OR\s+IGNORE", "INSERT", sql, flags=re.IGNORECASE)
    sql = re.sub(r"INSERT\s+OR\s+REPLACE", "INSERT", sql, flags=re.IGNORECASE)

    return sql


class _CursorWrapper:
    """Envuelve un cursor para traducir SQL y emular lastrowid."""
    def __init__(self, cursor):
        self._cur = cursor
        self.lastrowid = None

    def execute(self, sql, params=()):
        sql_t = _traducir_sql(sql)
        # psycopg2 interpreta '%' como inicio de placeholder. Si el SQL no lleva
        # parámetros (ej: CREATE TABLE con un '%' en un comentario), hay que
        # escapar los '%' literales duplicándolos para que no rompa.
        if USE_POSTGRES and (not params) and "%" in sql_t:
            sql_t = sql_t.replace("%", "%%")
        upper = sql_t.strip().upper()
        # Para INSERT en PostgreSQL, capturar el id con RETURNING (cuando aplica)
        if USE_POSTGRES and upper.startswith("INSERT"):
            ya_tiene_returning = "RETURNING" in upper
            # No agregar RETURNING si:
            #  - ya lo tiene
            #  - es un upsert con ON CONFLICT (la tabla puede no tener columna id,
            #    o el id no es lo que interesa)
            tiene_on_conflict = "ON CONFLICT" in upper
            if ya_tiene_returning or tiene_on_conflict:
                self._cur.execute(sql_t, params)
                if ya_tiene_returning:
                    try:
                        row = self._cur.fetchone()
                        if row:
                            self.lastrowid = row[0] if not isinstance(row, dict) else row.get("id")
                    except Exception:
                        self.lastrowid = None
                return self
            # INSERT normal: agregar RETURNING id para emular lastrowid
            sql_ret = sql_t.rstrip().rstrip(";") + " RETURNING id"
            self._cur.execute(sql_ret, params)
            try:
                row = self._cur.fetchone()
                if row:
                    self.lastrowid = row[0] if not isinstance(row, dict) else row.get("id")
            except Exception:
                self.lastrowid = None
            return self
        else:
            self._cur.execute(sql_t, params)
            if not USE_POSTGRES:
                self.lastrowid = self._cur.lastrowid
            return self

    def executemany(self, sql, seq):
        self._cur.executemany(_traducir_sql(sql), seq)
        return self

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def __iter__(self):
        return iter(self._cur)


class _ConnectionWrapper:
    """Envuelve la conexión para devolver cursores traductores."""
    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=()):
        """Atajo: crea cursor, ejecuta y lo devuelve (como sqlite3)."""
        cur = self.cursor()
        try:
            cur.execute(sql, params)
        except Exception as e:
            # En PostgreSQL, si una sentencia falla hay que hacer rollback
            # o la transacción queda "abortada" y bloquea todo lo demás.
            if USE_POSTGRES:
                # Si la conexión murió (la cortó Supabase), reemplazarla y
                # reintentar UNA vez con una conexión fresca.
                if isinstance(e, (psycopg2.OperationalError, psycopg2.InterfaceError)):
                    try:
                        self._conn = psycopg2.connect(DATABASE_URL)
                        cur = self.cursor()
                        cur.execute(sql, params)
                        return cur
                    except Exception:
                        pass
                try:
                    self._conn.rollback()
                except Exception:
                    pass
            raise
        return cur

    def executemany(self, sql, seq):
        cur = self.cursor()
        try:
            cur.executemany(sql, seq)
        except Exception:
            if USE_POSTGRES:
                try:
                    self._conn.rollback()
                except Exception:
                    pass
            raise
        return cur

    def cursor(self):
        if USE_POSTGRES:
            return _CursorWrapper(
                self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor))
        else:
            return _CursorWrapper(self._conn.cursor())

    def commit(self):
        self._conn.commit()

    def close(self):
        if USE_POSTGRES:
            # Devolver la conexión al pool para reutilizarla (no cerrarla).
            # Antes hacemos rollback de cualquier transacción pendiente para
            # que la conexión vuelva limpia al pool.
            try:
                self._conn.rollback()
            except Exception:
                pass
            try:
                _get_pool().putconn(self._conn)
            except Exception:
                # Si el pool falla, cerrar la conexión directamente
                try:
                    self._conn.close()
                except Exception:
                    pass
        else:
            self._conn.close()

    def __getattr__(self, name):
        return getattr(self._conn, name)


def get_connection():
    """Devuelve una conexión lista para usar, con acceso por nombre de columna.
    En PostgreSQL la saca del pool (reutiliza conexiones = mucho más rápido)."""
    if USE_POSTGRES:
        try:
            conn = _get_pool().getconn()
            return _ConnectionWrapper(conn)
        except Exception:
            # Si el pool falla, crear conexión directa como respaldo
            conn = psycopg2.connect(DATABASE_URL)
            return _ConnectionWrapper(conn)
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return _ConnectionWrapper(conn)


def motor_actual():
    """Devuelve 'PostgreSQL' o 'SQLite' según lo que se esté usando."""
    return "PostgreSQL" if USE_POSTGRES else "SQLite"


# ───────────────────────────────────────────────────────────────────────────
#  Excepciones agnósticas (funcionan con ambos motores)
# ───────────────────────────────────────────────────────────────────────────

if USE_POSTGRES:
    IntegrityError = psycopg2.IntegrityError
    OperationalError = psycopg2.OperationalError
    ProgrammingError = psycopg2.ProgrammingError
else:
    IntegrityError = sqlite3.IntegrityError
    OperationalError = sqlite3.OperationalError
    ProgrammingError = sqlite3.ProgrammingError


def es_error_duplicado(exc):
    """True si la excepción es por violación de UNIQUE/PRIMARY KEY."""
    return isinstance(exc, IntegrityError)


def columnas_de_tabla(conn, tabla):
    """Devuelve la lista de nombres de columnas de una tabla (ambos motores)."""
    if USE_POSTGRES:
        rows = conn.execute("""
            SELECT column_name AS name FROM information_schema.columns
            WHERE table_name = %s
        """, (tabla,)).fetchall()
    else:
        rows = conn.execute(f"PRAGMA table_info({tabla})").fetchall()
    return [r["name"] for r in rows]
