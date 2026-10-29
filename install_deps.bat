@echo off
echo ============================================
echo  Laser + Depth Camera Sync Tool - Dependencies
echo ============================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found in PATH.
    echo Please install Python 3.8 - 3.12 from python.org
    echo and check "Add Python to PATH" during install.
    pause
    exit /b 1
)

echo Installing packages...
python -m pip install --upgrade pip
python -m pip install pyserial opencv-python pillow numpy pyrealsense2

echo.
echo Verifying...
python -c "import serial, cv2, PIL, numpy; print('core OK')"
python -c "import pyrealsense2; print('realsense OK')"

echo.
echo Done. Run start.bat to launch the tool.
pause
