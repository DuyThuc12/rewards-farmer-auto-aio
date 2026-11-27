# MICROSOFT REWARDS BOT (ALL-IN-ONE) — SETUP & USAGE GUIDE

Comprehensive Microsoft Rewards automation project:
- **Automated Desktop Tasks**: Quests, Daily Sets, More Activities, Visual Search, and Desktop Searches.
- **Automated Mobile Tasks**: Mobile browser emulation (iPhone / Android via CDP) to complete Mobile Search points.
- **Isolated on a Virtual Desktop**: Both flows run in the background on a Windows Virtual Desktop without stealing mouse focus or interrupting your main desktop.
- **Local Ollama AI (`llama3.2`)**: Generates natural search queries to help reduce the risk of Microsoft Rewards search cooldowns or penalties.

---

## 1. FIRST-TIME SETUP ON A NEW PC (~3 MINUTES)

After extracting or cloning this folder on a new PC:

1. **Double-click `setup.bat`**.
2. The installer will ask for your confirmation (Review) at each step and automatically perform:
   - **Step 1**: Check for Python (downloads the official installer from python.org if missing).
   - **Step 2**: Download and install Ollama + the `llama3.2` AI model for search query generation.
   - **Step 3**: Create a virtual environment (`venv`) and install all required dependencies.
   - **Step 4**: Detect the project folder path and create a `Run_Rewards_Bot.bat` shortcut on your Desktop.
   - **Step 5**: Launch Edge so you can **sign in to your Microsoft account for the first time**.

3. **Sign in to Microsoft Rewards**:
   - When Edge opens, sign in to your Microsoft account at [rewards.bing.com](https://rewards.bing.com/).
   - Once signed in, **close the Edge browser window**.

---

## 2. DAILY USAGE

Every day, you only need to do one thing:
- **Double-click `Run_Rewards_Bot.bat` on your Desktop** (or `autobot.bat` inside this folder).

### Automated Workflow:
1. The bot creates **a single Windows Virtual Desktop**.
2. Launches Edge on the virtual desktop and switches you back to your main desktop.
3. Runs all Desktop tasks, then switches to Mobile emulation (via CDP) to complete Mobile Search points without leaving extra virtual desktops behind.
4. Once both Desktop and Mobile tasks finish, it closes Edge, cleans up the virtual desktop, returns to your main desktop, and prints the summary.

---

## 3. KEY PROJECT FILES

| File | Purpose |
|---|---|
| **`setup.bat`** | Interactive step-by-step setup script for a new PC |
| **`autobot.bat`** | Main daily runner (`src/main.py --unattended --mobile`) |
| **`src/mobile_search.py`** | Integrated Mobile Search module using CDP emulation |
| **`mobile_rewards_search.py`** | Standalone Mobile Search script (shares `src/mobile_search.py` and `src/desktop_utils.py`) |
| **`run_mobile_search.bat`** | Batch script to run only the Mobile Search flow if needed |
| **`requirements.txt`** | Required Python packages |
| **`.env`** | Bot configuration parameters (AI model, Virtual Desktop, etc.) |
| **`data-dir/`** | Edge browser profile directory storing your login session (created after first login) |

---

## 4. TROUBLESHOOTING

### A. Error: "Profile is open in another window" (Lock file)
- **Cause**: Edge is currently open with the profile, or a previous run exited unexpectedly.
- **Fix**: Close all Edge windows, then run `autobot.bat` again. The bot includes automatic lock cleanup for stale runs.

### B. Ollama returns "404 Not Found" or Model Not Found
- Run `ollama list` in Terminal/CMD to check if `llama3.2` is installed.
- If not, run: `ollama pull llama3.2`.
- Restart the Ollama server with: `ollama serve`.

### C. Switching to Another Microsoft Account
- Delete the `data-dir` folder in the project directory, then run `setup.bat` (Step 5) to open Edge and sign in with the new account.
