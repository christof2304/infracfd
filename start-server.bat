@echo off
cd /d "%~dp0"
echo Starting infraCFD on http://localhost:8000/cfd/
echo.
uvicorn server.app:app --reload --port 8000
pause
