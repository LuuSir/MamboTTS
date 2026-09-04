@echo off
title MamboTTS Engine Installer
:: 强制切换到脚本所在目录，避免管理员启动时工作目录被切到 System32
cd /d "%~dp0"
echo ===================================================
echo             MamboTTS Local Engine Installer
echo ===================================================
echo.

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

echo [STATUS] Installing required dependencies (PySide6, requests)...
echo [STATUS] This may take 10-30 seconds. Please wait...
:: 显式走 venv python -m pip，不依赖 activate 改 PATH
.venv\Scripts\python.exe -m pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
if errorlevel 1 (
    echo [WARNING] Dependency installation failed! Retrying without mirror...
    .venv\Scripts\python.exe -m pip install -r requirements.txt
)

echo [STATUS] Launching installer script...
.venv\Scripts\python.exe install_engine.py

pause
