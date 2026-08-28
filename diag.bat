@echo off
cd /d "%~dp0"
echo === IC-7610 Diagnostico ===
py -3 ic7610_diag.py %*
pause
