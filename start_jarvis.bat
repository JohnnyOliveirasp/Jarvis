@echo off
REM ── Inicia o servidor web do Jarvis ──
cd /d "%~dp0"
call venv_Jarvis\Scripts\activate.bat
echo.
echo  J.A.R.V.I.S. iniciando... abra http://127.0.0.1:8000 no navegador
echo  (Ctrl+C para parar)
echo.
python -m uvicorn jarvis.web.server:app --host 127.0.0.1 --port 8000
pause
