@echo off
setlocal
cd /d %~dp0

python -m venv .venv
if errorlevel 1 goto :error

call .venv\Scripts\activate.bat
if errorlevel 1 goto :error

python -m pip install --upgrade pip
if errorlevel 1 goto :error

pip install -r requirements.txt
if errorlevel 1 goto :error

python tools\generate_test_images.py
if errorlevel 1 goto :error

echo.
echo Setup completed.
echo.
echo Step 1 - Calibrate camera 1:
echo   python calibrate_parameters.py --source 1 --profile balanced
echo.
echo Step 2 - Run with saved tuning:
echo   python app.py --source 1 --profile balanced
echo.
pause
exit /b 0

:error
echo.
echo Setup failed.
pause
exit /b 1
