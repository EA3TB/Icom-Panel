@echo off
cd /d "%~dp0"
echo ============================================================
echo   IC-7610 Voice Panel - Instalacion de dependencias
echo ============================================================
py -3 --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python no encontrado. Instala Python 3.13 desde python.org
    pause
    exit /b 1
)
py -3 --version
py -3 -m pip install --upgrade pip
py -3 -m pip install icom-lan customtkinter pynput
echo.
py -3 -c "import icom_lan; print('icom_lan:', icom_lan.__version__)"
py -3 -c "import customtkinter; print('customtkinter:', customtkinter.__version__)"
py -3 -c "import pynput; print('pynput: OK')"
echo.
echo Instalacion completada.
pause
