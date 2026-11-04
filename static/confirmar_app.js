/* confirmar_app.js — La Santaniana
 * El chofer TIENE que confirmar que ya tiene la app en el celular. Hasta que
 * toca «Sí, ya la tengo», la pantalla queda tapada con esta pregunta (no se
 * puede cerrar). Si todavía no la tiene, le muestra cómo instalarla.
 * Se usa en la app del chofer (/mi) y en la de rendiciones (/corp).
 * Al confirmar avisa con el evento «app-confirmada».
 */
(function () {
  let promptInstalar = null;
  addEventListener("beforeinstallprompt", e => { e.preventDefault(); promptInstalar = e; });

  const enLaApp = () => matchMedia("(display-mode: standalone)").matches || navigator.standalone === true ||
    document.referrer.startsWith("android-app://");
  const ios = /iphone|ipad|ipod/i.test(navigator.userAgent);

  const css = `
  .cfa-velo{position:fixed;inset:0;z-index:9000;background:rgba(10,20,34,.72);backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px);
    display:flex;align-items:flex-end;justify-content:center;padding:0;animation:cfa-in .25s ease-out}
  .cfa{width:100%;max-width:480px;background:#fff;color:#14263D;border-radius:26px 26px 0 0;padding:26px 22px calc(22px + env(safe-area-inset-bottom));
    font-family:Inter,system-ui,sans-serif;box-shadow:0 -10px 40px rgba(0,0,0,.25);animation:cfa-sube .35s cubic-bezier(.2,.8,.2,1)}
  @media (min-width:560px){.cfa-velo{align-items:center}.cfa{border-radius:26px}}
  .cfa-ic{width:58px;height:58px;border-radius:18px;background:#14263D;color:#fff;display:grid;place-items:center;font-size:30px;margin-bottom:16px}
  .cfa-et{font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#DC2641;margin:0 0 6px}
  .cfa h2{font-size:23px;line-height:1.2;margin:0 0 8px;font-weight:800;letter-spacing:-.01em}
  .cfa p{font-size:15px;line-height:1.45;color:#4B5B70;margin:0 0 18px}
  .cfa-b{width:100%;border:0;border-radius:15px;padding:16px;font:700 16px Inter,system-ui,sans-serif;display:flex;align-items:center;justify-content:center;gap:8px;cursor:pointer}
  .cfa-b.si{background:#DC2641;color:#fff;box-shadow:0 8px 20px -8px rgba(220,38,65,.7)}
  .cfa-b.si:active{transform:scale(.98)}
  .cfa-b.no{background:#F1F3F6;color:#14263D;margin-top:10px}
  .cfa-b:disabled{opacity:.6}
  .cfa ol{margin:0 0 18px;padding:0;list-style:none;counter-reset:p;display:flex;flex-direction:column;gap:10px}
  .cfa li{counter-increment:p;display:grid;grid-template-columns:30px 1fr;gap:10px;align-items:start;font-size:15px;line-height:1.4}
  .cfa li::before{content:counter(p);width:30px;height:30px;border-radius:50%;background:#EAF1F8;color:#1E5A96;font-weight:800;display:grid;place-items:center;font-size:14px}
  .cfa-tilde{width:76px;height:76px;margin:6px auto 14px;display:block}
  .cfa-tilde circle{fill:#2F7C46;transform-origin:center;animation:cfa-pop .4s cubic-bezier(.2,1.4,.4,1)}
  .cfa-tilde path{fill:none;stroke:#fff;stroke-width:6;stroke-linecap:round;stroke-linejoin:round;stroke-dasharray:50;stroke-dashoffset:50;animation:cfa-traza .4s .25s forwards}
  .cfa.listo{text-align:center}
  .cfa-velo.chau{animation:cfa-out .35s forwards}
  @keyframes cfa-in{from{opacity:0}} @keyframes cfa-out{to{opacity:0}}
  @keyframes cfa-sube{from{transform:translateY(40px);opacity:.4}}
  @keyframes cfa-pop{from{transform:scale(.3)}} @keyframes cfa-traza{to{stroke-dashoffset:0}}
  @media (prefers-reduced-motion:reduce){.cfa-velo,.cfa,.cfa-tilde circle,.cfa-tilde path{animation:none!important}.cfa-tilde path{stroke-dashoffset:0}}
  @media (prefers-color-scheme:dark){.cfa{background:#16202D;color:#EEF2F7}.cfa p{color:#A9B6C6}.cfa-b.no{background:#223042;color:#EEF2F7}
    .cfa li::before{background:#223042;color:#8CBDEB}.cfa-ic{background:#DC2641}}`;

  let velo, caja;

  function abrir() {
    if (!document.getElementById("cfa-css")) {
      const s = document.createElement("style"); s.id = "cfa-css"; s.textContent = css; document.head.appendChild(s);
    }
    velo = document.createElement("div");
    velo.className = "cfa-velo";
    velo.setAttribute("role", "dialog"); velo.setAttribute("aria-modal", "true"); velo.setAttribute("aria-labelledby", "cfa-t");
    caja = document.createElement("div"); caja.className = "cfa";
    velo.appendChild(caja);
    document.body.appendChild(velo);
    document.documentElement.style.overflow = "hidden";
    pregunta();
  }

  function pregunta() {
    const app = enLaApp();
    caja.className = "cfa";
    caja.innerHTML = `
      <div class="cfa-ic"><i class="ti ti-device-mobile-check"></i></div>
      <p class="cfa-et">Un paso antes de empezar</p>
      <h2 id="cfa-t">${app ? "Confirmá que ya tenés la app" : "¿Ya tenés la app de La Santaniana en tu celular?"}</h2>
      <p>${app ? "Estás adentro de la app. Tocá el botón así la oficina sabe que ya te llegan tus servicios."
               : "La oficina necesita saber quién ya la tiene, para mandarte tu servicio al celular."}</p>
      <button class="cfa-b si" id="cfa-si"><i class="ti ti-check"></i> Sí, ya la tengo</button>
      ${app ? "" : `<button class="cfa-b no" id="cfa-no">Todavía no la tengo</button>`}`;
    caja.querySelector("#cfa-si").onclick = confirmar;
    const no = caja.querySelector("#cfa-no");
    if (no) no.onclick = instalar;
    caja.querySelector("#cfa-si").focus();
  }

  function instalar() {
    const pasos = ios
      ? ["Abrí esta página en <b>Safari</b>", "Tocá <b>Compartir</b> (el cuadrado con la flecha para arriba)", "Elegí <b>Agregar a inicio</b> y después <b>Agregar</b>", "Abrí <b>La Santaniana</b> desde el ícono y entrá con tu usuario"]
      : ["Abrí el archivo <b>La Santaniana</b> que te pasó la oficina por WhatsApp y tocá <b>Instalar</b>",
         "Si no lo tenés: en Chrome tocá <b>⋮</b> (arriba a la derecha) → <b>Instalar app</b> o <b>Agregar a la pantalla principal</b>",
         "Abrí <b>La Santaniana</b> desde el ícono y entrá con tu usuario"];
    caja.innerHTML = `
      <div class="cfa-ic"><i class="ti ti-download"></i></div>
      <p class="cfa-et">Instalala en un minuto</p>
      <h2 id="cfa-t">Cómo tener la app</h2>
      <ol>${pasos.map(p => `<li><span>${p}</span></li>`).join("")}</ol>
      ${promptInstalar ? `<button class="cfa-b si" id="cfa-inst"><i class="ti ti-download"></i> Instalar ahora</button>` : ""}
      <button class="cfa-b ${promptInstalar ? "no" : "si"}" id="cfa-ya"><i class="ti ti-check"></i> Ya la instalé</button>
      <button class="cfa-b no" id="cfa-volver">Volver</button>`;
    const inst = caja.querySelector("#cfa-inst");
    if (inst) inst.onclick = async () => {
      try { promptInstalar.prompt(); const r = await promptInstalar.userChoice; promptInstalar = null; if (r && r.outcome === "accepted") confirmar(); else instalar(); }
      catch (e) { instalar(); }
    };
    caja.querySelector("#cfa-ya").onclick = confirmar;
    caja.querySelector("#cfa-volver").onclick = pregunta;
  }

  async function confirmar() {
    const b = caja.querySelector("#cfa-si, #cfa-ya");
    caja.querySelectorAll("button").forEach(x => x.disabled = true);
    if (b) b.innerHTML = "Confirmando…";
    try {
      const r = await fetch("/api/push/confirmar", { method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify({ modo: enLaApp() ? "app" : "navegador" }) });
      if (!r.ok) throw new Error();
    } catch (e) {
      caja.querySelectorAll("button").forEach(x => x.disabled = false);
      if (b) b.innerHTML = `<i class="ti ti-check"></i> Probá de nuevo`;
      return;
    }
    if (navigator.vibrate) navigator.vibrate(30);
    caja.className = "cfa listo";
    caja.innerHTML = `<svg class="cfa-tilde" viewBox="0 0 64 64" aria-hidden="true"><circle cx="32" cy="32" r="32"/><path d="M19 33l9 9 17-19"/></svg>
      <h2 id="cfa-t">¡Listo, gracias!</h2><p style="margin:0">La oficina ya sabe que tenés la app.</p>`;
    setTimeout(() => velo.classList.add("chau"), 1500);
    setTimeout(() => {
      velo.remove(); document.documentElement.style.overflow = "";
      dispatchEvent(new CustomEvent("app-confirmada"));
    }, 1850);
  }

  async function revisar() {
    try {
      const r = await fetch("/api/push/confirmacion", { credentials: "same-origin" }).then(x => x.json());
      if (r && r.pide && !r.confirmado_el) abrir();
    } catch (e) { /* sin conexión: se vuelve a preguntar la próxima vez */ }
  }
  if (document.readyState === "loading") addEventListener("DOMContentLoaded", revisar); else revisar();
})();
