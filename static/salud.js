// ════════════════════════════════════════════════════════════════════════════
// SALUD DEL SISTEMA (Sistema → Salud del sistema, solo administración)
//
// 1. Los errores de las pantallas se mandan solos al servidor (para que no
//    dependa de que alguien llame y lo cuente).
// 2. La pantalla de salud: si la base responde, a dónde llegan los avisos, el
//    botón de prueba, los pasos para configurar Telegram o ntfy y el vigilante
//    externo, y la lista de errores agrupados.
// ════════════════════════════════════════════════════════════════════════════

(function sdEscucharErrores() {
  let enviados = 0;
  const vistos = new Set();
  function mandar(d) {
    if (enviados >= 20) return;                         // por pestaña, alcanza
    const clave = (d.mensaje || "") + "|" + (d.fuente || "") + "|" + (d.linea || "");
    if (vistos.has(clave)) return;
    vistos.add(clave); enviados++;
    try {
      d.seccion = document.querySelector(".sidebar .nav-item.active[data-sec]")?.dataset.sec || location.pathname;
      fetch("/api/sistema/error_pantalla", { method: "POST", headers: { "Content-Type": "application/json" },
        credentials: "same-origin", body: JSON.stringify(d), keepalive: true }).catch(() => {});
    } catch (e) { }
  }
  window.addEventListener("error", e => {
    if (!e || !e.message) return;                       // errores de carga de imágenes, etc.
    mandar({ mensaje: String(e.message), fuente: e.filename || "", linea: e.lineno, columna: e.colno,
             pila: e.error && e.error.stack ? String(e.error.stack) : "" });
  });
  window.addEventListener("unhandledrejection", e => {
    const r = e && e.reason;
    if (!r) return;
    const msg = r.message || String(r);
    if (/Failed to fetch|NetworkError|Load failed|AbortError/i.test(msg)) return;   // sin internet: no es un error del sistema
    mandar({ mensaje: "Promesa sin atender: " + msg, pila: r.stack ? String(r.stack) : "" });
  });
})();

const sdEsc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const sd = { datos: null, abierto: null };

async function renderSalud() {
  status("Salud del sistema");
  content.innerHTML = `<div class="section"><div class="empty"><i class="ti ti-loader-2"></i>Revisando…</div></div>`;
  const d = await api("/api/sistema/salud");
  if (!d || d.error) { content.innerHTML = `<div class="section"><div class="empty"><i class="ti ti-lock"></i>Solo administración ve la salud del sistema.</div></div>`; return; }
  sd.datos = d;
  sdPintar();
}

function sdPintar() {
  const d = sd.datos;
  const base = d.base.ok
    ? `<span class="sd-estado ok"><i class="ti ti-circle-check"></i> Responde en ${d.base.ms} ms</span>`
    : `<span class="sd-estado mal"><i class="ti ti-alert-octagon"></i> No responde</span>`;
  const can = d.canales.length
    ? `<span class="sd-estado ok"><i class="ti ti-bell-ringing"></i> Llegan por ${d.canales.map(c => c === "telegram" ? "Telegram" : "ntfy").join(" y ")}</span>`
    : `<span class="sd-estado aviso"><i class="ti ti-bell-off"></i> Sin configurar: los errores se guardan, pero no te avisan</span>`;
  content.innerHTML = `
    <div class="page-header">
      <h1><i class="ti ti-heartbeat"></i> Salud del sistema</h1>
      <p>Si algo falla, queda acá y te llega un aviso al celular, antes de que te llamen</p>
    </div>
    <div class="section">
      <div class="sd-resumen">
        <div class="sd-caja"><span class="sd-tit">Base de datos</span>${base}
          <small>Se revisa sola cada 5 minutos${d.vigia.ultimo_chequeo ? ` · última: ${sdEsc(d.vigia.ultimo_chequeo.slice(11, 16))}` : ""}</small></div>
        <div class="sd-caja"><span class="sd-tit">Avisos al celular</span>${can}
          <small>${d.ultimo_aviso ? `Último aviso: ${sdEsc(d.ultimo_aviso)}` : "Todavía no se mandó ninguno"}${d.ultimo_aviso_error ? ` · <b class="sd-rojo">falló: ${sdEsc(d.ultimo_aviso_error)}</b>` : ""}</small>
          <button class="btn btn-ghost btn-sm" onclick="sdProbar(this)"><i class="ti ti-send"></i> Mandar aviso de prueba</button></div>
        <div class="sd-caja"><span class="sd-tit">Errores sin mirar</span>
          <span class="sd-estado ${d.sin_ver ? "mal" : "ok"}"><i class="ti ${d.sin_ver ? "ti-bug" : "ti-mood-smile"}"></i> ${d.sin_ver ? `${d.sin_ver} para revisar` : "Ninguno"}</span>
          <small>El sistema arrancó hace ${sdHace(d.arranque_hace_min)}</small></div>
      </div>

      <div class="card">
        <div class="card-head"><i class="ti ti-bug"></i> Errores
          ${d.sin_ver ? `<button class="btn btn-ghost btn-sm sd-der" onclick="sdTodosVistos()"><i class="ti ti-checks"></i> Marcar todos como vistos</button>` : ""}</div>
        <div class="card-body">${sdLista()}</div>
      </div>

      <div class="card">
        <div class="card-head"><i class="ti ti-school"></i> Configurar los avisos (una sola vez)</div>
        <div class="card-body sd-pasos">${sdPasos(d)}</div>
      </div>
    </div>`;
}

function sdHace(min) {
  if (min < 60) return `${min} min`;
  const h = Math.floor(min / 60);
  return h < 48 ? `${h} h` : `${Math.floor(h / 24)} días`;
}

function sdLista() {
  const es = sd.datos.errores;
  if (!es.length) return `<div class="empty"><i class="ti ti-mood-smile"></i>No se registró ningún error. Cuando algo falle, aparece acá agrupado: el mismo error repetido suma veces en vez de llenar la lista.</div>`;
  return `<div class="sd-lista">${es.map(e => `
    <div class="sd-err ${e.visto ? "visto" : ""}">
      <button type="button" class="sd-err-cab" onclick="sdAbrir(${e.id})" aria-expanded="${sd.abierto === e.id}">
        <span class="sd-err-tipo ${e.tipo}">${e.tipo === "servidor" ? "Servidor" : "Pantalla"}</span>
        <span class="sd-err-txt"><b>${sdEsc((e.mensaje || "").split("\n")[0])}</b>
          <small>${sdEsc(e.ruta || "-")} · ${sdEsc(e.usuario || "-")} · última vez ${sdEsc((e.ultima || "").slice(0, 16))}</small></span>
        <span class="sd-err-veces" title="Veces que pasó">${e.veces}×</span>
      </button>
      ${sd.abierto === e.id ? `<div class="sd-err-det">
        <div class="sd-err-meta">Primera vez: ${sdEsc(e.primera || "-")} · Navegador: ${sdEsc(e.navegador || "-")}</div>
        <pre>${sdEsc(e.detalle || "Sin detalle")}</pre>
        ${e.visto ? "" : `<button class="btn btn-primary btn-sm" onclick="sdVisto(${e.id})"><i class="ti ti-check"></i> Ya lo vi</button>`}
      </div>` : ""}
    </div>`).join("")}</div>`;
}

function sdAbrir(id) { sd.abierto = sd.abierto === id ? null : id; sdPintar(); }

async function sdVisto(id) {
  const r = await api(`/api/sistema/errores/${id}/visto`, { method: "POST" });
  if (r && r.ok) { const e = sd.datos.errores.find(x => x.id === id); if (e) e.visto = 1; sd.datos.sin_ver = sd.datos.errores.filter(x => !x.visto).length; sdPintar(); }
}
async function sdTodosVistos() {
  const r = await api(`/api/sistema/errores/vistos`, { method: "POST" });
  if (r && r.ok) { sd.datos.errores.forEach(e => e.visto = 1); sd.datos.sin_ver = 0; sdPintar(); }
}
async function sdProbar(b) {
  b.disabled = true;
  const r = await api("/api/sistema/probar_aviso", { method: "POST" });
  b.disabled = false;
  toast(r && r.msg ? r.msg : "No se pudo probar", r && r.ok ? "success" : "error");
  const d = await api("/api/sistema/salud");
  if (d && !d.error) { sd.datos = d; sdPintar(); }
}

function sdPasos(d) {
  return `
    <div class="sd-paso">
      <span class="sd-num">1</span>
      <div><b>Avisos por Telegram</b> (recomendado: llegan como un mensaje más)
        <ol>
          <li>En Telegram, buscá <b>@BotFather</b>, mandale <code>/newbot</code> y seguí los pasos. Al final te da un <b>token</b> (algo como <code>123456:ABC…</code>).</li>
          <li>Abrí el bot que creaste y mandale cualquier mensaje (un «hola»).</li>
          <li>Buscá <b>@userinfobot</b>, escribile y te responde tu <b>Id</b> (un número).</li>
          <li>En Render, en el servicio del sistema → <b>Environment</b>, agregá <code>AVISOS_TELEGRAM_TOKEN</code> con el token y <code>AVISOS_TELEGRAM_CHAT</code> con tu Id. Guardá (Render reinicia solo).</li>
          <li>Volvé acá y tocá <b>Mandar aviso de prueba</b>.</li>
        </ol>
      </div>
    </div>
    <div class="sd-paso">
      <span class="sd-num">2</span>
      <div><b>O por ntfy</b> (sin cuenta, una app de notificaciones)
        <ol>
          <li>Instalá la app <b>ntfy</b> en el celular y suscribite a un tema con un nombre difícil de adivinar, por ejemplo <code>santaniana-${sdEsc(sdTemaSugerido())}</code>.</li>
          <li>En Render → Environment agregá <code>AVISOS_NTFY_TEMA</code> con ese mismo nombre.</li>
        </ol>
      </div>
    </div>
    <div class="sd-paso">
      <span class="sd-num">3</span>
      <div><b>Vigilante externo</b> (para cuando el sistema entero se cae y no puede avisar solo)
        <ol>
          <li>Creá una cuenta gratis en <b>UptimeRobot</b> (o Better Stack).</li>
          <li>Agregá un monitor de tipo HTTP con esta dirección, cada 5 minutos:</li>
        </ol>
        <div class="sd-url"><code>${sdEsc(d.url_salud)}</code>
          <button class="btn btn-ghost btn-sm" onclick="navigator.clipboard.writeText('${sdEsc(d.url_salud)}').then(() => toast('Dirección copiada', 'success'))"><i class="ti ti-copy"></i> Copiar</button></div>
        <p class="sd-nota">Esa dirección solo dice si el sistema y la base responden; no muestra ningún dato.</p>
      </div>
    </div>`;
}

let _sdTema = null;
function sdTemaSugerido() {
  if (!_sdTema) { const a = new Uint8Array(5); (crypto || window.msCrypto).getRandomValues(a); _sdTema = [...a].map(x => x.toString(36).padStart(2, "0")).join("").slice(0, 8); }
  return _sdTema;
}
