@echo off
cd /d %~dp0
call .venv\Scripts\activate.bat
python app.py --source 0 --profile balanced
pause
