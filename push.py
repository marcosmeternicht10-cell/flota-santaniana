"""
push.py — Notificaciones en el celular (La Santaniana)

Le manda avisos al celular de un usuario aunque la app esté cerrada: "Tu
servicio del martes 3/11 · 05:30 Asunción → Concepción · Coche 21037".

Cómo funciona (Web Push, el estándar que usan Chrome y Android):
  1. El celular pide permiso y le da al sistema una "dirección" para avisarle
     (la suscripción). Se guarda en push_subs, atada al usuario.
  2. Cuando hay algo que avisar, el servidor cifra el mensaje con las claves de
     esa suscripción y lo manda al servicio de avisos de Google, que lo entrega.
  3. El service worker (/sw.js) lo recibe y muestra la notificación.

Las claves del servidor (VAPID) se generan solas la primera vez y quedan
guardadas en la base: no hay que configurar nada en Render. Si se borran,
los celulares tienen que volver a activar los avisos.

Está hecho a mano sobre la librería 'cryptography' (RFC 8291 y RFC 8292) en vez
de usar pywebpush, porque esa depende de un paquete que no se instala en las
versiones nuevas de Python.

  enviar(usuario_ids, titulo, cuerpo, url="/", tag="")   en segundo plano
  enviar_ya(...)                                          lo mismo, esperando el resultado

Rutas (para el usuario con sesión):
  GET  /api/push/clave      la clave pública para suscribirse
  POST /api/push/suscribir  guarda la suscripción de este celular
  POST /api/push/baja       la borra
  POST /api/push/probar     manda un aviso de prueba a mis celulares
"""

import base64
import json
import os
import struct
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from flask import Blueprint, jsonify, request, session

from db_compat import get_connection, USE_POSTGRES
from hora_local import ahora_iso

bp_push = Blueprint("push", __name__)

PK = "SERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"
CONTACTO = "mailto:avisos@lasantaniana.com.py"   # lo pide el estándar; Google lo usa si hay problemas
TTL = 24 * 3600                                  # si el celular está apagado, el aviso espera hasta un día

_claves = {}                                     # se cargan una vez por proceso


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _deb64(s):
    s = str(s or "")
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def init_push():
    conn = get_connection()
    conn.execute("""CREATE TABLE IF NOT EXISTS push_config (
        clave TEXT PRIMARY KEY,
        valor TEXT NOT NULL)""")
    conn.execute(f"""CREATE TABLE IF NOT EXISTS push_subs (
        id {PK},
        usuario_id INTEGER NOT NULL,
        endpoint TEXT NOT NULL UNIQUE,
        p256dh TEXT NOT NULL,
        auth TEXT NOT NULL,
        equipo TEXT DEFAULT '',
        creado_el TEXT DEFAULT '',
        ultimo_ok TEXT DEFAULT '',
        fallos INTEGER DEFAULT 0)""")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_push_subs_usuario ON push_subs (usuario_id)")
    conn.commit()
    conn.close()


# ── Claves del servidor (VAPID) ─────────────────────────────────────────────

def _cargar_claves():
    if _claves:
        return _claves
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    conn = get_connection()
    try:
        r = conn.execute("SELECT valor FROM push_config WHERE clave='vapid_privada'").fetchone()
        if r:
            priv = serialization.load_pem_private_key(r["valor"].encode(), password=None)
        else:
            priv = ec.generate_private_key(ec.SECP256R1())
            pem = priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                     serialization.NoEncryption()).decode()
            conn.execute("""INSERT INTO push_config (clave, valor) VALUES ('vapid_privada', ?)
                            ON CONFLICT (clave) DO NOTHING""", (pem,))
            conn.commit()
            # Si otro proceso la creó al mismo tiempo, quedarse con la guardada
            r = conn.execute("SELECT valor FROM push_config WHERE clave='vapid_privada'").fetchone()
            priv = serialization.load_pem_private_key(r["valor"].encode(), password=None)
    finally:
        conn.close()
    pub = priv.public_key().public_bytes(serialization.Encoding.X962,
                                         serialization.PublicFormat.UncompressedPoint)
    _claves.update(privada=priv, publica=pub, publica_b64=_b64(pub))
    return _claves


def clave_publica():
    return _cargar_claves()["publica_b64"]


def _jwt_vapid(endpoint):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    k = _cargar_claves()
    u = urlparse(endpoint)
    cab = _b64(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    datos = _b64(json.dumps({"aud": f"{u.scheme}://{u.netloc}", "exp": int(time.time()) + 12 * 3600,
                             "sub": CONTACTO}, separators=(",", ":")).encode())
    firmar = f"{cab}.{datos}".encode()
    r, s = decode_dss_signature(k["privada"].sign(firmar, ec.ECDSA(hashes.SHA256())))
    firma = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    return f"{cab}.{datos}.{_b64(firma)}"


# ── Cifrado del mensaje (RFC 8291, aes128gcm) ───────────────────────────────

def _hmac(clave, datos):
    import hmac
    import hashlib
    return hmac.new(clave, datos, hashlib.sha256).digest()


def cifrar(mensaje, p256dh, auth, sal=None, efimera=None):
    """Cifra el mensaje para una suscripción. Devuelve el cuerpo listo para mandar.
    (sal y efimera solo para las pruebas)."""
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    ua_pub = _deb64(p256dh)
    secreto = _deb64(auth)
    efimera = efimera or ec.generate_private_key(ec.SECP256R1())
    as_pub = efimera.public_key().public_bytes(serialization.Encoding.X962,
                                               serialization.PublicFormat.UncompressedPoint)
    compartido = efimera.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_pub))
    prk_clave = _hmac(secreto, compartido)
    ikm = _hmac(prk_clave, b"WebPush: info\x00" + ua_pub + as_pub + b"\x01")[:32]
    sal = sal or os.urandom(16)
    prk = _hmac(sal, ikm)
    cek = _hmac(prk, b"Content-Encoding: aes128gcm\x00\x01")[:16]
    nonce = _hmac(prk, b"Content-Encoding: nonce\x00\x01")[:12]
    cifrado = AESGCM(cek).encrypt(nonce, mensaje + b"\x02", None)
    return sal + struct.pack(">I", 4096) + bytes([len(as_pub)]) + as_pub + cifrado


def _mandar_uno(sub, datos):
    """Manda un aviso a una suscripción. Devuelve 'ok', 'vencida' o 'error'."""
    k = _cargar_claves()
    cuerpo = cifrar(datos, sub["p256dh"], sub["auth"])
    req = urllib.request.Request(sub["endpoint"], data=cuerpo, method="POST", headers={
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
        "TTL": str(TTL),
        "Urgency": "high",
        "Authorization": f"vapid t={_jwt_vapid(sub['endpoint'])}, k={k['publica_b64']}",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return "ok" if 200 <= r.status < 300 else "error"
    except urllib.error.HTTPError as e:
        return "vencida" if e.code in (404, 410) else "error"
    except Exception:
        return "error"


# ── Envío ───────────────────────────────────────────────────────────────────

def enviar_ya(usuario_ids, titulo, cuerpo, url="/", tag=""):
    """Manda el aviso a todos los celulares de esos usuarios. Devuelve cuántos llegaron."""
    ids = sorted({int(i) for i in usuario_ids if i})
    if not ids:
        return {"enviados": 0, "fallidos": 0, "sin_celular": 0}
    conn = get_connection()
    try:
        marcas = ",".join("?" * len(ids))
        subs = [dict(r) for r in conn.execute(
            f"SELECT * FROM push_subs WHERE usuario_id IN ({marcas})", ids).fetchall()]
    finally:
        conn.close()
    datos = json.dumps({"titulo": titulo, "cuerpo": cuerpo, "url": url, "tag": tag},
                       ensure_ascii=False).encode()
    ok, mal, vencidas = [], [], []
    for s in subs:
        r = _mandar_uno(s, datos)
        (ok if r == "ok" else vencidas if r == "vencida" else mal).append(s["id"])
    conn = get_connection()
    try:
        cuando = ahora_iso()
        for i in ok:
            conn.execute("UPDATE push_subs SET ultimo_ok=?, fallos=0 WHERE id=?", (cuando, i))
        for i in mal:
            conn.execute("UPDATE push_subs SET fallos=COALESCE(fallos,0)+1 WHERE id=?", (i,))
        for i in vencidas:                       # el celular desinstaló o sacó el permiso
            conn.execute("DELETE FROM push_subs WHERE id=?", (i,))
        conn.execute("DELETE FROM push_subs WHERE fallos >= 20")
        conn.commit()
    finally:
        conn.close()
    con_cel = {s["usuario_id"] for s in subs}
    return {"enviados": len(ok), "fallidos": len(mal) + len(vencidas),
            "sin_celular": len([i for i in ids if i not in con_cel])}


def enviar(usuario_ids, titulo, cuerpo, url="/", tag=""):
    """Igual que enviar_ya pero sin hacer esperar a quien publica."""
    ids = list(usuario_ids or [])
    if not ids:
        return
    threading.Thread(target=lambda: _seguro(enviar_ya, ids, titulo, cuerpo, url, tag), daemon=True).start()


def enviar_varios(avisos):
    """Una tanda de avisos distintos [(usuario_id, titulo, cuerpo, url, tag)], en segundo plano."""
    avisos = [a for a in avisos or [] if a and a[0]]
    if not avisos:
        return

    def _todo():
        for uid, titulo, cuerpo, url, tag in avisos:
            _seguro(enviar_ya, [uid], titulo, cuerpo, url, tag)
    threading.Thread(target=_todo, daemon=True).start()


def _seguro(f, *a):
    try:
        return f(*a)
    except Exception as e:                       # un aviso que falla nunca rompe nada
        print("push:", e)


def con_avisos(usuario_ids=None):
    """{usuario_id: cantidad de celulares con avisos activos}."""
    conn = get_connection()
    try:
        filas = conn.execute("SELECT usuario_id, COUNT(*) AS n FROM push_subs GROUP BY usuario_id").fetchall()
    finally:
        conn.close()
    d = {r["usuario_id"]: r["n"] for r in filas}
    return d if usuario_ids is None else {i: d.get(i, 0) for i in usuario_ids}


# ── Rutas ───────────────────────────────────────────────────────────────────

def _uid():
    return session.get("usuario_id")


@bp_push.route("/api/push/clave", methods=["GET"])
def api_clave():
    if not _uid():
        return jsonify({"ok": False}), 401
    try:
        return jsonify({"ok": True, "clave": clave_publica()})
    except Exception as e:
        return jsonify({"ok": False, "msg": f"Los avisos no están disponibles ({str(e)[:60]})"}), 500


@bp_push.route("/api/push/suscribir", methods=["POST"])
def api_suscribir():
    if not _uid():
        return jsonify({"ok": False}), 401
    d = request.get_json(silent=True) or {}
    sub = d.get("sub") or {}
    endpoint = str(sub.get("endpoint") or "")
    claves = sub.get("keys") or {}
    if not endpoint.startswith("https://") or not claves.get("p256dh") or not claves.get("auth"):
        return jsonify({"ok": False, "msg": "Suscripción inválida"}), 400
    equipo = str(request.headers.get("User-Agent") or "")[:160]
    conn = get_connection()
    try:
        # Un celular es de quien entró último en él
        conn.execute("DELETE FROM push_subs WHERE endpoint=?", (endpoint,))
        conn.execute("""INSERT INTO push_subs (usuario_id, endpoint, p256dh, auth, equipo, creado_el)
                        VALUES (?,?,?,?,?,?)""",
                     (_uid(), endpoint, claves["p256dh"], claves["auth"], equipo, ahora_iso()))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True})


@bp_push.route("/api/push/baja", methods=["POST"])
def api_baja():
    if not _uid():
        return jsonify({"ok": False}), 401
    endpoint = str((request.get_json(silent=True) or {}).get("endpoint") or "")
    conn = get_connection()
    try:
        conn.execute("DELETE FROM push_subs WHERE endpoint=? AND usuario_id=?", (endpoint, _uid()))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True})


@bp_push.route("/api/push/probar", methods=["POST"])
def api_probar():
    if not _uid():
        return jsonify({"ok": False}), 401
    nombre = (session.get("nombre") or session.get("usuario") or "").split(",")[-1].strip().title()
    r = enviar_ya([_uid()], "Avisos activados",
                  f"Listo{', ' + nombre if nombre else ''}: acá te va a llegar cada servicio que te toque.",
                  url=request.headers.get("Referer") or "/", tag="prueba")
    if not r["enviados"]:
        return jsonify({"ok": False, "msg": "No llegó a tu celular. Probá desactivar y volver a activar los avisos."}), 400
    return jsonify({"ok": True, **r})
