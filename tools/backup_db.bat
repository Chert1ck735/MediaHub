@echo off
chcp 65001 > nul
setlocal EnableExtensions

REM ============================================================
REM  pg_dump БД проекта в backups/media_project_YYYY-MM-DD_HHMM.sql
REM  Запускать ПЕРЕД prod-миграциями и перед опасными операциями.
REM ============================================================

set "PROJECT_ROOT=%~dp0.."
set "BACKUP_DIR=%PROJECT_ROOT%\backups"
if not exist "%BACKUP_DIR%" mkdir "%BACKUP_DIR%"

REM Читаем .env, чтобы взять DB_* без хардкода.
for /f "tokens=1,2 delims==" %%A in ('type "%PROJECT_ROOT%\.env" 2^>nul ^| findstr /R "^[ ]*DB_"') do (
    set "%%A=%%B"
)
REM Убираем пробелы (в .env у пользователя есть ведущие пробелы).
set "DB_NAME=%DB_NAME: =%"
set "DB_USER=%DB_USER: =%"
set "DB_HOST=%DB_HOST: =%"
set "DB_PORT=%DB_PORT: =%"
set "DB_PASS=%DB_PASS: =%"

if "%DB_NAME%"=="" (
    echo [!] DB_NAME not found in .env
    exit /b 1
)

set "TS=%date:~6,4%-%date:~3,2%-%date:~0,2%_%time:~0,2%%time:~3,2%"
set "TS=%TS: =0%"
set "OUT=%BACKUP_DIR%\%DB_NAME%_%TS%.sql"

echo Backing up %DB_NAME% to:
echo   %OUT%
echo.

set "PGPASSWORD=%DB_PASS%"
pg_dump -h %DB_HOST% -p %DB_PORT% -U %DB_USER% -d %DB_NAME% -f "%OUT%" --no-owner --no-acl
set "RC=%ERRORLEVEL%"
set "PGPASSWORD="

if not "%RC%"=="0" (
    echo [!] pg_dump failed with exit code %RC%
    exit /b %RC%
)

for %%I in ("%OUT%") do set "SZ=%%~zI"
echo Done. Size: %SZ% bytes.
echo Last 5 backups:
dir /b /o-d "%BACKUP_DIR%\%DB_NAME%_*.sql" 2^>nul | head -n 5

endlocal
