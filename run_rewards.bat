@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
title Microsoft Rewards Farmer - Daily Runner
color 0A

:: Parse wrapper-only flags (--no-pause) and forward the rest to src/main.py
set "NO_PAUSE=0"
set "USER_HAS_MOBILE_FLAG=0"
set "EXTRA_ARGS="
:parse_args
if "%~1"=="" goto :args_done
if /i "%~1"=="--no-pause" (
    set "NO_PAUSE=1"
) else (
    if /i "%~1"=="--mobile" set "USER_HAS_MOBILE_FLAG=1"
    if /i "%~1"=="--no-mobile" set "USER_HAS_MOBILE_FLAG=1"
    set "EXTRA_ARGS=!EXTRA_ARGS! %1"
)
shift
goto :parse_args
:args_done

echo ======================================================
echo           MICROSOFT REWARDS FARMER
echo      Automated Flow: Desktop + Mobile Search
echo        (Shared Virtual Desktop Workflow)
echo ======================================================
echo.

:: 1. Detect project directory
set "PROJECT_DIR="
if exist "%~dp0src\main.py" set "PROJECT_DIR=%~dp0"
if not defined PROJECT_DIR if exist "%~dp0rewards-farmer\src\main.py" set "PROJECT_DIR=%~dp0rewards-farmer"
if not defined PROJECT_DIR (
    color 0C
    echo [ERROR] Could not find project directory containing src\main.py!
    call :maybe_pause
    exit /b 1
)
cd /d "!PROJECT_DIR!"
echo [OK] Project directory: !PROJECT_DIR!

:: 2. Keep localhost direct (avoid routing local Ollama traffic through a proxy)
if defined NO_PROXY (
    echo !NO_PROXY! | findstr /i "localhost" >nul 2>&1
    if errorlevel 1 set "NO_PROXY=!NO_PROXY!,localhost,127.0.0.1"
) else (
    set "NO_PROXY=localhost,127.0.0.1"
)

:: 3. Read relevant defaults from .env without overriding explicit environment variables
set "ENV_QUERY_SOURCE="
set "ENV_LLM_PROVIDER="
set "ENV_LOCAL_LLM_MODEL="
set "ENV_USE_VIRTUAL_DESKTOP="
set "ENV_CLEANUP_VIRTUAL_DESKTOP="
set "ENV_ENABLE_MOBILE_SEARCH="

if exist ".env" (
    for /f "usebackq eol=# tokens=1* delims==" %%k in (".env") do (
        set "KEY=%%k"
        set "VAL=%%l"
        for /f "tokens=* delims= " %%a in ("!KEY!") do set "KEY=%%a"
        if /i "!KEY!"=="QUERY_SOURCE" set "ENV_QUERY_SOURCE=!VAL!"
        if /i "!KEY!"=="LLM_PROVIDER" set "ENV_LLM_PROVIDER=!VAL!"
        if /i "!KEY!"=="LOCAL_LLM_MODEL" set "ENV_LOCAL_LLM_MODEL=!VAL!"
        if /i "!KEY!"=="USE_VIRTUAL_DESKTOP" set "ENV_USE_VIRTUAL_DESKTOP=!VAL!"
        if /i "!KEY!"=="CLEANUP_VIRTUAL_DESKTOP" set "ENV_CLEANUP_VIRTUAL_DESKTOP=!VAL!"
        if /i "!KEY!"=="ENABLE_MOBILE_SEARCH" set "ENV_ENABLE_MOBILE_SEARCH=!VAL!"
    )
)

:: Apply sensible defaults only when neither the shell environment nor .env set them
if not defined USE_VIRTUAL_DESKTOP if not defined ENV_USE_VIRTUAL_DESKTOP set "USE_VIRTUAL_DESKTOP=true"
if not defined CLEANUP_VIRTUAL_DESKTOP if not defined ENV_CLEANUP_VIRTUAL_DESKTOP set "CLEANUP_VIRTUAL_DESKTOP=true"
if not defined ENABLE_MOBILE_SEARCH if not defined ENV_ENABLE_MOBILE_SEARCH set "ENABLE_MOBILE_SEARCH=true"

set "EFF_QUERY_SOURCE=!QUERY_SOURCE!"
if not defined EFF_QUERY_SOURCE set "EFF_QUERY_SOURCE=!ENV_QUERY_SOURCE!"
if not defined EFF_QUERY_SOURCE set "EFF_QUERY_SOURCE=llm"

set "EFF_LLM_PROVIDER=!LLM_PROVIDER!"
if not defined EFF_LLM_PROVIDER set "EFF_LLM_PROVIDER=!ENV_LLM_PROVIDER!"
if not defined EFF_LLM_PROVIDER set "EFF_LLM_PROVIDER=local"

set "EFF_LOCAL_MODEL=!LOCAL_LLM_MODEL!"
if not defined EFF_LOCAL_MODEL set "EFF_LOCAL_MODEL=!ENV_LOCAL_LLM_MODEL!"
if not defined EFF_LOCAL_MODEL set "EFF_LOCAL_MODEL=llama3.2"

:: 4. Ensure Ollama is running ONLY when using local LLM queries
set "NEEDS_OLLAMA=0"
if /i "!EFF_QUERY_SOURCE!"=="llm" (
    if /i "!EFF_LLM_PROVIDER!"=="local" set "NEEDS_OLLAMA=1"
    if /i "!EFF_LLM_PROVIDER!"=="ollama" set "NEEDS_OLLAMA=1"
)

if "!NEEDS_OLLAMA!"=="0" (
    echo [*] Query source: !EFF_QUERY_SOURCE! [provider: !EFF_LLM_PROVIDER!] - skipping Ollama check.
    goto :ollama_done
)

echo.
echo [*] Checking Ollama for model "!EFF_LOCAL_MODEL!"...
call :check_ollama
if "!OLLAMA_OK!"=="1" (
    echo [OK] Ollama and model "!EFF_LOCAL_MODEL!" are ready.
    if not defined LOCAL_LLM_MODEL if not defined ENV_LOCAL_LLM_MODEL set "LOCAL_LLM_MODEL=!EFF_LOCAL_MODEL!"
    goto :ollama_done
)

call :detect_ollama
if not defined OLLAMA_EXE (
    echo [WARNING] Ollama not found. Falling back to Trends queries for this run.
    set "QUERY_SOURCE=trends"
    goto :ollama_done
)

echo [*] Ollama is not ready. Starting Ollama server...
start "" /min "!OLLAMA_EXE!" serve
echo [*] Waiting for Ollama to respond (up to 20 seconds)...

for /L %%i in (1,1,10) do (
    if "!OLLAMA_OK!"=="0" (
        ping -n 3 127.0.0.1 >nul
        call :check_ollama
    )
)
if "!OLLAMA_OK!"=="1" (
    echo [OK] Ollama and model "!EFF_LOCAL_MODEL!" are ready!
    if not defined LOCAL_LLM_MODEL if not defined ENV_LOCAL_LLM_MODEL set "LOCAL_LLM_MODEL=!EFF_LOCAL_MODEL!"
) else (
    echo [WARNING] Ollama or model "!EFF_LOCAL_MODEL!" did not respond. Falling back to Trends queries.
    set "QUERY_SOURCE=trends"
)

:ollama_done

:: 5. Check Python venv
set "PYTHON_EXE="
if exist ".\venv\Scripts\python.exe" set "PYTHON_EXE=.\venv\Scripts\python.exe"
if not defined PYTHON_EXE (
    color 0C
    echo [ERROR] Python venv not found!
    echo Please run setup.bat first.
    call :maybe_pause
    exit /b 1
)
echo [OK] Python: !PYTHON_EXE!

:: 6. Build CLI arguments (respect ENABLE_MOBILE_SEARCH and user flags)
set "MOBILE_FLAG="
if "!USER_HAS_MOBILE_FLAG!"=="0" (
    set "EFF_MOBILE=!ENABLE_MOBILE_SEARCH!"
    if not defined EFF_MOBILE set "EFF_MOBILE=!ENV_ENABLE_MOBILE_SEARCH!"
    if /i "!EFF_MOBILE!"=="true" set "MOBILE_FLAG=--mobile"
    if /i "!EFF_MOBILE!"=="1" set "MOBILE_FLAG=--mobile"
    if /i "!EFF_MOBILE!"=="yes" set "MOBILE_FLAG=--mobile"
)

echo.
echo ======================================================
echo   RUNNING AUTOMATION: DESKTOP REWARDS + MOBILE SEARCH
echo ======================================================
echo.

"!PYTHON_EXE!" src/main.py --unattended !MOBILE_FLAG!!EXTRA_ARGS!
set "RUN_EXIT=!errorlevel!"

echo.
if "!RUN_EXIT!"=="0" (
    echo [OK] Completed the Microsoft Rewards workflow!
) else (
    echo [WARNING] Run exited with code !RUN_EXIT!. Check logs in the runs\ directory.
)

echo.
echo ======================================================
echo              ALL WORKFLOWS COMPLETED!
echo ======================================================
call :maybe_pause
exit /b !RUN_EXIT!

:: ============================================
:: HELPERS
:: ============================================
:check_ollama
set "OLLAMA_OK=0"
curl -s --connect-timeout 2 --max-time 3 http://localhost:11434/api/tags 2>nul > "%TEMP%\ollama_check_%RANDOM%.tmp"
for %%f in ("%TEMP%\ollama_check_*.tmp") do (
    findstr /i /c:"!EFF_LOCAL_MODEL!" "%%f" >nul 2>&1
    if not errorlevel 1 set "OLLAMA_OK=1"
    del /f /q "%%f" >nul 2>&1
)
goto :eof

:detect_ollama
set "OLLAMA_EXE="
for /f "delims=" %%p in ('where ollama 2^>nul') do (
    if not defined OLLAMA_EXE set "OLLAMA_EXE=%%p"
)
if not defined OLLAMA_EXE if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" (
    set "OLLAMA_EXE=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
)
goto :eof

:maybe_pause
if "!NO_PAUSE!"=="0" pause
goto :eof
