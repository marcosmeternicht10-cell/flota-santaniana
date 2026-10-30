"""
buscador.py — Búsqueda a prueba de errores para repuestos y proveedores
(La Santaniana)

La gente escribe como sale: «filto de aseite», «pastiyas», «rulemam»,
«filt comb», «w 1374», «balatas». Esto encuentra igual lo que buscan:

  · sin tildes ni mayúsculas, y suena igual = es igual (s/z/c, v/b, ll/y,
    h muda, qu/k…): «aseite» = «aceite», «pastiya» = «pastilla»;
  · errores de tipeo (una letra de más, de menos, cambiada o dos letras
    al revés): «filto» = «filtro», «rulemam» = «ruleman»;
  · abreviado: «filt comb» = «filtro combustible»;
  · plurales: «filtros» = «filtro»;
  · palabras del taller que dicen lo mismo: pastilla = balata, rulemán =
    rodamiento, correa = banda, gasoil = combustible = diésel…;
  · códigos con o sin guiones y espacios: «w 1374» = «MANN-W1374»;
  · y aprende: cuando Compras engancha «aceite p/ caja» con un repuesto, la
    próxima vez que alguien escriba algo parecido ese repuesto sale primero.

Sin librerías: Python puro, para que funcione igual en Render.

  buscar_repuestos(q, limite)     [(repuesto, puntaje, motivo)]
  buscar_proveedores(q, limite)   [(proveedor, puntaje)]
  corregir(q)                     «Quisiste decir…» con las palabras del catálogo
  aprender(texto, repuesto_id)    recuerda lo que se eligió
"""

import re
import time
import unicodedata

from db_compat import get_connection, USE_POSTGRES

PK = "SERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"

VACIAS = {"de", "del", "la", "el", "los", "las", "para", "con", "y", "un", "una", "por", "en", "a", "al",
          "p", "c", "x", "sin", "o", "u", "lo", "le", "q", "que", "mas", "nro", "num", "n"}

# Palabras del taller que quieren decir lo mismo (cada grupo, una idea)
SINONIMOS = [
    ["pastilla", "balata", "pastillas de freno"],
    ["zapata", "cinta de freno", "lona de freno"],
    ["ruleman", "rodamiento", "cojinete", "rolinera", "bolillero"],
    ["correa", "banda", "correia"],
    ["combustible", "gasoil", "gasoleo", "diesel", "gasoil", "comb"],
    ["aceite", "lubricante", "oleo"],
    ["refrigerante", "coolant", "anticongelante"],
    ["embrague", "clutch", "croche", "cloche"],
    ["neumatico", "cubierta", "goma", "llanta"],
    ["camara", "tubo"],
    ["tornillo", "bulon", "perno"],
    ["reten", "sello", "estopera"],
    ["junta", "empaquetadura", "empaque", "guarnicion"],
    ["lampara", "foco", "bombilla", "bombillo", "ampolleta"],
    ["rele", "relay", "relevador"],
    ["arranque", "burro", "motor de arranque", "marcha"],
    ["alternador", "dinamo"],
    ["amortiguador", "amortiguadores", "shock"],
    ["parabrisas", "parabrisa", "vidrio delantero"],
    ["limpiaparabrisas", "escobilla", "plumilla", "limpiador"],
    ["manguera", "manga", "mangote"],
    ["abrazadera", "precinto metalico", "grampa"],
    ["burlete", "goma de puerta", "guarnicion de puerta"],
    ["valijera", "bodega", "baulera", "maletero"],
    ["bateria", "acumulador"],
    ["bomba", "bombita"],
    ["filtro", "filtros", "elemento filtrante"],
    ["separador", "trampa de agua", "decantador"],
    ["fusible", "fusibles"],
    ["cruceta", "cruz", "cardan"],
    ["buje", "bocina", "casquillo"],
    ["rotula", "rotulas", "terminal de direccion"],
    ["termostato", "valvula termostatica"],
    ["ventilador", "electroventilador", "helice"],
    ["espejo", "retrovisor"],
    ["butaca", "asiento"],
    ["aire acondicionado", "ac", "a/c", "climatizador"],
    ["grasa", "grasa de chasis"],
    ["arandela", "golilla"],
]


# ════════════════════════════════════════════════════════════════════════════
# NORMALIZAR: lo que se escribe distinto pero se dice igual
# ════════════════════════════════════════════════════════════════════════════

def sin_tildes(t):
    t = unicodedata.normalize("NFD", str(t or "").lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def _fonetica(w):
    """Cómo suena (castellano rioplatense/paraguayo): aseite = aceite."""
    if any(ch.isdigit() for ch in w):
        return w
    w = w.replace("ll", "y").replace("qu", "k").replace("ch", "#")
    w = re.sub(r"c(?=[ei])", "s", w)
    w = re.sub(r"g(?=[ei])", "j", w)
    w = w.replace("z", "s").replace("c", "k").replace("v", "b").replace("w", "u").replace("h", "")
    w = w.replace("#", "ch").replace("x", "ks")
    w = re.sub(r"y$", "i", w)
    w = re.sub(r"(.)\1+", r"\1", w)      # letras dobles
    return w


def _raiz(w):
    """Sin plural: filtros → filtro, rulemanes → ruleman, luces → luz."""
    if any(ch.isdigit() for ch in w) or len(w) <= 3:
        return w
    if w.endswith("ses") and len(w) > 5:
        return w[:-2]
    if w.endswith("es") and len(w) > 4 and w[-3] not in "aeiou":
        return w[:-2]
    if w.endswith("s") and w[-2] in "aeiou":
        return w[:-1]
    return w


def _clave(w):
    return _raiz(_fonetica(_raiz(w)))


def palabras(t):
    """Las palabras útiles, normalizadas. Los códigos se juntan ('w 1374' → 'w1374')."""
    t = sin_tildes(t)
    t = re.sub(r"(?<=[a-z])[-./](?=\d)|(?<=\d)[-./](?=[a-z\d])", "", t)   # w-1374, 1.374
    crudas = re.findall(r"[a-z0-9ñ]+", t)
    out = []
    for p in crudas:
        if p in VACIAS:
            continue
        if len(p) == 1 and not p.isdigit():
            continue
        out.append(p)
    return out


def compacto(t):
    return re.sub(r"[^a-z0-9]", "", sin_tildes(t))


_SIN_IDX = None


def _sinonimos():
    """{clave de palabra: número de grupo}."""
    global _SIN_IDX
    if _SIN_IDX is None:
        _SIN_IDX = {}
        for i, grupo in enumerate(SINONIMOS):
            for frase in grupo:
                ps = palabras(frase)
                if len(ps) == 1:
                    _SIN_IDX.setdefault(_clave(ps[0]), i)
    return _SIN_IDX


# ════════════════════════════════════════════════════════════════════════════
# PARECIDO ENTRE DOS PALABRAS
# ════════════════════════════════════════════════════════════════════════════

def distancia(a, b, tope=3):
    """Damerau-Levenshtein (dos letras al revés cuenta como un error)."""
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if abs(la - lb) > tope:
        return tope + 1
    prev2, prev = None, list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        mejor = cur[0]
        for j in range(1, lb + 1):
            costo = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + costo)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
            mejor = min(mejor, cur[j])
        if mejor > tope:
            return tope + 1
        prev2, prev = prev, cur
    return prev[lb]


def _tolerancia(n):
    return 0 if n <= 3 else 1 if n <= 7 else 2


def parecido(q, d, qk=None, dk=None):
    """Qué tan parecida es la palabra buscada (q) a una del catálogo (d): 0 a 1."""
    if q == d:
        return 1.0
    qk = qk or _clave(q)
    dk = dk or _clave(d)
    if qk == dk:
        return 0.97
    num_q, num_d = any(c.isdigit() for c in q), any(c.isdigit() for c in d)
    if num_q or num_d:
        # códigos: exacto, contenido, o casi igual si son largos
        if len(q) >= 3 and q in d:
            return 0.92 if len(q) >= 4 else 0.8
        if len(d) >= 4 and d in q:
            return 0.8
        if len(q) >= 5 and distancia(q, d, 1) <= 1:
            return 0.75
        return 0.0
    sin = _sinonimos()
    if qk in sin and sin.get(dk) == sin[qk]:
        return 0.9
    # abreviado: filt → filtro, comb → combustible
    if len(q) >= 3 and (d.startswith(q) or dk.startswith(qk)):
        return 0.88 if len(q) >= 4 else 0.78
    if len(d) >= 4 and q.startswith(d):
        return 0.8
    # abreviado y mal escrito: conbus → combustible, filtr → filtro
    if len(q) >= 5 and len(d) > len(q) and q[:1] == d[:1]:
        if distancia(q, d[:len(q)], 1) <= 1 or (len(dk) > len(qk) and distancia(qk, dk[:len(qk)], 1) <= 1):
            return 0.78
    tol = _tolerancia(max(len(qk), len(dk)))
    if tol:
        castigo = 0 if qk[:1] == dk[:1] else 0.1     # casi nadie le erra a la primera letra
        dist = distancia(qk, dk, tol)
        if dist <= tol:
            return 0.86 - 0.08 * (dist - 1) - castigo
        # error de tipeo en la palabra cruda (por si la fonética la deformó)
        dist = distancia(q, d, tol)
        if dist <= tol:
            return 0.8 - 0.08 * (dist - 1) - castigo
    return 0.0


# ════════════════════════════════════════════════════════════════════════════
# ÍNDICE DEL CATÁLOGO (se arma una vez y se renueva si cambia)
# ════════════════════════════════════════════════════════════════════════════

_IDX = {"rep": None, "rep_firma": None, "rep_t": 0, "prov": None, "prov_firma": None, "prov_t": 0}
TTL = 45


def _rollback(conn):
    try:
        conn.rollback()
    except Exception:
        pass


def _firma(conn, tabla):
    r = conn.execute(f"SELECT COUNT(*) AS n, COALESCE(MAX(id),0) AS m FROM {tabla}").fetchone()
    return (int(r["n"] or 0), int(r["m"] or 0))


def _campos(texto, peso):
    return [(p, _clave(p), peso) for p in palabras(texto)]


def _indice_repuestos():
    ahora = time.time()
    if _IDX["rep"] is not None and ahora - _IDX["rep_t"] < TTL:
        return _IDX["rep"]
    conn = get_connection()
    try:
        firma = _firma(conn, "repuestos")
        if _IDX["rep"] is not None and firma == _IDX["rep_firma"]:
            _IDX["rep_t"] = ahora
            return _IDX["rep"]
        filas = [dict(r) for r in conn.execute("SELECT * FROM repuestos WHERE activo=1").fetchall()]
        otros = {}
        try:
            for r in conn.execute("SELECT repuesto_id, codigo_prov, proveedor FROM repuestos_por_proveedor").fetchall():
                otros.setdefault(r["repuesto_id"], []).append(f"{r['codigo_prov'] or ''} {r['proveedor'] or ''}")
        except Exception:
            _rollback(conn)
    finally:
        conn.close()
    idx = []
    for r in filas:
        toks = (_campos(r.get("descripcion"), 1.0) + _campos(r.get("codigo"), 1.0) + _campos(r.get("codigo_alt"), 0.95)
                + _campos(r.get("marca"), 0.8) + _campos(r.get("aplicacion"), 0.75) + _campos(r.get("categoria"), 0.6)
                + _campos(r.get("proveedor"), 0.5) + _campos(" ".join(otros.get(r["id"], [])), 0.6))
        codigos = {compacto(r.get("codigo")), compacto(r.get("codigo_alt"))} | {
            compacto(x.split(" ")[0]) for x in otros.get(r["id"], []) if x.split(" ")[0]}
        idx.append({"r": r, "toks": toks, "codigos": {c for c in codigos if len(c) >= 3},
                    "desc": compacto(r.get("descripcion"))})
    _IDX.update(rep=idx, rep_firma=firma, rep_t=ahora)
    return idx


def _indice_proveedores():
    ahora = time.time()
    if _IDX["prov"] is not None and ahora - _IDX["prov_t"] < TTL:
        return _IDX["prov"]
    conn = get_connection()
    try:
        firma = _firma(conn, "repuestos_proveedores")
        if _IDX["prov"] is not None and firma == _IDX["prov_firma"]:
            _IDX["prov_t"] = ahora
            return _IDX["prov"]
        filas = [dict(r) for r in conn.execute("SELECT * FROM repuestos_proveedores").fetchall()]
    finally:
        conn.close()
    societarias = {"sa", "srl", "saci", "sacia", "saic", "eirl", "ltda", "cia", "y", "hnos", "hermanos", "e", "s"}
    idx = []
    for p in filas:
        toks = [t for t in _campos(p.get("nombre"), 1.0) + _campos(p.get("fantasia"), 1.0) + _campos(p.get("contacto"), 0.6)
                if t[0] not in societarias]
        idx.append({"p": p, "toks": toks, "ruc": compacto(p.get("ruc"))})
    _IDX.update(prov=idx, prov_firma=firma, prov_t=ahora)
    return idx


def olvidar_indice():
    _IDX.update(rep=None, prov=None)


# ════════════════════════════════════════════════════════════════════════════
# PUNTAJE DE UNA BÚSQUEDA CONTRA UNA FILA
# ════════════════════════════════════════════════════════════════════════════

def _puntaje(q_toks, doc_toks):
    """Promedio de lo bien que encuentra cada palabra buscada. Devuelve
    (puntaje 0..1, cuántas palabras encontró bien)."""
    if not q_toks:
        return 0.0, 0
    total, buenas = 0.0, 0
    for q, qk in q_toks:
        mejor = 0.0
        for d, dk, peso in doc_toks:
            s = parecido(q, d, qk, dk) * peso
            if s > mejor:
                mejor = s
                if s >= 0.99:
                    break
        total += mejor
        buenas += 1 if mejor >= 0.75 else 0
    return total / len(q_toks), buenas


def _consulta(q):
    return [(p, _clave(p)) for p in palabras(q)]


# ════════════════════════════════════════════════════════════════════════════
# LO QUE APRENDE: «esto que escribieron» = «este repuesto»
# ════════════════════════════════════════════════════════════════════════════

def init_buscador():
    conn = get_connection()
    try:
        conn.execute(f"""CREATE TABLE IF NOT EXISTS repuestos_alias (
            id {PK},
            texto TEXT NOT NULL,
            clave TEXT NOT NULL,
            repuesto_id INTEGER NOT NULL,
            veces INTEGER DEFAULT 1,
            ultimo TEXT DEFAULT '')""")
        conn.execute("CREATE INDEX IF NOT EXISTS ix_repalias_rep ON repuestos_alias (repuesto_id)")
        conn.commit()
    except Exception as e:
        _rollback(conn)
        print(f"[buscador] no se pudo crear la tabla de alias: {e}")
    finally:
        conn.close()


def _clave_texto(t):
    return " ".join(sorted({_clave(p) for p in palabras(t)}))


_ALIAS = {"lista": None, "t": 0}


def aprender(texto, repuesto_id):
    clave = _clave_texto(texto)
    if not clave or not repuesto_id:
        return
    try:
        from hora_local import ahora_iso
        ahora = ahora_iso()
    except Exception:
        ahora = ""
    conn = get_connection()
    try:
        r = conn.execute("SELECT id FROM repuestos_alias WHERE clave=? AND repuesto_id=?", (clave, repuesto_id)).fetchone()
        if r:
            conn.execute("UPDATE repuestos_alias SET veces=veces+1, ultimo=? WHERE id=?", (ahora, r["id"]))
        else:
            conn.execute("INSERT INTO repuestos_alias (texto, clave, repuesto_id, veces, ultimo) VALUES (?,?,?,1,?)",
                         (str(texto or "")[:200], clave, repuesto_id, ahora))
        conn.commit()
        _ALIAS["lista"] = None
    except Exception:
        _rollback(conn)
    finally:
        conn.close()


def _alias():
    if _ALIAS["lista"] is not None and time.time() - _ALIAS["t"] < TTL:
        return _ALIAS["lista"]
    conn = get_connection()
    try:
        filas = [dict(r) for r in conn.execute("SELECT texto, repuesto_id, veces FROM repuestos_alias").fetchall()]
    except Exception:
        _rollback(conn)
        filas = []
    finally:
        conn.close()
    lista = [(f["repuesto_id"], int(f["veces"] or 1), [(p, _clave(p), 1.0) for p in palabras(f["texto"])], f["texto"])
             for f in filas]
    _ALIAS.update(lista=lista, t=time.time())
    return lista


# ════════════════════════════════════════════════════════════════════════════
# BUSCAR
# ════════════════════════════════════════════════════════════════════════════

def buscar_repuestos(q, limite=20):
    """[(repuesto dict, puntaje, motivo)] del más parecido al menos.
    motivo: 'codigo' | 'exacto' | 'parecido' | 'aprendido'."""
    q = str(q or "").strip()
    qt = _consulta(q)
    qc = compacto(q)
    if not qt and len(qc) < 3:
        return []
    aprendidos = {}
    for rid, veces, toks, texto in _alias():
        s, buenas = _puntaje(qt, toks)
        if s >= 0.82 and buenas == len(qt):
            aprendidos[rid] = max(aprendidos.get(rid, 0), s + min(veces, 5) * 0.02)
    res = []
    for e in _indice_repuestos():
        r = e["r"]
        motivo = "parecido"
        # el código completo, escrito como sea
        if len(qc) >= 4 and any(qc == c or (len(qc) >= 5 and qc in c) for c in e["codigos"]):
            s = 1.2 if qc in e["codigos"] else 1.05
            motivo = "codigo"
        else:
            s, buenas = _puntaje(qt, e["toks"])
            # tiene que encontrar bien la mayoría de lo escrito
            minimo = len(qt) if len(qt) <= 2 else len(qt) - 1
            if buenas < max(1, minimo) or s < 0.6:
                s = 0
            elif all(p in [d for d, _, _ in e["toks"]] for p, _ in qt):
                motivo = "exacto"
        if r["id"] in aprendidos:
            s = max(s, 0.7) + 0.35 * aprendidos[r["id"]]
            motivo = "aprendido"
        if s <= 0:
            continue
        s += 0.04 if float(r.get("stock_actual") or 0) > 0 else 0
        res.append((r, round(s, 3), motivo))
    res.sort(key=lambda x: (-x[1], str(x[0].get("descripcion") or "")))
    if res:   # si hay algo muy parecido, no llenar con lo que se parece de casualidad
        # (lo aprendido va arriba, pero no tapa a los demás)
        base = next((x[1] for x in res if x[2] != "aprendido"), res[0][1])
        corte = base * 0.88
        res = [x for x in res if x[1] >= corte or x[2] == "aprendido"]
    return res[:limite]


def buscar_proveedores(q, limite=12):
    q = str(q or "").strip()
    qt = _consulta(q)
    qc = compacto(q)
    if not qt:
        return []
    res = []
    for e in _indice_proveedores():
        if len(qc) >= 5 and qc.isdigit() and e["ruc"].startswith(qc):
            res.append((e["p"], 1.1))
            continue
        s, buenas = _puntaje(qt, e["toks"])
        if buenas >= max(1, len(qt) - 1) and s >= 0.6:
            res.append((e["p"], round(s, 3)))
    res.sort(key=lambda x: (-x[1], str(x[0].get("nombre") or "")))
    if res:
        corte = res[0][1] * 0.85
        res = [x for x in res if x[1] >= corte]
    return res[:limite]


def corregir(q):
    """«filto de aseite» → «filtro de aceite», con las palabras que de verdad
    hay en el catálogo. Devuelve '' si no hay nada que corregir."""
    vocab = {}
    for e in _indice_repuestos():
        for d, dk, peso in e["toks"]:
            if peso >= 0.95 and not any(c.isdigit() for c in d) and len(d) >= 3:
                vocab.setdefault(dk, {}).setdefault(d, 0)
                vocab[dk][d] += 1
    if not vocab:
        return ""
    salida, cambio = [], False
    for p in re.findall(r"[^\s]+", str(q or "")):
        pn = sin_tildes(p)
        ps = palabras(p)
        if not ps or any(c.isdigit() for c in pn):
            salida.append(p)
            continue
        w = ps[0]
        wk = _clave(w)
        if (wk in vocab and w in vocab[wk]) or (wk in _sinonimos() and wk not in vocab):
            salida.append(p)     # bien escrita, o es otra forma de decir lo mismo
            continue
        mejor, mejor_s = None, 0.0
        for dk, formas in vocab.items():
            forma = max(formas, key=formas.get)
            s = parecido(w, forma, wk, dk)
            if s > mejor_s or (s == mejor_s and mejor and formas[forma] > vocab[_clave(mejor)].get(mejor, 0)):
                mejor, mejor_s = forma, s
        if mejor and 0.7 <= mejor_s < 1.0 and mejor != w and not mejor.startswith(w):
            salida.append(mejor)
            cambio = True
        else:
            salida.append(p)
    return " ".join(salida) if cambio else ""
