"""合成历史记录持久化（JSON，GUI 无关，可独立测试）。

记录结构：[{record_id, path, text, time, duration}, ...]，最新在前，上限 50 条。
record_id 在落盘与加载间保持一致（往返契约），加载时保留原 id 供
app 侧恢复 _history_seq 继续自增，避免新记录与旧记录 id 冲突。
加载时先过滤"磁盘文件已不存在"的死链，再截断到上限——避免前 N 条全失效
时把后面仍然有效的记录误丢。
"""
import json
import os

MAX_RECORDS = 50


def load(path: str) -> list:
    """读取历史；文件缺失/损坏/结构异常时返回空列表（绝不抛异常阻断启动）"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, OSError):
        return []
    except Exception:
        return []
    if not isinstance(data, list):
        return []

    valid = []
    for r in data:
        if not isinstance(r, dict):
            continue
        p = r.get("path")
        t = r.get("text")
        if not isinstance(p, str) or not isinstance(t, str) or not p:
            continue
        # 磁盘文件已被用户清理：静默丢弃该条（不显示死链）
        if not os.path.exists(p):
            continue
        try:
            duration = float(r.get("duration", 0))
        except (TypeError, ValueError):
            duration = 0.0
        # 保留原始 record_id（若缺失/非法则回退 0，由 app 侧重建序号）
        rid = r.get("record_id")
        if not isinstance(rid, int) or rid < 0:
            rid = 0
        valid.append({
            "record_id": rid,
            "path": p,
            "text": t,
            "time": str(r.get("time", "")),
            "duration": duration,
        })
    return valid[:MAX_RECORDS]


def save(path: str, records: list) -> None:
    """原子写入（tmp + os.replace）；records 按最新在前排列，截断到上限"""
    payload = []
    for r in records[:MAX_RECORDS]:
        payload.append({
            "record_id": r.get("record_id", 0),
            "path": r.get("path", ""),
            "text": r.get("text", ""),
            "time": r.get("time", ""),
            "duration": r.get("duration", 0),
        })
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except OSError:
        # 写失败（磁盘满/权限）不影响功能：历史退化为会话级
        try:
            os.remove(tmp)
        except OSError:
            pass
