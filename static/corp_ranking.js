// ════════════════════════════════════════════════════════════════════════════
// RANKING DE CHOFERES DE CORPORATIVOS (Corporativos → Ranking de choferes)
//
// Puntaje de 0 a 100 por chofer: cumplimiento de lo asignado, carga a tiempo,
// prolijidad (rendiciones sin observaciones) y consumo. Lo calcula
// corp_ranking.py; acá se elige el período y la empresa, se ve el podio, la
// tabla y, al tocar un chofer, por qué tiene ese puntaje.
// ════════════════════════════════════════════════════════════════════════════

const rk = { preset: "30", desde: "", hasta: "", cliente: "", d: null, abierto: "", seq: 0, q: "" };
const RK_PARTES = [["cumplimiento", "Cumplimiento", "clipboard-check", "De lo que se le asignó, cuánto rindió"],
                   ["a_tiempo", "A tiempo", "clock-check", "Rendiciones cargadas el mismo día o al siguiente"],
                   ["prolijidad", "Prolijidad", "checks", "Rendiciones sin observaciones"],
                   ["consumo", "Consumo", "gas-station", "Combustible contra lo normal de sus coches"]];
const rkE = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const rkTono = p => p == null ? "" : p >= 85 ? "bien" : p >= 70 ? "medio" : "mal";
function rkQuery() {
  return new URLSearchParams({ desde: rk.desde, hasta: rk.hasta, ...(rk.cliente ? { cliente: rk.cliente } : {}) }).toString();
}

async function renderCorpRanking() {
  status("Ranking de choferes de corporativos");
  if (!rk.desde) [rk.desde, rk.hasta] = csPeriodo(rk.preset);
  content.innerHTML = `
    <div class="page-header">
      <h1><i class="ti ti-trophy"></i> Ranking de choferes</h1>
      <p>Quién trabaja mejor en corporativos: cumple lo que se le asigna, carga a tiempo, sin errores y sin gastar combustible de más</p>
      <div class="page-actions"><button class="btn btn-ghost" onclick="rksElegir()"><i class="ti ti-calendar-user"></i> Servicios de un chofer</button>
        <button class="btn btn-ghost" onclick="rkPdf()"><i class="ti ti-printer"></i> Imprimir</button></div>
    </div>
    <div class="section cs-raiz rk-raiz">
      <div class="cs-filtros" id="rk-filtros"></div>
      <div id="rk-cuerpo"><div class="dossier-loading"><div class="dossier-spinner"></div></div></div>
    </div>`;
  rkFiltros();
  rkCargar();
}
function rkFiltros() {
  const f = $("#rk-filtros");
  if (!f) return;
  const clis = (rk.d && rk.d.clientes_disponibles && rk.d.clientes_disponibles.length ? rk.d.clientes_disponibles : rk.clis) || [];
  if (clis.length) rk.clis = clis;
  f.innerHTML = `
    <div class="cs-fila-f">
      <div class="cs-chips" role="group" aria-label="Período">
        ${CS_PRESETS.filter(p => p[0] !== "7").map(([k, t]) => `<button class="chip ${rk.preset === k ? "activo" : ""}" onclick="rkPeriodo('${k}')">${t}</button>`).join("")}
      </div>
      <label class="cs-fechas ${rk.preset === "custom" ? "on" : ""}"><i class="ti ti-calendar"></i>
        <input type="date" id="rk-desde" value="${rk.desde}" max="${trHoy()}" onchange="rkFechas()" aria-label="Desde">
        <span>al</span>
        <input type="date" id="rk-hasta" value="${rk.hasta}" max="${trHoy()}" onchange="rkFechas()" aria-label="Hasta"></label>
    </div>
    ${clis.length ? `<div class="cs-chips" role="group" aria-label="Empresa">
      <button class="chip ${!rk.cliente ? "activo" : ""}" onclick="rkCliente('')">Todas las empresas</button>
      ${clis.map(c => `<button class="chip ${rk.cliente === c ? "activo" : ""}" onclick="rkCliente('${rkE(c)}')">${rkE(c)}</button>`).join("")}
    </div>` : ""}`;
}
function rkPeriodo(k) { rk.preset = k; [rk.desde, rk.hasta] = csPeriodo(k); rkFiltros(); rkCargar(); }
function rkFechas() {
  const d = $("#rk-desde").value, h = $("#rk-hasta").value;
  if (!d || !h) return;
  rk.preset = "custom"; rk.desde = d <= h ? d : h; rk.hasta = d <= h ? h : d;
  rkFiltros(); rkCargar();
}
function rkCliente(c) { rk.cliente = c; rk.abierto = ""; rkFiltros(); rkCargar(); }
function rkPdf() { window.open(`/api/corp/ranking_choferes/pdf?${rkQuery()}`, "_blank"); }

async function rkCargar(fresco) {
  const seq = ++rk.seq, box = $("#rk-cuerpo");
  if (box && rk.d) box.classList.add("cargando");
  const d = await api(`/api/corp/ranking_choferes?${rkQuery()}${fresco ? "&fresco=1" : ""}`).catch(() => null);
  if (seq !== rk.seq || !$("#rk-cuerpo")) return;
  $("#rk-cuerpo").classList.remove("cargando");
  if (!d || d.error) { $("#rk-cuerpo").innerHTML = `<div class="empty"><i class="ti ti-alert-circle"></i>${rkE((d && d.error) || "No se pudo traer el ranking")}</div>`; return; }
  const antes = (rk.clis || []).join("|");
  rk.d = d;
  if (!rk.cliente && antes !== (d.clientes_disponibles || []).join("|")) rkFiltros();
  rkPintar();
}

function rkPintar() {
  const d = rk.d, box = $("#rk-cuerpo");
  if (!d || !box) return;
  if (!d.ranking.length) {
    box.innerHTML = `<div class="empty"><i class="ti ti-users-group"></i>Ningún chofer hizo ${d.min_servicios} servicios o más ${rk.cliente ? `en ${rkE(rk.cliente)} ` : ""}en este período.</div>${rkPocos()}`;
    return;
  }
  const top = d.ranking.slice(0, 3);
  const mejorar = d.ranking.filter(f => f.puntaje < 70).length;
  box.innerHTML = `
    <div class="rk-podio">${[1, 0, 2].filter(i => top[i]).map(i => {
      const f = top[i];
      return `<button class="rk-pod p${i + 1}" onclick="rkAbrir('${rkE(f.usuario)}', true)">
        <span class="rk-med"><i class="ti ti-medal"></i>${i + 1}</span>
        <b>${rkE(f.nombre)}</b>
        <span class="rk-pod-pts">${f.puntaje}<small> pts</small></span>
        <span class="rk-pod-sub">${fmtNum(f.servicios)} servicios · ${rkE(f.clientes.join(", "))}</span>
      </button>`;
    }).join("")}</div>
    <div class="rk-resumen">
      <span><b>${d.ranking.length}</b> choferes en el ranking</span>
      <span>Promedio <b>${d.promedio}</b> pts</span>
      ${mejorar ? `<span class="mal"><b>${mejorar}</b> con menos de 70 pts</span>` : ""}
      <span class="rk-ayuda" title="${RK_PARTES.map(([k, n, , x]) => `${n} (${d.pesos[k]}): ${x}`).join("\n")}"><i class="ti ti-info-circle"></i> Cómo se calcula</span>
    </div>
    ${!d.dias_publicados ? `<div class="rk-nota"><i class="ti ti-info-circle"></i> En este período no hay asignaciones publicadas: el cumplimiento no entra en el puntaje.</div>` : ""}
    <div class="pv-card rk-card">
      <div class="pv-card-cab"><h3><i class="ti ti-list-numbers"></i> Todos</h3>
        <label class="cs-busca"><i class="ti ti-search"></i><input type="search" id="rk-q" value="${rkE(rk.q)}" placeholder="Buscar chofer" oninput="rk.q=this.value;rkTabla()"></label></div>
      <div id="rk-tabla">${rkTablaHTML()}</div>
    </div>
    ${rkPocos()}
    <p class="rk-pie"><i class="ti ti-info-circle"></i> Puntaje de 0 a 100: ${RK_PARTES.map(([k, n]) => `${n.toLowerCase()} (${d.pesos[k]})`).join(", ")}.
      Si a un chofer le falta un dato (no tuvo asignación publicada, no se le pudo medir el consumo) se calcula con el resto.
      Entran los que hicieron al menos ${d.min_servicios} servicios.</p>`;
}

function rkTabla() { const t = $("#rk-tabla"); if (t) t.innerHTML = rkTablaHTML(); }
function rkTablaHTML() {
  const q = rk.q.trim().toLowerCase();
  const filas = rk.d.ranking.filter(f => !q || f.nombre.toLowerCase().includes(q));
  if (!filas.length) return `<div class="empty chico">Nadie con ese nombre</div>`;
  return `<div class="rk-lista">${filas.map(f => `
    <div class="rk-fila ${rk.abierto === f.usuario ? "abierta" : ""}" id="rk-${rkE(f.usuario)}">
      <button class="rk-fila-cab" onclick="rkAbrir('${rkE(f.usuario)}')" aria-expanded="${rk.abierto === f.usuario}">
        <span class="rk-pos ${f.pos <= 3 ? "top" : ""}">${f.pos}</span>
        <span class="rk-nom"><b>${rkE(f.nombre)}</b><small>${fmtNum(f.servicios)} servicios · ${f.dias} días · ${rkE(f.clientes.join(", "))}</small></span>
        <span class="rk-barras">${RK_PARTES.map(([k, n]) => {
          const v = f.partes[k];
          return `<span class="rk-b ${v == null ? "nd" : rkTono(v)}" title="${n}: ${v == null ? "sin datos" : v + " %"}"><i style="width:${v == null ? 0 : Math.max(4, v)}%"></i><em>${n}</em></span>`;
        }).join("")}</span>
        <span class="rk-pts ${rkTono(f.puntaje)}">${f.puntaje}</span>
        <i class="ti ti-chevron-down rk-flecha"></i>
      </button>
      ${rk.abierto === f.usuario ? rkDetalle(f) : ""}
    </div>`).join("")}</div>`;
}
function rkAbrir(u, ir) {
  rk.abierto = rk.abierto === u && !ir ? "" : u;
  if (ir && rk.q) rk.q = "";
  rkTabla();
  if (ir) document.getElementById("rk-" + u)?.scrollIntoView({ behavior: "smooth", block: "center" });
}

function rkDetalle(f) {
  const a = f.asignacion, t = f.a_tiempo, c = f.consumo;
  const caja = (k, cuerpo) => {
    const p = RK_PARTES.find(x => x[0] === k), v = f.partes[k];
    return `<div class="rk-det-caja ${v == null ? "nd" : rkTono(v)}">
      <div class="rk-det-tit"><i class="ti ti-${p[2]}"></i>${p[1]}<b>${v == null ? "—" : v + " %"}</b></div>
      <p>${cuerpo}</p></div>`;
  };
  return `<div class="rk-det">
    <div class="rk-det-acc">
      <button class="btn btn-pdf btn-sm" onclick="rksRendir('${rkE(f.usuario)}', '${rkE(f.nombre).replace(/'/g, "\\'")}', rk.desde, rk.hasta)" title="Elegí de qué fecha a qué fecha y bajá el PDF con lo que hizo"><i class="ti ti-file-type-pdf"></i> Rendir por fechas</button>
      <button class="btn btn-primary btn-sm" onclick="rkServicios('${rkE(f.usuario)}', '${rkE(f.nombre).replace(/'/g, "\\'")}')"><i class="ti ti-calendar-user"></i> Ver sus servicios por fecha${puedeOperarCorp() ? " · agregar o quitar" : ""}</button></div>
    ${f.motivos.length ? `<div class="rk-mejorar"><i class="ti ti-target-arrow"></i><span><b>A mejorar:</b> ${rkE(f.motivos.join("; "))}.</span></div>` : `<div class="rk-mejorar bien"><i class="ti ti-star"></i><span>Viene muy bien en todo.</span></div>`}
    <div class="rk-det-grid">
      ${caja("cumplimiento", a ? `Se le asignaron <b>${a.asignados}</b> servicios en ${a.dias} días publicados. ${a.sin_rendir ? `No rindió <b>${a.sin_rendir}</b>. ` : ""}${a.otro_chofer ? `<b>${a.otro_chofer}</b> los hizo otro chofer. ` : ""}${a.sin_rendir || a.otro_chofer ? "" : "Rindió todo lo asignado. "}Confirmó la asignación ${a.confirmo} de ${a.dias} días.` : "No tuvo asignaciones publicadas en el período.")}
      ${caja("a_tiempo", t.cargadas ? `<b>${t.a_tiempo}</b> de ${t.cargadas} rendiciones cargadas el mismo día o al siguiente.${t.atraso_max > 1 ? ` La más atrasada, ${t.atraso_max} días después.` : ""}` : "Sin fecha de carga registrada.")}
      ${caja("prolijidad", f.n_observadas ? `<b>${f.n_observadas}</b> de ${f.rendiciones} rendiciones con observaciones.` : `Ninguna observación en ${f.rendiciones} rendiciones.`)}
      ${caja("consumo", c ? `Gasta <b>${c.desvio_pct > 0 ? "+" : ""}${String(c.desvio_pct).replace(".", ",")} %</b> contra lo normal de los coches que maneja (${c.medidos} tanques medidos${c.alertas ? `, ${c.alertas} con alerta` : ""}).` : "No hay tanques suficientes para medirlo.")}
    </div>
    ${a && a.detalle.length ? `<div class="rk-det-lista"><div class="rk-det-sub">Asignado y no cumplido</div>${a.detalle.map(x => `<div>${rkE(x)}</div>`).join("")}</div>` : ""}
    ${f.observadas.length ? `<div class="rk-det-lista"><div class="rk-det-sub">Rendiciones con observaciones${f.n_observadas > f.observadas.length ? ` (las últimas ${f.observadas.length})` : ""}</div>${f.observadas.map(o => `<div><b>${csFC(o.fecha)}</b> ${rkE(o.tramo)} — ${rkE(o.motivo)}</div>`).join("")}</div>` : ""}
    <div class="rk-det-num"><span>${fmtNum(f.pasajeros)} pasajeros</span><span>${fmtNum(f.km)} km</span>${f.suspendidos ? `<span>${f.suspendidos} suspendidos</span>` : ""}<span>Último servicio: ${csFC(f.ultimo)}</span></div>
  </div>`;
}
function rkPocos() {
  const p = rk.d.pocos_servicios;
  if (!p.length) return "";
  return `<p class="rk-pocos"><i class="ti ti-user-minus"></i> <span><b>Con menos de ${rk.d.min_servicios} servicios</b> (no entran al ranking): ${p.map(f => `<button class="rk-link" onclick="rkServicios('${rkE(f.usuario)}', '${rkE(f.nombre).replace(/'/g, "\\'")}')" title="Ver sus servicios">${rkE(f.nombre)}</button> (${fmtNum(f.servicios)})`).join(", ")}</span></p>`;
}


// ════════════════════════════════════════════════════════════════════════════
// SERVICIOS DE UN CHOFER, DÍA POR DÍA (desde el ranking)
// Todos los días del período, con lo que rindió cada uno. Desde acá la oficina
// agrega un servicio que el chofer no marcó, lo quita, lo pasa a otro chofer o
// le corrige la fecha. Cada cambio queda en la auditoría.
// ════════════════════════════════════════════════════════════════════════════

const rks = { u: "", nombre: "", desde: "", hasta: "", d: null, cfg: null, choferes: null, seq: 0 };
const RKS_EST = { completado: "Completo", entrante: "Entrante", saliente: "Saliente", suspendido: "Suspendido" };
const rksD = f => new Date(f + "T12:00:00");
const rksIso = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const RKS_DIAS = ["dom", "lun", "mar", "mié", "jue", "vie", "sáb"];
const RKS_MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];

async function rksListas() {
  if (!rks.cfg) rks.cfg = await api("/api/corp/config").catch(() => null);
  if (!rks.choferes) rks.choferes = await api("/api/corp/choferes").catch(() => []);
}

async function rksElegir() {
  await rksListas();
  const lista = Array.isArray(rks.choferes) ? rks.choferes : [];
  rvModal({
    titulo: "Servicios de un chofer", icono: "calendar-user", ancho: 440,
    sub: "Elegí el chofer para ver lo que rindió día por día.",
    cuerpo: `<input class="form-input" id="rks-q" placeholder="Buscar chofer…" autocomplete="off" style="margin-bottom:8px" autofocus>
      <select class="form-input" id="rks-sel" size="10" style="height:auto">${lista.map(c => `<option value="${rkE(c.usuario)}">${rkE(c.nombre)}</option>`).join("")}</select>`,
    pie: `<button class="btn btn-ghost" onclick="this.closest('.modal-overlay').remove()">Cancelar</button>
          <button class="btn btn-primary" id="rks-ir"><i class="ti ti-arrow-right"></i> Ver</button>`,
  });
  const sel = $("#rks-sel");
  $("#rks-q").oninput = e => { const q = e.target.value.trim().toLowerCase(); [...sel.options].forEach(o => { o.hidden = q && !o.textContent.toLowerCase().includes(q); }); };
  const ir = () => { if (!sel.value) return; const o = sel.selectedOptions[0]; sel.closest(".modal-overlay").remove(); rkServicios(sel.value, o.textContent); };
  $("#rks-ir").onclick = ir; sel.ondblclick = ir;
}

async function rkServicios(u, nombre) {
  Object.assign(rks, { u: u.toLowerCase(), nombre, desde: rk.desde, hasta: rk.hasta > trHoy() ? trHoy() : rk.hasta, d: null });
  rvModal({
    titulo: rkE(nombre), icono: "calendar-user", ancho: 860, clase: "rks-modal",
    sub: "Sus servicios día por día" + (puedeOperarCorp() ? ". Podés agregar lo que no marcó, quitar lo que está de más, pasarlo a otro chofer o corregirle la fecha." : "."),
    cuerpo: `<div id="rks"><div class="dossier-loading"><div class="dossier-spinner"></div></div></div>`,
    pie: `<button class="btn btn-ghost" onclick="this.closest('.modal-overlay').remove()">Cerrar</button>`,
  });
  rksListas();
  rksCargar();
}

async function rksCargar() {
  const seq = ++rks.seq;
  const d = await api(`/api/corp/rendiciones?chofer=${encodeURIComponent(rks.u)}&desde=${rks.desde}&hasta=${rks.hasta}`).catch(() => null);
  if (seq !== rks.seq || !$("#rks")) return;
  rks.d = d;
  rksPintar();
}

function rksFechas() {
  const a = $("#rks-desde").value, b = $("#rks-hasta").value;
  if (!a || !b) return;
  [rks.desde, rks.hasta] = a <= b ? [a, b] : [b, a];
  if ((rksD(rks.hasta) - rksD(rks.desde)) / 864e5 > 92) rks.desde = rksIso(new Date(rksD(rks.hasta).getTime() - 92 * 864e5));
  rksCargar();
}

function rksPintar() {
  const box = $("#rks");
  if (!box) return;
  const d = rks.d;
  if (!d || d.error) { box.innerHTML = `<div class="empty"><i class="ti ti-alert-circle"></i>${rkE((d && d.error) || "No se pudieron traer los servicios")}</div>`; return; }
  const puede = puedeOperarCorp();
  const por = {};
  d.rendiciones.forEach(r => (por[r.fecha_servicio] = por[r.fecha_servicio] || []).push(r));
  const hechos = d.rendiciones.filter(r => r.estado !== "suspendido");
  const dias = [];
  for (let f = rks.hasta; f >= rks.desde && dias.length < 93; f = rksIso(new Date(rksD(f).getTime() - 864e5))) dias.push(f);
  const monto = d.rendiciones.reduce((s, r) => s + (+r.monto || 0), 0);
  box.innerHTML = `
    <div class="rks-barra">
      <label class="cs-fechas on"><i class="ti ti-calendar"></i>
        <input type="date" id="rks-desde" value="${rks.desde}" max="${trHoy()}" onchange="rksFechas()" aria-label="Desde"><span>al</span>
        <input type="date" id="rks-hasta" value="${rks.hasta}" max="${trHoy()}" onchange="rksFechas()" aria-label="Hasta"></label>
      <span class="rks-tot"><b>${d.rendiciones.length}</b> ${d.rendiciones.length === 1 ? "servicio" : "servicios"} · <b>${new Set(hechos.map(r => r.fecha_servicio)).size}</b> días trabajados · Gs. ${fmtNum(Math.round(monto))}</span>
      <button class="btn btn-pdf btn-sm" onclick="rksRendir(rks.u, rks.nombre, rks.desde, rks.hasta)" title="Elegí de qué fecha a qué fecha y bajá el PDF con lo que hizo"><i class="ti ti-file-type-pdf"></i> Rendir por fechas</button>
      ${puede ? `<button class="btn btn-primary btn-sm" onclick="rksNuevo('${dias[0] || trHoy()}')"><i class="ti ti-plus"></i> Agregar servicio</button>` : ""}
    </div>
    <div id="rks-form"></div>
    <div class="rks-dias">${dias.map(f => {
      const rs = (por[f] || []).sort((a, b) => a.cliente_c.localeCompare(b.cliente_c) || a.tramo_c.localeCompare(b.tramo_c));
      const dd = rksD(f), finde = [0, 6].includes(dd.getDay());
      return `<div class="rks-dia ${rs.length ? "" : "vacio"} ${finde ? "finde" : ""}">
        <div class="rks-fecha"><small>${RKS_DIAS[dd.getDay()]}</small><b>${dd.getDate()}</b><small>${RKS_MESES[dd.getMonth()]}</small></div>
        <div class="rks-servs">${rs.length ? rs.map(r => `
          <div class="rks-s ${r.estado === "suspendido" ? "susp" : ""}">
            <div class="rks-s-que"><span class="sm-cli">${rkE(r.cliente_c)}</span> <b>${rkE(r.tramo_c)}</b>
              <span class="sm-estado e-${rkE(r.estado)}">${RKS_EST[r.estado] || rkE(r.estado)}</span></div>
            <small>${[r.bus_interno && `Coche ${rkE(r.bus_interno)}`, r.cargado && `marcado ${r.cargado.slice(0, 10) !== f ? "el " + csFC(r.cargado.slice(0, 10)) + " " : ""}a las ${r.cargado.slice(11, 16)}`,
                      r.editado_por && (r.editado_por.startsWith("cargado por") ? rkE(r.editado_por) : "corregido por " + rkE(r.editado_por)),
                      r.monto && `Gs. ${fmtNum(Math.round(r.monto))}`, r.observacion && rkE(r.observacion)].filter(Boolean).join(" · ")}</small>
            ${puede ? (r.liquidado ? `<span class="sm-liq" title="Ya está liquidado"><i class="ti ti-lock"></i> Liquidado</span>` : `<span class="rks-acc">
              <button class="sm-borrar rks-ed" title="Cambiar la fecha" onclick="rksFecha(${r.id}, '${f}')"><i class="ti ti-calendar-event"></i></button>
              <button class="sm-borrar rks-ed" title="Pasar a otro chofer" onclick="rksPasar(${r.id})"><i class="ti ti-user-share"></i></button>
              <button class="sm-borrar" title="Quitar este servicio" onclick="rksQuitar(${r.id})"><i class="ti ti-trash"></i></button></span>`) : ""}
          </div>`).join("") : `<span class="rks-nada">Sin servicios</span>`}</div>
        ${puede ? `<button class="rks-mas" onclick="rksNuevo('${f}')" title="Agregar un servicio el ${dd.getDate()}/${dd.getMonth() + 1}" aria-label="Agregar un servicio este día"><i class="ti ti-plus"></i></button>` : ""}
      </div>`;
    }).join("")}</div>`;
}

// PDF con lo que hizo el chofer en el período: el total a pagarle, cómo se
// compone, cada servicio y lugar para firmar (el de Rendiciones y pagos)
function rksPdf(u, desde, hasta, pend) {
  const q = new URLSearchParams({ chofer: u, desde, hasta, ...(pend ? { pendientes: "1" } : {}) });
  window.open(`/api/corp/rendiciones_pdf?${q}`, "_blank");
}

// Rendir por fechas: se elige de tal a tal fecha (con atajos de semana,
// quincena y mes), se ve cuántos servicios y cuánto da, y se baja el PDF.
const rr = { u: "", nombre: "", desde: "", hasta: "", pend: false, seq: 0 };
function rrRangos() {
  const hoy = trHoy(), d = rksD(hoy), y = d.getFullYear(), m = d.getMonth();
  const iso = x => rksIso(x), dow = (d.getDay() + 6) % 7;
  const lunes = new Date(d.getTime() - dow * 864e5);
  const finMes = (yy, mm) => new Date(yy, mm + 1, 0);
  const q1 = d.getDate() <= 15;
  const qAct = q1 ? [new Date(y, m, 1), new Date(y, m, 15)] : [new Date(y, m, 16), finMes(y, m)];
  const qAnt = q1 ? [new Date(y, m - 1, 16), finMes(y, m - 1)] : [new Date(y, m, 1), new Date(y, m, 15)];
  const tope = x => (iso(x) > hoy ? hoy : iso(x));
  return [
    ["Esta semana", iso(lunes), hoy],
    ["Semana pasada", iso(new Date(lunes.getTime() - 7 * 864e5)), iso(new Date(lunes.getTime() - 864e5))],
    ["Esta quincena", iso(qAct[0]), tope(qAct[1])],
    ["Quincena anterior", iso(qAnt[0]), iso(qAnt[1])],
    ["Este mes", iso(new Date(y, m, 1)), hoy],
    ["Mes pasado", iso(new Date(y, m - 1, 1)), iso(finMes(y, m - 1))],
  ];
}
function rksRendir(u, nombre, desde, hasta) {
  Object.assign(rr, { u: u.toLowerCase(), nombre, desde, hasta: hasta > trHoy() ? trHoy() : hasta });
  rvModal({
    titulo: `Rendir a ${rkE(nombre)}`, icono: "file-type-pdf", ancho: 560, clase: "rr-modal",
    sub: "Elegí de qué fecha a qué fecha. El PDF trae cada servicio, el total a pagar y lugar para firmar.",
    cuerpo: `<div class="rr-atajos" id="rr-atajos"></div>
      <div class="rr-fechas">
        <label class="rv-f"><span>Desde</span><input type="date" id="rr-desde" value="${rr.desde}" max="${trHoy()}" onchange="rrFechas()"></label>
        <label class="rv-f"><span>Hasta</span><input type="date" id="rr-hasta" value="${rr.hasta}" max="${trHoy()}" onchange="rrFechas()"></label>
      </div>
      <label class="rks-pend rr-pend"><input type="checkbox" id="rr-pend" ${rr.pend ? "checked" : ""} onchange="rr.pend=this.checked;rrVer()"> Solo lo que todavía no se le pagó</label>
      <div id="rr-ver" class="rr-ver"></div>`,
    pie: `<button class="btn btn-ghost" onclick="this.closest('.modal-overlay').remove()">Cancelar</button>
          <button class="btn btn-pdf" id="rr-pdf" onclick="rksPdf(rr.u, rr.desde, rr.hasta, rr.pend)"><i class="ti ti-download"></i> Descargar PDF</button>`,
  });
  rrAtajos(); rrVer();
}
function rrAtajos() {
  const box = $("#rr-atajos");
  if (box) box.innerHTML = rrRangos().map(([t, a, b]) =>
    `<button class="chip ${rr.desde === a && rr.hasta === b ? "activo" : ""}" onclick="rrPoner('${a}','${b}')">${t}</button>`).join("");
}
function rrPoner(a, b) { rr.desde = a; rr.hasta = b; $("#rr-desde").value = a; $("#rr-hasta").value = b; rrAtajos(); rrVer(); }
function rrFechas() {
  const a = $("#rr-desde").value, b = $("#rr-hasta").value;
  if (!a || !b) return;
  [rr.desde, rr.hasta] = a <= b ? [a, b] : [b, a];
  $("#rr-desde").value = rr.desde; $("#rr-hasta").value = rr.hasta;
  rrAtajos(); rrVer();
}
async function rrVer() {
  const box = $("#rr-ver"), n = ++rr.seq;
  if (!box) return;
  box.innerHTML = `<div class="rr-cargando">Calculando…</div>`;
  const q = new URLSearchParams({ chofer: rr.u, desde: rr.desde, hasta: rr.hasta, ...(rr.pend ? { pendientes: "1" } : {}) });
  const d = await api(`/api/corp/rendiciones?${q}`).catch(() => null);
  if (n !== rr.seq || !$("#rr-ver")) return;
  const btn = $("#rr-pdf");
  if (!d || d.error) { box.innerHTML = `<div class="rks-aviso mal">No se pudo calcular</div>`; return; }
  const rs = d.rendiciones || [], l = (d.liquidacion || [])[0] || {};
  if (btn) btn.disabled = !rs.length;
  if (!rs.length) { box.innerHTML = `<div class="rks-aviso"><i class="ti ti-calendar-off"></i><span>No tiene servicios ${rr.pend ? "sin pagar " : ""}del ${csFC(rr.desde)} al ${csFC(rr.hasta)}.</span></div>`; return; }
  const dias = new Set(rs.filter(r => r.estado !== "suspendido").map(r => r.fecha_servicio)).size;
  const liq = rs.filter(r => r.liquidado).length;
  box.innerHTML = `<div class="rr-res">
      <div><b>${rs.length}</b><span>servicios</span></div>
      <div><b>${dias}</b><span>días trabajados</span></div>
      <div><b>${l.completados || 0}</b><span>completos</span></div>
      <div><b>${l.medios || 0}</b><span>medias</span></div>
      <div class="rr-total"><b>Gs. ${fmtNum(Math.round(l.total || 0))}</b><span>total${l.tiene_plus ? " con plus" : ""}</span></div>
    </div>
    ${liq ? `<p class="rr-nota"><i class="ti ti-info-circle"></i> ${liq} de estos ya ${liq === 1 ? "está liquidado" : "están liquidados"}. Marcá «Solo lo que todavía no se le pagó» si querés dejarlos afuera.</p>` : ""}`;
}

// ── Agregar ──
function rksNuevo(fecha) {
  const box = $("#rks-form");
  if (!box) return;
  const clis = Object.keys((rks.cfg && rks.cfg.clientes_tramos) || {});
  box.innerHTML = `<div class="rks-nuevo">
    <div class="rks-nuevo-tit"><i class="ti ti-plus"></i> Agregar un servicio a ${rkE(rks.nombre)}</div>
    <div class="rks-grid">
      <label class="rv-f"><span>Fecha</span><input type="date" id="rksn-fecha" value="${fecha}" max="${trHoy()}" onchange="rksDisp()"></label>
      <label class="rv-f"><span>Empresa</span><select id="rksn-cli" onchange="rksTramos()"><option value="">Elegí…</option>${clis.map(c => `<option>${rkE(c)}</option>`).join("")}</select></label>
      <label class="rv-f rks-ancho"><span>Tramo</span><select id="rksn-tramo" onchange="rksDisp()"><option value="">Primero la empresa</option></select></label>
      <label class="rv-f"><span>¿Qué hizo?</span><select id="rksn-estado" onchange="rksDisp()">
        <option value="completado">Completo (entrante y saliente)</option><option value="entrante">Solo el entrante</option>
        <option value="saliente">Solo el saliente</option><option value="suspendido">Suspendido</option></select></label>
      <label class="rv-f"><span>Coche</span><input id="rksn-bus" inputmode="numeric" placeholder="N° interno"></label>
      <label class="rv-f"><span>Km inicial</span><input id="rksn-kmi" inputmode="numeric" placeholder="0"></label>
      <label class="rv-f"><span>Km final</span><input id="rksn-kmf" inputmode="numeric" placeholder="0"></label>
      <label class="rv-f"><span>Pasajeros</span><input id="rksn-pas" inputmode="numeric" placeholder="0"></label>
      <label class="rv-f rks-ancho"><span>Observación <small>(obligatoria si fue suspendido o es variable)</small></span><input id="rksn-obs" placeholder="Por ejemplo: no lo marcó, lo confirmó el supervisor"></label>
    </div>
    <div id="rksn-aviso"></div>
    <div class="rks-nuevo-pie"><button class="btn btn-ghost btn-sm" onclick="$('#rks-form').innerHTML=''">Cancelar</button>
      <button class="btn btn-primary btn-sm" id="rksn-ok" onclick="rksGuardar(this)"><i class="ti ti-check"></i> Agregar</button></div>
  </div>`;
  box.scrollIntoView({ behavior: "smooth", block: "nearest" });
  $("#rksn-cli").focus();
}
function rksTramos() {
  const c = $("#rksn-cli").value, t = $("#rksn-tramo");
  const lista = (rks.cfg && rks.cfg.clientes_tramos && rks.cfg.clientes_tramos[c]) || [];
  t.innerHTML = `<option value="">Elegí el tramo…</option>` + lista.map(x => `<option>${rkE(x)}</option>`).join("");
  rksDisp();
}
let rksDispSeq = 0;
async function rksDisp() {
  const av = $("#rksn-aviso");
  if (!av) return;
  const cli = $("#rksn-cli").value, tr = $("#rksn-tramo").value, f = $("#rksn-fecha").value, est = $("#rksn-estado").value;
  if (!cli || !tr || !f || est === "suspendido") { av.innerHTML = ""; return; }
  const n = ++rksDispSeq;
  const d = await api(`/api/corp/disponibilidad?cliente=${encodeURIComponent(cli)}&tramo=${encodeURIComponent(tr)}&fecha=${f}`).catch(() => null);
  if (n !== rksDispSeq || !d || !Array.isArray(d.tomados)) return;
  const choca = d.tomados.filter(t => t.estado === "completado" || est === "completado" || t.estado === est);
  av.innerHTML = choca.length
    ? `<div class="rks-aviso mal"><i class="ti ti-lock"></i><span>Ese día ese tramo ya lo marcó ${choca.map(t => `<b>${rkE(t.chofer_nombre)}</b> (${t.estado === "completado" ? "completo" : t.estado})`).join(" y ")}. Si lo hizo ${rkE(rks.nombre)}, usá <b>Pasar a otro chofer</b> en ese servicio en vez de agregar uno nuevo.</span></div>`
    : d.tomados.length ? `<div class="rks-aviso"><i class="ti ti-users"></i><span>La otra mitad la marcó ${d.tomados.map(t => `<b>${rkE(t.chofer_nombre)}</b> (${t.estado})`).join(", ")}.</span></div>`
    : `<div class="rks-aviso bien"><i class="ti ti-circle-check"></i><span>Ese tramo está libre ese día.</span></div>`;
}
async function rksGuardar(btn) {
  const v = id => ($("#" + id).value || "").trim();
  const datos = { chofer_usuario: rks.u, fecha_servicio: v("rksn-fecha"), cliente: v("rksn-cli"), tramo: v("rksn-tramo"), estado: v("rksn-estado"),
                  bus_interno: v("rksn-bus"), km_inicial: v("rksn-kmi"), km_final: v("rksn-kmf"), pasajeros: v("rksn-pas"), observacion: v("rksn-obs") };
  if (!datos.cliente || !datos.tramo) { toast("Elegí la empresa y el tramo", "error"); return; }
  if (!datos.bus_interno) { toast("Poné el coche", "error"); return; }
  btn.disabled = true;
  const r = await api("/api/corp/rendicion_para", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(datos) })
    .catch(e => ({ ok: false, msg: e.message }));
  btn.disabled = false;
  toast((r && r.msg) || "No se pudo", r && r.ok ? "success" : "error");
  if (r && r.ok) { $("#rks-form").innerHTML = ""; rksCargar(); rkCargar(true); }
}

// ── Quitar, pasar, cambiar fecha ──
async function rksQuitar(id) {
  const r0 = rks.d.rendiciones.find(x => x.id === id);
  if (!r0 || !confirm(`¿Quitar ${r0.cliente_c} ${r0.tramo_c} del ${csFC(r0.fecha_servicio)} a ${rks.nombre}?\n\nEl tramo queda libre para volver a cargarse. Queda en la auditoría.`)) return;
  const r = await api(`/api/corp/rendicion/${id}`, { method: "DELETE" }).catch(e => ({ ok: false, msg: e.message }));
  toast((r && (r.msg || r.error)) || "No se pudo", r && r.ok ? "success" : "error");
  if (r && r.ok) { rksCargar(); rkCargar(true); }
}
async function rksFecha(id, actual) {
  const f = prompt("¿De qué fecha es este servicio? (AAAA-MM-DD)", actual);
  if (!f || f === actual) return;
  const r = await api(`/api/corp/rendicion/${id}/mover`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ fecha: f.trim() }) })
    .catch(e => ({ ok: false, error: e.message }));
  toast((r && (r.msg || r.error)) || "No se pudo", r && r.ok ? "success" : "error");
  if (r && r.ok) { if (f < rks.desde) rks.desde = f; rksCargar(); rkCargar(true); }
}
async function rksPasar(id) {
  await rksListas();
  const r0 = rks.d.rendiciones.find(x => x.id === id);
  const lista = (rks.choferes || []).filter(c => c.usuario.toLowerCase() !== rks.u);
  const caja = $("#rks-form");
  caja.innerHTML = `<div class="rks-nuevo">
    <div class="rks-nuevo-tit"><i class="ti ti-user-share"></i> Pasar ${rkE(r0.cliente_c)} ${rkE(r0.tramo_c)} del ${csFC(r0.fecha_servicio)} a otro chofer</div>
    <input class="form-input" id="rksp-q" placeholder="Buscar chofer…" autocomplete="off" style="margin-bottom:8px">
    <select class="form-input" id="rksp-a" size="7" style="height:auto">${lista.map(c => `<option value="${rkE(c.usuario)}">${rkE(c.nombre)}</option>`).join("")}</select>
    <div class="rks-nuevo-pie"><button class="btn btn-ghost btn-sm" onclick="$('#rks-form').innerHTML=''">Cancelar</button>
      <button class="btn btn-primary btn-sm" id="rksp-ok"><i class="ti ti-user-share"></i> Pasar</button></div></div>`;
  caja.scrollIntoView({ behavior: "smooth", block: "nearest" });
  const sel = $("#rksp-a");
  $("#rksp-q").oninput = e => { const q = e.target.value.trim().toLowerCase(); [...sel.options].forEach(o => { o.hidden = q && !o.textContent.toLowerCase().includes(q); }); };
  $("#rksp-q").focus();
  $("#rksp-ok").onclick = async e => {
    if (!sel.value) { toast("Elegí el chofer", "error"); return; }
    e.target.disabled = true;
    const r = await api(`/api/corp/marcados/${id}/chofer`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ usuario: sel.value }) })
      .catch(err => ({ error: err.message }));
    toast((r && (r.msg || r.error)) || "No se pudo", r && r.ok ? "success" : "error");
    if (r && r.ok) { caja.innerHTML = ""; rksCargar(); rkCargar(true); } else e.target.disabled = false;
  };
}
