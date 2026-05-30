@echo off
:: build.bat — Genera el ejecutable .exe (ventana de escritorio)
:: Sistema de Gestion de Flota - La Santaniana v4.0

echo ============================================================
echo   Generando GestionFlota_Santaniana.exe
echo ============================================================
echo.

python --version
if errorlevel 1 (
    echo ERROR: Python no encontrado. Instala Python 3.9+ desde python.org
    pause
    exit /b 1
)

echo Instalando dependencias...
pip install -r requirements.txt

echo.
echo Compilando (esto puede tardar unos minutos)...
pyinstaller ^
    --onefile ^
    --windowed ^
    --name "GestionFlota_Santaniana" ^
    --add-data "templates;templates" ^
    --add-data "static;static" ^
    --hidden-import "webview.platforms.winforms" ^
    app.py

echo.
echo ============================================================
echo   Listo! El .exe esta en la carpeta dist\
echo ============================================================
pause
