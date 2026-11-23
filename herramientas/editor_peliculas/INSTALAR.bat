@echo off
chcp 65001 >nul
title Instalar el editor de peliculas
cd /d "%~dp0"
echo.
echo  === Instalacion del editor de peliculas (se hace una sola vez) ===
echo.

rem --- 1. Python ---
where pyw >nul 2>nul && goto :python_ok
where pythonw >nul 2>nul && goto :python_ok
echo  [1/2] Instalando Python...
winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
  echo.
  echo  No se pudo instalar Python solo. Bajalo de https://www.python.org/downloads/
  echo  y al instalar marca la casilla "Add python.exe to PATH". Despues volve a abrir este archivo.
  pause
  exit /b 1
)
:python_ok
echo  [1/2] Python: listo.

rem --- 2. ffmpeg (queda en la carpeta "ffmpeg", al lado del programa) ---
if exist "ffmpeg\bin\ffmpeg.exe" goto :ffmpeg_ok
echo  [2/2] Descargando ffmpeg (unos 100 MB, puede tardar)...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ProgressPreference='SilentlyContinue';" ^
  "Invoke-WebRequest 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile 'ffmpeg.zip';" ^
  "Expand-Archive 'ffmpeg.zip' -DestinationPath 'ffmpeg_tmp' -Force;" ^
  "$d = Get-ChildItem 'ffmpeg_tmp' -Directory | Select-Object -First 1;" ^
  "Move-Item $d.FullName 'ffmpeg';" ^
  "Remove-Item 'ffmpeg.zip','ffmpeg_tmp' -Recurse -Force"
if not exist "ffmpeg\bin\ffmpeg.exe" (
  echo.
  echo  No se pudo descargar ffmpeg. Revisa la conexion a internet y volve a abrir este archivo.
  pause
  exit /b 1
)
:ffmpeg_ok
echo  [2/2] ffmpeg: listo.
echo.
echo  Todo instalado. Ahora abri "Abrir editor.bat".
echo.
pause
