@echo off
cd /d "%~dp0"
python dual_sync_gui.py %*
if errorlevel 1 pause
