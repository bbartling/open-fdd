@echo off
cd /d "%~dp0..\.."
python openclaw\bench\e2e\automated_suite.py --api-url http://127.0.0.1:8000 --frontend-url http://127.0.0.1:5173 --daytime-smoke >> openclaw\reports\daytime_short.log 2>&1
