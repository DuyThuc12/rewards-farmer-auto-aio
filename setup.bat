@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
title Microsoft Rewards Bot - Automated Setup
color 0B

echo ==================================================================
echo         MICROSOFT REWARDS BOT - AUTOMATED SETUP
echo ==================================================================
echo  This installer sets up everything needed to run the bot on a
echo  new PC automatically (Python, Ollama, dependencies, shortcut).
echo.
echo  EVERY STEP ASKS FOR YOUR REVIEW AND CONFIRMATION BEFORE RUNNING.
echo ==================================================================
echo.
pause

set "ROOT_DIR=%~dp0"
cd /d "%ROOT_DIR%"

:: ====================================================================
:: STEP 1: CHECK PYTHON
:: ====================================================================
echo.
echo ------------------------------------------------------------------
echo [STEP 1/5] CHECK PYTHON ENVIRONMENT
echo ------------------------------------------------------------------
set "PYTHON_CMD="
python --version >nul 2>&1
if not errorlevel 1 (
    for /f "tokens=*" %%v in ('python --version 2^>^&1') do set "PY_VER=%%v"
    echo [OK] Found: !PY_VER!
    set "PYTHON_CMD=python"
    goto :python_done
)
py --version >nul 2>&1
if not errorlevel 1 (
    for /f "tokens=*" %%v in ('py --version 2^>^&1') do set "PY_VER=%%v"
    echo [OK] Found: !PY_VER!
    set "PYTHON_CMD=py"
    goto :python_done
)

echo [NOTICE] Python is not installed or not added to PATH.
echo.
echo [REVIEW] Do you want to automatically download and open the Python 3.12 installer?
set /p "ANS1=>> Enter Y to continue, N to skip: "
if /i "!ANS1!"=="n" (
    echo [*] Skipped Python installation. Note: Python is required to run the bot.
    goto :python_done
)
echo [*] Downloading Python 3.12 Installer from python.org...
curl -L -o "python_installer.exe" "https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe"
if not exist "python_installer.exe" (
    echo [ERROR] Could not download Python automatically. Please download from: https://www.python.org/downloads/
    goto :python_done
)
echo [*] Launching Python installer. Please CHECK: 'Add python.exe to PATH'!
start /wait python_installer.exe
del /f /q "python_installer.exe" >nul 2>&1
echo [*] Python installation finished. Restart this window if the command is not recognized yet.
set "PYTHON_CMD=python"

:python_done

:: ====================================================================
:: STEP 2: CHECK OLLAMA
:: ====================================================================
echo.
echo ------------------------------------------------------------------
echo [STEP 2/5] CHECK OLLAMA (LOCAL AI QUERY GENERATOR)
echo ------------------------------------------------------------------
echo Description: Ollama runs locally using the llama3.2 model to generate
echo natural search queries and help avoid Microsoft Rewards cooldowns.
echo.
ollama --version >nul 2>&1
if not errorlevel 1 (
    for /f "tokens=*" %%v in ('ollama --version 2^>^&1') do echo [OK] Found: %%v
    goto :ollama_install_done
)

echo [NOTICE] Ollama was not detected on this PC.
echo.
echo [REVIEW] Do you want to automatically download and install Ollama from ollama.com?
set /p "ANS2=>> Enter Y to continue, N to skip: "
if /i "!ANS2!"=="n" (
    echo [*] Skipped Ollama installation. The bot will use default Trends queries.
    goto :ollama_install_done
)
echo [*] Downloading OllamaSetup.exe from ollama.com...
curl -L -o "OllamaSetup.exe" "https://ollama.com/download/OllamaSetup.exe"
if not exist "OllamaSetup.exe" (
    echo [ERROR] Could not download Ollama automatically. Please download from: https://ollama.com
    goto :ollama_install_done
)
echo [*] Running Ollama installer...
start /wait OllamaSetup.exe
del /f /q "OllamaSetup.exe" >nul 2>&1
echo [OK] Ollama installation complete.

:ollama_install_done

:: Pull llama3.2 model
echo.
echo [REVIEW] Do you want to check / pull the llama3.2 AI model for Ollama now?
set /p "ANS2B=>> Enter Y to continue, N to skip: "
if /i "!ANS2B!"=="n" (
    echo [*] Skipped pulling model. You can pull it later with: ollama pull llama3.2
    goto :ollama_model_done
)
echo [*] Checking Ollama Server...
taskkill /f /im "ollama app.exe" >nul 2>&1
taskkill /f /im ollama.exe >nul 2>&1
ping -n 2 127.0.0.1 >nul
start /min "" ollama.exe serve
ping -n 4 127.0.0.1 >nul
echo [*] Pulling llama3.2 model (~2GB, first time only)...
ollama pull llama3.2
echo [OK] Model llama3.2 is ready!

:ollama_model_done

:: ====================================================================
:: STEP 3: CREATE VENV AND INSTALL DEPENDENCIES
:: ====================================================================
echo.
echo ------------------------------------------------------------------
echo [STEP 3/5] CREATE VENV AND INSTALL REQUIRED PACKAGES
echo ------------------------------------------------------------------
echo Packages: selenium, requests, python-dotenv, ollama,
echo           pygame-ce, pillow, pygetwindow, keyboard, ...
echo.
echo [REVIEW] Do you want to create a virtual environment (venv) and install dependencies?
set /p "ANS3=>> Enter Y to continue, N to skip: "
if /i "!ANS3!"=="n" (
    echo [*] Skipped venv creation.
    goto :venv_done
)

if not exist "venv\Scripts\python.exe" (
    echo [*] Initializing virtual environment venv...
    python -m venv venv
) else (
    echo [*] Virtual environment venv already exists.
)

if not exist "venv\Scripts\python.exe" (
    echo [ERROR] Could not create virtual environment venv. Please check your Python installation!
    goto :venv_done
)
echo [*] Installing/updating packages from requirements.txt...
".\venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
".\venv\Scripts\python.exe" -m pip install -r requirements.txt
echo [OK] All required packages installed!

:venv_done

:: ====================================================================
:: STEP 4: CREATE DESKTOP RUNNER FILE
:: ====================================================================
echo.
echo ------------------------------------------------------------------
echo [STEP 4/5] CREATE RUNNER SHORTCUT FILE ON DESKTOP
echo ------------------------------------------------------------------
set "USER_DESKTOP="
for /f "usebackq tokens=*" %%d in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"`) do (
    set "USER_DESKTOP=%%d"
)
if not defined USER_DESKTOP set "USER_DESKTOP=%USERPROFILE%\Desktop"

echo Current Bot folder  : !ROOT_DIR!
echo Your Desktop folder : !USER_DESKTOP!
echo.
echo [REVIEW] Do you want to create 'Run_Rewards_Bot.bat' directly on your Desktop?
set /p "ANS4=>> Enter Y to continue, N to skip: "
if /i "!ANS4!"=="n" (
    echo [*] Skipped Desktop shortcut creation. You can run autobot.bat directly.
    goto :shortcut_done
)

set "DESKTOP_BAT=!USER_DESKTOP!\Run_Rewards_Bot.bat"
(
    echo @echo off
    echo title Microsoft Rewards Bot
    echo cd /d "%ROOT_DIR%"
    echo call autobot.bat
) > "!DESKTOP_BAT!"
echo [OK] Created file: "!DESKTOP_BAT!"

:shortcut_done

:: ====================================================================
:: STEP 5: OPEN EDGE FOR FIRST-TIME SIGN-IN
:: ====================================================================
echo.
echo ------------------------------------------------------------------
echo [STEP 5/5] FIRST-TIME MICROSOFT REWARDS SIGN-IN
echo ------------------------------------------------------------------
echo For the bot to earn points, you need to sign in to your Microsoft
echo account once. Edge will open using the project's dedicated profile.
echo.
echo [REVIEW] Do you want to open Edge now to sign in to your account?
set /p "ANS5=>> Enter Y to continue, N to skip: "
if /i "!ANS5!"=="n" (
    echo [*] You can sign in later at any time.
    goto :login_done
)
echo [*] Launching Microsoft Edge...
echo [*] PLEASE SIGN IN TO YOUR ACCOUNT ON THE REWARDS PAGE THAT JUST OPENED.
echo [*] AFTER SIGNING IN, PLEASE CLOSE THE EDGE BROWSER WINDOW!
start "" msedge.exe --user-data-dir="%ROOT_DIR%data-dir" --profile-directory="Default" "https://rewards.bing.com/"
echo.
pause

:login_done

:: ====================================================================
:: COMPLETE
:: ====================================================================
echo.
echo ==================================================================
echo                         SETUP COMPLETE!
echo ==================================================================
echo  From now on, you only need to run:
echo    - "Run_Rewards_Bot.bat" on your Desktop
echo    - Or "autobot.bat" directly inside this folder
echo.
echo  The entire Desktop + Mobile farming process will run automatically
echo  in the background on a Virtual Desktop without interrupting you!
echo ==================================================================
pause
