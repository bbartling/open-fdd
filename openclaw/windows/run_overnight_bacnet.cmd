@echo off
REM Run from repo root after editing API/frontend URLs and device IDs.
cd /d "%~dp0..\.."
python openclaw\bench\e2e\automated_suite.py --api-url http://127.0.0.1:8000 --frontend-url http://127.0.0.1:5173 --bacnet-devices 3456789 3456790 --long-run-check-faults >> openclaw\reports\overnight_bacnet.log 2>&1
