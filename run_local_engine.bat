@echo off
title Start MamboTTS Local Engine
cd /d "%~dp0"

:: Check Python
py --version >nul 2>&1
if not errorlevel 1 (
    set PY_CMD=py
) else (
    python --version >nul 2>&1
    if not errorlevel 1 (
        set PY_CMD=python
    ) else (
        echo [ERROR] Python not found! Please install Python.
        pause
        exit /b
    )
)

:: Check Venv
if not exist .venv (
    echo [STATUS] Creating virtual environment .venv...
    %PY_CMD% -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment!
        pause
        exit /b
    )
)

echo [STATUS] Activating virtual environment...
call .venv\Scripts\activate.bat

echo [STATUS] Starting Local GPU Voice Engine via Python...
:: 显式走 venv 解释器，不依赖 activate 改 PATH
.venv\Scripts\python.exe run_engine.py

pause
