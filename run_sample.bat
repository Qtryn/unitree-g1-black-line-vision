@echo off
cd /d %~dp0
call .venv\Scripts\activate.bat
python tools\generate_test_images.py
python app.py --source samples\line_center.jpg --image --profile balanced --no-tuning
pause
