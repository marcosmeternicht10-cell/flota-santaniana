// ════════════════════════════════════════════════════════════════════════════
// SERVICIOS MARCADOS (Corporativos → Servicios marcados)
//
// Todos los servicios de un día con quién marcó cada uno, quién marcó más, y
// el botón para eliminar lo que esté de más. Los datos salen de
// corp_marcados.py; el borrado usa las rutas de siempre de corporativos.
// ════════════════════════════════════════════════════════════════════════════

const sm = { fecha: "", d: null, chofer: "", cliente: "", q: "", soloAvisos: false, sel: new Set(), confirmar: 0, verAviso: 0, seq: 0 };
const smE = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const SM_DIAS = ["dom", "lun", "mar", "mié", "jue", "vie", "sáb"];
const SM_MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];
const smD = f => new Date(f + "T12:00:00");
function smFechaLarga(f) {
  const d = smD(f), hoy = sm.d ? sm.d.hoy : trIso(new Date());
  const dif = Math.round((smD(hoy) - d) / 864e5);
  const pre = dif === 0 ? "Hoy, " : dif === 1 ? "Ayer, " : "";
  return `${pre}${["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"][d.getDay()]} ${d.getDate()} de ${SM_MESES[d.getMonth()]}`;
}
const smIniciales = n => n.replace(/,/g, "").split(/\s+/).filter(Boolean).slice(0, 2).map(x => x[0]).join("").toUpperCase();

async function renderCorpMarcados() {
  status("Servicios marcados por los choferes");
  if (!sm.fecha) sm.fecha = trIso(new Date());
  content.innerHTML = `
    <div class="page-header">
      <h1><i class="ti ti-checklist"></i> Servicios marcados</h1>
      <p>Todo lo que marcaron los choferes en el día, quién marcó cada servicio y quién marcó más</p>
    </div>
    <div class="section sm-raiz">
      <div class="sm-nav" id="sm-nav"></div>
      <div id="sm-cuerpo"><div class="dossier-loading"><div class="dossier-spinner"></div></div></div>
    </div>`;
  smCargar();
}

async function smCargar(mantener) {
  const seq = ++sm.seq;
  if (!mantener) { sm.chofer = ""; sm.cliente = ""; sm.soloAvisos = false; sm.sel.clear(); sm.confirmar = 0; }
  $("#sm-cuerpo")?.classList.add("cargando");
  const d = await api(`/api/corp/marcados?fecha=${sm.fecha}`).catch(() => null);
  if (seq !== sm.seq || !$("#sm-cuerpo")) return;
  $("#sm-cuerpo").classList.remove("cargando");
  if (!d || d.error) { $("#sm-cuerpo").innerHTML = `<div class="empty"><i class="ti ti-alert-circle"></i>${smE((d && d.error) || "No se pudieron traer los servicios")}</div>`; return; }
  sm.d = d;
  // Si el filtro quedó apuntando a alguien que ya no tiene servicios, se limpia
  if (sm.chofer && !d.choferes.some(c => c.usuario === sm.chofer)) sm.chofer = "";
  [...sm.sel].forEach(id => { if (!d.servicios.some(s => s.id === id)) sm.sel.delete(id); });
  smNav(); smPintar();
}

function smDia(n) { const d = smD(sm.fecha); d.setDate(d.getDate() + n); smIr(trIso(d)); }
function smIr(f) { if (!f || (sm.d && f > sm.d.hoy)) return; sm.fecha = f; smCargar(); }

function smNav() {
  const d = sm.d, nav = $("#sm-nav");
  if (!nav) return;
  const max = Math.max(1, ...d.semana.map(x => x.n));
  nav.innerHTML = `
    <div class="sm-dia">
      <button class="sm-flecha" onclick="smDia(-1)" aria-label="Día anterior"><i class="ti ti-chevron-left"></i></button>
      <label class="sm-fecha"><b>${smFechaLarga(d.fecha)}</b>
        <input type="date" value="${d.fecha}" max="${d.hoy}" onchange="smIr(this.value)" aria-label="Elegir el día"></label>
      <button class="sm-flecha" onclick="smDia(1)" ${d.fecha >= d.hoy ? "disabled" : ""} aria-label="Día siguiente"><i class="ti ti-chevron-right"></i></button>
      ${d.fecha !== d.hoy ? `<button class="btn btn-ghost btn-sm" onclick="smIr('${d.hoy}')">Hoy</button>` : ""}
    </div>
    <div class="sm-semana" role="group" aria-label="Los últimos 7 días">
      ${d.semana.map(x => `<button class="sm-sem ${x.fecha === d.fecha ? "on" : ""}" onclick="smIr('${x.fecha}')" title="${x.n} servicios">
        <span class="sm-sem-barra"><i style="height:${Math.round(100 * x.n / max)}%"></i></span>
        <b>${x.n}</b><small>${SM_DIAS[smD(x.fecha).getDay()]} ${smD(x.fecha).getDate()}</small></button>`).join("")}
    </div>`;
}

function smFiltrados() {
  const q = sm.q.trim().toLowerCase();
  return sm.d.servicios.filter(s =>
    (!sm.chofer || s.usuario === sm.chofer) && (!sm.cliente || s.cliente === sm.cliente) && (!sm.soloAvisos || s.aviso) &&
    (!q || `${s.chofer} ${s.cliente} ${s.tramo} ${s.coche}`.toLowerCase().includes(q)));
}

function smPintar() {
  const d = sm.d, box = $("#sm-cuerpo");
  if (!box) return;
  if (!d.total) {
    box.innerHTML = `<div class="sm-vacio"><i class="ti ti-calendar-off"></i><b>Nadie marcó servicios este día</b><span>${d.fecha === d.hoy ? "Cuando los choferes carguen, aparecen acá." : "Probá con otro día de la semana, arriba."}</span></div>`;
    return;
  }
  const top = d.choferes[0], max = top.servicios;
  const empate = d.choferes.filter(c => c.servicios === max);
  box.innerHTML = `
    <div class="sm-arriba">
      <section class="sm-top">
        <span class="sm-top-et"><i class="ti ti-crown"></i> ${empate.length > 1 ? "Los que más marcaron" : "El que más marcó"}</span>
        <div class="sm-top-quien">
          <span class="sm-avatar grande">${smIniciales(top.chofer)}</span>
          <div><b>${smE(empate.length > 1 ? empate.slice(0, 3).map(c => c.chofer).join(" · ") + (empate.length > 3 ? ` y ${empate.length - 3} más` : "") : top.chofer)}</b>
            <span>${empate.length > 1 ? "empatados" : smE(top.clientes.join(", "))}${empate.length === 1 && top.primera ? (top.primera === top.ultima ? ` · cargó a las ${top.primera}` : ` · cargó de ${top.primera} a ${top.ultima}`) : ""}</span></div>
        </div>
        <div class="sm-top-num"><b>${max}</b><span>${max === 1 ? "servicio" : "servicios"}<br>${max > d.promedio ? `el promedio del día es ${String(d.promedio).replace(".", ",")}` : "igual que el resto"}</span></div>
        ${empate.length === 1 ? `<button class="sm-top-ver" onclick="smChofer('${smE(top.usuario)}')">Ver sus servicios <i class="ti ti-arrow-right"></i></button>` : ""}
      </section>
      <section class="sm-cifras">
        <div><b>${d.total}</b><span>servicios marcados</span></div>
        <div><b>${d.choferes.length}</b><span>${d.choferes.length === 1 ? "chofer" : "choferes"}</span></div>
        <div class="${d.con_aviso ? "mal" : ""}"><b>${d.con_aviso}</b><span>para revisar</span>
          ${d.con_aviso ? `<button class="sm-link" onclick="smAvisos()">${sm.soloAvisos ? "Ver todos" : "Ver cuáles"}</button>` : ""}</div>
        <div><b>${d.suspendidos}</b><span>suspendidos</span></div>
      </section>
    </div>
    <div class="sm-cols">
      <aside class="sm-rank">
        <h3><i class="ti ti-chart-bar"></i> Quién marcó cuánto</h3>
        <div class="sm-rank-lista">${d.choferes.map((c, i) => `
          <button class="sm-rk ${sm.chofer === c.usuario ? "on" : ""}" onclick="smChofer('${smE(c.usuario)}')" title="Ver solo los servicios de ${smE(c.chofer)}">
            <span class="sm-rk-pos">${i + 1}</span>
            <span class="sm-rk-nom">${smE(c.chofer)}${c.avisos ? `<i class="ti ti-alert-triangle" title="${c.avisos} para revisar"></i>` : ""}</span>
            <span class="sm-rk-n">${c.servicios}</span>
            <span class="sm-rk-barra"><i style="width:${Math.max(6, Math.round(100 * c.servicios / max))}%"></i></span>
          </button>`).join("")}</div>
      </aside>
      <section class="sm-lista-caja">
        <div class="sm-filtros">
          <div class="cs-chips">
            <button class="chip ${!sm.cliente ? "activo" : ""}" onclick="smCliente('')">Todas <span class="chip-nota">${d.total}</span></button>
            ${d.clientes.map(([c, n]) => `<button class="chip ${sm.cliente === c ? "activo" : ""}" onclick="smCliente('${smE(c)}')">${smE(c)} <span class="chip-nota">${n}</span></button>`).join("")}
          </div>
          <label class="cs-busca"><i class="ti ti-search"></i><input type="search" id="sm-q" value="${smE(sm.q)}" placeholder="Buscar chofer, tramo o coche" oninput="sm.q=this.value;smLista()"></label>
        </div>
        <div id="sm-lista"></div>
      </section>
    </div>`;
  smLista();
}

function smLista() {
  const box = $("#sm-lista");
  if (!box) return;
  const d = sm.d, filas = smFiltrados(), puede = d.puede_borrar;
  const quien = sm.chofer ? d.choferes.find(c => c.usuario === sm.chofer) : null;
  const borrables = filas.filter(s => !s.liquidado);
  const nSel = borrables.filter(s => sm.sel.has(s.id)).length;
  const activo = [quien && `de <b>${smE(quien.chofer)}</b>`, sm.soloAvisos && "<b>para revisar</b>"].filter(Boolean);
  box.innerHTML = `
    <div class="sm-barra">
      <span>${filas.length} ${filas.length === 1 ? "servicio" : "servicios"}${activo.length ? " " + activo.join(", ") : ""}
        ${activo.length ? `<button class="sm-link" onclick="smQuitarFiltros()">Quitar filtro</button>` : ""}</span>
      ${puede && borrables.length ? `<span class="sm-barra-der">
        ${nSel ? `<button class="btn btn-danger btn-sm" onclick="smEliminarSel()"><i class="ti ti-trash"></i> Eliminar ${nSel} ${nSel === 1 ? "elegido" : "elegidos"}</button>` : ""}
        <button class="sm-link" onclick="smElegirTodos(${nSel === borrables.length ? "false" : "true"})">${nSel === borrables.length ? "No elegir ninguno" : "Elegir todos"}</button></span>` : ""}
    </div>
    ${filas.length ? `<div class="sm-filas">${filas.map(s => `
      <div class="sm-fila ${s.aviso ? "con-aviso" : ""} ${s.estado === "suspendido" ? "susp" : ""} ${sm.sel.has(s.id) ? "elegida" : ""}">
        ${puede ? `<input type="checkbox" class="sm-chk" ${sm.sel.has(s.id) ? "checked" : ""} ${s.liquidado ? "disabled" : ""} onchange="smElegir(${s.id}, this.checked)" aria-label="Elegir este servicio">` : ""}
        <span class="sm-avatar">${smIniciales(s.chofer)}</span>
        <div class="sm-fila-quien"><b>${smE(s.chofer)}</b>
          <small>${s.cargado_el ? `Marcado ${s.otro_dia ? "el " + csFC(s.cargado_el.slice(0, 10)) + " " : ""}a las ${s.cargado_el.slice(11)}` : "Sin hora de carga"}${s.editado_por ? ` · ${s.editado_por.startsWith("cargado por") ? "" : "corregido por "}${smE(s.editado_por)}` : ""}</small></div>
        <div class="sm-fila-que"><b><span class="sm-cli">${smE(s.cliente)}</span> ${smE(s.tramo)}</b>
          <small>${[s.coche && `Coche ${smE(s.coche)}`, s.pasajeros && `${s.pasajeros} pasajeros`, s.km && `${fmtNum(s.km)} km`, s.observacion && smE(s.observacion)].filter(Boolean).join(" · ") || "Sin más datos"}</small>
          ${s.aviso ? `<button class="sm-aviso" onclick="smVerAviso(${s.id})" aria-expanded="${sm.verAviso === s.id}" title="Ver con qué servicio choca"><i class="ti ti-alert-triangle"></i> ${smE(s.aviso)} <i class="ti ti-chevron-${sm.verAviso === s.id ? "up" : "down"}"></i></button>` : ""}</div>
        <span class="sm-estado e-${s.estado}">${smE(s.estado_txt)}</span>
        ${puede ? (s.liquidado
          ? `<span class="sm-liq" title="Ya está liquidado: para borrarlo hay que revertir la liquidación"><i class="ti ti-lock"></i> Liquidado</span>`
          : sm.confirmar === s.id
            ? `<span class="sm-conf"><button class="btn btn-danger btn-sm" onclick="smEliminar(${s.id})">Sí, eliminar</button><button class="btn btn-ghost btn-sm" onclick="smConfirmar(0)">No</button></span>`
            : `<span class="sm-acc"><button class="sm-borrar" onclick="smPasar(${s.id})" title="Pasar a otro chofer (lo marcó uno y lo hizo otro)" aria-label="Pasar a otro chofer"><i class="ti ti-user-share"></i></button><button class="sm-borrar" onclick="smConfirmar(${s.id})" title="Eliminar este servicio" aria-label="Eliminar este servicio"><i class="ti ti-trash"></i></button></span>`) : ""}
      </div>${sm.verAviso === s.id ? smChoque(s, puede) : ""}`).join("")}</div>` : `<div class="empty chico">Ningún servicio con ese filtro</div>`}`;
}

// Al tocar el aviso de un servicio: con qué otro servicio choca, los dos lado
// a lado con su horario, para decidir cuál está de más y borrarlo ahí mismo.
function smVerAviso(id) { sm.verAviso = sm.verAviso === id ? 0 : id; sm.confirmar = 0; smLista(); }
function smChoque(s, puede) {
  const otros = s.choca_con.map(id => sm.d.servicios.find(x => x.id === id)).filter(Boolean);
  const tarjeta = (x, cual) => `
    <div class="sm-ch-serv">
      <span class="sm-ch-et">${cual}</span>
      <b><span class="sm-cli">${smE(x.cliente)}</span> ${smE(x.tramo)}</b>
      <span class="sm-ch-hora"><i class="ti ti-clock"></i> ${x.horario ? smE(x.horario[0].toUpperCase() + x.horario.slice(1)) : "Sin horario"}${x.estado !== "completado" && x.estado !== "ok" ? ` · ${smE(x.estado_txt)}` : ""}</span>
      <small>${smE(x.chofer)}${x.coche ? ` · coche ${smE(x.coche)}` : ""}${x.cargado_el ? ` · marcado ${x.otro_dia ? "el " + csFC(x.cargado_el.slice(0, 10)) + " " : ""}a las ${x.cargado_el.slice(11)}` : ""}</small>
      ${puede ? (x.liquidado ? `<span class="sm-liq"><i class="ti ti-lock"></i> Liquidado</span>`
        : sm.confirmar === -x.id
          ? `<span class="sm-conf"><button class="btn btn-danger btn-sm" onclick="smEliminar(${x.id})">Sí, eliminar</button><button class="btn btn-ghost btn-sm" onclick="smConfirmar(0)">No</button></span>`
          : `<button class="btn btn-ghost btn-sm sm-ch-borrar" onclick="smConfirmar(${-x.id})"><i class="ti ti-trash"></i> Eliminar este</button>`) : ""}
    </div>`;
  return `<div class="sm-choque">
    <div class="sm-ch-tit"><i class="ti ti-arrows-diff"></i> ${s.aviso.startsWith("Mismo") ? "Estos servicios son a la misma hora" : "El mismo tramo, marcado por más de un chofer"}</div>
    <div class="sm-ch-grid">${tarjeta(s, "Este servicio")}${otros.map(x => tarjeta(x, "Choca con")).join("") || `<div class="sm-ch-serv"><small>El otro servicio ya no está en la lista.</small></div>`}</div>
  </div>`;
}

function smChofer(u) { sm.chofer = sm.chofer === u ? "" : u; sm.confirmar = 0; smPintar(); }
function smCliente(c) { sm.cliente = c; sm.confirmar = 0; smPintar(); }
function smAvisos() { sm.soloAvisos = !sm.soloAvisos; smPintar(); }
function smQuitarFiltros() { sm.chofer = ""; sm.soloAvisos = false; smPintar(); }
function smElegir(id, si) { si ? sm.sel.add(id) : sm.sel.delete(id); smLista(); }
function smElegirTodos(si) { smFiltrados().filter(s => !s.liquidado).forEach(s => si ? sm.sel.add(s.id) : sm.sel.delete(s.id)); smLista(); }
function smConfirmar(id) { sm.confirmar = id; smLista(); }

async function smEliminar(id) {
  sm.confirmar = 0; sm.verAviso = 0;
  const r = await api(`/api/corp/rendicion/${id}`, { method: "DELETE" }).catch(() => null);
  toast((r && r.msg) || (r && r.error) || "No se pudo eliminar", r && r.ok ? "success" : "error");
  if (r && r.ok) sm.sel.delete(id);
  smCargar(true);
}
async function smEliminarSel() {
  const ids = smFiltrados().filter(s => !s.liquidado && sm.sel.has(s.id)).map(s => s.id);
  if (!ids.length) return;
  rvModal({
    titulo: `Eliminar ${ids.length} ${ids.length === 1 ? "servicio" : "servicios"}`, icono: "trash", ancho: 440,
    sub: "Se borran del sistema y los tramos quedan libres para volver a cargarse. No se puede deshacer.",
    cuerpo: `<ul class="sm-conf-lista">${sm.d.servicios.filter(s => ids.includes(s.id)).slice(0, 8).map(s => `<li><b>${smE(s.chofer)}</b> · ${smE(s.cliente)} ${smE(s.tramo)}</li>`).join("")}${ids.length > 8 ? `<li>y ${ids.length - 8} más</li>` : ""}</ul>`,
    pie: `<button class="btn btn-ghost" onclick="this.closest('.modal-overlay').remove()">Cancelar</button>
          <button class="btn btn-danger" id="sm-conf-si"><i class="ti ti-trash"></i> Eliminar</button>`,
  });
  $("#sm-conf-si").onclick = async e => {
    e.target.disabled = true;
    const r = await api("/api/corp/eliminar_lote", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ids }) }).catch(() => null);
    document.querySelector(".modal-overlay")?.remove();
    toast((r && r.msg) || (r && r.error) || "No se pudo eliminar", r && r.ok ? "success" : "error");
    if (r && r.ok) sm.sel.clear();
    smCargar(true);
  };
}

// Pasar un servicio a otro chofer: cuando lo marcó uno y lo hizo otro, o
// alguien entró con el usuario equivocado.
function smPasar(id) {
  const s = sm.d.servicios.find(x => x.id === id);
  if (!s) return;
  const lista = (sm.d.choferes_corp || []).filter(c => c.usuario.toLowerCase() !== s.usuario);
  rvModal({
    titulo: "Pasar a otro chofer", icono: "user-share", ancho: 460,
    sub: `${smE(s.cliente)} ${smE(s.tramo)} · ${smFechaLarga(sm.d.fecha)}. Hoy figura a nombre de <b>${smE(s.chofer)}</b>.`,
    cuerpo: `<label class="form-label" for="sm-pasar-a">¿Quién hizo el servicio?</label>
      <input class="form-input" id="sm-pasar-q" placeholder="Buscar chofer…" autocomplete="off" style="margin-bottom:8px">
      <select class="form-input" id="sm-pasar-a" size="8" style="height:auto">${lista.map(c => `<option value="${smE(c.usuario)}">${smE(c.nombre)} (${smE(c.usuario)})</option>`).join("")}</select>`,
    pie: `<button class="btn btn-ghost" onclick="this.closest('.modal-overlay').remove()">Cancelar</button>
          <button class="btn btn-primary" id="sm-pasar-si"><i class="ti ti-user-share"></i> Pasar</button>`,
  });
  const sel = $("#sm-pasar-a");
  $("#sm-pasar-q").oninput = e => {
    const q = e.target.value.trim().toLowerCase();
    [...sel.options].forEach(o => { o.hidden = q && !o.textContent.toLowerCase().includes(q); });
  };
  $("#sm-pasar-si").onclick = async e => {
    if (!sel.value) { toast("Elegí el chofer", "error"); return; }
    e.target.disabled = true;
    const r = await api(`/api/corp/marcados/${id}/chofer`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ usuario: sel.value }) }).catch(err => ({ error: err.message }));
    document.querySelector(".modal-overlay")?.remove();
    toast((r && (r.msg || r.error)) || "No se pudo pasar", r && r.ok ? "success" : "error");
    smCargar(true);
  };
}
