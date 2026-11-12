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
      <div class="page-actions"><button class="btn btn-ghost" onclick="rkPdf()"><i class="ti ti-printer"></i> Imprimir</button></div>
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

async function rkCargar() {
  const seq = ++rk.seq, box = $("#rk-cuerpo");
  if (box && rk.d) box.classList.add("cargando");
  const d = await api(`/api/corp/ranking_choferes?${rkQuery()}`).catch(() => null);
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
  return `<p class="rk-pocos"><i class="ti ti-user-minus"></i> <span><b>Con menos de ${rk.d.min_servicios} servicios</b> (no entran al ranking): ${p.map(f => `${rkE(f.nombre)} (${fmtNum(f.servicios)})`).join(", ")}</span></p>`;
}
