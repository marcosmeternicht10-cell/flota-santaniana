"""
nombres.py — Los nombres de las personas, apellido primero (La Santaniana)

En todo lo que se imprime (PDF y Excel) las personas van con el APELLIDO
PRIMERO y después el nombre, como en las planillas de la empresa:

    "Juan Bautista Prieto Fernandez"  → "Prieto Fernandez, Juan Bautista"
    "Mario Luis González"             → "González, Mario Luis"
    "Angelino Candia Bogado"          → "Candia Bogado, Angelino"
    "GUSTAVO LEON"                    → "LEON, GUSTAVO"
    "PEREZ, WALTER"                   → "PEREZ, WALTER"        (ya viene así)
    "N°21 Claudio Diaz"               → "N°21 Diaz, Claudio"

Cómo sabe dónde termina el nombre: con dos palabras, la segunda es el
apellido; con tres, el segundo es nombre si es un nombre de pila conocido
(Luis, Ángel, Carlos…), si no es el primer apellido; con cuatro o más, los
dos primeros son nombres. Si alguna persona sale mal, se carga en el sistema
como «Apellido, Nombre» (con la coma) y queda así.

  apellido_primero(nombre)           una persona
  apellido_primero_varios(texto)     "N°3 Juan Pérez, N°5 Ana Gómez" o "A / B" (varios: separados con «·»)
  clave_orden(nombre)                para ordenar por apellido
"""

import re
import unicodedata

# Nombres de pila frecuentes (sin tildes, en minúscula)
_PILA = set("""
abel abelardo abraham adan adolfo adrian agustin agustina aida alan alba alberto alcides alejandra alejandro alexis
alfonso alfredo alicia alma amado amalia amanda ambrosio ana anacleto anahi analia andrea andres angel angela angelica
angelino angelo anibal antonia antonio araceli ariel armando arnaldo arturo asterio augusto aurelio aurora axel
beatriz belen benicio benigno benito bernardo bernardino blanca blas braulio brenda bruno carina carla carlos carmen
carolina catalina catalino cecilia celeste celestino cesar cinthia cipriano clara claudia claudio clemente concepcion
cristhian cristian cristina cristobal cynthia dahiana daisy dalila damian daniel daniela dario david debora delia
denis derlis diana diego dionisio domingo dora edgar edgardo edith eduardo efrain elias elisa elizabeth elena eliseo
elva elvio emilia emiliano emilio emmanuel enrique erica erico ernesto esteban estela ester eugenio eusebio eva
evelyn ezequiel fabian fabio fatima federico felipe felix fermin fernanda fernando fidel filomena flavia flavio
florencia francisca francisco fredy fulgencio crispin eliodoro milciades rodi selso gabriel gabriela gaspar gerardo german gilberto gisela gladys
gloria graciela gregorio guadalupe guido guillermo gustavo hector heber heberlino helena heriberto hernan hilda hugo
humberto ignacio ines ingrid irma isaac isabel isidro ismael israel ivan jacinto jaime javier jazmin jesus joaquin
joel johana jonas jonathan jorge jose josefa josefina juan juana julia julian juliana julio justo karen karina laura
leandro leonardo leonel leticia liliana lidia lider lorena lourdes lucas lucia luciano lucio luis luisa lujan luz
macarena magdalena manuel marcela marcelo marcial marco marcos margarita maria mariano marina mario marisa marta
martin matias mauricio maximiliano mayra melisa mercedes micaela miguel milagros miriam moises monica natalia nelson
nery nestor nicolas nidia nilda nilton noelia norma octavio olga omar orlando oscar osmar osvaldo pablino pablo
pamela pascual patricia patricio paola paula pedro perla pilar rafael ramon ramona raquel raul rebeca reinaldo
ricardo richard roberto robert rocio rodolfo rodrigo rody rogelio rolando romina roque rosa rosalia rosana rosario
ruben rufino ruth sabrina salvador samuel sandra santiago sara sebastian sergio silvia silvio simon sofia sonia
susana tamara tatiana teodoro teofilo teresa timoteo tomas ulises valentin valeria vanesa vanessa veronica vicente
victor victoria vilma virginia walter wilfrido willian william ximena yanina yesica yolanda zulma
""".split())
_DEVOCION = {"dios", "jesus", "carmen", "rosario", "angeles", "lourdes", "fatima", "asuncion", "pilar", "luz",
             "mercedes", "cruz", "pena", "concepcion", "dolores", "milagros", "socorro", "lujan", "guadalupe"}
_PARTICULAS = {"de", "del", "la", "las", "los", "da", "das", "do", "dos", "van", "von", "y"}
# Si aparece una de estas palabras no es una persona («Taller Bosch», «Gomería Ruta 2»)
_NO_PERSONA = {"taller", "talleres", "gomeria", "prueba", "chofer", "tecnico", "servicio", "ruta", "empresa",
               "sa", "s.a.", "srl", "ltda", "externo", "tercero", "afuera", "mecanica", "electricidad", "torneria",
               "chaperia", "rectificadora", "agencia", "deposito", "oficina", "sin", "asignar",
               "def", "definir", "conf", "confirmar", "reserva", "vacante"}
_PREFIJO = re.compile(r"^\s*((?:N[°º]|Nº|N\.|#)\s*\d+\s*[-·:]?\s*)", re.I)


def _llano(t):
    t = unicodedata.normalize("NFD", str(t or "").lower())
    return "".join(ch for ch in t if unicodedata.category(ch) != "Mn")


def _partir(palabras):
    """Cuántas palabras son nombre de pila."""
    n = len(palabras)
    if n <= 1:
        return n
    if n == 2:
        return 1
    if n == 3:
        return 2 if _llano(palabras[1]) in _PILA else 1
    # 4 o más: dos nombres; tres si el tercero también es nombre y quedan dos apellidos
    if n >= 5 and _llano(palabras[2]) in _PILA:
        return 3
    return 2


def apellido_primero(nombre):
    """Una persona, apellido primero: 'Juan Pérez' → 'Pérez, Juan'."""
    s = " ".join(str(nombre or "").split())
    if not s:
        return ""
    m = _PREFIJO.match(s)
    pre = ""
    if m:
        pre, s = m.group(1).strip() + " ", s[m.end():].strip()
    if "," in s or not s:
        return pre + s                       # ya viene «Apellido, Nombre»
    pal = s.split(" ")
    if any(ch.isdigit() for ch in s) or any(_llano(x).strip(".") in _NO_PERSONA for x in pal):
        return pre + s                       # «Chofer 21027», «Taller Bosch»: no es un nombre
    if len(pal) < 2:
        return pre + s
    # ¿ya viene con el apellido primero, sin coma? («CABRERA WALTER», «GOMEZ CACERES ARNALDO»):
    # la primera palabra no es nombre de pila y la(s) última(s) sí
    if _llano(pal[0]) not in _PILA and _llano(pal[0]) not in _PARTICULAS:
        t = 0
        while t < len(pal) - 1 and t < 2 and _llano(pal[-1 - t]) in _PILA:
            t += 1
        if t:
            return pre + " ".join(pal[:-t]) + ", " + " ".join(pal[-t:])
    # nombres compuestos con «de»: Juan de Dios, María de los Ángeles, del Carmen
    j = 1
    while j < len(pal) and _llano(pal[j]) in _PARTICULAS:
        j += 1
    if j > 1 and j < len(pal) - 1 and _llano(pal[j]) in (_PILA | _DEVOCION):
        k = j + 1
        if len(pal) - k >= 3 and _llano(pal[k]) in _PILA:
            k += 1
    else:
        k = _partir(pal)
        # una partícula («de», «del») va con el apellido que sigue
        while 1 < k < len(pal) and _llano(pal[k - 1]) in _PARTICULAS:
            k -= 1
    nom, ape = pal[:k], pal[k:]
    if not ape:
        return pre + s
    return pre + " ".join(ape) + ", " + " ".join(nom)


def apellido_primero_varios(texto):
    """Varias personas en un texto: 'N°3 Juan Pérez, N°5 Ana Gómez',
    'JUAN PEREZ / CARLOS GOMEZ', 'Juan Pérez y Ana Gómez' o una por renglón."""
    s = str(texto or "")
    if not s.strip():
        return s
    if "\n" in s:
        return "\n".join(apellido_primero_varios(x) for x in s.split("\n"))
    # separadores claros
    for sep in (" / ", "/", " + ", " - ", " y ", " Y "):
        if sep in s:
            return sep.join(apellido_primero_varios(x) for x in s.split(sep))
    # «N°3 Juan Pérez, N°5 Ana Gómez»: la coma separa personas numeradas
    if re.search(r",\s*(N[°º]|Nº|#)\s*\d", s, re.I):
        partes = [x.strip() for x in s.split(",") if x.strip()]
        return " · ".join(apellido_primero(x) for x in partes)
    # «Juan Pérez, Ana Gómez» (dos o más palabras a cada lado) son dos personas;
    # «PEREZ, WALTER» es una sola ya ordenada
    if "," in s:
        partes = [x.strip() for x in s.split(",")]
        if len(partes) > 2 or all(len(x.split()) >= 2 for x in partes):
            return " · ".join(apellido_primero(x) for x in partes)
    return apellido_primero(s)


def clave_orden(nombre):
    """Para ordenar por apellido (sin tildes ni mayúsculas)."""
    return _llano(apellido_primero(nombre)).replace(",", " ")


def separar_personas(texto):
    """Las personas de un campo que puede tener varias: 'JUAN PEREZ / CARLOS GOMEZ',
    'N°3 Juan Pérez, N°5 Ana Gómez', 'Juan Pérez y Ana Gómez', una por renglón.
    Devuelve los nombres sueltos, sin el N° y sin lo que no es una persona."""
    s = str(texto or "")
    if not s.strip():
        return []
    partes = [s]
    for sep in ("\n", " / ", "/", " + ", " - ", " y ", " Y "):
        partes = [y for x in partes for y in x.split(sep)]
    out = []
    for p in partes:
        p = p.strip()
        if not p:
            continue
        # «N°3 A, N°5 B» o «Juan Pérez, Ana Gómez»: la coma separa personas;
        # «PEREZ, WALTER» es una sola
        trozos = [x.strip() for x in p.split(",")]
        if len(trozos) > 1 and (re.search(r",\s*(N[°º]|Nº|#)\s*\d", p, re.I) or len(trozos) > 2
                                or all(len(x.split()) >= 2 for x in trozos)):
            cands = trozos
        else:
            cands = [p]
        for c in cands:
            c = _PREFIJO.sub("", c).strip()
            pal = c.replace(",", " ").split()
            if len(pal) < 2 or any(ch.isdigit() for ch in c) or any(_llano(x).strip(".") in _NO_PERSONA for x in pal):
                continue
            out.append(c)
    return out


def clave_persona(nombre):
    """La misma persona escrita de cualquier forma da la misma clave:
    'JUAN PEREZ', 'Pérez, Juan' y 'PEREZ JUAN' → 'JUAN PEREZ'."""
    t = _llano(_PREFIJO.sub("", str(nombre or ""))).upper()
    partes = [x for x in "".join(ch if ch.isalnum() else " " for ch in t).split() if x]
    return " ".join(sorted(partes))
