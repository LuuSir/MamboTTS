"""
MamboTTS 启动引导
- 用 tkinter 显示引导窗口（Python 标准库，无需预装）
- 负责: 创建 venv + 安装 PySide6/requests
- 装完后: 启动 launcher.py
"""
import os
import sys
import subprocess
import threading
import time
import tkinter as tk
from tkinter import ttk, scrolledtext
from datetime import datetime


# 整合包预期大小（GB），用于下载进度估算
# 实际 7z 文件约 8GB（含模型+引擎）
GPT_SOVITS_EXPECTED_SIZE_GB = 8.0

# bootstrap 阶段定义
BOOTSTRAP_STAGES = [
    ("环境检测", 0.05),
    ("创建虚拟环境", 0.30),
    ("安装依赖", 0.55),
    ("启动主程序", 0.10),
]


def _project_dir():
    return os.path.dirname(os.path.abspath(__file__))


def _venv_python():
    base = _project_dir()
    return os.path.join(base, ".venv", "Scripts", "python.exe")


def _venv_ready():
    return os.path.exists(_venv_python())


def _system_python():
    """返回可用的系统 Python 命令"""
    for cmd in ("py", "python"):
        try:
            subprocess.check_output([cmd, "--version"], stderr=subprocess.STDOUT, timeout=5)
            return cmd
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return None


# ============================================================
# 主引导窗口
# ============================================================

class BootstrapWindow:
    """tkinter 引导窗口，显示 venv + 依赖安装进度"""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("MamboTTS 启动引导")
        self.root.geometry("640x480")
        self.root.minsize(560, 400)

        # 阻止窗口关闭时直接死掉
        self._canceled = False
        self._worker_thread = None

        self._build_ui()

    def _build_ui(self):
        # 配色（浅色风格，符合用户偏好）
        bg = "#f5f5f5"
        card_bg = "#ffffff"
        accent = "#3b82f6"
        text_color = "#1f2937"
        muted = "#6b7280"

        self.root.configure(bg=bg)

        # Header
        header = tk.Frame(self.root, bg=accent, height=64)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(
            header, text="MamboTTS", bg=accent, fg="white",
            font=("Segoe UI", 18, "bold")
        ).pack(side="left", padx=16, pady=10)
        tk.Label(
            header, text="正在准备运行环境...", bg=accent, fg="#dbeafe",
            font=("Segoe UI", 10)
        ).pack(side="left", padx=8, pady=10, anchor="s")

        # 主体
        body = tk.Frame(self.root, bg=bg)
        body.pack(fill="both", expand=True, padx=20, pady=16)

        # 当前阶段
        stage_frame = tk.Frame(body, bg=bg)
        stage_frame.pack(fill="x", pady=(0, 8))
        self.stage_label = tk.Label(
            stage_frame, text="准备中...", bg=bg, fg=text_color,
            font=("Segoe UI", 12, "bold")
        )
        self.stage_label.pack(anchor="w")

        # 进度条
        self.progress = ttk.Progressbar(
            body, orient="horizontal", mode="determinate", length=580, maximum=100
        )
        self.progress.pack(fill="x", pady=(0, 8))

        # 进度数值
        self.progress_label = tk.Label(
            body, text="0%", bg=bg, fg=muted,
            font=("Segoe UI", 9)
        )
        self.progress_label.pack(anchor="e")

        # 日志面板
        tk.Label(
            body, text="安装日志:", bg=bg, fg=text_color,
            font=("Segoe UI", 10)
        ).pack(anchor="w", pady=(8, 4))

        log_frame = tk.Frame(body, bg=card_bg, highlightbackground="#e5e7eb", highlightthickness=1)
        log_frame.pack(fill="both", expand=True)
        self.log_view = scrolledtext.ScrolledText(
            log_frame, wrap="word", bg=card_bg, fg="#374151",
            font=("Consolas", 9), relief="flat", padx=8, pady=6,
            height=10
        )
        self.log_view.pack(fill="both", expand=True)
        self.log_view.configure(state="disabled")

        # 底部按钮
        btn_frame = tk.Frame(self.root, bg=bg)
        btn_frame.pack(fill="x", padx=20, pady=(0, 16))
        self.cancel_btn = tk.Button(
            btn_frame, text="取消", bg="#e5e7eb", fg=text_color,
            font=("Segoe UI", 10), relief="flat", padx=16, pady=4,
            command=self._on_cancel
        )
        self.cancel_btn.pack(side="right")

    # ============================================================
    # 线程安全的 UI 更新
    # ============================================================

    def _run_in_main_thread(self, func, *args):
        """把 UI 更新调度到主线程执行"""
        self.root.after(0, lambda: func(*args))

    def set_stage(self, stage_text):
        self._run_in_main_thread(self.stage_label.configure, {"text": stage_text})

    def set_progress(self, percent):
        """设置整体进度（0-100）"""
        clamped = max(0, min(100, percent))
        self._run_in_main_thread(self.progress.configure, {"value": clamped})
        self._run_in_main_thread(self.progress_label.configure, {"text": f"{clamped:.0f}%"})

    def append_log(self, message):
        """向日志面板追加一行（带时间戳）"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}\n"
        def _do():
            self.log_view.configure(state="normal")
            self.log_view.insert("end", line)
            self.log_view.see("end")
            self.log_view.configure(state="disabled")
        self._run_in_main_thread(_do)

    def _on_cancel(self):
        if self._worker_thread and self._worker_thread.is_alive():
            self._canceled = True
            self.append_log("正在取消...（后台进程可能需要几秒钟收尾）")
            self.cancel_btn.configure(state="disabled")
        else:
            self.root.destroy()

    # ============================================================
    # 主流程
    # ============================================================

    def run(self):
        """启动后台工作线程，主线程进入 tk 消息循环"""
        self._worker_thread = threading.Thread(target=self._work, daemon=True)
        self._worker_thread.start()
        self.root.mainloop()

        # mainloop 退出后，根据状态决定
        if self._canceled:
            sys.exit(0)

    def _work(self):
        """后台工作线程：负责 venv + 依赖安装 + 启动 launcher"""
        try:
            # ===== 阶段 0: 环境检测 =====
            self.set_stage("阶段 1/4: 环境检测")
            self.append_log("开始环境检测...")

            sys_python = _system_python()
            if not sys_python:
                self.append_log("[错误] 未检测到 Python，请先安装 Python 3.10+")
                self.set_stage("错误: 未安装 Python")
                self._show_error_and_exit(
                    "未检测到 Python",
                    "请安装 Python 3.10 或更高版本:\nhttps://www.python.org/downloads/\n\n"
                    "安装时请勾选 'Add Python to PATH'。"
                )
                return

            self.append_log(f"检测到系统 Python: {sys_python}")
            self.set_progress(5)

            # 检查 venv 是否已就绪
            if _venv_ready():
                self.append_log("虚拟环境已存在，跳过创建步骤")
                self.set_progress(35)
            else:
                # ===== 阶段 1: 创建 venv =====
                self.set_stage("阶段 2/4: 创建虚拟环境")
                self.append_log("正在创建虚拟环境 .venv ...")
                base = _project_dir()
                venv_path = os.path.join(base, ".venv")
                try:
                    subprocess.check_call(
                        [sys_python, "-m", "venv", venv_path],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.STDOUT,
                    )
                except subprocess.CalledProcessError as e:
                    self.append_log(f"[错误] 创建虚拟环境失败: {e}")
                    self._show_error_and_exit(
                        "创建虚拟环境失败",
                        f"可能原因:\n1. 权限不足（请用管理员身份运行）\n2. Python 安装不完整\n\n"
                        f"详细错误: {e}"
                    )
                    return
                self.append_log("虚拟环境创建完成")
                self.set_progress(35)

            # ===== 阶段 2: 安装依赖 =====
            self.set_stage("阶段 3/4: 安装依赖")
            venv_python = _venv_python()
            req_path = os.path.join(_project_dir(), "requirements.txt")

            if not os.path.exists(req_path):
                self.append_log("[警告] 未找到 requirements.txt，将只安装基础依赖")
                deps = ["PySide6", "requests"]
            else:
                deps = None  # 用 -r requirements.txt

            # 先尝试国内镜像
            self.append_log("正在通过国内镜像安装依赖（PySide6, requests）...")
            self.append_log("这可能需要 10-30 秒，请耐心等待...")
            install_ok = self._pip_install(venv_python, req_path, use_mirror=True)
            if not install_ok:
                self.append_log("[警告] 镜像安装失败，尝试默认源...")
                install_ok = self._pip_install(venv_python, req_path, use_mirror=False)

            if not install_ok:
                self._show_error_and_exit(
                    "依赖安装失败",
                    "无法安装 PySide6/requests。\n请检查网络连接后重试。"
                )
                return

            self.append_log("依赖安装完成")
            self.set_progress(90)

            # ===== 阶段 3: 启动主程序 =====
            self.set_stage("阶段 4/4: 启动主程序")
            self.append_log("正在启动 MamboTTS 主程序...")

            launcher_path = os.path.join(_project_dir(), "launcher.py")
            if not os.path.exists(launcher_path):
                self._show_error_and_exit(
                    "文件缺失",
                    f"未找到 launcher.py:\n{launcher_path}"
                )
                return

            self.set_progress(95)

            # 启动 launcher.py（PySide6 主程序），用 venv 的 python
            # 不阻塞等待：launcher 自己接管 GUI
            creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            proc = subprocess.Popen(
                [venv_python, launcher_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags,
            )
            self.append_log(f"主程序已启动 (PID={proc.pid})")

            self.set_progress(100)
            self.set_stage("启动完成")

            # 等待主程序窗口出现（给一点缓冲时间）
            time.sleep(1.5)
            self.append_log("引导完成，即将关闭此窗口...")

            # 退出引导窗口
            self._run_in_main_thread(self.root.destroy)

        except Exception as e:
            self.append_log(f"[错误] 引导过程异常: {type(e).__name__}: {e}")
            self._show_error_and_exit(
                "启动异常",
                f"引导过程发生异常:\n{type(e).__name__}: {e}"
            )

    def _pip_install(self, venv_python, req_path, use_mirror=True):
        """用 venv 的 pip 安装依赖，实时输出日志"""
        venv_pip = os.path.join(_project_dir(), ".venv", "Scripts", "pip.exe")
        cmd = [venv_pip, "install", "-r", req_path]
        if use_mirror:
            cmd += ["-i", "https://mirrors.aliyun.com/pypi/simple/"]

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    # 过滤掉过长的进度条行，避免日志爆炸
                    if len(line) < 200:
                        self.append_log(line)
            proc.wait()
            return proc.returncode == 0
        except Exception as e:
            self.append_log(f"[错误] pip 执行异常: {e}")
            return False

    def _show_error_and_exit(self, title, message):
        """显示错误对话框并退出"""
        from tkinter import messagebox
        def _do():
            messagebox.showerror(title, message)
            self.root.destroy()
        self._run_in_main_thread(_do)


# ============================================================
# 入口
# ============================================================

def _quick_start_launcher():
    """venv 已就绪时的快速启动路径：跳过 tk 窗口，直接启动 launcher.py"""
    venv_python = _venv_python()
    launcher_path = os.path.join(_project_dir(), "launcher.py")
    if not os.path.exists(launcher_path):
        # launcher.py 不存在，回退到 tk 引导
        return False

    creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    subprocess.Popen(
        [venv_python, launcher_path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation_flags,
    )
    return True


def main():
    # 如果 venv 已就绪，跳过 tk 窗口直接启动 launcher.py（避免空白 tk 窗口）
    if _venv_ready():
        if _quick_start_launcher():
            return
        # launcher.py 不存在才回退到 tk 引导

    # 设置 ttk 主题，让进度条更好看
    try:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Horizontal.TProgressbar", troughcolor="#e5e7eb", background="#3b82f6")
    except Exception:
        pass

    win = BootstrapWindow()
    win.run()


if __name__ == "__main__":
    main()
