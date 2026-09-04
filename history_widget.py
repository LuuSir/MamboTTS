"""合成历史记录卡片组件（从 app.py 抽出）。

不再持有主窗口引用：交互一律通过构造时传入的 on_play / on_save_as / on_delete
回调完成。控件样式以 objectName + 全局 QSS 为主，另暴露 refresh_theme()
供主窗口在主题切换后逐卡重刷内联兜底（个别平台 QSS 背景对动态子控件
应用不可靠，双保险保证换肤正确）。
"""
from PySide6.QtWidgets import (QFrame, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QScrollArea)
from PySide6.QtCore import Qt

from theme import THEME

_LONG_TEXT_LIMIT = 80


class HistoryItemWidget(QFrame):
    """单条合成历史记录：时间/时长 + 播放/另存/删除按钮 + 可折叠完整文案"""

    def __init__(self, record_id, path, text, time_str, duration_sec,
                 on_play=None, on_save_as=None, on_delete=None, parent=None):
        super().__init__(parent)
        self.record_id = record_id
        self.path = path
        self.text = text
        self._on_play = on_play
        self._on_save_as = on_save_as
        self._on_delete = on_delete
        self._expanded = False
        self._scroll = None  # 展开全文用的内部滚动区（懒创建）
        self._build_ui(time_str, duration_sec)

    def _build_ui(self, time_str, duration_sec):
        # 卡片与内部控件样式走 objectName + 全局 QSS（theme.py），
        # 主题切换时整窗 setStyleSheet 自动重刷，无需逐卡重建
        self.setObjectName("HistoryCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        top_row = QHBoxLayout()
        top_row.setSpacing(6)

        dur_int = int(duration_sec)
        dur_str = f"{dur_int // 60:01d}:{dur_int % 60:02d}"
        info = QLabel(f"{time_str}   {dur_str}")
        info.setObjectName("HistoryMeta")
        top_row.addWidget(info)
        top_row.addStretch()

        # 主操作（播放）中灰底；另存次灰；删除红字幽灵
        btn_play = QPushButton("播放")
        btn_play.setObjectName("HisPlay")
        btn_play.setFixedSize(56, 26)
        btn_play.setCursor(Qt.PointingHandCursor)
        btn_play.clicked.connect(lambda: self._on_play and self._on_play(self.path))
        self.btn_play = btn_play
        top_row.addWidget(btn_play)

        btn_save = QPushButton("另存")
        btn_save.setObjectName("HisSave")
        btn_save.setFixedSize(56, 26)
        btn_save.setCursor(Qt.PointingHandCursor)
        btn_save.clicked.connect(lambda: self._on_save_as and self._on_save_as(self.path))
        self.btn_save = btn_save
        top_row.addWidget(btn_save)

        btn_del = QPushButton("删除")
        btn_del.setObjectName("HisDel")
        btn_del.setFixedSize(56, 26)
        btn_del.setCursor(Qt.PointingHandCursor)
        btn_del.clicked.connect(lambda: self._on_delete and self._on_delete(self.record_id, self))
        self.btn_del = btn_del
        top_row.addWidget(btn_del)

        layout.addLayout(top_row)

        self.text_label = QLabel()
        self.text_label.setObjectName("HistoryText")
        self.text_label.setWordWrap(True)
        self.text_label.setTextFormat(Qt.PlainText)

        if len(self.text) > _LONG_TEXT_LIMIT:
            self._is_long = True
            self.text_label.setText(self.text[:_LONG_TEXT_LIMIT] + "...")
            self.btn_expand = QPushButton("展开全文 ▼")
            self.btn_expand.setObjectName("HisExpand")
            self.btn_expand.setFixedHeight(20)
            self.btn_expand.setCursor(Qt.PointingHandCursor)
            self.btn_expand.clicked.connect(self._toggle_expand)
            layout.addWidget(self.text_label)
            layout.addWidget(self.btn_expand)
        else:
            self._is_long = False
            self.text_label.setText(self.text)
            layout.addWidget(self.text_label)

    def refresh_theme(self):
        """主题切换后重刷本卡内联样式（QSS 兜底，保证动态卡片换肤可靠）。"""
        t = THEME
        self.setStyleSheet(
            f"QFrame {{ background-color: {t['surface']}; "
            f"border: 1px solid {t['border']}; border-radius: 8px; }}"
        )
        # 三按钮内联重设（避免个别平台 QSS 背景对动态子控件不生效）
        self.btn_play.setStyleSheet(
            f"QPushButton {{ background-color: {t['btn_primary']}; color: {t['btn_primary_text']};"
            f" border: 1px solid {t['btn_primary_hover']}; border-radius: 4px;"
            f" font-size: 11px; font-weight: 600; }}"
        )
        self.btn_save.setStyleSheet(
            f"QPushButton {{ background-color: {t['surface3']}; color: {t['border_active']};"
            f" border: none; border-radius: 4px; font-size: 11px; }}"
        )
        self.btn_del.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {t['danger']};"
            f" border: 1px solid {t['border_hover']}; border-radius: 4px; font-size: 11px; }}"
        )
        self.text_label.setStyleSheet(
            f"color: {t['text']}; font-size: 12px; background: transparent; border: none;"
        )
        if hasattr(self, "btn_expand"):
            self.btn_expand.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {t['muted']}; border: none;"
                f" font-size: 11px; text-align: left; }}"
            )
        if self._scroll is not None:
            self._scroll.setStyleSheet(
                "QScrollArea { background-color: transparent; border: none; }"
            )

    def _toggle_expand(self):
        """展开/收起全文。

        展开时全文放进"固定最大高度 + 内部滚动"的区域，并给整卡设最大高度，
        避免长文案把卡片撑到占满整个右栏。
        """
        if self._expanded:
            # 收起
            self.text_label.setText(self.text[:_LONG_TEXT_LIMIT] + "...")
            self.text_label.setVisible(True)
            if self._scroll is not None:
                self._scroll.setVisible(False)
            self.btn_expand.setText("展开全文 ▼")
            self.setMaximumHeight(16777215)  # 还原不限高
        else:
            # 展开
            self.text_label.setVisible(False)
            if self._scroll is None:
                self._scroll = QScrollArea()
                self._scroll.setWidgetResizable(True)
                self._scroll.setMaximumHeight(160)
                self._scroll.setMinimumHeight(60)
                self._scroll.setStyleSheet(
                    "QScrollArea { background-color: transparent; border: none; }"
                )
                full = QLabel(self.text)
                full.setObjectName("HistoryFull")
                full.setWordWrap(True)
                full.setTextFormat(Qt.PlainText)
                self._scroll.setWidget(full)
                # 个别平台 viewport 默认底色不随 QSS：显式透明，避免滚出白色补丁
                try:
                    self._scroll.viewport().setAutoFillBackground(False)
                except Exception:
                    pass
                # 插入到折叠 label 之后、展开按钮之前
                idx = self.layout().indexOf(self.btn_expand)
                self.layout().insertWidget(idx, self._scroll)
            self._scroll.setVisible(True)
            self.btn_expand.setText("收起 ▲")
            # 整卡限高：顶部按钮行(约30) + 滚动区(≤160) + 按钮行(约24) + 边距
            self.setMaximumHeight(240)
        self._expanded = not self._expanded
