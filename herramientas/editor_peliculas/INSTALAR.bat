@echo off
chcp 65001 >nul
title Instalar el editor de peliculas
cd /d "%~dp0"
echo.
echo  === Instalacion del editor de peliculas (se hace una sola vez) ===
echo  Tarda entre 3 y 10 minutos segun la conexion. No cierres esta ventana.
echo.

rem --- 1. Python ---
where pyw >nul 2>nul && goto :python_ok
where pythonw >nul 2>nul && goto :python_ok
echo  [1/3] Instalando Python (1 a 3 minutos)...
echo        Si aparece una ventana pidiendo permiso, toca "Si".
winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
  echo.
  echo  No se pudo instalar Python solo. Bajalo de https://www.python.org/downloads/
  echo  y al instalar marca la casilla "Add python.exe to PATH". Despues volve a abrir este archivo.
  pause
  exit /b 1
)
:python_ok
echo  [1/3] Python: listo.
echo.

rem --- 2 y 3. ffmpeg (queda en la carpeta "ffmpeg", al lado del programa) ---
if exist "ffmpeg\bin\ffmpeg.exe" goto :ffmpeg_ok
echo  [2/3] Descargando ffmpeg (unos 100 MB). Abajo ves cuanto falta:
curl.exe -L --fail -# -o ffmpeg.zip "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
if errorlevel 1 goto :ffmpeg_error
echo.
echo  [3/3] Descomprimiendo (menos de un minuto)...
if exist ffmpeg_tmp rmdir /s /q ffmpeg_tmp
mkdir ffmpeg_tmp
tar -xf ffmpeg.zip -C ffmpeg_tmp
if errorlevel 1 goto :ffmpeg_error
for /d %%D in (ffmpeg_tmp\*) do move "%%D" ffmpeg >nul
rmdir /s /q ffmpeg_tmp
del ffmpeg.zip
if not exist "ffmpeg\bin\ffmpeg.exe" goto :ffmpeg_error
:ffmpeg_ok
echo  [3/3] ffmpeg: listo.
echo.
echo  Todo instalado. Ahora abri "Abrir editor.bat".
echo.
pause
exit /b 0

:ffmpeg_error
echo.
echo  No se pudo bajar o descomprimir ffmpeg. Revisa la conexion y volve a abrir este archivo.
if exist ffmpeg_tmp rmdir /s /q ffmpeg_tmp
pause
exit /b 1
