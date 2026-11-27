@echo off
setlocal enabledelayedexpansion
title Microsoft Rewards Auto Bot - All in One
color 0A

echo ======================================================
echo           MICROSOFT REWARDS AUTO BOT
echo      Automated Flow: Desktop + Mobile Search
echo        (Shared Virtual Desktop Workflow)
echo ======================================================
echo.

:: 1. Detect project directory
set "PROJECT_DIR="
if exist "%~dp0rewards-farmer\src\main.py" set "PROJECT_DIR=%~dp0rewards-farmer"
if not defined PROJECT_DIR if exist "%~dp0src\main.py" set "PROJECT_DIR=%~dp0"
if not defined PROJECT_DIR (
    color 0C
    echo [ERROR] Could not find rewards-farmer directory!
    pause
    exit /b 1
)
cd /d "!PROJECT_DIR!"
echo [OK] Project directory: !PROJECT_DIR!

:: 2. Bypass proxy for localhost and set Ollama models directory if present on D:
set "NO_PROXY=localhost,127.0.0.1"
set "HTTP_PROXY="
set "HTTPS_PROXY="
if exist "D:\Duy Thuc\.ollama\models" set "OLLAMA_MODELS=D:\Duy Thuc\.ollama\models"

:: 3. Virtual Desktop + Mobile Search settings
set "USE_VIRTUAL_DESKTOP=true"
set "CLEANUP_VIRTUAL_DESKTOP=true"
set "ENABLE_MOBILE_SEARCH=true"

:: 4. Clean up stale driver processes (without deleting active session locks)
taskkill /f /im msedgedriver.exe >nul 2>&1

:: 5. Ensure Ollama is running
echo.
echo [*] Checking Ollama...
call :check_ollama
if "!OLLAMA_OK!"=="1" (
    echo [OK] Ollama and model llama3.2 are ready.
    goto :ollama_done
)

where ollama >nul 2>&1
if errorlevel 1 (
    echo [WARNING] ollama not found in PATH. Bot will use fallback Trends queries.
    set "QUERY_SOURCE=trends"
    goto :ollama_done
)

echo [*] Ollama is not ready. Restarting Ollama server...
taskkill /f /im "ollama app.exe" >nul 2>&1
taskkill /f /im ollama.exe >nul 2>&1
ping -n 3 127.0.0.1 >nul
start "" /min ollama.exe serve
echo [*] Waiting for Ollama to start and initialize GPU (up to 20 seconds)...

for /L %%i in (1,1,20) do (
    if "!OLLAMA_OK!"=="0" (
        ping -n 2 127.0.0.1 >nul
        call :check_ollama
    )
)
if "!OLLAMA_OK!"=="1" (
    echo [OK] Ollama and model llama3.2 are ready!
) else (
    echo [WARNING] Ollama did not respond. Bot will use fallback Trends queries.
    set "QUERY_SOURCE=trends"
)

:ollama_done

:: 6. Check Python venv
set "PYTHON_EXE="
if exist ".\venv\Scripts\python.exe" set "PYTHON_EXE=.\venv\Scripts\python.exe"
if not defined PYTHON_EXE (
    color 0C
    echo [ERROR] Python venv not found!
    echo Please run setup.bat first.
    pause
    exit /b 1
)
echo [OK] Python: !PYTHON_EXE!

:: 7. Run Desktop + Mobile Search on a single Virtual Desktop
echo.
echo ======================================================
echo   RUNNING AUTOMATION: DESKTOP REWARDS + MOBILE SEARCH
echo ======================================================
echo.

"!PYTHON_EXE!" src/main.py --unattended --mobile
set "RUN_EXIT=!errorlevel!"

echo.
if "!RUN_EXIT!"=="0" (
    echo [OK] Completed the entire Desktop + Mobile Search workflow!
) else (
    echo [WARNING] Run exited with code !RUN_EXIT!. Check logs in the runs\ directory.
)

echo.
echo ======================================================
echo              ALL WORKFLOWS COMPLETED!
echo ======================================================
pause
exit /b !RUN_EXIT!

:: ============================================
:: CHECK OLLAMA HELPER (avoids pipes in for loop)
:: ============================================
:check_ollama
set "OLLAMA_OK=0"
curl -s --connect-timeout 2 --max-time 3 http://localhost:11434/api/tags 2>nul > "%TEMP%\ollama_check.tmp"
findstr /i "llama3.2" "%TEMP%\ollama_check.tmp" >nul 2>&1
if not errorlevel 1 set "OLLAMA_OK=1"
del /f /q "%TEMP%\ollama_check.tmp" >nul 2>&1
goto :eof
