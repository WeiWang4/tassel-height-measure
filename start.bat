@echo off
cd /d "%~dp0"

set "PYEXE="
if exist "D:\Program Files\Python311\python.exe" set "PYEXE=D:\Program Files\Python311\python.exe"
if exist "C:\Users\Administrator\AppData\Local\Programs\Python\Python311\python.exe" set "PYEXE=C:\Users\Administrator\AppData\Local\Programs\Python\Python311\python.exe"
if defined PYEXE goto checkdeps

where python >nul 2>&1
if errorlevel 1 goto nopython
set "PYEXE=python"

:checkdeps
"%PYEXE%" -c "import serial, cv2, PIL, numpy" >nul 2>&1
if errorlevel 1 goto nodeps

echo Starting with: %PYEXE%
"%PYEXE%" dual_sync_gui.py %*
if errorlevel 1 pause
exit /b 0

:nodeps
echo.
echo [ERROR] The Python at "%PYEXE%" is missing required packages.
echo Run install_deps.bat first, or install with:
echo     "%PYEXE%" -m pip install pyserial opencv-python pillow numpy pyrealsense2
echo.
pause
exit /b 1

:nopython
echo.
echo [ERROR] Python not found.
echo Install Python 3.11 from python.org and check "Add Python to PATH".
echo.
pause
exit /b 1
