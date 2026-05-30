"""
flota_seed.py — Carga masiva de la flota oficial de La Santaniana
desde el archivo Excel "FLOTA_SANTANIANA_GENERAL_LS-_HABILITACIONES_V_E_2026_.xlsx"

Mapea cada vehículo a su plan de mantenimiento según marca/carrocería/año.
También carga seguros (Pasajeros + RC) y habilitaciones municipales/Senatran.
"""

import os
import pandas as pd
from database import (
    inicializar_db, agregar_vehiculo, obtener_vehiculos,
    asignar_plan, obtener_planes, agregar_documento,
)
from mantenimiento_seed import cargar_planes_default


# ─── Mapeo de marca/carrocería → plan de mantenimiento ────────────────────────

def detectar_plan(marca, carroceria, año, tipo):
    """Devuelve el nombre del plan que corresponde a un vehículo."""
    m = (marca or "").upper().strip()
    c = (carroceria or "").upper().strip()
    t = (tipo or "").upper().strip()

    # SCANIA
    if "SCANIA" in m:
        if "K380" in c or "1800DD-K380" in c:
            return "Scania K380 / DC12 380 HP"
        if "K 410" in c or "K410" in c:
            return "Scania K410 / DC13 410 HP"
        if "K124" in c:
            return "Scania K124 / DC11 360 HP"
        if "MARCOPOLO" in c or "ANDARE" in c or "IRIZAR" in c:
            return ("Scania K380 / DC12 380 HP" if año and año >= 2010
                    else "Scania K124 / DC11 360 HP")
        return "Scania K380 / DC12 380 HP"

    # MERCEDES-BENZ
    if "M.BENZ" in m or "MERCEDES" in m:
        if "SPRINTER" in c:
            return "Mercedes-Benz Sprinter / OM651 / OM642"
        if "K380" in c or "1800DD" in c or "MARCOPOLO" in c:
            return "Mercedes-Benz O500 RSD / OM457 360 HP"
        return "Mercedes-Benz O500 RS / OM457 354 HP"

    # VOLVO
    if "VOLVO" in m:
        if "B430R" in c or "B 430" in c or "IRIZAR" in c:
            return "Volvo B430R / D11A 430 HP"
        return "Volvo B430R / D11A 430 HP"

    # VOLKSWAGEN (Senior)
    if "VOLKSWAGEN" in m:
        return "Volkswagen 9.150 / 9.160 OD (Senior)"

    # AGRALE / MARCOPOLO VOLARE
    if "AGRALE" in m or ("MARCOPOLO" in m and "VOLARE" in c):
        return "Agrale Volare W / WL"

    # HYUNDAI
    if "HYUNDAI" in m:
        return "Hyundai H350 / H1 (minibús)"

    # SENIOR (chasis MB)
    if m == "SENIOR":
        return "Mercedes-Benz Sprinter / OM651 / OM642"

    # Camionetas y otros - sin plan
    return None


def normalizar_marca(marca):
    """Convierte 'M.BENZ' → 'Mercedes-Benz', etc."""
    m = (marca or "").upper().strip()
    if "M.BENZ" in m: return "Mercedes-Benz"
    if "SCANIA" in m: return "Scania"
    if "VOLVO" in m: return "Volvo"
    if "VOLKSWAGEN" in m: return "Volkswagen"
    if "HYUNDAI" in m: return "Hyundai"
    if "AGRALE" in m: return "Agrale"
    if "TOYOTA" in m or "HILUX" in m: return "Toyota"
    if "MITSUBISHI" in m or "L200" in m: return "Mitsubishi"
    return marca.title() if marca else ""


def cargar_flota_desde_xlsx(ruta_xlsx, verbose=True):
    """Carga todos los vehículos de la hoja 'GENERAL 2026' al sistema.
    Optimizado: usa una sola conexión y evita re-consultas (rápido en la nube)."""
    if not os.path.exists(ruta_xlsx):
        print(f"❌ No se encontró el archivo: {ruta_xlsx}")
        return

    from db_compat import get_connection

    df = pd.read_excel(ruta_xlsx, sheet_name="GENERAL 2026", header=1)
    cols = ["TIPO ", "MARCA", "CARROCERIA", "CHASIS", "AÑO", "PATENTE ", "COCHE ", "EJES", "ASIENTOS"]
    df = df[cols].copy()
    df.columns = ["tipo", "marca", "carroceria", "chasis", "año",
                  "patente", "coche", "ejes", "asientos"]
    df = df.dropna(subset=["patente"])

    # Patentes existentes y planes (una sola consulta cada uno)
    existentes = {v["patente"] for v in obtener_vehiculos(solo_activos=False)}
    planes = {p["nombre"]: p["id"] for p in obtener_planes()}

    creados = 0
    saltados = 0
    sin_plan = []

    # Una sola conexión para toda la carga
    conn = get_connection()
    cur = conn.cursor()

    for _, row in df.iterrows():
        patente = str(row["patente"]).strip().replace(" ", "").upper()
        if patente in existentes:
            saltados += 1
            continue

        marca = normalizar_marca(row["marca"])
        modelo_carroceria = str(row["carroceria"]).strip().title()
        año = int(row["año"]) if pd.notna(row["año"]) else None
        chasis = str(row["chasis"]).strip().upper() if pd.notna(row["chasis"]) else ""
        n_interno = str(row["coche"]).strip() if pd.notna(row["coche"]) else ""
        asientos = int(row["asientos"]) if pd.notna(row["asientos"]) else 0
        ejes = int(row["ejes"]) if pd.notna(row["ejes"]) else 0
        tipo_v = str(row["tipo"]).strip().title() if pd.notna(row["tipo"]) else ""

        # Insertar vehículo y obtener su id en el acto (sin re-consultar)
        try:
            cur.execute(
                """INSERT INTO vehiculos
                   (patente, marca, modelo, año, chasis, n_interno, asientos, ejes, tipo)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (patente, marca, modelo_carroceria, año, chasis,
                 str(n_interno), asientos, ejes, tipo_v)
            )
            vid = cur.lastrowid
        except Exception as e:
            print(f"  ✗ {patente}: {e}")
            continue

        existentes.add(patente)  # para no duplicar en la misma corrida

        # Asignar plan en la misma conexión
        nombre_plan = detectar_plan(row["marca"], row["carroceria"], año, row["tipo"])
        if nombre_plan and nombre_plan in planes and vid:
            cur.execute(
                """INSERT INTO vehiculo_plan (vehiculo_id, plan_id, km_inicial)
                   VALUES (?,?,?)
                   ON CONFLICT(vehiculo_id) DO UPDATE SET
                       plan_id=excluded.plan_id, km_inicial=excluded.km_inicial""",
                (vid, planes[nombre_plan], 0)
            )
        else:
            sin_plan.append(patente)

        creados += 1

    conn.commit()
    conn.close()

    print()
    print(f"═══ RESUMEN ═══")
    print(f"  Vehículos creados:  {creados}")
    print(f"  Saltados (ya existían): {saltados}")
    print(f"  Sin plan (camionetas/otros): {len(sin_plan)}")
    if sin_plan:
        print(f"  Patentes sin plan: {', '.join(sin_plan)}")


def normalizar_patente(p):
    """Normaliza la patente: sin espacios, mayúsculas."""
    return str(p).strip().replace(" ", "").upper()


def cargar_documentos_desde_xlsx(ruta_xlsx, verbose=True):
    """
    Carga los documentos de toda la flota:

    SEGUROS (del Excel):
      - Seguro Pasajeros (col "Seguro" + "Vigencia")
      - Responsabilidad Civil (col "Seguro.1" + "Vigencia.1")

    HABILITACIÓN MUNICIPAL:
      - Vence el 30/06/2026 para TODA la flota.

    HABILITACIÓN DINATRAN (según regla operativa de la empresa):
      - Vehículos ≤ 10 años (año 2016 a 2026) → vencen el 21/11/2026.
      - Vehículos > 10 años (año < 2016) → vencieron el 21/05/2026,
        se renovaron y vuelven a vencer el 21/11/2026 (renovación 6 meses).
      - Todos vencen el mismo día (21/11/2026), pero queda el dato del
        ciclo corto en las observaciones de los vehículos viejos.
    """
    print()
    print("=" * 60)
    print("Cargando documentos (seguros + habilitaciones)...")
    print("=" * 60)

    from datetime import date
    from db_compat import get_connection

    # Fechas fijas según jefa
    FECHA_MUN = "2026-06-30"          # Habilitación Municipal (toda la flota)
    FECHA_DINATRAN = "2026-11-21"     # DINATRAN (todos al final)
    ANIO_ACTUAL = date.today().year   # para calcular antigüedad

    # Mapa patente → id de vehículo + año
    vehiculos = obtener_vehiculos(solo_activos=False)
    veh_por_patente = {v["patente"]: v for v in vehiculos}

    # Una sola conexión para TODOS los documentos (rápido en la nube)
    conn = get_connection()
    cur = conn.cursor()

    def _insert_doc(vid, tipo, nombre, fecha, proveedor="", obs=""):
        cur.execute("""
            INSERT INTO documentos
                (vehiculo_id, tipo, nombre, fecha_emision, fecha_vencimiento,
                 proveedor, costo, observaciones)
            VALUES (?,?,?,?,?,?,?,?)
        """, (vid, tipo, nombre, None, fecha, proveedor, 0, obs))

    # ─── 1. SEGUROS desde GENERAL 2026 ─────────────────────────────────
    df = pd.read_excel(ruta_xlsx, sheet_name="GENERAL 2026", header=1)
    df = df[['PATENTE ', 'Seguro', 'Vigencia ', 'Seguro.1', 'Vigencia .1']].copy()
    df.columns = ['patente', 'seg_pas', 'venc_pas', 'seg_rc', 'venc_rc']
    df = df.dropna(subset=['patente'])

    seg_creados = 0
    for _, row in df.iterrows():
        patente = normalizar_patente(row['patente'])
        veh = veh_por_patente.get(patente)
        if not veh:
            continue
        vid = veh["id"]

        if pd.notna(row['venc_pas']):
            try:
                fecha = pd.to_datetime(row['venc_pas']).strftime('%Y-%m-%d')
                proveedor = str(row['seg_pas']).strip() if pd.notna(row['seg_pas']) else ''
                _insert_doc(vid, 'Seguro', 'Seguro Pasajeros', fecha, proveedor)
                seg_creados += 1
            except Exception as e:
                if verbose: print(f"  ✗ {patente} seg pasajeros: {e}")

        if pd.notna(row['venc_rc']):
            try:
                fecha = pd.to_datetime(row['venc_rc']).strftime('%Y-%m-%d')
                proveedor = str(row['seg_rc']).strip() if pd.notna(row['seg_rc']) else ''
                _insert_doc(vid, 'Seguro', 'Responsabilidad Civil (RC)', fecha, proveedor)
                seg_creados += 1
            except Exception as e:
                if verbose: print(f"  ✗ {patente} seg RC: {e}")

    print(f"  ✓ Seguros cargados: {seg_creados}")

    # ─── 2. HABILITACIÓN MUNICIPAL — toda la flota, vence 30/06/2026 ────
    hab_mun = 0
    for v in vehiculos:
        try:
            _insert_doc(v["id"], 'Habilitación Municipal', 'Habilitación Municipal 2026',
                        FECHA_MUN, 'Municipalidad', 'Vence 30/06/2026 (toda la flota)')
            hab_mun += 1
        except Exception as e:
            if verbose: print(f"  ✗ {v['patente']} hab municipal: {e}")
    print(f"  ✓ Habilitaciones Municipales cargadas: {hab_mun}")

    # ─── 3. HABILITACIÓN DINATRAN ──────────────────────────────────────
    hab_din = 0
    for v in vehiculos:
        try:
            año = v.get("año") or 0
            antiguedad = ANIO_ACTUAL - año if año else 0
            if antiguedad > 10:
                obs = f"Vehículo > 10 años ({año}). Renovación cada 6 meses. Última: 21/05/2026 → vence 21/11/2026."
            else:
                obs = f"Vehículo ≤ 10 años ({año}). Vigencia anual."
            _insert_doc(v["id"], 'Habilitación DINATRAN', 'Habilitación DINATRAN',
                        FECHA_DINATRAN, 'DINATRAN', obs)
            hab_din += 1
        except Exception as e:
            if verbose: print(f"  ✗ {v['patente']} hab DINATRAN: {e}")
    print(f"  ✓ Habilitaciones DINATRAN cargadas: {hab_din}")

    # Guardar todo de una sola vez
    conn.commit()
    conn.close()

    print()
    print(f"═══ RESUMEN DOCUMENTOS ═══")
    print(f"  Seguros (Pasajeros + RC):     {seg_creados}")
    print(f"  Habilitaciones Municipales:   {hab_mun}  (vencen 30/06/2026)")
    print(f"  Habilitaciones DINATRAN:      {hab_din}  (vencen 21/11/2026)")
    print(f"  TOTAL documentos:             {seg_creados + hab_mun + hab_din}")


if __name__ == "__main__":
    import sys
    # Buscar el XLSX
    rutas_candidatas = [
        "FLOTA_SANTANIANA_GENERAL_LS-_HABILITACIONES_V_E_2026_.xlsx",
        "FLOTA SANTANIANA GENERAL LS- HABILITACIONES V.E 2026 .xlsx",
        os.path.join(os.path.dirname(__file__),
                     "FLOTA_SANTANIANA_GENERAL_LS-_HABILITACIONES_V_E_2026_.xlsx"),
    ]
    if len(sys.argv) > 1:
        rutas_candidatas.insert(0, sys.argv[1])
    ruta = next((r for r in rutas_candidatas if os.path.exists(r)), None)

    if ruta and os.path.exists(ruta):
        inicializar_db()
        cargar_planes_default()
        print()
        print("=" * 60)
        print("Cargando vehículos de la flota...")
        print("=" * 60)
        cargar_flota_desde_xlsx(ruta)
        cargar_documentos_desde_xlsx(ruta)
    else:
        print("Poné el XLSX 'FLOTA_SANTANIANA_GENERAL_LS-_HABILITACIONES_V_E_2026_.xlsx'")
        print("en la misma carpeta que este script, o ejecutalo así:")
        print("  python flota_seed.py ruta/al/archivo.xlsx")
