"""MamboTTS 双主题（Monochrome 深色 / Paper 浅色）。

设计规范由 muse-spark-1.3 评审制定：
- 深色：近黑分层 + 白强调（白底黑字主按钮）+ 绿/红功能色
- 浅色：纸灰分层（bg 灰→卡片白）+ 黑强调（黑底白字主按钮，与深色镜像）
- 切换方式：模块级 THEME 指向当前主题 dict，apply_theme() 原地更新
  并返回该主题的全局 QSS；所有 base_qss/status_style/log_color 读取
  THEME，切换后 GUI 只需 setStyleSheet(新 QSS) 即可全局换肤。
"""

# ---- 两套 Token ----

_DARK_THEME = {
    # 背景层级：4 阶近黑，彼此只差 4-6% 明度
    "bg": "#0A0A0B",          # 主窗口底（冷调近黑）
    "surface": "#141417",     # 卡片 / Header
    "surface2": "#1A1A1E",    # 输入框 / 日志 / ScrollArea / 次按钮底
    "surface3": "#232326",    # 仅 hover/pressed 填充
    "border": "#26262B",      # 常态描边
    "border_hover": "#3F3F46",
    "border_active": "#E4E4E7",  # focus / 选中（接近白）
    "text": "#FAFAFA",        # 主文字
    "muted": "#A1A1AA",       # 次要文字
    "dim": "#71717A",         # 弱化文字
    "faint": "#3A3A42",       # 仅分割线/禁用
    "accent": "#FFFFFF",      # 滑条填充/进度强调（白）
    "accent_hover": "#E4E4E7",
    "accent_pressed": "#C9C9CF",
    "accent_text": "#0B0B0D",
    # 主按钮（用户反馈纯白刺眼 → 用中灰，视觉更稳）
    "btn_primary": "#3F3F46",
    "btn_primary_hover": "#52525B",
    "btn_primary_pressed": "#2E2E33",
    "btn_primary_text": "#F4F4F5",
    "success": "#34D399",     # 绿
    "success_hover": "#6EE7B7",
    "danger": "#F87171",      # 红
    "warning": "#FBBF24",     # 黄
    "pink": "#A1A1AA",
    "log_bg": "#101013",      # 日志底（比输入框更暗，下沉）
    "radio_border": "#8A8F98",  # 单选未选中描边
}

_LIGHT_THEME = {
    # 浅色：纸灰分层（bg 灰→surface 白浮起→surface2 内凹）
    "bg": "#F4F4F5",          # 窗底 Zinc-100 纸灰，非纯白
    "surface": "#FFFFFF",     # 卡片：纯白
    "surface2": "#F9F9FA",    # 输入框：比卡片微暗，内凹
    "surface3": "#E9E9EC",    # hover：比 bg 深一档
    "border": "#E4E4E7",      # 描边 Zinc-200
    "border_hover": "#D4D4D8",
    "border_active": "#09090B",  # focus 黑（与深色 focus 白镜像）
    "text": "#09090B",        # 主字近黑
    "muted": "#3F3F46",       # 次字（日志正文/说明，需 ≥4.5:1）
    "dim": "#4B4B53",         # 弱字（时间戳/次要，浅底可读）
    "faint": "#6B7280",       # placeholder/禁用（Zinc-500，浅底清晰）
    "accent": "#18181B",      # 滑条填充/进度强调（近黑）
    "accent_hover": "#27272A",
    "accent_pressed": "#3F3F46",
    "accent_text": "#FFFFFF",
    # 主按钮（用户反馈纯黑刺眼 → 中灰更柔和）
    "btn_primary": "#5B5C60",
    "btn_primary_hover": "#4B4C50",
    "btn_primary_pressed": "#3F4044",
    "btn_primary_text": "#FFFFFF",
    "success": "#059669",     # Emerald-600（浅底需压深才可读）
    "success_hover": "#10B981",
    "danger": "#DC2626",      # Red-600
    "warning": "#D97706",     # Amber-600
    "pink": "#71717A",
    "log_bg": "#E9E9EC",      # 日志底（浅色下微沉）
    "radio_border": "#A1A1AA",  # 单选未选中描边
}

THEMES = {"dark": _DARK_THEME, "light": _LIGHT_THEME}

# 当前主题：独立副本（不直接引用 _DARK_THEME，避免 clear/update 污染源表）
THEME = dict(_DARK_THEME)
_current_theme_name = "dark"


def current_theme_name() -> str:
    return _current_theme_name


def apply_theme(name: str) -> str:
    """切换到 name 主题（dark/light），原地更新 THEME 内容并返回新 QSS。
    调用方（QMainWindow）负责 self.setStyleSheet(返回值) 全局换肤。
    注意：THEME 是模块级 dict，被各文件以引用方式共享，原地 update
    后所有读取 THEME 的函数（base_qss/status_style/log_color）自动生效。"""
    global _current_theme_name
    if name not in THEMES:
        name = "dark"
    target = THEMES[name]
    THEME.clear()
    THEME.update(target)
    _current_theme_name = name
    return base_qss()

FONT_FAMILY = "'Segoe UI', 'Microsoft YaHei', sans-serif"
MONO_FAMILY = "Consolas, 'Noto Sans Mono', monospace"

# 状态文本符号（代码里拼到文案前）：圆点/符号即状态
STATUS_SYMBOL = {
    "ok": "●",
    "busy": "◐",
    "warn": "▲",
    "error": "✕",
    "info": "○",
}


def base_qss() -> str:
    """主窗口/安装窗口通用的全局 QSS（黑白扁平 + 1px 描边）。"""
    t = THEME
    return f"""
        QMainWindow {{ background-color: {t['bg']}; }}
        QWidget {{
            color: {t['text']};
            font-family: {FONT_FAMILY};
            font-size: 13px;
        }}
        /* 模态子对话框跟随深色主题（QFileDialog 为系统原生，无法 QSS） */
        QDialog, QMessageBox {{ background-color: {t['bg']}; }}
        QDialog QLabel, QMessageBox QLabel {{ color: {t['text']}; }}
        QLabel {{ font-size: 13px; }}

        QTextEdit {{
            background-color: {t['surface2']};
            border: 1px solid {t['border']};
            border-radius: 8px;
            padding: 8px 10px;
            color: {t['text']};
            font-size: 14px;
            selection-background-color: {t['surface3']};
        }}
        QTextEdit:focus {{ border: 1px solid {t['border_active']}; }}
        QTextEdit:disabled {{ color: {t['faint']}; }}
        /* 日志：下沉 + 等宽，比输入框更暗 */
        QTextEdit#LogView {{
            background-color: {t['log_bg']};
            color: {t['muted']};
            font-size: 12px;
            font-family: {MONO_FAMILY};
        }}
        QLineEdit {{
            background-color: {t['surface2']};
            border: 1px solid {t['border']};
            border-radius: 6px;
            padding: 6px 10px;
            color: {t['text']};
            selection-background-color: {t['surface3']};
        }}
        QLineEdit:focus {{ border: 1px solid {t['border_active']}; }}
        QLineEdit:disabled {{ color: {t['faint']}; }}

        /* 主按钮 = 白底黑字，反白是黑白主题里最大的强调 */
        QPushButton {{
            background-color: {t['btn_primary']};
            color: {t['btn_primary_text']};
            border: none;
            border-radius: 6px;
            padding: 8px 16px;
            font-weight: 700;
            font-size: 13px;
        }}
        QPushButton:hover {{ background-color: {t['btn_primary_hover']}; }}
        QPushButton:pressed {{ background-color: {t['btn_primary_pressed']}; }}
        QPushButton:disabled {{
            background-color: {t['surface2']};
            color: {t['faint']};
            border: 1px solid {t['border']};
        }}
        /* 次按钮 = 深灰 ghost（描边提亮，避免与背景糊在一起） */
        QPushButton#SecondaryBtn {{
            background-color: {t['surface2']};
            color: {t['border_active']};
            border: 1px solid {t['border_hover']};
            border-radius: 6px;
            font-weight: 400;
        }}
        QPushButton#SecondaryBtn:hover {{ background-color: {t['surface3']}; border-color: {t['border_active']}; }}
        QPushButton#SecondaryBtn:pressed {{ background-color: {t['surface']}; }}
        QPushButton#SecondaryBtn:disabled {{ color: {t['faint']}; border-color: {t['border']}; }}
        /* 主题切换按钮：次按钮风格，宽裕 padding 防中文截断 */
        QPushButton#ThemeBtn {{
            background-color: {t['surface2']};
            color: {t['border_active']};
            border: 1px solid {t['border_hover']};
            border-radius: 6px;
            padding: 2px 16px;
            font-size: 12px;
            font-weight: 400;
            min-width: 96px;
        }}
        QPushButton#ThemeBtn:hover {{ background-color: {t['surface3']}; border-color: #52525B; }}
        QPushButton#ThemeBtn:pressed {{ background-color: {t['surface']}; }}
        /* 危险操作不做红色：幽灵 + hover 反白 */
        QPushButton#DangerBtn {{
            background: transparent;
            color: {t['muted']};
            border: 1px solid {t['border_hover']};
            border-radius: 6px;
            font-weight: 400;
        }}
        QPushButton#DangerBtn:hover {{ color: {t['accent_hover']}; border-color: {t['border_active']}; background: {t['surface2']}; }}

        /* Header 扁平卡片（去渐变） */
        QFrame#HeaderCard {{
            background-color: {t['surface']};
            border: 1px solid {t['border']};
            border-radius: 12px;
        }}
        QLabel#HeaderTitle {{ color: {t['text']}; font-size: 17px; font-weight: 800; background: transparent; }}
        QLabel#HeaderSub {{ color: {t['muted']}; font-size: 12px; font-weight: 400; background: transparent; }}
        QFrame#MainCard {{
            background-color: {t['surface']};
            border: 1px solid {t['border']};
            border-radius: 12px;
        }}
        QFrame#AccentBar {{ background-color: {t['accent']}; border-radius: 2px; }}

        /* 历史卡片 */
        QFrame#HistoryCard {{
            background-color: {t['surface']};
            border: 1px solid {t['border']};
            border-radius: 8px;
        }}
        QFrame#HistoryCard:hover {{ border-color: {t['border_hover']}; }}
        QLabel#HistoryMeta {{ color: {t['dim']}; font-size: 11px; background: transparent; border: none; }}
        QLabel#HistoryText {{ color: {t['text']}; font-size: 12px; background: transparent; border: none; }}
        QLabel#HistoryFull {{
            color: {t['text']}; font-size: 12px; background: transparent; border: none; padding: 2px 4px;
        }}
        QPushButton#HisPlay {{
            background-color: {t['btn_primary']}; color: {t['btn_primary_text']};
            border: 1px solid {t['btn_primary_hover']}; border-radius: 4px;
            padding: 1px 12px; font-size: 11px; font-weight: 600;
        }}
        QPushButton#HisPlay:hover {{ background-color: {t['btn_primary_hover']}; }}
        QPushButton#HisSave {{
            background-color: {t['surface3']}; color: {t['border_active']};
            border: none; border-radius: 4px; padding: 2px 12px; font-size: 11px;
        }}
        QPushButton#HisSave:hover {{ background-color: {t['border_hover']}; }}
        QPushButton#HisDel {{
            background: transparent; color: {t['danger']};
            border: 1px solid {t['border_hover']}; border-radius: 4px;
            padding: 2px 12px; font-size: 11px;
        }}
        QPushButton#HisDel:hover {{ color: {t['danger']}; border-color: {t['danger']}; background: {t['surface2']}; }}
        QPushButton#HisExpand {{
            background: transparent; color: {t['muted']}; border: none;
            padding: 0px; font-size: 11px; text-align: left;
        }}
        QPushButton#HisExpand:hover {{ color: {t['text']}; }}

        QProgressBar {{
            background-color: {t['surface2']};
            border: 1px solid {t['border']};
            border-radius: 6px;
            text-align: center;
            color: {t['muted']};
            font-size: 12px;
            min-height: 18px;
        }}
        QProgressBar::chunk {{ background-color: {t['border_active']}; border-radius: 5px; }}
        QProgressBar:disabled {{ color: {t['faint']}; }}

        /* 滑条：4px 可见轨道 + 白手柄（可拖拽感） */
        QSlider::groove:horizontal {{
            background: {t['border_hover']};
            height: 4px;
            border-radius: 2px;
        }}
        QSlider::sub-page:horizontal {{ background: {t['accent']}; border-radius: 2px; }}
        QSlider::add-page:horizontal {{ background: {t['border_hover']}; border-radius: 2px; }}
        QSlider::handle:horizontal {{
            background: {t['accent']};
            border: 2px solid {t['bg']};
            width: 14px;
            height: 14px;
            margin: -7px 0;
            border-radius: 9px;
        }}
        QSlider::handle:horizontal:hover {{ background: {t['accent_hover']}; width: 16px; height: 16px; margin: -8px 0; }}
        QSlider::handle:horizontal:disabled {{ background: {t['dim']}; border-color: {t['surface3']}; }}

        /* 滚动条：细 + 低对比 */
        QScrollArea {{
            border: 1px solid {t['border']};
            border-radius: 8px;
            background-color: {t['surface2']};
        }}
        QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
        QScrollBar::handle:vertical {{ background: {t['surface3']}; border-radius: 4px; min-height: 30px; }}
        QScrollBar::handle:vertical:hover {{ background: {t['border_hover']}; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 2px; }}
        QScrollBar::handle:horizontal {{ background: {t['surface3']}; border-radius: 4px; min-width: 30px; }}
        QScrollBar::handle:horizontal:hover {{ background: {t['border_hover']}; }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
    """


def header_qss() -> str:
    """launcher/bootstrap 等独立窗口顶层 QSS（QWidget 底色版）。"""
    t = THEME
    return f"""
        QWidget {{
            background-color: {t['bg']};
            color: {t['text']};
            font-family: {FONT_FAMILY};
            font-size: 13px;
        }}
        QDialog, QMessageBox {{ background-color: {t['bg']}; }}
        QDialog QLabel, QMessageBox QLabel {{ color: {t['text']}; }}
        QLabel {{ font-size: 13px; }}
        QTextEdit {{
            background-color: {t['log_bg']};
            border: 1px solid {t['border']};
            border-radius: 8px;
            padding: 8px 10px;
            color: {t['muted']};
            font-size: 12px;
            font-family: {MONO_FAMILY};
            selection-background-color: {t['surface3']};
        }}
        QPushButton {{
            background-color: {t['btn_primary']};
            color: {t['btn_primary_text']};
            border: none;
            border-radius: 6px;
            padding: 8px 16px;
            font-weight: 700;
            font-size: 13px;
        }}
        QPushButton:hover {{ background-color: {t['btn_primary_hover']}; }}
        QPushButton:pressed {{ background-color: {t['btn_primary_pressed']}; }}
        QPushButton:disabled {{ background-color: {t['surface2']}; color: {t['faint']}; border: 1px solid {t['border']}; }}
        QPushButton#SecondaryBtn {{
            background-color: {t['surface2']};
            color: {t['border_active']};
            border: 1px solid {t['surface3']};
            border-radius: 6px;
            font-weight: 400;
        }}
        QPushButton#SecondaryBtn:hover {{ background-color: {t['surface3']}; border-color: {t['border_hover']}; }}
        QPushButton#SecondaryBtn:pressed {{ background-color: {t['surface']}; }}
        QFrame#HeaderCard {{
            background-color: {t['surface']};
            border: 1px solid {t['border']};
            border-radius: 12px;
        }}
        QLabel#HeaderTitle {{ color: {t['text']}; font-size: 17px; font-weight: 800; background: transparent; }}
        QLabel#HeaderSub {{ color: {t['muted']}; font-size: 12px; font-weight: 400; background: transparent; }}
        QFrame#AccentBar {{ background-color: {t['accent']}; border-radius: 2px; }}
        QProgressBar {{
            background-color: {t['surface2']};
            border: 1px solid {t['border']};
            border-radius: 6px;
            text-align: center;
            color: {t['muted']};
            font-size: 12px;
            min-height: 18px;
        }}
        QProgressBar::chunk {{ background-color: {t['border_active']}; border-radius: 5px; }}
        QRadioButton {{ color: {t['border_active']}; font-size: 13px; spacing: 10px; background: transparent; }}
        QRadioButton::indicator {{
            width: 16px; height: 16px; border-radius: 9px;
            background: {t['surface2']}; border: 1.5px solid {t['radio_border']};
        }}
        QRadioButton::indicator:hover {{ border-color: {t['border_active']}; }}
        QRadioButton::indicator:checked {{ background: {t['accent']}; border-color: {t['accent']}; }}
        QRadioButton:disabled {{ color: {t['faint']}; }}
        QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
        QScrollBar::handle:vertical {{ background: {t['surface3']}; border-radius: 4px; min-height: 30px; }}
        QScrollBar::handle:vertical:hover {{ background: {t['border_hover']}; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    """


def status_style(kind: str) -> str:
    """状态文字样式：不套 pill 边框（避免像按钮），用彩色状态点/文字表达。

    规则（muse 视觉审查修正版：保留绿/红两个功能色，其余黑白灰）：
    - ok    绿色 ● 前缀 + 亮字
    - busy  灰白 ◐ 前缀
    - warn  中灰 ▲ 前缀
    - error 红色 ✕ 前缀 + 亮字（错误文字红，不用整行反白）
    - info  暗灰 ○ 前缀
    实际状态文本由调用方拼符号，这里只给颜色/字重。
    """
    m = {
        "ok":    f"color: {THEME['success']}; font-weight: 700;",
        "busy":  f"color: {THEME['border_active']}; font-weight: 600;",
        "warn":  f"color: {THEME['muted']}; font-weight: 400;",
        "error": f"color: {THEME['danger']}; font-weight: 700;",
        "info":  f"color: {THEME['dim']}; font-weight: 400;",
    }
    return m.get(kind, m["info"])


def log_color(level: str) -> str:
    """日志行颜色（muse 修正版）：ERROR 红、WARNING 黄、INFO 灰，
    让用户扫日志时能一眼抓到异常，其余保持黑白。"""
    if level == "ERROR":
        return THEME["danger"]
    if level == "WARNING":
        return THEME["warning"]
    return THEME["muted"]
