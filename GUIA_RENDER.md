# Guía paso a paso: Subir La Santaniana a Render con GitHub + PostgreSQL

Esta guía te lleva de la mano para tener el sistema funcionando en internet,
con base de datos PostgreSQL (los datos NO se borran nunca) y acceso para
2-3 personas desde cualquier lugar.

**Tiempo estimado:** 30-40 minutos la primera vez.

---

## RESUMEN DE LO QUE VAMOS A HACER

1. Subir el código a GitHub (un repositorio)
2. Crear una base de datos PostgreSQL en Render (gratis)
3. Crear el servicio web en Render (gratis)
4. Conectar todo y entrar al sistema
5. Cargar la flota y crear los usuarios

---

## PARTE 1 — Subir el código a GitHub

### 1.1 Crear cuenta en GitHub
- Entrá a https://github.com y creá una cuenta gratis (si ya tenés, saltá esto).

### 1.2 Crear el repositorio
1. Tocá el botón **"+"** arriba a la derecha → **"New repository"**.
2. Nombre: `flota-santaniana` (o el que quieras).
3. Dejalo en **Private** (privado) para que nadie más vea tu código.
4. NO marques ninguna opción de "Initialize". 
5. Tocá **"Create repository"**.

### 1.3 Subir los archivos
La forma más fácil sin instalar nada:

1. En la página del repo recién creado, tocá el link **"uploading an existing file"**.
2. Arrastrá TODOS los archivos de la carpeta `flota_web`:
   - `app.py`, `database.py`, `db_compat.py`, `models.py`, `pdf_export.py`
   - `mantenimiento_seed.py`, `flota_seed.py`
   - `requirements-nube.txt`, `Procfile`, `.gitignore`
   - La carpeta `static/` (con `app.js`, `style.css`, `logo.png`)
   - La carpeta `templates/` (con `index.html`, `login.html`)
   - **El archivo Excel** `FLOTA_SANTANIANA_GENERAL_LS-_HABILITACIONES_V_E_2026_.xlsx.xlsx`
     (este es importante para cargar la flota después)
3. Abajo tocá **"Commit changes"**.

> **Nota:** NO subas `flota_santaniana.db` (el `.gitignore` ya lo evita).
> En la nube se usa PostgreSQL, no ese archivo.

---

## PARTE 2 — Crear la base de datos PostgreSQL en Render

### 2.1 Crear cuenta en Render
- Entrá a https://render.com
- Tocá **"Get Started"** y registrate (lo más fácil: **"Sign in with GitHub"**,
  así ya queda conectado a tu repositorio).

### 2.2 Crear la base PostgreSQL
1. En el panel de Render, tocá **"New +"** → **"Postgres"**.
2. Completá:
   - **Name**: `flota-db` (o el que quieras)
   - **Database**: dejá lo que sugiere
   - **User**: dejá lo que sugiere
   - **Region**: elegí **Oregon (US West)** o la más cercana
   - **Plan**: **Free** (gratis)
3. Tocá **"Create Database"**.
4. Esperá 1-2 minutos hasta que diga **"Available"**.
5. **IMPORTANTE:** Una vez creada, buscá la sección **"Connections"** y copiá
   el valor de **"Internal Database URL"** (empieza con `postgresql://...`).
   Lo vas a necesitar en el próximo paso. Guardalo en un bloc de notas.

---

## PARTE 3 — Crear el servicio web

### 3.1 Crear el Web Service
1. En Render, tocá **"New +"** → **"Web Service"**.
2. Conectá tu repositorio `flota-santaniana` (si no aparece, tocá
   "Configure account" para darle permiso a Render de ver tus repos).
3. Completá la configuración:
   - **Name**: `flota-santaniana`
   - **Region**: **la misma que la base de datos** (ej: Oregon)
   - **Branch**: `main`
   - **Runtime**: `Python 3`
   - **Build Command**: 
     ```
     pip install -r requirements-nube.txt
     ```
   - **Start Command**: 
     ```
     gunicorn app:app --bind 0.0.0.0:$PORT --timeout 120
     ```
   - **Plan**: **Free** (gratis)

### 3.2 Configurar las variables de entorno
Antes de crear, bajá hasta **"Environment Variables"** y agregá estas tres:

| Key (nombre) | Value (valor) |
|--------------|---------------|
| `DATABASE_URL` | (pegá la Internal Database URL que copiaste antes) |
| `SECRET_KEY` | una clave larga inventada, ej: `santaniana-2026-xyz-clave-secreta-larga` |
| `MODO_SERVIDOR` | `1` |

> La `DATABASE_URL` es lo que conecta tu app con la base PostgreSQL.
> Sin ella, no funciona.

### 3.3 Crear
1. Tocá **"Create Web Service"**.
2. Render va a instalar todo y arrancar la app. Mirá los logs (tarda 3-5 minutos).
3. Cuando veas **"Your service is live"**, está listo.
4. Arriba tenés la dirección, algo como:
   ```
   https://flota-santaniana.onrender.com
   ```

---

## PARTE 4 — Entrar y configurar

### 4.1 Primer ingreso
1. Abrí la dirección que te dio Render en el navegador.
2. Te aparece la pantalla de login.
3. Entrá con:
   - Usuario: `admin`
   - Contraseña: `santaniana2026`

> Si tarda ~30 segundos la primera vez, es normal (el plan gratis "duerme"
> la app cuando no se usa).

### 4.2 Cambiar la contraseña del admin
1. En el menú lateral, tocá el ícono de **usuarios** (arriba a la derecha del menú).
2. Buscá el usuario `admin` y tocá la **llave** (cambiar contraseña).
3. Poné una contraseña nueva y segura.

### 4.3 Cargar la flota completa
1. Andá al **Dashboard**.
2. Como está vacío, vas a ver un botón **"Cargar flota completa desde Excel"**.
3. Tocalo y esperá unos segundos.
4. Listo: 89 vehículos + 333 documentos cargados automáticamente.

### 4.4 Crear los usuarios de las otras personas
1. Volvé a la pantalla de **usuarios**.
2. Creá un usuario para cada persona, eligiendo su rol:
   - **Administrador**: acceso total (vos)
   - **Operador**: el del taller que carga las OT y mantenimientos
   - **Solo consulta**: la jefa/gerencia que solo quiere ver reportes

---

## LISTO ✓

Ya tenés el sistema en internet. Compartí la dirección
(`https://flota-santaniana.onrender.com`) con tu equipo y cada uno entra con
su usuario.

---

## PREGUNTAS FRECUENTES

**¿Los datos se borran?**
No. Al usar PostgreSQL, los datos quedan guardados permanentemente, aunque la
app se reinicie o se actualice.

**¿Por qué tarda al entrar después de un rato?**
El plan gratis de Render "duerme" la app tras 15 minutos sin uso. La primera
visita la despierta (~30 seg). Si querés que esté siempre activa, el plan
pago de Render cuesta unos USD 7/mes.

**¿Cómo actualizo el sistema si hacemos cambios?**
Subís los archivos nuevos a GitHub y Render se actualiza solo (detecta el
cambio y vuelve a desplegar). Los datos NO se pierden.

**¿Cómo hago backup de los datos?**
En Render, la base PostgreSQL tiene opción de backups. En el plan gratis
podés exportar manualmente. Te puedo ayudar con esto cuando lo necesites.

**Subí el código pero Render da error.**
Mirá los "Logs" en Render, copiá el error y pedí ayuda. Lo más común:
- Olvidarse de poner la variable `DATABASE_URL`
- Olvidarse de `MODO_SERVIDOR=1`
- Que la base de datos y el web service estén en regiones distintas

**¿Puedo seguir usándolo en mi PC sin internet?**
Sí. En tu PC, sin la variable DATABASE_URL, sigue usando SQLite y se abre como
ventana de escritorio con `python app.py`. Los dos modos conviven.
