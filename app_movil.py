"""
app_movil.py — La Santaniana como app instalable (celular y Play Store)

Lo que necesita Android para tratar el sistema como una app:

  /manifest.webmanifest           nombre, íconos, colores y cómo se abre (pantalla completa)
  /sw.js                          service worker: si no hay internet muestra un aviso
                                  en vez de la pantalla del dinosaurio
  /offline                        ese aviso
  /.well-known/assetlinks.json    la prueba de que la app de la Play Store y esta web
                                  son del mismo dueño (sin esto la app abre con la barra
                                  del navegador arriba)
  /privacidad                     política de privacidad (la Play Store la exige)

assetlinks se arma con dos variables de entorno que se cargan en Render
(Environment), sin tocar el código:

  ANDROID_PAQUETE   el "Package ID" que se eligió en PWABuilder (ej. py.com.lasantaniana.flota)
  ANDROID_HUELLAS   la huella SHA-256 de la firma; si son varias, separadas con coma
                    (la de tu llave y la de "App signing" de la Play Console)

  CONTACTO_PRIVACIDAD  (opcional) correo que aparece en la política de privacidad

Todas estas rutas son públicas (no piden login): Android y Google las leen
sin sesión.
"""

import json
import os

from flask import Blueprint, Response, abort, current_app, render_template_string, send_from_directory

bp_movil = Blueprint("movil", __name__)

RUTAS_PUBLICAS = ("/manifest.webmanifest", "/sw.js", "/offline", "/privacidad",
                  "/.well-known/assetlinks.json")

NOMBRE = "La Santaniana · Gestión de Flota"
NOMBRE_CORTO = "Santaniana"
COLOR_TEMA = "#1D344E"     # azul marino de la marca: la barra de arriba del celular
COLOR_FONDO = "#FFFFFF"    # la pantalla de carga: blanca, con el logo

# Si se cambia algo del service worker o de la pantalla sin internet, subir este número
VERSION_SW = "2"


def es_publica(path):
    return path in RUTAS_PUBLICAS


@bp_movil.route("/manifest.webmanifest")
def manifest():
    m = {
        "id": "/",
        "name": NOMBRE,
        "short_name": NOMBRE_CORTO,
        "description": "Sistema de gestión de flota de La Santaniana: taller, compras, tráfico, "
                       "corporativos, turismo y boletería.",
        "lang": "es-PY",
        "dir": "ltr",
        "start_url": "/?app=1",
        "scope": "/",
        "display": "standalone",
        "orientation": "any",
        "background_color": COLOR_FONDO,
        "theme_color": COLOR_TEMA,
        "categories": ["business", "productivity"],
        "icons": [
            {"src": "/static/app/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": "/static/app/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": "/static/app/icon-maskable-192.png", "sizes": "192x192", "type": "image/png",
             "purpose": "maskable"},
            {"src": "/static/app/icon-maskable-512.png", "sizes": "512x512", "type": "image/png",
             "purpose": "maskable"},
        ],
    }
    r = Response(json.dumps(m, ensure_ascii=False, indent=2), mimetype="application/manifest+json")
    r.headers["Cache-Control"] = "no-cache"
    return r


_SW = """// Service worker de La Santaniana (v%(v)s)
// No guarda datos del sistema: todo se pide siempre al servidor. Solo guarda la
// pantalla de "sin conexión" y el logo, para mostrarlos si no hay internet.
const CACHE = "santaniana-%(v)s";
const GUARDAR = ["/offline", "/static/app/icon-192.png"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(GUARDAR)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(caches.keys()
    .then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", e => {
  // Solo las pantallas (no la API, ni los archivos): si falla la red, el aviso
  if (e.request.mode !== "navigate") return;
  e.respondWith(fetch(e.request).catch(() => caches.match("/offline")));
});

// Los avisos que manda el sistema (servicio publicado, cambios)
self.addEventListener("push", e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (x) { d = { cuerpo: e.data ? e.data.text() : "" }; }
  e.waitUntil(self.registration.showNotification(d.titulo || "La Santaniana", {
    body: d.cuerpo || "",
    icon: "/static/app/icon-192.png",
    badge: "/static/app/badge-96.png",
    tag: d.tag || undefined,
    renotify: !!d.tag,
    data: { url: d.url || "/" },
    vibrate: [120, 60, 120],
  }));
});

// Tocar el aviso abre la app en la pantalla que corresponde
self.addEventListener("notificationclick", e => {
  e.notification.close();
  const url = new URL((e.notification.data && e.notification.data.url) || "/", self.location.origin).href;
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(ws => {
    for (const w of ws) {
      if (w.url.startsWith(self.location.origin)) { w.focus(); return w.navigate(url).catch(() => {}); }
    }
    return self.clients.openWindow(url);
  }));
});
"""


_ICONOS = {"icon-192.png", "icon-512.png", "icon-maskable-192.png", "icon-maskable-512.png",
           "apple-touch-icon.png", "favicon-48.png", "badge-96.png"}


@bp_movil.route("/static/app/<nombre>")
def icono(nombre):
    """Los íconos de la app: se buscan en static/app y, si no están ahí, sueltos en
    static (así funciona igual si se subieron a una carpeta o a la otra)."""
    if nombre not in _ICONOS:
        abort(404)
    base = current_app.static_folder
    for carpeta in (os.path.join(base, "app"), base):
        if os.path.isfile(os.path.join(carpeta, nombre)):
            r = send_from_directory(carpeta, nombre, mimetype="image/png")
            r.headers["Cache-Control"] = "no-cache"
            return r
    abort(404)


@bp_movil.route("/sw.js")
def service_worker():
    r = Response(_SW % {"v": VERSION_SW}, mimetype="application/javascript")
    r.headers["Cache-Control"] = "no-cache"
    r.headers["Service-Worker-Allowed"] = "/"
    return r


_OFFLINE = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="{{ tema }}">
<title>Sin conexión · La Santaniana</title>
<style>
  *{box-sizing:border-box;margin:0}
  body{min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:18px;
       padding:24px;background:#fff;color:#1D344E;font-family:-apple-system,"Segoe UI",Roboto,sans-serif;text-align:center}
  img{width:96px;height:96px}
  h1{font-size:22px}
  p{font-size:15px;color:#4A5568;max-width:320px;line-height:1.45}
  button{margin-top:6px;padding:12px 26px;border:0;border-radius:10px;background:#1D344E;color:#fff;font-size:15px;
         font-weight:600;cursor:pointer}
</style></head>
<body>
  <img src="/static/app/icon-192.png" alt="La Santaniana">
  <h1>Sin conexión a internet</h1>
  <p>El sistema necesita internet para funcionar. Revisá los datos o el wifi y probá de nuevo.</p>
  <button onclick="location.reload()">Reintentar</button>
  <script>window.addEventListener("online", () => location.reload());</script>
</body></html>"""


@bp_movil.route("/offline")
def offline():
    return render_template_string(_OFFLINE, tema=COLOR_TEMA)


@bp_movil.route("/.well-known/assetlinks.json")
def assetlinks():
    paquete = (os.environ.get("ANDROID_PAQUETE") or "").strip()
    huellas = [h.strip().upper() for h in (os.environ.get("ANDROID_HUELLAS") or "").split(",") if h.strip()]
    datos = []
    if paquete and huellas:
        datos = [{
            "relation": ["delegate_permission/common.handle_all_urls"],
            "target": {"namespace": "android_app", "package_name": paquete,
                       "sha256_cert_fingerprints": huellas},
        }]
    r = Response(json.dumps(datos, indent=2), mimetype="application/json")
    r.headers["Cache-Control"] = "no-cache"
    return r


_PRIVACIDAD = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="{{ tema }}">
<link rel="icon" href="/static/app/favicon-48.png">
<title>Política de privacidad · La Santaniana</title>
<style>
  *{box-sizing:border-box}
  body{margin:0;background:#F7F6F3;color:#1D344E;font-family:-apple-system,"Segoe UI",Roboto,sans-serif;line-height:1.6}
  main{max-width:760px;margin:0 auto;padding:40px 20px 64px}
  header{display:flex;align-items:center;gap:14px;margin-bottom:28px}
  header img{width:56px;height:56px;border-radius:12px;background:#fff}
  h1{font-size:26px;margin:0}
  h2{font-size:18px;margin:28px 0 6px}
  p,li{font-size:15.5px;color:#2D3748}
  ul{padding-left:20px}
  small{color:#718096}
</style></head>
<body><main>
<header><img src="/static/app/icon-192.png" alt=""><div><h1>Política de privacidad</h1>
<small>La Santaniana · Sistema de Gestión de Flota · vigente desde el {{ desde }}</small></div></header>

<p>Esta aplicación es de uso interno de La Santaniana. Solo pueden entrar las personas a las que la
empresa les dio un usuario y una contraseña. No está pensada para el público en general.</p>

<h2>Qué datos se usan</h2>
<ul>
  <li><b>Datos de la cuenta:</b> nombre, usuario y rol de cada persona que usa el sistema.</li>
  <li><b>Datos del trabajo:</b> lo que cada usuario carga en el sistema, por ejemplo órdenes de trabajo,
      horas trabajadas, kilometraje, cargas de combustible, rendiciones, servicios y pasajes vendidos.</li>
  <li><b>Fotos y documentos</b> que el usuario decide subir (comprobantes, facturas, fotos de una falla).
      La cámara solo se abre cuando el usuario toca el botón para sacar una foto.</li>
  <li><b>Datos de pasajeros</b> en la venta de pasajes: nombre y documento, y en los viajes
      internacionales los datos que exige la migración.</li>
</ul>
<p>La aplicación no usa la ubicación del celular, no lee contactos ni otros archivos del teléfono
y no tiene publicidad.</p>

<h2>Para qué se usan</h2>
<p>Solo para la operación de la empresa: mantenimiento de la flota, compras, tráfico, liquidaciones,
venta de pasajes e informes internos. No se venden ni se comparten con terceros para fines comerciales.</p>

<h2>Dónde se guardan</h2>
<p>En servidores de proveedores de infraestructura en la nube contratados por la empresa, con
conexión cifrada (HTTPS).</p>

<h2>Quién puede verlos</h2>
<p>Cada usuario ve solo lo que corresponde a su función. La administración de La Santaniana
define esos permisos.</p>

<h2>Cuánto tiempo se guardan</h2>
<p>Mientras sean necesarios para la operación y para las obligaciones legales y contables de la empresa.</p>

<h2>Tus derechos</h2>
<p>Podés pedir ver, corregir o borrar tus datos personales, o la baja de tu usuario, escribiendo a
{{ contacto }}.</p>

<h2>Cambios</h2>
<p>Si esta política cambia, se publica la nueva versión en esta misma página.</p>
</main></body></html>"""


@bp_movil.route("/privacidad")
def privacidad():
    contacto = (os.environ.get("CONTACTO_PRIVACIDAD") or "").strip()
    contacto_html = (f'<a href="mailto:{contacto}">{contacto}</a>' if "@" in contacto
                     else "la administración de La Santaniana")
    from markupsafe import Markup
    return render_template_string(_PRIVACIDAD, tema=COLOR_TEMA, contacto=Markup(contacto_html),
                                  desde="2 de noviembre de 2026")


# Lo que va en el <head> de cada pantalla (se inserta en las plantillas)
CABECERA = """  <link rel="manifest" href="/manifest.webmanifest">
  <meta name="theme-color" content="#1D344E">
  <link rel="icon" type="image/png" sizes="48x48" href="/static/app/favicon-48.png">
  <link rel="apple-touch-icon" href="/static/app/apple-touch-icon.png">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="mobile-web-app-capable" content="yes">
  <script>if ("serviceWorker" in navigator) addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));</script>
"""
