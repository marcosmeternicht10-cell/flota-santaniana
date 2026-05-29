# 🚌 Sistema de Gestión de Flota — La Santaniana
### Versión 4.0 — Web moderna (Flask) · App de escritorio · PDF con gráficos

---

## Qué cambió respecto a la versión anterior

- Interfaz **web moderna** tipo SaaS (estilo Notion/Canva), mucho más linda
- Se abre como **ventana de escritorio** (no necesitás abrir el navegador)
- **Exportación a PDF con gráficos** (barras + torta) — no solo texto
- Gráficos interactivos en pantalla con Chart.js
- Toda la lógica (servicios por coche, KPIs mes/producción, eliminar) se mantiene

---

## Estructura

```
flota_web/
├── app.py            ← Servidor Flask + ventana de escritorio (arrancá esto)
├── database.py       ← Base de datos SQLite
├── models.py         ← KPIs por mes y por producción
├── pdf_export.py     ← Genera el PDF con gráficos (matplotlib + reportlab)
├── templates/
│   └── index.html    ← Estructura de la interfaz
├── static/
│   ├── style.css     ← Estilos modernos
│   └── app.js        ← Lógica de la interfaz + gráficos
├── requirements.txt
├── build.bat         ← Genera el .exe
└── README.md
```

---

## Cómo correr en VS Code

### 1. Instalar dependencias (una sola vez)
```bash
pip install -r requirements.txt
```

### 2. Cargar datos de ejemplo (opcional)
```bash
python models.py
```

### 3. Arrancar la aplicación
```bash
python app.py
```
Se abre una **ventana de escritorio** automáticamente.
Si no tenés `pywebview` instalado, se abre en el navegador en `http://127.0.0.1:5000`.

---

## Generar el .exe

```bash
build.bat
```
(o manualmente con el comando pyinstaller que está dentro de build.bat)

El ejecutable queda en `dist/GestionFlota_Santaniana.exe`.
Es un único archivo que podés pasarle al jefe de taller.

---

## Flujo de uso

1. **Vehículos** → agregá coches y hacé clic en uno para seleccionarlo
2. **Servicios** → cargá servicios uno por uno (fecha, km, horas, ingreso), filtrá por mes, eliminá
3. **Costos** → cargá costos por mes (variables, fijos directos, fijos indirectos)
4. **KPIs** → vé los indicadores por mes o por producción, con gráficos
5. **Exportar PDF** → botón rojo arriba a la derecha en KPIs

---

## El PDF incluye
- Encabezado con logo de La Santaniana y fecha
- Tarjetas de KPIs principales
- Gráfico de barras de la estructura de costos
- Gráfico de torta de la distribución del ingreso
- Tabla detallada de la estructura de costos
- Indicadores operativos
- Detalle de servicios

Nota: el guaraní se muestra como "Gs." (abreviatura oficial) en el PDF
porque las fuentes estándar de PDF no incluyen el símbolo ₲.
En la pantalla de la app sí se usa el formato completo.

---

## Tecnologías
- **Flask** — servidor web local
- **PyWebView** — convierte la web en ventana de escritorio
- **Chart.js** — gráficos interactivos en pantalla
- **matplotlib + reportlab** — gráficos e impresión del PDF
- **SQLite** — base de datos local (archivo flota_santaniana.db)

## Próximos pasos sugeridos
- Comparar varios coches lado a lado
- Gráfico de evolución mes a mes
- Exportar a Excel además de PDF
- Login para el jefe de taller
