"""config.json 读写（GUI 无关，可独立测试）。

职责：默认值合并、类型容错、原子写入。
GUI 层负责从控件取值组成 dict 再调用 save()。
"""
import json
import os

DEFAULTS = {
    "api_url": "http://127.0.0.1:9880",
    "speed": 1.0,
    "output_dir": "",
    "name": "",
    "theme": "dark",
}


def load(config_path: str, warn_cb=None) -> dict:
    """读取配置并合并默认值；文件缺失/损坏时静默回退默认值。
    warn_cb: 可选回调 warn_cb(message)，GUI 用它把「配置损坏」显示到日志面板。"""

    def _warn(msg):
        print(f"[Config] {msg}")
        if warn_cb:
            try:
                warn_cb(msg)
            except Exception:
                pass

    data = {}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            data = raw
    except FileNotFoundError:
        pass
    except Exception as e:
        _warn(f"读取配置失败，使用默认值: {e}")

    merged = dict(DEFAULTS)
    for k in DEFAULTS:
        if k in data:
            merged[k] = data[k]

    # 类型容错：speed 必须能转 float，api_url 必须是非空字符串
    try:
        merged["speed"] = float(merged["speed"])
    except (TypeError, ValueError):
        merged["speed"] = DEFAULTS["speed"]
    if not isinstance(merged["api_url"], str) or not merged["api_url"].strip():
        merged["api_url"] = DEFAULTS["api_url"]
    if not isinstance(merged["output_dir"], str):
        merged["output_dir"] = ""
    if not isinstance(merged["name"], str):
        merged["name"] = ""
    # 主题白名单
    if merged["theme"] not in ("dark", "light"):
        merged["theme"] = "dark"
    # 向后兼容：v1.1.x 的旧配置只有 output_file（完整路径），取其目录
    if not merged["output_dir"] and isinstance(data.get("output_file"), str):
        legacy_dir = os.path.dirname(data["output_file"])
        if legacy_dir and os.path.isdir(legacy_dir):
            merged["output_dir"] = legacy_dir
    return merged


def save(config_path: str, data: dict) -> None:
    """原子写入：先写临时文件再 os.replace，避免中途崩溃损坏配置。"""
    theme = data.get("theme", DEFAULTS["theme"])
    if theme not in ("dark", "light"):
        theme = "dark"
    payload = {
        "api_url": str(data.get("api_url", DEFAULTS["api_url"])),
        "speed": data.get("speed", DEFAULTS["speed"]),
        "output_dir": str(data.get("output_dir", "")),
        "name": str(data.get("name", "")),
        "theme": theme,
    }
    tmp_path = config_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, config_path)
