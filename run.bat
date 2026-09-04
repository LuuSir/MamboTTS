@echo off
title MamboTTS Runner
:: 强制切换到脚本所在目录，避免管理员启动时工作目录被切到 System32
cd /d "%~dp0"
echo ===================================================
echo               MamboTTS - Mambo Voice Tool
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
    echo [STATUS] Creating virtual environment venv...
    %PY_CMD% -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment!
        pause
        exit /b
    )
)

:: 直接固定使用 venv 解释器执行安装与运行（旧版依赖 activate 改 PATH，
:: 在部分环境下 pip/python 会解析到全局解释器，把包装到系统里且导致版本漂移）
.venv\Scripts\python.exe -c "import PySide6, requests" >nul 2>&1
if errorlevel 1 (
    echo [STATUS] Installing dependencies PySide6 and requests...
    echo [STATUS] This may take 10-30 seconds. Please wait...
    .venv\Scripts\python.exe -m pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
    if errorlevel 1 (
        echo [WARNING] Retrying install without mirror...
        .venv\Scripts\python.exe -m pip install -r requirements.txt
    )
) else (
    echo [STATUS] Dependencies already installed, skipping installation.
)

echo [STATUS] Starting MamboTTS...
.venv\Scripts\python.exe app.py

if errorlevel 1 (
    echo.
    echo [INFO] Program exited.
    pause
)
