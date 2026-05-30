# Guía para poner La Santaniana en la nube (multiusuario)

Esta guía te explica cómo subir el sistema a internet para que **2-3 personas
puedan usarlo desde distintos lugares** (taller, oficina, casa), cada una con
su usuario y contraseña.

---

## ¿Qué cambió en el sistema?

Ahora el sistema tiene **dos modos de funcionar**:

1. **Modo escritorio** (como hasta ahora): corrés `python app.py` y se abre la
   ventana en tu PC. Sirve para uso local de una sola persona.

2. **Modo servidor/nube** (nuevo): el sistema corre en internet y todos entran
   desde el navegador con su usuario y contraseña.

Además ahora hay **login de usuarios** con 3 roles:
- **Administrador**: acceso total + puede crear/borrar usuarios
- **Operador**: carga y edita datos (vehículos, OTs, mantenimientos, etc.)
- **Solo consulta**: únicamente puede ver, no puede modificar nada

**Usuario inicial** (se crea solo la primera vez):
- Usuario: `admin`
- Contraseña: `santaniana2026`
- ⚠️ **Cambiá esta contraseña apenas entres** (desde el ícono de usuarios)

---

## OPCIÓN A — Probar en red local primero (gratis)

Antes de pagar la nube, podés probarlo en la oficina:

1. En la PC que va a hacer de servidor, abrí la terminal en la carpeta del proyecto.
2. Activá el modo servidor y arrancá:

   **Windows (PowerShell):**
   ```
   $env:MODO_SERVIDOR="1"
   python app.py
   ```

3. Anotá la dirección IP de esa PC. Para verla, en otra terminal escribí:
   ```
   ipconfig
   ```
   Buscá "Dirección IPv4", algo como `192.168.1.50`.

4. Desde las otras computadoras de la oficina, abrí Chrome y entrá a:
   ```
   http://192.168.1.50:5000
   ```
   (reemplazá por la IP real de tu PC servidor)

5. Te va a pedir usuario y contraseña. Entrás con `admin` / `santaniana2026`.

**Limitación**: solo funciona dentro de la misma red (oficina). Si necesitás
acceso desde casa, seguí con la Opción B.

---

## OPCIÓN B — Subir a la nube (acceso desde cualquier lugar)

Recomiendo **Render.com** porque tiene un plan gratis para empezar y es simple.
También sirve Railway.app o PythonAnywhere.

### Paso 1: Preparar los archivos

En la carpeta del proyecto ya están estos archivos nuevos:
- `requirements-nube.txt` — las librerías que necesita el servidor
- `Procfile` — le dice al servidor cómo arrancar la app

### Paso 2: Subir el código a GitHub

1. Creá una cuenta gratis en https://github.com
2. Creá un repositorio nuevo (botón verde "New", ponele un nombre como `flota-santaniana`)
3. Subí todos los archivos de la carpeta `flota_web`. Podés hacerlo:
   - Arrastrando los archivos en la web de GitHub (botón "uploading an existing file")
   - O con Git si sabés usarlo

   **Importante**: NO subas el archivo `flota_santaniana.db` (la base de datos).
   En la nube se crea una nueva. Tampoco subas el Excel.

### Paso 3: Crear el servicio en Render

1. Creá una cuenta gratis en https://render.com (podés entrar con tu cuenta de GitHub)
2. Tocá "New +" → "Web Service"
3. Conectá tu repositorio de GitHub (`flota-santaniana`)
4. Completá la configuración:
   - **Name**: `flota-santaniana` (o el que quieras)
   - **Region**: la más cercana (por ejemplo, Ohio para Sudamérica funciona bien)
   - **Branch**: `main`
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements-nube.txt`
   - **Start Command**: `gunicorn app:app --bind 0.0.0.0:$PORT --timeout 120`
   - **Instance Type**: Free (gratis) para empezar

5. En "Environment Variables" (variables de entorno) agregá:
   - `SECRET_KEY` = (una clave larga al azar, ej: `santaniana-clave-secreta-2026-xyz789`)
   - `MODO_SERVIDOR` = `1`

6. Tocá "Create Web Service" y esperá unos minutos.

7. Cuando termine, Render te da una dirección como:
   ```
   https://flota-santaniana.onrender.com
   ```
   Esa es la dirección que comparten todos. Cada uno entra con su usuario.

### Paso 4: Configurar los usuarios

1. Entrá a la dirección que te dio Render.
2. Iniciá sesión con `admin` / `santaniana2026`.
3. **Cambiá la contraseña del admin** (ícono de usuarios arriba a la derecha del menú).
4. Creá los usuarios de las otras personas con su rol correspondiente.

### Paso 5: Cargar la flota

La base de datos en la nube arranca vacía. Para cargar los 89 vehículos:
- **Opción simple**: cargalos a mano desde la pantalla Vehículos (son varios pero
  queda más controlado).
- **Opción técnica**: si sabés usar la consola de Render, podés correr
  `python flota_seed.py` con el Excel subido. Pedí ayuda para esto si lo necesitás.

---

## ⚠️ Cosas importantes sobre el plan gratis de Render

1. **La app se "duerme" tras 15 minutos sin uso.** La primera vez que entrás
   después de un rato, tarda ~30 segundos en despertar. Es normal en el plan gratis.
   Si molesta, el plan pago (USD 7/mes) la mantiene siempre despierta.

2. **La base de datos en el plan gratis se puede borrar** cuando el servicio se
   reinicia. Para uso real conviene:
   - Usar un disco persistente (Render lo ofrece en plan pago), o
   - Migrar a PostgreSQL (Render tiene una base gratis que NO se borra).

   **Para 2-3 personas con datos importantes, recomiendo el PostgreSQL gratis de
   Render.** Avisame y te preparo esa versión (es un cambio menor en el código).

3. **Hacé backups.** Bajá la base de datos de vez en cuando para no perder datos.

---

## Resumen de costos

| Opción | Costo | Acceso | Datos seguros |
|--------|-------|--------|---------------|
| Red local | Gratis | Solo en la oficina | Sí (en tu PC) |
| Render gratis | Gratis | Desde cualquier lado | Riesgo (se puede borrar) |
| Render + PostgreSQL gratis | Gratis | Desde cualquier lado | Sí |
| Render pago | ~USD 7/mes | Desde cualquier lado, siempre activo | Sí |

**Mi recomendación para ustedes**: Render con PostgreSQL gratis. Acceso remoto,
sin costo, y los datos quedan seguros. Si después crece el uso, pasan al plan pago.

---

## ¿Necesitás ayuda?

Si te trabás en algún paso, sacá captura del error y pedí ayuda. Lo más común:
- El nombre del archivo Excel (acordate que tenía `.xlsx.xlsx`)
- Las variables de entorno mal escritas
- Olvidarse de poner `MODO_SERVIDOR=1`
