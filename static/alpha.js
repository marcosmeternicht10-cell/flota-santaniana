// alpha.js — Alpha, la venta de pasajes (se carga después de app.js y usa sus
// utilidades: api, toast, trEsc, fmtNum, content, status).
// ════════════════════════════════════════════════════════════════════════════
// ALPHA (solo admin). Los servicios salen del TRÁFICO de cada día (corredores,
// salidas de ida y regreso, coche asignado y tripulación); si ese día todavía
// no se armó, se toman los horarios del último tráfico del mismo día de la
// semana y el coche queda a confirmar.
//
// Todo está en la base: la configuración (/api/alpha/config: planos, coche →
// plano, recorridos, tarifas, descuentos) y las ventas de todas las agencias
// (/api/alpha/ventas, ocupación, caja y liquidaciones). Las ventas siguen
// siendo de prueba, sin valor fiscal (falta lo fiscal).
//
// Pantallas: Vender · Pasajes · Manifiesto · Caja · Tarifas · Planos. Lo de
// control (servicios, transbordos, agencias, liquidaciones, recaudación) está
// en su propio módulo: static/controles.js.
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
                   ["caja", "cash-register", "Caja"],
                   ["tarifas", "currency-dollar", "Tarifas"], ["planos", "armchair", "Planos"]];
const AL_PVACIO = () => ({ tipoDoc: "CI", doc: "", nombre: "", apellidos: "", nombres: "", sexo: "", nac: "", nacionalidad: "", residencia: "" });
const AL_LOGO = `<svg aria-hidden="true" width="40" height="33" viewBox="0 0 120 100"><path d="M98 20C80 40 72 80 42 80C22 80 12 66 12 50C12 34 24 20 42 20C70 20 80 58 99 77" fill="none" stroke="#F3F4F6" stroke-width="13" stroke-linecap="round" stroke-linejoin="round"></path><circle cx="98" cy="20" r="10" fill="#E83040"></circle><circle cx="106" cy="84" r="8" fill="none" stroke="#F3F4F6" stroke-width="5"></circle></svg>`;

function alEsAgencia() { return window.USUARIO_ROL === "agencia" || !!al.comoAgencia; }
function alVistasPermitidas() { return alEsAgencia() ? ["vender", "pasajes", "caja"] : AL_VISTAS.map(v => v[0]); }
const al = {
  comoAgencia: false,
  vista: "vender", cor: "", lado: "ida", dia: 0, dep: 0, sube: 0, baja: -1, sel: null,
  tarifa: "general", pago: "efectivo", recibe: "", aviso: "", p: AL_PVACIO(),
  datos: {}, cargando: false, error: "", cfg: null, cambio: null, cambioV: null, cobrarReserva: null,
  ocup: {}, miCaja: 0, reservas: 0, conocido: null, pasLista: [],
  liq: { agencia: "", hasta: "", soloEf: false, prev: null },
  buscaHits: [], buscaSel: 0,
  pas: { q: "", estado: "" }, man: { clave: "" }, caja: { fecha: "", vendedor: "" },
  ultimo: null, vuelta: null, ver: null, verK: "", x: { menor: null, bultos: 0 },
  rec: { desde: "", hasta: "", por: "servicio" }, ctl: { vista: "servicios", umbral: 75, clave: "", q: "" },
  servEst: {}, credito: null,
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
const _alNormMemo = new Map();
function alNorm(t) {
  const k = String(t || "");
  let r = _alNormMemo.get(k);
  if (r === undefined) {
    r = k.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/\s+/g, " ").trim();
    if (_alNormMemo.size > 5000) _alNormMemo.clear();
    _alNormMemo.set(k, r);
  }
  return r;
}
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

// Las ventas (de todas las agencias, en la base). De cada día se trae la
// ocupación: las ventas propias completas y las ajenas solo como "ocupado".
function alSalidaISO(v) { return `${v.fecha}T${v.sale || v.hora}`; }
function alReservaViva(v) { return v.estado === "reserva" && alAhoraISO() < (v.vence || alSalidaISO(v)).slice(0, 16); }
function alOcupa(v) { return v.estado === "vendido" || v.estado === "bloqueado" || alReservaViva(v); }
// Los asientos se vuelven a pedir si lo que hay tiene más de 15 segundos:
// así se ve lo que vendieron las otras agencias (el servidor igual no deja
// vender dos veces el mismo asiento).
const AL_OCUP_FRESCO = 15000;
async function alTraerOcup(fecha, forzar) {
  fecha = fecha || alISO(alFechaDe(al.dia));
  al.ocupEl = al.ocupEl || {};
  if (al.ocup[fecha] && !forzar && Date.now() - (al.ocupEl[fecha] || 0) < AL_OCUP_FRESCO) return al.ocup[fecha];
  let d = null;
  try { d = await api(`/api/alpha/ocupacion?fecha=${fecha}`); } catch (e) { d = null; }
  if (d && d.ventas) {
    al.ocup[fecha] = d.ventas; al.ocupEl[fecha] = Date.now(); al.miCaja = d.mi_caja_hoy || 0; al.reservas = d.reservas || 0;
    al.servEst[fecha] = d.servicios || {}; al.credito = d.credito || null;
  }
  else if (!al.ocup[fecha]) al.ocup[fecha] = [];
  return al.ocup[fecha];
}
// Refresca en segundo plano y repinta solo si cambió algo y no se está escribiendo
async function alRefrescarOcup() {
  if (al.vista !== "vender" || al.enviando || document.hidden) return;
  const f = alISO(alFechaDe(al.dia)), antes = JSON.stringify(al.ocup[f] || []);
  await alTraerOcup(f, true);
  const escribiendo = document.activeElement && document.activeElement.closest && document.activeElement.closest("#al-raiz") && /INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName);
  if (al.vista === "vender" && JSON.stringify(al.ocup[f] || []) !== antes && !escribiendo) alPintar(false);
}
setInterval(() => { if (document.getElementById("al-raiz")) alRefrescarOcup(); }, 20000);
function alOcupDe(fecha) { return al.ocup[fecha] || []; }
async function alPost(url, cuerpo) {
  const r = await api(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo || {}) });
  if (!r || !r.ok) { toast((r && (r.msg || r.error)) || "No se pudo", "error"); return null; }
  return r;
}

// ─── Configuración (de la base) ───
async function alCfgTraer(forzar) {
  if (al.cfg && !forzar) return al.cfg;
  const d = await api("/api/alpha/config");
  if (d && d.planos) { al.cfg = d; al.cfgVer = (al.cfgVer || 0) + 1; }
  else if (!al.cfg) al.cfg = { planos: {}, coche_plano: {}, recorridos: {}, tarifas: {}, descuentos: [{ id: "general", nombre: "General", factor: 1 }], coches: [], corredores: [] };
  return al.cfg;
}
async function alCfgGuardar(clave, valor) {
  const r = await api(`/api/alpha/config/${clave}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ valor }) });
  if (!r || !r.ok) { toast((r && (r.msg || r.error)) || "No se pudo guardar", "error"); return false; }
  al.cfg[clave] = JSON.parse(JSON.stringify(valor));
  al.cfgVer = (al.cfgVer || 0) + 1;
  return true;
}
function alPlanos() { return (al.cfg && al.cfg.planos) || {}; }
function alDescuentos() { const d = (al.cfg && al.cfg.descuentos) || []; return d.length ? d : [{ id: "general", nombre: "General", factor: 1 }]; }
function alPlanoAuto(modelo) {
  const m = String(modelo || "").toLowerCase(), pls = alPlanos();
  const ok = c => pls[c] ? c : Object.keys(pls)[0];
  if (/volare|senior/.test(m)) return ok("VOLARE");
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
  if (al.datos[f] && !forzar) { al.cargando = false; return; }
  al.cargando = true; al.error = "";
  let d = null;
  try { d = await api(`/api/alpha/dia/${f}`); }
  catch (e) { d = null; }
  finally { al.cargando = false; }
  if (!d || !d.corredores) { al.error = (d && d.error) || "No se pudo traer el tráfico. Probá de nuevo."; return; }
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
// Las salidas del corredor y sentido elegidos: se arman una vez y se guardan
// hasta que cambie el día, el corredor, el sentido o la configuración
let _alSvMemo = { k: null, r: null, lista: [] };
function alServicios() {
  const r = alRuta(), k = `${alISO(alFechaDe(al.dia))}|${r ? r.clave : ""}|${al.lado}|${al.cfgVer || 0}|${window.USUARIO_ROL}`;
  if (_alSvMemo.k !== k || _alSvMemo.r !== r) _alSvMemo = { k, r, lista: alServiciosDe(r, al.lado) };
  return { lista: _alSvMemo.lista };
}
function alServ(k) { return alServicios().lista[k ?? al.dep]; }
function alPlano(sv) { return alPlanos()[sv.plano] || Object.values(alPlanos())[0]; }
const _alAsiMemo = new WeakMap();
function alAsientos(pl, fresco) {
  if (!pl) return [];
  const m = !fresco && _alAsiMemo.get(pl);
  if (m) return m;
  const out = [];
  if (!fresco) _alAsiMemo.set(pl, out);
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
const _alCamMemo = new Map();
function alCamino(sv) {
  const k = `${sv.clave}|${al.cfgVer || 0}`;
  let c = _alCamMemo.get(k);
  if (!c) { c = _alCaminoCalc(sv); if (_alCamMemo.size > 500) _alCamMemo.clear(); _alCamMemo.set(k, c); }
  return c;
}
function _alCaminoCalc(sv) {
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
function alVentasDe(fecha, sv) { return alOcupDe(fecha).filter(v => v.servicio === sv.clave && alOcupa(v) && (v.nro == null || v.nro !== al.cambio)); }
function alOcupacion(fecha, k, s, b) {
  // asiento → venta, solo las que se pisan con el tramo s..b
  const sv = alServ(k), cam = alCamino(sv), out = new Map();
  if (s == null) { s = 0; b = cam.length - 1; }
  alVentasDe(fecha, sv).forEach(v => {
    const vs = v.subeIdx ?? alIdxDe(cam, v.sube, 0), vb = Math.min(v.bajaIdx ?? alIdxDe(cam, v.baja, cam.length - 1), cam.length - 1);
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
function alDescAsiento(n, plano) {
  if (n == null) return null;
  let pl = plano;
  if (!pl) { const sv = alServ(); if (!sv) return null; pl = alPlano(sv); }
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
function alConocido() { return al.conocido; }
let _alConTimer = null;
function alBuscarConocido(doc) {
  clearTimeout(_alConTimer);
  al.conocido = null;
  const dig = String(doc || "").replace(/\D/g, "");
  if (dig.length < 5) return;
  _alConTimer = setTimeout(async () => {
    const r = await api(`/api/alpha/pasajero?doc=${encodeURIComponent(dig)}`);
    if (!r || !r.datos || String(al.p.doc).replace(/\D/g, "") !== dig) return;
    al.conocido = r;
    const d = r.datos, p = al.p, intl = alServ()?.intl;
    const poner = (k, val) => { if (val && !p[k]) { p[k] = val; const e = document.getElementById("al-" + k); if (e) e.value = val; } };
    if (intl) ["apellidos", "nombres", "sexo", "nac", "nacionalidad", "residencia"].forEach(k => poner(k, d[k]));
    else poner("nombre", d.nombreCompleto || [d.nombres, d.apellidos].filter(Boolean).join(" "));
    const h = document.getElementById("al-hint");
    if (h) h.textContent = `Ya viajó ${r.viajes} ${r.viajes === 1 ? "vez" : "veces"} con ustedes`;
  }, 350);
}
function alNombreCompleto(p) { return p.nombre || [p.nombres, p.apellidos].filter(Boolean).join(" "); }

// ════════════════════════════════════════════════════════════════════════════
// LA PANTALLA: cabecera con las secciones de Alpha
// ════════════════════════════════════════════════════════════════════════════
async function renderAlpha() {
  if (typeof status === "function") status("Alpha: la venta de pasajes. servicios del tráfico; tarifas, planos y ventas (de prueba) en la base");
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
  try { await Promise.all([alTraer(), alTraerOcup(null, true)]); }
  finally { al.cargando = false; }
  alRender(true);
}
function alIr(vista) {
  if (vista === al.vista || !alVistasPermitidas().includes(vista)) return;
  al.vista = vista;
  if (vista === "vender") setTimeout(alRefrescarOcup, 0);
  if (vista === "tarifas") { al.tar.rec = al.tar.pre = al.tar.des = null; }
  if (vista === "planos") { al.pla.draft = null; al.pla.cp = null; }
  alRender(true);
}
function alShell(cuerpo, animar, extraCab = "") {
  const caja = al.miCaja || 0, res = al.reservas || 0;
  return `<div class="al ${animar ? "al-entra" : ""}" id="al-raiz">
    <header class="al-cab">
      <div class="al-marca">${AL_LOGO}<span class="al-d al-marca-t">Alpha</span><span class="al-maqueta">Maqueta</span></div>
      <nav class="al-nav" aria-label="Secciones de Alpha">${AL_VISTAS.filter(([k]) => alVistasPermitidas().includes(k)).map(([k, ic, t], i) => `${k === "tarifas" ? '<span class="al-nav-sep" aria-hidden="true"></span>' : ""}<button type="button" class="al-nav-b ${al.vista === k ? "on" : ""}" aria-current="${al.vista === k ? "page" : "false"}" onclick="alIr('${k}')"><i class="ti ti-${ic}"></i><span>${t}</span>${k === "pasajes" && res ? `<em title="Reservas vigentes">${res}</em>` : ""}</button>`).join("")}</nav>
      ${extraCab}
      <div class="al-caja">
        <button type="button" class="al-ic al-imp-b" onclick="alImpModal()" title="Impresora de esta computadora" aria-label="Impresora de esta computadora"><i class="ti ti-printer"></i></button>
        ${al.credito && al.credito.disponible != null ? `<div class="${al.credito.disponible <= 0 ? "al-sin-cred" : ""}"><span>Podés vender hasta</span><b class="al-d">${alGs(Math.max(0, al.credito.disponible))}</b></div>` : ""}
        <div><span>Tu caja de hoy</span><b class="al-d">${alGs(caja)}</b></div>
        ${window.USUARIO_ROL === "admin" ? `<button type="button" class="al-sec al-comoag ${al.comoAgencia ? "on" : ""}" onclick="alComoAgencia()" title="Ver Alpha como la ve una agencia">
            <i class="ti ti-${al.comoAgencia ? "shield" : "building-store"}"></i> ${al.comoAgencia ? "Volver a administración" : "Ver como agencia"}</button>` : ""}
        ${window.USUARIO_ROL === "agencia" ? `<div class="al-quien"><span>${trEsc(window.USUARIO_AGENCIA || "Agencia")}</span><b>${trEsc(window.USUARIO_NOMBRE || "")}</b></div>
            <button type="button" class="al-sec" onclick="alSalir()"><i class="ti ti-logout"></i> Salir</button>` : ""}
      </div>
    </header>
    ${alBannerCredito()}
    ${al.comoAgencia ? `<div class="al-banner al-banner-ag"><i class="ti ti-eye"></i><span><b>Así lo ve una agencia.</b> Solo vende, ve sus pasajes y su caja: sin tarifario, planos, manifiesto, tripulación ni coche.</span></div>` : ""}
    ${cuerpo}
  </div>`;
}
async function alReintentar() {
  al.error = ""; al.cargando = true; alRender(false);
  try { await Promise.all([alCfgTraer(true), alTraer(true), alTraerOcup(null, true)]); } finally { al.cargando = false; }
  alRender(true);
}
// La agencia suspendida o pasada del tope no puede vender: se le avisa arriba
function alBannerCredito() {
  const c = al.credito;
  if (!c) return "";
  if (c.estado === "suspendida" || c.estado === "baja") return `<div class="al-banner al-banner-rojo"><i class="ti ti-ban"></i><span><b>Tu agencia está ${c.estado === "baja" ? "dada de baja" : "suspendida"}${c.motivo ? ": " + trEsc(c.motivo) : ""}.</b> No podés vender ni cobrar reservas. Hablá con La Santaniana.</span></div>`;
  if (c.disponible != null && c.disponible <= 0) return `<div class="al-banner al-banner-rojo"><i class="ti ti-alert-triangle"></i><span><b>Llegaste al tope de venta sin depositar (${alGs(c.tope)}).</b> Tenés ${alGs(c.saldo)} sin depositar: depositá para seguir vendiendo.</span></div>`;
  if (c.disponible != null && c.tope && c.disponible < c.tope * 0.15) return `<div class="al-banner"><i class="ti ti-alert-triangle"></i><span>Te quedan <b>${alGs(c.disponible)}</b> para vender antes del tope de tu contrato (${alGs(c.tope)}). Depositá lo pendiente para no quedarte sin venta.</span></div>`;
  return "";
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
    <div class="al-vacio"><i class="ti ti-${al.cargando || /Trayendo/.test(txt) ? "loader-2 al-gira" : "calendar-off"}"></i><b>${txt}</b><span>${alDiaTxt(alFechaDe(al.dia))}</span>
      ${!al.cargando && al.error ? `<button type="button" class="al-sec" onclick="alReintentar()"><i class="ti ti-refresh"></i> Probar de nuevo</button>` : ""}</div>`, animar);
}
function alBannerCambio() {
  const v = al.cambio ? al.cambioV : null;
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
  if (!al.ocup[fecha]) {
    if (!al._trayendoOcup) { al._trayendoOcup = true; alTraerOcup(fecha).finally(() => { al._trayendoOcup = false; if (al.vista === "vender") alPintar(false); }); }
    return alVacio(animar, "Trayendo los asientos…");
  }
  const lleno = k => { const pl = alPlano(alServ(k)); return alOcupacion(fecha, k).size >= alAsientos(pl).length && alParadosVendidos(fecha, k) >= (pl.parados || 0); };
  const estSv = k => alEstadoServ(fecha, lista[k] && lista[k].clave);
  const sirve = k => k < lista.length && !alYaSalio(al.dia, k) && !lleno(k) && estSv(k) === "abierto";
  if (al.dep >= lista.length) al.dep = 0;
  if (!sirve(al.dep)) { const k = lista.findIndex((_, i) => sirve(i)); if (k >= 0 && k !== al.dep) { al.dep = k; al.sube = 0; al.baja = -1; } }
  alVueltaTramo();
  if (al.ver != null && al.verK !== `${fecha}|${alServ().clave}`) al.ver = null;
  const sv = alServ(), pl = alPlano(sv), cam = alCamino(sv), [s, b] = alTramoIdx();
  const ocup = alOcupacion(fecha, al.dep, s, b), todos = alAsientos(pl);
  if (al.ver != null && !(ocup.get(al.ver) || {}).mia) al.ver = null;
  const paradosQuedan = Math.max(0, (pl.parados || 0) - alParadosVendidos(fecha, al.dep));
  if (al.sel === "P" && !paradosQuedan) al.sel = null;
  if (al.sel != null && al.sel !== "P" && !todos.some(a => a.n === al.sel)) al.sel = null;
  if (al.sel != null && al.sel !== "P" && ocup.has(al.sel) && ocup.get(al.sel).estado !== "reserva") al.sel = null;
  if (al.sel == null) { const libre = todos.find(a => !ocup.has(a.n)); al.sel = libre ? libre.n : (paradosQuedan ? "P" : null); }
  const r = alRuta();

  const tabs = lista.map((x, k) => {
    const v = alOcupacion(fecha, k), fue = alYaSalio(al.dia, k);
    const asi = alAsientos(alPlano(x));
    const porClase = ["CO", "CA"].map(c => { const tot = asi.filter(a => a.clase === c); if (!tot.length) return ""; return (tot.length - tot.filter(a => v.has(a.n)).length) + " " + c; }).filter(Boolean);
    const est = estSv(k);
    const txt = fue ? "Ya salió" : est === "cancelado" ? "Cancelado" : est === "cerrado" ? "Venta cerrada" : lleno(k) ? "Completo" : porClase.join(", ") + " libres";
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
      const o = ocup.get(n), bl = o && o.estado === "bloqueado", v = o && (o.estado === "vendido" || bl), rs = o && o.estado === "reserva";
      const ver = v && o.mia && o.nro != null, on = (!v && n === al.sel && al.ver == null) || (ver && n === al.ver);
      celdas += `<button type="button" class="al-as ${cama ? "cama" : nf >= 12 ? "chico" : ""} ${bl ? "vendido bloqueado" : v ? "vendido" : rs ? "reservado" : ""} ${on ? (v ? "visto" : "elegido") : ""} ${ver ? "ver" : ""}" style="grid-column:${nf - fi};grid-row:${pos + 1}"
        ${v && !ver ? "disabled" : ""} aria-pressed="${on}" ${ver ? `title="${trEsc(bl ? "Bloqueado: " + (o.motivo || o.nombre) : o.nombre)}"` : ""} aria-label="Asiento ${n}${bl ? ", bloqueado" : v ? ", vendido" + (ver ? ": ver el boleto" : "") : rs ? ", reservado" : on ? ", elegido" : ", libre"}" onclick="${ver ? `alVerAsiento(${n})` : `alAsiento(${n})`}"><i aria-hidden="true"></i>${n}</button>`;
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
    ${alBannerVuelta()}
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
            <div><h2 id="al-coche-t" class="al-d">${sv.coche ? "Coche " + trEsc(sv.coche) : "Coche a confirmar"}</h2>${sv.reemplazo ? `<span class="al-reemp" title="${trEsc(sv.reemplazo.motivo || "")}"><i class="ti ti-arrows-shuffle"></i> reemplaza al ${trEsc(sv.reemplazo.de)}</span>` : ""}
              <span class="al-sub">${trEsc(sv.coche ? sv.modelo : sv.habitual ? `Suele ir el ${sv.habitual}${sv.habitual_modelo ? " (" + sv.habitual_modelo + ")" : ""}` : "Todavía sin coche")} · ${trEsc(sv.cod)}, sale ${alHH(sv.h)}${sv.dur ? `, ${alDur(sv.dur)} de viaje` : ""}</span>
              ${sv.tripulacion.length ? `<span class="al-trip"><i class="ti ti-steering-wheel"></i> ${sv.tripulacion.map(trEsc).join(" y ")}</span>` : ""}
              ${sv.coche || sv.habitual ? `<label class="al-plano-sel"><span>Plano</span><select onchange="alCambiarPlano(this.value)" aria-label="Plano de asientos de este coche">${Object.entries(alPlanos()).map(([k, p]) => `<option value="${k}" ${k === sv.plano ? "selected" : ""}>${trEsc(p.nombre || k)} (${k})</option>`).join("")}</select></label>` : ""}
            </div>`}
            <div class="al-ley">
              <span><i class="al-ley-c"></i>Libre</span><span><i class="al-ley-c v"></i>Vendido</span><span><i class="al-ley-c r"></i>Reservado</span>${[...ocup.values()].some(o => o.estado === "bloqueado") ? `<span><i class="al-ley-c b"></i>Bloqueado</span>` : ""}<span><i class="al-ley-c e"></i>Elegido</span>
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
  if (al.ver != null) return alPanelVer();
  const fecha = alISO(alFechaDe(al.dia)), cam = alCamino(sv), [s, b] = alTramoIdx();
  const d = alDescAsiento(al.sel), intl = sv.intl, p = al.p;
  // Asiento reservado: se cobra o se libera
  const res = al.sel != null && al.sel !== "P" ? alOcupacion(fecha, al.dep, s, b).get(al.sel) : null;
  if (res && res.estado === "reserva" && !res.mia) {
    return `<div class="al-elegido"><div class="al-num reservado"><span class="al-d">${al.sel}</span></div>
      <div class="al-elegido-t"><b class="al-d">Reservado</b><span>Por otra agencia</span><small>Vence ${res.vence ? alDM(res.vence.slice(0, 10)) + " " + res.vence.slice(11, 16) : "al salir"}</small></div></div>
      <p class="al-hint">Elegí otro asiento.</p>`;
  }
  if (res && res.estado === "reserva" && al.cobrarReserva !== res.nro) {
    return `<div class="al-elegido"><div class="al-num reservado"><span class="al-d">${al.sel}</span></div>
      <div class="al-elegido-t"><b class="al-d">Reservado</b><span>${trEsc(res.nombre)}</span><small>${res.tipoDoc && res.mig ? trEsc(res.tipoDoc) : "CI"} ${trEsc(res.doc)}</small></div></div>
      <div class="al-res-info">
        <span><b>${trEsc(res.origen)} → ${trEsc(res.destino)}</b></span>
        <span>Reserva ${alNro(res.nro)}, hecha el ${alDM(res.reservado_en.slice(0, 10))} a las ${res.reservado_en.slice(11, 16)} por ${trEsc(res.vendedor || "")}</span>
        <span>Vence ${res.vence ? `el ${alDM(res.vence.slice(0, 10))} a las ${res.vence.slice(11, 16)}` : "al salir"} si no se cobra</span>
      </div>
      <button type="button" class="al-cobrar" onclick="alReservaCobrar(${res.nro})"><span class="al-cobrar-in"><span class="al-d">Cobrar la reserva</span></span></button>
      <button type="button" class="al-sec" onclick="alReservaLiberar(${res.nro}, '${trEsc(res.nombre).replace(/'/g, "\\'")}', ${res.asiento})"><i class="ti ti-lock-open"></i> Liberar el asiento</button>`;
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
  if (al.cambio && al.cambioV) cambio = { v: al.cambioV, dif: total - al.cambioV.total };
  const reserva = al.cobrarReserva ? alOcupDe(fecha).find(x => x.nro === al.cobrarReserva) : null;
  const aCobrar = cambio ? Math.max(0, cambio.dif) : total;
  const imp = alImp();
  const boton = cambio ? "Confirmar el cambio" : reserva ? "Cobrar la reserva" : imp.modo === "no" ? "Cobrar" : "Cobrar e imprimir";
  const ult = al.ultimo && !cambio && !reserva ? `<div class="al-ult"><span><i class="ti ti-circle-check"></i> Último: <b>${alNro(al.ultimo.nro)}</b> ${trEsc(al.ultimo.nombre)}</span>
      <span class="al-ult-b"><button type="button" class="al-link" onclick="alReimprimir(${al.ultimo.nro})">Reimprimir</button>${!al.vuelta ? `<button type="button" class="al-link" onclick="alVueltaVender()">Vender la vuelta</button>` : ""}</span></div>` : "";
  const adm = window.USUARIO_ROL === "admin" && !al.comoAgencia;
  return `
    ${ult}
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
    ${alExtrasHTML(intl)}
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
    <div class="al-imp-l">
      <label class="al-check"><input type="checkbox" ${imp.modo !== "no" ? "checked" : ""} onchange="alImpRapido(this.checked)"> Imprimir el boleto</label>
      <button type="button" class="al-link" onclick="alImpModal()" title="Configurar la impresora de esta computadora"><i class="ti ti-printer"></i> ${trEsc(alImpTxt(imp))}</button>
    </div>
    ${adm && !cambio && !reserva && d && !d.parado ? `<button type="button" class="al-link al-bloq" onclick="alBloquear()"><i class="ti ti-lock"></i> Bloquear el asiento ${al.sel} (tripulación, compromiso…)</button>` : ""}
    <p class="al-aviso" id="al-aviso" role="status">${d && !pt ? "Ese tramo no tiene precio: cargalo en Tarifas." : trEsc(al.aviso)}</p>`;
}
function alVueltoTxt(total) {
  const r = +al.recibe || 0;
  if (!r) return "—";
  return r >= total ? fmtNum(r - total) : "faltan " + fmtNum(total - r);
}
function alRepintarPanel() { const p = document.getElementById("al-panel"); if (p) p.innerHTML = alPanel(); }
function alAvisoLimpio() { if (al.aviso) { al.aviso = ""; const a = document.getElementById("al-aviso"); if (a) a.textContent = ""; } }

// ─── Menor en brazos (sin asiento) y bultos en bodega ───
function alExtrasHTML(intl) {
  const x = al.x, bo = alBoletoCfg(), m = x.menor;
  return `<div class="al-extra">
      <button type="button" class="al-chip ${m ? "on" : ""}" aria-pressed="${!!m}" onclick="alMenorToggle()"><i class="ti ti-baby-carriage"></i> Menor en brazos</button>
      <div class="al-bultos" role="group" aria-label="Bultos en bodega"><span>Bultos</span>
        <button type="button" class="al-ic" onclick="alBultos(-1)" aria-label="Un bulto menos" ${x.bultos ? "" : "disabled"}><i class="ti ti-minus"></i></button>
        <b class="al-d" aria-live="polite">${x.bultos}</b>
        <button type="button" class="al-ic" onclick="alBultos(1)" aria-label="Un bulto más"><i class="ti ti-plus"></i></button></div>
    </div>
    ${m ? `<div class="al-fila al-menor">
      <label class="al-campo"><span>Nombre del menor</span><input id="al-m-nombre" autocomplete="off" value="${trEsc(m.nombre || "")}" oninput="alMenorCampo('nombre', this)"></label>
      <label class="al-campo ci"><span>Edad</span><input id="al-m-edad" inputmode="numeric" autocomplete="off" value="${m.edad ?? ""}" placeholder="hasta ${bo.menor_edad}" oninput="alMenorCampo('edad', this)"></label>
      ${intl ? `<label class="al-campo ci"><span>Documento</span><input id="al-m-doc" autocomplete="off" value="${trEsc(m.doc || "")}" oninput="alMenorCampo('doc', this)"></label>` : ""}
    </div>` : ""}`;
}
function alMenorToggle() {
  al.x.menor = al.x.menor ? null : { nombre: "", edad: "", doc: "" };
  alAvisoLimpio(); alRepintarPanel();
  if (al.x.menor) setTimeout(() => document.getElementById("al-m-nombre")?.focus(), 20);
}
function alMenorCampo(k, el) {
  if (!el.isConnected || !al.x.menor) return;
  let v = el.value;
  if (k === "nombre") { v = v.toUpperCase(); el.value = v; }
  if (k === "edad") { v = v.replace(/\D/g, "").slice(0, 2); el.value = v; }
  al.x.menor[k] = v;
  alAvisoLimpio();
}
function alBultos(d) { al.x.bultos = Math.max(0, Math.min(20, (al.x.bultos || 0) + d)); alRepintarPanel(); }
function alExtrasCuerpo() {
  const m = al.x.menor;
  return { menor: m && m.nombre.trim() ? { nombre: m.nombre.trim(), edad: m.edad === "" ? null : +m.edad, doc: (m.doc || "").trim() } : null, bultos: al.x.bultos || 0 };
}
function alExtrasDe(v) { return { menor: v.menor ? { nombre: v.menor.nombre || "", edad: v.menor.edad ?? "", doc: v.menor.doc || "" } : null, bultos: +v.bultos || 0 }; }

// ─── Un asiento vendido (propio) o bloqueado: ver el boleto y lo que se hace con él ───
function alVerAsiento(n) {
  al.ver = n; al.verK = `${alISO(alFechaDe(al.dia))}|${alServ().clave}`; al.aviso = "";
  alPintar(false);
}
function alVerCerrar() { al.ver = null; alPintar(false); }
function alPanelVer() {
  const fecha = alISO(alFechaDe(al.dia)), [s, b] = alTramoIdx();
  const o = alOcupacion(fecha, al.dep, s, b).get(al.ver);
  if (!o || !o.mia) { al.ver = null; return alPanel(); }
  const e = trEsc, adm = window.USUARIO_ROL === "admin" && !al.comoAgencia, cuando = x => x ? `${alDM(x.slice(0, 10))} a las ${x.slice(11, 16)}` : "";
  const volver = `<button type="button" class="al-sec" onclick="alVerCerrar()"><i class="ti ti-arrow-left"></i> Volver a vender</button>`;
  if (o.estado === "bloqueado") return `
    <div class="al-elegido"><div class="al-num bloqueado"><span class="al-d">${al.ver}</span></div>
      <div class="al-elegido-t"><b class="al-d">Bloqueado</b><span>${e(o.motivo || o.nombre)}</span><small>${e(o.bloqueado_por || o.vendedor || "")}, el ${cuando(o.bloqueado_en)}</small></div></div>
    <p class="al-hint">No se vende en ninguna parada de esta salida.</p>
    ${adm ? `<button type="button" class="al-btn-r" onclick="alDesbloquear(${o.nro})"><i class="ti ti-lock-open"></i> Desbloquear el asiento</button>` : ""}
    ${volver}`;
  const futuro = alSalidaISO(o) > alAhoraISO(), bultos = alBultosDe(o), reimp = (o.reimpresiones || []).length;
  const pago = (AL_PAGOS.find(p => p[0] === o.pago) || AL_PAGOS[0])[1].toLowerCase();
  return `
    <div class="al-elegido"><div class="al-num vendido"><span class="al-d">${al.ver}</span></div>
      <div class="al-elegido-t"><b class="al-d">Vendido</b><span>${e(o.nombre)}</span><small>${o.mig ? e(o.tipoDoc) : "CI"} ${e(o.doc)}</small></div></div>
    <div class="al-res-info gris">
      <span><b>${e(o.origen)} → ${e(o.destino)}</b>, sale ${o.sale || o.hora}</span>
      <span>Boleto ${alNro(o.nro)} · ${alGs(o.total)} en ${pago}</span>
      <span>Vendido el ${cuando(o.vendido_en)} por ${e(o.vendedor || "")}</span>
      ${o.menor ? `<span>Con un menor en brazos: ${e(o.menor.nombre)}${o.menor.edad != null ? `, ${o.menor.edad} años` : ""}</span>` : ""}
      ${bultos ? `<span>${bultos} ${bultos === 1 ? "bulto" : "bultos"} en bodega</span>` : ""}
      ${o.embarque ? `<span>Embarque: ${o.embarque.estado === "subio" ? "subió" : "no se presentó"}</span>` : ""}
      ${reimp ? `<span>Reimpreso ${reimp} ${reimp === 1 ? "vez" : "veces"}</span>` : ""}
    </div>
    <div class="al-acc">
      <button type="button" class="al-sec" onclick="alReimprimir(${o.nro})"><i class="ti ti-printer"></i> Reimprimir</button>
      <button type="button" class="al-sec" onclick="alBajarPDF(${o.nro})"><i class="ti ti-file-type-pdf"></i> PDF</button>
      <button type="button" class="al-sec" onclick="alComprobante(${o.nro})"><i class="ti ti-file-certificate"></i> Comprobante</button>
      <button type="button" class="al-sec" onclick="alEquipaje(${o.nro})"><i class="ti ti-luggage"></i> Equipaje</button>
      ${futuro ? `<button type="button" class="al-sec" onclick="alCambiar(${o.nro})"><i class="ti ti-arrows-exchange"></i> Cambiar</button>
      <button type="button" class="al-sec" onclick="alDevolver(${o.nro})"><i class="ti ti-receipt-refund"></i> Devolver</button>` : ""}
      <button type="button" class="al-sec" onclick="alHistorial(${o.nro})"><i class="ti ti-history"></i> Historial</button>
    </div>
    ${volver}`;
}

// ─── Bloquear un asiento (administración) ───
function alBloquear() {
  const sv = alServ();
  if (!sv || al.sel == null || al.sel === "P") return;
  alModal({ titulo: `Bloquear el asiento ${al.sel}`, ancho: 480, cuerpo: `
    <p class="al-m-txt">No se va a poder vender en ninguna parada de la salida de las ${alHH(sv.h)} (${trEsc(sv.cod)}), ${alDiaTxt(alFechaDe(al.dia)).toLowerCase()}. Para desbloquearlo, tocalo en el coche.</p>
    <div class="al-chips">${["Tripulación", "Guarda", "Compromiso", "Asiento roto"].map(m => `<button type="button" class="al-chip" onclick="document.getElementById('al-bl-m').value='${m}';alChipOn(this)">${m}</button>`).join("")}</div>
    <label class="al-campo"><span>Motivo</span><input id="al-bl-m" maxlength="60" value="Tripulación" autofocus onkeydown="if(event.key==='Enter')alBloquearOk()"></label>`,
    pie: `<button type="button" class="al-sec" onclick="alModalCerrar()">Cancelar</button><button type="button" class="al-btn-r" onclick="alBloquearOk()"><i class="ti ti-lock"></i> Bloquear</button>` });
}
async function alBloquearOk() {
  const motivo = (document.getElementById("al-bl-m")?.value || "").trim();
  const r = await alPost("/api/alpha/bloqueos", { viaje: alDatosViaje(), motivo });
  if (!r) return;
  alModalCerrar(); toast(`Asiento ${r.venta.asiento} bloqueado`, "success");
  al.sel = null;
  await alTraerOcup(null, true); alPintar(false);
}
async function alDesbloquear(nro) {
  if (!confirm("¿Desbloquear este asiento? Vuelve a estar a la venta.")) return;
  const r = await alPost(`/api/alpha/ventas/${nro}/desbloquear`);
  if (!r) return;
  toast(`Asiento ${r.venta.asiento} desbloqueado`, "success");
  al.ver = null;
  await alTrasAccion();
}

// ─── Vender la vuelta con el mismo pasajero ───
function alVueltaVender() {
  const v = al.ultimo; if (!v) return;
  alLimpiarVenta();
  al.p = Object.assign(AL_PVACIO(), v.mig || {}, { doc: v.doc, nombre: v.mig ? "" : v.nombre, tipoDoc: v.tipoDocId || "CI" });
  al.x = alExtrasDe(v);
  al.vuelta = { nro: v.nro, nombre: v.nombre, origen: v.origen, destino: v.destino, sube: v.destino, baja: v.origen, svc: null };
  if (alCorredores().some(c => c.clave === v.cor)) al.cor = v.cor;
  al.lado = v.lado === "regreso" ? "ida" : "regreso"; al.dep = 0; al.sube = 0; al.baja = -1;
  alPintar(true);
  toast("Elegí el día y el horario de la vuelta", "info");
}
function alVueltaTramo() {
  const sv = alServ();
  if (!al.vuelta || !sv || al.vuelta.svc === sv.clave) return;
  al.vuelta.svc = sv.clave;
  const cam = alCamino(sv), i = alIdxDe(cam, al.vuelta.sube, 0), j = alIdxDe(cam, al.vuelta.baja, -1);
  al.sube = Math.min(i, cam.length - 2); al.baja = j > al.sube ? j : -1;
}
function alBannerVuelta() {
  const v = al.vuelta;
  if (!v) return "";
  return `<div class="al-banner al-banner-ag"><i class="ti ti-arrow-back-up"></i><span><b>Vuelta de ${trEsc(v.nombre)}</b> (boleto ${alNro(v.nro)}, ${trEsc(v.origen)} → ${trEsc(v.destino)}): elegí el día y el horario del regreso. Los datos del pasajero ya están cargados.</span>
    <button type="button" class="al-link" onclick="alVueltaCancelar()">Cancelar la vuelta</button></div>`;
}
function alVueltaCancelar() { alLimpiarVenta(); alPintar(false); }
function alEstadoServ(fecha, clave) { return ((al.servEst[fecha] || {})[clave] || {}).estado || "abierto"; }

function alCambiarRuta(c) { if (c === al.cor) return; al.cor = c; al.lado = "ida"; al.dep = 0; al.sube = 0; al.baja = -1; al.sel = null; al.aviso = ""; alPintar(true); alRefrescarOcup(); }
function alLado(l) { if (l === al.lado) return; al.lado = l; al.dep = 0; al.sube = 0; al.baja = -1; al.sel = null; al.aviso = ""; alPintar(true); alRefrescarOcup(); }
function alSalida(k) { al.dep = k; al.sube = 0; al.baja = -1; al.sel = null; al.aviso = ""; alPintar(true); alRefrescarOcup(); }
function alSube(i) { al.sube = i; const [, b] = alTramoIdx(); if (b <= i) al.baja = -1; al.sel = null; alPintar(false); }
function alBaja(i) { al.baja = i; al.sel = null; alPintar(false); }
async function alDia(i) {
  al.dia = i; al.sel = null; al.aviso = ""; al.dep = 0; al.sube = 0; al.baja = -1;
  const f = alISO(alFechaDe(i));
  if (!al.datos[f] || !al.ocup[f]) {
    al.cargando = true; alRender(false);
    try { await Promise.all([alTraer(), alTraerOcup(f)]); } finally { al.cargando = false; }
    alRender(true);
  } else { alRender(true); alRefrescarOcup(); }
}
function alInvertir() { alLado(al.lado === "ida" ? "regreso" : "ida"); }
function alAsiento(n) { al.sel = n; al.ver = null; al.aviso = ""; if (al.cobrarReserva) { al.cobrarReserva = null; al.p = AL_PVACIO(); } alPintar(false); }
function alTarifa(t) { al.tarifa = t; alRepintarPanel(); }
function alPago(p) { al.pago = p; alRepintarPanel(); }
function alCampo(id, el) {
  if (!el.isConnected) return;          // un campo que ya se borró de la pantalla no pisa los datos nuevos
  let v = el.value;
  if (["nombre", "apellidos", "nombres"].includes(id)) { v = v.toUpperCase(); el.value = v; }
  al.p[id] = v;
  alAvisoLimpio();
  if (id !== "doc") return;
  const h = document.getElementById("al-hint"), intl = alServ()?.intl;
  if (h) h.textContent = intl ? "Con el documento se completan los datos si ya viajó" : "Con la cédula se completa el nombre si ya viajó";
  alBuscarConocido(v);
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
    if (al.cambio && al.cambioV) aCobrar = Math.max(0, aCobrar - al.cambioV.total);
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
  const m = al.x.menor;
  if (m) {
    if (!m.nombre.trim()) falta.push("el nombre del menor");
    if (intl && completo && !String(m.doc || "").trim()) falta.push("el documento del menor");
  }
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
  al.cambio = null; al.cambioV = null; al.cobrarReserva = null; al.conocido = null;
  al.x = { menor: null, bultos: 0 }; al.vuelta = null; al.ver = null;
}
async function alCobrar() {
  if (al.vista !== "vender" || al.enviando) return;
  // Se suelta el campo que se estaba escribiendo antes de vaciar el formulario,
  // así su "al salir" no vuelve a poner el dato viejo en la venta siguiente
  if (document.activeElement && document.activeElement.closest && document.activeElement.closest("#al-raiz")) document.activeElement.blur();
  const sv = alServ(); if (!sv) return;
  const total = alPrecio(al.sel), [s, b] = alTramoIdx();
  const d = alDescAsiento(al.sel), pt = d ? alPrecioTramo(sv, d.clase, s, b) : null;
  if (d && !pt) { al.aviso = "Ese tramo no tiene precio: cargalo en Tarifas."; alRepintarPanel(); return; }
  const falta = alFaltan(true);
  if (falta) { al.aviso = falta; alRepintarPanel(); return; }
  const me = al.x.menor, tope = alBoletoCfg().menor_edad;
  if (me && me.edad !== "" && +me.edad > tope) { al.aviso = `El menor en brazos es hasta ${tope} años: si es más grande, paga su asiento (con la tarifa de menor).`; alRepintarPanel(); return; }
  const cambio = al.cambio ? al.cambioV : null;
  const aCobrar = cambio ? Math.max(0, total - cambio.total) : total;
  if (al.pago === "efectivo" && al.recibe && aCobrar > 0 && +al.recibe < aCobrar) { al.aviso = "Lo que recibe no alcanza: faltan " + alGs(aCobrar - al.recibe) + "."; alRepintarPanel(); return; }
  const recibe = al.pago === "efectivo" && aCobrar > 0 ? (+al.recibe || aCobrar) : null;
  const cuerpo = Object.assign({ viaje: alDatosViaje(), pasajero: alPasajero(), total, tarifa: al.tarifa, pago: al.pago, recibe, sube_idx: s, baja_idx: b }, alExtrasCuerpo());
  al.enviando = true;
  let r;
  try {
    if (cambio) r = await alPost(`/api/alpha/ventas/${cambio.nro}/cambiar`, cuerpo);
    else if (al.cobrarReserva) r = await alPost(`/api/alpha/ventas/${al.cobrarReserva}/cobrar`, cuerpo);
    else r = await alPost("/api/alpha/ventas", Object.assign({ accion: "vender" }, cuerpo));
  } finally { al.enviando = false; }
  if (!r) { await alTraerOcup(null, true); alPintar(false); return; }
  const v = r.venta;
  alTrasVender(v);
  toast(cambio ? `Boleto ${alNro(v.nro)} cambiado` : `Boleto ${alNro(v.nro)} vendido: ${v.asiento === "P" ? "parado" : "asiento " + v.asiento}`, "success");
  alLimpiarVenta();
  await alTraerOcup(null, true);
  alPintar(false);
}
async function alReservar() {
  if (al.enviando) return;
  if (document.activeElement && document.activeElement.closest && document.activeElement.closest("#al-raiz")) document.activeElement.blur();
  if (al.sel === "P") { al.aviso = "Los pasajes parados no se reservan."; alRepintarPanel(); return; }
  const falta = alFaltan(false);
  if (falta) { al.aviso = falta; alRepintarPanel(); return; }
  const viaje = alDatosViaje(), [s, b] = alTramoIdx();
  const venc = new Date(`${viaje.fecha}T${viaje.sale}`); venc.setMinutes(venc.getMinutes() - AL_RESERVA_MIN);
  const vence = alISO(venc) + "T" + String(venc.getHours()).padStart(2, "0") + ":" + String(venc.getMinutes()).padStart(2, "0");
  if (vence <= alAhoraISO()) { al.aviso = "Falta menos de una hora para la salida: ya no se reserva, se vende."; alRepintarPanel(); return; }
  al.enviando = true;
  let r;
  try { r = await alPost("/api/alpha/ventas", Object.assign({ accion: "reservar", viaje, pasajero: alPasajero(), total: alPrecio(al.sel), tarifa: al.tarifa, vence, sube_idx: s, baja_idx: b }, alExtrasCuerpo())); }
  finally { al.enviando = false; }
  if (r) toast(`Asiento ${r.venta.asiento} reservado para ${r.venta.nombre} hasta el ${alDM(vence.slice(0, 10))} ${vence.slice(11)}`, "success");
  alLimpiarVenta();
  await alTraerOcup(null, true);
  alPintar(false);
}
function alReservaCobrar(nro) {
  const v = alOcupDe(alISO(alFechaDe(al.dia))).find(x => x.nro === nro);
  if (!v) return;
  al.cobrarReserva = nro; al.tarifa = v.tarifa || "general";
  const cam = alCamino(alServ());
  al.sube = v.subeIdx ?? alIdxDe(cam, v.sube, 0); al.baja = Math.min(v.bajaIdx ?? alIdxDe(cam, v.baja, cam.length - 1), cam.length - 1);
  al.sel = v.asiento; al.ver = null;
  al.p = Object.assign(AL_PVACIO(), v.mig || {}, { doc: v.doc, nombre: v.mig ? "" : v.nombre, tipoDoc: v.tipoDocId || "CI" });
  al.x = alExtrasDe(v);
  alPintar(false);
}
async function alReservaLiberar(nro, nombre, asiento) {
  if (!confirm(`¿Liberar el asiento${asiento ? " " + asiento : ""} reservado${nombre ? " para " + nombre : ""}?`)) return;
  const r = await alPost(`/api/alpha/ventas/${nro}/liberar`);
  if (!r) return;
  toast("Reserva liberada", "success");
  al.sel = null;
  await alTraerOcup(null, true);
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
// IMPRESORA: se configura en cada computadora (papel, copias, vista previa,
// ajuste). Los navegadores no dejan elegir la impresora desde la página: se
// elige en la ventana de imprimir (Chrome la recuerda) o se pone la ticketera
// como predeterminada y Chrome con --kiosk-printing para que no pregunte.
// ════════════════════════════════════════════════════════════════════════════
const AL_COPIAS = [["original", "Original", "para el pasajero"], ["duplicado", "Duplicado", "queda en la caja"], ["triplicado", "Triplicado", "para el guarda"]];
const AL_IMP_DEF = { modo: "imprimir", papel: "80", copias: ["original", "duplicado", "triplicado"], etiquetas: true, pdf: false, escala: 100, margen: 0 };
const AL_PAPELES = [["80", "Ticketera 80 mm"], ["58", "Ticketera 58 mm"], ["A4", "Hoja A4"]];
const AL_MODOS = [["imprimir", "Imprimir enseguida"], ["vista", "Mostrar antes"], ["no", "No imprimir"]];
function alImp() {
  let c = {};
  try { c = JSON.parse(localStorage.getItem("alpha-impresora") || "{}") || {}; } catch (e) { c = {}; }
  c = Object.assign({}, AL_IMP_DEF, c);
  if (!Array.isArray(c.copias)) c.copias = AL_IMP_DEF.copias.slice();
  return c;
}
function alImpGuardar(c) { try { localStorage.setItem("alpha-impresora", JSON.stringify(c)); return true; } catch (e) { return false; } }
function alImpTxt(c = alImp()) {
  if (c.modo === "no") return "No imprime al cobrar";
  const p = (AL_PAPELES.find(x => x[0] === c.papel) || AL_PAPELES[0])[1];
  return `${p} · ${c.copias.length} ${c.copias.length === 1 ? "copia" : "copias"}${c.modo === "vista" ? " · con vista previa" : ""}`;
}
function alImpRapido(on) {
  const c = alImp();
  if (on) c.modo = c.modoOn && c.modoOn !== "no" ? c.modoOn : "imprimir";
  else { c.modoOn = c.modo !== "no" ? c.modo : "imprimir"; c.modo = "no"; }
  alImpGuardar(c); alRepintarPanel();
}
function alBoletoCfg() { return Object.assign({ presentarse_min: 15, equipaje_kg: 20, telefono: "", leyenda: "", menor_edad: 5 }, (al.cfg && al.cfg.boleto) || {}); }
function alChipOn(el) { el.parentElement.querySelectorAll(".al-chip").forEach(b => { b.classList.toggle("on", b === el); b.setAttribute("aria-pressed", b === el); }); }
function alImpModal() {
  const c = alImp(), b = alBoletoCfg(), adm = window.USUARIO_ROL === "admin" && !al.comoAgencia;
  al.impDraft = JSON.parse(JSON.stringify(c));
  const chips = (lista, val, fn) => `<div class="al-chips">${lista.map(([k, t]) => `<button type="button" class="al-chip ${k === val ? "on" : ""}" aria-pressed="${k === val}" onclick="${fn}('${k}', this)">${t}</button>`).join("")}</div>`;
  alModal({ titulo: "Impresora", ancho: 640, cuerpo: `
    <p class="al-m-txt">Se guarda en <b>esta computadora</b>: cada boletería elige la suya.</p>
    <div class="al-imp-g"><span>Papel</span>${chips(AL_PAPELES, c.papel, "alImpPapel")}</div>
    <div class="al-imp-g"><span>Al cobrar</span>${chips(AL_MODOS, c.modo, "alImpModo")}</div>
    <div class="al-imp-g"><span>Copias del boleto</span><div class="al-checks">${AL_COPIAS.map(([k, t, d]) => `<label class="al-check"><input type="checkbox" value="${k}" name="al-imp-c" ${c.copias.includes(k) ? "checked" : ""}> ${t} <small>${d}</small></label>`).join("")}</div></div>
    <div class="al-imp-g"><span>Además</span><div class="al-checks">
      <label class="al-check"><input type="checkbox" id="al-imp-et" ${c.etiquetas ? "checked" : ""}> Una etiqueta por cada bulto en bodega</label>
      <label class="al-check"><input type="checkbox" id="al-imp-pdf" ${c.pdf ? "checked" : ""}> Bajar también el PDF del boleto (para mandarlo por WhatsApp)</label></div></div>
    <div class="al-imp-g"><span>Si se corta o sale corrido</span><div class="al-fila al-imp-aj">
      <label class="al-campo ci"><span>Tamaño (%)</span><input id="al-imp-esc" type="number" min="60" max="120" step="5" value="${c.escala}"></label>
      <label class="al-campo ci"><span>Margen izq. (mm)</span><input id="al-imp-mar" type="number" min="0" max="15" step="1" value="${c.margen}"></label>
      <button type="button" class="al-sec" onclick="alImpPrueba()"><i class="ti ti-printer"></i> Imprimir una prueba</button></div></div>
    <details class="al-ayuda"><summary>Para que imprima sin preguntar y elegir la impresora</summary>
      <ol>
        <li>En Windows, poné la ticketera como <b>impresora predeterminada</b> (Configuración → Bluetooth y dispositivos → Impresoras).</li>
        <li>Cerrá Chrome. En el acceso directo de Chrome: clic derecho → Propiedades → al final de <b>Destino</b> agregá un espacio y <code>--kiosk-printing</code>. Aceptá.</li>
        <li>Abrí Chrome desde ese acceso directo: los boletos salen derecho, sin la ventana de imprimir.</li>
      </ol>
      <p>Sin eso, Chrome muestra su ventana: elegí la ticketera una vez y la recuerda. Ahí poné <b>Márgenes: ninguno</b> y sacá <b>Encabezados y pies de página</b>. Para un PDF elegí «Guardar como PDF».</p>
    </details>
    ${adm ? `<div class="al-imp-g al-imp-adm"><span>Lo que dice el boleto <small>(para todas las boleterías y agencias)</small></span>
      <div class="al-fila">
        <label class="al-campo"><span>Presentarse antes (min)</span><input id="al-bo-min" type="number" min="0" max="240" value="${b.presentarse_min}"></label>
        <label class="al-campo"><span>Equipaje incluido (kg)</span><input id="al-bo-kg" type="number" min="0" max="100" value="${b.equipaje_kg}"></label>
        <label class="al-campo"><span>Menor en brazos hasta (años)</span><input id="al-bo-menor" type="number" min="0" max="12" value="${b.menor_edad}"></label>
      </div>
      <div class="al-fila">
        <label class="al-campo"><span>Teléfono para consultas</span><input id="al-bo-tel" maxlength="60" value="${trEsc(b.telefono)}" placeholder="Ej.: 021 000 000"></label>
        <label class="al-campo"><span>Leyenda al pie</span><input id="al-bo-ley" maxlength="300" value="${trEsc(b.leyenda)}" placeholder="Ej.: no se aceptan animales"></label>
      </div></div>` : ""}`,
    pie: `<button type="button" class="al-sec" onclick="alModalCerrar()">Cancelar</button><button type="button" class="al-btn-r" onclick="alImpOk()"><i class="ti ti-device-floppy"></i> Guardar</button>` });
}
function alImpPapel(k, el) { al.impDraft.papel = k; alChipOn(el); }
function alImpModo(k, el) { al.impDraft.modo = k; alChipOn(el); }
function alImpLeer() {
  const c = Object.assign({}, al.impDraft);
  c.copias = [...document.querySelectorAll('#al-modal [name="al-imp-c"]:checked')].map(x => x.value);
  c.etiquetas = !!document.getElementById("al-imp-et")?.checked;
  c.pdf = !!document.getElementById("al-imp-pdf")?.checked;
  c.escala = Math.max(60, Math.min(120, +document.getElementById("al-imp-esc")?.value || 100));
  c.margen = Math.max(0, Math.min(15, +document.getElementById("al-imp-mar")?.value || 0));
  return c;
}
async function alImpOk() {
  const c = alImpLeer();
  if (!c.copias.length) { toast("Elegí al menos una copia del boleto", "error"); return; }
  if (!alImpGuardar(c)) { toast("Este navegador no deja guardar la configuración", "error"); return; }
  if (document.getElementById("al-bo-min")) {
    const v = id => document.getElementById(id).value;
    const b = Object.assign(alBoletoCfg(), { presentarse_min: +v("al-bo-min") || 0, equipaje_kg: +v("al-bo-kg") || 0, menor_edad: +v("al-bo-menor") || 0, telefono: v("al-bo-tel").trim(), leyenda: v("al-bo-ley").trim() });
    if (JSON.stringify(b) !== JSON.stringify(alBoletoCfg()) && !(await alCfgGuardar("boleto", b))) return;
  }
  alModalCerrar(); toast("Impresora guardada en esta computadora", "success");
  if (al.vista === "vender") alRepintarPanel();
}
function alImpPrueba() {
  const c = alImpLeer(), ahora = alAhoraISO();
  const regla = Array.from({ length: 8 }, (_, i) => `<i style="left:${i * 10}mm"><b>${i}</b></i>`).join("");
  const art = `<article class="prueba">
    <div class="pr-t">PRUEBA DE IMPRESORA</div>
    <div class="pr-s">${(AL_PAPELES.find(x => x[0] === c.papel) || AL_PAPELES[0])[1]} · tamaño ${c.escala} % · margen ${c.margen} mm</div>
    <div class="pr-regla">${regla}</div>
    <p>Tienen que verse los dos bordes de la caja y la regla entera (de 0 a 7 cm).</p>
    <p>Si se corta a la derecha, bajá el tamaño. Si sale corrido, cambiá el margen.</p>
    <div class="pr-l"><span style="font-size:11px">Letra chica 0123456789</span><b style="font-size:20px">Letra mediana</b><b style="font-size:40px;line-height:1">Grande 123</b></div>
    <div class="pie"><b>Alpha</b><span>${ahora.slice(8, 10)}/${ahora.slice(5, 7)} ${ahora.slice(11, 16)}</span></div>
  </article>`;
  alImprimir(alDocTicket("Prueba de impresora", art), "ticket", c);
}

// El documento de un ticket (boleto, etiquetas, comprobante, prueba): cada
// <article> sale en su hoja de 80 mm; el ajuste del papel se agrega al imprimir
function alDocTicket(titulo, arts) {
  return `<!doctype html><html lang="es"><head><meta charset="utf-8"><title>${trEsc(titulo)}</title>
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

.et .et-l{margin-top:8px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.08em}
.et .et-d{font-weight:900;font-size:38px;line-height:.95;font-stretch:62%;margin-top:2px;overflow-wrap:anywhere}
.reimp{letter-spacing:.04em!important;font-size:12px!important}.as-t .baja{overflow-wrap:anywhere}
.et .et-s{margin-top:6px;font-size:12.5px;font-weight:700}
.et .et-p{margin-top:8px;padding-top:6px;border-top:1.5px dashed #000;font-weight:800;font-size:15px}
.et .et-n{display:flex;align-items:baseline;gap:8px;margin-top:6px}.et .et-n b{font-weight:900;font-size:46px;line-height:1;font-stretch:80%}.et .et-n span{font-size:15px;font-weight:700}
.et .et-c{margin-top:10px;padding-top:6px;border-top:1.5px dashed #000;font-size:10.5px}
.cv .cv-t{margin-top:10px;padding-top:8px;border-top:1.5px dashed #000;font-weight:900;font-size:22px;line-height:1.05;font-stretch:80%}
.cv .cv-p{margin:8px 0 0;font-size:12.5px;line-height:1.45}.cv .cv-p.s{font-size:11px}
.cv .r{display:flex;justify-content:space-between;gap:8px;font-size:12.5px;padding:3px 0;border-bottom:1px dashed #000}
.cv .r.f{font-size:16px;font-weight:900;border-bottom:2px solid #000}
.cv .fi{margin-top:34px;border-top:1px solid #000;text-align:center;font-size:11px;padding-top:3px}
.prueba{border:2px solid #000}.pr-t{font-weight:900;font-size:20px}.pr-s{font-size:11px;margin-top:2px}
.pr-regla{position:relative;height:12mm;margin:8px 0;border-bottom:2px solid #000}.pr-regla i{position:absolute;bottom:0;height:5mm;border-left:2px solid #000}.pr-regla i b{position:absolute;bottom:5mm;left:1px;font-size:10px;font-style:normal}
.prueba p{font-size:11.5px;margin:4px 0}.pr-l{display:flex;flex-direction:column;gap:4px;margin-top:8px}
</style></head><body>${arts}</body></html>`;
}
// El papel elegido: 58 mm achica todo, A4 pone los tickets de a varios por hoja
function alAjusteTicket(c) {
  const esc = (c.escala || 100) / 100, m = c.margen || 0;
  if (c.papel === "A4") return `<style>@page{size:A4;margin:10mm}body{display:flex;flex-wrap:wrap;align-content:flex-start;gap:5mm;zoom:${esc}}article{break-after:auto!important;page-break-after:auto!important;break-inside:avoid;page-break-inside:avoid;outline:1px dashed #888}</style>`;
  const z = (c.papel === "58" ? 58 / 80 : 1) * esc;
  return `<style>@page{size:${c.papel === "58" ? 58 : 80}mm auto;margin:0}body{zoom:${z.toFixed(4)}}${m ? `body{padding-left:${(m / z).toFixed(2)}mm}` : ""}</style>`;
}
function alImprimir(html, tipo = "ticket", c) {
  if (tipo === "210mm") tipo = "hoja";
  c = c || alImp();
  const hoja = tipo === "hoja";
  const ancho = hoja || c.papel === "A4" ? "210mm" : c.papel === "58" ? "58mm" : "80mm";
  if (!hoja) html = html.replace("</head>", alAjusteTicket(c) + "</head>");
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
// Imprime según la configuración: enseguida o mostrando antes cómo sale
function alMandarImprimir(html, titulo) {
  const c = alImp();
  if (c.modo !== "vista") return alImprimir(html, "ticket", c);
  const ancho = c.papel === "A4" ? "210mm" : c.papel === "58" ? "58mm" : "80mm";
  alModal({ titulo: titulo || "Vista previa", ancho: c.papel === "A4" ? 900 : 460,
    cuerpo: `<div class="al-previa"><iframe id="al-previa-f" title="Cómo sale impreso" style="width:${ancho}"></iframe></div>`,
    pie: `<button type="button" class="al-sec" onclick="alModalCerrar()">Cerrar</button><button type="button" class="al-btn-r" onclick="alPreviaImprimir()" autofocus><i class="ti ti-printer"></i> Imprimir</button>` });
  const f = document.getElementById("al-previa-f");
  if (f) f.srcdoc = html.replace("</head>", alAjusteTicket(c) + "</head>");
}
function alPreviaImprimir() { const f = document.getElementById("al-previa-f"); if (f && f.contentWindow) { f.contentWindow.focus(); f.contentWindow.print(); } }
function alBajarPDF(nro, abrir) {
  const a = document.createElement("a");
  a.href = `/api/alpha/ventas/${nro}/pdf${abrir ? "" : "?descargar=1"}`;
  if (abrir) a.target = "_blank"; else a.download = `boleto-001-001-${alNro(nro)}.pdf`;
  document.body.appendChild(a); a.click(); a.remove();
}
// Después de cobrar: el boleto (con las copias elegidas), las etiquetas y el PDF
function alTrasVender(v) {
  al.ultimo = v;
  const c = alImp();
  if (c.modo !== "no") {
    let arts = alBoletoArts(v, c.copias.length ? c.copias : ["original"]);
    if (c.etiquetas && alBultosDe(v)) arts += alEtiquetasArts(v);
    alMandarImprimir(alDocTicket(`Boleto ${alNro(v.nro)}`, arts), `Boleto ${alNro(v.nro)}`);
  }
  if (c.pdf) setTimeout(() => alBajarPDF(v.nro), c.modo === "imprimir" ? 1500 : 0);
}

// ════════════════════════════════════════════════════════════════════════════
// EL BOLETO: original, duplicado y triplicado en papel de 80 mm, una por hoja
// ════════════════════════════════════════════════════════════════════════════
function alBultosDe(v) { return (+v.bultos || 0) + (v.equipaje || []).reduce((a, e) => a + (+e.bultos || 0), 0); }
function alCabTicket() {
  const b = alBoletoCfg();
  return `<div class="cab"><img src="${location.origin}/static/logo.png" alt=""><div><b class="n">La Santaniana</b><span>RUC [RUC], timbrado [número]<br>vence [fecha]${b.telefono ? `<br>Tel. ${trEsc(b.telefono)}` : ""}</span></div></div>`;
}
function alBoletoArts(v, copias, reimp) {
  copias = copias || alImp().copias;
  const e = trEsc, fechaD = alDeISO(v.fecha), bo = alBoletoCfg();
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
  const reimps = v.reimpresiones || [], ur = reimps[reimps.length - 1];
  const rm = reimp && ur ? `<div class="reimp">REIMPRESIÓN N.º ${reimps.length} · ${ur.el.slice(8, 10)}/${ur.el.slice(5, 7)} ${ur.el.slice(11, 16)}</div>` : reimp ? `<div class="reimp">REIMPRESIÓN</div>` : "";
  const cab = `
    ${alCabTicket()}
    ${rm}
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
  const bultos = alBultosDe(v);
  const extra = `${v.menor ? `<span>Con un menor en brazos: ${e(v.menor.nombre)}${v.menor.edad != null ? `, ${v.menor.edad} años` : ""}${v.menor.doc ? `, doc. ${e(v.menor.doc)}` : ""}</span>` : ""}${bultos ? `<span>Bultos en bodega: ${bultos}</span>` : ""}`;
  const pas = `<div class="pas"><b>${e(v.nombre)}</b><span>${docTxt}</span>${v.mig ? `<span>${e(v.mig.nacionalidad)}, nac. ${e(String(v.mig.nac || "").split("-").reverse().join("/"))}</span>` : ""}${extra}</div>`;
  const precio = (detalle) => `
    <div class="pre">
      <div class="r"><span>${e(d.tipo)}, tarifa ${e(tarifa)}</span><span>${fmtNum(v.total)}</span></div>
      <div class="t"><b>Total Gs.</b><b class="tg">${fmtNum(v.total)}</b></div>
      <span class="p">${detalle}</span>
    </div>`;
  const pie = (a, b) => `<div class="pie"><b>${a}</b><span>${b}</span></div><div class="maq">Maqueta de Alpha: sin valor fiscal</div>`;
  const efectivo = v.pago === "efectivo" && v.recibe ? ` Recibió ${fmtNum(v.recibe)}, vuelto ${fmtNum(v.recibe - v.total)}.` : "";
  const cambiado = v.cambios && v.cambios.length ? ` Cambio del boleto: antes ${alDM(v.cambios[v.cambios.length - 1].antes.fecha)} ${v.cambios[v.cambios.length - 1].antes.sale || ""}.` : "";
  const nota = `Mostrá este boleto al subir. Presentate ${bo.presentarse_min} minutos antes de la salida. Equipaje incluido: ${bo.equipaje_kg} kg.${v.mig ? " Viajá con el mismo documento que figura acá." : ""}${bo.leyenda ? " " + e(bo.leyenda) : ""}`;
  const out = {
    original: `<article>${cab}${ruta(true)}${asiento(true)}${pas}${precio(`Pagó con ${pago}.${cambiado} ${vendedor}`)}
      <div class="nota">${nota}</div>${pie("Original", "para el pasajero")}</article>`,
    duplicado: `<article>${cab}${ruta(false)}${asiento(false)}${pas}${precio(`Pagó con ${pago}.${efectivo}${cambiado} ${vendedor}`)}${pie("Duplicado", "queda en la caja")}</article>`,
    triplicado: `<article class="tri">
      <div class="doc top"><b class="n">La Santaniana</b><b>Boleto ${alNro(v.nro)}</b></div>
      ${rm}
      <div class="tri-s">${alDiaTxt(fechaD).split(" de ")[0]}, sale ${sale}<br>${e(servicio)}</div>
      <div class="as">${nroAs(true)}
        <div class="as-t mid"><span>Baja en</span><b class="baja">${e(v.destino.toUpperCase())}</b><small>Sube en ${e(v.origen)}</small></div></div>
      ${pas}${pie("Triplicado", "para el guarda")}</article>`,
  };
  return AL_COPIAS.map(c => c[0]).filter(k => copias.includes(k)).map(k => out[k]).join("");
}
function alBoletoHTML(v) { return alDocTicket(`Boleto 001-001-${alNro(v.nro)}`, alBoletoArts(v)); }
// Una etiqueta por bulto, con el talón para el pasajero
function alEtiquetasArts(v, desde = 1, hasta) {
  const tot = alBultosDe(v), e = trEsc, f = alDeISO(v.fecha);
  hasta = Math.min(hasta || tot, tot);
  let out = "";
  for (let i = desde; i <= hasta; i++) out += `<article class="et">
    <div class="doc top"><b class="n">La Santaniana</b><b>Boleto ${alNro(v.nro)}</b></div>
    <div class="et-l">Equipaje · baja en</div>
    <div class="et-d">${e(v.destino.toUpperCase())}</div>
    <div class="et-s">${alDiaTxt(f).split(" ")[0]} ${alDM(v.fecha)}, sale ${v.sale || v.hora} · ${e(v.tramo || "")}</div>
    <div class="et-p">${e(v.nombre)}</div>
    <div class="et-n"><b>${i}</b><span>de ${tot} ${tot === 1 ? "bulto" : "bultos"}</span></div>
    <div class="et-c">✂ Talón para el pasajero · Boleto ${alNro(v.nro)} · bulto ${i} de ${tot} · ${e(v.destino)}</div>
  </article>`;
  return out;
}
// Comprobante de viaje (constancia para el trabajo, el colegio…)
function alComprobanteArt(v) {
  const e = trEsc, f = alDeISO(v.fecha), ahora = alAhoraISO();
  const viajo = v.embarque && v.embarque.estado === "subio", paso = alSalidaISO(v) < ahora;
  const doc = v.mig ? `${v.tipoDoc} ${v.doc}` : `cédula ${v.doc}`;
  return `<article class="cv">
    ${alCabTicket()}
    <div class="cv-t">Comprobante de viaje</div>
    <p class="cv-p">Dejamos constancia de que <b>${e(v.nombre)}</b>, ${e(doc)}, ${viajo ? "viajó" : paso ? "tenía pasaje para viajar" : "tiene pasaje para viajar"} con La Santaniana el <b>${alDiaTxt(f).toLowerCase()} de ${f.getFullYear()}</b>, en el servicio ${e(v.tramo || "")} que sale a las <b>${v.sale || v.hora}</b>, de <b>${e(v.origen)}</b> a <b>${e(v.destino)}</b>${v.asiento === "P" ? ", con pasaje parado" : `, en el asiento ${v.asiento}`}.</p>
    <p class="cv-p">Boleto 001-001-${alNro(v.nro)}, por Gs. ${fmtNum(v.total)}.${v.menor ? ` Con un menor en brazos: ${e(v.menor.nombre)}.` : ""}</p>
    <p class="cv-p s">Se extiende a pedido del pasajero el ${ahora.slice(8, 10)}/${ahora.slice(5, 7)}/${ahora.slice(0, 4)} a las ${ahora.slice(11, 16)}, por ${e(alVendedor())}.</p>
    <div class="fi">Firma y sello</div>
    <div class="maq">Maqueta de Alpha: sin valor fiscal</div>
  </article>`;
}
function alExcesoArt(v, eq) {
  const e = trEsc, fl = (a, b, c) => `<div class="r ${c || ""}"><span>${a}</span><b>${b}</b></div>`;
  return `<article class="cv">
    ${alCabTicket()}
    <div class="cv-t">Exceso de equipaje</div>
    <p class="cv-p"><b>${e(v.nombre)}</b> · Boleto ${alNro(v.nro)}<br>${alDM(v.fecha)} ${v.sale || v.hora}, ${e(v.origen)} → ${e(v.destino)}</p>
    ${eq.bultos ? fl("Bultos que agrega", eq.bultos) : ""}${eq.kg ? fl("Kilos de más", fmtNum(eq.kg)) : ""}${eq.nota ? fl("Nota", e(eq.nota)) : ""}
    ${fl("Forma de pago", (AL_PAGOS.find(p => p[0] === eq.pago) || AL_PAGOS[0])[1])}
    ${fl("Total Gs.", fmtNum(eq.monto), "f")}
    <p class="cv-p s">${eq.el.slice(8, 10)}/${eq.el.slice(5, 7)} ${eq.el.slice(11, 16)} · ${e(eq.por || "")}</p>
    <div class="pie"><b>Exceso</b><span>para el pasajero</span></div><div class="maq">Maqueta de Alpha: sin valor fiscal</div>
  </article>`;
}

// ─── Buscar un boleto (en lo que ya está en pantalla o en el servidor) ───
function alVentaLocal(nro) {
  const de = l => (l || []).find(x => x && x.nro === nro);
  return de(al.pasLista) || de(al.manPas) || de(Object.values(al.ocup).flat()) || (al.ultimo && al.ultimo.nro === nro ? al.ultimo : null);
}
async function alVenta(nro, fresca) {
  if (!fresca) { const v = alVentaLocal(nro); if (v) return v; }
  const r = await api(`/api/alpha/ventas/${nro}`);
  if (!r || !r.venta) { toast((r && (r.msg || r.error)) || "No se encontró el boleto", "error"); return null; }
  return r.venta;
}
function alGuardarVenta(v) {
  [al.pasLista, al.manPas, ...Object.values(al.ocup)].forEach(l => {
    if (!l) return;
    const i = l.findIndex(x => x && x.nro === v.nro);
    if (i >= 0) l[i] = Object.assign({}, l[i], v);
  });
  if (al.ultimo && al.ultimo.nro === v.nro) al.ultimo = v;
}
// Después de devolver, anular, desbloquear…: se repinta lo que se está viendo
async function alTrasAccion() {
  al.ocup = {};
  if (al.vista === "pasajes") return alVistaPasajes(false);
  if (al.vista === "manifiesto") { al.manClave = ""; return alVistaManifiesto(false); }
  if (al.vista === "vender") { await alTraerOcup(null, true); return alPintar(false); }
  return alRender(false);
}

// ─── Reimprimir: qué copias, y queda registrado ───
async function alReimprimir(nro) {
  const v = await alVenta(nro, true);
  if (!v) return;
  if (v.estado !== "vendido") { toast("Solo se reimprime un boleto vendido", "error"); return; }
  const rs = v.reimpresiones || [], ur = rs[rs.length - 1], bultos = alBultosDe(v);
  const op = (k, t, d, si) => `<label class="al-check"><input type="checkbox" name="al-rc" value="${k}" ${si ? "checked" : ""}> ${t} <small>${d}</small></label>`;
  alModal({ titulo: `Reimprimir el boleto ${alNro(nro)}`, ancho: 500, cuerpo: `
    <p class="al-m-txt"><b>${trEsc(v.nombre)}</b> · ${alDM(v.fecha)} ${v.sale || v.hora}, ${trEsc(v.origen)} → ${trEsc(v.destino)}, ${v.asiento === "P" ? "parado" : "asiento " + v.asiento}.<br>
      ${rs.length ? `Ya se reimprimió ${rs.length} ${rs.length === 1 ? "vez" : "veces"} (la última el ${alDM(ur.el.slice(0, 10))} a las ${ur.el.slice(11, 16)}, ${trEsc(ur.por || "")}).` : "Es la primera reimpresión."} Sale marcado «REIMPRESIÓN» y queda registrado.</p>
    <div class="al-checks">
      ${AL_COPIAS.map(([k, t, d]) => op(k, t, d, k === "original")).join("")}
      ${bultos ? op("etiquetas", "Etiquetas de equipaje", `${bultos} ${bultos === 1 ? "bulto" : "bultos"}`) : ""}
      ${op("comprobante", "Comprobante de viaje", "constancia para el pasajero")}
    </div>`,
    pie: `<button type="button" class="al-sec" onclick="alModalCerrar()">Cancelar</button>
      <button type="button" class="al-sec" onclick="alBajarPDF(${nro})"><i class="ti ti-file-type-pdf"></i> PDF</button>
      <button type="button" class="al-btn-r" onclick="alReimprimirOk(${nro})" autofocus><i class="ti ti-printer"></i> Reimprimir</button>` });
}
async function alReimprimirOk(nro) {
  const copias = [...document.querySelectorAll('#al-modal [name="al-rc"]:checked')].map(x => x.value);
  if (!copias.length) { toast("Elegí qué reimprimir", "error"); return; }
  const r = await alPost(`/api/alpha/ventas/${nro}/reimpresion`, { copias });
  if (!r) return;
  alModalCerrar();
  const v = r.venta; alGuardarVenta(v);
  let arts = alBoletoArts(v, copias, true);
  if (copias.includes("etiquetas")) arts += alEtiquetasArts(v);
  if (copias.includes("comprobante")) arts += alComprobanteArt(v);
  alMandarImprimir(alDocTicket(`Boleto ${alNro(nro)} (reimpresión)`, arts), `Reimpresión del boleto ${alNro(nro)}`);
  toast(`Reimprimiendo el boleto ${alNro(nro)} (vez ${(v.reimpresiones || []).length})`, "success");
}
async function alComprobante(nro) {
  const v = await alVenta(nro);
  if (!v) return;
  alMandarImprimir(alDocTicket(`Comprobante de viaje ${alNro(nro)}`, alComprobanteArt(v)), "Comprobante de viaje");
}

// ─── Equipaje: bultos que se agregan y exceso cobrado (entra en la caja) ───
async function alEquipaje(nro) {
  const v = await alVenta(nro, true);
  if (!v) return;
  const b = alBultosDe(v), kg = alBoletoCfg().equipaje_kg;
  al.eqPago = "efectivo";
  const num = `oninput="this.value=this.value.replace(/\\D/g,'')?fmtNum(+this.value.replace(/\\D/g,'')):''"`;
  alModal({ titulo: `Equipaje del boleto ${alNro(nro)}`, ancho: 540, cuerpo: `
    <p class="al-m-txt"><b>${trEsc(v.nombre)}</b> · ${alDM(v.fecha)} ${v.sale || v.hora}, ${trEsc(v.origen)} → ${trEsc(v.destino)}.<br>
      ${b ? `Ya tiene ${b} ${b === 1 ? "bulto" : "bultos"} en bodega.` : "No tiene bultos cargados."} El boleto incluye ${kg} kg.</p>
    <div class="al-fila">
      <label class="al-campo ci"><span>Bultos que agrega</span><input id="al-eq-b" inputmode="numeric" value="1" autofocus></label>
      <label class="al-campo ci"><span>Kilos de más</span><input id="al-eq-kg" inputmode="numeric" placeholder="0"></label>
      <label class="al-campo"><span>Cobra por el exceso (Gs.)</span><input id="al-eq-m" inputmode="numeric" placeholder="0: no se cobra" ${num}></label>
    </div>
    <div class="al-chips" role="group" aria-label="Forma de pago">${AL_PAGOS.map(([k, t]) => `<button type="button" class="al-chip ${k === "efectivo" ? "on" : ""}" onclick="al.eqPago='${k}';alChipOn(this)">${t}</button>`).join("")}</div>
    <label class="al-campo"><span>Nota (opcional)</span><input id="al-eq-n" maxlength="120" placeholder="Ej.: caja con repuestos"></label>
    <p class="al-hint">Se imprime una etiqueta por cada bulto nuevo y, si se cobra, el recibo del exceso. Lo cobrado entra en tu caja.</p>`,
    pie: `<button type="button" class="al-sec" onclick="alModalCerrar()">Cancelar</button><button type="button" class="al-btn-r" onclick="alEquipajeOk(${nro})"><i class="ti ti-luggage"></i> Registrar</button>` });
}
async function alEquipajeOk(nro) {
  const n = id => +String(document.getElementById(id)?.value || "").replace(/\D/g, "") || 0;
  const cuerpo = { bultos: n("al-eq-b"), kg: n("al-eq-kg"), monto: n("al-eq-m"), pago: al.eqPago || "efectivo", nota: document.getElementById("al-eq-n")?.value || "" };
  if (!cuerpo.bultos && !cuerpo.kg && !cuerpo.monto) { toast("Poné los bultos, los kilos o lo que se cobra", "error"); return; }
  const r = await alPost(`/api/alpha/ventas/${nro}/equipaje`, cuerpo);
  if (!r) return;
  alModalCerrar();
  const v = r.venta; alGuardarVenta(v);
  const eq = v.equipaje[v.equipaje.length - 1], antes = alBultosDe(v) - (+eq.bultos || 0);
  let arts = "";
  if (eq.monto) arts += alExcesoArt(v, eq);
  if (eq.bultos) arts += alEtiquetasArts(v, antes + 1, antes + eq.bultos);
  if (arts) alMandarImprimir(alDocTicket(`Equipaje ${alNro(nro)}`, arts), "Equipaje");
  toast(`Equipaje registrado${eq.monto ? `: ${alGs(eq.monto)}` : ""}`, "success");
  await alTrasAccion();
}

// ─── Historial de un boleto: todo lo que le pasó ───
async function alHistorial(nro) {
  const v = await alVenta(nro, true);
  if (!v) return;
  const ev = [], add = (el, ic, txt, por) => { if (el) ev.push({ el, ic, txt, por }); };
  const pagoTxt = p => ((AL_PAGOS.find(x => x[0] === p) || ["", p || ""])[1] || "").toLowerCase();
  add(v.reservado_en, "bookmark", `Reservado, asiento ${v.asiento}`, "");
  add(v.bloqueado_en, "lock", `Asiento bloqueado: ${v.motivo || v.nombre}`, v.bloqueado_por);
  (v.movs || []).forEach(m => {
    if (m.t === "venta") add(m.el, "ticket", `Vendido: ${alGs(m.monto)} en ${pagoTxt(m.pago)}`, m.vendedor);
    else if (m.t === "cobro") add(m.el, "cash", `Cobró la reserva: ${alGs(m.monto)} en ${pagoTxt(m.pago)}`, m.vendedor);
    else if (m.t === "devolucion") add(m.el, "receipt-refund", `Devuelto: se le devolvió ${alGs(-m.monto)}`, m.vendedor);
    else if (m.t === "anulacion") add(m.el, "ban", `Anulado: ${alGs(-m.monto)}`, m.vendedor);
  });
  (v.cambios || []).forEach(c => {
    const dif = (v.movs || []).find(m => m.t === "cambio" && m.el === c.el);
    add(c.el, "arrows-exchange", `Cambiado. Antes: ${alDM(c.antes.fecha)} ${c.antes.sale || ""}, ${c.antes.origen || ""} → ${c.antes.destino || ""}, ${c.antes.asiento === "P" ? "parado" : "asiento " + c.antes.asiento}${dif ? ` · diferencia ${dif.monto < 0 ? "−" : ""}${alGs(Math.abs(dif.monto))}` : ""}`, c.por);
  });
  (v.reimpresiones || []).forEach((r, i) => add(r.el, "printer", `Reimpresión N.º ${i + 1}${r.copias && r.copias.length ? ": " + r.copias.join(", ") : ""}`, r.por));
  (v.equipaje || []).forEach(q => add(q.el, "luggage", `Equipaje: ${[q.bultos ? `${q.bultos} ${q.bultos === 1 ? "bulto" : "bultos"}` : "", q.kg ? `${fmtNum(q.kg)} kg` : "", q.monto ? `cobró ${alGs(q.monto)}` : "sin cargo"].filter(Boolean).join(", ")}${q.nota ? ` (${q.nota})` : ""}`, q.por));
  (v.transbordos || []).forEach(t => add(t.el, "arrows-shuffle", `Transbordo (${t.motivo}). Antes: ${alDM(t.antes.fecha)} ${t.antes.sale || t.antes.hora || ""}${t.antes.coche ? ", coche " + t.antes.coche : ""}, ${t.antes.asiento === "P" ? "parado" : "asiento " + t.antes.asiento}`, t.por));
  if (v.embarque) add(v.embarque.el, v.embarque.estado === "subio" ? "bus" : "user-x", v.embarque.estado === "subio" ? "Subió al coche" : "No se presentó", v.embarque.por);
  add(v.liberada_en, "lock-open", "Reserva liberada", v.liberada_por);
  ev.sort((a, b) => a.el.localeCompare(b.el));
  alModal({ titulo: `Historial del boleto ${alNro(nro)}`, ancho: 620, cuerpo: `
    <p class="al-m-txt"><b>${trEsc(v.nombre)}</b> · ${alDM(v.fecha)} ${v.sale || v.hora}, ${trEsc(v.origen || "")} → ${trEsc(v.destino || "")} · <span class="al-est ${alEstado(v)}">${AL_ESTADOS[alEstado(v)] || v.estado}</span></p>
    <ol class="al-hist">${ev.map(x => `<li><i class="ti ti-${x.ic}"></i><div><b>${trEsc(x.txt)}</b><small>${alDM(x.el.slice(0, 10))}/${x.el.slice(0, 4)} ${x.el.slice(11, 16)}${x.por ? " · " + trEsc(x.por) : ""}</small></div></li>`).join("") || "<li>Sin movimientos</li>"}</ol>`,
    pie: `<button type="button" class="al-sec" onclick="alModalCerrar()">Cerrar</button>` });
}

// ════════════════════════════════════════════════════════════════════════════
// PASAJES: consultar, reimprimir, cambiar, devolver, anular; reservas
// ════════════════════════════════════════════════════════════════════════════
const AL_ESTADOS = { vendido: "Vendido", reserva: "Reserva", anulado: "Anulado", devuelto: "Devuelto", liberada: "Liberada", vencida: "Vencida", bloqueado: "Bloqueado" };
function alEstado(v) { return v.estado === "reserva" && !alReservaViva(v) ? "vencida" : v.estado; }
async function alVistaPasajes(animar, sinTraer) {
  if (!sinTraer) {
    if (!document.getElementById("al-pas-lista")) content.innerHTML = alShell(`<div class="al-vacio"><i class="ti ti-loader-2"></i><b>Trayendo los pasajes…</b></div>`, animar);
    const r = await api(`/api/alpha/ventas?q=${encodeURIComponent(al.pas.q)}&estado=${al.pas.estado}&limite=200`);
    if (al.vista !== "pasajes") return;
    al.pasLista = (r && r.ventas) || []; al.pasCuenta = (r && r.cuenta) || {}; al.pasTotal = (r && r.total) || 0;
  }
  const est = al.pas.estado, lista = al.pasLista, cuenta = al.pasCuenta || {};
  const todas = Object.values(cuenta).reduce((a, n) => a + n, 0);
  const ahora = alAhoraISO(), hoy = ahora.slice(0, 10);
  const fila = v => {
    const e = alEstado(v), futuro = alSalidaISO(v) > ahora;
    const acc = [];
    if (e === "vendido") {
      acc.push(`<button type="button" class="al-ic" title="Reimprimir" aria-label="Reimprimir" onclick="alReimprimir(${v.nro})"><i class="ti ti-printer"></i></button>`);
      acc.push(`<button type="button" class="al-ic" title="Equipaje: bultos y exceso" aria-label="Equipaje" onclick="alEquipaje(${v.nro})"><i class="ti ti-luggage"></i></button>`);
      if (futuro) acc.push(`<button type="button" class="al-ic" title="Cambiar fecha, servicio o asiento" aria-label="Cambiar" onclick="alCambiar(${v.nro})"><i class="ti ti-arrows-exchange"></i></button>`);
      if (futuro) acc.push(`<button type="button" class="al-ic" title="Devolver" aria-label="Devolver" onclick="alDevolver(${v.nro})"><i class="ti ti-receipt-refund"></i></button>`);
      if ((v.vendido_en || "").slice(0, 10) === hoy && futuro) acc.push(`<button type="button" class="al-ic rojo" title="Anular (solo el mismo día)" aria-label="Anular" onclick="alAnular(${v.nro})"><i class="ti ti-ban"></i></button>`);
    } else if (e === "reserva") {
      acc.push(`<button type="button" class="al-ic" title="Ir a cobrarla" aria-label="Cobrar la reserva" onclick="alIrAReserva(${v.nro})"><i class="ti ti-cash"></i></button>`);
      acc.push(`<button type="button" class="al-ic rojo" title="Liberar el asiento" aria-label="Liberar" onclick="alReservaLiberar(${v.nro}, '${trEsc(v.nombre).replace(/'/g, "\\'")}', '${v.asiento}')"><i class="ti ti-lock-open"></i></button>`);
    } else if (e === "bloqueado" && window.USUARIO_ROL === "admin") {
      acc.push(`<button type="button" class="al-ic" title="Desbloquear el asiento" aria-label="Desbloquear" onclick="alDesbloquear(${v.nro})"><i class="ti ti-lock-open"></i></button>`);
    }
    if (e !== "bloqueado") acc.push(`<button type="button" class="al-ic" title="Historial del boleto" aria-label="Historial" onclick="alHistorial(${v.nro})"><i class="ti ti-history"></i></button>`);
    return `<tr class="${e}">
      <td class="al-t-n"><b>${alNro(v.nro)}</b>${v.cambios && v.cambios.length ? `<small title="Cambiado">cambiado</small>` : ""}</td>
      <td><b>${alDM(v.fecha)}</b> ${v.sale || v.hora}<small>${trEsc(v.tramo || "")}${v.coche && !alEsAgencia() ? " · coche " + trEsc(v.coche) : ""}</small></td>
      <td>${trEsc(v.origen)} → ${trEsc(v.destino)}</td>
      <td class="al-t-c">${v.asiento === "P" ? "P" : v.asiento}</td>
      <td><b>${trEsc(v.nombre)}</b><small>${e === "bloqueado" ? "Asiento bloqueado" : `${v.mig ? trEsc(v.tipoDoc) : "CI"} ${trEsc(v.doc)}`}${v.menor ? " · con un menor" : ""}${alBultosDe(v) ? ` · ${alBultosDe(v)} b.` : ""}</small></td>
      <td class="al-t-m">${fmtNum(v.total)}${v.devuelto != null ? `<small>devuelto ${fmtNum(v.devuelto)}</small>` : ""}</td>
      <td><span class="al-est ${e}">${AL_ESTADOS[e] || e}</span>${e === "reserva" ? `<small>vence ${alDM(v.vence.slice(0, 10))} ${v.vence.slice(11, 16)}</small>` : ""}${v.embarque ? `<small>${v.embarque.estado === "subio" ? "subió" : "no se presentó"}</small>` : ""}${(v.reimpresiones || []).length ? `<small>reimpreso ${v.reimpresiones.length}</small>` : ""}${!alEsAgencia() ? `<small>${trEsc(v.vendedor || "")}</small>` : ""}</td>
      <td class="al-t-a">${acc.join("")}</td></tr>`;
  };
  const q = document.getElementById("al-pas-q"), foco = document.activeElement === q, pos = q ? q.selectionStart : 0;
  content.innerHTML = alShell(`
    <div class="al-vista">
      <div class="al-v-cab"><h1 class="al-d">Pasajes</h1><span>Buscá un boleto o una reserva para reimprimir, cambiar, devolver o anular.${alEsAgencia() ? " Ves los de tu agencia." : ""}</span></div>
      <div class="al-busca al-busca-pas"><i class="ti ti-search" aria-hidden="true"></i>
        <input id="al-pas-q" type="search" autocomplete="off" value="${trEsc(al.pas.q)}" placeholder="Número de boleto, documento, nombre, destino o fecha" oninput="alPasBuscar(this.value)" aria-label="Buscar pasajes"></div>
      <div class="al-chips al-pas-est" role="group" aria-label="Estado">
        <button type="button" class="al-chip ${!est ? "on" : ""}" onclick="al.pas.estado='';alVistaPasajes(false)">Todos <small>${todas}</small></button>
        ${["vendido", "reserva", "vencida", "devuelto", "anulado", "liberada", "bloqueado"].filter(k => cuenta[k]).map(k => `<button type="button" class="al-chip ${est === k ? "on" : ""}" onclick="al.pas.estado='${k}';alVistaPasajes(false)">${AL_ESTADOS[k]}s <small>${cuenta[k]}</small></button>`).join("")}
      </div>
      <div id="al-pas-lista">${lista.length ? `<div class="al-tabla-w"><table class="al-tabla">
        <thead><tr><th>Boleto</th><th>Viaje</th><th>Tramo</th><th class="al-t-c">Asiento</th><th>Pasajero</th><th class="al-t-m">Gs.</th><th>Estado</th><th></th></tr></thead>
        <tbody>${lista.map(fila).join("")}</tbody></table></div>${al.pasTotal > lista.length ? `<p class="al-nota">Se muestran los ${lista.length} más recientes de ${al.pasTotal}: buscá para encontrar los demás.</p>` : ""}`
        : `<div class="al-vacio"><i class="ti ti-receipt-off"></i><b>${todas ? "No hay pasajes con esa búsqueda" : "Todavía no hay pasajes vendidos"}</b></div>`}</div>
      ${window.USUARIO_ROL === "admin" && todas ? `<p class="al-nota"><button type="button" class="al-link" onclick="alBorrar()">Borrar todas las ventas de prueba (de todas las agencias)</button></p>` : ""}
    </div>`, animar);
  if (foco) { const n = document.getElementById("al-pas-q"); n.focus(); n.setSelectionRange(pos, pos); }
}
let _alPasTimer = null;
function alPasBuscar(v) { al.pas.q = v; clearTimeout(_alPasTimer); _alPasTimer = setTimeout(() => alVistaPasajes(false), 300); }
function alPasRefrescar() { alVistaPasajes(false); }
async function alAnular(nro) {
  const v = await alVenta(nro);
  if (!v || !confirm(`¿Anular el boleto ${alNro(nro)} de ${v.nombre}?\n\nSe devuelve todo (${alGs(v.total)}) y el asiento queda libre. Se usa para errores del mismo día.`)) return;
  const r = await alPost(`/api/alpha/ventas/${nro}/anular`);
  if (!r) return;
  toast(`Boleto ${alNro(nro)} anulado`, "success");
  al.ver = null;
  await alTrasAccion();
}
async function alDevolver(nro) {
  const v = await alVenta(nro);
  if (!v) return;
  const sug = Math.round(v.total * (1 - AL_RETENCION) / 1000) * 1000;
  alModal({ titulo: `Devolver el boleto ${alNro(nro)}`, ancho: 480, cuerpo: `
    <p class="al-m-txt"><b>${trEsc(v.nombre)}</b> · ${alDM(v.fecha)} ${v.sale || v.hora}, ${trEsc(v.origen)} → ${trEsc(v.destino)}, ${v.asiento === "P" ? "parado" : "asiento " + v.asiento}.<br>Pagó ${alGs(v.total)} con ${(AL_PAGOS.find(p => p[0] === v.pago) || AL_PAGOS[0])[1].toLowerCase()}.</p>
    <label class="al-campo"><span>Se le devuelve (Gs.)</span><input id="al-dev-m" inputmode="numeric" value="${fmtNum(sug)}" autofocus oninput="this.value=this.value.replace(/\\D/g,'')?fmtNum(+this.value.replace(/\\D/g,'')):''"></label>
    <p class="al-hint">Sugerido: el total menos ${Math.round(AL_RETENCION * 100)} % de retención (de ejemplo, hasta que se defina la regla).</p>`,
    pie: `<button type="button" class="al-sec" onclick="alModalCerrar()">Cancelar</button><button type="button" class="al-btn-r" onclick="alDevolverOk(${nro})"><i class="ti ti-receipt-refund"></i> Devolver</button>` });
}
async function alDevolverOk(nro) {
  const m = +String(document.getElementById("al-dev-m")?.value || "").replace(/\D/g, "");
  const r = await alPost(`/api/alpha/ventas/${nro}/devolver`, { monto: m });
  if (!r) return;
  alModalCerrar(); toast(`Boleto ${alNro(nro)} devuelto: ${alGs(m)}`, "success");
  al.ver = null;
  await alTrasAccion();
}
async function alIrAViaje(v) {
  const i = Math.round((alDeISO(v.fecha) - alFechaDe(0)) / 864e5);
  if (i < 0) { toast("Ese viaje ya pasó", "error"); return false; }
  al.dia = i; al.vista = "vender";
  const f = alISO(alFechaDe(i));
  al.cargando = true; alRender(false);
  try { await Promise.all([alTraer(), alTraerOcup(f, true)]); } finally { al.cargando = false; }
  al.cor = v.cor; al.lado = v.lado;
  const lista = alServicios().lista, k = lista.findIndex(x => x.clave === v.servicio);
  if (k < 0) { toast("Ese servicio ya no está en el tráfico de ese día: elegí otro", "error"); al.dep = 0; return true; }
  al.dep = k;
  const cam = alCamino(lista[k]);
  al.sube = v.subeIdx ?? alIdxDe(cam, v.sube, 0); al.baja = Math.min(v.bajaIdx ?? alIdxDe(cam, v.baja, cam.length - 1), cam.length - 1);
  return true;
}
async function alCambiar(nro) {
  const v = await alVenta(nro);
  if (!v) return;
  alLimpiarVenta();
  al.cambio = nro; al.cambioV = v; al.tarifa = v.tarifa || "general";
  al.p = Object.assign(AL_PVACIO(), v.mig || {}, { doc: v.doc, nombre: v.mig ? "" : v.nombre, tipoDoc: v.tipoDocId || "CI" });
  al.x = alExtrasDe(v);
  await alIrAViaje(v);
  al.sel = null;
  alRender(true);
}
async function alIrAReserva(nro) {
  const v = await alVenta(nro);
  if (!v) return;
  alLimpiarVenta();
  if (!(await alIrAViaje(v))) return;
  alRender(true);
  alReservaCobrar(nro);
}
async function alBorrar() {
  if (!confirm("¿Borrar TODAS las ventas, reservas, cierres de caja y liquidaciones de prueba de Alpha, de todas las agencias?\n\nNo se puede deshacer.")) return;
  const r = await api("/api/alpha/ventas", { method: "DELETE" });
  if (!r || !r.ok) { toast((r && r.msg) || "No se pudo", "error"); return; }
  alLimpiarVenta(); al.ocup = {}; al.miCaja = 0; al.reservas = 0;
  toast("Ventas de prueba borradas", "success");
  alRender(false);
}
// ════════════════════════════════════════════════════════════════════════════
// MANIFIESTO: los pasajeros de un servicio
// ════════════════════════════════════════════════════════════════════════════
function alManServicios() {
  return alTodasSalidas().map(({ c, l, k }) => alServiciosDe(c, l)[k]);
}
function alManifiestoDatos(sv, fecha) {
  const pas = (al.manPas || []).filter(v => v.fecha === fecha && v.servicio === sv.clave && (v.estado === "vendido" || alReservaViva(v)));
  const cam = alCamino(sv);
  pas.sort((a, b) => (a.asiento === "P") - (b.asiento === "P") || (+a.asiento || 0) - (+b.asiento || 0) || (a.subeIdx ?? alIdxDe(cam, a.sube, 0)) - (b.subeIdx ?? alIdxDe(cam, b.sube, 0)));
  return pas;
}
async function alVistaManifiesto(animar) {
  if (!al.cfg) await alCfgTraer();
  if (!alHoyDatos()) { alShellCargando(animar); await alTraer(); if (al.vista !== "manifiesto") return; }
  const fecha = alISO(alFechaDe(al.dia)), svs = alManServicios();
  const actual = alServ();
  if (!svs.some(s => s.clave === al.man.clave)) al.man.clave = (actual && svs.some(s => s.clave === actual.clave)) ? actual.clave : (svs[0]?.clave || "");
  const sv = svs.find(s => s.clave === al.man.clave);
  const clave = `${fecha}|${al.man.clave}`;
  if (sv && al.manClave !== clave) {
    if (!document.querySelector(".al-man-res")) alShellCargando(animar);
    const r = await api(`/api/alpha/ventas?fecha=${fecha}&servicio=${encodeURIComponent(sv.clave)}&limite=1000`);
    if (al.vista !== "manifiesto") return;
    al.manPas = (r && r.ventas) || []; al.manClave = clave;
  }
  const adm = window.USUARIO_ROL === "admin";
  let cuerpo;
  if (!sv) cuerpo = `<div class="al-vacio"><i class="ti ti-calendar-off"></i><b>No hay servicios este día</b></div>`;
  else {
    const pas = alManifiestoDatos(sv, fecha), pl = alPlano(sv), asi = alAsientos(pl);
    const vend = pas.filter(v => v.estado === "vendido"), res = pas.filter(v => v.estado === "reserva");
    const bloq = (al.manPas || []).filter(v => v.fecha === fecha && v.servicio === sv.clave && v.estado === "bloqueado");
    const cam = alCamino(sv);
    const baja = {}; vend.forEach(v => { baja[v.baja] = (baja[v.baja] || 0) + 1; });
    const menores = vend.filter(v => v.menor).length, bultos = vend.reduce((a, v) => a + alBultosDe(v), 0);
    const subio = vend.filter(v => v.embarque && v.embarque.estado === "subio").length, novino = vend.filter(v => v.embarque && v.embarque.estado === "no_vino").length;
    const emb = v => {
      if (v.estado !== "vendido") return "";
      const st = v.embarque ? v.embarque.estado : "";
      if (!adm) return st === "subio" ? "Subió" : st === "no_vino" ? "No vino" : "";
      return `<div class="al-emb" role="group" aria-label="Embarque de ${trEsc(v.nombre)}">
        <button type="button" class="al-emb-b ${st === "subio" ? "on si" : ""}" aria-pressed="${st === "subio"}" onclick="alEmbarque(${v.nro}, '${st === "subio" ? "" : "subio"}')"><i class="ti ti-check"></i> Subió</button>
        <button type="button" class="al-emb-b ${st === "no_vino" ? "on no" : ""}" aria-pressed="${st === "no_vino"}" onclick="alEmbarque(${v.nro}, '${st === "no_vino" ? "" : "no_vino"}')"><i class="ti ti-x"></i> No vino</button></div>`;
    };
    cuerpo = `
      <div class="al-man-res">
        <div><span>Pasajeros</span><b class="al-d">${vend.length}${menores ? ` <small>+ ${menores} ${menores === 1 ? "menor" : "menores"} en brazos</small>` : ""}</b></div>
        <div><span>Reservas</span><b class="al-d">${res.length}</b></div>
        <div><span>Asientos</span><b class="al-d">${asi.length}${pl.parados ? ` <small>+ ${pl.parados} parados</small>` : ""}${bloq.length ? ` <small>· ${bloq.length} bloq.</small>` : ""}</b></div>
        <div><span>Bultos en bodega</span><b class="al-d">${bultos}</b></div>
        <div><span>Recaudado</span><b class="al-d">${alGs(vend.reduce((a, v) => a + v.total, 0))}</b></div>
        ${vend.length ? `<div><span>Embarque</span><b class="al-d">${subio} <small>subieron${novino ? ` · ${novino} no vinieron` : ""} · ${vend.length - subio - novino} sin marcar</small></b></div>` : ""}
        ${cam.length > 2 ? `<div class="al-man-baja"><span>Bajan en</span><p>${cam.slice(1).map(p => `${trEsc(p.nombre)}: <b>${baja[p.nombre] || 0}</b>`).join(" · ")}</p></div>` : ""}
      </div>
      ${pas.length ? `<div class="al-tabla-w"><table class="al-tabla">
        <thead><tr><th class="al-t-c">Asiento</th><th>Pasajero</th><th>Documento</th><th>Sube</th><th>Baja</th>${sv.intl ? "<th>Nacionalidad</th><th>Nacimiento</th><th>Sexo</th>" : ""}<th class="al-t-c">Bultos</th><th>Boleto</th><th>Estado</th><th>Embarque</th></tr></thead>
        <tbody>${pas.map(v => `<tr class="${v.estado}">
          <td class="al-t-c"><b>${v.asiento}</b></td><td><b>${trEsc(v.nombre)}</b>${v.menor ? `<small>con un menor en brazos: ${trEsc(v.menor.nombre)}${v.menor.edad != null ? ` (${v.menor.edad})` : ""}</small>` : ""}</td><td>${v.mig ? trEsc(v.tipoDoc) : "CI"} ${trEsc(v.doc)}</td>
          <td>${trEsc(v.sube)}</td><td>${trEsc(v.baja)}</td>
          ${sv.intl ? `<td>${trEsc(v.mig?.nacionalidad || "")}</td><td>${v.mig?.nac ? alDM(v.mig.nac) + "/" + v.mig.nac.slice(0, 4) : ""}</td><td>${trEsc(v.mig?.sexo || "")}</td>` : ""}
          <td class="al-t-c">${alBultosDe(v) || ""}</td>
          <td>${alNro(v.nro)}<small>${trEsc(v.vendedor || "")}</small></td><td><span class="al-est ${v.estado}">${AL_ESTADOS[v.estado]}</span></td><td>${emb(v)}</td></tr>`).join("")}</tbody></table></div>`
        : `<div class="al-vacio"><i class="ti ti-users"></i><b>Todavía no hay pasajeros en este servicio</b></div>`}
      ${bloq.length ? `<p class="al-nota"><i class="ti ti-lock"></i> Asientos bloqueados: ${bloq.map(v => `<b>${v.asiento}</b> (${trEsc(v.motivo || v.nombre)})`).join(", ")}</p>` : ""}`;
  }
  const est = sv ? alEstadoServ(fecha, sv.clave) : "abierto";
  const vendSv = sv ? alManifiestoDatos(sv, fecha).filter(v => v.estado === "vendido") : [];
  content.innerHTML = alShell(`
    <div class="al-vista">
      <div class="al-v-cab"><h1 class="al-d">Manifiesto</h1><span>La lista de pasajeros de cada servicio, para el guarda y para migraciones. Marcá quién subió.</span></div>
      <div class="al-filtros"><div class="al-dias" role="group" aria-label="Día del viaje">${alChipsDias()}</div></div>
      <div class="al-man-sel">
        <label class="al-campo"><span>Servicio</span><select onchange="al.man.clave=this.value;al.manClave='';alVistaManifiesto(false)">${svs.map(s => `<option value="${trEsc(s.clave)}" ${s.clave === al.man.clave ? "selected" : ""}>${s.hora} · ${trEsc(s.origen_nombre)} → ${trEsc(s.llega_nombre)} · ${trEsc(s.cod)}${s.coche ? " · coche " + trEsc(s.coche) : ""}</option>`).join("")}</select></label>
        ${sv ? `<button type="button" class="al-btn-r" onclick="alManImprimir()"><i class="ti ti-printer"></i> Imprimir${sv.intl ? " (para migraciones)" : ""}</button>
          <button type="button" class="al-sec" onclick="alHojaRutaImprimir()"><i class="ti ti-route"></i> Hoja de ruta</button>
          <button type="button" class="al-sec" onclick="alManCSV()"><i class="ti ti-file-spreadsheet"></i> CSV</button>
          ${adm && vendSv.some(v => !v.embarque) ? `<button type="button" class="al-sec" onclick="alEmbarqueTodos()"><i class="ti ti-checks"></i> Los que faltan: subieron</button>` : ""}` : ""}
      </div>
      ${sv ? `<p class="al-nota">${alDiaTxt(alFechaDe(al.dia))} · ${sv.coche ? "Coche " + trEsc(sv.coche) + (sv.modelo ? ", " + trEsc(sv.modelo) : "") + (sv.reemplazo ? ` (reemplaza al ${trEsc(sv.reemplazo.de)})` : "") : "Coche a confirmar"}${sv.tripulacion.length ? " · Tripulación: " + sv.tripulacion.map(trEsc).join(" y ") : ""}${est !== "abierto" ? ` · <b class="al-rojo-t">${est === "cancelado" ? "Servicio cancelado" : "Venta cerrada"}</b>` : ""}</p>` : ""}
      ${cuerpo}
    </div>`, animar);
}
async function alEmbarque(nro, estado) {
  const r = await alPost(`/api/alpha/ventas/${nro}/embarque`, { estado });
  if (!r) return;
  alGuardarVenta(r.venta);
  if (!estado) { const v = (al.manPas || []).find(x => x.nro === nro); if (v) delete v.embarque; }
  alVistaManifiesto(false);
}
async function alEmbarqueTodos() {
  const fecha = alISO(alFechaDe(al.dia)), sv = alManServicios().find(s => s.clave === al.man.clave);
  if (!sv) return;
  const faltan = alManifiestoDatos(sv, fecha).filter(v => v.estado === "vendido" && !v.embarque);
  if (!faltan.length || !confirm(`¿Marcar que subieron los ${faltan.length} pasajeros que faltan marcar?`)) return;
  for (const v of faltan) {
    const r = await api(`/api/alpha/ventas/${v.nro}/embarque`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ estado: "subio" }) });
    if (r && r.venta) alGuardarVenta(r.venta);
  }
  toast(`${faltan.length} marcados como que subieron`, "success");
  alVistaManifiesto(false);
}
function alManCSV() {
  const fecha = alISO(alFechaDe(al.dia)), sv = alManServicios().find(s => s.clave === al.man.clave);
  if (!sv) return;
  const pas = alManifiestoDatos(sv, fecha).filter(v => v.estado === "vendido");
  alCSV(`manifiesto-${fecha}-${sv.hora.replace(":", "")}.csv`, [["Asiento", "Pasajero", "Documento", "Sube", "Baja", "Nacionalidad", "Nacimiento", "Sexo", "Menor en brazos", "Bultos", "Boleto", "Vendió", "Embarque"]]
    .concat(pas.map(v => [v.asiento, v.nombre, `${v.mig ? v.tipoDoc : "CI"} ${v.doc}`, v.sube, v.baja, v.mig?.nacionalidad || "", v.mig?.nac || "", v.mig?.sexo || "",
      v.menor ? v.menor.nombre : "", alBultosDe(v) || "", alNro(v.nro), v.vendedor || "", v.embarque ? (v.embarque.estado === "subio" ? "subió" : "no vino") : ""])));
}
function alCSV(nombre, filas) {
  const q = x => `"${String(x ?? "").replace(/"/g, '""')}"`;
  const blob = new Blob(["﻿" + filas.map(f => f.map(q).join(";")).join("\r\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = nombre;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}
// Hoja de ruta: parada por parada, a qué hora pasa, cuántos suben y bajan
function alHojaRuta(sv, pas) {
  const cam = alCamino(sv), n = cam.length;
  let abordo = 0;
  return cam.map((p, i) => {
    const s = pas.filter(v => Math.min(v.subeIdx ?? alIdxDe(cam, v.sube, 0), n - 1) === i);
    const b = pas.filter(v => Math.min(v.bajaIdx ?? alIdxDe(cam, v.baja, n - 1), n - 1) === i);
    abordo += s.length - b.length;
    const o = alOffset(cam, i);
    return { nombre: p.nombre, hora: o != null ? alHH(sv.h + o) : i === 0 ? alHH(sv.h) : i === n - 1 && sv.dur ? alHH(sv.h + sv.dur) : "", suben: s, bajan: b, abordo,
      bultosBajan: b.reduce((a, v) => a + alBultosDe(v), 0) };
  });
}
function alHojaRutaImprimir(clave) {
  const fecha = alISO(alFechaDe(al.dia));
  const sv = alManServicios().find(s => s.clave === (clave || al.man.clave));
  if (!sv) return;
  const pas = (clave ? alOcupDe(fecha).filter(v => v.servicio === sv.clave && v.estado === "vendido" && v.mia) : alManifiestoDatos(sv, fecha).filter(v => v.estado === "vendido"));
  const hr = alHojaRuta(sv, pas), e = trEsc;
  const html = `<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Hoja de ruta ${fecha} ${sv.hora}</title>
<style>@page{size:A4;margin:12mm}*{box-sizing:border-box}body{margin:0;font-family:Arial,sans-serif;color:#000;font-size:11.5px}
.cab{display:flex;justify-content:space-between;align-items:flex-end;border-bottom:2px solid #000;padding-bottom:6px;margin-bottom:8px}h1{font-size:18px;margin:0}
.dat{display:flex;flex-wrap:wrap;gap:4px 22px;margin-bottom:10px}table{width:100%;border-collapse:collapse}th,td{border:1px solid #999;padding:5px 6px;text-align:left;vertical-align:top}
th{background:#eee;font-size:10px;text-transform:uppercase}.c{text-align:center}.n{font-size:10.5px;color:#333}.f{font-weight:700}
.firmas{display:flex;gap:40px;margin-top:40px}.firmas div{flex:1;border-top:1px solid #000;padding-top:4px;text-align:center}.maq{margin-top:12px;font-size:9.5px;color:#555;text-align:center}</style></head><body>
<div class="cab"><div><b>LA SANTANIANA</b><h1>Hoja de ruta</h1></div><span>Impresa ${alAhoraISO().replace("T", " ")}</span></div>
<div class="dat"><span><b>Fecha:</b> ${alDiaTxt(alDeISO(fecha))}</span><span><b>Sale:</b> ${sv.hora}</span><span><b>Servicio:</b> ${e(sv.cod)}</span>
<span><b>Coche:</b> ${e(sv.coche || "a confirmar")}</span><span><b>Tripulación:</b> ${e(sv.tripulacion.join(" y ") || "—")}</span><span><b>Pasajeros:</b> ${pas.length}${pas.some(v => v.menor) ? ` + ${pas.filter(v => v.menor).length} menores en brazos` : ""}</span></div>
<table><thead><tr><th class="c">#</th><th>Parada</th><th class="c">Hora</th><th class="c">Suben</th><th class="c">Bajan</th><th class="c">A bordo</th><th class="c">Bultos que bajan</th><th>Asientos que bajan</th><th>Llegó</th></tr></thead><tbody>
${hr.map((p, i) => `<tr><td class="c">${i + 1}</td><td class="f">${e(p.nombre)}</td><td class="c">${p.hora}</td><td class="c">${p.suben.length || ""}</td><td class="c">${p.bajan.length || ""}</td><td class="c">${i < hr.length - 1 ? p.abordo : ""}</td><td class="c">${p.bultosBajan || ""}</td><td class="n">${p.bajan.map(v => v.asiento).join(", ")}</td><td style="width:70px"></td></tr>`).join("")}
</tbody></table>
<div class="firmas"><div>Chofer</div><div>Guarda</div><div>Despacho</div></div>
<div class="maq">Maqueta de Alpha: sin valor fiscal</div></body></html>`;
  alImprimir(html, "hoja");
}
function alShellCargando(animar) {
  content.innerHTML = alShell(`<div class="al-vacio"><i class="ti ti-loader-2"></i><b>Trayendo los datos…</b></div>`, animar);
}
function alManImprimir() {
  const fecha = alISO(alFechaDe(al.dia)), sv = alManServicios().find(s => s.clave === al.man.clave);
  if (!sv) return;
  const pas = alManifiestoDatos(sv, fecha).filter(v => v.estado === "vendido"), e = trEsc, intl = sv.intl;
  const menores = pas.filter(v => v.menor).length, bultos = pas.reduce((a, v) => a + alBultosDe(v), 0);
  const emb = v => v.embarque ? (v.embarque.estado === "subio" ? "✓" : "✗") : "☐";
  const filas = pas.map((v, i) => `<tr><td>${i + 1}</td><td class="c"><b>${v.asiento}</b></td><td><b>${e(v.mig ? v.mig.apellidos : v.nombre)}</b>${v.mig ? `<br>${e(v.mig.nombres)}` : ""}${v.menor ? `<br><span class="m">+ menor en brazos: ${e(v.menor.nombre)}${v.menor.edad != null ? ` (${v.menor.edad})` : ""}${v.menor.doc ? `, doc. ${e(v.menor.doc)}` : ""}</span>` : ""}</td>
    <td>${v.mig ? e(v.tipoDoc) : "CI"} ${e(v.doc)}</td>${intl ? `<td>${e(v.mig?.nacionalidad || "")}</td><td>${v.mig?.nac ? v.mig.nac.split("-").reverse().join("/") : ""}</td><td class="c">${e(v.mig?.sexo || "")}</td><td>${e(v.mig?.residencia || "")}</td>` : ""}
    <td>${e(v.sube)}</td><td>${e(v.baja)}</td><td class="c">${alBultosDe(v) || ""}</td><td class="c">${emb(v)}</td></tr>`).join("");
  const hr = alHojaRuta(sv, pas);
  const html = `<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Manifiesto ${fecha} ${sv.hora}</title>
<style>@page{size:A4 ${intl ? "landscape" : "portrait"};margin:12mm}*{box-sizing:border-box}body{margin:0;font-family:Arial,sans-serif;color:#000;font-size:11px}
.cab{display:flex;justify-content:space-between;align-items:flex-end;border-bottom:2px solid #000;padding-bottom:6px;margin-bottom:8px}
h1{font-size:18px;margin:0}h2{font-size:13px;margin:14px 0 6px}.cab span{font-size:11px}.dat{display:flex;flex-wrap:wrap;gap:4px 22px;margin-bottom:8px;font-size:11.5px}
table{width:100%;border-collapse:collapse}th,td{border:1px solid #999;padding:4px 5px;text-align:left;vertical-align:top}th{background:#eee;font-size:10px;text-transform:uppercase}
.c{text-align:center}.m{font-size:10px}.firmas{display:flex;gap:40px;margin-top:40px}.firmas div{flex:1;border-top:1px solid #000;padding-top:4px;text-align:center}
.maq{margin-top:12px;font-size:9.5px;color:#555;text-align:center}</style></head><body>
<div class="cab"><div><b>LA SANTANIANA</b><h1>Manifiesto de pasajeros${intl ? " · Viaje internacional" : ""}</h1></div><span>Impreso ${alAhoraISO().replace("T", " ")}</span></div>
<div class="dat"><span><b>Fecha:</b> ${alDiaTxt(alDeISO(fecha))}</span><span><b>Sale:</b> ${sv.hora}</span><span><b>Servicio:</b> ${e(sv.cod)}</span>
<span><b>De:</b> ${e(sv.origen_nombre)} <b>a</b> ${e(sv.llega_nombre)}</span><span><b>Coche:</b> ${e(sv.coche || "a confirmar")}${sv.modelo ? " (" + e(sv.modelo) + ")" : ""}</span>
<span><b>Tripulación:</b> ${e(sv.tripulacion.join(" y ") || "—")}</span><span><b>Pasajeros:</b> ${pas.length}${menores ? ` + ${menores} menores en brazos (${pas.length + menores} personas)` : ""}</span><span><b>Bultos:</b> ${bultos}</span></div>
<table><thead><tr><th>#</th><th class="c">Asiento</th><th>${intl ? "Apellidos y nombres" : "Pasajero"}</th><th>Documento</th>${intl ? "<th>Nacionalidad</th><th>Nacimiento</th><th>Sexo</th><th>Reside en</th>" : ""}<th>Sube</th><th>Baja</th><th class="c">Bultos</th><th class="c">Subió</th></tr></thead>
<tbody>${filas || `<tr><td colspan="${intl ? 12 : 8}" class="c">Sin pasajeros</td></tr>`}</tbody></table>
${hr.length > 2 ? `<h2>Por parada</h2><table><thead><tr><th>Parada</th><th class="c">Hora</th><th class="c">Suben</th><th class="c">Bajan</th><th class="c">A bordo</th></tr></thead><tbody>${hr.map((p, i) => `<tr><td>${e(p.nombre)}</td><td class="c">${p.hora}</td><td class="c">${p.suben.length || ""}</td><td class="c">${p.bajan.length || ""}</td><td class="c">${i < hr.length - 1 ? p.abordo : ""}</td></tr>`).join("")}</tbody></table>` : ""}
<div class="firmas"><div>Chofer</div><div>Guarda</div><div>Boletería</div></div>
<div class="maq">Maqueta de Alpha: sin valor fiscal</div></body></html>`;
  alImprimir(html, "hoja");
}
// ════════════════════════════════════════════════════════════════════════════
// CAJA: lo que entró y salió por vendedor, y el cierre
// ════════════════════════════════════════════════════════════════════════════
const AL_MOV_TXT = { venta: "Venta", cobro: "Cobro de reserva", cambio: "Diferencia por cambio", devolucion: "Devolución", anulacion: "Anulación",
  equipaje: "Exceso de equipaje", ingreso: "Ingreso", egreso: "Egreso" };
async function alVistaCaja(animar) {
  const fecha = al.caja.fecha || alISO(new Date());
  if (!document.querySelector(".al-caja-v")) alShellCargando(animar);
  const d = await api(`/api/alpha/caja?fecha=${fecha}&usuario=${encodeURIComponent(al.caja.usuario || "")}`);
  if (al.vista !== "caja" || !d || !d.movs) return;
  al.caja.usuario = d.usuario; al.cajaDatos = d;
  const propia = !d.yo || d.usuario === d.yo, hoy = fecha === alISO(new Date());
  const cierres = d.cierres, ultimo = cierres.length ? cierres[cierres.length - 1].hasta : "";
  const movs = d.movs, abiertos = movs.filter(m => m.el > ultimo);
  const tot = alTotales(abiertos);
  const ie = m => m.t === "ingreso" || m.t === "egreso";
  const fila = m => `<tr class="${m.el <= ultimo ? "cerrado" : ""}"><td>${m.el.slice(11, 16)}</td><td>${AL_MOV_TXT[m.t] || m.t}</td><td>${m.nro ? alNro(m.nro) : "—"}</td>
    <td>${trEsc(m.nombre)}${ie(m) ? "" : `<small>${trEsc(m.origen)} → ${trEsc(m.destino)}</small>`}</td>
    <td>${(AL_PAGOS.find(p => p[0] === m.pago) || ["", m.pago || ""])[1]}</td><td class="al-t-m ${m.monto < 0 ? "neg" : ""}">${m.monto < 0 ? "−" : ""}${fmtNum(Math.abs(m.monto))}</td>
    <td class="al-t-a">${ie(m) && propia && m.cierre_id == null && m.liquidacion_id == null ? `<button type="button" class="al-ic rojo" title="Borrar este movimiento" aria-label="Borrar" onclick="alCajaMovBorrar(${m.id})"><i class="ti ti-trash"></i></button>` : ""}</td></tr>`;
  content.innerHTML = alShell(`
    <div class="al-vista al-caja-v">
      <div class="al-v-cab"><h1 class="al-d">Caja</h1><span>Lo que cobró y devolvió cada vendedor, los ingresos y egresos sueltos y el cierre del turno.</span></div>
      <div class="al-man-sel">
        <label class="al-campo"><span>Día</span><input type="date" value="${fecha}" max="${alISO(new Date())}" onchange="al.caja.fecha=this.value;alVistaCaja(false)"></label>
        <label class="al-campo"><span>Vendedor</span><select onchange="al.caja.usuario=this.value;alVistaCaja(false)">${d.vendedores.map(x => `<option value="${trEsc(x.usuario)}" ${x.usuario === d.usuario ? "selected" : ""}>${trEsc(x.vendedor)}</option>`).join("")}</select></label>
        ${propia && hoy ? `<button type="button" class="al-sec" onclick="alCajaMov('ingreso')"><i class="ti ti-circle-plus"></i> Ingreso</button>
          <button type="button" class="al-sec" onclick="alCajaMov('egreso')"><i class="ti ti-circle-minus"></i> Egreso</button>` : ""}
        ${abiertos.length ? `<button type="button" class="al-btn-r" onclick="alCerrarCaja()"><i class="ti ti-lock"></i> Cerrar la caja</button>` : ""}
      </div>
      <div class="al-man-res">
        ${AL_PAGOS.map(([k, t]) => `<div><span>${t}</span><b class="al-d">${alGs(tot.pago[k] || 0)}</b></div>`).join("")}
        <div><span>Devoluciones y anulaciones</span><b class="al-d neg">${tot.salidas ? "− " : ""}${alGs(tot.salidas)}</b></div>
        ${tot.ingresos || tot.egresos ? `<div><span>Ingresos / egresos</span><b class="al-d">${alGs(tot.ingresos)} <small>/ − ${fmtNum(tot.egresos)}</small></b></div>` : ""}
        <div class="fuerte"><span>Efectivo en caja</span><b class="al-d">${alGs(tot.efectivoNeto)}</b></div>
        <div><span>Boletos</span><b class="al-d">${tot.boletos}</b></div>
      </div>
      ${ultimo ? `<p class="al-nota">Última caja cerrada a las ${ultimo.slice(11, 16)}. Arriba se suma lo que entró después.</p>` : ""}
      ${movs.length ? `<div class="al-tabla-w"><table class="al-tabla">
        <thead><tr><th>Hora</th><th>Movimiento</th><th>Boleto</th><th>Pasajero o concepto</th><th>Forma de pago</th><th class="al-t-m">Gs.</th><th></th></tr></thead>
        <tbody>${movs.slice().reverse().map(fila).join("")}</tbody></table></div>`
        : `<div class="al-vacio"><i class="ti ti-cash-off"></i><b>Sin movimientos ese día</b></div>`}
      ${cierres.length ? `<h2 class="al-d al-h2">Cierres del día</h2><div class="al-cierres">${cierres.map((c, i) => `<div class="al-cierre"><b>Cierre ${i + 1}</b><span>a las ${c.hasta.slice(11, 16)} · ${c.tot.boletos} boletos · efectivo ${alGs(c.tot.efectivoNeto)}</span><button type="button" class="al-link" onclick="alCierreImprimir(${c.id})">Reimprimir</button></div>`).join("")}</div>` : ""}
    </div>`, animar);
}
// Ingresos y egresos de la caja que no son de un boleto (entran en la liquidación de la agencia)
function alCajaMov(tipo) {
  const ing = tipo === "ingreso";
  al.ieTipo = tipo; al.iePago = "efectivo";
  const sug = ing ? ["Fondo de caja", "Encomienda", "Otro ingreso"] : ["Gasto por cuenta de la empresa", "Viático de la tripulación", "Combustible", "Otro gasto"];
  alModal({ titulo: ing ? "Registrar un ingreso" : "Registrar un egreso", ancho: 520, cuerpo: `
    <div class="al-chips">${sug.map(x => `<button type="button" class="al-chip" onclick="document.getElementById('al-ie-c').value='${x}';alChipOn(this)">${x}</button>`).join("")}</div>
    <label class="al-campo"><span>Concepto</span><input id="al-ie-c" maxlength="120" autofocus></label>
    <label class="al-campo"><span>Monto (Gs.)</span><input id="al-ie-m" inputmode="numeric" oninput="this.value=this.value.replace(/\\D/g,'')?fmtNum(+this.value.replace(/\\D/g,'')):''"></label>
    <div class="al-chips" role="group" aria-label="Forma de pago">${AL_PAGOS.map(([k, t]) => `<button type="button" class="al-chip ${k === "efectivo" ? "on" : ""}" onclick="al.iePago='${k}';alChipOn(this)">${t}</button>`).join("")}</div>
    <p class="al-hint">${alEsAgencia() || window.USUARIO_ROL === "agencia" ? `Entra en tu caja y en la liquidación de la agencia: ${ing ? "un ingreso suma" : "un egreso resta"} a lo que tenés que depositar.` : "Entra en tu caja del día."}</p>`,
    pie: `<button type="button" class="al-sec" onclick="alModalCerrar()">Cancelar</button><button type="button" class="al-btn-r" onclick="alCajaMovOk()"><i class="ti ti-device-floppy"></i> Registrar</button>` });
}
async function alCajaMovOk() {
  const concepto = (document.getElementById("al-ie-c")?.value || "").trim();
  const monto = +String(document.getElementById("al-ie-m")?.value || "").replace(/\D/g, "");
  if (!concepto) { toast("Poné el concepto", "error"); return; }
  if (!monto) { toast("Poné el monto", "error"); return; }
  const r = await alPost("/api/alpha/caja/movimiento", { tipo: al.ieTipo, concepto, monto, pago: al.iePago || "efectivo" });
  if (!r) return;
  alModalCerrar(); toast(`${al.ieTipo === "ingreso" ? "Ingreso" : "Egreso"} registrado: ${alGs(monto)}`, "success");
  al.caja.fecha = alISO(new Date());
  alTraerOcup(null, true).then(() => { if (al.vista === "caja") alVistaCaja(false); });
}
async function alCajaMovBorrar(id) {
  if (!confirm("¿Borrar este movimiento de la caja?")) return;
  const r = await api(`/api/alpha/caja/movimiento/${id}`, { method: "DELETE" });
  if (!r || !r.ok) { toast((r && (r.msg || r.error)) || "No se pudo", "error"); return; }
  toast("Movimiento borrado", "success");
  alTraerOcup(null, true).then(() => { if (al.vista === "caja") alVistaCaja(false); });
}
function alTotales(movs) {
  const t = { pago: {}, salidas: 0, efectivoNeto: 0, boletos: 0, entradas: 0, ingresos: 0, egresos: 0 };
  movs.forEach(m => {
    if (m.t === "ingreso") t.ingresos += m.monto;
    else if (m.t === "egreso") t.egresos += -m.monto;
    else if (m.monto >= 0) { t.pago[m.pago] = (t.pago[m.pago] || 0) + m.monto; t.entradas += m.monto; }
    else t.salidas += -m.monto;
    // una anulación de una venta con tarjeta no saca efectivo de la caja
    if (m.pago === "efectivo") t.efectivoNeto += m.monto;
    if (m.t === "venta" || m.t === "cobro") t.boletos += 1;
  });
  return t;
}
async function alCerrarCaja() {
  const d = al.cajaDatos; if (!d) return;
  const vend = (d.vendedores.find(x => x.usuario === d.usuario) || {}).vendedor || d.usuario;
  if (!confirm(`¿Cerrar la caja de ${vend}?`)) return;
  const r = await alPost("/api/alpha/caja/cerrar", { fecha: d.fecha, usuario: d.usuario });
  if (!r) return;
  toast("Caja cerrada", "success");
  await alVistaCaja(false);
  alCierreImprimir(r.cierre.id);
}
function alCierreImprimir(id) {
  const d = al.cajaDatos, c = d && d.cierres.find(x => x.id === id);
  if (!c) return;
  const movs = d.movs.filter(m => m.el > c.desde && m.el <= c.hasta);
  const t = c.tot, fl = (a, b, f) => `<div class="r ${f || ""}"><span>${a}</span><b>${b}</b></div>`;
  const html = `<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Cierre de caja</title>
<style>@page{size:80mm auto;margin:0}*{box-sizing:border-box}body{margin:0;font-family:Arial,sans-serif;color:#000}
article{width:80mm;padding:5mm 4mm}h1{font-size:18px;margin:4px 0 2px}.s{font-size:11px}.r{display:flex;justify-content:space-between;font-size:12.5px;padding:3px 0;border-bottom:1px dashed #000}
.r.f{font-size:15px;font-weight:900;border-bottom:2px solid #000}.m{font-size:10.5px;margin-top:8px}.m div{display:flex;justify-content:space-between;gap:6px}
.fi{margin-top:30px;border-top:1px solid #000;text-align:center;font-size:11px;padding-top:3px}.maq{margin-top:8px;font-size:9.5px;text-align:center}</style></head><body><article>
<b>LA SANTANIANA</b><h1>Cierre de caja</h1><div class="s">${trEsc(c.vendedor)} · ${alDM(c.fecha)}/${c.fecha.slice(0, 4)} · ${c.desde ? "desde las " + c.desde.slice(11, 16) + " " : ""}hasta las ${c.hasta.slice(11, 16)}</div><br>
${AL_PAGOS.map(([k, n]) => fl(n, fmtNum(t.pago[k] || 0))).join("")}
${fl("Devoluciones y anulaciones", "− " + fmtNum(t.salidas))}
${t.ingresos ? fl("Ingresos", fmtNum(t.ingresos)) : ""}${t.egresos ? fl("Egresos", "− " + fmtNum(t.egresos)) : ""}
${fl("Boletos", t.boletos)}
${fl("Efectivo en caja", fmtNum(t.efectivoNeto), "f")}
<div class="m">${movs.map(m => `<div><span>${m.el.slice(11, 16)} ${AL_MOV_TXT[m.t] || m.t} ${m.nro ? alNro(m.nro) : trEsc(m.concepto || "")}</span><span>${m.monto < 0 ? "−" : ""}${fmtNum(Math.abs(m.monto))}</span></div>`).join("")}</div>
<div class="fi">Firma del vendedor</div><div class="fi">Recibió</div><div class="maq">Maqueta de Alpha: sin valor fiscal</div></article></body></html>`;
  alMandarImprimir(html, "Cierre de caja");
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
        <div class="al-card-cab"><h2 class="al-d">Qué plano usa cada coche</h2><span>«Automático» lo deduce del modelo (todo es Marcopolo): Volare o Senior → micro, Paradiso 1800 DD → AO01, los 8x2 → AO03, el resto → Paradiso un piso.</span></div>
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
  const a = alAsientos(d, true);
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
function alPlanoMax(d) { return Math.max(0, ...alAsientos(d, true).map(a => a.n)); }
function alPlanoCelda(pi, fi, pos) {
  const f = al.pla.draft.pisos[pi].filas[fi];
  f[pos] = f[pos] != null ? null : alPlanoMax(al.pla.draft) + 1;
  alVistaPlanos(false);
}
function alPlanoNumero(pi, fi, pos, inp) {
  const n = +inp.value.replace(/\D/g, "");
  if (!n || n > 199) { inp.value = al.pla.draft.pisos[pi].filas[fi][pos]; toast("El número va de 1 a 199", "error"); return; }
  const otro = alAsientos(al.pla.draft, true).find(a => a.n === n && !(a.piso === pi && a.fila === fi && a.pos === pos));
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
