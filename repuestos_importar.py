"""
repuestos_importar.py — Cargar repuestos al inventario desde un Excel (La Santaniana)

Para no cargar uno por uno a mano: se sube la planilla del depósito, el
sistema busca la hoja con los repuestos, muestra qué va a cargar (lo nuevo, lo
que ya estaba, lo que tiene problemas) y recién al confirmar los da de alta.

Reconoce las columnas por su título, escritas como sea:
  Código del repuesto · Repuesto o Insumo (o Descripción) · Marca ·
  Nº de coche · Proveedor · Precio unitario · y si las tiene,
  Cantidad / Stock, Stock mínimo, Categoría y Unidad.

  · El proveedor se busca en el listado de la empresa aunque esté escrito
    distinto ("JUHU SRL" es "Juhu S.R.L."), así no se duplica.
  · La categoría se deduce del nombre (filtro → Filtros, ruleman →
    Rulemanes...) y se puede cambiar antes de importar.
  · Un código que ya está en el inventario no se toca.
  · La cantidad de cada repuesto entra como "Stock inicial" (un movimiento de
    entrada), igual que al cargarlo a mano.
"""

import io
import re
import unicodedata

from flask import Blueprint, request, jsonify, session
from db_compat import get_connection

import repuestos_db as rdb

bp_rep_imp = Blueprint("repuestos_importar", __name__)

MAX_FILAS = 3000


def _norm(t):
    t = unicodedata.normalize("NFD", str(t or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^a-z0-9ñ]+", " ", t).split())


# ════════════════════════════════════════════════════════════════════════════
# LEER LA PLANILLA
# ════════════════════════════════════════════════════════════════════════════

# Qué título corresponde a cada dato (se mira en orden: el primero que encaja)
COLUMNAS = [
    ("minimo", ("stock minimo", "minimo", "stock min")),
    ("codigo", ("codigo", "cod ", "cod.", "nro de parte", "numero de parte", "n de parte")),
    ("proveedor", ("proveedor",)),
    ("marca", ("marca",)),
    ("coche", ("coche", "interno", "aplicacion", "vehiculo", "movil")),
    ("precio", ("precio", "costo", "valor")),
    ("cantidad", ("cantidad", "stock", "existencia", "cant")),
    ("categoria", ("categoria", "rubro")),
    ("unidad", ("unidad", "u m", "medida")),
    ("descripcion", ("repuesto", "insumo", "descripcion", "articulo", "producto", "nombre", "detalle")),
]


def _columna(titulo):
    t = _norm(titulo) + " "
    for clave, palabras in COLUMNAS:
        for p in palabras:
            if _norm(p) and (t.startswith(_norm(p) + " ") or (" " + _norm(p) + " ") in (" " + t)):
                return clave
    return None


def _encabezado(filas):
    """La fila de títulos: la primera (de las 15 de arriba) que tiene al menos
    código y nombre del repuesto."""
    for i, f in enumerate(filas[:15]):
        mapa = {}
        for j, v in enumerate(f):
            if v is None or str(v).strip() == "":
                continue
            c = _columna(v)
            if c and c not in mapa:
                mapa[c] = j
        if "codigo" in mapa and "descripcion" in mapa:
            return i, mapa
    return None, None


def _texto(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return " ".join(str(v).split())


def _numero(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("Gs.", "").replace("Gs", "").replace("₲", "").replace(" ", "")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") >= 1 and re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def leer_excel(contenido):
    """Devuelve (hoja, filas) con la hoja de repuestos que más datos tenga."""
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(contenido), data_only=True, read_only=True)
    mejor = None
    for ws in wb.worksheets:
        filas = [list(r) for r in ws.iter_rows(values_only=True)]
        i, mapa = _encabezado(filas)
        if i is None:
            continue
        datos = []
        for k, f in enumerate(filas[i + 1:], start=i + 2):
            def val(c):
                j = mapa.get(c)
                return f[j] if j is not None and j < len(f) else None
            codigo, desc = _texto(val("codigo")), _texto(val("descripcion"))
            if not codigo and not desc:
                continue
            datos.append({
                "fila": k, "codigo": codigo, "descripcion": desc,
                "marca": _texto(val("marca")), "coche": _texto(val("coche")),
                "proveedor": _texto(val("proveedor")), "precio": _numero(val("precio")),
                "cantidad": _numero(val("cantidad")), "minimo": _numero(val("minimo")),
                "categoria": _texto(val("categoria")), "unidad": _texto(val("unidad")),
            })
        if datos and (mejor is None or len(datos) > len(mejor[1])):
            mejor = (ws.title, datos, sorted(mapa))
    wb.close()
    return mejor


# ════════════════════════════════════════════════════════════════════════════
# PREPARAR (vista previa)
# ════════════════════════════════════════════════════════════════════════════

# Del nombre del repuesto a la categoría del depósito (en este orden)
CATEGORIA_POR_PALABRA = [
    ("Filtros", ("filtro", "prefiltro", "trampa de agua", "vasito", "deshidratador", "separador de agua")),
    ("Embragues / frenos", ("embrague", "freno", "pastilla", "cinta de freno", "campana", "plato de presion", "crapodina")),
    ("Rulemanes / rodamientos", ("ruleman", "rodamiento", "rolinera", "buje")),
    ("Correas y mangueras", ("correa", "manguera", "union rapida", "conexion rapida", "cano")),
    ("Tensores / bombas", ("tensor", "bomba", "polea")),
    ("Eléctricos", ("lampara", "faro", "foco", "fusible", "rele", "bateria", "alternador", "arranque",
                    "cable", "sensor", "interruptor", "led")),
    ("Tornillería / ferretería", ("tornillo", "tuerca", "arandela", "remache", "abrazadera", "bulon", "perno",
                                  "esparrago", "chaveta", "grampa")),
    ("Neumáticos", ("cubierta", "neumatico", "camara de aire", "valvula de rueda")),
    ("Lubricantes y aditivos", ("lubricante", "grasa", "fluido", "liquido de freno", "refrigerante", "aditivo",
                                "anticongelante", "urea", "arla")),
]


def categoria_de(nombre):
    n = " " + _norm(nombre) + " "
    # "Aceite…", "Grasa…", "Fluido de embrague": es lo que se carga, no la pieza
    if n.split()[:1] and n.split()[0] in ("aceite", "grasa", "fluido", "liquido", "lubricante",
                                          "refrigerante", "aditivo", "anticongelante"):
        return "Lubricantes y aditivos"
    for cat, palabras in CATEGORIA_POR_PALABRA:
        if any(" " + _norm(p) in n for p in palabras):
            return cat
    return "Varios"


SUFIJOS = {"s", "a", "sa", "srl", "r", "l", "saci", "c", "i", "sae", "e", "ltda", "sacei", "saic",
           "sacia", "sociedad", "anonima", "cia"}


def _base_proveedor(nombre):
    """'JUHU SRL', 'Juhu S.R.L.' y 'juhu' son lo mismo."""
    partes = _norm(nombre).split()
    while partes and partes[-1] in SUFIJOS:
        partes.pop()
    return " ".join(partes)


def _directorio_proveedores(conn):
    """{base: nombre oficial} con solo las bases que no se repiten."""
    vistos, dup = {}, set()
    for r in conn.execute("SELECT nombre FROM repuestos_proveedores").fetchall():
        b = _base_proveedor(r["nombre"])
        if not b:
            continue
        if b in vistos and vistos[b] != r["nombre"]:
            dup.add(b)
        vistos.setdefault(b, r["nombre"])
    return {b: n for b, n in vistos.items() if b not in dup}


def _coche(v):
    v = _texto(v)
    if not v:
        return ""
    if re.fullmatch(r"\d+", v):
        return f"Coche {v}"
    if _norm(v) in ("general", "todos", "varios", "flota"):
        return "General"
    return v


def _clave_codigo(c):
    return " ".join(str(c or "").upper().split())


def preparar(filas):
    """Cada fila con lo que va a pasar: 'nuevo', 'existe' (ya está en el
    inventario), 'repetido' (el código ya vino más arriba en el Excel) o
    'falta' (sin código o sin nombre)."""
    conn = get_connection()
    try:
        existentes = {_clave_codigo(r["codigo"]): dict(r) for r in conn.execute(
            "SELECT id, codigo, descripcion, stock_actual FROM repuestos").fetchall()}
        directorio = _directorio_proveedores(conn)
    finally:
        conn.close()
    vistos = {}
    salida = []
    for f in filas:
        d = dict(f)
        d["codigo"] = _clave_codigo(d.get("codigo"))
        d["aplicacion"] = _coche(d.get("coche"))
        prov = d.get("proveedor") or ""
        d["proveedor_oficial"] = directorio.get(_base_proveedor(prov), prov) if prov else ""
        cat = d.get("categoria") or ""
        d["categoria"] = next((c for c in rdb.CATEGORIAS if _norm(c) == _norm(cat)), "") or categoria_de(d["descripcion"])
        if not d["codigo"] or not d.get("descripcion"):
            d["estado"] = "falta"
            d["motivo"] = "Sin código" if not d["codigo"] else "Sin nombre del repuesto"
        elif d["codigo"] in existentes:
            d["estado"] = "existe"
            d["motivo"] = f"Ya está en el inventario: {existentes[d['codigo']]['descripcion']}"
        elif d["codigo"] in vistos:
            d["estado"] = "repetido"
            d["motivo"] = f"El mismo código ya está en la fila {vistos[d['codigo']]}"
        else:
            d["estado"] = "nuevo"
            vistos[d["codigo"]] = d["fila"]
        salida.append(d)
    return salida


# ════════════════════════════════════════════════════════════════════════════
# IMPORTAR
# ════════════════════════════════════════════════════════════════════════════

def importar(filas, usuario=""):
    """Da de alta los repuestos confirmados. Devuelve (creados, errores)."""
    import repuestos_multi as multi
    creados, errores = [], []
    for f in filas[:MAX_FILAS]:
        codigo = _clave_codigo(f.get("codigo"))
        desc = " ".join(str(f.get("descripcion") or "").split())[:200]
        if not codigo or not desc:
            errores.append({"codigo": codigo, "msg": "Falta el código o el nombre"})
            continue
        if multi.repuesto_por_codigo(codigo):
            errores.append({"codigo": codigo, "msg": "Ya estaba en el inventario"})
            continue
        cat = f.get("categoria") if f.get("categoria") in rdb.CATEGORIAS else categoria_de(desc)
        precio = _numero(f.get("precio")) or 0
        cant = _numero(f.get("cantidad")) or 0
        ok, res = rdb.agregar_repuesto(
            codigo, desc,
            categoria=cat,
            marca=" ".join(str(f.get("marca") or "").split())[:80],
            aplicacion=" ".join(str(f.get("aplicacion") or "").split())[:120],
            proveedor=" ".join(str(f.get("proveedor") or "").split())[:120],
            costo_unitario=max(0.0, precio),
            stock_minimo=max(0.0, _numero(f.get("minimo")) or 0),
            unidad=(f.get("unidad") or "u")[:12],
            stock_inicial=max(0.0, cant),
            observaciones="Cargado desde Excel" + (f" (fila {f['fila']})" if f.get("fila") else ""),
            usuario=usuario,
        )
        if ok:
            multi.sincronizar(res)
            creados.append({"id": res, "codigo": codigo})
        else:
            errores.append({"codigo": codigo, "msg": res})
    return creados, errores


# ════════════════════════════════════════════════════════════════════════════
# RUTAS
# ════════════════════════════════════════════════════════════════════════════

def _puede():
    return session.get("rol") in ("admin", "taller")


def _no():
    msg = "No tenés permiso para cargar repuestos"
    return jsonify({"ok": False, "msg": msg, "error": msg}), 403


@bp_rep_imp.route("/api/repuestos/importar/leer", methods=["POST"])
def api_leer():
    """Lee el Excel y devuelve la vista previa (todavía no carga nada)."""
    if not _puede():
        return _no()
    arch = request.files.get("archivo")
    if not arch:
        return jsonify({"ok": False, "msg": "Elegí el archivo Excel."}), 400
    nombre = (arch.filename or "").lower()
    if not nombre.endswith((".xlsx", ".xlsm")):
        return jsonify({"ok": False, "msg": "Tiene que ser un Excel (.xlsx). Si es .xls viejo, guardalo como .xlsx."}), 400
    contenido = arch.read()
    if len(contenido) > 15 * 1024 * 1024:
        return jsonify({"ok": False, "msg": "El archivo es muy grande (más de 15 MB)."}), 400
    try:
        res = leer_excel(contenido)
    except Exception:
        return jsonify({"ok": False, "msg": "No pude abrir el Excel. ¿Está dañado o con contraseña?"}), 400
    if not res:
        return jsonify({"ok": False, "msg": "No encontré una hoja con columnas de código y nombre del repuesto "
                                            "(por ejemplo «Código del repuesto» y «Repuesto o Insumo»)."}), 400
    hoja, filas, columnas = res
    filas = preparar(filas[:MAX_FILAS])
    return jsonify({"ok": True, "hoja": hoja, "columnas": columnas, "filas": filas,
                    "categorias": rdb.CATEGORIAS,
                    "nuevos": sum(1 for f in filas if f["estado"] == "nuevo"),
                    "con_cantidad": "cantidad" in columnas})


@bp_rep_imp.route("/api/repuestos/importar", methods=["POST"])
def api_importar():
    if not _puede():
        return _no()
    d = request.json or {}
    filas = d.get("filas") or []
    if not filas:
        return jsonify({"ok": False, "msg": "No marcaste ningún repuesto."}), 400
    usuario = session.get("nombre") or session.get("usuario") or ""
    creados, errores = importar(filas, usuario)
    try:
        from database import registrar_auditoria
        registrar_auditoria(usuario=usuario or "?", rol=session.get("rol") or "",
                            accion=f"Importó {len(creados)} repuesto(s) desde Excel", categoria="Repuestos",
                            detalle=(d.get("archivo") or "") + (f" · {len(errores)} sin cargar" if errores else ""))
    except Exception:
        pass
    return jsonify({"ok": True, "creados": len(creados), "errores": errores})
