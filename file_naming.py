"""输出文件命名与路径工具（从 app.py 抽出，GUI 无关，可独立测试）。"""
import os

# Windows 文件名非法字符（含换行/制表等控制空白）
_INVALID_CHARS = '<>:"/\\|?*\n\r\t'

DEFAULT_BASENAME = "mambo_output"


# Windows 保留设备名：命中会生成非法文件路径（如 CON.wav 指向控制台设备）
_RESERVED = {
    "CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def sanitize_stem(name: str) -> str:
    """清理文件名主干：去非法字符、去首尾点/空格、规避保留设备名；
    全空则返回默认名。"""
    stem = (name or "").strip()
    for ch in _INVALID_CHARS:
        stem = stem.replace(ch, "")
    stem = stem.strip(". ")
    # 去掉扩展名残留后的主干如果是保留名，前缀加下划线规避
    stem_head = stem.split(".")[0].upper()
    if stem_head in _RESERVED:
        stem = "_" + stem
    if not stem:
        stem = DEFAULT_BASENAME
    return stem


def filename_from_text(text: str, max_prefix: int = 20) -> str:
    """默认文件名：取文案前 max_prefix 字（已清理非法字符）+ .wav。"""
    return f"{sanitize_stem(text[:max_prefix])}.wav"


# 常见的非 WAV 音频扩展名：用户填 "配乐.mp3" 时意图是文件名主干为 "配乐"
_OTHER_AUDIO_EXTS = (".mp3", ".flac", ".ogg", ".m4a", ".aac", ".wma", ".opus")


def ensure_wav_suffix(name: str) -> str:
    """补全 .wav 后缀：先剥离其他常见音频扩展名（如 foo.mp3 → foo.wav），
    避免生成 foo.mp3.wav 这类怪异双后缀。"""
    stem = name
    for ext in _OTHER_AUDIO_EXTS:
        if stem.lower().endswith(ext):
            stem = stem[: -len(ext)]
            break
    if stem.lower().endswith(".wav"):
        return stem
    return f"{stem}.wav"


def unique_path(path: str) -> str:
    """路径已存在时追加 _1/_2... 直到唯一，防止覆盖历史成品。"""
    if not os.path.exists(path):
        return path
    dir_name, file_name = os.path.split(path)
    base_name, ext = os.path.splitext(file_name)
    counter = 1
    while True:
        candidate = os.path.join(dir_name, f"{base_name}_{counter}{ext}")
        if not os.path.exists(candidate):
            return candidate
        counter += 1


def resolve_output_dir(path_input_text: str, saved_dir: str) -> str:
    """确定本次合成输出目录：路径框目录 > 上次保存目录 > 桌面；目录失效回退桌面。"""
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    for cand in (os.path.dirname(path_input_text.strip()), saved_dir, desktop):
        if cand and os.path.isdir(cand):
            return cand
    return desktop
