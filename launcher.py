"""
MamboTTS 统一启动器
- 检测安装状态
- 未安装：弹窗询问 → 安装界面（4 阶段进度条 + 实时日志）
- 已安装：直接启动主界面 app.py
"""
import os
import sys
import subprocess

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QTextEdit, QMessageBox, QFrame, QGraphicsDropShadowEffect,
    QDialog, QRadioButton
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor


# ============================================================
# 安装状态检测
# ============================================================

def _project_dir():
    return os.path.dirname(os.path.abspath(__file__))


def is_installed():
    """
    判定是否已安装：
    - GPT-SoVITS 目录存在且含 api.py（整合包已解压）
    - runtime/python.exe 存在（整合包自带 python）
    """
    base = _project_dir()
    gsv_dir = os.path.join(base, "GPT-SoVITS")
    api_py = os.path.join(gsv_dir, "api.py")
    runtime_python = os.path.join(gsv_dir, "runtime", "python.exe")
    return os.path.exists(api_py) and os.path.exists(runtime_python)


def is_venv_ready():
    """客户端 venv 是否已就绪"""
    base = _project_dir()
    venv_python = os.path.join(base, ".venv", "Scripts", "python.exe")
    return os.path.exists(venv_python)


# ============================================================
# 显卡型号选择对话框
# ============================================================

class GpuSelectionDialog(QDialog):
    """让用户选择显卡型号，决定下载哪个整合包"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择显卡型号")
        self.setFixedSize(500, 320)
        self._gpu_type = "nvidia50"
        self._build_ui()

    def _build_ui(self):
        self.setStyleSheet("""
            QDialog { background-color: #1e1e2e; }
            QLabel { color: #cdd6f4; font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif; }
            QRadioButton { color: #cdd6f4; font-size: 13px; spacing: 8px; }
            QRadioButton::indicator { width: 16px; height: 16px; }
            QPushButton {
                background-color: #89b4fa; color: #11111b; border: none;
                border-radius: 6px; padding: 8px 20px; font-weight: bold; font-size: 13px;
            }
            QPushButton:hover { background-color: #b4befe; }
            QPushButton#cancelBtn { background-color: #45475a; color: #cdd6f4; }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 24, 24, 24)

        title = QLabel("请选择您的显卡型号")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #cdd6f4;")
        layout.addWidget(title)

        desc = QLabel("不同显卡需要下载对应的 GPT-SoVITS 整合包，\n选错可能导致无法正常推理。")
        desc.setStyleSheet("color: #7f849c; font-size: 12px;")
        layout.addWidget(desc)

        self.rb_nvidia50 = QRadioButton("NVIDIA 50 系显卡 (RTX 5070 / 5080 / 5090 等)")
        self.rb_nvidia50.setChecked(True)
        layout.addWidget(self.rb_nvidia50)

        self.rb_other = QRadioButton("其他显卡 (NVIDIA RTX 30/40 系、AMD 等)")
        layout.addWidget(self.rb_other)

        layout.addStretch()

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_cancel = QPushButton("取消")
        btn_cancel.setObjectName("cancelBtn")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QPushButton("确认下载")
        btn_ok.clicked.connect(self._on_confirm)
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_ok)
        layout.addLayout(btn_layout)

    def _on_confirm(self):
        if self.rb_nvidia50.isChecked():
            self._gpu_type = "nvidia50"
        else:
            self._gpu_type = "general"
        self.accept()

    def get_gpu_type(self):
        return self._gpu_type


# ============================================================
# 安装线程：后台执行 install_engine.install()
# ============================================================

class InstallWorker(QThread):
    """后台安装线程，避免阻塞 GUI"""
    progress_signal = Signal(float)         # 整体进度 0.0~1.0
    log_signal = Signal(str)               # 日志文本
    state_signal = Signal(str)             # 当前阶段名
    finished_signal = Signal(bool, str)    # (success, message)

    def __init__(self, gpu_type="nvidia50"):
        super().__init__()
        self.gpu_type = gpu_type

    def run(self):
        # 延迟导入，避免在未安装 modelscope 时主线程 import 失败
        try:
            from install_engine import install
        except Exception as e:
            self.finished_signal.emit(False, f"加载安装模块失败: {e}")
            return

        success, message = install(
            progress_cb=lambda p: self.progress_signal.emit(p),
            log_cb=lambda m: self.log_signal.emit(m),
            state_cb=lambda s: self.state_signal.emit(s),
            gpu_type=self.gpu_type,
        )
        self.finished_signal.emit(success, message)


# ============================================================
# 安装界面
# ============================================================

class InstallerWindow(QWidget):
    """安装界面：分阶段进度条 + 实时日志"""

    def __init__(self, on_done_callback=None, gpu_type="nvidia50"):
        super().__init__()
        self.on_done_callback = on_done_callback
        self.gpu_type = gpu_type
        self._worker = None
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("MamboTTS 引擎安装")
        self.resize(700, 560)
        self.setMinimumSize(600, 480)

        self.setStyleSheet("""
            QWidget {
                background-color: #1e1e2e;
                color: #cdd6f4;
                font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
            }
            QLabel { font-size: 13px; }
            QTextEdit {
                background-color: #11111b;
                border: 1px solid #313244;
                border-radius: 8px;
                padding: 10px;
                color: #e4e8f0;
                font-size: 13px;
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
            QPushButton:hover { background-color: #b4befe; }
            QPushButton:disabled { background-color: #45475a; color: #7f849c; }
            QProgressBar {
                background-color: #11111b;
                border: 1px solid #313244;
                border-radius: 6px;
                text-align: center;
                color: #cdd6f4;
                min-height: 22px;
            }
            QProgressBar::chunk { background-color: #89b4fa; border-radius: 5px; }
            QFrame#HeaderCard {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #89b4fa, stop:1 #b4befe);
                border-radius: 10px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # Header
        header = QFrame()
        header.setObjectName("HeaderCard")
        header.setFixedHeight(70)
        # 直接在 QFrame 上设置内联背景色，避免 QGraphicsDropShadowEffect
        # 导致 stylesheet 中的 qlineargradient 背景不渲染（Qt 已知问题）
        header.setStyleSheet("background-color: #89b4fa; border-radius: 10px;")

        h_layout = QVBoxLayout(header)
        h_layout.setContentsMargins(15, 10, 15, 10)
        title = QLabel("MamboTTS 引擎一键安装")
        title.setStyleSheet("color: #11111b; font-size: 20px; font-weight: bold;")
        subtitle = QLabel("首次使用需要下载 GPT-SoVITS 整合包（约 8GB），请保持网络畅通")
        subtitle.setStyleSheet("color: #1e1e2e; font-size: 12px;")
        h_layout.addWidget(title)
        h_layout.addWidget(subtitle)
        layout.addWidget(header)

        # 当前阶段
        self.stage_label = QLabel("准备中...")
        self.stage_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #f9e2af;")
        layout.addWidget(self.stage_label)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        # 日志面板
        log_label = QLabel("安装日志:")
        layout.addWidget(log_label)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        layout.addWidget(self.log_view, 1)

        # 按钮栏
        btn_layout = QHBoxLayout()
        self.btn_install = QPushButton("🚀 开始安装")
        self.btn_install.setFixedHeight(40)
        self.btn_install.clicked.connect(self.start_install)
        self.btn_close = QPushButton("退出")
        self.btn_close.setStyleSheet("background-color: #45475a; color: #cdd6f4;")
        self.btn_close.setFixedHeight(40)
        self.btn_close.clicked.connect(self.close)
        btn_layout.addWidget(self.btn_install, 2)
        btn_layout.addWidget(self.btn_close, 1)
        layout.addLayout(btn_layout)

    def start_install(self):
        """启动后台安装线程"""
        self.btn_install.setEnabled(False)
        self.btn_install.setText("⏳ 安装进行中...")
        self.progress_bar.setValue(0)

        self._worker = InstallWorker(gpu_type=self.gpu_type)
        self._worker.progress_signal.connect(self.on_progress)
        self._worker.log_signal.connect(self.on_log)
        self._worker.state_signal.connect(self.on_state)
        self._worker.finished_signal.connect(self.on_finished)
        self._worker.start()

    def on_progress(self, p):
        self.progress_bar.setValue(int(p * 100))

    def on_log(self, msg):
        # 用 HTML 显式设置颜色，QTextEdit.append 不一定继承 stylesheet 的 color
        safe_msg = (msg.replace("&", "&amp;")
                        .replace("<", "&lt;")
                        .replace(">", "&gt;"))
        self.log_view.append(f'<span style="color:#e4e8f0; font-size:13px;">{safe_msg}</span>')
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def on_state(self, stage):
        self.stage_label.setText(f"当前阶段: {stage}")

    def on_finished(self, success, message):
        if success:
            self.stage_label.setText("✅ 安装完成")
            self.stage_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #a6e3a1;")
            self.btn_install.setText("✅ 完成")
            QMessageBox.information(self, "安装完成", "GPT-SoVITS 引擎安装成功！\n即将启动 MamboTTS 主界面。")
            if self.on_done_callback:
                self.on_done_callback()
            self.close()
        else:
            self.stage_label.setText("❌ 安装失败")
            self.stage_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #f38ba8;")
            self.btn_install.setEnabled(True)
            self.btn_install.setText("🔄 重新尝试安装")
            QMessageBox.critical(self, "安装失败", f"安装过程中发生错误:\n\n{message}\n\n请查看日志了解详情。")

    def closeEvent(self, event):
        # 安装进行中不允许直接关闭，避免文件半成品
        if self._worker and self._worker.isRunning():
            reply = QMessageBox.question(
                self, "确认退出",
                "安装正在进行中，退出可能导致文件不完整。确定要退出吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply == QMessageBox.No:
                event.ignore()
                return
            try:
                self._worker.terminate()
            except Exception:
                pass
        event.accept()


# ============================================================
# 主入口
# ============================================================

def launch_main_app():
    """启动主界面 app.py（同一进程内 import，避免再起子进程）"""
    from app import MamboTTSApp
    # 隐藏/关闭安装窗口由调用方处理
    win = MamboTTSApp()
    win.show()
    return win


def main():
    app = QApplication(sys.argv)

    if is_installed():
        # 已安装：直接进主界面
        from app import MamboTTSApp
        win = MamboTTSApp()
        win.show()
        sys.exit(app.exec())
    else:
        # 未安装：弹窗提示
        reply = QMessageBox.question(
            None, "首次使用",
            "检测到 GPT-SoVITS 引擎尚未安装。\n\n"
            "安装需要下载约 8GB 的整合包（国内镜像源，速度较快）。\n"
            "是否立即开始安装？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
        )
        if reply == QMessageBox.No:
            sys.exit(0)

        # 选择显卡型号，决定下载哪个整合包
        gpu_dialog = GpuSelectionDialog()
        if gpu_dialog.exec() != QDialog.Accepted:
            sys.exit(0)
        gpu_type = gpu_dialog.get_gpu_type()

        # 启动安装界面；安装完成后启动主界面
        installer = InstallerWindow(on_done_callback=None, gpu_type=gpu_type)
        installer.show()
        # 选完显卡后直接开始下载，无需再手动点击"开始安装"
        installer.start_install()

        # 安装完成后，由 on_finished 启动主界面（在同进程里 replace）
        # 为简单起见，安装完成后直接退出当前 app，由 MamboTTS.bat 重新拉起
        def on_done():
            installer.close()
            # 重新拉起主程序：在同一进程里启动主窗口
            from app import MamboTTSApp
            win = MamboTTSApp()
            win.show()
            # 把 installer 引用清掉避免 GC
            nonlocal_installer[0] = win

        nonlocal_installer = [None]
        installer.on_done_callback = on_done

        sys.exit(app.exec())


if __name__ == "__main__":
    main()
