/* acuse_asig.js — La Santaniana
 * Cuando la oficina publica la asignación corporativa, el chofer TIENE que
 * confirmar que la recibió: se le muestra lo que le toca y no se cierra hasta
 * que toca «Recibí mi asignación». Si después la asignación le cambia, se le
 * vuelve a pedir. Se usa en la app del chofer (/mi) y en rendiciones (/corp).
 * Si antes tiene que confirmar que tiene la app (confirmar_app.js), espera a eso.
 * Al confirmar avisa con el evento «asignacion-recibida».
 */
(function () {
  const css = `
  .acu-velo{position:fixed;inset:0;z-index:8990;background:rgba(10,20,34,.72);backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px);
    display:flex;align-items:flex-end;justify-content:center;animation:acu-in .25s ease-out}
  .acu{width:100%;max-width:480px;max-height:92vh;overflow:auto;background:#fff;color:#14263D;border-radius:26px 26px 0 0;
    padding:24px 20px calc(20px + env(safe-area-inset-bottom));font-family:Inter,system-ui,sans-serif;box-shadow:0 -10px 40px rgba(0,0,0,.25);
    animation:acu-sube .35s cubic-bezier(.2,.8,.2,1)}
  @media (min-width:560px){.acu-velo{align-items:center}.acu{border-radius:26px}}
  .acu-et{font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#DC2641;margin:0 0 6px}
  .acu h2{font-size:23px;line-height:1.2;margin:0 0 6px;font-weight:800}
  .acu > p{font-size:14.5px;line-height:1.45;color:#4B5B70;margin:0 0 16px}
  .acu-dia{border:1px solid #E7E4DD;border-radius:16px;padding:12px 14px;margin-bottom:10px}
  .acu-dia-t{display:flex;align-items:center;gap:8px;font-size:13px;font-weight:700;margin-bottom:6px}
  .acu-dia-t em{font-style:normal;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;padding:2px 7px;border-radius:6px;background:#FAF1DE;color:#8A5A00}
  .acu-it{display:grid;grid-template-columns:58px 1fr;gap:10px;align-items:baseline;padding:6px 0;border-top:1px dashed #ECEAE5}
  .acu-it:first-of-type{border-top:0}
  .acu-it b{font-size:20px;font-weight:800;font-variant-numeric:tabular-nums}
  .acu-it span{font-size:14.5px;line-height:1.35}
  .acu-it small{display:block;font-size:12.5px;color:#6B7685}
  .acu-b{width:100%;border:0;border-radius:15px;padding:16px;font:700 16px Inter,system-ui,sans-serif;display:flex;align-items:center;justify-content:center;gap:8px;
    cursor:pointer;background:#DC2641;color:#fff;box-shadow:0 8px 20px -8px rgba(220,38,65,.7);margin-top:8px}
  .acu-b:active{transform:scale(.98)} .acu-b:disabled{opacity:.6}
  .acu.listo{text-align:center}
  .acu-tilde{width:76px;height:76px;margin:6px auto 14px;display:block}
  .acu-tilde circle{fill:#2F7C46;transform-origin:center;animation:acu-pop .4s cubic-bezier(.2,1.4,.4,1)}
  .acu-tilde path{fill:none;stroke:#fff;stroke-width:6;stroke-linecap:round;stroke-linejoin:round;stroke-dasharray:50;stroke-dashoffset:50;animation:acu-traza .4s .25s forwards}
  .acu-velo.chau{animation:acu-out .35s forwards}
  @keyframes acu-in{from{opacity:0}} @keyframes acu-out{to{opacity:0}}
  @keyframes acu-sube{from{transform:translateY(40px);opacity:.4}}
  @keyframes acu-pop{from{transform:scale(.3)}} @keyframes acu-traza{to{stroke-dashoffset:0}}
  @media (prefers-reduced-motion:reduce){.acu-velo,.acu,.acu-tilde circle,.acu-tilde path{animation:none!important}.acu-tilde path{stroke-dashoffset:0}}
  @media (prefers-color-scheme:dark){.acu{background:#16202D;color:#EEF2F7}.acu > p,.acu-it small{color:#A9B6C6}.acu-dia{border-color:#2A3A50}.acu-it{border-color:#2A3A50}}`;

  const esc = t => String(t ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const may = t => String(t || "").charAt(0).toUpperCase() + String(t || "").slice(1);
  let velo, caja, abierto = false;

  function abrir(pend) {
    if (abierto) return;
    abierto = true;
    if (!document.getElementById("acu-css")) {
      const s = document.createElement("style"); s.id = "acu-css"; s.textContent = css; document.head.appendChild(s);
    }
    velo = document.createElement("div");
    velo.className = "acu-velo";
    velo.setAttribute("role", "dialog"); velo.setAttribute("aria-modal", "true"); velo.setAttribute("aria-labelledby", "acu-t");
    caja = document.createElement("div"); caja.className = "acu";
    velo.appendChild(caja); document.body.appendChild(velo);
    document.documentElement.style.overflow = "hidden";
    const cambio = pend.some(p => p.cambio);
    caja.innerHTML = `
      <p class="acu-et">${cambio ? "Cambió tu asignación" : "Tenés asignación"}</p>
      <h2 id="acu-t">Confirmá que la recibiste</h2>
      <p>Mirá lo que te toca y tocá el botón, así la oficina sabe que ya lo viste.</p>
      ${pend.map(p => `<div class="acu-dia">
        <div class="acu-dia-t">${esc(p.dia_txt === "hoy" || p.dia_txt === "mañana" ? `${may(p.dia_txt)} · ${p.dia_largo}` : may(p.dia_largo))}${p.cambio ? "<em>Cambió</em>" : ""}</div>
        ${p.items.map(i => `<div class="acu-it"><b>${esc(i.hora || "--:--")}</b><span>${esc(i.cliente)} · ${esc(i.tramo)}${i.lado ? " (" + esc(i.lado) + ")" : ""}
          <small>${i.coche ? "Coche " + esc(i.coche) : "Coche a confirmar"}${i.hora_fin ? " · hasta las " + esc(i.hora_fin) : ""}</small></span></div>`).join("")}
      </div>`).join("")}
      <button class="acu-b" id="acu-si"><i class="ti ti-check"></i> Recibí mi asignación</button>`;
    const b = caja.querySelector("#acu-si");
    b.onclick = confirmar;
    b.focus();
  }

  async function confirmar() {
    const b = caja.querySelector("#acu-si");
    b.disabled = true; b.textContent = "Confirmando…";
    try {
      const r = await fetch("/api/mi/asignacion/recibido", { method: "POST", credentials: "same-origin" });
      if (!r.ok) throw new Error();
    } catch (e) {
      b.disabled = false; b.innerHTML = `<i class="ti ti-check"></i> Probá de nuevo`;
      return;
    }
    if (navigator.vibrate) navigator.vibrate(30);
    caja.className = "acu listo";
    caja.innerHTML = `<svg class="acu-tilde" viewBox="0 0 64 64" aria-hidden="true"><circle cx="32" cy="32" r="32"/><path d="M19 33l9 9 17-19"/></svg>
      <h2 id="acu-t">¡Listo!</h2><p style="margin:0">La oficina ya sabe que recibiste tu asignación.</p>`;
    setTimeout(() => velo.classList.add("chau"), 1400);
    setTimeout(() => {
      velo.remove(); document.documentElement.style.overflow = ""; abierto = false;
      dispatchEvent(new CustomEvent("asignacion-recibida"));
    }, 1750);
  }

  async function revisar() {
    if (abierto) return;
    // Primero, si falta, que confirme que tiene la app
    if (document.querySelector(".cfa-velo")) { addEventListener("app-confirmada", revisar, { once: true }); return; }
    try {
      const r = await fetch("/api/mi/asignacion", { credentials: "same-origin" }).then(x => x.json());
      if (r && r.pendientes && r.pendientes.length) abrir(r.pendientes);
    } catch (e) { /* sin conexión: se vuelve a preguntar la próxima vez */ }
  }
  window.acuseRevisar = revisar;
  // Un poco después de cargar (para que primero aparezca, si hace falta, lo de la app)
  const arrancar = () => setTimeout(revisar, 900);
  if (document.readyState === "loading") addEventListener("DOMContentLoaded", arrancar); else arrancar();
  // Al volver a la app (por ejemplo, desde el aviso), revisar de nuevo
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") setTimeout(revisar, 400); });
})();
