@echo off
cd /d %~dp0
call .venv\Scripts\activate.bat
python calibrate_parameters.py --source 0 --profile balanced --load-existing
pause
