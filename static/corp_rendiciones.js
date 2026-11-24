// ════════════════════════════════════════════════════════════════════════════
// RENDICIONES Y PAGOS (Corporativos → Rendiciones y pagos)
//
// Lo que rindió cada chofer en un período: por chofer, por día (una grilla
// chofer × día) y el detalle día por día. Los datos salen de
// /api/corp/rendiciones; la liquidación, editar el monto, borrar y el resto de
// las herramientas son las de siempre (app.js), que siguen usando los campos
// #corp-chofer, #corp-desde y #corp-hasta y llaman a cargarRendiciones().
// ════════════════════════════════════════════════════════════════════════════

const cr = { desde: "", hasta: "", preset: "semana", chofer: "", cliente: "", estado: "", q: "", pend: false,
             vista: "choferes", d: null, choferes: [], seq: 0, dia: "" };
const crE = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const crD = f => new Date(f + "T12:00:00");
const crIso = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const crSuma = (f, n) => { const d = crD(f); d.setDate(d.getDate() + n); return crIso(d); };
const CR_DIAS = ["dom", "lun", "mar", "mié", "jue", "vie", "sáb"];
const CR_DIAS_L = ["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"];
const CR_MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];
const CR_EST = { completado: "Completo", entrante: "Entrante", saliente: "Saliente", suspendido: "Suspendido" };
const crIni = n => String(n || "").replace(/,/g, "").split(/\s+/).filter(Boolean).slice(0, 2).map(x => x[0]).join("").toUpperCase();
const crGs = n => "Gs. " + fmtNum(Math.round(n || 0));

function crRango(p) {
  const hoy = crIso(new Date()), d = crD(hoy), dow = (d.getDay() + 6) % 7;
  const lunes = crSuma(hoy, -dow);
  const ini = (y, m) => crIso(new Date(y, m, 1)), fin = (y, m) => crIso(new Date(y, m + 1, 0));
  return {
    hoy: [hoy, hoy], ayer: [crSuma(hoy, -1), crSuma(hoy, -1)],
    semana: [lunes, crSuma(lunes, 6) > hoy ? hoy : crSuma(lunes, 6)], semana_ant: [crSuma(lunes, -7), crSuma(lunes, -1)],
    mes: [ini(d.getFullYear(), d.getMonth()), hoy], mes_ant: [ini(d.getFullYear(), d.getMonth() - 1), fin(d.getFullYear(), d.getMonth() - 1)],
    d30: [crSuma(hoy, -29), hoy],
  }[p];
}
const CR_PRESETS = [["hoy", "Hoy"], ["ayer", "Ayer"], ["semana", "Esta semana"], ["semana_ant", "Semana pasada"],
                    ["mes", "Este mes"], ["mes_ant", "Mes pasado"], ["d30", "Últimos 30 días"]];

function crTextoPeriodo(a, b) {
  const da = crD(a), db = crD(b);
  if (a === b) return `${CR_DIAS_L[da.getDay()]} ${da.getDate()} de ${CR_MESES[da.getMonth()]}`;
  const mismoMes = da.getMonth() === db.getMonth() && da.getFullYear() === db.getFullYear();
  return `${da.getDate()}${mismoMes ? "" : " de " + CR_MESES[da.getMonth()]} al ${db.getDate()} de ${CR_MESES[db.getMonth()]}`
    + (db.getFullYear() !== new Date().getFullYear() ? ` de ${db.getFullYear()}` : "");
}

async function renderCorpResumen() {
  status("Rendiciones de los choferes de corporativos");
  if (!cr.desde) [cr.desde, cr.hasta] = crRango(cr.preset);
  const op = puedeOperarCorp(), ges = puedeGestionarCorp();
  content.innerHTML = `
    <div class="page-header cr-cab">
      <div><h1><i class="ti ti-clipboard-check"></i> Rendiciones y pagos</h1>
        <p>Lo que rindió cada chofer, por fechas</p></div>
      <div class="cr-cab-acc">
        <button class="btn btn-pdf" onclick="descargarRendicionesPDF(true)" title="Una hoja con el total de cada chofer"><i class="ti ti-file-type-pdf"></i> PDF resumido</button>
        <button class="btn btn-pdf" onclick="descargarRendicionesPDF(false)" title="Una hoja por chofer con el detalle"><i class="ti ti-file-description"></i> PDF detallado</button>
        ${op || ges ? `<details class="cr-mas"><summary class="btn btn-ghost"><i class="ti ti-tool"></i> Herramientas <i class="ti ti-chevron-down"></i></summary>
          <div class="cr-mas-menu">
            ${op ? `<button onclick="crCerrarMas();abrirSospechosas()"><i class="ti ti-shield-search"></i><span>Revisar cargas<small>Lo que llama la atención</small></span></button>
            <button onclick="crCerrarMas();abrirDescartables()"><i class="ti ti-eraser"></i><span>Limpiar servicios<small>Pruebas y repetidos</small></span></button>
            <button onclick="crCerrarMas();bpcAbrir()"><i class="ti ti-user-x"></i><span>Borrar por chofer<small>Todo lo de un chofer en un período</small></span></button>` : ""}
            ${ges ? `<button onclick="crCerrarMas();verAccesosChoferes()"><i class="ti ti-key"></i><span>Accesos<small>Usuarios de los choferes</small></span></button>
            <button onclick="crCerrarMas();abrirConfigPlus()"><i class="ti ti-gift"></i><span>Plus semanal</span></button>
            <button onclick="crCerrarMas();abrirTarifas()"><i class="ti ti-currency-guarani"></i><span>Tarifas</span></button>` : ""}
          </div></details>` : ""}
      </div>
    </div>
    <div class="section cr-raiz">
      <div class="cr-periodo">
        <div class="cr-presets" role="group" aria-label="Período">${CR_PRESETS.map(([k, t]) =>
          `<button class="chip ${cr.preset === k ? "activo" : ""}" onclick="crPreset('${k}')">${t}</button>`).join("")}</div>
        <div class="cr-fechas">
          <button class="sm-flecha" onclick="crCorrer(-1)" aria-label="Período anterior"><i class="ti ti-chevron-left"></i></button>
          <b id="cr-titulo">${crTextoPeriodo(cr.desde, cr.hasta)}</b>
          <button class="sm-flecha" id="cr-sig" onclick="crCorrer(1)" aria-label="Período siguiente"><i class="ti ti-chevron-right"></i></button>
          <label class="cr-f"><span>Desde</span><input id="corp-desde" type="date" value="${cr.desde}" onchange="crFechas()"></label>
          <label class="cr-f"><span>Hasta</span><input id="corp-hasta" type="date" value="${cr.hasta}" onchange="crFechas()"></label>
        </div>
      </div>
      <div class="cr-filtros">
        <label class="cr-f cr-f-chofer"><span>Chofer</span><select id="corp-chofer" onchange="cr.chofer=this.value.toLowerCase();crPintar()"><option value="">Todos los choferes</option></select></label>
        <div class="cr-chips" id="cr-clientes"></div>
        <div class="cr-chips" id="cr-estados"></div>
        <label class="cs-busca cr-busca"><i class="ti ti-search"></i><input type="search" value="${crE(cr.q)}" placeholder="Buscar tramo, coche o chofer" oninput="cr.q=this.value;crPintar()"></label>
        <label class="cr-toggle"><input type="checkbox" ${cr.pend ? "checked" : ""} onchange="cr.pend=this.checked;crPintar()"> Solo sin liquidar</label>
      </div>
      <div id="corp-resultado"><div class="dossier-loading"><div class="dossier-spinner"></div></div></div>
    </div>`;
  api("/api/corp/choferes").then(l => {
    cr.choferes = Array.isArray(l) ? l : [];
    const sel = $("#corp-chofer");
    if (sel) sel.innerHTML = `<option value="">Todos los choferes</option>` + cr.choferes.map(c =>
      `<option value="${crE(c.usuario)}" ${c.usuario.toLowerCase() === cr.chofer ? "selected" : ""}>${crE(c.nombre)}${c.activo === 0 ? " (inactivo)" : ""}</option>`).join("");
  }).catch(() => {});
  cargarRendiciones();
}

function crCerrarMas() { document.querySelector(".cr-mas")?.removeAttribute("open"); }
function crPreset(p) { cr.preset = p; [cr.desde, cr.hasta] = crRango(p); renderCorpResumen(); }
function crFechas() {
  const a = $("#corp-desde").value, b = $("#corp-hasta").value;
  if (!a || !b) return;
  [cr.desde, cr.hasta] = a <= b ? [a, b] : [b, a];
  cr.preset = ""; renderCorpResumen();
}
function crCorrer(n) {
  const largo = Math.round((crD(cr.hasta) - crD(cr.desde)) / 864e5) + 1;
  let a, b;
  if (["mes", "mes_ant"].includes(cr.preset) || (cr.desde.endsWith("-01") && crSuma(cr.hasta, 1).endsWith("-01"))) {
    const d = crD(cr.desde); d.setMonth(d.getMonth() + n);
    a = crIso(new Date(d.getFullYear(), d.getMonth(), 1)); b = crIso(new Date(d.getFullYear(), d.getMonth() + 1, 0));
  } else { a = crSuma(cr.desde, n * largo); b = crSuma(cr.hasta, n * largo); }
  const hoy = crIso(new Date());
  if (a > hoy) return;
  cr.desde = a; cr.hasta = b > hoy ? hoy : b; cr.preset = ""; renderCorpResumen();
}

async function cargarRendiciones() {
  const cont = $("#corp-resultado");
  if (!cont) return;
  const seq = ++cr.seq;
  cont.classList.add("cargando");
  const d = await api(`/api/corp/rendiciones?desde=${cr.desde}&hasta=${cr.hasta}`).catch(() => null);
  if (seq !== cr.seq || !$("#corp-resultado")) return;
  cont.classList.remove("cargando");
  if (!d || d.error) { cont.innerHTML = `<div class="empty"><i class="ti ti-alert-circle"></i>${crE((d && d.error) || "No se pudieron traer las rendiciones")}</div>`; return; }
  cr.d = d;
  const sig = $("#cr-sig"); if (sig) sig.disabled = cr.hasta >= (d.hoy || crIso(new Date()));
  crPintar();
}

function crFiltradas(sinEstado) {
  const q = cr.q.trim().toLowerCase();
  return cr.d.rendiciones.filter(r =>
    (!cr.chofer || r.usuario === cr.chofer) && (!cr.cliente || r.cliente_c === cr.cliente) &&
    (sinEstado || !cr.estado || (cr.estado === "medias" ? ["entrante", "saliente"].includes(r.estado) : r.estado === cr.estado)) &&
    (!cr.pend || !r.liquidado) &&
    (!q || `${r.chofer} ${r.cliente_c} ${r.tramo_c} ${r.bus_interno}`.toLowerCase().includes(q)));
}

function crPintar() {
  const cont = $("#corp-resultado");
  if (!cont || !cr.d) return;
  const base = crFiltradas(true), rs = crFiltradas();
  // Chips de empresas y estados, con cuántos hay
  const porCli = {};
  cr.d.rendiciones.forEach(r => { porCli[r.cliente_c] = (porCli[r.cliente_c] || 0) + 1; });
  $("#cr-clientes").innerHTML = `<button class="chip ${!cr.cliente ? "activo" : ""}" onclick="cr.cliente='';crPintar()">Todas las empresas</button>` +
    Object.entries(porCli).sort((a, b) => b[1] - a[1]).map(([c, n]) =>
      `<button class="chip ${cr.cliente === c ? "activo" : ""}" onclick="cr.cliente=cr.cliente==='${crE(c)}'?'':'${crE(c)}';crPintar()">${crE(c)} <span class="chip-nota">${n}</span></button>`).join("");
  const cuenta = k => base.filter(r => k === "medias" ? ["entrante", "saliente"].includes(r.estado) : r.estado === k).length;
  $("#cr-estados").innerHTML = [["", "Todos", base.length], ["completado", "Completos", cuenta("completado")],
    ["medias", "Medias", cuenta("medias")], ["suspendido", "Suspendidos", cuenta("suspendido")]].map(([k, t, n]) =>
    `<button class="chip ${cr.estado === k ? "activo" : ""}" onclick="cr.estado='${k}';crPintar()">${t} <span class="chip-nota">${n}</span></button>`).join("");

  if (!cr.d.rendiciones.length) {
    cont.innerHTML = `<div class="sm-vacio"><i class="ti ti-calendar-off"></i><b>Nadie rindió en este período</b><span>Probá con otras fechas, arriba.</span></div>`;
    return;
  }
  const vivas = rs.filter(r => r.estado !== "suspendido");
  const choferes = new Set(rs.map(r => r.usuario));
  const dias = new Set(vivas.map(r => r.fecha_servicio));
  const filtrado = cr.cliente || cr.estado || cr.q || cr.pend;
  const liq = cr.d.liquidacion.filter(l => !cr.chofer || (l.chofer_usuario || "").toLowerCase() === cr.chofer);
  const aPagar = filtrado ? rs.reduce((s, r) => s + (+r.monto || 0), 0) : liq.reduce((s, l) => s + (l.total || 0), 0);
  const pend = rs.filter(r => !r.liquidado).reduce((s, r) => s + (+r.monto || 0), 0);
  cont.innerHTML = `
    <div class="cr-kpis">
      <div class="cr-kpi grande"><b>${rs.length}</b><span>${rs.length === 1 ? "servicio" : "servicios"} rendidos</span>
        <small>${vivas.length !== rs.length ? `${vivas.length} hechos · ${rs.length - vivas.length} suspendidos` : `en ${dias.size} ${dias.size === 1 ? "día" : "días"}`}</small></div>
      <div class="cr-kpi"><b>${choferes.size}</b><span>${choferes.size === 1 ? "chofer" : "choferes"}</span></div>
      <div class="cr-kpi"><b>${rs.filter(r => r.estado === "completado").length}</b><span>completos</span></div>
      <div class="cr-kpi"><b>${rs.filter(r => ["entrante", "saliente"].includes(r.estado)).length}</b><span>medias</span></div>
      <div class="cr-kpi plata"><b>${crGs(aPagar)}</b><span>${filtrado ? "en tramos (con el filtro)" : "a pagar en el período, con plus"}</span>
        ${pend && pend !== aPagar ? `<small>${crGs(pend)} todavía sin liquidar</small>` : ""}</div>
    </div>
    <div class="cr-tabs" role="tablist">
      ${[["choferes", "users", "Por chofer"], ["dias", "calendar-stats", "Por día"], ["detalle", "list-details", "Detalle"]].map(([k, i, t]) =>
        `<button role="tab" aria-selected="${cr.vista === k}" class="${cr.vista === k ? "on" : ""}" onclick="cr.vista='${k}';crPintar()"><i class="ti ti-${i}"></i> ${t}</button>`).join("")}
      ${cr.dia || cr.chofer ? `<span class="cr-tab-filtro">${cr.chofer ? `<b>${crE((rs[0] || {}).chofer || cr.chofer)}</b>` : ""}${cr.dia ? ` ${crTextoPeriodo(cr.dia, cr.dia)}` : ""}
        <button class="sm-link" onclick="crQuitar()">Ver todo</button></span>` : ""}
    </div>
    <div id="cr-vista">${!rs.length ? `<div class="empty chico">Ningún servicio con esos filtros</div>`
      : cr.vista === "dias" ? crVistaDias(rs) : cr.vista === "detalle" ? crVistaDetalle(rs) : crVistaChoferes(rs, liq, filtrado)}</div>`;
}

function crQuitar() {
  cr.dia = ""; cr.chofer = "";
  const s = $("#corp-chofer"); if (s) s.value = "";
  crPintar();
}
function crVerChofer(u, vista) {
  cr.chofer = u; cr.vista = vista || "detalle";
  const s = $("#corp-chofer"); if (s) s.value = [...s.options].find(o => o.value.toLowerCase() === u)?.value || "";
  crPintar(); window.scrollTo({ top: 0, behavior: "smooth" });
}
function crVerCelda(u, f) { cr.dia = f; crVerChofer(u, "detalle"); }

// ── Por chofer ──
function crVistaChoferes(rs, liq, filtrado) {
  const fechas = crFechasPeriodo();
  const por = {};
  rs.forEach(r => {
    const c = por[r.usuario] = por[r.usuario] || { u: r.usuario, nombre: r.chofer, n: 0, comp: 0, med: 0, susp: 0, monto: 0, pend: 0, dias: {}, clientes: {} };
    c.n++; c.monto += +r.monto || 0;
    if (!r.liquidado) c.pend += +r.monto || 0;
    if (r.estado === "completado") c.comp++; else if (r.estado === "suspendido") c.susp++; else c.med++;
    if (r.estado !== "suspendido") c.dias[r.fecha_servicio] = (c.dias[r.fecha_servicio] || 0) + 1;
    c.clientes[r.cliente_c] = (c.clientes[r.cliente_c] || 0) + 1;
  });
  const liqDe = u => liq.find(l => (l.chofer_usuario || "").toLowerCase() === u);
  const filas = Object.values(por).sort((a, b) => b.n - a.n || a.nombre.localeCompare(b.nombre));
  const max = Math.max(1, ...filas.map(f => f.n));
  const op = puedeOperarCorp();
  return `<div class="cr-tabla-caja"><table class="cr-tabla">
    <thead><tr><th>#</th><th>Chofer</th><th class="num">Servicios</th><th class="center">Días</th>
      <th class="cr-sp">${fechas.length <= 31 ? "Día por día" : "Servicios"}</th>
      <th class="num">Tramos</th>${filtrado ? "" : `<th class="num">Plus</th><th class="num">Total</th>`}${op ? "<th></th>" : ""}</tr></thead>
    <tbody>${filas.map((f, i) => {
      const l = liqDe(f.u) || {};
      return `<tr>
        <td class="cr-pos">${i + 1}</td>
        <td><button class="cr-quien" onclick="crVerChofer('${crE(f.u)}')" title="Ver sus servicios">
          <span class="sm-avatar">${crIni(f.nombre)}</span>
          <span><b>${crE(f.nombre)}</b><small>${Object.entries(f.clientes).sort((a, b) => b[1] - a[1]).map(([c, n]) => `${crE(c)} ${n}`).join(" · ")}</small></span></button></td>
        <td class="num"><span class="cr-n"><b>${f.n}</b><i style="width:${Math.max(4, Math.round(56 * f.n / max))}px"></i></span>
          <small class="cr-desg">${[f.comp && `${f.comp} completos`, f.med && `${f.med} medias`, f.susp && `${f.susp} susp.`].filter(Boolean).join(" · ")}</small></td>
        <td class="center">${Object.keys(f.dias).length}</td>
        <td class="cr-sp">${fechas.length <= 31 ? `<span class="cr-tira">${fechas.map(x => {
          const n = f.dias[x] || 0;
          return `<i class="n${Math.min(n, 3)}" title="${CR_DIAS[crD(x).getDay()]} ${crD(x).getDate()}: ${n || "nada"}" onclick="crVerCelda('${crE(f.u)}','${x}')"></i>`;
        }).join("")}</span>` : ""}</td>
        <td class="num">${fmtNum(Math.round(f.monto))}${f.pend && f.pend !== f.monto ? `<small class="cr-desg">${fmtNum(Math.round(f.pend))} sin liquidar</small>` : ""}</td>
        ${filtrado ? "" : `<td class="num">${l.tiene_plus ? fmtNum(l.plus) : "—"}</td><td class="num"><b>${fmtNum(Math.round(l.total || f.monto))}</b></td>`}
        ${op ? `<td class="center cr-acc-ch"><button class="btn btn-ghost btn-sm" title="Rendir por fechas: PDF con lo que hizo de tal a tal fecha" onclick="rksRendir('${crE(f.u)}','${crE(f.nombre).replace(/'/g, "\\'")}', cr.desde, cr.hasta)"><i class="ti ti-file-type-pdf"></i> PDF</button>
              ${f.u && f.pend ? `<button class="btn btn-ghost btn-sm" onclick="abrirLiquidacion('${crE(f.u)}','${crE(f.nombre).replace(/'/g, "\\'")}')"><i class="ti ti-cash"></i> Liquidar</button>`
              : `<span class="cr-ok"><i class="ti ti-circle-check"></i> Al día</span>`}</td>` : ""}
      </tr>`;
    }).join("")}</tbody></table></div>
    ${fechas.length <= 31 ? `<p class="cr-nota"><i class="ti ti-info-circle"></i> En «Día por día» cada cuadrito es un día del período: más oscuro, más servicios. Tocalo para ver ese día.</p>` : ""}`;
}

function crFechasPeriodo() {
  const out = [];
  for (let f = cr.desde; f <= cr.hasta && out.length < 400; f = crSuma(f, 1)) out.push(f);
  return out;
}

// ── Por día: grilla chofer × día ──
function crVistaDias(rs) {
  let cols = crFechasPeriodo(), semanal = false;
  if (cols.length > 31) {                // períodos largos: por semana
    semanal = true;
    const lunes = f => crSuma(f, -((crD(f).getDay() + 6) % 7));
    cols = [...new Set(cols.map(lunes))];
  }
  const clave = f => semanal ? crSuma(f, -((crD(f).getDay() + 6) % 7)) : f;
  const por = {}, tot = {};
  rs.forEach(r => {
    if (r.estado === "suspendido" && cr.estado !== "suspendido") return;
    const k = clave(r.fecha_servicio);
    const c = por[r.usuario] = por[r.usuario] || { u: r.usuario, nombre: r.chofer, n: 0, k: {} };
    c.k[k] = (c.k[k] || 0) + 1; c.n++;
    tot[k] = (tot[k] || 0) + 1;
  });
  const filas = Object.values(por).sort((a, b) => a.nombre.localeCompare(b.nombre));
  const max = Math.max(1, ...filas.flatMap(f => Object.values(f.k)));
  const hoy = cr.d.hoy;
  const cab = f => semanal ? `<b>${crD(f).getDate()}/${crD(f).getMonth() + 1}</b><small>sem.</small>`
    : `<small>${CR_DIAS[crD(f).getDay()]}</small><b>${crD(f).getDate()}</b>`;
  return `<div class="cr-tabla-caja"><table class="cr-grilla">
    <thead><tr><th class="cr-g-nom">Chofer</th>${cols.map(f => `<th class="${!semanal && [0, 6].includes(crD(f).getDay()) ? "finde" : ""} ${f === hoy ? "hoy" : ""}">${cab(f)}</th>`).join("")}<th class="cr-g-tot">Total</th></tr></thead>
    <tbody>${filas.map(f => `<tr><th class="cr-g-nom"><button class="cr-link" onclick="crVerChofer('${crE(f.u)}')">${crE(f.nombre)}</button></th>
      ${cols.map(k => { const n = f.k[k] || 0;
        return `<td>${n ? `<button class="cr-celda" style="--a:${(0.18 + 0.82 * n / max).toFixed(2)}" onclick="${semanal ? `crVerChofer('${crE(f.u)}')` : `crVerCelda('${crE(f.u)}','${k}')`}" title="${crE(f.nombre)}: ${n} el ${semanal ? "semana del " : ""}${crD(k).getDate()}/${crD(k).getMonth() + 1}">${n}</button>` : `<span class="cr-cero">·</span>`}</td>`; }).join("")}
      <td class="cr-g-tot"><b>${f.n}</b></td></tr>`).join("")}</tbody>
    <tfoot><tr><th class="cr-g-nom">Total del ${semanal ? "período" : "día"}</th>${cols.map(k => `<td><b>${tot[k] || ""}</b></td>`).join("")}<td class="cr-g-tot"><b>${Object.values(tot).reduce((a, b) => a + b, 0)}</b></td></tr></tfoot>
  </table></div>
  <p class="cr-nota"><i class="ti ti-info-circle"></i> Cantidad de servicios ${cr.estado === "suspendido" ? "suspendidos" : "hechos (sin los suspendidos)"} de cada chofer ${semanal ? "por semana" : "por día"}. Tocá un número para ver el detalle.</p>`;
}

// ── Detalle, agrupado por día ──
function crVistaDetalle(rs) {
  const lista = cr.dia ? rs.filter(r => r.fecha_servicio === cr.dia) : rs;
  if (!lista.length) return `<div class="empty chico">Ese día no rindió nada con estos filtros</div>`;
  const porDia = {};
  lista.forEach(r => (porDia[r.fecha_servicio] = porDia[r.fecha_servicio] || []).push(r));
  const op = puedeOperarCorp();
  return Object.keys(porDia).sort().reverse().map(f => {
    const items = porDia[f].sort((a, b) => a.cliente_c.localeCompare(b.cliente_c) || a.tramo_c.localeCompare(b.tramo_c) || a.chofer.localeCompare(b.chofer));
    const monto = items.reduce((s, r) => s + (+r.monto || 0), 0);
    return `<section class="cr-dia">
      <header><b>${crTextoPeriodo(f, f)}</b><span>${items.length} ${items.length === 1 ? "servicio" : "servicios"} · ${crGs(monto)}</span></header>
      <div class="cr-filas">${items.map(r => {
        const km = (+r.km_final || 0) - (+r.km_inicial || 0);
        const datos = [r.bus_interno && `Coche ${crE(r.bus_interno)}`, (r.hora_inicio || r.hora_fin) && `${crE(r.hora_inicio || "?")}${r.hora_fin ? "–" + crE(r.hora_fin) : ""}`,
                       km > 0 && km < 2000 && `${fmtNum(km)} km`, r.pasajeros && `${r.pasajeros} pasajeros`,
                       r.cargado && `marcado ${r.cargado.slice(0, 10) !== f ? "el " + csFC(r.cargado.slice(0, 10)) + " " : ""}a las ${r.cargado.slice(11, 16)}`,
                       r.editado_por && (r.editado_por.startsWith("cargado por") ? crE(r.editado_por) : "corregido por " + crE(r.editado_por))].filter(Boolean);
        return `<div class="cr-fila ${r.estado === "suspendido" ? "susp" : ""}">
          <span class="sm-avatar">${crIni(r.chofer)}</span>
          <div class="cr-fila-quien"><button class="cr-link" onclick="crVerChofer('${crE(r.usuario)}')"><b>${crE(r.chofer)}</b></button>
            <small>${datos.join(" · ") || "Sin más datos"}</small>
            ${r.observacion ? `<small class="cr-obs"><i class="ti ti-message"></i> ${crE(r.observacion)}</small>` : ""}</div>
          <div class="cr-fila-que"><span class="sm-cli">${crE(r.cliente_c)}</span> ${crE(r.tramo_c)}</div>
          <span class="sm-estado e-${crE(r.estado)}">${CR_EST[r.estado] || crE(r.estado)}</span>
          <span class="cr-monto">${r.monto ? fmtNum(Math.round(r.monto)) : "—"}${r.monto_fijo ? ` <i class="ti ti-pin-filled" title="Monto fijado a mano por ${crE(r.editado_por || "admin")}"></i>` : ""}</span>
          ${op ? (r.liquidado ? `<span class="sm-liq" title="Ya está liquidado"><i class="ti ti-lock"></i> Liquidado</span>`
            : `<span class="sm-acc">
                <button class="sm-borrar cr-ed" title="Cambiar el monto" onclick="editarMontoRendicion(${r.id}, ${+r.monto || 0}, ${r.monto_fijo ? 1 : 0})"><i class="ti ti-pencil"></i></button>
                <button class="sm-borrar cr-ed" title="Pasar a otro chofer" onclick="crPasar(${r.id})"><i class="ti ti-user-share"></i></button>
                <button class="sm-borrar" title="Eliminar" onclick="borrarRendicion(${r.id}, '${crE(r.chofer).replace(/'/g, "\\'")}', '${f}')"><i class="ti ti-trash"></i></button></span>`) : ""}
        </div>`;
      }).join("")}</div></section>`;
  }).join("");
}

// Pasar un servicio a otro chofer (lo marcó uno y lo hizo otro)
function crPasar(id) {
  const r = cr.d.rendiciones.find(x => x.id === id);
  if (!r) return;
  const lista = cr.choferes.filter(c => c.activo !== 0 && c.usuario.toLowerCase() !== r.usuario);
  rvModal({
    titulo: "Pasar a otro chofer", icono: "user-share", ancho: 460,
    sub: `${crE(r.cliente_c)} ${crE(r.tramo_c)} · ${crTextoPeriodo(r.fecha_servicio, r.fecha_servicio)}. Hoy figura a nombre de <b>${crE(r.chofer)}</b>.`,
    cuerpo: `<input class="form-input" id="cr-pasar-q" placeholder="Buscar chofer…" autocomplete="off" style="margin-bottom:8px">
      <select class="form-input" id="cr-pasar-a" size="8" style="height:auto">${lista.map(c => `<option value="${crE(c.usuario)}">${crE(c.nombre)} (${crE(c.usuario)})</option>`).join("")}</select>`,
    pie: `<button class="btn btn-ghost" onclick="this.closest('.modal-overlay').remove()">Cancelar</button>
          <button class="btn btn-primary" id="cr-pasar-si"><i class="ti ti-user-share"></i> Pasar</button>`,
  });
  const sel = $("#cr-pasar-a");
  $("#cr-pasar-q").oninput = e => { const q = e.target.value.trim().toLowerCase(); [...sel.options].forEach(o => { o.hidden = q && !o.textContent.toLowerCase().includes(q); }); };
  $("#cr-pasar-si").onclick = async e => {
    if (!sel.value) { toast("Elegí el chofer", "error"); return; }
    e.target.disabled = true;
    const x = await api(`/api/corp/marcados/${id}/chofer`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ usuario: sel.value }) }).catch(err => ({ error: err.message }));
    document.querySelector(".modal-overlay")?.remove();
    toast((x && (x.msg || x.error)) || "No se pudo pasar", x && x.ok ? "success" : "error");
    cargarRendiciones();
  };
}
