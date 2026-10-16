@echo off
chcp 65001 > nul
setlocal EnableExtensions

REM ============================================================
REM  SIGMA DEV - uvicorn (8000) + Vite (5173).
REM ============================================================

set "BACKEND_DIR=%~dp0"
set "FRONTEND_DIR=%~dp0frontend"

echo.
echo ====== SIGMA DEV ======
echo Backend:  %BACKEND_DIR%
echo Frontend: %FRONTEND_DIR%
echo ============================
echo.

REM --- 1) Python ---
set "PYTHON_CMD="
if exist "%BACKEND_DIR%.venv\Scripts\python.exe" set "PYTHON_CMD=%BACKEND_DIR%.venv\Scripts\python.exe"
if not defined PYTHON_CMD if exist "%BACKEND_DIR%backend\.venv\Scripts\python.exe" set "PYTHON_CMD=%BACKEND_DIR%backend\.venv\Scripts\python.exe"
if not defined PYTHON_CMD if defined CONDA_PREFIX if exist "%CONDA_PREFIX%\python.exe" set "PYTHON_CMD=%CONDA_PREFIX%\python.exe"
if not defined PYTHON_CMD for /f "delims=" %%I in ('where.exe python 2^>nul') do if not defined PYTHON_CMD set "PYTHON_CMD=%%~fI"
if not defined PYTHON_CMD for %%I in (
  "%LocalAppData%\Programs\Python\Python313\python.exe"
  "%LocalAppData%\Programs\Python\Python312\python.exe"
  "%LocalAppData%\Programs\Python\Python311\python.exe"
  "%LocalAppData%\Programs\Python\Python310\python.exe"
  "%USERPROFILE%\miniconda3\python.exe"
  "%USERPROFILE%\anaconda3\python.exe"
  "C:\ProgramData\miniconda3\python.exe"
  "C:\ProgramData\anaconda3\python.exe"
  "D:\Conda\python.exe"
) do if not defined PYTHON_CMD if exist "%%~I" set "PYTHON_CMD=%%~I"
if not defined PYTHON_CMD (
  echo [!] Python not found in PATH, .venv or conda.
  echo     Install Python 3.10+ or run from an activated conda environment.
  pause & exit /b 1
)
echo [bk] Python: %PYTHON_CMD%

REM --- 2) Backend deps ---
echo [bk] Checking backend packages...
"%PYTHON_CMD%" -c "import fastapi, uvicorn, sqlalchemy, asyncpg, pydantic_settings, multipart, jose, passlib" 2>nul
if errorlevel 1 (
  echo [bk] Missing packages - installing from requirements.txt
  "%PYTHON_CMD%" -m pip install --disable-pip-version-check -r "%BACKEND_DIR%requirements.txt"
  if errorlevel 1 (
    echo [!] pip install failed. Fix the error above and rerun.
    pause & exit /b 1
  )
) else (
  echo [bk] Python packages are present.
)

REM --- 3) Backend env ---
if not exist "%BACKEND_DIR%.env" (
  echo.
  echo [!] File not found: %BACKEND_DIR%.env
  echo     Backend will not start without DB_*, ACCESS_TOKEN, GROUP_ID and related variables.
  pause & exit /b 1
)

REM --- 4) Node + npm ---
where node >nul 2>nul
if errorlevel 1 (
  echo [!] Node.js not found in PATH. Install Node.js 20+ and rerun.
  pause & exit /b 1
)

if not exist "%FRONTEND_DIR%\node_modules" (
  echo [fe] node_modules missing - running npm install...
  pushd "%FRONTEND_DIR%"
  call npm install
  if errorlevel 1 (
    echo [!] npm install failed.
    popd & pause & exit /b 1
  )
  popd
) else (
  echo [fe] node_modules present.
)

REM --- 5) Show IPv4 for mobile ---
echo.
echo --- IPv4 of this machine ---
for /f "tokens=2 delims=:" %%A in ('ipconfig ^| findstr /C:"IPv4"') do (
  for /f "tokens=* delims= " %%B in ("%%A") do echo   http://%%B:5173/
)
echo (local PC - http://localhost:5173/)
echo.

REM --- 6) Run ---
echo [run] Starting backend on port 8000...
start "SIGMA backend" cmd /k "cd /d %BACKEND_DIR% && set BACKEND_HOST=0.0.0.0&& set BACKEND_PORT=8000&& set BACKEND_RELOAD=true&& %PYTHON_CMD% -m backend.app.main"

timeout /t 2 /nobreak > nul

echo [run] Starting frontend on port 5173...
start "SIGMA frontend" cmd /k "cd /d %FRONTEND_DIR% && npm run dev"

echo.
echo ============================
echo Done. Backend and frontend are running in separate windows.
echo Close those windows to stop the services.
echo ============================
echo.
pause
endlocal
