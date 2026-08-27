@echo off
REM Double-click to start the festival bot on Windows.
REM Auto-restarts if it crashes. Keep this window open all day.

cd /d "%~dp0"
if not exist "bot.py" cd ..

REM Prefer Python 3.12 - best-tested for discord.py voice. Fall back to whatever exists.
set PY=python
py -3.12 --version >nul 2>&1 && set PY=py -3.12
if "%PY%"=="python" ( py -3.11 --version >nul 2>&1 && set PY=py -3.11 )

if not exist ".venv" (
  echo First run - setting up, this takes a couple of minutes...
  %PY% -m venv .venv
  .venv\Scripts\pip install --upgrade pip --quiet
  .venv\Scripts\pip install -r requirements.txt
  if errorlevel 1 (
    echo.
    echo !! Install failed. Delete the .venv folder and run this again.
    pause
    exit /b 1
  )
)

REM Self-heal the Python 3.13+ audioop removal in environments built earlier.
.venv\Scripts\python -c "import audioop" >nul 2>&1
if errorlevel 1 (
  echo Patching audio support for this Python version...
  .venv\Scripts\pip install --quiet --upgrade "discord.py[voice]>=2.6.0" audioop-lts
)

if not exist ".env" (
  echo.
  echo !! No .env file found.
  echo !! Copy .env.example to .env, paste your bot token into it, then run this again.
  echo.
  pause
  exit /b 1
)

where ffmpeg >nul 2>&1
if errorlevel 1 (
  echo.
  echo !! ffmpeg not found - bot will run but the kitchen speaker stays silent.
  echo !! Fix with:  winget install Gyan.FFmpeg
  echo.
)

echo Starting. Keep this window open all day. Ctrl+C to stop.

:loop
.venv\Scripts\python bot.py
echo.
echo !! Bot stopped. Restarting in 5 seconds... (close this window to quit)
timeout /t 5 /nobreak >nul
goto loop
