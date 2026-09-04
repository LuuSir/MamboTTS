import os
import sys
import socket
import subprocess

from engine_contract import (
    DEFAULT_REF_TEXT, SOVITS_MODEL, GPT_MODEL, REF_WAV, API_HOST, API_PORT,
)


def _project_dir():
    return os.path.dirname(os.path.abspath(__file__))


def engine_paths(base=None):
    """集中返回引擎与模型文件路径，install_engine 生成 bat 时也复用同一清单。"""
    base = base or _project_dir()
    gsv_dir = os.path.join(base, "GPT-SoVITS")
    models_dir = os.path.join(base, "models")
    return {
        "gsv_dir": gsv_dir,
        "models_dir": models_dir,
        "python_exe": os.path.join(gsv_dir, "runtime", "python.exe"),
        "api_py": os.path.join(gsv_dir, "api.py"),
        "sovits": os.path.join(models_dir, SOVITS_MODEL),
        "gpt": os.path.join(models_dir, GPT_MODEL),
        "ref_wav": os.path.join(models_dir, REF_WAV),
    }


def preflight_check(base=None):
    """启动前检查引擎与模型文件完整性，返回错误列表（空 = 就绪）。
    避免半安装状态下静默卡 60 秒后报「启动超时」，让人摸不着头脑。"""
    p = engine_paths(base)
    required = [
        ("GPT-SoVITS 整合包目录", p["gsv_dir"]),
        ("引擎入口 api.py", p["api_py"]),
        ("内置 Python runtime", p["python_exe"]),
        ("SoVITS 模型", p["sovits"]),
        ("GPT 模型", p["gpt"]),
        ("参考音频", p["ref_wav"]),
    ]
    return [f"{name}: {path}" for name, path in required if not os.path.exists(path)]


def port_in_use(host=API_HOST, port=API_PORT):
    """探测端口是否已被其他进程占用（api.py 绑定失败会抛英文 traceback，
    提前用中文提示更好排障）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        return s.connect_ex((host, port)) == 0


def main():
    current_dir = _project_dir()
    p = engine_paths(current_dir)

    missing = preflight_check(current_dir)
    if missing:
        print("[错误] 引擎文件不完整，无法启动：")
        for item in missing:
            print(f"  - {item}")
        print("请通过 MamboTTS.bat 完成安装，或确认整合包/模型文件放置正确。")
        sys.exit(1)

    # 端口占用预检：若已被其他引擎实例或无关程序占住，明确提示，
    # 而不是让 api.py 抛一段 Uvicorn 的 Errno 10048 traceback
    if port_in_use():
        print(f"[错误] 端口 {API_HOST}:{API_PORT} 已被占用。")
        print("  · 若已有 MamboTTS/GPT-SoVITS 在运行，无需重复启动；")
        print("  · 否则请关闭占用该端口的程序后重试。")
        sys.exit(3)

    print("====================================================")
    print("         MamboTTS 本地 GPU 语音推理引擎启动程序")
    print("====================================================")
    print(f"[状态] 正在加载 SoVITS 模型: {os.path.basename(p['sovits'])}")
    print(f"[状态] 正在加载 GPT 模型: {os.path.basename(p['gpt'])}")
    print(f"[提示] 推理服务即将启动在: http://{API_HOST}:{API_PORT}")
    print("====================================================\n")

    # 构建启动命令（旧版 api.py 支持 -s/-g/-dr/-dt/-dl 参数）
    cmd = [
        p["python_exe"],
        p["api_py"],
        "-a", API_HOST,
        "-p", str(API_PORT),
        "-s", p["sovits"],
        "-g", p["gpt"],
        "-dr", p["ref_wav"],
        "-dt", DEFAULT_REF_TEXT,
        "-dl", "zh",
    ]

    # 在 GPT-SoVITS 目录下运行 API，保证工作目录正确
    try:
        proc = subprocess.Popen(cmd, cwd=p["gsv_dir"])
        proc.wait()
    except KeyboardInterrupt:
        print("\n[状态] 推理服务已关闭。")
    except Exception as e:
        print(f"\n[错误] 启动推理引擎失败: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
