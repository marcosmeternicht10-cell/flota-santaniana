@echo off
cd /d "%~dp0"
where pyw >nul 2>nul && (start "" pyw -3 editor.py %* & exit /b)
where pythonw >nul 2>nul && (start "" pythonw editor.py %* & exit /b)
echo Falta Python. Abri primero "INSTALAR.bat".
pause
