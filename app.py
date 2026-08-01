import os
import sys
import json
import shutil
import subprocess
import time
import threading
import webbrowser
import requests
from datetime import datetime
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QTextEdit, QPushButton, QLabel,
                             QLineEdit, QFileDialog, QFrame, QGraphicsDropShadowEffect,
                             QComboBox, QProgressBar, QMessageBox, QSlider,
                             QScrollArea)
from PySide6.QtCore import Qt, QUrl, QThread, Signal, QTimer
from PySide6.QtGui import QFont, QColor, QIcon
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput

# 导入推理客户端
from inference import TTSClient

# 当前版本号，用于 GitHub 新版本检查
CURRENT_VERSION = "v1.2.0"
GITHUB_REPO = "Tsukimisaka/MamboTTS"


class GenerateWorker(QThread):
    """后台合成线程，避免阻塞 GUI 主线程导致界面卡死"""
    finished_signal = Signal(bool, str)  # (success, message)

    def __init__(self, tts_client, text, save_path, speed):
        super().__init__()
        self.tts_client = tts_client
        self.text = text
        self.save_path = save_path
        self.speed = speed

    def run(self):
        try:
            success, message = self.tts_client.generate_speech(
                self.text, self.save_path, speed=self.speed
            )
        except Exception as e:
            success, message = False, f"后台合成异常：{type(e).__name__}: {e}"
        self.finished_signal.emit(success, message)


# ============================================================
# 合成历史记录单条组件
# ============================================================

class HistoryItemWidget(QFrame):
    """单条合成历史记录：显示完整文案 + 播放/另存/删除按钮"""

    def __init__(self, record_id, path, text, time_str, duration_sec, main_window):
        super().__init__()
        self.record_id = record_id
        self.path = path
        self.text = text
        self.main_window = main_window
        self._expanded = False
        self._build_ui(time_str, duration_sec)

    def _build_ui(self, time_str, duration_sec):
        self.setStyleSheet("""
            QFrame {
                background-color: #181825;
                border: 1px solid #313244;
                border-radius: 8px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        # 顶行：时间 + 时长 + 按钮组
        top_row = QHBoxLayout()
        top_row.setSpacing(6)

        dur_str = f"{int(duration_sec)//60:01d}:{int(duration_sec)%60:02d}"
        info = QLabel(f"🕐 {time_str}   ⏱ {dur_str}")
        info.setStyleSheet("color: #7f849c; font-size: 11px; background: transparent; border: none;")
        top_row.addWidget(info)
        top_row.addStretch()

        btn_play = QPushButton("▶ 播放")
        btn_play.setFixedHeight(26)
        btn_play.setCursor(Qt.PointingHandCursor)
        btn_play.setStyleSheet(
            "QPushButton { background-color: #a6e3a1; color: #11111b; border-radius: 4px; padding: 2px 10px; font-size: 11px; font-weight: bold; }"
            "QPushButton:hover { background-color: #b5e8ad; }"
        )
        btn_play.clicked.connect(lambda: self.main_window._play_path(self.path))
        top_row.addWidget(btn_play)

        btn_save = QPushButton("💾 另存")
        btn_save.setFixedHeight(26)
        btn_save.setCursor(Qt.PointingHandCursor)
        btn_save.setStyleSheet(
            "QPushButton { background-color: #45475a; color: #cdd6f4; border-radius: 4px; padding: 2px 10px; font-size: 11px; }"
            "QPushButton:hover { background-color: #585b70; }"
        )
        btn_save.clicked.connect(lambda: self.main_window._history_save_as_path(self.path))
        top_row.addWidget(btn_save)

        btn_del = QPushButton("🗑 删除")
        btn_del.setFixedHeight(26)
        btn_del.setCursor(Qt.PointingHandCursor)
        btn_del.setStyleSheet(
            "QPushButton { background-color: #45475a; color: #f38ba8; border-radius: 4px; padding: 2px 10px; font-size: 11px; }"
            "QPushButton:hover { background-color: #585b70; }"
        )
        btn_del.clicked.connect(lambda: self.main_window._history_delete_path(self.record_id, self))
        top_row.addWidget(btn_del)

        layout.addLayout(top_row)

        # 文案显示：完整文案，过长时折叠+展开按钮
        self.text_label = QLabel()
        self.text_label.setWordWrap(True)
        self.text_label.setTextFormat(Qt.PlainText)
        self.text_label.setStyleSheet("color: #cdd6f4; font-size: 12px; background: transparent; border: none;")

        if len(self.text) > 80:
            self._is_long = True
            self.text_label.setText(self.text[:80] + "...")
            self.btn_expand = QPushButton("展开全文 ▼")
            self.btn_expand.setFixedHeight(20)
            self.btn_expand.setCursor(Qt.PointingHandCursor)
            self.btn_expand.setStyleSheet(
                "QPushButton { background: transparent; color: #89b4fa; border: none; padding: 0px; font-size: 11px; text-align: left; }"
                "QPushButton:hover { color: #b4befe; }"
            )
            self.btn_expand.clicked.connect(self._toggle_expand)
            layout.addWidget(self.text_label)
            layout.addWidget(self.btn_expand)
        else:
            self._is_long = False
            self.text_label.setText(self.text)
            layout.addWidget(self.text_label)

    def _toggle_expand(self):
        if self._expanded:
            self.text_label.setText(self.text[:80] + "...")
            self.btn_expand.setText("展开全文 ▼")
        else:
            self.text_label.setText(self.text)
            self.btn_expand.setText("收起 ▲")
        self._expanded = not self._expanded


# 配置文件路径：与 app.py 同目录，便于携带
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

class MamboTTSApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.tts_client = TTSClient()
        # 默认输出目录（桌面），会被配置文件覆盖
        default_desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        self.output_dir = default_desktop
        # output_file 仅作为运行期「下次合成目标路径」使用，不再持久化完整路径
        self.output_file = os.path.join(default_desktop, "mambo_output.wav")

        # 加载持久化配置（API URL、语速、输出目录、文件命名）
        config = self.load_config()
        self.saved_api_url = config.get("api_url", "http://127.0.0.1:9880")
        self.saved_speed = config.get("speed", 1.0)

        # 优先读取新字段 output_dir；若缺失则向后兼容旧字段 output_file（取其目录）
        saved_dir = config.get("output_dir", "")
        if saved_dir and os.path.isdir(saved_dir):
            self.output_dir = saved_dir
        elif config.get("output_file", ""):
            legacy_dir = os.path.dirname(config.get("output_file", ""))
            if legacy_dir and os.path.isdir(legacy_dir):
                self.output_dir = legacy_dir
        # 同步 output_file 到当前目录
        self.output_file = os.path.join(self.output_dir, "mambo_output.wav")

        # 自定义文件命名（留空则用文案前20字），跨次启动保留
        self.saved_name = config.get("name", "")

        # 音频播放器初始化
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        # 播放器与历史记录状态
        self._current_play_path = ""
        self._last_synth_text = ""

        # 引擎子进程引用：随客户端启动/关闭
        self.engine_proc = None
        self._engine_start_time = time.time()

        self.init_ui()
        # 注入日志回调，把 inference 的日志实时推送到 GUI 日志面板
        self.tts_client.set_log_handler(lambda level, msg: self.append_log(level, msg))
        self.append_log("INFO", "MamboTTS 已启动。如遇问题，请查看此处日志。")

        # 启动引擎子进程（如果引擎没在线）
        self._start_engine_subprocess()

        # 启动 API 在线状态轮询（每 2 秒检查一次，直到在线或超时）
        self._api_check_timer = QTimer(self)
        self._api_check_timer.timeout.connect(self._poll_engine_status)
        self._api_check_timer.start(2000)

        # API URL 输入防抖定时器：用户停止输入 600ms 后才检查在线状态并写配置，
        # 避免每个键击都触发 HTTP 请求 + 写盘导致输入卡顿
        self._api_url_debounce = QTimer(self)
        self._api_url_debounce.setSingleShot(True)
        self._api_url_debounce.timeout.connect(self._on_api_url_debounced)

        self.check_api_status()

        # 启动 3 秒后后台检查 GitHub 是否有新版本（非阻塞，失败静默）
        QTimer.singleShot(3000, self._check_for_updates_async)

    def _check_for_updates_async(self):
        """在后台线程中检查 GitHub 是否有新版本，避免阻塞 UI"""
        def _check():
            try:
                resp = requests.get(
                    f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
                    timeout=5,
                    headers={"Accept": "application/vnd.github.v3+json"}
                )
                if resp.status_code == 200:
                    data = resp.json()
                    latest_tag = data.get("tag_name", "")
                    release_url = data.get("html_url", "")
                    if latest_tag and self._is_newer_version(latest_tag, CURRENT_VERSION):
                        # 回到主线程显示更新提示
                        QTimer.singleShot(0, lambda: self._show_update_dialog(latest_tag, release_url))
            except Exception:
                pass  # 网络异常静默忽略，不打扰用户

        threading.Thread(target=_check, daemon=True).start()

    def _is_newer_version(self, latest, current):
        """比较版本号，如 v1.2.0 > v1.1.0"""
        def parse(v):
            v = v.lstrip('v').strip()
            parts = v.split('.')
            return [int(p) for p in parts if p.isdigit()]
        try:
            l = parse(latest)
            c = parse(current)
            while len(l) < len(c):
                l.append(0)
            while len(c) < len(l):
                c.append(0)
            return l > c
        except Exception:
            return False

    def _show_update_dialog(self, latest_tag, release_url):
        """显示新版本更新提示对话框"""
        reply = QMessageBox.question(
            self,
            "发现新版本",
            f"MamboTTS 有新版本可用！\n\n"
            f"当前版本: {CURRENT_VERSION}\n"
            f"最新版本: {latest_tag}\n\n"
            f"是否前往 GitHub 下载新版本？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
        )
        if reply == QMessageBox.Yes and release_url:
            webbrowser.open(release_url)

    def _start_engine_subprocess(self):
        """启动 GPT-SoVITS 引擎子进程（run_engine.py）"""
        # 先检查引擎是否已在线（避免重复启动）
        if self.tts_client.is_api_running():
            self.append_log("INFO", "检测到引擎已在线，跳过子进程启动。")
            return

        base_dir = os.path.dirname(os.path.abspath(__file__))
        run_engine_path = os.path.join(base_dir, "run_engine.py")

        if not os.path.exists(run_engine_path):
            self.append_log("WARNING", "未找到 run_engine.py，跳过引擎子进程启动。")
            return

        # 检查 GPT-SoVITS 是否已安装
        gsv_dir = os.path.join(base_dir, "GPT-SoVITS")
        if not os.path.exists(gsv_dir):
            self.append_log("WARNING", "GPT-SoVITS 未安装，请先运行安装程序。")
            return

        try:
            # 用当前 Python 启动 run_engine.py，不在新窗口里跑（避免黑窗）
            # creationflags=CREATE_NO_WINDOW 让 Windows 不弹黑窗
            # 新进程组：便于关闭时按进程树 kill 孙子进程（api.py）
            creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            if sys.platform == "win32":
                creation_flags |= subprocess.CREATE_NEW_PROCESS_GROUP
            self.engine_proc = subprocess.Popen(
                [sys.executable, run_engine_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=creation_flags,
                bufsize=1,
                universal_newlines=True,
                encoding="utf-8",
                errors="replace",
            )
            self.append_log("INFO", f"已启动引擎子进程 (PID={self.engine_proc.pid})，等待加载完成...")
            # 后台线程读取引擎 stdout（含 stderr 合并），实时转发到 GUI 日志面板
            self._engine_log_thread = threading.Thread(
                target=self._pump_engine_log, daemon=True
            )
            self._engine_log_thread.start()
        except Exception as e:
            self.append_log("ERROR", f"启动引擎子进程失败: {e}")

    def _pump_engine_log(self):
        """后台线程：读取引擎子进程 stdout（含合并的 stderr），转发到 GUI 日志面板。

        GPT-SoVITS 的 uvicorn/模型加载日志会输出到这里。逐行读取避免阻塞，
        通过 QTimer.singleShot(0) 把日志 marshal 回 GUI 主线程追加（线程安全）。
        """
        if not self.engine_proc or not self.engine_proc.stdout:
            return
        try:
            for line in iter(self.engine_proc.stdout.readline, ''):
                line = line.rstrip()
                if not line:
                    continue
                # marshal 到主线程，避免直接操作 GUI 控件
                QTimer.singleShot(0, lambda msg=line: self._append_engine_log_line(msg))
        except Exception:
            # 读取异常（如进程已退出）静默结束
            pass

    def _append_engine_log_line(self, msg):
        """把引擎子进程的一行日志追加到 GUI 日志面板（主线程调用）"""
        # 简单识别常见级别关键词，便于着色；无法识别的按 INFO 处理
        level = "INFO"
        upper = msg.upper()
        if "ERROR" in upper or "TRACEBACK" in upper or "EXCEPTION" in upper:
            level = "ERROR"
        elif "WARN" in upper:
            level = "WARNING"
        self.append_log(level, f"[引擎] {msg}")

    def _poll_engine_status(self):
        """轮询引擎在线状态，在线后停止轮询"""
        if self.tts_client.is_api_running():
            elapsed = time.time() - self._engine_start_time
            self.append_log("INFO", f"引擎已在线，加载耗时 {elapsed:.1f} 秒。")
            self.status_label.setText("🟢 本地 GPU 引擎在线")
            self.status_label.setStyleSheet("color: #a6e3a1; font-weight: bold;")
            self._api_check_timer.stop()
            return

        # 超时判断：60 秒还没起来就停止轮询
        elapsed = time.time() - self._engine_start_time
        if elapsed > 60:
            self.append_log("ERROR", "引擎启动超时（60秒），请检查 GPT-SoVITS 是否安装完整。")
            self.status_label.setText("❌ 引擎启动超时")
            self.status_label.setStyleSheet("color: #f38ba8; font-weight: bold;")
            self._api_check_timer.stop()
            return

        # 仍在等待中
        self.status_label.setText(f"⏳ 引擎启动中... ({elapsed:.0f}s)")
        self.status_label.setStyleSheet("color: #f9e2af; font-weight: bold;")

    def load_config(self):
        """从 config.json 读取配置；失败时返回空 dict，使用默认值"""
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except Exception as e:
            # 配置损坏时不阻断启动，仅打印
            print(f"[Config] 读取配置失败: {e}")
            return {}

    def save_config(self):
        """把当前 GUI 状态持久化到 config.json。
        注意：只存输出目录（output_dir），不存完整文件路径，
        避免合成时自动生成的文件名污染用户选择的目录。
        """
        try:
            # 从路径输入框提取目录部分
            current_path = self.path_input.text().strip()
            dir_to_save = os.path.dirname(current_path) or self.output_dir
            data = {
                "api_url": self.api_input.text().strip(),
                "speed": self.speed_combo.currentData(),
                "output_dir": dir_to_save,
                "name": self.name_input.text().strip() if hasattr(self, "name_input") else "",
            }
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.append_log("WARNING", f"保存配置失败: {e}")

    def init_ui(self):
        self.setWindowTitle("MamboTTS - 曼波配音工具")
        self.resize(1280, 800)
        self.setMinimumSize(960, 600)
        
        # 全局深色猫咪肤色风格 (Catppuccin Mocha Inspired)
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1e1e2e;
            }
            QWidget {
                color: #cdd6f4;
                font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
            }
            QLabel {
                font-size: 13px;
            }
            QTextEdit {
                background-color: #11111b;
                border: 1px solid #313244;
                border-radius: 8px;
                padding: 10px;
                color: #a6adc8;
                font-size: 14px;
            }
            QTextEdit:focus {
                border: 1px solid #89b4fa;
            }
            QLineEdit {
                background-color: #11111b;
                border: 1px solid #313244;
                border-radius: 6px;
                padding: 6px 10px;
                color: #cdd6f4;
            }
            QLineEdit:focus {
                border: 1px solid #89b4fa;
            }
            QPushButton {
                background-color: #89b4fa;
                color: #11111b;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #b4befe;
            }
            QPushButton:pressed {
                background-color: #74c7ec;
            }
            QPushButton:disabled {
                background-color: #45475a;
                color: #7f849c;
            }
            QFrame#HeaderCard {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #89b4fa, stop:1 #b4befe);
                border-radius: 10px;
            }
            QFrame#MainCard {
                background-color: #181825;
                border-radius: 12px;
                border: 1px solid #313244;
            }
            QComboBox {
                background-color: #11111b;
                border: 1px solid #313244;
                border-radius: 6px;
                padding: 6px 12px;
                color: #cdd6f4;
                min-width: 150px;
            }
            QComboBox:focus {
                border: 1px solid #89b4fa;
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 25px;
                border-left-width: 1px;
                border-left-color: #313244;
                border-left-style: solid;
                border-top-right-radius: 6px;
                border-bottom-right-radius: 6px;
            }
            QComboBox QAbstractItemView {
                background-color: #11111b;
                color: #cdd6f4;
                selection-background-color: #313244;
                selection-color: #89b4fa;
                border: 1px solid #313244;
            }
        """)

        # 主布局：顶部 Header + 下方左右分栏（左控制区 + 右历史记录）
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        root_layout = QVBoxLayout(central_widget)
        root_layout.setContentsMargins(20, 20, 20, 20)
        root_layout.setSpacing(15)

        # 1. 顶部 Header 栏（横跨全宽）
        header_card = QFrame()
        header_card.setObjectName("HeaderCard")
        header_card.setFixedHeight(70)
        header_card.setStyleSheet("background-color: #89b4fa; border-radius: 10px;")

        header_layout = QHBoxLayout(header_card)
        header_layout.setContentsMargins(15, 10, 15, 10)
        header_left = QVBoxLayout()
        header_title = QLabel("MamboTTS")
        header_title.setStyleSheet("color: #11111b; font-size: 20px; font-weight: bold;")
        header_subtitle = QLabel('本地专属"曼波"文字转语音配音助手')
        header_subtitle.setStyleSheet("color: #1e1e2e; font-size: 12px;")
        header_left.addWidget(header_title)
        header_left.addWidget(header_subtitle)
        header_layout.addLayout(header_left)
        header_layout.addStretch()
        root_layout.addWidget(header_card)

        # 2. 内容区域：左右分栏
        content_layout = QHBoxLayout()
        content_layout.setSpacing(15)

        # ===== 左列：主控制区 =====
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(12)

        # 2.1 主卡片（API + 文案 + 语速 + 路径 + 进度）
        main_card = QFrame()
        main_card.setObjectName("MainCard")
        main_card_layout = QVBoxLayout(main_card)
        main_card_layout.setContentsMargins(15, 15, 15, 15)
        main_card_layout.setSpacing(10)

        # API 设置与状态
        api_layout = QHBoxLayout()
        api_label = QLabel("引擎接口:")
        self.api_input = QLineEdit(self.saved_api_url)
        self.api_input.textChanged.connect(self.on_api_url_changed)
        self.status_label = QLabel("正在检测服务...")
        self.status_label.setStyleSheet("color: #f9e2af; font-weight: bold;")
        api_layout.addWidget(api_label)
        api_layout.addWidget(self.api_input)
        api_layout.addWidget(self.status_label)
        main_card_layout.addLayout(api_layout)

        # 文案输入
        text_label = QLabel("配音文案内容:")
        main_card_layout.addWidget(text_label)
        self.text_input = QTextEdit()
        self.text_input.setPlaceholderText('在此输入想要配音的文字。例如："大家好，我是曼波，今天给大家讲一个非常炸裂的故事……"')
        self.text_input.setText("大家好，我是曼波。今天给大家分享一个非常有意思的技术方案。")
        self.text_input.setAcceptRichText(False)
        self.text_input.setMinimumHeight(100)
        main_card_layout.addWidget(self.text_input)

        # 语速控制
        speed_layout = QHBoxLayout()
        speed_label = QLabel("语速调节:")
        self.speed_combo = QComboBox()
        speeds = [
            ("0.5 倍速", 0.5), ("1.0 倍速 (默认)", 1.0),
            ("1.25 倍速", 1.25), ("1.5 倍速", 1.5),
            ("1.75 倍速", 1.75), ("2.0 倍速", 2.0),
            ("2.25 倍速", 2.25), ("2.5 倍速", 2.5),
            ("2.75 倍速", 2.75), ("3.0 倍速", 3.0)
        ]
        for text, val in speeds:
            self.speed_combo.addItem(text, val)
        speed_idx = 1
        for i in range(self.speed_combo.count()):
            if self.speed_combo.itemData(i) == self.saved_speed:
                speed_idx = i
                break
        self.speed_combo.setCurrentIndex(speed_idx)
        self.speed_combo.currentIndexChanged.connect(self.on_speed_changed)
        speed_layout.addWidget(speed_label)
        speed_layout.addWidget(self.speed_combo)
        speed_layout.addStretch()
        main_card_layout.addLayout(speed_layout)

        # 保存路径
        path_layout = QHBoxLayout()
        path_label = QLabel("保存路径:")
        self.path_input = QLineEdit(self.output_file)
        btn_browse = QPushButton("浏览...")
        btn_browse.setStyleSheet("background-color: #45475a; color: #cdd6f4;")
        btn_browse.clicked.connect(self.browse_path)
        path_layout.addWidget(path_label)
        path_layout.addWidget(self.path_input)
        path_layout.addWidget(btn_browse)
        main_card_layout.addLayout(path_layout)

        # 配音文件命名：用户可自定义文件名，留空则默认用文案前20字
        name_layout = QHBoxLayout()
        name_label = QLabel("配音文件命名:")
        self.name_input = QLineEdit(self.saved_name)
        self.name_input.setPlaceholderText("留空则默认使用配音文案内容的前20个字（无需填写 .wav 后缀）")
        name_layout.addWidget(name_label)
        name_layout.addWidget(self.name_input, 1)
        main_card_layout.addLayout(name_layout)

        # 合成进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(22)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p%")
        self.progress_bar.setStyleSheet(
            "QProgressBar { background-color: #11111b; border: 1px solid #313244; border-radius: 6px; text-align: center; color: #cdd6f4; font-size: 12px; font-weight: bold; }"
            "QProgressBar::chunk { background-color: #89b4fa; border-radius: 5px; }"
        )
        main_card_layout.addWidget(self.progress_bar)

        self._synth_timer = QTimer(self)
        self._synth_timer.timeout.connect(self._update_synth_progress)
        self._synth_start_time = 0
        self._synth_estimated_sec = 5.0

        left_layout.addWidget(main_card)

        # 播放器控制栏
        player_layout = QHBoxLayout()
        self.btn_play_pause = QPushButton("▶ 播放")
        self.btn_play_pause.setFixedHeight(36)
        self.btn_play_pause.setFixedWidth(90)
        self.btn_play_pause.setStyleSheet("background-color: #a6e3a1; color: #11111b;")
        self.btn_play_pause.setEnabled(False)
        self.btn_play_pause.clicked.connect(self.toggle_playback)
        player_layout.addWidget(self.btn_play_pause)

        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setFixedWidth(120)
        self.time_label.setStyleSheet("color: #7f849c; font-size: 12px;")
        self.time_label.setAlignment(Qt.AlignCenter)
        player_layout.addWidget(self.time_label)

        self.seek_slider = QSlider(Qt.Horizontal)
        self.seek_slider.setRange(0, 1000)
        self.seek_slider.setValue(0)
        self.seek_slider.setEnabled(False)
        self.seek_slider.sliderMoved.connect(self.on_seek_slider_moved)
        self.seek_slider.sliderReleased.connect(self.on_seek_slider_released)
        self.seek_slider.setStyleSheet(
            "QSlider::groove:horizontal { background: #313244; height: 6px; border-radius: 3px; }"
            "QSlider::handle:horizontal { background: #89b4fa; width: 14px; margin: -5px 0; border-radius: 7px; }"
            "QSlider::sub-page:horizontal { background: #89b4fa; border-radius: 3px; }"
        )
        player_layout.addWidget(self.seek_slider, 1)
        left_layout.addLayout(player_layout)

        # 操作按钮栏
        actions_layout = QHBoxLayout()
        self.btn_generate = QPushButton("⚡ 合成配音")
        self.btn_generate.setFixedHeight(40)
        self.btn_generate.clicked.connect(self.generate_voice)
        btn_open_folder = QPushButton("📁 打开输出目录")
        btn_open_folder.setStyleSheet("background-color: #f5c2e7; color: #11111b;")
        btn_open_folder.setFixedHeight(40)
        btn_open_folder.clicked.connect(self.open_output_folder)
        actions_layout.addWidget(self.btn_generate, 2)
        actions_layout.addWidget(btn_open_folder, 1)
        left_layout.addLayout(actions_layout)

        # 运行日志
        log_label = QLabel("运行日志:")
        left_layout.addWidget(log_label)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setPlaceholderText("运行日志将显示在此处，便于排查问题。")
        self.log_view.setMinimumHeight(60)
        self.log_view.setStyleSheet("QTextEdit { font-size: 12px; background-color: #11111b; }")
        left_layout.addWidget(self.log_view)

        content_layout.addWidget(left_widget, 3)

        # ===== 右列：合成历史记录 =====
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        history_label = QLabel("📋 合成历史记录")
        history_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #cdd6f4;")
        right_layout.addWidget(history_label)

        self.history_scroll = QScrollArea()
        self.history_scroll.setWidgetResizable(True)
        self.history_scroll.setStyleSheet(
            "QScrollArea { border: 1px solid #313244; border-radius: 8px; background-color: #11111b; }"
            "QScrollBar:vertical { background: #181825; width: 8px; border-radius: 4px; }"
            "QScrollBar::handle:vertical { background: #313244; border-radius: 4px; min-height: 30px; }"
            "QScrollBar::handle:vertical:hover { background: #45475a; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )
        self.history_container = QWidget()
        self.history_container.setStyleSheet("background-color: transparent;")
        self.history_container_layout = QVBoxLayout(self.history_container)
        self.history_container_layout.setAlignment(Qt.AlignTop)
        self.history_container_layout.setSpacing(8)
        self.history_container_layout.setContentsMargins(6, 6, 6, 6)
        self.history_scroll.setWidget(self.history_container)
        right_layout.addWidget(self.history_scroll, 1)
        content_layout.addWidget(right_widget, 2)

        root_layout.addLayout(content_layout, 1)

        # 历史记录数据：[{record_id, path, text, time, duration}, ...]
        self._history_data = []
        self._history_widgets = {}
        self._history_seq = 0  # 自增 record_id，避免路径复用导致记录覆盖
        self._seeking = False

        # 连接播放器信号
        self.player.positionChanged.connect(self.on_position_changed)
        self.player.durationChanged.connect(self.on_duration_changed)
        self.player.playbackStateChanged.connect(self.on_playback_state_changed)

    def check_api_status(self):
        """异步/定时检查本地服务状态"""
        self.tts_client.api_url = self.api_input.text().strip()
        if self.tts_client.is_api_running():
            self.status_label.setText("🟢 本地 GPU 引擎在线")
            self.status_label.setStyleSheet("color: #a6e3a1; font-weight: bold;")
            self.append_log("INFO", f"API 服务在线: {self.tts_client.api_url}")
        else:
            self.status_label.setText("🟡 离线模式 (Mock 生成)")
            self.status_label.setStyleSheet("color: #f9e2af; font-weight: bold;")
            self.append_log("WARNING", f"API 服务离线: {self.tts_client.api_url}（将进入 Mock 模式）")

    def append_log(self, level, message):
        """把日志追加到 GUI 日志面板，按级别着色，并自动滚动到底部"""
        color_map = {
            "ERROR": "#f38ba8",
            "WARNING": "#f9e2af",
            "INFO": "#cdd6f4",
        }
        color = color_map.get(level, "#cdd6f4")
        timestamp = datetime.now().strftime("%H:%M:%S")
        # 用 HTML 转义避免日志内容里的 < > & 破坏渲染
        safe_msg = (message.replace("&", "&amp;")
                           .replace("<", "&lt;")
                           .replace(">", "&gt;"))
        self.log_view.append(
            f'<span style="color:{color};">[{timestamp}] [{level}] {safe_msg}</span>'
        )
        # 自动滚动到底部，确保最新日志可见
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def on_api_url_changed(self):
        """URL 输入变化时不立即检查，启动防抖定时器（600ms 无新输入才执行）"""
        self._api_url_debounce.start(600)

    def _on_api_url_debounced(self):
        """防抖到期后：检查 API 状态并持久化配置"""
        self.check_api_status()
        self.save_config()

    def on_speed_changed(self):
        """语速改变时持久化"""
        self.save_config()

    def browse_path(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "选择保存路径", self.output_file, "WAV Files (*.wav)"
        )
        if file_path:
            # 用户通过浏览选择的具体文件名也作为下次合成的命名模板来源
            self.output_file = file_path
            self.output_dir = os.path.dirname(file_path) or self.output_dir
            self.path_input.setText(file_path)
            self.save_config()
            self.append_log("INFO", f"已选择输出路径: {file_path}")

    def closeEvent(self, event):
        """窗口关闭时：停止播放器、停止轮询、终止引擎子进程、保存配置"""
        # 停止音频播放器
        if hasattr(self, "player"):
            self.player.stop()
        # 停止 API 状态轮询
        if hasattr(self, "_api_check_timer"):
            self._api_check_timer.stop()
        # 停止防抖定时器
        if hasattr(self, "_api_url_debounce"):
            self._api_url_debounce.stop()
        # 等待合成线程结束（最多 3 秒），避免 WAV 写入不完整
        if hasattr(self, "_worker") and self._worker is not None and self._worker.isRunning():
            self.append_log("INFO", "等待合成线程收尾...")
            self._worker.wait(3000)
        # 终止引擎子进程（随客户端关闭而关闭）
        # 用 taskkill /T /F 按进程树关闭，确保孙子进程 api.py 也被回收，
        # 避免 9880 端口被孤儿进程占用导致下次启动失败
        if self.engine_proc:
            self.append_log("INFO", "正在关闭引擎子进程...")
            try:
                self._terminate_engine_tree(self.engine_proc.pid)
                # 等待最多 5 秒
                try:
                    self.engine_proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    # 兜底：直接 kill 直接子进程
                    self.engine_proc.kill()
                    self.engine_proc.wait(timeout=2)
                self.append_log("INFO", "引擎子进程已关闭。")
            except Exception as e:
                self.append_log("WARNING", f"关闭引擎子进程异常: {e}")
            finally:
                self.engine_proc = None
        # 保存配置
        self.save_config()
        super().closeEvent(event)

    def _terminate_engine_tree(self, pid):
        """按进程树终止引擎子进程及其所有派生进程（含孙子进程 api.py）。

        Windows 用 taskkill /T /F <pid>；非 Windows 退化到 terminate()。
        静默处理失败，由调用方兜底 kill。
        """
        if sys.platform != "win32":
            return
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
        except Exception:
            pass

    def get_unique_path(self, path):
        """如果文件已存在，则自动递增生成唯一文件名，防止覆盖"""
        if not os.path.exists(path):
            return path
        dir_name, file_name = os.path.split(path)
        base_name, ext = os.path.splitext(file_name)
        counter = 1
        while True:
            new_file_name = f"{base_name}_{counter}{ext}"
            new_path = os.path.join(dir_name, new_file_name)
            if not os.path.exists(new_path):
                return new_path
            counter += 1

    def _update_synth_progress(self):
        """基于已用时间 / 估算时间更新进度条百分比（上限 95%）"""
        if self._synth_estimated_sec <= 0:
            return
        elapsed = time.time() - self._synth_start_time
        pct = min(int(elapsed / self._synth_estimated_sec * 100), 95)
        self.progress_bar.setValue(pct)

    def _generate_filename_from_text(self, text):
        """从文案内容前20个字生成 wav 文件名"""
        prefix = text[:20].strip()
        # 清理 Windows 文件名非法字符
        invalid_chars = '<>:"/\\|?*\n\r\t'
        for ch in invalid_chars:
            prefix = prefix.replace(ch, "")
        prefix = prefix.strip(". ")
        if not prefix:
            prefix = "mambo_output"
        return f"{prefix}.wav"

    def generate_voice(self):
        text = self.text_input.toPlainText().strip()
        if not text:
            self.status_label.setText("❌ 请输入配音文案")
            self.status_label.setStyleSheet("color: #f38ba8; font-weight: bold;")
            return

        # 记录本次合成文案，供 on_generate_finished 添加到历史记录
        self._last_synth_text = text

        # 防止重复点击：合成进行中再次点击直接忽略
        if hasattr(self, "_worker") and self._worker is not None and self._worker.isRunning():
            self.append_log("WARNING", "上一次合成仍在进行中，请稍候。")
            return

        self.btn_generate.setEnabled(False)
        self.btn_generate.setText("⏳ 正在合成中...")
        # 进度条切换为确定模式，基于文本长度估算合成时间
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.status_label.setText("⏳ 正在合成，请稍候...")
        self.status_label.setStyleSheet("color: #f9e2af; font-weight: bold;")

        # 生成文件名：优先使用用户填写的「配音文件命名」，留空则用文案前20字
        # 输出目录优先取 path_input 的目录；若为空则用 self.output_dir（用户上次选择的目录）
        current_path = self.path_input.text().strip()
        out_dir = os.path.dirname(current_path) or self.output_dir or os.path.join(os.path.expanduser("~"), "Desktop")
        # 确保目录存在，目录失效时回退桌面
        if not os.path.isdir(out_dir):
            out_dir = os.path.join(os.path.expanduser("~"), "Desktop")
        custom_name = self.name_input.text().strip()
        if custom_name:
            # 清理非法字符并自动补充 .wav 后缀
            invalid_chars = '<>:"/\\|?*\n\r\t'
            for ch in invalid_chars:
                custom_name = custom_name.replace(ch, "")
            custom_name = custom_name.strip(". ")
            if not custom_name:
                custom_name = self._generate_filename_from_text(text).replace(".wav", "")
            new_filename = f"{custom_name}.wav"
        else:
            new_filename = self._generate_filename_from_text(text)
        save_path = os.path.join(out_dir, new_filename)
        unique_path = self.get_unique_path(save_path)
        self.path_input.setText(unique_path)
        self.output_file = unique_path
        # 同步目录状态，下次启动沿用此目录
        self.output_dir = os.path.dirname(unique_path) or out_dir
        # 持久化（save_config 只存目录，不存完整文件路径，避免文件名污染配置）
        self.save_config()

        speed_val = self.speed_combo.currentData()

        # 估算合成时间：约 0.15 秒/字，最低 5 秒，最高 120 秒
        text_len = len(text)
        self._synth_estimated_sec = max(5.0, min(120.0, text_len * 0.15))
        self._synth_start_time = time.time()
        # 每 200ms 更新一次进度条
        self._synth_timer.start(200)

        # 用后台线程执行合成，避免阻塞 GUI
        self._worker = GenerateWorker(self.tts_client, text, unique_path, speed_val)
        self._worker.finished_signal.connect(self.on_generate_finished)
        self._worker.start()

    def on_generate_finished(self, success, message):
        """合成线程完成回调：恢复 UI 状态并展示结果"""
        # 停止进度定时器
        self._synth_timer.stop()
        # 恢复进度条为 100% 或保持当前值
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100 if success else self.progress_bar.value())
        self.btn_generate.setEnabled(True)
        self.btn_generate.setText("⚡ 合成配音")

        if success:
            self.status_label.setText("✅ 合成成功！")
            self.status_label.setStyleSheet("color: #a6e3a1; font-weight: bold;")
            self.append_log("INFO", message)
            # 合成成功后自动添加到历史记录并启用播放按钮
            self._add_to_history(self.output_file, self._last_synth_text)
            self.btn_play_pause.setEnabled(True)
        else:
            self.status_label.setText("❌ 合成失败，请查看下方日志")
            self.status_label.setStyleSheet("color: #f38ba8; font-weight: bold;")
            # 把具体的错误原因显示在日志面板，让用户能自助排查
            self.append_log("ERROR", f"合成失败：{message}")

    def play_voice(self):
        """兼容旧调用：播放当前路径的音频"""
        save_path = self.path_input.text().strip()
        if os.path.exists(save_path):
            self._play_path(save_path)
        else:
            self.status_label.setText("❌ 未找到音频文件")
            self.status_label.setStyleSheet("color: #f38ba8; font-weight: bold;")

    # ============ 播放器控制 ============

    def _play_path(self, path):
        """加载并播放指定路径的音频"""
        if not os.path.exists(path):
            self.status_label.setText("❌ 未找到音频文件")
            self.status_label.setStyleSheet("color: #f38ba8; font-weight: bold;")
            return
        self._current_play_path = path
        self.player.setSource(QUrl.fromLocalFile(path))
        self.player.play()
        self.btn_play_pause.setEnabled(True)
        self.btn_play_pause.setText("⏸ 暂停")
        self.seek_slider.setEnabled(True)
        self.status_label.setText("🔊 正在播放音频...")
        self.status_label.setStyleSheet("color: #a6e3a1; font-weight: bold;")

    def toggle_playback(self):
        """播放/暂停切换"""
        if self.player.source().isEmpty():
            # 没有加载音频，尝试播放当前路径
            self.play_voice()
            return
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def on_playback_state_changed(self, state):
        """播放状态变化时更新按钮文字"""
        if state == QMediaPlayer.PlayingState:
            self.btn_play_pause.setText("⏸ 暂停")
        else:
            self.btn_play_pause.setText("▶ 播放")

    def on_position_changed(self, position):
        """播放位置变化时更新进度条和时间标签"""
        duration = self.player.duration()
        # 更新时间标签
        pos_sec = position // 1000
        dur_sec = duration // 1000
        self.time_label.setText(f"{pos_sec//60:02d}:{pos_sec%60:02d} / {dur_sec//60:02d}:{dur_sec%60:02d}")
        # 更新进度条（拖动中不自动更新）
        if not self._seeking and duration > 0:
            self.seek_slider.setValue(int(position / duration * 1000))

    def on_duration_changed(self, duration):
        """音频总时长变化时更新时间标签"""
        pos_sec = self.player.position() // 1000
        dur_sec = duration // 1000
        self.time_label.setText(f"{pos_sec//60:02d}:{pos_sec%60:02d} / {dur_sec//60:02d}:{dur_sec%60:02d}")

    def on_seek_slider_moved(self, value):
        """用户拖动进度条时标记 seeking 状态"""
        self._seeking = True

    def on_seek_slider_released(self):
        """用户释放进度条时跳转到对应位置"""
        duration = self.player.duration()
        if duration > 0:
            position = int(self.seek_slider.value() / 1000 * duration)
            self.player.setPosition(position)
        self._seeking = False

    # ============ 合成历史记录 ============

    def _add_to_history(self, path, text):
        """合成成功后添加到历史记录（仅本次会话有效），最新记录插入最上方"""
        import wave
        duration_sec = 0
        try:
            with wave.open(path, 'rb') as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                if rate > 0:
                    duration_sec = frames / rate
        except Exception:
            pass

        time_str = datetime.now().strftime("%H:%M:%S")
        # 用自增 record_id 作为唯一标识，避免路径复用导致记录覆盖
        self._history_seq += 1
        record_id = self._history_seq
        record = {"record_id": record_id, "path": path, "text": text, "time": time_str, "duration": duration_sec}
        self._history_data.append(record)

        # 创建历史记录组件并插入到最上方（index 0）
        item_widget = HistoryItemWidget(record_id, path, text, time_str, duration_sec, self)
        self.history_container_layout.insertWidget(0, item_widget)
        self._history_widgets[record_id] = item_widget

    def _history_save_as_path(self, src_path):
        """将指定路径的音频另存为新文件"""
        if not src_path or not os.path.exists(src_path):
            self.append_log("WARNING", "源文件不存在，无法另存为。")
            return
        default_name = os.path.basename(src_path)
        save_path, _ = QFileDialog.getSaveFileName(
            self, "另存为", default_name, "WAV Files (*.wav)"
        )
        if save_path:
            try:
                shutil.copy2(src_path, save_path)
                self.append_log("INFO", f"已另存为：{save_path}")
            except Exception as e:
                self.append_log("ERROR", f"另存为失败：{e}")

    def _history_delete_path(self, record_id, widget):
        """从历史记录中删除指定项（不删除磁盘文件）"""
        self.history_container_layout.removeWidget(widget)
        widget.deleteLater()
        if record_id in self._history_widgets:
            del self._history_widgets[record_id]
        self._history_data = [r for r in self._history_data if r.get("record_id") != record_id]
        path = widget.path
        self.append_log("INFO", f"已从历史记录移除（磁盘文件保留）：{os.path.basename(path)}")

    def open_output_folder(self):
        save_path = self.path_input.text().strip()
        folder_path = os.path.dirname(save_path)
        if not folder_path:
            self.append_log("WARNING", "保存路径为空，无法打开目录。")
            return
        if not os.path.exists(folder_path):
            self.append_log("WARNING", f"目录不存在：{folder_path}")
            return
        try:
            os.startfile(folder_path)
        except Exception as e:
            self.append_log("ERROR", f"打开目录失败：{e}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MamboTTSApp()
    window.show()
    sys.exit(app.exec())
