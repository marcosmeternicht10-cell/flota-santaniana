// alpha.js — Alpha, la venta de pasajes (se carga después de app.js y usa sus
// utilidades: api, toast, trEsc, fmtNum, content, status).
// ════════════════════════════════════════════════════════════════════════════
// ALPHA (solo admin). Los servicios salen del TRÁFICO de cada día (corredores,
// salidas de ida y regreso, coche asignado y tripulación); si ese día todavía
// no se armó, se toman los horarios del último tráfico del mismo día de la
// semana y el coche queda a confirmar.
//
// La configuración es real y está en la base (/api/alpha/config): los planos
// de asientos, qué plano usa cada coche, los recorridos con sus paradas, las
// tarifas por tramo y los descuentos. Las ventas, reservas y la caja todavía
// son de prueba y quedan en este navegador (falta lo fiscal).
//
// Pantallas: Vender · Pasajes · Manifiesto · Caja · Tarifas · Planos.
// Las AGENCIAS (rol agencia, entran por /boleteria) ven solo Vender, sus
// Pasajes y su Caja: sin tarifario, sin planos, sin manifiesto y sin datos
// internos del tráfico (tripulación, coche, notas). El servidor tampoco se
// los manda. Administración puede mirar Alpha "como agencia" para revisarlo.
// ════════════════════════════════════════════════════════════════════════════

const AL_CLASES = { CO: "Diferencial", CA: "Cama ejecutivo" };
const AL_PAGOS = [["efectivo", "Efectivo"], ["tarjeta", "Tarjeta"], ["transferencia", "Transferencia"]];
const AL_TIPODOC = [["CI", "Cédula paraguaya"], ["PAS", "Pasaporte"], ["DNI", "DNI argentino"], ["OTRO", "Otro documento"]];
const AL_NACION = ["Paraguaya", "Argentina", "Brasileña", "Boliviana", "Uruguaya", "Otra"];
const AL_PAISES = ["Paraguay", "Argentina", "Brasil", "Bolivia", "Uruguay", "Otro"];
const AL_CONOCIDOS = {
  "3456789": { apellidos: "GIMÉNEZ", nombres: "ROSA", sexo: "F", nac: "1990-03-14", nacionalidad: "Paraguaya", residencia: "Paraguay", viajes: 4 },
  "4123987": { apellidos: "ORTIZ", nombres: "DERLIS", sexo: "M", nac: "1985-11-02", nacionalidad: "Paraguaya", residencia: "Argentina", viajes: 2 },
};
const AL_DIAS = ["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"];
const AL_MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "setiembre", "octubre", "noviembre", "diciembre"];
// Precio de ejemplo de punta a punta mientras ese corredor no tenga tarifa cargada
const AL_PRECIOS = {
  COP: { CO: 150000, CA: 180000 }, LOT: { CO: 150000, CA: 180000 },
  PJC: { CO: 170000, CA: 200000 }, "SAN PEDRO": { CO: 90000, CA: 110000 }, ATQ: { CO: 100000, CA: 120000 },
  TACUATI: { CO: 120000, CA: 140000 }, "SAN VICENTE": { CO: 110000, CA: 130000 }, CDE: { CO: 100000, CA: 120000 },
  VILLARRICA: { CO: 60000, CA: 75000 }, CARAPEGUA: { CO: 40000, CA: 50000 },
};
const AL_PRECIO_INTL = { CO: 450000, CA: 550000 };
const AL_PRECIO_OTRO = { CO: 100000, CA: 120000 };
// Duración de Delta para las salidas de Asunción a Concepción (las demás salen de los minutos del recorrido)
const AL_DUR = { "COP|09:00": 485, "COP|11:30": 485, "COP|17:00": 320, "COP|23:00": 321, "LOT|23:15": 355 };
const AL_RESERVA_MIN = 60;            // la reserva vence una hora antes de la salida
const AL_RETENCION = 0.1;             // devolución: se retiene el 10 % (de ejemplo)
const AL_VISTAS = [["vender", "ticket", "Vender"], ["pasajes", "receipt", "Pasajes"], ["manifiesto", "list-details", "Manifiesto"],
                   ["caja", "cash-register", "Caja"], ["tarifas", "currency-dollar", "Tarifas"], ["planos", "armchair", "Planos"]];
const AL_PVACIO = () => ({ tipoDoc: "CI", doc: "", nombre: "", apellidos: "", nombres: "", sexo: "", nac: "", nacionalidad: "", residencia: "" });
const AL_LOGO = `<svg aria-hidden="true" width="40" height="33" viewBox="0 0 120 100"><path d="M98 20C80 40 72 80 42 80C22 80 12 66 12 50C12 34 24 20 42 20C70 20 80 58 99 77" fill="none" stroke="#F3F4F6" stroke-width="13" stroke-linecap="round" stroke-linejoin="round"></path><circle cx="98" cy="20" r="10" fill="#E83040"></circle><circle cx="106" cy="84" r="8" fill="none" stroke="#F3F4F6" stroke-width="5"></circle></svg>`;

function alEsAgencia() { return window.USUARIO_ROL === "agencia" || !!al.comoAgencia; }
function alVistasPermitidas() { return alEsAgencia() ? ["vender", "pasajes", "caja"] : AL_VISTAS.map(v => v[0]); }
const al = {
  comoAgencia: false,
  vista: "vender", cor: "", lado: "ida", dia: 0, dep: 0, sube: 0, baja: -1, sel: null,
  tarifa: "general", pago: "efectivo", recibe: "", aviso: "", p: AL_PVACIO(),
  datos: {}, cargando: false, error: "", cfg: null, cambio: null, cobrarReserva: null,
  buscaHits: [], buscaSel: 0,
  pas: { q: "", estado: "" }, man: { clave: "" }, caja: { fecha: "", vendedor: "" },
  tar: { cor: "", rec: null, pre: null, des: null }, pla: { cod: "", draft: null, nuevo: false, modo: "poner", q: "", cp: null },
};

// ─── Utilidades ───
function alHH(m) { const x = ((m % 1440) + 1440) % 1440; return String(Math.floor(x / 60)).padStart(2, "0") + ":" + String(x % 60).padStart(2, "0"); }
function alDur(m) { return Math.floor(m / 60) + " h" + (m % 60 ? " " + (m % 60) + " min" : ""); }
function alFechaDe(i) { const d = new Date(); d.setHours(12, 0, 0, 0); d.setDate(d.getDate() + i); return d; }
function alISO(d) { return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0"); }
function alDeISO(f) { return new Date(f + "T12:00"); }
function alDiaTxt(d) { return AL_DIAS[d.getDay()][0].toUpperCase() + AL_DIAS[d.getDay()].slice(1) + " " + d.getDate() + " de " + AL_MESES[d.getMonth()]; }
function alDM(f) { return f ? `${f.slice(8, 10)}/${f.slice(5, 7)}` : ""; }
function alMin(h) { const [a, b] = String(h || "0:0").split(":").map(Number); return a * 60 + b; }
function alAhoraISO() { const a = new Date(); return alISO(a) + "T" + String(a.getHours()).padStart(2, "0") + ":" + String(a.getMinutes()).padStart(2, "0"); }
function alNorm(t) { return String(t || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/\s+/g, " ").trim(); }
function alRnd(seed, n) {
  let x = (seed ^ Math.imul(n, 0x9E3779B1)) >>> 0;
  x = (x ^ (x >>> 16)) >>> 0; x = Math.imul(x, 0x45d9f3b) >>> 0; x = (x ^ (x >>> 16)) >>> 0;
  return (x % 10000) / 10000;
}
function alSemilla(...p) { let h = 2166136261; for (const c of p.join("|")) h = Math.imul(h ^ c.charCodeAt(0), 16777619) >>> 0; return h; }
function alVendedor() {
  const n = (document.getElementById("user-name")?.textContent || window.USUARIO_NOMBRE || "").trim();
  if (window.USUARIO_ROL === "agencia") return [window.USUARIO_AGENCIA, n].filter(Boolean).join(" · ") || "Agencia";
  return n || "Administración";
}
function alGs(n) { return "Gs. " + fmtNum(Math.round(n || 0)); }
function alNro(n) { return String(n).padStart(7, "0"); }

// Las ventas de prueba (este navegador)
function alGuardado() {
  try {
    const d = JSON.parse(localStorage.getItem("alpha_maqueta_v3") || "null");
    if (d && Array.isArray(d.ventas)) { d.cierres = d.cierres || []; return d; }
  } catch (e) {}
  return { nro: 124, ventas: [], cierres: [] };
}
function alGuardar(d) { try { localStorage.setItem("alpha_maqueta_v3", JSON.stringify(d)); } catch (e) { toast("No se pudo guardar en este navegador", "error"); } }
function alSalidaISO(v) { return `${v.fecha}T${v.sale || v.hora}`; }
function alReservaViva(v) { return v.estado === "reserva" && alAhoraISO() < (v.vence || alSalidaISO(v)); }
function alOcupa(v) { return v.estado === "vendido" || alReservaViva(v); }

// ─── Configuración (de la base) ───
async function alCfgTraer(forzar) {
  if (al.cfg && !forzar) return al.cfg;
  const d = await api("/api/alpha/config");
  if (d && d.planos) al.cfg = d;
  else if (!al.cfg) al.cfg = { planos: {}, coche_plano: {}, recorridos: {}, tarifas: {}, descuentos: [{ id: "general", nombre: "General", factor: 1 }], coches: [], corredores: [] };
  return al.cfg;
}
async function alCfgGuardar(clave, valor) {
  const r = await api(`/api/alpha/config/${clave}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ valor }) });
  if (!r || !r.ok) { toast((r && (r.msg || r.error)) || "No se pudo guardar", "error"); return false; }
  al.cfg[clave] = JSON.parse(JSON.stringify(valor));
  return true;
}
function alPlanos() { return (al.cfg && al.cfg.planos) || {}; }
function alDescuentos() { const d = (al.cfg && al.cfg.descuentos) || []; return d.length ? d : [{ id: "general", nombre: "General", factor: 1 }]; }
function alPlanoAuto(modelo) {
  const m = String(modelo || "").toLowerCase(), pls = alPlanos();
  const ok = c => pls[c] ? c : Object.keys(pls)[0];
  if (/1800\s*dd|b6x2/.test(m)) return ok("AO01");
  if (/8x2/.test(m)) return ok("AO03");
  if (m) return ok("ACXC");
  return ok("AO01");
}
function alPlanoDe(coche, modelo) {
  const fijo = coche && ((al.cfg && al.cfg.coche_plano) || {})[coche];
  return fijo && alPlanos()[fijo] ? fijo : alPlanoAuto(modelo);
}
async function alCambiarPlano(pl) {
  const sv = alServ(), coche = sv && (sv.coche || sv.habitual);
  if (!coche) return;
  const m = Object.assign({}, al.cfg.coche_plano || {}, { [coche]: pl });
  if (await alCfgGuardar("coche_plano", m)) { toast(`El coche ${coche} queda con el plano ${pl}`, "success"); al.sel = null; alRender(false); }
}

// ─── El tráfico del día ───
async function alTraer(forzar) {
  const f = alISO(alFechaDe(al.dia));
  if (al.datos[f] && !forzar) return;
  al.cargando = true; al.error = "";
  const d = await api(`/api/alpha/dia/${f}`);
  al.cargando = false;
  if (!d || !d.corredores) { al.error = (d && d.error) || "No se pudo traer el tráfico"; al.datos[f] = { corredores: [] }; return; }
  al.datos[f] = d;
  if (!d.corredores.some(c => c.clave === al.cor)) { al.cor = d.corredores[0]?.clave || ""; al.dep = 0; }
}
function alHoyDatos() { return al.datos[alISO(alFechaDe(al.dia))]; }
function alCorredores() { return (alHoyDatos() || {}).corredores || []; }
function alRuta() { const cs = alCorredores(); return cs.find(c => c.clave === al.cor) || cs[0] || null; }
function alFuenteTxt(r) {
  const f = r.fuente || {};
  const dm = x => x ? `${AL_DIAS[alDeISO(x).getDay()]} ${alDM(x)}` : "";
  const qu = r.tipo === "internacional" ? "internacional" : "nacional";
  if (f.estado === "publicado") return `Del tráfico ${qu} publicado (versión ${f.version}).`;
  if (f.estado === "cambios") return `Del tráfico ${qu} (versión ${f.version}, con cambios sin publicar).`;
  if (f.estado === "borrador") return `Del tráfico ${qu}, armado pero sin publicar.`;
  return `El tráfico ${qu} de este día todavía no está armado: horarios del ${dm(f.fecha_ref)}; el coche se confirma cuando se arme.`;
}
function alServiciosDe(r, lado) {
  if (!r) return [];
  return (r[lado] || []).map(x => {
    const coche = x.coche || x.habitual;
    // La agencia no recibe el coche: el plano ya viene resuelto del servidor
    const plano = window.USUARIO_ROL === "agencia" ? (alPlanos()[x.plano] ? x.plano : alPlanoAuto("")) : alPlanoDe(coche, x.coche ? x.modelo : x.habitual_modelo);
    const dur = lado === "ida" && x.origen === "ASU" ? AL_DUR[`${x.llega}|${x.hora}`] : null;
    return Object.assign({}, x, { cor: r.clave, intl: r.tipo === "internacional", lado, h: alMin(x.hora), dur: dur || null, plano,
      cod: [x.tramo, ...(x.extras || [])].join(" ") });
  });
}
function alServicios() { return { lista: alServiciosDe(alRuta(), al.lado) }; }
function alServ(k) { return alServicios().lista[k ?? al.dep]; }
function alPlano(sv) { return alPlanos()[sv.plano] || Object.values(alPlanos())[0]; }
function alAsientos(pl) {
  const out = [];
  if (!pl) return out;
  pl.pisos.forEach((p, pi) => p.filas.forEach((f, fi) => f.forEach((n, pos) => {
    if (n == null) return;
    const lado = pos < 2 ? [f[0], f[1]] : [f[3], f[4]];
    const solo = lado.filter(x => x != null).length === 1;
    out.push({ n, piso: pi, fila: fi, pos, clase: p.clase, solo });
  })));
  return out;
}

// ─── El recorrido: paradas entre el origen y el destino de la salida ───
function alRecorrido(sv) {
  const lista = ((al.cfg && al.cfg.recorridos) || {})[sv.cor] || [];
  if (!lista.length) return null;
  const cod = alNorm(sv.cod + " " + (sv.destino || ""));
  // El que dice lo mismo que la salida («X 25», «X CHACO»). Si la salida dice
  // por dónde va y ningún recorrido coincide, se vende de punta a punta; si no
  // dice nada (los regresos casi nunca lo dicen), va el que no tiene texto o el primero.
  const hit = lista.find(r => r.variante && cod.includes(alNorm(r.variante)));
  if (hit) return hit;
  const libre = lista.find(r => !String(r.variante || "").trim());
  if (libre) return libre;
  return (sv.extras || []).some(x => /^X /.test(x)) ? null : lista[0];
}
function alIgual(a, b) {
  const x = alNorm(a), y = alNorm(b);
  return x && y && (x === y || x.startsWith(y + " ") || y.startsWith(x + " "));
}
function alCamino(sv) {
  // Las paradas de esta salida, en el orden en que las hace
  const rec = alRecorrido(sv);
  const base = [{ nombre: sv.origen_nombre, min: null }, { nombre: sv.llega_nombre, min: null }];
  if (!rec) return base;
  let ps = rec.paradas.map(p => ({ nombre: p.nombre, min: p.min === "" || p.min == null ? null : +p.min }));
  if (sv.lado === "regreso") ps = ps.slice().reverse();
  const o = ps.findIndex(p => alIgual(p.nombre, sv.origen_nombre)), d = ps.findIndex(p => alIgual(p.nombre, sv.llega_nombre));
  if (o < 0 || d < 0 || o >= d) return base;
  return ps.slice(o, d + 1);
}
function alOffset(camino, i) {
  const a = camino[0].min, b = camino[i].min;
  return a == null || b == null ? null : Math.abs(b - a);
}
function alTramoIdx() {
  const sv = alServ(); if (!sv) return [0, 1];
  const n = alCamino(sv).length;
  let s = Math.max(0, Math.min(n - 2, al.sube)), b = al.baja < 0 ? n - 1 : Math.max(s + 1, Math.min(n - 1, al.baja));
  return [s, b];
}
function alIdxDe(camino, nombre, def) { const i = camino.findIndex(p => alIgual(p.nombre, nombre)); return i < 0 ? def : i; }
function alHorasTramo(sv, camino, s, b) {
  const os = alOffset(camino, s), ob = alOffset(camino, b);
  const sale = sv.h + (os || 0);
  const llega = ob != null ? sv.h + ob : (b === camino.length - 1 && sv.dur ? sv.h + sv.dur : null);
  return { sale, llega };
}

// ─── Ocupación (por tramo) y precio ───
function alVentasDe(fecha, sv) { return alGuardado().ventas.filter(v => v.fecha === fecha && v.servicio === sv.clave && alOcupa(v) && v.nro !== al.cambio); }
function alOcupacion(fecha, k, s, b) {
  // asiento → venta, solo las que se pisan con el tramo s..b
  const sv = alServ(k), cam = alCamino(sv), out = new Map();
  if (s == null) { s = 0; b = cam.length - 1; }
  alVentasDe(fecha, sv).forEach(v => {
    const vs = alIdxDe(cam, v.sube, 0), vb = alIdxDe(cam, v.baja, cam.length - 1);
    if (vs < b && s < vb && v.asiento !== "P") out.set(v.asiento, v);
  });
  return out;
}
function alParadosVendidos(fecha, k) { const sv = alServ(k); return alVentasDe(fecha, sv).filter(v => v.asiento === "P").length; }
function alYaSalio(dia, k) {
  if (dia !== 0) return false;
  const a = new Date();
  return alServ(k).h <= a.getHours() * 60 + a.getMinutes();
}
function alDescAsiento(n) {
  if (n == null) return null;
  const sv = alServ(); if (!sv) return null;
  const pl = alPlano(sv);
  if (n === "P") return { piso: "Parado", pos: "Sin asiento asignado", tipo: AL_CLASES.CO, clase: "CO", parado: true, pisoIdx: null };
  const a = alAsientos(pl).find(x => x.n === n);
  if (!a) return null;
  const pos = a.solo ? "Individual" : (a.pos === 0 || a.pos === 4) ? "Ventanilla" : "Pasillo";
  return { piso: pl.pisos.length > 1 ? pl.pisos[a.piso].nombre : "Asiento", pos: pos + ", fila " + (a.fila + 1), tipo: AL_CLASES[a.clase], clase: a.clase, pisoIdx: a.piso };
}
function alParKey(a, b) { return `${a}|${b}`; }
function alPrecioTramo(sv, clase, s, b) {
  // { precio, ejemplo } o null si ese tramo no tiene precio
  const cam = alCamino(sv), tar = ((al.cfg && al.cfg.tarifas) || {})[sv.cor] || {};
  const A = cam[s].nombre, B = cam[b].nombre;
  const busca = (x, y) => Object.entries(tar).find(([k]) => { const [p, q] = k.split("|"); return alIgual(p, x) && alIgual(q, y); });
  const hit = busca(A, B) || busca(B, A);
  if (hit && hit[1] && hit[1][clase] > 0) return { precio: +hit[1][clase], ejemplo: false };
  if (hit && hit[1] && clase === "CA" && hit[1].CO > 0) return { precio: Math.round(hit[1].CO * 1.2 / 1000) * 1000, ejemplo: true };
  if (s === 0 && b === cam.length - 1) {
    const otro = sv.origen === "ASU" ? sv.llega : sv.llega === "ASU" ? sv.origen : sv.llega;
    const t = sv.intl ? AL_PRECIO_INTL : (AL_PRECIOS[otro] || AL_PRECIO_OTRO);
    return { precio: t[clase], ejemplo: true };
  }
  return null;
}
function alPrecio(n) {
  const d = alDescAsiento(n), sv = alServ();
  if (!d || !sv) return 0;
  const [s, b] = alTramoIdx(), pt = alPrecioTramo(sv, d.clase, s, b);
  if (!pt) return 0;
  const f = (alDescuentos().find(t => t.id === al.tarifa) || alDescuentos()[0]).factor;
  return Math.round(pt.precio * f / 1000) * 1000;
}
function alConocido(doc) {
  const dig = String(doc || "").replace(/\D/g, "");
  if (!dig) return null;
  const propias = alGuardado().ventas.filter(v => String(v.doc).replace(/\D/g, "") === dig && v.estado !== "reserva");
  const base = AL_CONOCIDOS[dig];
  if (!base && !propias.length) return null;
  const ult = propias.length ? propias[propias.length - 1] : null;
  const datos = Object.assign({}, base || {}, ult && ult.mig ? ult.mig : {});
  if (!datos.nombres && ult) datos.nombreCompleto = ult.nombre;
  return { datos, viajes: (base ? base.viajes : 0) + propias.length };
}
function alNombreCompleto(p) { return p.nombre || [p.nombres, p.apellidos].filter(Boolean).join(" "); }

// ════════════════════════════════════════════════════════════════════════════
// LA PANTALLA: cabecera con las secciones de Alpha
// ════════════════════════════════════════════════════════════════════════════
async function renderAlpha() {
  if (typeof status === "function") status("Alpha: la venta de pasajes. Servicios del tráfico; tarifas y planos en la base; las ventas de prueba quedan en este navegador");
  if (!["admin", "agencia"].includes(window.USUARIO_ROL)) {
    content.innerHTML = `<div class="page-header"><h1>Alpha</h1><p>Esta sección la ven administración y las agencias.</p></div>`;
    return;
  }
  if (!alVistasPermitidas().includes(al.vista)) al.vista = "vender";
  if (!document.getElementById("al-fuentes")) {
    const l = document.createElement("link");
    l.id = "al-fuentes"; l.rel = "stylesheet";
    l.href = "https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible+Next:wght@400..800&family=Big+Shoulders:opsz,wght@10..72,600..900&display=swap";
    document.head.appendChild(l);
  }
  al.sel = null; al.aviso = "";
  al.cargando = true;
  alRender(true);
  await alCfgTraer();
  await alTraer();
  alRender(true);
}
function alIr(vista) {
  if (vista === al.vista || !alVistasPermitidas().includes(vista)) return;
  al.vista = vista;
  if (vista === "tarifas") { al.tar.rec = al.tar.pre = al.tar.des = null; }
  if (vista === "planos") { al.pla.draft = null; al.pla.cp = null; }
  alRender(true);
}
function alShell(cuerpo, animar, extraCab = "") {
  const g = alGuardado(), hoy = alISO(new Date());
  const caja = alMovs(g).filter(m => m.el.slice(0, 10) === hoy && m.vendedor === alVendedor()).reduce((a, m) => a + m.monto, 0);
  const res = g.ventas.filter(alReservaViva).length;
  return `<div class="al ${animar ? "al-entra" : ""}" id="al-raiz">
    <header class="al-cab">
      <div class="al-marca">${AL_LOGO}<span class="al-d al-marca-t">Alpha</span><span class="al-maqueta">Maqueta</span></div>
      <nav class="al-nav" aria-label="Secciones de Alpha">${AL_VISTAS.filter(([k]) => alVistasPermitidas().includes(k)).map(([k, ic, t], i) => `${k === "tarifas" ? '<span class="al-nav-sep" aria-hidden="true"></span>' : ""}<button type="button" class="al-nav-b ${al.vista === k ? "on" : ""}" aria-current="${al.vista === k ? "page" : "false"}" onclick="alIr('${k}')"><i class="ti ti-${ic}"></i><span>${t}</span>${k === "pasajes" && res ? `<em title="Reservas vigentes">${res}</em>` : ""}</button>`).join("")}</nav>
      ${extraCab}
      <div class="al-caja">
        <div><span>Tu caja de hoy (prueba)</span><b class="al-d">${alGs(caja)}</b></div>
        ${window.USUARIO_ROL === "admin" ? `<button type="button" class="al-sec al-comoag ${al.comoAgencia ? "on" : ""}" onclick="alComoAgencia()" title="Ver Alpha como la ve una agencia">
            <i class="ti ti-${al.comoAgencia ? "shield" : "building-store"}"></i> ${al.comoAgencia ? "Volver a administración" : "Ver como agencia"}</button>` : ""}
        ${window.USUARIO_ROL === "agencia" ? `<div class="al-quien"><span>${trEsc(window.USUARIO_AGENCIA || "Agencia")}</span><b>${trEsc(window.USUARIO_NOMBRE || "")}</b></div>
            <button type="button" class="al-sec" onclick="alSalir()"><i class="ti ti-logout"></i> Salir</button>` : ""}
      </div>
    </header>
    ${al.comoAgencia ? `<div class="al-banner al-banner-ag"><i class="ti ti-eye"></i><span><b>Así lo ve una agencia.</b> Solo vende, ve sus pasajes y su caja: sin tarifario, planos, manifiesto, tripulación ni coche.</span></div>` : ""}
    ${cuerpo}
  </div>`;
}
function alComoAgencia() {
  al.comoAgencia = !al.comoAgencia;
  if (!alVistasPermitidas().includes(al.vista)) al.vista = "vender";
  alRender(true);
}
async function alSalir() {
  await fetch("/api/logout", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
  window.location.href = "/login";
}
function alRender(animar) {
  if (!document.getElementById("al-raiz") && !content) return;
  if (!alVistasPermitidas().includes(al.vista)) al.vista = "vender";
  const v = al.vista;
  if (v === "pasajes") return alVistaPasajes(animar);
  if (v === "manifiesto") return alVistaManifiesto(animar);
  if (v === "caja") return alVistaCaja(animar);
  if (v === "tarifas") return alVistaTarifas(animar);
  if (v === "planos") return alVistaPlanos(animar);
  return alPintar(animar);
}
// Ventanita propia de Alpha (oscura)
function alModal({ titulo, cuerpo, pie, ancho = 520 }) {
  document.getElementById("al-modal")?.remove();
  const o = document.createElement("div");
  o.id = "al-modal"; o.className = "al-modal-fondo";
  o.innerHTML = `<div class="al al-modal" role="dialog" aria-modal="true" aria-label="${trEsc(titulo)}" style="max-width:${ancho}px" tabindex="-1">
    <div class="al-modal-cab"><h2 class="al-d">${trEsc(titulo)}</h2><button type="button" class="al-modal-x" onclick="alModalCerrar()" aria-label="Cerrar"><i class="ti ti-x"></i></button></div>
    <div class="al-modal-cuerpo">${cuerpo}</div>
    <div class="al-modal-pie">${pie}</div></div>`;
  o.addEventListener("mousedown", e => { if (e.target === o) alModalCerrar(); });
  o.addEventListener("keydown", e => { if (e.key === "Escape") { e.stopPropagation(); alModalCerrar(); } });
  document.body.appendChild(o);
  setTimeout(() => (o.querySelector("[autofocus]") || o.querySelector(".al-modal")).focus(), 30);
  return o;
}
function alModalCerrar() { document.getElementById("al-modal")?.remove(); }

// ════════════════════════════════════════════════════════════════════════════
// VENDER
// ════════════════════════════════════════════════════════════════════════════
function alChipsCorredores() {
  const cs = alCorredores(), r = alRuta();
  if (!cs.length) return "";
  return `<div class="al-dias al-corredores" role="group" aria-label="Viaje">${cs.map(c => `<button type="button" class="al-chip ${r && c.clave === r.clave ? "on" : ""}" aria-pressed="${r && c.clave === r.clave}" onclick="alCambiarRuta('${c.clave.replace(/'/g, "\\'")}')">Asunción ⇄ ${trEsc(c.titulo)}${c.tipo === "internacional" ? ' <i class="ti ti-world" aria-label="internacional"></i>' : ""}</button>`).join("")}</div>`;
}
function alChipsDias() {
  const chip = i => {
    const d = alFechaDe(i);
    const t = i === 0 ? "Hoy" : i === 1 ? "Mañana" : AL_DIAS[d.getDay()][0].toUpperCase() + AL_DIAS[d.getDay()].slice(1) + " " + d.getDate();
    return `<button type="button" class="al-chip ${i === al.dia ? "on" : ""}" aria-pressed="${i === al.dia}" onclick="alDia(${i})">${t}</button>`;
  };
  const otro = al.dia > 2;
  return [0, 1, 2].map(chip).join("") + `
    <label class="al-chip al-fecha ${otro ? "on" : ""}" title="Elegir otra fecha"><i class="ti ti-calendar"></i>
      <span>${otro ? alDiaTxt(alFechaDe(al.dia)).replace(/ de \S+$/, "") : "Otra fecha"}</span>
      <input type="date" min="${alISO(alFechaDe(0))}" max="${alISO(alFechaDe(90))}" value="${alISO(alFechaDe(al.dia))}" onchange="alOtraFecha(this.value)" onclick="try{this.showPicker()}catch(e){}" aria-label="Otra fecha de viaje"></label>`;
}
function alOtraFecha(v) {
  if (!v) return;
  const i = Math.round((alDeISO(v) - alFechaDe(0)) / 864e5);
  if (i < 0 || i > 90) { toast("Elegí una fecha desde hoy y hasta 3 meses", "error"); return; }
  alDia(i);
}
function alChipsLado() {
  const r = alRuta();
  if (!r) return "";
  const n = l => (r[l] || []).length;
  return `<div class="al-lados" role="group" aria-label="Sentido">
    <button type="button" class="al-lado ${al.lado === "ida" ? "on" : ""}" aria-pressed="${al.lado === "ida"}" onclick="alLado('ida')">Ida <small>desde Asunción · ${n("ida")}</small></button>
    <button type="button" class="al-lado ${al.lado === "regreso" ? "on" : ""}" aria-pressed="${al.lado === "regreso"}" onclick="alLado('regreso')">Regreso <small>a Asunción · ${n("regreso")}</small></button>
  </div>`;
}
function alVacio(animar, txt) {
  content.innerHTML = alShell(`
    ${al.vista === "vender" ? alBuscador() : ""}
    <div class="al-filtros">${alChipsCorredores()}<div class="al-dias" role="group" aria-label="Día del viaje">${alChipsDias()}</div></div>
    ${alChipsLado()}
    <div class="al-vacio"><i class="ti ti-${al.cargando ? "loader-2" : "calendar-off"}"></i><b>${txt}</b><span>${alDiaTxt(alFechaDe(al.dia))}</span></div>`, animar);
}
function alBannerCambio() {
  if (!al.cambio) return "";
  const v = alGuardado().ventas.find(x => x.nro === al.cambio);
  if (!v) { al.cambio = null; return ""; }
  return `<div class="al-banner"><i class="ti ti-arrows-exchange"></i><span><b>Cambiando el boleto ${alNro(v.nro)}</b> de ${trEsc(v.nombre)}: antes ${alDM(v.fecha)} ${v.sale || v.hora}, ${trEsc(v.origen)} → ${trEsc(v.destino)}, ${v.asiento === "P" ? "parado" : "asiento " + v.asiento}. Elegí el nuevo servicio y asiento.</span>
    <button type="button" class="al-link" onclick="alCambioCancelar()">Cancelar el cambio</button></div>`;
}
function alPintar(animar) {
  if (!al.cfg || al.cargando) return alVacio(animar, "Trayendo el tráfico…");
  const r0 = alRuta();
  if (!r0) return alVacio(animar, al.error || "No hay tráfico armado para tomar los servicios.");
  if (!alServicios().lista.length) return alVacio(animar, `No hay salidas de ${al.lado === "ida" ? "ida" : "regreso"} en este corredor.`);
  const fechaD = alFechaDe(al.dia), fecha = alISO(fechaD), lista = alServicios().lista;
  const lleno = k => { const pl = alPlano(alServ(k)); return alOcupacion(fecha, k).size >= alAsientos(pl).length && alParadosVendidos(fecha, k) >= (pl.parados || 0); };
  const sirve = k => k < lista.length && !alYaSalio(al.dia, k) && !lleno(k);
  if (al.dep >= lista.length) al.dep = 0;
  if (!sirve(al.dep)) { const k = lista.findIndex((_, i) => sirve(i)); if (k >= 0 && k !== al.dep) { al.dep = k; al.sube = 0; al.baja = -1; } }
  const sv = alServ(), pl = alPlano(sv), cam = alCamino(sv), [s, b] = alTramoIdx();
  const ocup = alOcupacion(fecha, al.dep, s, b), todos = alAsientos(pl);
  const paradosQuedan = Math.max(0, (pl.parados || 0) - alParadosVendidos(fecha, al.dep));
  if (al.sel === "P" && !paradosQuedan) al.sel = null;
  if (al.sel != null && al.sel !== "P" && !todos.some(a => a.n === al.sel)) al.sel = null;
  if (al.sel != null && al.sel !== "P" && ocup.has(al.sel) && ocup.get(al.sel).estado === "vendido") al.sel = null;
  if (al.sel == null) { const libre = todos.find(a => !ocup.has(a.n)); al.sel = libre ? libre.n : (paradosQuedan ? "P" : null); }
  const r = alRuta();

  const tabs = lista.map((x, k) => {
    const v = alOcupacion(fecha, k), fue = alYaSalio(al.dia, k);
    const asi = alAsientos(alPlano(x));
    const porClase = ["CO", "CA"].map(c => { const tot = asi.filter(a => a.clase === c); if (!tot.length) return ""; return (tot.length - tot.filter(a => v.has(a.n)).length) + " " + c; }).filter(Boolean);
    const txt = fue ? "Ya salió" : lleno(k) ? "Completo" : porClase.join(", ") + " libres";
    const coche = alEsAgencia() ? "" : x.coche ? `Coche ${x.coche}` : x.habitual ? `A confirmar (suele ir el ${x.habitual})` : "Coche a confirmar";
    return `<button type="button" class="al-tab ${k === al.dep ? "on" : ""}" ${fue || !sirve(k) ? "disabled" : ""} aria-pressed="${k === al.dep}" onclick="alSalida(${k})" aria-label="${alHH(x.h)}, ${trEsc(x.cod)}${coche ? ", " + coche : ""}, ${txt}">
      <span class="al-tab-in"><b class="al-d">${alHH(x.h)}</b><span class="al-tab-t"><span>${trEsc(x.cod)}${x.dur ? `, llega ${alHH(x.h + x.dur)}` : ""}</span>${coche ? `<span class="al-tab-c ${x.coche ? "" : "conf"}">${coche}</span>` : ""}<span class="al-tab-l">${txt}</span></span></span></button>`;
  }).join("");

  const pisos = pl.pisos.map((p, pi) => {
    const nf = p.filas.length, ultimo = pi === pl.pisos.length - 1, cama = p.clase === "CA";
    const usa4 = p.filas.some(f => f[3] != null);
    let celdas = "";
    p.filas.forEach((f, fi) => f.forEach((n, pos) => {
      if (n == null) return;
      const o = ocup.get(n), v = o && o.estado === "vendido", rs = o && o.estado === "reserva", on = !v && n === al.sel;
      celdas += `<button type="button" class="al-as ${cama ? "cama" : nf >= 12 ? "chico" : ""} ${v ? "vendido" : rs ? "reservado" : ""} ${on ? "elegido" : ""}" style="grid-column:${nf - fi};grid-row:${pos + 1}"
        ${v ? "disabled" : ""} aria-pressed="${on}" aria-label="Asiento ${n}${v ? ", vendido" : rs ? ", reservado" : on ? ", elegido" : ", libre"}" onclick="alAsiento(${n})"><i aria-hidden="true"></i>${n}</button>`;
    }));
    if (ultimo) celdas += `<div class="al-cel lleno" style="grid-column:${nf + 1};grid-row:1/3"><i class="ti ti-steering-wheel"></i>Chofer</div>
      <div class="al-cel" style="grid-column:${nf + 1};grid-row:4/6">Puerta</div>`;
    const ancho = cama ? 64 : nf >= 12 ? 40 : 48, alto = cama ? 50 : 42;
    const libres = p.filas.flat().filter(n => n != null && !ocup.has(n)).length;
    const pt = alPrecioTramo(sv, p.clase, s, b);
    return `<div class="al-piso">
      <div class="al-piso-t"><h3 class="al-d">${pl.pisos.length > 1 ? trEsc(p.nombre) : "Asientos"}</h3><span class="al-sub">${AL_CLASES[p.clase]}, ${pt ? alGs(pt.precio) + (pt.ejemplo ? " (de ejemplo)" : "") : "sin precio cargado"}</span><b>${libres} libres</b></div>
      <div class="al-scroll"><div class="al-coche">
        <div class="al-grid" style="grid-template-columns:repeat(${nf}, ${ancho}px)${ultimo ? " 58px" : ""};grid-template-rows:${alto}px ${alto}px 14px ${usa4 ? alto + "px" : "0"} ${alto}px">${celdas}</div>
        <div class="al-parabrisas" aria-hidden="true"></div>
      </div></div>
    </div>`;
  }).join("");
  const parados = pl.parados ? `<button type="button" class="al-parado ${al.sel === "P" ? "on" : ""}" ${paradosQuedan ? "" : "disabled"} aria-pressed="${al.sel === "P"}" onclick="alAsiento('P')">
      <i class="ti ti-man"></i><span>Pasaje parado</span><small>${paradosQuedan ? `quedan ${paradosQuedan} de ${pl.parados}` : "no quedan"}</small></button>` : "";
  const paradas = cam.length > 2 ? `<div class="al-paradas">
      <div class="al-par-f"><span>Sube en</span><div class="al-chips">${cam.slice(0, -1).map((p, i) => { const o = alOffset(cam, i); return `<button type="button" class="al-chip ${i === s ? "on" : ""}" aria-pressed="${i === s}" onclick="alSube(${i})">${trEsc(p.nombre)}${o != null ? ` <small>${alHH(sv.h + o)}</small>` : ""}</button>`; }).join("")}</div></div>
      <div class="al-par-f"><span>Baja en</span><div class="al-chips">${cam.map((p, i) => i <= s ? "" : (() => { const o = alOffset(cam, i); return `<button type="button" class="al-chip ${i === b ? "on" : ""}" aria-pressed="${i === b}" onclick="alBaja(${i})">${trEsc(p.nombre)}${o != null ? ` <small>${alHH(sv.h + o)}</small>` : ""}</button>`; })()).join("")}</div></div>
    </div>` : "";
  const hor = alHorasTramo(sv, cam, s, b);

  content.innerHTML = alShell(`
    ${alBannerCambio()}
    ${alBuscador()}
    <div class="al-filtros">
      ${alChipsCorredores()}
      <div class="al-dias" role="group" aria-label="Día del viaje">${alChipsDias()}</div>
    </div>
    ${alChipsLado()}
    <div class="al-salidas" role="group" aria-label="Salidas del ${alDiaTxt(fechaD)}">${tabs}</div>
    <p class="al-nota">${alDiaTxt(fechaD)}.${alEsAgencia() ? "" : " " + alFuenteTxt(r)}${r.tipo === "internacional" ? " Viaje internacional: se piden los datos para migraciones." : ""}</p>

    <div class="al-cuerpo">
      <section class="al-escena" aria-labelledby="al-coche-t">
        <div class="al-cartel" aria-hidden="true">${trEsc(cam[b].nombre.toUpperCase())}</div>
        <div class="al-contenido">
          <div class="al-esc-cab">
            ${alEsAgencia() ? `<div><h2 id="al-coche-t" class="al-d">Servicio de las ${alHH(sv.h)}</h2>
              <span class="al-sub">${trEsc(sv.cod)}${sv.dur ? `, ${alDur(sv.dur)} de viaje` : ""} · ${trEsc(alPlano(sv).tipo || "")}</span></div>` : `
            <div><h2 id="al-coche-t" class="al-d">${sv.coche ? "Coche " + trEsc(sv.coche) : "Coche a confirmar"}</h2>
              <span class="al-sub">${trEsc(sv.coche ? sv.modelo : sv.habitual ? `Suele ir el ${sv.habitual}${sv.habitual_modelo ? " (" + sv.habitual_modelo + ")" : ""}` : "Todavía sin coche")} · ${trEsc(sv.cod)}, sale ${alHH(sv.h)}${sv.dur ? `, ${alDur(sv.dur)} de viaje` : ""}</span>
              ${sv.tripulacion.length ? `<span class="al-trip"><i class="ti ti-steering-wheel"></i> ${sv.tripulacion.map(trEsc).join(" y ")}</span>` : ""}
              ${sv.coche || sv.habitual ? `<label class="al-plano-sel"><span>Plano</span><select onchange="alCambiarPlano(this.value)" aria-label="Plano de asientos de este coche">${Object.entries(alPlanos()).map(([k, p]) => `<option value="${k}" ${k === sv.plano ? "selected" : ""}>${trEsc(p.nombre || k)} (${k})</option>`).join("")}</select></label>` : ""}
            </div>`}
            <div class="al-ley">
              <span><i class="al-ley-c"></i>Libre</span><span><i class="al-ley-c v"></i>Vendido</span><span><i class="al-ley-c r"></i>Reservado</span><span><i class="al-ley-c e"></i>Elegido</span>
              ${parados}
            </div>
          </div>
          ${paradas}
          ${pisos}
        </div>
      </section>
      <aside class="al-panel" id="al-panel" aria-label="Venta del asiento elegido">${alPanel()}</aside>
    </div>`, animar, `<div class="al-viaje">
        <span class="al-d">${trEsc(cam[s].nombre)}</span>
        <button type="button" class="al-redondo" onclick="alInvertir()" aria-label="Dar vuelta el viaje" title="Dar vuelta el viaje"><i class="ti ti-arrows-exchange"></i></button>
        <span class="al-d">${trEsc(cam[b].nombre)}</span>
        <small class="al-viaje-h">${alHH(hor.sale)}${hor.llega != null ? " → " + alHH(hor.llega) : ""}</small>
      </div>`);
}

function alPanel() {
  const sv = alServ(); if (!sv) return "";
  const fecha = alISO(alFechaDe(al.dia)), cam = alCamino(sv), [s, b] = alTramoIdx();
  const d = alDescAsiento(al.sel), intl = sv.intl, p = al.p;
  // Asiento reservado: se cobra o se libera
  const res = al.sel != null && al.sel !== "P" ? alOcupacion(fecha, al.dep, s, b).get(al.sel) : null;
  if (res && res.estado === "reserva" && al.cobrarReserva !== res.nro) {
    return `<div class="al-elegido"><div class="al-num reservado"><span class="al-d">${al.sel}</span></div>
      <div class="al-elegido-t"><b class="al-d">Reservado</b><span>${trEsc(res.nombre)}</span><small>${res.tipoDoc && res.mig ? trEsc(res.tipoDoc) : "CI"} ${trEsc(res.doc)}</small></div></div>
      <div class="al-res-info">
        <span><b>${trEsc(res.origen)} → ${trEsc(res.destino)}</b></span>
        <span>Reserva ${alNro(res.nro)}, hecha el ${alDM(res.reservado_en.slice(0, 10))} a las ${res.reservado_en.slice(11, 16)} por ${trEsc(res.vendedor || "")}</span>
        <span>Vence ${res.vence ? `el ${alDM(res.vence.slice(0, 10))} a las ${res.vence.slice(11, 16)}` : "al salir"} si no se cobra</span>
      </div>
      <button type="button" class="al-cobrar" onclick="alReservaCobrar(${res.nro})"><span class="al-cobrar-in"><span class="al-d">Cobrar la reserva</span></span></button>
      <button type="button" class="al-sec" onclick="alReservaLiberar(${res.nro})"><i class="ti ti-lock-open"></i> Liberar el asiento</button>`;
  }
  const pt = d ? alPrecioTramo(sv, d.clase, s, b) : null, total = alPrecio(al.sel);
  const con = alConocido(p.doc);
  const chips = (lista, actual, fn, nombre) => `<div class="al-chips" role="group" aria-label="${nombre}">${lista.map(t =>
    `<button type="button" class="al-chip ${t[0] === actual ? "on" : ""}" aria-pressed="${t[0] === actual}" onclick="${fn}('${t[0]}')">${trEsc(t[1])}</button>`).join("")}</div>`;
  const campo = (id, et, val, extra = "", cls = "") => `<label class="al-campo ${cls}"><span>${et}</span>
    <input id="al-${id}" autocomplete="off" value="${trEsc(val)}" ${extra} oninput="alCampo('${id}', this)"></label>`;
  const opciones = (lista, val, vacio) => `<option value="">${vacio}</option>` + lista.map(o => {
    const [v, t] = Array.isArray(o) ? o : [o, o];
    return `<option value="${v}" ${v === val ? "selected" : ""}>${t}</option>`;
  }).join("");
  const hint = con ? `Ya viajó ${con.viajes} ${con.viajes === 1 ? "vez" : "veces"} con ustedes` : intl ? "Con el documento se completan los datos si ya viajó" : "Con la cédula se completa el nombre si ya viajó";
  const datos = intl ? `
    <div class="al-mig">
      <div class="al-mig-t"><b>Datos para migraciones</b><span>Van a la lista de pasajeros del viaje internacional</span></div>
      <div class="al-fila">
        <label class="al-campo"><span>Documento</span><select id="al-tipoDoc" onchange="alCampo('tipoDoc', this)">${opciones(AL_TIPODOC, p.tipoDoc, "Elegí")}</select></label>
        ${campo("doc", "Número", p.doc, 'inputmode="text" onblur="alDocFormato(this)"', "ci")}
      </div>
      <p class="al-hint" id="al-hint">${hint}</p>
      <div class="al-fila">${campo("apellidos", "Apellidos", p.apellidos)}${campo("nombres", "Nombres", p.nombres)}</div>
      <div class="al-fila">
        <label class="al-campo"><span>Sexo</span><select id="al-sexo" onchange="alCampo('sexo', this)">${opciones([["F", "Femenino"], ["M", "Masculino"]], p.sexo, "Elegí")}</select></label>
        <label class="al-campo"><span>Fecha de nacimiento</span><input id="al-nac" type="date" value="${trEsc(p.nac)}" onchange="alCampo('nac', this)"></label>
      </div>
      <div class="al-fila">
        <label class="al-campo"><span>Nacionalidad</span><select id="al-nacionalidad" onchange="alCampo('nacionalidad', this)">${opciones(AL_NACION, p.nacionalidad, "Elegí")}</select></label>
        <label class="al-campo"><span>País donde vive</span><select id="al-residencia" onchange="alCampo('residencia', this)">${opciones(AL_PAISES, p.residencia, "Elegí")}</select></label>
      </div>
    </div>` : `
    <div class="al-fila">
      ${campo("doc", "Cédula", p.doc, 'inputmode="numeric" placeholder="Número" onblur="alDocFormato(this)"', "ci")}
      ${campo("nombre", "Nombre y apellido", p.nombre, 'placeholder="Como figura en la cédula"')}
    </div>
    <p class="al-hint" id="al-hint">${hint}</p>`;
  const hor = alHorasTramo(sv, cam, s, b);
  // Cambio de boleto: la diferencia con lo que ya pagó
  let cambio = null;
  if (al.cambio) {
    const v = alGuardado().ventas.find(x => x.nro === al.cambio);
    if (v) cambio = { v, dif: total - v.total };
  }
  const reserva = al.cobrarReserva ? alGuardado().ventas.find(x => x.nro === al.cobrarReserva) : null;
  const aCobrar = cambio ? Math.max(0, cambio.dif) : total;
  const boton = cambio ? "Confirmar el cambio" : reserva ? "Cobrar la reserva" : "Cobrar e imprimir";
  return `
    ${reserva ? `<div class="al-res-info on"><span><b>Cobrando la reserva ${alNro(reserva.nro)}</b></span><span>Revisá los datos y cobrá. <button type="button" class="al-link" onclick="al.cobrarReserva=null;al.p=AL_PVACIO();alRepintarPanel()">Volver</button></span></div>` : ""}
    <div class="al-elegido">
      <div class="al-num ${d ? "" : "vacio"} ${d && d.parado ? "parado" : ""}"><span class="al-d">${d ? (d.parado ? "P" : al.sel) : "?"}</span></div>
      <div class="al-elegido-t">
        <b class="al-d">${d ? trEsc(d.piso) : "Sin asiento"}</b>
        <span>${d ? d.pos : "Tocá un asiento libre en el coche"}</span>
        <small>${d ? d.tipo : ""}</small>
      </div>
    </div>
    <div class="al-linea">
      <b class="al-d">${alHH(hor.sale)}</b><i aria-hidden="true"></i><b class="al-d der">${hor.llega != null ? alHH(hor.llega) : "—"}</b>
      <span>${trEsc(cam[s].nombre)}</span><span class="cen">${hor.llega != null ? alDur(hor.llega - hor.sale) : trEsc(sv.cod)}</span><span class="der">${trEsc(cam[b].nombre)}</span>
    </div>
    ${datos}
    ${chips(alDescuentos().map(t => [t.id, t.nombre]), al.tarifa, "alTarifa", "Tarifa")}
    ${aCobrar > 0 ? chips(AL_PAGOS, al.pago, "alPago", "Forma de pago") : ""}
    ${al.pago === "efectivo" && aCobrar > 0 ? `
    <div class="al-vuelto">
      <label class="al-campo"><span>Recibe</span>
        <input id="al-recibe" inputmode="numeric" autocomplete="off" value="${al.recibe ? fmtNum(+al.recibe) : ""}" placeholder="${fmtNum(Math.ceil((aCobrar + 1) / 50000) * 50000)}" oninput="alRecibe(this)"></label>
      <div class="al-vuelto-t"><span>Vuelto</span><b class="al-d" id="al-vuelto">${alVueltoTxt(aCobrar)}</b></div>
    </div>` : ""}
    ${cambio ? `<div class="al-dif"><span>Ya pagó</span><b>${alGs(cambio.v.total)}</b><span>Nuevo precio</span><b>${alGs(total)}</b></div>` : ""}
    <div class="al-total"><span>${cambio ? (cambio.dif >= 0 ? "Cobra la diferencia" : "Se le devuelve") : "Total"}</span><b class="al-d">${alGs(cambio ? Math.abs(cambio.dif) : total)}</b></div>
    ${pt && pt.ejemplo ? `<p class="al-hint">Precio de ejemplo: este tramo no tiene tarifa cargada.</p>` : ""}
    <button type="button" class="al-cobrar" onclick="alCobrar()" ${d && pt ? "" : "disabled"}>
      <span class="al-cobrar-in"><span class="al-d">${boton}</span><kbd>F9</kbd></span>
    </button>
    ${!cambio && !reserva && d && pt ? `<button type="button" class="al-sec" onclick="alReservar()"><i class="ti ti-bookmark"></i> Reservar sin cobrar</button>` : ""}
    <p class="al-aviso" id="al-aviso" role="status">${d && !pt ? "Ese tramo no tiene precio: cargalo en Tarifas." : trEsc(al.aviso)}</p>`;
}
function alVueltoTxt(total) {
  const r = +al.recibe || 0;
  if (!r) return "—";
  return r >= total ? fmtNum(r - total) : "faltan " + fmtNum(total - r);
}
function alRepintarPanel() { const p = document.getElementById("al-panel"); if (p) p.innerHTML = alPanel(); }
function alAvisoLimpio() { if (al.aviso) { al.aviso = ""; const a = document.getElementById("al-aviso"); if (a) a.textContent = ""; } }

function alCambiarRuta(c) { if (c === al.cor) return; al.cor = c; al.lado = "ida"; al.dep = 0; al.sube = 0; al.baja = -1; al.sel = null; al.aviso = ""; alPintar(true); }
function alLado(l) { if (l === al.lado) return; al.lado = l; al.dep = 0; al.sube = 0; al.baja = -1; al.sel = null; al.aviso = ""; alPintar(true); }
function alSalida(k) { al.dep = k; al.sube = 0; al.baja = -1; al.sel = null; al.aviso = ""; alPintar(true); }
function alSube(i) { al.sube = i; const [, b] = alTramoIdx(); if (b <= i) al.baja = -1; al.sel = null; alPintar(false); }
function alBaja(i) { al.baja = i; al.sel = null; alPintar(false); }
async function alDia(i) {
  al.dia = i; al.sel = null; al.aviso = ""; al.dep = 0; al.sube = 0; al.baja = -1;
  if (!al.datos[alISO(alFechaDe(i))]) { al.cargando = true; alRender(false); await alTraer(); }
  alRender(true);
}
function alInvertir() { alLado(al.lado === "ida" ? "regreso" : "ida"); }
function alAsiento(n) { al.sel = n; al.aviso = ""; if (al.cobrarReserva) { al.cobrarReserva = null; al.p = AL_PVACIO(); } alPintar(false); }
function alTarifa(t) { al.tarifa = t; alRepintarPanel(); }
function alPago(p) { al.pago = p; alRepintarPanel(); }
function alCampo(id, el) {
  if (!el.isConnected) return;          // un campo que ya se borró de la pantalla no pisa los datos nuevos
  let v = el.value;
  if (["nombre", "apellidos", "nombres"].includes(id)) { v = v.toUpperCase(); el.value = v; }
  al.p[id] = v;
  alAvisoLimpio();
  if (id !== "doc") return;
  const con = alConocido(v), h = document.getElementById("al-hint"), intl = alServ()?.intl;
  if (con) {
    const d = con.datos, p = al.p;
    const poner = (k, val) => { if (val && !p[k]) { p[k] = val; const e = document.getElementById("al-" + k); if (e) e.value = val; } };
    if (intl) ["apellidos", "nombres", "sexo", "nac", "nacionalidad", "residencia"].forEach(k => poner(k, d[k]));
    else poner("nombre", d.nombreCompleto || [d.nombres, d.apellidos].filter(Boolean).join(" "));
  }
  if (h) h.textContent = con ? `Ya viajó ${con.viajes} ${con.viajes === 1 ? "vez" : "veces"} con ustedes` : intl ? "Con el documento se completan los datos si ya viajó" : "Con la cédula se completa el nombre si ya viajó";
}
function alDocFormato(inp) {
  // La cédula paraguaya con puntos; pasaportes y otros documentos se dejan como están
  if (!inp.isConnected || al.p.tipoDoc !== "CI") return;
  const d = inp.value.replace(/\D/g, "");
  al.p.doc = d ? fmtNum(+d) : "";
  inp.value = al.p.doc;
}
function alRecibe(inp) {
  if (!inp.isConnected) return;
  const d = inp.value.replace(/\D/g, "");
  al.recibe = d;
  inp.value = d ? fmtNum(+d) : "";
  const v = document.getElementById("al-vuelto");
  if (v) {
    let aCobrar = alPrecio(al.sel);
    if (al.cambio) { const x = alGuardado().ventas.find(y => y.nro === al.cambio); if (x) aCobrar = Math.max(0, aCobrar - x.total); }
    v.textContent = alVueltoTxt(aCobrar);
  }
}

// Lo que se arma igual para una venta, una reserva o un cambio
function alDatosViaje() {
  const sv = alServ(), cam = alCamino(sv), [s, b] = alTramoIdx(), fechaD = alFechaDe(al.dia);
  const hor = alHorasTramo(sv, cam, s, b), d = alDescAsiento(al.sel);
  let llegaDia = "";
  if (hor.llega != null && hor.llega >= 1440) { const x = new Date(fechaD); x.setDate(x.getDate() + Math.floor(hor.llega / 1440)); llegaDia = AL_DIAS[x.getDay()] + " " + x.getDate(); }
  return {
    fecha: alISO(fechaD), servicio: sv.clave, cor: sv.cor, lado: sv.lado, hora: sv.hora, sale: alHH(hor.sale),
    llega: hor.llega != null ? alHH(hor.llega) : "", llegaDia, tramo: sv.cod, coche: sv.coche || "", plano: sv.plano,
    sube: cam[s].nombre, baja: cam[b].nombre, origen: cam[s].nombre, destino: cam[b].nombre, intl: !!sv.intl,
    asiento: al.sel, asDesc: d ? { piso: d.piso, pos: d.pos, tipo: d.tipo, clase: d.clase, pisoIdx: d.pisoIdx } : null,
  };
}
function alFaltan(completo) {
  const d = alDescAsiento(al.sel), p = al.p, intl = alServ()?.intl;
  const falta = [];
  if (!d) falta.push("el asiento");
  if (!String(p.doc).trim()) falta.push(intl ? "el documento" : "la cédula");
  if (intl) {
    if (!p.apellidos.trim()) falta.push("los apellidos");
    if (!p.nombres.trim()) falta.push("los nombres");
    if (completo) {
      if (!p.tipoDoc) falta.push("el tipo de documento");
      if (!p.sexo) falta.push("el sexo");
      if (!p.nac) falta.push("la fecha de nacimiento");
      if (!p.nacionalidad) falta.push("la nacionalidad");
      if (!p.residencia) falta.push("el país donde vive");
    }
  } else if (!p.nombre.trim()) falta.push("el nombre");
  return falta.length ? (falta.length > 1 ? "Faltan " : "Falta ") + falta.join(", ").replace(/, ([^,]*)$/, " y $1") + "." : "";
}
function alPasajero() {
  const p = al.p, intl = alServ()?.intl;
  return {
    nombre: alNombreCompleto(p).trim().toUpperCase(), doc: String(p.doc).trim(),
    tipoDoc: (AL_TIPODOC.find(t => t[0] === p.tipoDoc) || AL_TIPODOC[0])[1], tipoDocId: p.tipoDoc || "CI",
    mig: intl ? { apellidos: p.apellidos, nombres: p.nombres, sexo: p.sexo, nac: p.nac, nacionalidad: p.nacionalidad, residencia: p.residencia } : null,
  };
}
function alLimpiarVenta() {
  al.p = AL_PVACIO(); al.recibe = ""; al.tarifa = "general"; al.pago = "efectivo"; al.sel = null; al.aviso = "";
  al.cambio = null; al.cobrarReserva = null;
}
function alCobrar() {
  if (al.vista !== "vender") return;
  // Se suelta el campo que se estaba escribiendo antes de vaciar el formulario,
  // así su "al salir" no vuelve a poner el dato viejo en la venta siguiente
  if (document.activeElement && document.activeElement.closest && document.activeElement.closest("#al-raiz")) document.activeElement.blur();
  const sv = alServ(); if (!sv) return;
  const total = alPrecio(al.sel), [s, b] = alTramoIdx();
  const d = alDescAsiento(al.sel), pt = d ? alPrecioTramo(sv, d.clase, s, b) : null;
  if (d && !pt) { al.aviso = "Ese tramo no tiene precio: cargalo en Tarifas."; alRepintarPanel(); return; }
  const falta = alFaltan(true);
  if (falta) { al.aviso = falta; alRepintarPanel(); return; }
  const g = alGuardado(), ahora = alAhoraISO(), vend = alVendedor();
  const cambio = al.cambio ? g.ventas.find(x => x.nro === al.cambio) : null;
  const aCobrar = cambio ? Math.max(0, total - cambio.total) : total;
  if (al.pago === "efectivo" && al.recibe && aCobrar > 0 && +al.recibe < aCobrar) { al.aviso = "Lo que recibe no alcanza: faltan " + alGs(aCobrar - al.recibe) + "."; alRepintarPanel(); return; }
  // El asiento puede haberse vendido en otra pestaña mientras se cargaban los datos
  const o = alOcupacion(alISO(alFechaDe(al.dia)), al.dep, s, b).get(al.sel);
  if (o && o.nro !== al.cobrarReserva && (o.estado === "vendido" || o.estado === "reserva")) { al.aviso = "Ese asiento ya está tomado en ese tramo."; alPintar(false); return; }
  const viaje = alDatosViaje(), pas = alPasajero();
  const recibe = al.pago === "efectivo" && aCobrar > 0 ? (+al.recibe || aCobrar) : null;
  let v;
  if (cambio) {
    const antes = { fecha: cambio.fecha, sale: cambio.sale, origen: cambio.origen, destino: cambio.destino, asiento: cambio.asiento, total: cambio.total, tramo: cambio.tramo };
    v = Object.assign(cambio, viaje, pas, { total, tarifa: al.tarifa });
    v.cambios = (v.cambios || []).concat([{ el: ahora, por: vend, antes }]);
    const dif = total - antes.total;
    if (dif) v.movs.push({ t: "cambio", el: ahora, monto: dif, pago: dif > 0 ? al.pago : "efectivo", vendedor: vend, recibe });
  } else if (al.cobrarReserva) {
    v = g.ventas.find(x => x.nro === al.cobrarReserva);
    if (!v || !alReservaViva(v)) { al.aviso = "La reserva ya no está vigente."; al.cobrarReserva = null; alPintar(false); return; }
    Object.assign(v, viaje, pas, { estado: "vendido", total, tarifa: al.tarifa, pago: al.pago, recibe, vendido_en: ahora, vendedor: vend });
    v.movs.push({ t: "cobro", el: ahora, monto: total, pago: al.pago, vendedor: vend, recibe });
  } else {
    v = Object.assign({ nro: g.nro, estado: "vendido" }, viaje, pas, { total, tarifa: al.tarifa, pago: al.pago, recibe, vendido_en: ahora, vendedor: vend,
      movs: [{ t: "venta", el: ahora, monto: total, pago: al.pago, vendedor: vend, recibe }] });
    g.ventas.push(v); g.nro += 1;
  }
  alGuardar(g);
  alImprimir(alBoletoHTML(v));
  toast(cambio ? `Boleto ${alNro(v.nro)} cambiado` : `Boleto ${alNro(v.nro)} vendido: ${v.asiento === "P" ? "parado" : "asiento " + v.asiento}`, "success");
  alLimpiarVenta();
  alPintar(false);
}
function alReservar() {
  if (document.activeElement && document.activeElement.closest && document.activeElement.closest("#al-raiz")) document.activeElement.blur();
  if (al.sel === "P") { al.aviso = "Los pasajes parados no se reservan."; alRepintarPanel(); return; }
  const falta = alFaltan(false);
  if (falta) { al.aviso = falta; alRepintarPanel(); return; }
  const g = alGuardado(), ahora = alAhoraISO(), viaje = alDatosViaje();
  const venc = new Date(`${viaje.fecha}T${viaje.sale}`); venc.setMinutes(venc.getMinutes() - AL_RESERVA_MIN);
  const vence = alISO(venc) + "T" + String(venc.getHours()).padStart(2, "0") + ":" + String(venc.getMinutes()).padStart(2, "0");
  if (vence <= ahora) { al.aviso = "Falta menos de una hora para la salida: ya no se reserva, se vende."; alRepintarPanel(); return; }
  const v = Object.assign({ nro: g.nro, estado: "reserva" }, viaje, alPasajero(), { total: alPrecio(al.sel), tarifa: al.tarifa,
    reservado_en: ahora, vence, vendedor: alVendedor(), movs: [] });
  g.ventas.push(v); g.nro += 1;
  alGuardar(g);
  toast(`Asiento ${v.asiento} reservado para ${v.nombre} hasta el ${alDM(vence.slice(0, 10))} ${vence.slice(11)}`, "success");
  alLimpiarVenta();
  alPintar(false);
}
function alReservaCobrar(nro) {
  const v = alGuardado().ventas.find(x => x.nro === nro);
  if (!v) return;
  al.cobrarReserva = nro; al.tarifa = v.tarifa || "general";
  const cam = alCamino(alServ());
  al.sube = alIdxDe(cam, v.sube, 0); al.baja = alIdxDe(cam, v.baja, cam.length - 1);
  al.sel = v.asiento;
  al.p = Object.assign(AL_PVACIO(), v.mig || {}, { doc: v.doc, nombre: v.mig ? "" : v.nombre, tipoDoc: v.tipoDocId || "CI" });
  alPintar(false);
}
function alReservaLiberar(nro) {
  const g = alGuardado(), v = g.ventas.find(x => x.nro === nro);
  if (!v || !confirm(`¿Liberar el asiento ${v.asiento} reservado para ${v.nombre}?`)) return;
  v.estado = "liberada"; v.liberada_en = alAhoraISO(); v.liberada_por = alVendedor();
  alGuardar(g);
  toast("Reserva liberada", "success");
  al.sel = null;
  alRender(false);
}
function alCambioCancelar() { alLimpiarVenta(); alPintar(false); }

// ─── Buscador de horarios: todas las salidas del día, de todos los corredores ───
function alBuscador() {
  if (!alCorredores().length) return "";
  return `<div class="al-busca" id="al-busca">
    <i class="ti ti-search" aria-hidden="true"></i>
    <input id="al-busca-q" type="search" autocomplete="off" placeholder="${alEsAgencia() ? "Buscá un horario: destino u hora" : "Buscá un horario: destino, hora, coche o tripulante"}"
      aria-label="Buscar un horario" aria-controls="al-busca-res" oninput="alBuscar()" onfocus="alBuscar()" onkeydown="alBuscaTecla(event)">
    <div class="al-busca-res" id="al-busca-res" role="listbox" hidden></div>
  </div>`;
}
function alTodasSalidas() {
  const out = [];
  alCorredores().forEach(c => ["ida", "regreso"].forEach(l => (c[l] || []).forEach((x, k) => out.push({ c, l, k, x }))));
  return out.sort((a, b) => a.x.hora.localeCompare(b.x.hora) || a.c.titulo.localeCompare(b.c.titulo));
}
function alBuscar() {
  const box = document.getElementById("al-busca-res"), q = document.getElementById("al-busca-q");
  if (!box || !q) return;
  const palabras = alNorm(q.value).split(/\s+/).filter(Boolean);
  const hits = alTodasSalidas().filter(({ c, l, x }) => {
    if (!palabras.length) return true;
    const rec = ((al.cfg && al.cfg.recorridos) || {})[c.clave] || [];
    const txt = alNorm([c.titulo, c.corredor, x.origen_nombre, x.llega_nombre, x.origen, x.llega, x.destino, x.tramo, (x.extras || []).join(" "),
      x.hora, x.hora.replace(":", ""), l, l === "ida" ? "desde asuncion" : "a asuncion",
      alEsAgencia() ? "" : [x.coche, x.habitual, (x.tripulacion || []).join(" ")].join(" "),
      rec.map(r => r.paradas.map(p => p.nombre).join(" ")).join(" "),
      c.tipo === "internacional" ? "internacional buenos aires argentina" : ""].join(" "));
    return palabras.every(w => txt.includes(w));
  });
  al.buscaHits = hits; al.buscaSel = 0;
  const ahora = new Date().getHours() * 60 + new Date().getMinutes();
  const fue = x => al.dia === 0 && alMin(x.hora) <= ahora;
  box.hidden = false;
  box.innerHTML = hits.length ? `<div class="al-busca-cab">${palabras.length ? `${hits.length} horario${hits.length === 1 ? "" : "s"}` : `Todos los horarios del día · ${hits.length}`}</div>` +
    hits.slice(0, 60).map(({ c, l, x }, i) => `
      <button type="button" class="al-busca-it ${i === 0 ? "on" : ""} ${fue(x) ? "fue" : ""}" role="option" data-i="${i}" onmousedown="event.preventDefault()" onclick="alIrA(${i})">
        <b class="al-d">${x.hora}</b>
        <span class="al-busca-t"><b>${trEsc(x.origen_nombre)} → ${trEsc(x.llega_nombre)}</b><small>${trEsc([x.tramo, ...(x.extras || [])].join(" "))} · ${l === "ida" ? "ida" : "regreso"}${c.tipo === "internacional" ? " · internacional" : ""}${!alEsAgencia() && palabras.length && (x.tripulacion || []).length && palabras.some(w => alNorm(x.tripulacion.join(" ")).includes(w)) ? " · " + trEsc(x.tripulacion.join(" y ")) : ""}</small></span>
        <span class="al-busca-c">${alEsAgencia() ? "" : x.coche ? `Coche ${trEsc(x.coche)}` : x.habitual ? `<i>a conf. (${trEsc(x.habitual)})</i>` : "<i>a confirmar</i>"}${fue(x) ? "<small>ya salió</small>" : ""}</span>
      </button>`).join("") + (hits.length > 60 ? `<div class="al-busca-cab">y ${hits.length - 60} más: escribí algo más</div>` : "")
    : `<div class="al-busca-nada">No hay horarios con «${trEsc(q.value)}» este día.</div>`;
}
function alBuscaTecla(e) {
  const box = document.getElementById("al-busca-res");
  const its = box ? [...box.querySelectorAll(".al-busca-it")] : [];
  if (e.key === "Escape") { if (box) box.hidden = true; e.target.blur(); return; }
  if (!its.length) return;
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    al.buscaSel = Math.max(0, Math.min(its.length - 1, (al.buscaSel || 0) + (e.key === "ArrowDown" ? 1 : -1)));
    its.forEach((b, i) => b.classList.toggle("on", i === al.buscaSel));
    its[al.buscaSel].scrollIntoView({ block: "nearest" });
  } else if (e.key === "Enter") { e.preventDefault(); alIrA(al.buscaSel || 0); }
}
function alIrA(i) {
  const h = (al.buscaHits || [])[i];
  if (!h) return;
  al.cor = h.c.clave; al.lado = h.l; al.dep = h.k; al.sube = 0; al.baja = -1; al.sel = null; al.aviso = "";
  alPintar(true);
  document.querySelector(".al-tab.on")?.scrollIntoView({ block: "nearest" });
}
document.addEventListener("mousedown", e => {
  const b = document.getElementById("al-busca");
  if (b && !b.contains(e.target)) { const r = document.getElementById("al-busca-res"); if (r) r.hidden = true; }
});

// ════════════════════════════════════════════════════════════════════════════
// EL BOLETO: 3 copias en papel de 80 mm, una por hoja (la impresora corta)
// ════════════════════════════════════════════════════════════════════════════
function alBoletoHTML(v) {
  const e = trEsc, fechaD = alDeISO(v.fecha);
  const nro = "001-001-" + alNro(v.nro);
  const sale = v.sale || v.hora, llega = v.llega || "";
  const servicio = `Servicio ${v.tramo || ""}${v.coche && window.USUARIO_ROL !== "agencia" ? ", coche " + v.coche : ""}`;
  const desc = alDescuentos().find(t => t.id === v.tarifa);
  const tarifa = (desc ? desc.nombre : "General").toLowerCase();
  const pago = (AL_PAGOS.find(p => p[0] === v.pago) || AL_PAGOS[0])[1].toLowerCase();
  const em = (v.cambios && v.cambios.length ? v.cambios[v.cambios.length - 1].el : v.vendido_en) || alAhoraISO();
  const emitido = `${em.slice(8, 10)}/${em.slice(5, 7)}/${em.slice(0, 4)} ${em.slice(11, 16)}`;
  const vendedor = v.vendedor ? `Vendió ${e(v.vendedor)}.` : "";
  const parado = v.asiento === "P", d = v.asDesc || { piso: "", pos: "", tipo: AL_CLASES.CO };
  let mapa = "";
  const pl = alPlanos()[v.plano];
  if (!parado && pl && d.pisoIdx != null && pl.pisos[d.pisoIdx]) {
    const piso = pl.pisos[d.pisoIdx], nf = piso.filas.length;
    piso.filas.forEach((f, fi) => f.forEach((n, pos) => {
      if (n != null) mapa += `<i style="grid-column:${nf - fi};grid-row:${pos + 1}" class="${n === v.asiento ? "si" : ""}"></i>`;
    }));
    mapa = `<div class="mapa"><div class="g" style="grid-template-columns:repeat(${nf},6px)">${mapa}</div><span>frente →</span></div>`;
  }
  const docTxt = v.mig ? `${e(v.tipoDoc)} ${e(v.doc)}` : `CI ${e(v.doc)}`;
  const reimp = v._reimpresion ? `<div class="reimp">REIMPRESIÓN</div>` : "";
  const cab = `
    <div class="cab"><img src="${location.origin}/static/logo.png" alt=""><div><b class="n">La Santaniana</b><span>RUC [RUC], timbrado [número]<br>vence [fecha]</span></div></div>
    ${reimp}
    <div class="doc"><b>Boleto ${nro}</b><span>${emitido}</span></div>
    <div class="dia">${alDiaTxt(fechaD)}</div>`;
  const ruta = (larga) => `
    <div class="ruta">
      <i class="p"></i><b class="c">${e(v.origen.toUpperCase())}</b><b class="h">${sale}</b>
      ${larga ? `<i class="l"></i><span class="m">${e(servicio)}.${llega ? ` ${v.llegaDia ? `Llega el ${e(v.llegaDia)}; la hora` : "La llegada"} es aproximada.` : ""}</span>` : ""}
      <i class="p o"></i><b class="c">${e(v.destino.toUpperCase())}</b><b class="h">${llega}</b>
    </div>`;
  const nroAs = (big) => parado
    ? `<div class="nro ${big ? "big" : ""}"><span>Pasaje</span><b class="par">Parado</b></div>`
    : `<div class="nro ${big ? "big" : ""}"><span>Asiento</span><b>${v.asiento}</b>${big ? `<span>${e(String(d.piso).toLowerCase())}</span>` : ""}</div>`;
  const asiento = (conMapa) => `
    <div class="as">${nroAs(false)}
      <div class="as-t"><b>${e(d.piso)}</b><span>${e(d.pos)}</span>${conMapa ? mapa : ""}<small>${e(d.tipo)} · ${e(servicio)}</small></div>
    </div>`;
  const pas = `<div class="pas"><b>${e(v.nombre)}</b><span>${docTxt}</span>${v.mig ? `<span>${e(v.mig.nacionalidad)}, nac. ${e(String(v.mig.nac || "").split("-").reverse().join("/"))}</span>` : ""}</div>`;
  const precio = (detalle) => `
    <div class="pre">
      <div class="r"><span>${e(d.tipo)}, tarifa ${e(tarifa)}</span><span>${fmtNum(v.total)}</span></div>
      <div class="t"><b>Total Gs.</b><b class="tg">${fmtNum(v.total)}</b></div>
      <span class="p">${detalle}</span>
    </div>`;
  const pie = (a, b) => `<div class="pie"><b>${a}</b><span>${b}</span></div><div class="maq">Maqueta de Alpha: sin valor fiscal</div>`;
  const efectivo = v.pago === "efectivo" && v.recibe ? ` Recibió ${fmtNum(v.recibe)}, vuelto ${fmtNum(v.recibe - v.total)}.` : "";
  const cambiado = v.cambios && v.cambios.length ? ` Cambio del boleto: antes ${alDM(v.cambios[v.cambios.length - 1].antes.fecha)} ${v.cambios[v.cambios.length - 1].antes.sale || ""}.` : "";
  const original = `<article>${cab}${ruta(true)}${asiento(true)}${pas}${precio(`Pagó con ${pago}.${cambiado} ${vendedor}`)}
    <div class="nota">Mostrá este boleto al subir. Presentate [minutos] antes de la salida. Equipaje incluido: [kg].${v.mig ? " Viajá con el mismo documento que figura acá." : ""}</div>${pie("Original", "para el pasajero")}</article>`;
  const duplicado = `<article>${cab}${ruta(false)}${asiento(false)}${pas}${precio(`Pagó con ${pago}.${efectivo}${cambiado} ${vendedor}`)}${pie("Duplicado", "queda en la caja")}</article>`;
  const triplicado = `<article class="tri">
    <div class="doc top"><b class="n">La Santaniana</b><b>Boleto ${alNro(v.nro)}</b></div>
    <div class="tri-s">${alDiaTxt(fechaD).split(" de ")[0]}, sale ${sale}<br>${e(servicio)}</div>
    <div class="as">${nroAs(true)}
      <div class="as-t mid"><span>Baja en</span><b class="baja">${e(v.destino.toUpperCase())}</b><small>Sube en ${e(v.origen)}</small></div></div>
    ${pas}${pie("Triplicado", "para el guarda")}</article>`;
  return `<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Boleto ${nro}</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,400..900&display=swap">
<style>
@page{size:80mm auto;margin:0}
*{box-sizing:border-box}
html,body{margin:0;background:#fff;color:#000;font-family:Archivo,Arial,sans-serif}
article{width:80mm;padding:5mm 4mm 3mm;break-after:page;page-break-after:always}
article:last-child{break-after:auto;page-break-after:auto}
.cab{display:flex;align-items:center;gap:10px}
.cab img{width:46px;height:32px;object-fit:contain;filter:grayscale(1) contrast(1.8) brightness(.85)}
.cab div{display:flex;flex-direction:column;gap:2px}
.n{font-weight:800;font-size:18px;line-height:1;font-stretch:80%}
.cab span{font-size:11px;line-height:1.3}
.reimp{margin-top:8px;padding:3px 0;border:1.5px solid #000;text-align:center;font-weight:900;font-size:13px;letter-spacing:.12em}
.doc{display:flex;justify-content:space-between;align-items:baseline;gap:8px;margin-top:10px;padding-top:8px;border-top:1.5px dashed #000}
.doc b{font-size:13px}.doc span{font-size:11px}
.doc.top{margin-top:0;padding-top:0;border:0}
.dia{margin-top:6px;font-weight:800;font-size:18px;line-height:1.1;font-stretch:85%}
.ruta{display:grid;grid-template-columns:12px minmax(0,1fr) auto;column-gap:9px;row-gap:6px;margin-top:8px}
.ruta .p{width:12px;height:12px;border-radius:50%;background:#000;align-self:center}
.ruta .p.o{background:#fff;border:3px solid #000}
.ruta .c{font-weight:800;font-size:25px;line-height:1;font-stretch:68%}
.ruta .h{font-weight:800;font-size:25px;line-height:1;font-stretch:85%;font-variant-numeric:tabular-nums}
.ruta .l{width:3px;justify-self:center;align-self:stretch;background:#000}
.ruta .m{grid-column:2/4;font-size:11px;line-height:1.35}
.as{display:flex;align-items:stretch;gap:11px;margin-top:10px;padding-top:10px;border-top:1.5px dashed #000}
.nro{width:76px;flex:0 0 76px;background:#000;color:#fff;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:6px 0 4px;-webkit-print-color-adjust:exact;print-color-adjust:exact}
.nro span{font-size:11px;font-weight:700}
.nro b{font-weight:900;font-size:50px;line-height:.95;font-stretch:80%;font-variant-numeric:tabular-nums}
.nro b.par{font-size:24px;line-height:1.2;font-stretch:75%}
.nro.big{width:92px;flex-basis:92px}.nro.big b{font-size:62px}.nro.big b.par{font-size:28px}
.as-t{display:flex;flex-direction:column;gap:4px;min-width:0}
.as-t.mid{justify-content:center;gap:2px}
.as-t > b{font-weight:800;font-size:19px;line-height:1;font-stretch:80%}
.as-t > span{font-size:12px;font-weight:600}
.as-t small{font-size:11px}
.as-t .baja{font-weight:900;font-size:34px;line-height:.95;font-stretch:64%}
.mapa{display:flex;align-items:center;gap:4px}
.mapa > span{font-size:10.5px;font-weight:600}
.g{display:grid;grid-template-rows:6px 6px 3px 6px 6px;gap:2px;padding:3px;border:1.25px solid #000;border-radius:3px 8px 8px 3px}
.g i{width:6px;height:6px;border:1px solid #000}
.g i.si{background:#000;-webkit-print-color-adjust:exact;print-color-adjust:exact}
.pas{display:flex;flex-direction:column;gap:2px;margin-top:10px;padding-top:8px;border-top:1.5px dashed #000}
.pas b{font-weight:800;font-size:16px}.pas span{font-size:12.5px;font-weight:600}
.pre{display:flex;flex-direction:column;gap:4px;margin-top:10px;padding-top:8px;border-top:1.5px dashed #000}
.pre .r{display:flex;justify-content:space-between;gap:8px;font-size:12px}
.pre .t{display:flex;justify-content:space-between;align-items:baseline}
.pre .t b{font-weight:800;font-size:14px}.pre .t .tg{font-weight:900;font-size:27px;line-height:1;font-stretch:85%}
.pre .p{font-size:11px;line-height:1.4}
.nota{margin-top:10px;padding-top:8px;border-top:1.5px dashed #000;font-size:11px;line-height:1.35}
.tri-s{margin-top:8px;padding-top:8px;border-top:1.5px dashed #000;font-weight:800;font-size:16px;line-height:1.25;font-stretch:85%}
.pie{display:flex;justify-content:space-between;align-items:baseline;margin:12px -4mm 0;padding:8px 4mm 9px;background:#000;color:#fff;-webkit-print-color-adjust:exact;print-color-adjust:exact}
.pie b{font-weight:900;font-size:18px;font-stretch:85%}.pie span{font-size:11px;font-weight:600}
.maq{margin-top:5px;font-size:10px;text-align:center}
</style></head><body>${original}${duplicado}${triplicado}</body></html>`;
}
function alImprimir(html, ancho = "80mm") {
  const f = document.createElement("iframe");
  f.setAttribute("aria-hidden", "true");
  f.style.cssText = `position:fixed;left:-10000px;top:0;width:${ancho};height:20px;border:0`;
  document.body.appendChild(f);
  const doc = f.contentDocument;
  doc.open(); doc.write(html); doc.close();
  const listo = () => {
    const w = f.contentWindow;
    const fuentes = w.document.fonts ? w.document.fonts.ready : Promise.resolve();
    Promise.race([fuentes, new Promise(r => setTimeout(r, 2500))]).then(() => {
      w.focus(); w.print();
      setTimeout(() => f.remove(), 60000);
    });
  };
  if (doc.readyState === "complete") setTimeout(listo, 300); else f.onload = listo;
}

// ════════════════════════════════════════════════════════════════════════════
// PASAJES: consultar, reimprimir, cambiar, devolver, anular; reservas
// ════════════════════════════════════════════════════════════════════════════
const AL_ESTADOS = { vendido: "Vendido", reserva: "Reserva", anulado: "Anulado", devuelto: "Devuelto", liberada: "Liberada", vencida: "Vencida" };
function alEstado(v) { return v.estado === "reserva" && !alReservaViva(v) ? "vencida" : v.estado; }
function alVistaPasajes(animar) {
  const g = alGuardado(), q = alNorm(al.pas.q), est = al.pas.estado;
  const palabras = q.split(/\s+/).filter(Boolean);
  const todas = g.ventas.filter(v => window.USUARIO_ROL !== "agencia" || v.vendedor === alVendedor()).sort((a, b) => b.nro - a.nro);
  const cuenta = {}; todas.forEach(v => { const e = alEstado(v); cuenta[e] = (cuenta[e] || 0) + 1; });
  const lista = todas.filter(v => (!est || alEstado(v) === est) && (!palabras.length || palabras.every(w =>
    alNorm([alNro(v.nro), v.nro, v.nombre, v.doc, String(v.doc).replace(/\D/g, ""), v.origen, v.destino, v.tramo, v.coche, v.fecha, alDM(v.fecha), v.sale].join(" ")).includes(w))));
  const ahora = alAhoraISO(), hoy = ahora.slice(0, 10);
  const fila = v => {
    const e = alEstado(v), futuro = alSalidaISO(v) > ahora;
    const acc = [];
    if (e === "vendido") {
      acc.push(`<button type="button" class="al-ic" title="Reimprimir" aria-label="Reimprimir" onclick="alReimprimir(${v.nro})"><i class="ti ti-printer"></i></button>`);
      if (futuro) acc.push(`<button type="button" class="al-ic" title="Cambiar fecha, servicio o asiento" aria-label="Cambiar" onclick="alCambiar(${v.nro})"><i class="ti ti-arrows-exchange"></i></button>`);
      if (futuro) acc.push(`<button type="button" class="al-ic" title="Devolver" aria-label="Devolver" onclick="alDevolver(${v.nro})"><i class="ti ti-receipt-refund"></i></button>`);
      if ((v.vendido_en || "").slice(0, 10) === hoy && futuro) acc.push(`<button type="button" class="al-ic rojo" title="Anular (solo el mismo día)" aria-label="Anular" onclick="alAnular(${v.nro})"><i class="ti ti-ban"></i></button>`);
    } else if (e === "reserva") {
      acc.push(`<button type="button" class="al-ic" title="Ir a cobrarla" aria-label="Cobrar la reserva" onclick="alIrAReserva(${v.nro})"><i class="ti ti-cash"></i></button>`);
      acc.push(`<button type="button" class="al-ic rojo" title="Liberar el asiento" aria-label="Liberar" onclick="alReservaLiberar(${v.nro})"><i class="ti ti-lock-open"></i></button>`);
    }
    return `<tr class="${e}">
      <td class="al-t-n"><b>${alNro(v.nro)}</b>${v.cambios && v.cambios.length ? `<small title="Cambiado">cambiado</small>` : ""}</td>
      <td><b>${alDM(v.fecha)}</b> ${v.sale || v.hora}<small>${trEsc(v.tramo || "")}${v.coche && !alEsAgencia() ? " · coche " + trEsc(v.coche) : ""}</small></td>
      <td>${trEsc(v.origen)} → ${trEsc(v.destino)}</td>
      <td class="al-t-c">${v.asiento === "P" ? "P" : v.asiento}</td>
      <td><b>${trEsc(v.nombre)}</b><small>${v.mig ? trEsc(v.tipoDoc) : "CI"} ${trEsc(v.doc)}</small></td>
      <td class="al-t-m">${fmtNum(v.total)}${v.devuelto != null ? `<small>devuelto ${fmtNum(v.devuelto)}</small>` : ""}</td>
      <td><span class="al-est ${e}">${AL_ESTADOS[e] || e}</span>${e === "reserva" ? `<small>vence ${alDM(v.vence.slice(0, 10))} ${v.vence.slice(11)}</small>` : ""}</td>
      <td class="al-t-a">${acc.join("")}</td></tr>`;
  };
  content.innerHTML = alShell(`
    <div class="al-vista">
      <div class="al-v-cab"><h1 class="al-d">Pasajes</h1><span>Buscá un boleto o una reserva para reimprimir, cambiar, devolver o anular.</span></div>
      <div class="al-busca al-busca-pas"><i class="ti ti-search" aria-hidden="true"></i>
        <input id="al-pas-q" type="search" autocomplete="off" value="${trEsc(al.pas.q)}" placeholder="Número de boleto, documento, nombre, destino o fecha" oninput="al.pas.q=this.value;alPasRefrescar()" aria-label="Buscar pasajes"></div>
      <div class="al-chips al-pas-est" role="group" aria-label="Estado">
        <button type="button" class="al-chip ${!est ? "on" : ""}" onclick="al.pas.estado='';alPasRefrescar()">Todos <small>${todas.length}</small></button>
        ${["vendido", "reserva", "vencida", "devuelto", "anulado", "liberada"].filter(k => cuenta[k]).map(k => `<button type="button" class="al-chip ${est === k ? "on" : ""}" onclick="al.pas.estado='${k}';alPasRefrescar()">${AL_ESTADOS[k]}s <small>${cuenta[k]}</small></button>`).join("")}
      </div>
      <div id="al-pas-lista">${lista.length ? `<div class="al-tabla-w"><table class="al-tabla">
        <thead><tr><th>Boleto</th><th>Viaje</th><th>Tramo</th><th class="al-t-c">Asiento</th><th>Pasajero</th><th class="al-t-m">Gs.</th><th>Estado</th><th></th></tr></thead>
        <tbody>${lista.slice(0, 200).map(fila).join("")}</tbody></table></div>`
        : `<div class="al-vacio"><i class="ti ti-receipt-off"></i><b>${todas.length ? "No hay pasajes con esa búsqueda" : "Todavía no hay pasajes vendidos"}</b><span>Las ventas de prueba quedan en este navegador.</span></div>`}</div>
      ${todas.length ? `<p class="al-nota"><button type="button" class="al-link" onclick="alBorrar()">Borrar todas las ventas de prueba</button></p>` : ""}
    </div>`, animar);
}
function alPasRefrescar() {
  const q = document.getElementById("al-pas-q"), pos = q ? q.selectionStart : 0, foco = document.activeElement === q;
  alVistaPasajes(false);
  if (foco) { const n = document.getElementById("al-pas-q"); n.focus(); n.setSelectionRange(pos, pos); }
}
function alReimprimir(nro) {
  const v = alGuardado().ventas.find(x => x.nro === nro);
  if (v) { alImprimir(alBoletoHTML(Object.assign({}, v, { _reimpresion: true }))); toast(`Reimprimiendo el boleto ${alNro(nro)}`, "success"); }
}
function alAnular(nro) {
  const g = alGuardado(), v = g.ventas.find(x => x.nro === nro);
  if (!v || !confirm(`¿Anular el boleto ${alNro(nro)} de ${v.nombre}?\n\nSe devuelve todo (${alGs(v.total)}) y el asiento queda libre. Se usa para errores del mismo día.`)) return;
  const ahora = alAhoraISO();
  v.estado = "anulado"; v.anulado_en = ahora; v.anulado_por = alVendedor();
  v.movs.push({ t: "anulacion", el: ahora, monto: -v.total, pago: v.pago, vendedor: alVendedor() });
  alGuardar(g); toast(`Boleto ${alNro(nro)} anulado`, "success"); alRender(false);
}
function alDevolver(nro) {
  const v = alGuardado().ventas.find(x => x.nro === nro);
  if (!v) return;
  const sug = Math.round(v.total * (1 - AL_RETENCION) / 1000) * 1000;
  alModal({ titulo: `Devolver el boleto ${alNro(nro)}`, ancho: 480, cuerpo: `
    <p class="al-m-txt"><b>${trEsc(v.nombre)}</b> · ${alDM(v.fecha)} ${v.sale || v.hora}, ${trEsc(v.origen)} → ${trEsc(v.destino)}, ${v.asiento === "P" ? "parado" : "asiento " + v.asiento}.<br>Pagó ${alGs(v.total)} con ${(AL_PAGOS.find(p => p[0] === v.pago) || AL_PAGOS[0])[1].toLowerCase()}.</p>
    <label class="al-campo"><span>Se le devuelve (Gs.)</span><input id="al-dev-m" inputmode="numeric" value="${fmtNum(sug)}" autofocus oninput="this.value=this.value.replace(/\\D/g,'')?fmtNum(+this.value.replace(/\\D/g,'')):''"></label>
    <p class="al-hint">Sugerido: el total menos ${Math.round(AL_RETENCION * 100)} % de retención (de ejemplo, hasta que se defina la regla).</p>`,
    pie: `<button type="button" class="al-sec" onclick="alModalCerrar()">Cancelar</button><button type="button" class="al-btn-r" onclick="alDevolverOk(${nro})"><i class="ti ti-receipt-refund"></i> Devolver</button>` });
}
function alDevolverOk(nro) {
  const m = +String(document.getElementById("al-dev-m")?.value || "").replace(/\D/g, "");
  const g = alGuardado(), v = g.ventas.find(x => x.nro === nro);
  if (!v) return;
  if (!(m >= 0) || m > v.total) { toast("Lo que se devuelve no puede ser más de lo que pagó", "error"); return; }
  const ahora = alAhoraISO();
  v.estado = "devuelto"; v.devuelto = m; v.devuelto_en = ahora; v.devuelto_por = alVendedor();
  v.movs.push({ t: "devolucion", el: ahora, monto: -m, pago: "efectivo", vendedor: alVendedor() });
  alGuardar(g); alModalCerrar(); toast(`Boleto ${alNro(nro)} devuelto: ${alGs(m)}`, "success"); alRender(false);
}
async function alIrAViaje(v) {
  const i = Math.round((alDeISO(v.fecha) - alFechaDe(0)) / 864e5);
  if (i < 0) { toast("Ese viaje ya pasó", "error"); return false; }
  al.dia = i; al.vista = "vender";
  if (!al.datos[v.fecha]) { al.cargando = true; alRender(false); await alTraer(); }
  al.cor = v.cor; al.lado = v.lado;
  const lista = alServicios().lista, k = lista.findIndex(x => x.clave === v.servicio);
  if (k < 0) { toast("Ese servicio ya no está en el tráfico de ese día: elegí otro", "error"); al.dep = 0; return true; }
  al.dep = k;
  const cam = alCamino(lista[k]);
  al.sube = alIdxDe(cam, v.sube, 0); al.baja = alIdxDe(cam, v.baja, cam.length - 1);
  return true;
}
async function alCambiar(nro) {
  const v = alGuardado().ventas.find(x => x.nro === nro);
  if (!v) return;
  alLimpiarVenta();
  al.cambio = nro; al.tarifa = v.tarifa || "general";
  al.p = Object.assign(AL_PVACIO(), v.mig || {}, { doc: v.doc, nombre: v.mig ? "" : v.nombre, tipoDoc: v.tipoDocId || "CI" });
  await alIrAViaje(v);
  al.sel = null;
  alRender(true);
}
async function alIrAReserva(nro) {
  const v = alGuardado().ventas.find(x => x.nro === nro);
  if (!v) return;
  alLimpiarVenta();
  if (!(await alIrAViaje(v))) return;
  alRender(true);
  alReservaCobrar(nro);
}
function alBorrar() {
  if (!confirm("¿Borrar todas las ventas, reservas y cierres de caja de prueba guardados en esta computadora?")) return;
  try { localStorage.removeItem("alpha_maqueta_v3"); } catch (e) {}
  alLimpiarVenta();
  alRender(false);
  toast("Ventas de prueba borradas", "success");
}

// ════════════════════════════════════════════════════════════════════════════
// MANIFIESTO: los pasajeros de un servicio
// ════════════════════════════════════════════════════════════════════════════
function alManServicios() {
  return alTodasSalidas().map(({ c, l, k }) => alServiciosDe(c, l)[k]);
}
function alManifiestoDatos(sv, fecha) {
  const pas = alGuardado().ventas.filter(v => v.fecha === fecha && v.servicio === sv.clave && (v.estado === "vendido" || alReservaViva(v)));
  const cam = alCamino(sv);
  pas.sort((a, b) => (a.asiento === "P") - (b.asiento === "P") || (+a.asiento || 0) - (+b.asiento || 0) || alIdxDe(cam, a.sube, 0) - alIdxDe(cam, b.sube, 0));
  return pas;
}
async function alVistaManifiesto(animar) {
  if (!al.cfg) await alCfgTraer();
  if (!alHoyDatos()) { al.cargando = true; alShellCargando(animar); await alTraer(); }
  const fecha = alISO(alFechaDe(al.dia)), svs = alManServicios();
  const actual = alServ();
  if (!svs.some(s => s.clave === al.man.clave)) al.man.clave = (actual && svs.some(s => s.clave === actual.clave)) ? actual.clave : (svs[0]?.clave || "");
  const sv = svs.find(s => s.clave === al.man.clave);
  let cuerpo;
  if (!sv) cuerpo = `<div class="al-vacio"><i class="ti ti-calendar-off"></i><b>No hay servicios este día</b></div>`;
  else {
    const pas = alManifiestoDatos(sv, fecha), pl = alPlano(sv), asi = alAsientos(pl);
    const vend = pas.filter(v => v.estado === "vendido"), res = pas.filter(v => v.estado === "reserva");
    const cam = alCamino(sv);
    const baja = {}; vend.forEach(v => { baja[v.baja] = (baja[v.baja] || 0) + 1; });
    cuerpo = `
      <div class="al-man-res">
        <div><span>Pasajeros</span><b class="al-d">${vend.length}</b></div>
        <div><span>Reservas</span><b class="al-d">${res.length}</b></div>
        <div><span>Asientos</span><b class="al-d">${asi.length}${pl.parados ? ` <small>+ ${pl.parados} parados</small>` : ""}</b></div>
        <div><span>Recaudado</span><b class="al-d">${alGs(vend.reduce((a, v) => a + v.total, 0))}</b></div>
        ${cam.length > 2 ? `<div class="al-man-baja"><span>Bajan en</span><p>${cam.slice(1).map(p => `${trEsc(p.nombre)}: <b>${baja[p.nombre] || 0}</b>`).join(" · ")}</p></div>` : ""}
      </div>
      ${pas.length ? `<div class="al-tabla-w"><table class="al-tabla">
        <thead><tr><th class="al-t-c">Asiento</th><th>Pasajero</th><th>Documento</th><th>Sube</th><th>Baja</th>${sv.intl ? "<th>Nacionalidad</th><th>Nacimiento</th><th>Sexo</th>" : ""}<th>Boleto</th><th>Estado</th></tr></thead>
        <tbody>${pas.map(v => `<tr class="${v.estado}">
          <td class="al-t-c"><b>${v.asiento}</b></td><td><b>${trEsc(v.nombre)}</b></td><td>${v.mig ? trEsc(v.tipoDoc) : "CI"} ${trEsc(v.doc)}</td>
          <td>${trEsc(v.sube)}</td><td>${trEsc(v.baja)}</td>
          ${sv.intl ? `<td>${trEsc(v.mig?.nacionalidad || "")}</td><td>${v.mig?.nac ? alDM(v.mig.nac) + "/" + v.mig.nac.slice(0, 4) : ""}</td><td>${trEsc(v.mig?.sexo || "")}</td>` : ""}
          <td>${alNro(v.nro)}</td><td><span class="al-est ${v.estado}">${AL_ESTADOS[v.estado]}</span></td></tr>`).join("")}</tbody></table></div>`
        : `<div class="al-vacio"><i class="ti ti-users"></i><b>Todavía no hay pasajeros en este servicio</b><span>Las ventas de prueba quedan en este navegador.</span></div>`}`;
  }
  content.innerHTML = alShell(`
    <div class="al-vista">
      <div class="al-v-cab"><h1 class="al-d">Manifiesto</h1><span>La lista de pasajeros de cada servicio, para el guarda y para migraciones.</span></div>
      <div class="al-filtros"><div class="al-dias" role="group" aria-label="Día del viaje">${alChipsDias()}</div></div>
      <div class="al-man-sel">
        <label class="al-campo"><span>Servicio</span><select onchange="al.man.clave=this.value;alVistaManifiesto(false)">${svs.map(s => `<option value="${trEsc(s.clave)}" ${s.clave === al.man.clave ? "selected" : ""}>${s.hora} · ${trEsc(s.origen_nombre)} → ${trEsc(s.llega_nombre)} · ${trEsc(s.cod)}${s.coche ? " · coche " + trEsc(s.coche) : ""}</option>`).join("")}</select></label>
        ${sv ? `<button type="button" class="al-btn-r" onclick="alManImprimir()"><i class="ti ti-printer"></i> Imprimir${sv.intl ? " (para migraciones)" : ""}</button>` : ""}
      </div>
      ${sv ? `<p class="al-nota">${alDiaTxt(alFechaDe(al.dia))} · ${sv.coche ? "Coche " + trEsc(sv.coche) + (sv.modelo ? ", " + trEsc(sv.modelo) : "") : "Coche a confirmar"}${sv.tripulacion.length ? " · Tripulación: " + sv.tripulacion.map(trEsc).join(" y ") : ""}</p>` : ""}
      ${cuerpo}
    </div>`, animar);
}
function alShellCargando(animar) {
  content.innerHTML = alShell(`<div class="al-vacio"><i class="ti ti-loader-2"></i><b>Trayendo los datos…</b></div>`, animar);
}
function alManImprimir() {
  const fecha = alISO(alFechaDe(al.dia)), sv = alManServicios().find(s => s.clave === al.man.clave);
  if (!sv) return;
  const pas = alManifiestoDatos(sv, fecha).filter(v => v.estado === "vendido"), e = trEsc, intl = sv.intl;
  const filas = pas.map((v, i) => `<tr><td>${i + 1}</td><td class="c"><b>${v.asiento}</b></td><td><b>${e(v.mig ? v.mig.apellidos : v.nombre)}</b>${v.mig ? `<br>${e(v.mig.nombres)}` : ""}</td>
    <td>${v.mig ? e(v.tipoDoc) : "CI"} ${e(v.doc)}</td>${intl ? `<td>${e(v.mig?.nacionalidad || "")}</td><td>${v.mig?.nac ? v.mig.nac.split("-").reverse().join("/") : ""}</td><td class="c">${e(v.mig?.sexo || "")}</td><td>${e(v.mig?.residencia || "")}</td>` : ""}
    <td>${e(v.sube)}</td><td>${e(v.baja)}</td></tr>`).join("");
  const html = `<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Manifiesto ${fecha} ${sv.hora}</title>
<style>@page{size:A4 ${intl ? "landscape" : "portrait"};margin:12mm}*{box-sizing:border-box}body{margin:0;font-family:Arial,sans-serif;color:#000;font-size:11px}
.cab{display:flex;justify-content:space-between;align-items:flex-end;border-bottom:2px solid #000;padding-bottom:6px;margin-bottom:8px}
h1{font-size:18px;margin:0}.cab span{font-size:11px}.dat{display:flex;flex-wrap:wrap;gap:4px 22px;margin-bottom:8px;font-size:11.5px}
table{width:100%;border-collapse:collapse}th,td{border:1px solid #999;padding:4px 5px;text-align:left;vertical-align:top}th{background:#eee;font-size:10px;text-transform:uppercase}
.c{text-align:center}.firmas{display:flex;gap:40px;margin-top:40px}.firmas div{flex:1;border-top:1px solid #000;padding-top:4px;text-align:center}
.maq{margin-top:12px;font-size:9.5px;color:#555;text-align:center}</style></head><body>
<div class="cab"><div><b>LA SANTANIANA</b><h1>Manifiesto de pasajeros${intl ? " · Viaje internacional" : ""}</h1></div><span>Impreso ${alAhoraISO().replace("T", " ")}</span></div>
<div class="dat"><span><b>Fecha:</b> ${alDiaTxt(alDeISO(fecha))}</span><span><b>Sale:</b> ${sv.hora}</span><span><b>Servicio:</b> ${e(sv.cod)}</span>
<span><b>De:</b> ${e(sv.origen_nombre)} <b>a</b> ${e(sv.llega_nombre)}</span><span><b>Coche:</b> ${e(sv.coche || "a confirmar")}${sv.modelo ? " (" + e(sv.modelo) + ")" : ""}</span>
<span><b>Tripulación:</b> ${e(sv.tripulacion.join(" y ") || "—")}</span><span><b>Pasajeros:</b> ${pas.length}</span></div>
<table><thead><tr><th>#</th><th class="c">Asiento</th><th>${intl ? "Apellidos y nombres" : "Pasajero"}</th><th>Documento</th>${intl ? "<th>Nacionalidad</th><th>Nacimiento</th><th>Sexo</th><th>Reside en</th>" : ""}<th>Sube</th><th>Baja</th></tr></thead>
<tbody>${filas || `<tr><td colspan="${intl ? 10 : 6}" class="c">Sin pasajeros</td></tr>`}</tbody></table>
<div class="firmas"><div>Chofer</div><div>Guarda</div><div>Boletería</div></div>
<div class="maq">Maqueta de Alpha: sin valor fiscal</div></body></html>`;
  alImprimir(html, "210mm");
}

// ════════════════════════════════════════════════════════════════════════════
// CAJA: lo que entró y salió por vendedor, y el cierre
// ════════════════════════════════════════════════════════════════════════════
const AL_MOV_TXT = { venta: "Venta", cobro: "Cobro de reserva", cambio: "Diferencia por cambio", devolucion: "Devolución", anulacion: "Anulación" };
function alMovs(g) {
  const out = [];
  (g || alGuardado()).ventas.forEach(v => (v.movs || []).forEach(m => out.push(Object.assign({ nro: v.nro, nombre: v.nombre, destino: v.destino, origen: v.origen }, m))));
  return out.sort((a, b) => a.el.localeCompare(b.el));
}
function alVistaCaja(animar) {
  const g = alGuardado(), fecha = al.caja.fecha || alISO(new Date());
  const movsDia = alMovs(g).filter(m => m.el.slice(0, 10) === fecha);
  const vendedores = alEsAgencia() ? [alVendedor()] : [...new Set(movsDia.map(m => m.vendedor).concat([alVendedor()]))].sort();
  if (!al.caja.vendedor || !vendedores.includes(al.caja.vendedor)) al.caja.vendedor = alVendedor();
  const vend = al.caja.vendedor;
  const cierres = g.cierres.filter(c => c.fecha === fecha && c.vendedor === vend).sort((a, b) => a.hasta.localeCompare(b.hasta));
  const ultimo = cierres.length ? cierres[cierres.length - 1].hasta : "";
  const movs = movsDia.filter(m => m.vendedor === vend);
  const abiertos = movs.filter(m => m.el > ultimo);
  const tot = alTotales(abiertos);
  const fila = m => `<tr class="${m.el <= ultimo ? "cerrado" : ""}"><td>${m.el.slice(11, 16)}</td><td>${AL_MOV_TXT[m.t] || m.t}</td><td>${alNro(m.nro)}</td><td>${trEsc(m.nombre)}<small>${trEsc(m.origen)} → ${trEsc(m.destino)}</small></td>
    <td>${(AL_PAGOS.find(p => p[0] === m.pago) || ["", m.pago || ""])[1]}</td><td class="al-t-m ${m.monto < 0 ? "neg" : ""}">${m.monto < 0 ? "−" : ""}${fmtNum(Math.abs(m.monto))}</td></tr>`;
  content.innerHTML = alShell(`
    <div class="al-vista">
      <div class="al-v-cab"><h1 class="al-d">Caja</h1><span>Lo que cobró y devolvió cada vendedor, y el cierre del turno.</span></div>
      <div class="al-man-sel">
        <label class="al-campo"><span>Día</span><input type="date" value="${fecha}" max="${alISO(new Date())}" onchange="al.caja.fecha=this.value;alVistaCaja(false)"></label>
        <label class="al-campo"><span>Vendedor</span><select onchange="al.caja.vendedor=this.value;alVistaCaja(false)">${vendedores.map(x => `<option ${x === vend ? "selected" : ""}>${trEsc(x)}</option>`).join("")}</select></label>
        ${abiertos.length ? `<button type="button" class="al-btn-r" onclick="alCerrarCaja()"><i class="ti ti-lock"></i> Cerrar la caja</button>` : ""}
      </div>
      <div class="al-man-res">
        ${AL_PAGOS.map(([k, t]) => `<div><span>${t}</span><b class="al-d">${alGs(tot.pago[k] || 0)}</b></div>`).join("")}
        <div><span>Devoluciones y anulaciones</span><b class="al-d neg">${tot.salidas ? "− " : ""}${alGs(tot.salidas)}</b></div>
        <div class="fuerte"><span>Efectivo en caja</span><b class="al-d">${alGs(tot.efectivoNeto)}</b></div>
        <div><span>Boletos</span><b class="al-d">${tot.boletos}</b></div>
      </div>
      ${ultimo ? `<p class="al-nota">Última caja cerrada a las ${ultimo.slice(11, 16)}. Arriba se suma lo que entró después.</p>` : ""}
      ${movs.length ? `<div class="al-tabla-w"><table class="al-tabla">
        <thead><tr><th>Hora</th><th>Movimiento</th><th>Boleto</th><th>Pasajero</th><th>Forma de pago</th><th class="al-t-m">Gs.</th></tr></thead>
        <tbody>${movs.slice().reverse().map(fila).join("")}</tbody></table></div>`
        : `<div class="al-vacio"><i class="ti ti-cash-off"></i><b>Sin movimientos ese día</b></div>`}
      ${cierres.length ? `<h2 class="al-d al-h2">Cierres del día</h2><div class="al-cierres">${cierres.map((c, i) => `<div class="al-cierre"><b>Cierre ${i + 1}</b><span>a las ${c.hasta.slice(11, 16)} · ${c.tot.boletos} boletos · efectivo ${alGs(c.tot.efectivoNeto)}</span><button type="button" class="al-link" onclick="alCierreImprimir('${c.id}')">Reimprimir</button></div>`).join("")}</div>` : ""}
    </div>`, animar);
}
function alTotales(movs) {
  const t = { pago: {}, salidas: 0, efectivoNeto: 0, boletos: 0, entradas: 0 };
  movs.forEach(m => {
    if (m.monto >= 0) { t.pago[m.pago] = (t.pago[m.pago] || 0) + m.monto; t.entradas += m.monto; }
    else t.salidas += -m.monto;
    if (m.pago === "efectivo" || m.monto < 0) t.efectivoNeto += m.monto;
    if (m.t === "venta" || m.t === "cobro") t.boletos += 1;
  });
  return t;
}
function alCerrarCaja() {
  const g = alGuardado(), fecha = al.caja.fecha || alISO(new Date()), vend = al.caja.vendedor;
  const prev = g.cierres.filter(c => c.fecha === fecha && c.vendedor === vend).map(c => c.hasta).sort().pop() || "";
  const ahora = alAhoraISO();
  const hasta = fecha === ahora.slice(0, 10) ? ahora : `${fecha}T23:59`;
  const movs = alMovs(g).filter(m => m.el.slice(0, 10) === fecha && m.vendedor === vend && m.el > prev && m.el <= hasta);
  if (!movs.length) { toast("No hay nada para cerrar", "error"); return; }
  const tot = alTotales(movs);
  if (!confirm(`¿Cerrar la caja de ${vend}?\n\n${tot.boletos} boletos · efectivo en caja ${alGs(tot.efectivoNeto)}`)) return;
  const c = { id: "c" + Date.now(), fecha, vendedor: vend, desde: prev, hasta, tot, movs: movs.length, el: ahora };
  g.cierres.push(c); alGuardar(g);
  alCierreImprimir(c.id);
  toast("Caja cerrada", "success");
  alVistaCaja(false);
}
function alCierreImprimir(id) {
  const g = alGuardado(), c = g.cierres.find(x => x.id === id);
  if (!c) return;
  const movs = alMovs(g).filter(m => m.el.slice(0, 10) === c.fecha && m.vendedor === c.vendedor && m.el > c.desde && m.el <= c.hasta);
  const t = c.tot, fl = (a, b, f) => `<div class="r ${f || ""}"><span>${a}</span><b>${b}</b></div>`;
  const html = `<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Cierre de caja</title>
<style>@page{size:80mm auto;margin:0}*{box-sizing:border-box}body{margin:0;font-family:Arial,sans-serif;color:#000}
article{width:80mm;padding:5mm 4mm}h1{font-size:18px;margin:4px 0 2px}.s{font-size:11px}.r{display:flex;justify-content:space-between;font-size:12.5px;padding:3px 0;border-bottom:1px dashed #000}
.r.f{font-size:15px;font-weight:900;border-bottom:2px solid #000}.m{font-size:10.5px;margin-top:8px}.m div{display:flex;justify-content:space-between;gap:6px}
.fi{margin-top:30px;border-top:1px solid #000;text-align:center;font-size:11px;padding-top:3px}.maq{margin-top:8px;font-size:9.5px;text-align:center}</style></head><body><article>
<b>LA SANTANIANA</b><h1>Cierre de caja</h1><div class="s">${trEsc(c.vendedor)} · ${alDM(c.fecha)}/${c.fecha.slice(0, 4)} · ${c.desde ? "desde las " + c.desde.slice(11, 16) + " " : ""}hasta las ${c.hasta.slice(11, 16)}</div><br>
${AL_PAGOS.map(([k, n]) => fl(n, fmtNum(t.pago[k] || 0))).join("")}
${fl("Devoluciones y anulaciones", "− " + fmtNum(t.salidas))}
${fl("Boletos", t.boletos)}
${fl("Efectivo en caja", fmtNum(t.efectivoNeto), "f")}
<div class="m">${movs.map(m => `<div><span>${m.el.slice(11, 16)} ${AL_MOV_TXT[m.t] || m.t} ${alNro(m.nro)}</span><span>${m.monto < 0 ? "−" : ""}${fmtNum(Math.abs(m.monto))}</span></div>`).join("")}</div>
<div class="fi">Firma del vendedor</div><div class="fi">Recibió</div><div class="maq">Maqueta de Alpha: sin valor fiscal</div></article></body></html>`;
  alImprimir(html);
}

// ════════════════════════════════════════════════════════════════════════════
// TARIFAS: recorridos (paradas), precio por tramo y descuentos — en la base
// ════════════════════════════════════════════════════════════════════════════
async function alVistaTarifas(animar) {
  if (!al.cfg) { alShellCargando(animar); await alCfgTraer(); }
  const cfg = al.cfg, cors = cfg.corredores || [];
  if (!al.tar.cor || !cors.some(c => c.clave === al.tar.cor)) al.tar.cor = (cors.find(c => c.clave === al.cor) || cors[0] || {}).clave || "";
  const cor = al.tar.cor;
  if (!al.tar.rec) al.tar.rec = JSON.parse(JSON.stringify(cfg.recorridos || {}));
  if (!al.tar.pre) al.tar.pre = JSON.parse(JSON.stringify(cfg.tarifas || {}));
  if (!al.tar.des) al.tar.des = JSON.parse(JSON.stringify(alDescuentos()));
  const recs = al.tar.rec[cor] || [];
  const c = cors.find(x => x.clave === cor) || { titulo: cor };
  // Las paradas de todos los recorridos del corredor, en orden
  const paradas = [];
  recs.forEach(r => r.paradas.forEach(p => { if (p.nombre.trim() && !paradas.some(x => alNorm(x) === alNorm(p.nombre))) paradas.push(p.nombre.trim()); }));
  const pares = [];
  recs.forEach(r => { const ps = r.paradas.map(p => p.nombre.trim()).filter(Boolean);
    ps.forEach((a, i) => ps.slice(i + 1).forEach(b => { if (!pares.some(([x, y]) => alNorm(x) === alNorm(a) && alNorm(y) === alNorm(b))) pares.push([a, b]); })); });
  if (!pares.length && c.titulo) pares.push(["Asunción", c.titulo]);
  const pre = al.tar.pre[cor] || {};
  const precioDe = (a, b, cl) => { const k = Object.keys(pre).find(k => { const [x, y] = k.split("|"); return (alNorm(x) === alNorm(a) && alNorm(y) === alNorm(b)) || (alNorm(x) === alNorm(b) && alNorm(y) === alNorm(a)); }); return k && pre[k][cl] ? fmtNum(pre[k][cl]) : ""; };
  const sinPrecio = pares.filter(([a, b]) => !precioDe(a, b, "CO")).length;
  content.innerHTML = alShell(`
    <div class="al-vista">
      <div class="al-v-cab"><h1 class="al-d">Tarifas</h1><span>El recorrido de cada corredor con sus paradas, el precio de cada tramo y los descuentos. Se guarda en la base y vale para todas las computadoras.</span></div>
      <div class="al-dias al-corredores" role="group" aria-label="Corredor">${cors.map(x => `<button type="button" class="al-chip ${x.clave === cor ? "on" : ""}" onclick="al.tar.cor='${x.clave.replace(/'/g, "\\'")}';alVistaTarifas(false)">${x.tipo === "internacional" ? "Asunción ⇄ " : "Asunción ⇄ "}${trEsc(x.titulo)}${x.tipo === "internacional" ? ' <i class="ti ti-world"></i>' : ""}</button>`).join("")}</div>

      <section class="al-card">
        <div class="al-card-cab"><h2 class="al-d">Recorridos</h2><span>Las paradas en orden de ida, desde Asunción. Cada recorrido vale para las salidas del tráfico que dicen ese texto (por ejemplo «X 25» o «X CHACO»); si lo dejás vacío, vale para todas las demás. Las salidas sin recorrido se venden de punta a punta.</span></div>
        ${recs.length ? recs.map((r, ri) => `
          <div class="al-rec">
            <div class="al-rec-cab">
              <label class="al-campo"><span>Nombre</span><input value="${trEsc(r.nombre || "")}" placeholder="Por Ruta 3" oninput="al.tar.rec['${cor}'][${ri}].nombre=this.value"></label>
              <label class="al-campo"><span>Se usa en las salidas que dicen</span><input value="${trEsc(r.variante || "")}" placeholder="Vacío = todas las demás salidas" oninput="al.tar.rec['${cor}'][${ri}].variante=this.value.toUpperCase()"></label>
              <button type="button" class="al-ic rojo" title="Borrar este recorrido" onclick="alRecBorrar(${ri})"><i class="ti ti-trash"></i></button>
            </div>
            <ol class="al-rec-ps">${r.paradas.map((p, pi) => `
              <li><span class="al-rec-n">${pi + 1}</span>
                <input class="al-in" value="${trEsc(p.nombre)}" placeholder="Nombre de la parada" oninput="al.tar.rec['${cor}'][${ri}].paradas[${pi}].nombre=this.value" aria-label="Parada ${pi + 1}">
                <input class="al-in min" value="${p.min ?? ""}" inputmode="numeric" placeholder="min" title="Minutos desde la primera parada (opcional)" oninput="al.tar.rec['${cor}'][${ri}].paradas[${pi}].min=this.value.replace(/\\D/g,'')===''?null:+this.value.replace(/\\D/g,'')" aria-label="Minutos desde la salida">
                <button type="button" class="al-ic" ${pi === 0 ? "disabled" : ""} onclick="alParMover(${ri},${pi},-1)" aria-label="Subir"><i class="ti ti-arrow-up"></i></button>
                <button type="button" class="al-ic" ${pi === r.paradas.length - 1 ? "disabled" : ""} onclick="alParMover(${ri},${pi},1)" aria-label="Bajar"><i class="ti ti-arrow-down"></i></button>
                <button type="button" class="al-ic rojo" ${r.paradas.length <= 2 ? "disabled" : ""} onclick="alParBorrar(${ri},${pi})" aria-label="Sacar la parada"><i class="ti ti-x"></i></button>
              </li>`).join("")}</ol>
            <button type="button" class="al-link" onclick="alParAgregar(${ri})">+ Agregar parada</button>
          </div>`).join("") : `<p class="al-nota">Este corredor todavía no tiene recorrido: se vende solo de punta a punta.</p>`}
        <div class="al-card-pie">
          <button type="button" class="al-sec" onclick="alRecAgregar()"><i class="ti ti-route"></i> ${recs.length ? "Otro recorrido" : "Armar el recorrido"}</button>
          <button type="button" class="al-btn-r" onclick="alRecGuardar()"><i class="ti ti-device-floppy"></i> Guardar recorridos</button>
        </div>
      </section>

      <section class="al-card">
        <div class="al-card-cab"><h2 class="al-d">Precios por tramo</h2><span>Lo mismo de ida que de vuelta. Si un tramo intermedio queda vacío, no se puede vender; de punta a punta se usa un precio de ejemplo hasta que lo cargues.${sinPrecio ? ` <b>${sinPrecio} sin precio.</b>` : ""} Si la cama queda vacía, se cobra 20 % más que el diferencial.</span></div>
        <div class="al-tabla-w"><table class="al-tabla al-precios">
          <thead><tr><th>Desde</th><th>Hasta</th><th class="al-t-m">Diferencial (Gs.)</th><th class="al-t-m">Cama (Gs.)</th></tr></thead>
          <tbody>${pares.map(([a, b]) => `<tr><td>${trEsc(a)}</td><td>${trEsc(b)}</td>
            ${["CO", "CA"].map(cl => `<td class="al-t-m"><input class="al-in num" inputmode="numeric" value="${precioDe(a, b, cl)}" placeholder="—" oninput="alPrecioPoner('${trEsc(a).replace(/'/g, "\\'")}','${trEsc(b).replace(/'/g, "\\'")}','${cl}',this)" aria-label="${cl === "CO" ? "Diferencial" : "Cama"} de ${trEsc(a)} a ${trEsc(b)}"></td>`).join("")}</tr>`).join("")}</tbody></table></div>
        <div class="al-card-pie"><button type="button" class="al-btn-r" onclick="alPreGuardar()"><i class="ti ti-device-floppy"></i> Guardar precios</button></div>
      </section>

      <section class="al-card">
        <div class="al-card-cab"><h2 class="al-d">Descuentos</h2><span>Las tarifas que se eligen al vender. «General» es el precio lleno.</span></div>
        <div class="al-des">${al.tar.des.map((d, i) => `
          <div class="al-des-f"><input class="al-in" value="${trEsc(d.nombre)}" ${d.id === "general" ? "readonly" : ""} oninput="al.tar.des[${i}].nombre=this.value" aria-label="Nombre">
            <label><input class="al-in num" inputmode="numeric" value="${Math.round((1 - d.factor) * 100)}" ${d.id === "general" ? "readonly" : ""} oninput="al.tar.des[${i}].factor=1-Math.min(100,+this.value.replace(/\\D/g,'')||0)/100" aria-label="Porcentaje de descuento"> % de descuento</label>
            ${d.id !== "general" ? `<button type="button" class="al-ic rojo" onclick="al.tar.des.splice(${i},1);alVistaTarifas(false)" aria-label="Sacar"><i class="ti ti-x"></i></button>` : ""}</div>`).join("")}</div>
        <div class="al-card-pie">
          <button type="button" class="al-sec" onclick="al.tar.des.push({id:'d'+Date.now(),nombre:'',factor:1});alVistaTarifas(false)"><i class="ti ti-plus"></i> Otro descuento</button>
          <button type="button" class="al-btn-r" onclick="alDesGuardar()"><i class="ti ti-device-floppy"></i> Guardar descuentos</button>
        </div>
      </section>
    </div>`, animar);
}
function alRecAgregar() {
  const cor = al.tar.cor, c = (al.cfg.corredores || []).find(x => x.clave === cor) || { titulo: "" };
  al.tar.rec[cor] = al.tar.rec[cor] || [];
  const prim = al.tar.rec[cor][0];
  al.tar.rec[cor].push({ nombre: prim ? "Otro recorrido" : "Recorrido principal", variante: prim ? "X " : "",
    paradas: prim ? prim.paradas.map(p => ({ nombre: p.nombre, min: null })) : [{ nombre: "Asunción", min: 0 }, { nombre: c.titulo, min: null }] });
  alVistaTarifas(false);
}
function alRecBorrar(ri) { if (!confirm("¿Borrar este recorrido?")) return; al.tar.rec[al.tar.cor].splice(ri, 1); alVistaTarifas(false); }
function alParAgregar(ri) { const ps = al.tar.rec[al.tar.cor][ri].paradas; ps.splice(ps.length - 1, 0, { nombre: "", min: null }); alVistaTarifas(false); setTimeout(() => { const ins = document.querySelectorAll(".al-rec")[ri]?.querySelectorAll(".al-rec-ps li input:first-of-type"); ins && ins[ins.length - 2]?.focus(); }, 30); }
function alParBorrar(ri, pi) { al.tar.rec[al.tar.cor][ri].paradas.splice(pi, 1); alVistaTarifas(false); }
function alParMover(ri, pi, d) { const ps = al.tar.rec[al.tar.cor][ri].paradas; const [x] = ps.splice(pi, 1); ps.splice(pi + d, 0, x); alVistaTarifas(false); }
async function alRecGuardar() {
  const rec = JSON.parse(JSON.stringify(al.tar.rec));
  Object.keys(rec).forEach(k => { rec[k] = rec[k].map(r => Object.assign(r, { paradas: r.paradas.filter(p => p.nombre.trim()).map(p => ({ nombre: p.nombre.trim(), min: p.min == null || p.min === "" ? null : +p.min })) })); if (!rec[k].length) delete rec[k]; });
  if (await alCfgGuardar("recorridos", rec)) { al.tar.rec = JSON.parse(JSON.stringify(rec)); toast("Recorridos guardados", "success"); alVistaTarifas(false); }
}
function alPrecioPoner(a, b, cl, inp) {
  const d = inp.value.replace(/\D/g, "");
  inp.value = d ? fmtNum(+d) : "";
  const cor = al.tar.cor, pre = al.tar.pre[cor] = al.tar.pre[cor] || {};
  let k = Object.keys(pre).find(k => { const [x, y] = k.split("|"); return (alNorm(x) === alNorm(a) && alNorm(y) === alNorm(b)) || (alNorm(x) === alNorm(b) && alNorm(y) === alNorm(a)); });
  if (!k) { k = alParKey(a, b); pre[k] = {}; }
  if (d) pre[k][cl] = +d; else delete pre[k][cl];
}
async function alPreGuardar() {
  const pre = JSON.parse(JSON.stringify(al.tar.pre));
  Object.keys(pre).forEach(c => { Object.keys(pre[c]).forEach(k => { if (!pre[c][k].CO && !pre[c][k].CA) delete pre[c][k]; }); });
  if (await alCfgGuardar("tarifas", pre)) toast("Precios guardados", "success");
}
async function alDesGuardar() {
  const des = al.tar.des.filter(d => String(d.nombre).trim()).map(d => ({ id: d.id, nombre: String(d.nombre).trim(), factor: Math.round(d.factor * 100) / 100 }));
  if (await alCfgGuardar("descuentos", des)) { al.tar.des = JSON.parse(JSON.stringify(des)); toast("Descuentos guardados", "success"); alVistaTarifas(false); }
}

// ════════════════════════════════════════════════════════════════════════════
// PLANOS DE ASIENTOS: editor y qué plano usa cada coche — en la base
// ════════════════════════════════════════════════════════════════════════════
async function alVistaPlanos(animar) {
  if (!al.cfg) { alShellCargando(animar); await alCfgTraer(); }
  const pls = alPlanos(), cods = Object.keys(pls);
  if (!al.pla.draft) {
    if (!al.pla.cod || !pls[al.pla.cod]) al.pla.cod = cods[0] || "";
    al.pla.draft = al.pla.cod ? JSON.parse(JSON.stringify(pls[al.pla.cod])) : null;
    al.pla.nuevo = false; al.pla.codNuevo = al.pla.cod;
  }
  if (!al.pla.cp) al.pla.cp = JSON.parse(JSON.stringify(al.cfg.coche_plano || {}));
  const usos = cod => (al.cfg.coches || []).filter(c => alPlanoDe(c.coche, c.modelo) === cod).length;
  const d = al.pla.draft;
  const lista = cods.map(k => { const a = alAsientos(pls[k]); const co = a.filter(x => x.clase === "CO").length, ca = a.length - co;
    return `<button type="button" class="al-pl-it ${k === al.pla.cod && !al.pla.nuevo ? "on" : ""}" onclick="alPlanoElegir('${k}')">
      <b class="al-d">${trEsc(k)}</b><span>${trEsc(pls[k].nombre || "")}</span><small>${co} diferencial${ca ? ` · ${ca} cama` : ""}${pls[k].parados ? ` · ${pls[k].parados} parados` : ""} · ${usos(k)} coche${usos(k) === 1 ? "" : "s"}</small></button>`; }).join("");
  const editor = d ? alPlanoEditor(d) : `<div class="al-vacio"><b>No hay planos</b></div>`;
  const q = alNorm(al.pla.q);
  const coches = (al.cfg.coches || []).filter(c => !q || alNorm(`${c.coche} ${c.marca} ${c.modelo} ${c.patente}`).includes(q));
  content.innerHTML = alShell(`
    <div class="al-vista">
      <div class="al-v-cab"><h1 class="al-d">Planos de asientos</h1><span>Cómo está armado cada modelo de coche y qué plano usa cada coche de la flota. Se guarda en la base.</span></div>
      <div class="al-pl">
        <aside class="al-pl-lista">${lista}
          <button type="button" class="al-sec" onclick="alPlanoNuevo()"><i class="ti ti-plus"></i> Nuevo plano</button></aside>
        <section class="al-card al-pl-ed">${editor}</section>
      </div>
      <section class="al-card">
        <div class="al-card-cab"><h2 class="al-d">Qué plano usa cada coche</h2><span>«Automático» lo deduce del modelo: Paradiso 1800 DD → AO01, los 8x2 → AO03, el resto → un piso.</span></div>
        <div class="al-busca al-busca-pas"><i class="ti ti-search" aria-hidden="true"></i><input id="al-pl-q" type="search" value="${trEsc(al.pla.q)}" placeholder="Buscar coche, marca o modelo" oninput="al.pla.q=this.value;alPlanosCoches()" aria-label="Buscar coche"></div>
        <div class="al-tabla-w al-pl-coches" id="al-pl-coches">${alPlanosCochesHTML(coches)}</div>
        <div class="al-card-pie"><button type="button" class="al-btn-r" onclick="alCochesGuardar()"><i class="ti ti-device-floppy"></i> Guardar los coches</button></div>
      </section>
    </div>`, animar);
}
function alPlanosCochesHTML(coches) {
  const pls = alPlanos();
  return `<table class="al-tabla"><thead><tr><th>Coche</th><th>Modelo</th><th>Plano</th></tr></thead><tbody>${coches.map(c => {
    const fijo = al.pla.cp[c.coche] && pls[al.pla.cp[c.coche]] ? al.pla.cp[c.coche] : "";
    return `<tr><td><b>${trEsc(c.coche)}</b><small>${trEsc(c.patente)}</small></td><td>${trEsc(`${c.marca} ${c.modelo}`.trim())}</td>
      <td><select class="al-in" onchange="if(this.value)al.pla.cp['${c.coche}']=this.value;else delete al.pla.cp['${c.coche}']" aria-label="Plano del coche ${trEsc(c.coche)}">
        <option value="">Automático (${alPlanoAuto(`${c.marca} ${c.modelo}`)})</option>
        ${Object.keys(pls).map(k => `<option value="${k}" ${k === fijo ? "selected" : ""}>${trEsc(k)} · ${trEsc(pls[k].nombre || "")}</option>`).join("")}</select></td></tr>`;
  }).join("")}</tbody></table>`;
}
function alPlanosCoches() {
  const q = alNorm(al.pla.q), box = document.getElementById("al-pl-coches");
  if (box) box.innerHTML = alPlanosCochesHTML((al.cfg.coches || []).filter(c => !q || alNorm(`${c.coche} ${c.marca} ${c.modelo} ${c.patente}`).includes(q)));
}
async function alCochesGuardar() {
  if (await alCfgGuardar("coche_plano", al.pla.cp)) { toast("Planos de los coches guardados", "success"); alVistaPlanos(false); }
}
function alPlanoEditor(d) {
  const pisos = d.pisos.map((p, pi) => {
    const nf = p.filas.length;
    let celdas = "";
    p.filas.forEach((f, fi) => [0, 1, 3, 4].forEach(pos => {
      const n = f[pos], st = `grid-column:${nf - fi};grid-row:${pos + 1}`;
      if (al.pla.modo === "numero" && n != null) celdas += `<input class="al-pl-num" style="${st}" value="${n}" inputmode="numeric" onchange="alPlanoNumero(${pi},${fi},${pos},this)" aria-label="Número del asiento">`;
      else celdas += `<button type="button" class="al-pl-c ${n != null ? "si" : ""}" style="${st}" onclick="alPlanoCelda(${pi},${fi},${pos})" aria-label="${n != null ? "Asiento " + n + ": sacar" : "Poner un asiento"}">${n != null ? n : "+"}</button>`;
    }));
    celdas += `<div class="al-cel" style="grid-column:${nf + 1};grid-row:1/3">${pi === d.pisos.length - 1 ? "Chofer" : "Frente"}</div>`;
    return `<div class="al-pl-piso">
      <div class="al-pl-piso-cab">
        <input class="al-in" value="${trEsc(p.nombre)}" oninput="al.pla.draft.pisos[${pi}].nombre=this.value" aria-label="Nombre del piso">
        <select class="al-in" onchange="al.pla.draft.pisos[${pi}].clase=this.value" aria-label="Clase">${Object.entries(AL_CLASES).map(([k, t]) => `<option value="${k}" ${p.clase === k ? "selected" : ""}>${t}</option>`).join("")}</select>
        <span class="al-pl-filas">Filas <button type="button" class="al-ic" onclick="alPlanoFilas(${pi},-1)" ${nf <= 1 ? "disabled" : ""} aria-label="Una fila menos"><i class="ti ti-minus"></i></button><b>${nf}</b><button type="button" class="al-ic" onclick="alPlanoFilas(${pi},1)" ${nf >= 20 ? "disabled" : ""} aria-label="Una fila más"><i class="ti ti-plus"></i></button></span>
        ${d.pisos.length > 1 ? `<button type="button" class="al-ic rojo" onclick="alPlanoPisoBorrar(${pi})" title="Sacar este piso" aria-label="Sacar este piso"><i class="ti ti-trash"></i></button>` : ""}
      </div>
      <div class="al-scroll"><div class="al-coche"><div class="al-grid" style="grid-template-columns:repeat(${nf}, 40px) 58px;grid-template-rows:40px 40px 12px 40px 40px">${celdas}</div><div class="al-parabrisas" aria-hidden="true"></div></div></div>
    </div>`;
  }).join("");
  const a = alAsientos(d);
  return `
    <div class="al-pl-cab">
      <label class="al-campo"><span>Código</span><input value="${trEsc(al.pla.nuevo ? al.pla.codNuevo : al.pla.cod)}" ${al.pla.nuevo ? "" : "readonly"} maxlength="12" oninput="al.pla.codNuevo=this.value.toUpperCase().replace(/[^A-Z0-9_-]/g,'');this.value=al.pla.codNuevo"></label>
      <label class="al-campo"><span>Nombre</span><input value="${trEsc(d.nombre || "")}" placeholder="Doble piso con cama abajo" oninput="al.pla.draft.nombre=this.value"></label>
      <label class="al-campo ci"><span>Parados</span><input value="${d.parados || 0}" inputmode="numeric" oninput="al.pla.draft.parados=Math.min(40,+this.value.replace(/\\D/g,'')||0)"></label>
    </div>
    <div class="al-pl-modo">
      <div class="al-lados" role="group" aria-label="Qué hace el clic">
        <button type="button" class="al-lado ${al.pla.modo === "poner" ? "on" : ""}" onclick="al.pla.modo='poner';alVistaPlanos(false)">Poner y sacar <small>tocá un lugar</small></button>
        <button type="button" class="al-lado ${al.pla.modo === "numero" ? "on" : ""}" onclick="al.pla.modo='numero';alVistaPlanos(false)">Cambiar números <small>escribí el número</small></button>
      </div>
      <button type="button" class="al-sec" onclick="alPlanoNumerar()"><i class="ti ti-123"></i> Numerar de nuevo</button>
      <span class="al-sub">${a.length} asientos · el frente del coche está a la derecha</span>
    </div>
    ${pisos}
    <div class="al-card-pie">
      ${d.pisos.length < 2 ? `<button type="button" class="al-sec" onclick="alPlanoPisoAgregar()"><i class="ti ti-stairs-up"></i> Agregar otro piso</button>` : ""}
      ${!al.pla.nuevo ? `<button type="button" class="al-sec" onclick="alPlanoDuplicar()"><i class="ti ti-copy"></i> Duplicar</button>
        <button type="button" class="al-sec rojo" onclick="alPlanoBorrar()"><i class="ti ti-trash"></i> Borrar</button>` : `<button type="button" class="al-sec" onclick="al.pla.draft=null;alVistaPlanos(false)">Cancelar</button>`}
      <button type="button" class="al-btn-r" onclick="alPlanoGuardar()"><i class="ti ti-device-floppy"></i> Guardar el plano</button>
    </div>`;
}
function alPlanoElegir(k) { al.pla.cod = k; al.pla.draft = null; alVistaPlanos(false); }
function alPlanoMax(d) { return Math.max(0, ...alAsientos(d).map(a => a.n)); }
function alPlanoCelda(pi, fi, pos) {
  const f = al.pla.draft.pisos[pi].filas[fi];
  f[pos] = f[pos] != null ? null : alPlanoMax(al.pla.draft) + 1;
  alVistaPlanos(false);
}
function alPlanoNumero(pi, fi, pos, inp) {
  const n = +inp.value.replace(/\D/g, "");
  if (!n || n > 199) { inp.value = al.pla.draft.pisos[pi].filas[fi][pos]; toast("El número va de 1 a 199", "error"); return; }
  const otro = alAsientos(al.pla.draft).find(a => a.n === n && !(a.piso === pi && a.fila === fi && a.pos === pos));
  if (otro) {
    // Si el número ya lo tiene otro asiento, se intercambian
    al.pla.draft.pisos[otro.piso].filas[otro.fila][otro.pos] = al.pla.draft.pisos[pi].filas[fi][pos];
  }
  al.pla.draft.pisos[pi].filas[fi][pos] = n;
  alVistaPlanos(false);
}
function alPlanoNumerar() {
  // Como en Delta: de adelante para atrás, en cada fila ventanilla izq, pasillo izq, ventanilla der, pasillo der
  let k = 1;
  al.pla.draft.pisos.forEach(p => p.filas.forEach(f => [0, 1, 4, 3].forEach(pos => { if (f[pos] != null) f[pos] = k++; })));
  alVistaPlanos(false);
}
function alPlanoFilas(pi, d) {
  const fs = al.pla.draft.pisos[pi].filas;
  if (d > 0) { const m = alPlanoMax(al.pla.draft); fs.push([m + 1, m + 2, null, m + 4, m + 3]); }
  else fs.pop();
  alVistaPlanos(false);
}
function alPlanoPisoAgregar() {
  const m = alPlanoMax(al.pla.draft), fs = [];
  for (let i = 0; i < 4; i++) fs.push([m + 1 + i * 4, m + 2 + i * 4, null, m + 4 + i * 4, m + 3 + i * 4]);
  al.pla.draft.pisos.push({ nombre: "Piso bajo", clase: "CA", filas: fs });
  if (al.pla.draft.pisos[0].nombre === "Planta única") al.pla.draft.pisos[0].nombre = "Piso alto";
  alVistaPlanos(false);
}
function alPlanoPisoBorrar(pi) { if (!confirm("¿Sacar este piso con sus asientos?")) return; al.pla.draft.pisos.splice(pi, 1); alVistaPlanos(false); }
function alPlanoNuevo() {
  const fs = []; for (let i = 0; i < 12; i++) fs.push([i * 4 + 1, i * 4 + 2, null, i * 4 + 4, i * 4 + 3]);
  al.pla.draft = { nombre: "", tipo: "Un piso", parados: 0, pisos: [{ nombre: "Planta única", clase: "CO", filas: fs }] };
  al.pla.nuevo = true; al.pla.codNuevo = "";
  alVistaPlanos(false);
}
function alPlanoDuplicar() {
  al.pla.draft = JSON.parse(JSON.stringify(al.pla.draft));
  al.pla.draft.nombre = (al.pla.draft.nombre || "") + " (copia)";
  al.pla.nuevo = true; al.pla.codNuevo = "";
  alVistaPlanos(false);
}
async function alPlanoGuardar() {
  const d = JSON.parse(JSON.stringify(al.pla.draft)), cod = al.pla.nuevo ? (al.pla.codNuevo || "").trim() : al.pla.cod;
  if (!cod) { toast("Poné un código al plano (por ejemplo AO05)", "error"); return; }
  if (al.pla.nuevo && alPlanos()[cod]) { toast(`Ya hay un plano ${cod}`, "error"); return; }
  if (!String(d.nombre || "").trim()) { toast("Poné un nombre al plano", "error"); return; }
  d.tipo = d.pisos.length > 1 ? "Doble piso" : "Un piso";
  const pls = Object.assign({}, alPlanos(), { [cod]: d });
  if (await alCfgGuardar("planos", pls)) { toast(`Plano ${cod} guardado`, "success"); al.pla.cod = cod; al.pla.draft = null; alVistaPlanos(false); }
}
async function alPlanoBorrar() {
  const cod = al.pla.cod, fijos = Object.entries(al.cfg.coche_plano || {}).filter(([, p]) => p === cod).map(([c]) => c);
  if (Object.keys(alPlanos()).length <= 1) { toast("Tiene que quedar al menos un plano", "error"); return; }
  if (fijos.length) { toast(`No se puede: lo usan los coches ${fijos.slice(0, 6).join(", ")}${fijos.length > 6 ? "…" : ""}. Cambiales el plano primero.`, "error"); return; }
  if (!confirm(`¿Borrar el plano ${cod}? Los coches que lo usaban en automático pasan a otro.`)) return;
  const pls = Object.assign({}, alPlanos()); delete pls[cod];
  if (await alCfgGuardar("planos", pls)) { toast(`Plano ${cod} borrado`, "success"); al.pla.cod = ""; al.pla.draft = null; alVistaPlanos(false); }
}

// F9 cobra mientras se está vendiendo en Alpha
document.addEventListener("keydown", e => {
  if (e.key === "F9" && document.getElementById("al-raiz") && al.vista === "vender") { e.preventDefault(); alCobrar(); }
});
