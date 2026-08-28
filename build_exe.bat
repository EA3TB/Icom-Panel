@echo off
cd /d "%~dp0"
echo ============================================================
echo   ICOM Voice Memory - Compilacion a EXE
echo ============================================================
py -3 --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python no encontrado. Instala Python 3.13 desde python.org
    pause
    exit /b 1
)
py -3 -m pip show pyinstaller >nul 2>&1
if errorlevel 1 py -3 -m pip install pyinstaller
py -3 -m pip install icom-lan customtkinter pynput --quiet

echo.
echo Compilando...
py -3.12 -m PyInstaller ^
    --onefile ^
    --windowed ^
    --name "ICOM - Memory Panel" ^
    --icon "icom_voice_memory.ico" ^
    --hidden-import "customtkinter" ^
    --hidden-import "darkdetect" ^
    --hidden-import "pynput" ^
    --hidden-import "pynput.keyboard" ^
    --hidden-import "pynput.mouse" ^
    --hidden-import "icom_lan" ^
    --collect-all "customtkinter" ^
    --collect-all "icom_lan" ^
    ic7610_voice_panel.py

echo.
if exist "dist\ICOM - Memory Panel.exe" (
    echo   [OK] dist\ICOM - Memory Panel.exe generado
    echo.
    echo   Copia estos archivos a la carpeta definitiva:
    echo     "ICOM - Memory Panel.exe"
    echo     radio_config.json
    echo     labels.json
) else (
    echo   [ERROR] No se genero el ejecutable. Revisa los mensajes arriba.
)
echo ============================================================
pause
