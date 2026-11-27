@echo off
setlocal enabledelayedexpansion
title Microsoft Rewards - Mobile Search Automation
color 0B

echo ======================================================
echo       MICROSOFT REWARDS - MOBILE SEARCH AUTOMATION
echo ======================================================
echo.

:: 1. Enable Virtual Desktop
set "USE_VIRTUAL_DESKTOP=true"

:: 2. Clean up stale driver processes
taskkill /f /im msedgedriver.exe >nul 2>&1

:: 3. Locate Python venv
set "PYTHON_EXE="
if exist "%~dp0venv\Scripts\python.exe" set "PYTHON_EXE=%~dp0venv\Scripts\python.exe"
if not defined PYTHON_EXE if exist "%~dp0rewards-farmer\venv\Scripts\python.exe" set "PYTHON_EXE=%~dp0rewards-farmer\venv\Scripts\python.exe"
if not defined PYTHON_EXE set "PYTHON_EXE=python"

:: 4. Locate mobile script
set "MOBILE_SCRIPT="
if exist "%~dp0mobile_rewards_search.py" set "MOBILE_SCRIPT=%~dp0mobile_rewards_search.py"
if not defined MOBILE_SCRIPT if exist "%~dp0rewards-farmer\mobile_rewards_search.py" set "MOBILE_SCRIPT=%~dp0rewards-farmer\mobile_rewards_search.py"
if not defined MOBILE_SCRIPT (
    echo [ERROR] Could not find mobile_rewards_search.py!
    pause
    exit /b 1
)

:: 5. Run
echo [*] Starting Mobile Search on Virtual Desktop...
echo.
"%PYTHON_EXE%" "%MOBILE_SCRIPT%"

echo.
echo ======================================================
echo                     COMPLETED
echo ======================================================
pause
