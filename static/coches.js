// ════════════════════════════════════════════════════════════════════════════
// COCHES — la ficha única de cada coche (Taller → Coches)
//
// Taller quedó en tres secciones: Órdenes de trabajo, Pedidos de choferes y
// Coches. Esta sección junta lo que antes estaba repartido en Plan preventivo,
// Preventivo, Correctivos, Mantenimientos, Neumáticos, Historial por coche,
// Costos y KPIs:
//
//   · La lista de la flota (con la agenda del taller, el cumplimiento y los
//     planes en sus pestañas).
//   · La ficha de un coche, con pestañas: Resumen, Historial, Preventivo,
//     Neumáticos, Costos y KPIs.
//
// El trabajo del taller se carga por orden de trabajo: la ficha es para mirar,
// y desde ahí se abre la OT del coche.
//
// Este archivo se carga ANTES que app.js (solo define funciones; las usa
// app.js cuando navega). Las pestañas reutilizan las pantallas de cada módulo,
// que dibujan adentro de la ficha (ver lienzo()).
// ════════════════════════════════════════════════════════════════════════════

const FC_TABS = [
  ["resumen", "layout-dashboard", "Resumen"],
  ["historial", "timeline-event", "Historial"],
  ["preventivo", "calendar-check", "Preventivo"],
  ["neumaticos", "disc", "Neumáticos"],
  ["costos", "coin", "Costos"],
  ["kpis", "chart-bar", "KPIs"],
];
// Las secciones que ya no están en el menú y a dónde llevan ahora
const FC_MENU_DE = { planes: "coches", mantenimientos: "coches", mantenimiento: "coches", neumaticos: "coches",
                     correctivos: "coches", historial_carga: "coches", costos: "coches", kpis: "coches",
                     personal: "ots", tablero_taller: "ots" };
const FC_SUBNAV_OT = [
  ["ots", "clipboard-check", "Órdenes"],
  ["tablero_taller", "layout-grid", "Tablero de control"],
  ["personal", "users", "Personal"],
];

const fc = { vid: null, v: null, tab: "resumen", res: null, seq: 0, scroll: 0, sec: "" };

const fcE = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const FC_MES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
function fcFecha(f) {
  const s = String(f || "").slice(0, 10);
  if (s.length < 10) return "—";
  const anio = +s.slice(0, 4), mismo = anio === new Date().getFullYear();
  return `${+s.slice(8)} ${FC_MES[+s.slice(5, 7) - 1]}${mismo ? "" : " " + anio}`;
}
function fcHaceDias(n) {
  if (n == null) return "";
  if (n <= 0) return "hoy";
  if (n === 1) return "ayer";
  if (n < 31) return `hace ${n} días`;
  const m = Math.round(n / 30.4);
  return m < 12 ? `hace ${m} ${m === 1 ? "mes" : "meses"}` : `hace ${Math.floor(n / 365)} ${Math.floor(n / 365) === 1 ? "año" : "años"}`;
}

// ─── Quién ve qué ───────────────────────────────────────────────────────────
// Administración y taller ven todo. Compras ve el resumen y el historial (lo
// que ya veía). Un usuario de taller con secciones limitadas ve la ficha si
// tiene "Coches", y las pestañas Costos y KPIs solo si las tiene tildadas.
function fcTabs() {
  const rol = window.USUARIO_ROL, todas = FC_TABS.map(t => t[0]);
  if (rol === "admin") return todas;
  if (rol === "compras") return ["resumen", "historial"];
  if (rol !== "taller") return [];
  const secs = window.USUARIO_SECCIONES || [];
  if (!secs.length) return todas;
  const t = [];
  if (secs.includes("coches")) t.push("resumen", "historial", "preventivo", "neumaticos");
  if (secs.includes("costos")) t.push("costos");
  if (secs.includes("kpis")) t.push("kpis");
  return t;
}
function fcPuedeOT() {
  return window.USUARIO_ROL === "compras" || (["admin", "taller"].includes(window.USUARIO_ROL) && puedeVerSeccion("ots"));
}

function fcMarcarMenu(sec = "coches") {
  document.querySelectorAll(".nav-item").forEach(b => b.classList.toggle("active", b.dataset.sec === sec));
}

// ─── A dónde lleva cada sección (la usa irA de app.js) ──────────────────────
// Devuelve la función que abre la pantalla, o null si la sección es de las de
// siempre. Las secciones viejas siguen andando como atajos: llevan a la ficha.
function fcRuta(sec) {
  fc.sec = sec;
  switch (sec) {
    case "coches": case "planes":
      return () => fcEntrar();
    case "correctivos":
      return () => fcEntrar({ filtro: "correctivos" });
    case "historial_carga": case "mantenimientos": {
      const vid = window._hiAbrirCoche || window._mtAbrirCoche;
      window._hiAbrirCoche = window._mtAbrirCoche = null;
      return () => vid ? fcAbrir(vid, "historial") : fcEntrar();
    }
    case "mantenimiento": case "neumaticos": case "costos": case "kpis": {
      const tab = sec === "mantenimiento" ? "preventivo" : sec;
      return () => cocheActual ? fcAbrir(cocheActual.id, tab) : fcEntrar();
    }
    case "ots": case "personal": case "tablero_taller":
      fcMarcarMenu("ots");
      return null;
  }
  return null;
}

// La caja "Coche seleccionado" del menú: abre la ficha de ese coche
function fcDesdeCaja() {
  if (typeof cerrarSidebar === "function") cerrarSidebar();
  if (cocheActual && fcTabs().length) fcAbrir(cocheActual.id);
  else if (typeof abrirDestino === "function") abrirDestino();
}

// ─── La flota ───────────────────────────────────────────────────────────────
async function fcEntrar(o = {}) {
  const tabs = fcTabs();
  if (!tabs.length) { toast("No tenés acceso a esa sección", "error"); return; }
  fcMarcarMenu();
  fc.vid = null;
  content.scrollTop = 0;
  if (tabs.includes("preventivo")) {
    if (o.tab) pv.tab = o.tab;
    if (o.filtro) { pv.tab = "flota"; pv.filtro = o.filtro; }
    return renderPlanes();
  }
  if (o.filtro === "correctivos") hi.filtro = "correctivos";
  return renderHistorialCarga();
}
function fcAgenda() { return fcEntrar({ tab: "agenda" }); }

// Cuántos correctivos tuvo cada coche en 90 días, para la lista de la flota.
// Se trae después de dibujar: la lista no espera por esto.
async function fcTraerCorrectivos() {
  const h = await api("/api/historia/flota");
  if (!h || !h.coches) return;
  pv.corr = Object.fromEntries(h.coches.filter(c => c.correctivos_90 > 0).map(c => [c.id, c.correctivos_90]));
  if ($("#pv-lista") && pv.tab === "flota") pvFlotaPintar();
}

async function fcVolver() {
  const y = fc.scroll;
  await fcEntrar();
  if (!y) return;
  // La lista llega un instante después: se vuelve a donde estaba
  let n = 0;
  const t = setInterval(() => {
    if (document.querySelector("#pv-lista .pv-fila, #hi-grilla .hi-coche")) { content.scrollTop = y; clearInterval(t); }
    else if (++n > 40) clearInterval(t);
  }, 80);
}

// ─── La ficha ───────────────────────────────────────────────────────────────
async function fcAbrir(vid, tab) {
  const tabs = fcTabs();
  if (!tabs.length) { toast("No tenés acceso a esa sección", "error"); return; }
  vid = Number(vid);
  if (!tab || !tabs.includes(tab)) tab = tabs[0];
  fcMarcarMenu();
  const v = ((await pvVehiculos()) || []).find(x => x.id === vid);
  if (!v) { toast("No se encontró ese coche", "error"); return; }
  if (!$("#fc-raiz")) fc.scroll = content.scrollTop;
  setCoche(v);
  fc.vid = vid; fc.v = v; fc.res = null;
  status(`Ficha del coche ${v.n_interno || v.patente}`);
  const modelo = `${v.marca || ""} ${v.modelo || ""}`.trim();
  content.innerHTML = `
    <div class="section fc-raiz" id="fc-raiz" data-vid="${vid}">
      <div class="fc-top">
        <button class="hi-volver" onclick="fcVolver()"><i class="ti ti-arrow-left"></i> Toda la flota</button>
        <span class="fc-acc">
          <button class="btn btn-ghost" onclick="informeCoche(${vid})" title="Todo el coche en un PDF"><i class="ti ti-file-type-pdf"></i> <span>Informe completo</span></button>
          ${fcPuedeOT() ? `<button class="btn btn-primary" onclick="fcNuevaOT()"><i class="ti ti-clipboard-plus"></i> <span>Abrir OT</span></button>` : ""}
        </span>
      </div>
      <header class="hi-hero-cartel fc-cartel">
        <span class="hi-hero-num">${fcE(v.n_interno || "—")}</span>
        <span class="hi-hero-id"><b>${fcE(v.patente || "")}</b>${modelo ? `<span>${fcE(modelo)}</span>` : ""}</span>
        <span class="fc-cartel-der" id="fc-cartel-der"></span>
      </header>
      <nav class="pv-tabs fc-tabs" role="tablist" aria-label="Partes de la ficha">
        ${FC_TABS.filter(t => tabs.includes(t[0])).map(([k, i, n]) =>
          `<button role="tab" class="pv-tab" data-t="${k}" aria-selected="false" onclick="fcIr('${k}')"><i class="ti ti-${i}"></i><span>${n}</span></button>`).join("")}
      </nav>
      <div class="fc-cuerpo" id="fc-cuerpo"></div>
    </div>`;
  content.scrollTop = 0;
  fcIr(tab);
  if (tab !== "resumen") fcTraerResumen();
}

const fcCargando = () => `<div class="dossier-loading"><div class="dossier-spinner"></div></div>`;
const fcError = msg => `<div class="rv-vacio"><i class="ti ti-plug-connected-x"></i><b>${msg}</b><span>Volvé a intentarlo en unos minutos.</span></div>`;

async function fcIr(tab) {
  const c = $("#fc-cuerpo");
  if (!c) return;
  fc.tab = tab;
  const seq = ++fc.seq;
  document.querySelectorAll(".fc-tabs .pv-tab").forEach(b => {
    const on = b.dataset.t === tab;
    b.classList.toggle("on", on);
    b.setAttribute("aria-selected", on);
    if (on) b.scrollIntoView({ block: "nearest", inline: "nearest" });
  });
  c.className = `fc-cuerpo fc-t-${tab}`;
  c.innerHTML = fcCargando();
  if (tab === "resumen") {
    await fcTraerResumen();
    if (seq === fc.seq) fcPintarResumen();
  } else if (tab === "historial") {
    c.innerHTML = `<div class="hi-raiz" id="hi-raiz">${fcCargando()}</div>`;
    hi.coche = fc.vid; hi.tipo = ""; hi.anio = ""; hi.pagina = 1; hi.sesion = 0;
    const d = await hiTraer(1);
    if (seq !== fc.seq || !$("#hi-raiz")) return;
    if (!d || d.error) { c.innerHTML = fcError("No se pudo traer el historial"); return; }
    hiPintarFicha(d);
  } else if (tab === "preventivo") {
    c.innerHTML = `<div class="pv-raiz pv-ficha" id="pv-ficha" data-vid="${fc.vid}">${fcCargando()}</div>`;
    await pvAbrirCoche(fc.vid);
  } else if (tab === "neumaticos") await renderNeumaticos();
  else if (tab === "costos") await renderCostos();
  else if (tab === "kpis") await renderKpis();
}

// Dónde dibujan Neumáticos, Costos y KPIs: adentro de la ficha, si la ficha
// está mostrando esa pestaña. Si no (se cambió de pestaña o de sección
// mientras cargaba), no dibujan nada.
function lienzo(tab) {
  const c = document.getElementById("fc-cuerpo");
  return c && fc.tab === tab ? c : null;
}

function fcNuevaOT() { abrirNuevaOT(fc.vid); }

// Después de crear, cerrar o borrar una OT desde la ficha: se queda en la ficha
// y se actualiza (devuelve true si la pantalla de atrás es de Coches).
function fcDetrasDeOT() {
  if ($("#fc-raiz")) { fcRefrescar(); return true; }
  if (fc.sec && FC_MENU_DE[fc.sec] === "coches" || fc.sec === "coches") {
    if ($("#pv-raiz") && typeof pvRefrescarDespuesDeTurno === "function") pvRefrescarDespuesDeTurno();
    return true;
  }
  return false;
}
async function fcRefrescar() {
  if (!$("#fc-raiz")) return;
  if (fc.tab === "resumen") { await fcTraerResumen(); fcPintarResumen(); }
  else if (fc.tab === "historial" && typeof hiRefrescar === "function") { fcTraerResumen(); hiRefrescar(); }
  else if (fc.tab === "preventivo") { fcTraerResumen(); pvAbrirCoche(fc.vid); }
  else fcTraerResumen();
}

// ─── Resumen ────────────────────────────────────────────────────────────────
async function fcTraerResumen() {
  const vid = fc.vid;
  const d = await api(`/api/coche/${vid}/resumen`);
  if (vid !== fc.vid) return;
  fc.res = d && !d.error ? d : null;
  fcPintarCartel();
}

// Lo que dice el cartel a la derecha: cómo está el coche ahora
function fcPintarCartel() {
  const el = $("#fc-cartel-der"), d = fc.res;
  if (!el) return;
  if (!d) { el.innerHTML = ""; return; }
  const p = d.preventivo, ots = d.ots || [];
  let estado;
  if (d.fuera_servicio) estado = `<span class="fc-chip mal"><i class="ti ti-ban"></i>Fuera de servicio</span>`;
  else if (ots.length) estado = `<span class="fc-chip taller"><i class="ti ti-tool"></i>En el taller</span>`;
  else if (p && p.estado === "vencido") estado = `<span class="fc-chip mal"><i class="ti ti-alert-octagon"></i>Preventivo vencido</span>`;
  else if (p && p.estado === "pronto") estado = `<span class="fc-chip aviso"><i class="ti ti-clock-hour-4"></i>Preventivo por vencer</span>`;
  else if (p && p.estado === "ok") estado = `<span class="fc-chip bien"><i class="ti ti-circle-check"></i>Al día</span>`;
  else estado = "";
  el.innerHTML = `${estado}${p && p.km_actual ? `<span class="fc-km"><b>${fmtNum(p.km_actual)}</b> km</span>` : ""}`;
}

function fcPintarResumen() {
  const c = $("#fc-cuerpo"), d = fc.res;
  if (!c || fc.tab !== "resumen") return;
  if (!d) { c.innerHTML = fcError("No se pudo traer el resumen del coche"); return; }
  const tabs = fcTabs();
  c.innerHTML = `
    <div class="fc-res">
      ${fcAlertas(d)}
      <div class="fc-cifras">${fcCifras(d)}</div>
      <div class="fc-grid">
        <div class="fc-col">
          ${fcCajaToca(d, tabs)}
          ${fcCajaUltimo(d, tabs)}
          ${fcCajaPapeles(d)}
        </div>
        <div class="fc-col">
          ${fcCajaTaller(d)}
          ${fcCajaCubiertas(d, tabs)}
          ${fcCajaDatos(d)}
        </div>
      </div>
    </div>`;
}

function fcAlertas(d) {
  const a = [];
  if (d.fuera_servicio) a.push(["mal", "ban", `Fuera de servicio ${fcHaceDias(d.fuera_servicio.dias)}${d.fuera_servicio.motivo ? `: ${fcE(d.fuera_servicio.motivo)}` : ""}`]);
  const venc = (d.documentos || []).filter(x => x.dias != null && x.dias < 0).length;
  const porVencer = (d.documentos || []).filter(x => x.dias != null && x.dias >= 0 && x.dias <= 30).length;
  if (venc) a.push(["mal", "file-alert", `${venc} ${venc === 1 ? "documento vencido" : "documentos vencidos"}`]);
  if (porVencer) a.push(["aviso", "file-time", `${porVencer} ${porVencer === 1 ? "documento vence" : "documentos vencen"} en los próximos 30 días`]);
  const n = d.neumaticos;
  if (n && n.para_cambiar) a.push(["aviso", "disc", `${n.para_cambiar} ${n.para_cambiar === 1 ? "neumático para cambiar" : "neumáticos para cambiar"}`]);
  return a.length ? `<div class="fc-alertas">${a.map(([t, i, x]) => `<span class="fc-alerta ${t}"><i class="ti ti-${i}"></i>${x}</span>`).join("")}</div>` : "";
}

function fcCifras(d) {
  const p = d.preventivo, ots = d.ots || [], ped = d.pedidos || [], h = d.historia;
  const out = [];
  if (p) {
    out.push(`<div class="fc-cifra"><span class="fc-et">Odómetro</span>
      <b>${p.km_actual ? fmtNum(p.km_actual) : "—"}<small> km</small></b>
      <span>${p.km_actual ? `≈ ${fmtNum(p.km_dia)} km por día` : "Sin lecturas todavía"}</span></div>`);
    const E = { vencido: ["Vencido", "mal"], pronto: ["Por vencer", "aviso"], ok: ["Al día", "bien"],
                sin_dato: ["Sin datos", ""], sin_km: ["Sin km", ""], sin_plan: ["Sin plan", ""] }[p.estado] || ["—", ""];
    const pr = p.proximo;
    out.push(`<div class="fc-cifra ${E[1]}"><span class="fc-et">Preventivo</span>
      <b class="fc-palabra">${E[0]}</b>
      <span>${pr ? `${fcE(pvNombreGrupo(pr))}: ${pr.km_restantes < 0 ? `pasado ${pvKm(-pr.km_restantes)} km` : `faltan ${pvKm(pr.km_restantes)} km`}`
        : p.estado === "sin_plan" ? "No tiene plan asignado" : p.sin_dato ? `Faltan datos de ${p.sin_dato} ${p.sin_dato === 1 ? "tarea" : "tareas"}` : ""}</span></div>`);
  }
  out.push(`<div class="fc-cifra ${ots.length ? "taller" : ""}"><span class="fc-et">En el taller</span>
    <b class="${ots.length ? "" : "fc-palabra"}">${ots.length ? `${ots.length}<small> ${ots.length === 1 ? "OT abierta" : "OT abiertas"}</small>` : "Libre"}</b>
    <span>${ped.length ? `${ped.length} ${ped.length === 1 ? "pedido de chofer" : "pedidos de choferes"} sin decidir` : "Sin pedidos de choferes"}</span></div>`);
  if (h) {
    const t = h.tres_meses, n = t.preventivo + t.correctivo + t.neumaticos + t.otros;
    out.push(`<div class="fc-cifra"><span class="fc-et">Últimos 90 días</span>
      <b>${n}<small> ${n === 1 ? "trabajo" : "trabajos"}</small></b>
      <span>${n ? [t.preventivo && `${t.preventivo} ${t.preventivo === 1 ? "preventivo" : "preventivos"}`,
                   t.correctivo && `${t.correctivo} ${t.correctivo === 1 ? "correctivo" : "correctivos"}`,
                   t.neumaticos && `${t.neumaticos} de neumáticos`].filter(Boolean).join(" · ") || "Otros trabajos"
               : h.resumen.ultimo ? `El último fue el ${fcFecha(h.resumen.ultimo)}` : "Sin registros"}</span></div>`);
  }
  return out.join("");
}

const fcCaja = (icono, titulo, cuerpo, pie = "", extra = "") => `
  <section class="fc-caja ${extra}">
    <h3><i class="ti ti-${icono}"></i>${titulo}</h3>
    <div class="fc-caja-c">${cuerpo}</div>
    ${pie ? `<div class="fc-caja-pie">${pie}</div>` : ""}
  </section>`;
const fcVacio = (icono, txt) => `<p class="fc-nada"><i class="ti ti-${icono}"></i>${txt}</p>`;
const fcLink = (txt, onclick, icono = "arrow-right") => `<button class="fc-link" onclick="${onclick}">${txt} <i class="ti ti-${icono}"></i></button>`;

function fcCajaToca(d, tabs) {
  const p = d.preventivo;
  if (!p) return "";
  const ve = tabs.includes("preventivo"), puede = ve && pvPuede();
  const pie = ve ? fcLink("Ver el plan completo", "fcIr('preventivo')") : "";
  if (p.estado === "sin_plan")
    return fcCaja("calendar-check", "Qué le toca", fcVacio("clipboard-off", "No tiene plan preventivo asignado."),
      ve ? fcLink("Asignar un plan", "fcIr('preventivo')") : "");
  const pr = p.proximo;
  if (!pr)
    return fcCaja("calendar-check", "Qué le toca",
      fcVacio("help-hexagon", p.estado === "sin_km" ? "Falta el kilometraje del coche para calcular."
        : `Falta saber cuándo se hizo por última vez ${p.sin_dato === 1 ? "una tarea" : `cada una de sus ${p.sin_dato} tareas`}.`),
      ve ? fcLink("Completar en Preventivo", "fcIr('preventivo')") : "");
  const t = p.turno;
  const turno = t
    ? `<div class="fc-turno">${pvTurnoChip(t, false, true)}<span>${t.estado === "en_taller" ? "Está en el taller" : `Turno: ${pvFL(t.fecha)}${t.hora ? " · " + t.hora : ""}`}</span></div>`
    : p.fecha_sugerida ? `<div class="fc-turno"><span><i class="ti ti-sparkles"></i> Conviene que entre el <b>${pvFL(p.fecha_sugerida)}</b></span>
        ${puede ? `<button class="btn btn-ghost btn-sm" onclick="pvAgendar(${d.coche.id}, '${p.fecha_sugerida}')"><i class="ti ti-calendar-plus"></i> Agendar turno</button>` : ""}</div>` : "";
  const cu = p.cumplimiento || {};
  return fcCaja("calendar-check", pr.km_restantes < 0 ? "Le tocaba" : "Qué le toca", `
    <div class="fc-toca ${(PV_ESTADO[pr.estado] || {}).c || ""}">
      <b class="fc-toca-que">${fcE(pvNombreGrupo(pr))}</b>
      ${pvBarra(pr.porcentaje, pr.estado)}
      <div class="fc-toca-vence">${pvVence(pr, p.km_dia)}</div>
      ${pr.tareas.length > 1 ? `<div class="fc-chips">${pr.tareas.slice(0, 8).map(x => `<span>${fcE(x)}</span>`).join("")}${pr.tareas.length > 8 ? `<span>+${pr.tareas.length - 8}</span>` : ""}</div>` : ""}
    </div>
    ${turno}
    <p class="fc-nota">${p.al_dia} de ${p.n_tareas} tareas al día${p.vencidas ? ` · <b class="tx-venc">${p.vencidas} ${p.vencidas === 1 ? "vencida" : "vencidas"}</b>` : ""}${cu.pct != null ? ` · ${cu.pct} % hecho a tiempo en el año` : ""}</p>`, pie);
}

function fcCajaTaller(d) {
  const ots = d.ots || [], ped = d.pedidos || [], cu = d.ots_cuenta;
  const partes = [];
  if (ots.length) partes.push(`<div class="fc-lista">${ots.map(o => `
    <button class="fc-ot" onclick="abrirOT(${o.id})" title="Abrir la OT #${o.id}">
      <span class="fc-ot-cab"><b>OT #${o.id}</b>
        <span class="badge ${o.estado === "en_proceso" ? "warning" : "danger"}"><span class="dot"></span> ${LABEL_ESTADO_OT[o.estado] || o.estado}</span></span>
      <span class="fc-ot-sub">Abierta ${fcHaceDias(o.dias)} · ${o.pendientes ? `faltan ${o.pendientes} de ${o.trabajos} trabajos` : `${o.trabajos} ${o.trabajos === 1 ? "trabajo" : "trabajos"}, todos hechos`}</span>
      ${o.falta.length ? `<span class="fc-ot-falta">${o.falta.map(x => fcE(x)).join(" · ")}${o.pendientes > o.falta.length ? " …" : ""}</span>` : ""}
    </button>`).join("")}</div>`);
  if (ped.length) partes.push(`
    <div class="fc-sub">Pedidos de choferes sin decidir</div>
    <ul class="fc-pedidos">${ped.slice(0, 4).map(p => `
      <li><b>${fcE(p.descripcion)}</b><span>${[p.chofer, p.fecha && fcFecha(p.fecha), p.estado === "agendado" && p.fecha_turno ? `con turno el ${fcFecha(p.fecha_turno)}` : ""].filter(Boolean).map(fcE).join(" · ")}</span></li>`).join("")}
      ${ped.length > 4 ? `<li class="fc-mas">y ${ped.length - 4} más</li>` : ""}</ul>`);
  if (!partes.length) partes.push(fcVacio("mood-smile", "No tiene nada abierto en el taller."));
  const pie = [
    cu && cu.total ? `<span class="fc-pie-txt">${fmtNum(cu.total)} OT en total · ${cu.ultimos_90} en los últimos 90 días</span>` : "",
    ped.length && puedeVerSeccion("pedidos_ot") ? fcLink("Ir a Pedidos", "destNavegar('pedidos_ot')") : "",
  ].filter(Boolean).join("");
  return fcCaja("tool", "En el taller", partes.join(""), pie, "fc-o2");
}

function fcCajaUltimo(d, tabs) {
  const h = d.historia;
  if (!h) return "";
  const ve = tabs.includes("historial");
  if (!h.resumen.registros)
    return fcCaja("timeline-event", "Lo último que se le hizo", fcVacio("notes-off", "Todavía no tiene nada cargado."),
      ve ? fcLink("Ir al historial", "fcIr('historial')") : "");
  const filas = h.ultimos.map(e => {
    const g = e.grupo || "otros";
    const titulo = e.descripcion || e.categoria || HI_TIPO_NOMBRE[e.tipo] || "Registro";
    return `<li style="--c:${hiColor(g)}"><time>${fcFecha(e.fecha)}</time>
      <span class="fc-ult-txt" title="${fcE(titulo)}">${fcE(titulo)}</span>
      <span class="fc-tag">${HI_TIPO_NOMBRE[e.tipo] || MT_NOMBRE[g]}</span></li>`;
  }).join("");
  return fcCaja("timeline-event", "Lo último que se le hizo", `
    <ul class="fc-ultimos">${filas}</ul>
    ${h.resumen.costo ? `<p class="fc-nota">En total se invirtieron <b>${gs(h.resumen.costo)}</b> en ${fmtNum(h.resumen.registros)} registros.</p>` : ""}`,
    ve ? fcLink(`Ver todo el historial (${fmtNum(h.resumen.registros)})`, "fcIr('historial')") : "");
}

function fcCajaCubiertas(d, tabs) {
  const n = d.neumaticos;
  const ve = tabs.includes("neumaticos");
  if (!n) return ve ? fcCaja("disc", "Neumáticos", fcVacio("disc-off", "Todavía no tiene configuración de neumáticos."), fcLink("Ver neumáticos", "fcIr('neumaticos')")) : "";
  const peor = n.peor;
  return fcCaja("disc", "Neumáticos", `
    <div class="fc-ruedas">${n.ruedas.map(r => `<i class="${r.vacia ? "vacia" : "g-" + (r.estado || "optimo")}" title="${fcE(r.nombre)}: ${r.vacia ? "sin neumático" : `${Math.round(r.uso)} % de uso`}"></i>`).join("")}</div>
    <p class="fc-linea"><b>${n.montadas}</b> de ${n.posiciones} montados${n.para_cambiar ? ` · <b class="tx-venc">${n.para_cambiar} para cambiar</b>` : ""}${n.medida ? ` · ${fcE(n.medida)}` : ""}</p>
    ${peor ? `<p class="fc-nota">El de mayor desgaste: ${fcE(peor.nombre)}, al ${Math.round(peor.uso)} % de su vida útil${peor.km_restantes ? ` (le quedan ${fmtNum(Math.round(peor.km_restantes))} km)` : ""}.</p>`
           : `<p class="fc-nota">No hay neumáticos cargados en este coche.</p>`}`,
    ve ? fcLink("Ver neumáticos", "fcIr('neumaticos')") : "");
}

function fcCajaPapeles(d) {
  const docs = d.documentos;
  if (!docs) return "";
  const pie = puedeVerSeccion("documentos") ? fcLink("Ir a Documentos", "destNavegar('documentos')") : "";
  if (!docs.length) return fcCaja("file-certificate", "Documentos", fcVacio("file-off", "No tiene documentos cargados."), pie);
  return fcCaja("file-certificate", "Documentos", `
    <ul class="fc-papeles">${docs.map(x => {
      const cl = x.dias == null ? "" : x.dias < 0 ? "mal" : x.dias <= 30 ? "aviso" : "";
      const cuando = x.dias == null ? "" : x.dias < 0 ? `vencido ${fcHaceDias(-x.dias)}` : x.dias === 0 ? "vence hoy" : x.dias <= 60 ? `en ${x.dias} ${x.dias === 1 ? "día" : "días"}` : "";
      return `<li class="${cl}"><b>${fcE(x.tipo)}${x.nombre ? ` <small>${fcE(x.nombre)}</small>` : ""}</b>
        <span>${fcFecha(x.vence)}${cuando ? ` · ${cuando}` : ""}</span></li>`;
    }).join("")}</ul>`, pie);
}

function fcCajaDatos(d) {
  const c = d.coche, p = d.preventivo;
  const filas = [["Marca y modelo", `${c.marca || ""} ${c.modelo || ""}`.trim()], ["Año", c.anio], ["Chasis", c.chasis],
                 ["Asientos", c.asientos], ["Ejes", c.ejes], ["Tipo", c.tipo], ["Plan preventivo", p && p.plan_nombre]]
    .filter(([, v]) => v);
  return fcCaja("id", "Datos del coche", `<dl class="fc-datos">${filas.map(([k, v]) => `<div><dt>${k}</dt><dd>${fcE(v)}</dd></div>`).join("")}</dl>`);
}

// ─── Órdenes de trabajo: el tablero y el personal van adentro ───────────────
// Tablero de control y Personal de taller ya no están en el menú: son pestañas
// de Órdenes de trabajo. Se ponen arriba de la pantalla cada vez que se dibuja.
function fcSubnavOT() {
  const raiz = document.getElementById("content");
  if (!raiz || !FC_SUBNAV_OT.some(x => x[0] === fc.sec) || typeof puedeVerSeccion !== "function") return;
  const cab = raiz.querySelector(":scope > .page-header");
  if (!cab || raiz.querySelector(":scope > .fc-subnav")) return;
  const ve = FC_SUBNAV_OT.filter(([k]) => puedeVerSeccion(k) && (k !== "ots" || window.USUARIO_ROL !== "auditor"));
  if (ve.length < 2) return;
  cab.insertAdjacentHTML("afterend", `
    <nav class="fc-subnav" aria-label="Partes de Órdenes de trabajo">
      <div class="pv-tabs">
        ${ve.map(([k, i, n]) => `<button class="pv-tab ${fc.sec === k ? "on" : ""}" onclick="destNavegar('${k}')"><i class="ti ti-${i}"></i><span>${n}</span></button>`).join("")}
        <button class="pv-tab" onclick="window.open('/tablero','_blank')" title="La pantalla del taller, en otra pestaña"><i class="ti ti-device-tv"></i><span>Tablero TV</span><i class="ti ti-external-link fc-ext"></i></button>
      </div>
    </nav>`);
}
(function () {
  const raiz = document.getElementById("content");
  if (!raiz || !window.MutationObserver) return;
  new MutationObserver(fcSubnavOT).observe(raiz, { childList: true });
})();
