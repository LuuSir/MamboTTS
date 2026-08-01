@echo off
title MamboTTS
:: Force switch to script directory (avoid admin-elevated System32 cwd issue)
cd /d "%~dp0"

:: Check Python (and set windowless variant for auto-closing console)
py --version >nul 2>&1
if not errorlevel 1 (
    set PY_CMD=py
    set PYW_CMD=pyw
) else (
    python --version >nul 2>&1
    if not errorlevel 1 (
        set PY_CMD=python
        set PYW_CMD=pythonw
    ) else (
        echo [ERROR] Python not found! Please install Python 3.10+
        echo Download: https://www.python.org/downloads/
        echo Remember to check "Add Python to PATH" during install.
        pause
        exit /b 1
    )
)

:: Check if windowless Python exists (pyw/pythonw)
%PYW_CMD% --version >nul 2>&1
if errorlevel 1 (
    :: Windowless Python not found; use regular Python (console stays visible)
    echo [INFO] Windowless Python not found, using console mode.
    %PY_CMD% bootstrap.py
    if errorlevel 1 (
        echo.
        echo [ERROR] Bootstrap exited with error.
        pause
    )
) else (
    :: Windowless Python found; launch in background and close this console
    :: bootstrap.py shows its own tk progress window and error dialogs
    start "" %PYW_CMD% bootstrap.py
)
exit
