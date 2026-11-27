@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
title Microsoft Rewards Bot - Automated Setup
color 0B

echo ==================================================================
echo         MICROSOFT REWARDS BOT - AUTOMATED SETUP
echo ==================================================================
echo  This installer sets up everything needed to run the bot on a
echo  new PC (Python 3.12+, Ollama, venv, .env, Desktop shortcut,
echo  and first-time Edge sign-in).
echo.
echo  EVERY STEP ASKS FOR YOUR REVIEW AND CONFIRMATION BEFORE RUNNING.
echo ==================================================================
echo.
pause

set "ROOT_DIR=%~dp0"
cd /d "%ROOT_DIR%"

set "PYTHON_EXE="
set "OLLAMA_EXE="
set "OLLAMA_READY=0"
set "DEFAULT_OLLAMA_MODEL=llama3.2"

:: ====================================================================
:: STEP 1/6: CHECK PYTHON (>= 3.12)
:: ====================================================================
echo.
echo ------------------------------------------------------------------
echo [STEP 1/6] CHECK PYTHON ENVIRONMENT (REQUIRED: 3.12+)
echo ------------------------------------------------------------------
call :detect_python
if defined PYTHON_EXE (
    echo [OK] Found compatible Python: !PY_VER!
    echo      Path: !PYTHON_EXE!
    goto :python_done
)

echo [NOTICE] Python 3.12 or newer was not detected on this PC.
echo.
echo [REVIEW] Do you want to automatically download and open the Python 3.12 installer?
set /p "ANS1=>> Enter Y to continue, N to skip: "
if /i "!ANS1!"=="n" (
    echo [*] Skipped Python installation. Note: Python 3.12+ is required to run the bot.
    goto :python_done
)
echo [*] Downloading Python 3.12 installer from python.org...
curl -L -o "python_installer.exe" "https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe"
if not exist "python_installer.exe" (
    echo [ERROR] Could not download Python automatically. Please download from: https://www.python.org/downloads/
    goto :python_done
)
echo [*] Launching Python installer. Please CHECK: 'Add python.exe to PATH'!
start /wait "" "python_installer.exe"
del /f /q "python_installer.exe" >nul 2>&1
call :detect_python
if defined PYTHON_EXE (
    echo [OK] Detected newly installed Python: !PY_VER!
) else (
    echo [WARNING] Python 3.12+ was not detected in this session yet.
    echo           Please restart setup.bat after installation finishes.
)

:python_done

:: ====================================================================
:: STEP 2/6: CHECK OLLAMA (OPTIONAL LOCAL AI QUERY GENERATOR)
:: ====================================================================
echo.
echo ------------------------------------------------------------------
echo [STEP 2/6] CHECK OLLAMA (OPTIONAL LOCAL AI QUERY GENERATOR)
echo ------------------------------------------------------------------
echo Description: Ollama runs locally using %DEFAULT_OLLAMA_MODEL% to generate
echo natural search queries and help avoid Microsoft Rewards cooldowns.
echo (If skipped, the bot will use Google Trends queries instead.)
echo.
call :detect_ollama
if defined OLLAMA_EXE (
    for /f "tokens=*" %%v in ('"!OLLAMA_EXE!" --version 2^>^&1') do echo [OK] Found: %%v
    goto :ollama_install_done
)

echo [NOTICE] Ollama was not detected on this PC.
echo.
echo [REVIEW] Do you want to automatically download and install Ollama from ollama.com?
set /p "ANS2=>> Enter Y to continue, N to skip: "
if /i "!ANS2!"=="n" (
    echo [*] Skipped Ollama installation. The bot will use Trends queries by default.
    goto :ollama_model_done
)
echo [*] Downloading OllamaSetup.exe from ollama.com...
curl -L -o "OllamaSetup.exe" "https://ollama.com/download/OllamaSetup.exe"
if not exist "OllamaSetup.exe" (
    echo [ERROR] Could not download Ollama automatically. Please download from: https://ollama.com
    goto :ollama_model_done
)
echo [*] Running Ollama installer...
start /wait "" "OllamaSetup.exe"
del /f /q "OllamaSetup.exe" >nul 2>&1
call :detect_ollama
if defined OLLAMA_EXE (
    echo [OK] Ollama installation complete.
) else (
    echo [WARNING] Ollama executable not found after install. You can pull the model later.
    goto :ollama_model_done
)

:ollama_install_done

:: Pull default model
echo.
echo [REVIEW] Do you want to check / pull the %DEFAULT_OLLAMA_MODEL% AI model for Ollama now?
set /p "ANS2B=>> Enter Y to continue, N to skip: "
if /i "!ANS2B!"=="n" (
    echo [*] Skipped pulling model. You can pull it later with: ollama pull %DEFAULT_OLLAMA_MODEL%
    goto :ollama_model_done
)
echo [*] Ensuring Ollama server is running...
set "NO_PROXY=localhost,127.0.0.1"
curl -s --connect-timeout 2 --max-time 3 http://localhost:11434/api/tags >nul 2>&1
if errorlevel 1 (
    start /min "" "!OLLAMA_EXE!" serve
    ping -n 5 127.0.0.1 >nul
)
echo [*] Pulling %DEFAULT_OLLAMA_MODEL% model (~2GB, first time only)...
"!OLLAMA_EXE!" pull %DEFAULT_OLLAMA_MODEL%
if errorlevel 1 (
    echo [WARNING] Could not pull %DEFAULT_OLLAMA_MODEL%. You can retry later with: ollama pull %DEFAULT_OLLAMA_MODEL%
) else (
    set "OLLAMA_READY=1"
    echo [OK] Model %DEFAULT_OLLAMA_MODEL% is ready!
)

:ollama_model_done

:: ====================================================================
:: STEP 3/6: CREATE VENV AND INSTALL DEPENDENCIES
:: ====================================================================
echo.
echo ------------------------------------------------------------------
echo [STEP 3/6] CREATE VENV AND INSTALL REQUIRED PACKAGES
echo ------------------------------------------------------------------
echo Packages: selenium, requests, python-dotenv, ollama,
echo           pygame-ce, pillow, pygetwindow, keyboard, matplotlib
echo.
echo [REVIEW] Do you want to create a virtual environment (venv) and install dependencies?
set /p "ANS3=>> Enter Y to continue, N to skip: "
if /i "!ANS3!"=="n" (
    echo [*] Skipped venv creation.
    goto :venv_done
)

if not exist "venv\Scripts\python.exe" (
    if not defined PYTHON_EXE (
        echo [ERROR] No compatible Python 3.12+ found. Cannot create venv.
        goto :venv_done
    )
    echo [*] Initializing virtual environment venv...
    "!PYTHON_EXE!" -m venv venv
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
if errorlevel 1 (
    echo [ERROR] Package installation failed! Check your internet connection and errors above.
) else (
    echo [OK] All required packages installed!
)

:venv_done

:: ====================================================================
:: STEP 4/6: CREATE DEFAULT .env CONFIGURATION
:: ====================================================================
echo.
echo ------------------------------------------------------------------
echo [STEP 4/6] CONFIGURE .env SETTINGS
echo ------------------------------------------------------------------
if exist ".env" (
    echo [OK] Existing .env file found. Keeping your current configuration.
    goto :env_done
)

set "DEFAULT_QUERY_SOURCE=trends"
if "!OLLAMA_READY!"=="1" set "DEFAULT_QUERY_SOURCE=llm"

echo No .env file was found in this folder.
echo Default configuration to create:
echo   QUERY_SOURCE=!DEFAULT_QUERY_SOURCE!
echo   LLM_PROVIDER=local
echo   LOCAL_LLM_MODEL=%DEFAULT_OLLAMA_MODEL%
echo   USE_VIRTUAL_DESKTOP=true
echo   CLEANUP_VIRTUAL_DESKTOP=true
echo   ENABLE_MOBILE_SEARCH=true
echo.
echo [REVIEW] Do you want to create this .env file now?
set /p "ANS_ENV=>> Enter Y to continue, N to skip: "
if /i "!ANS_ENV!"=="n" (
    echo [*] Skipped .env creation. You can configure it later with: .\venv\Scripts\python.exe src\init-config.py
    goto :env_done
)

(
    echo # Microsoft Rewards Bot configuration
    echo QUERY_SOURCE=!DEFAULT_QUERY_SOURCE!
    echo LLM_PROVIDER=local
    echo LOCAL_LLM_MODEL=%DEFAULT_OLLAMA_MODEL%
    echo.
    echo # Windows Virtual Desktop and Mobile Search
    echo USE_VIRTUAL_DESKTOP=true
    echo SWITCH_BACK_TO_MAIN_DESKTOP=true
    echo CLEANUP_VIRTUAL_DESKTOP=true
    echo ENABLE_MOBILE_SEARCH=true
) > ".env"
echo [OK] Created .env configuration file.

:env_done

:: ====================================================================
:: STEP 5/6: CREATE DESKTOP RUNNER SHORTCUT
:: ====================================================================
echo.
echo ------------------------------------------------------------------
echo [STEP 5/6] CREATE RUNNER SHORTCUT FILE ON DESKTOP
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
    echo [*] Skipped Desktop shortcut creation. You can run run_rewards.bat directly.
    goto :shortcut_done
)

set "DESKTOP_BAT=!USER_DESKTOP!\Run_Rewards_Bot.bat"
(
    echo @echo off
    echo title Microsoft Rewards Bot
    echo cd /d "%ROOT_DIR%"
    echo call run_rewards.bat %%*
) > "!DESKTOP_BAT!"
echo [OK] Created file: "!DESKTOP_BAT!"

:shortcut_done

:: ====================================================================
:: STEP 6/6: OPEN EDGE FOR FIRST-TIME SIGN-IN
:: ====================================================================
echo.
echo ------------------------------------------------------------------
echo [STEP 6/6] FIRST-TIME MICROSOFT REWARDS SIGN-IN
echo ------------------------------------------------------------------
echo For the bot to earn points, you need to sign in to your Microsoft
echo account once in the project's isolated Edge profile:
echo   1. Sign in to the Edge profile (top-right profile icon)
echo   2. Verify sign-in on BOTH rewards.bing.com AND www.bing.com
echo   3. Close the Edge window when finished
echo.
echo Tip: For multiple accounts, run:
echo      .\venv\Scripts\python.exe src\init-config.py --manage-accounts
echo.
echo [REVIEW] Do you want to open Edge now to sign in to your default account?
set /p "ANS5=>> Enter Y to continue, N to skip: "
if /i "!ANS5!"=="n" (
    echo [*] You can sign in later at any time.
    goto :login_done
)

call :detect_edge
if not defined EDGE_EXE (
    echo [ERROR] Could not locate Microsoft Edge [msedge.exe]. Please install Edge first.
    goto :login_done
)

echo [*] Launching Microsoft Edge...
echo [*] SIGN IN ON BOTH rewards.bing.com AND www.bing.com, THEN CLOSE EDGE!
start "" "!EDGE_EXE!" --user-data-dir="%ROOT_DIR%data-dir" --profile-directory="Default" "https://rewards.bing.com/" "https://www.bing.com/"
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
echo    - Or "run_rewards.bat" directly inside this folder
echo.
echo  For Windows Task Scheduler (no pause at exit):
echo    run_rewards.bat --no-pause
echo.
echo  The entire Desktop + Mobile farming process will run automatically
echo  in the background on a Virtual Desktop without interrupting you!
echo ==================================================================
pause
exit /b 0

:: ====================================================================
:: HELPERS
:: ====================================================================
:detect_python
set "PYTHON_EXE="
set "PY_VER="
for %%c in (python "py -3") do (
    if not defined PYTHON_EXE (
        %%~c -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>&1
        if not errorlevel 1 (
            for /f "delims=" %%p in ('%%~c -c "import sys; print(sys.executable)" 2^>nul') do set "PYTHON_EXE=%%p"
            for /f "tokens=*" %%v in ('%%~c --version 2^>^&1') do set "PY_VER=%%v"
        )
    )
)
if not defined PYTHON_EXE (
    for %%d in (
        "%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
        "%ProgramFiles%\Python314\python.exe"
        "%ProgramFiles%\Python313\python.exe"
        "%ProgramFiles%\Python312\python.exe"
    ) do (
        if not defined PYTHON_EXE if exist "%%~d" (
            "%%~d" -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>&1
            if not errorlevel 1 (
                set "PYTHON_EXE=%%~d"
                for /f "tokens=*" %%v in ('"%%~d" --version 2^>^&1') do set "PY_VER=%%v"
            )
        )
    )
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

:detect_edge
set "EDGE_EXE="
for /f "delims=" %%p in ('where msedge 2^>nul') do (
    if not defined EDGE_EXE set "EDGE_EXE=%%p"
)
if not defined EDGE_EXE if exist "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" (
    set "EDGE_EXE=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
)
if not defined EDGE_EXE if exist "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe" (
    set "EDGE_EXE=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"
)
goto :eof
