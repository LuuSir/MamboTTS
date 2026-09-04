import os
import sys
import hashlib
import shutil
import subprocess
import threading
import time

from engine_contract import DEFAULT_REF_TEXT


def _noop(*args, **kwargs):
    pass


def _false():
    return False


# GPU 型号 → 整合包文件名映射
# 两种整合包（约 8.2GB/8.23GB）由 GPT-SoVITS 官方 release（RVC-Boss 20250606v2pro）
# 提供四个网络直链源：ModelScope(FlowerCry) ×2 通道 + HuggingFace(lj1995) + hf-mirror。
# size_bytes/sha256 取自 ModelScope 仓库 API（2025-06 实测）——这四个源内容一致，
# 之前 nvidia50 的 size 曾误记 9499785293，导致下载完成后被大小校验误判删除、永远装不上。
GPU_PACKAGES = {
    "nvidia50": {
        "file": "GPT-SoVITS-v2pro-20250604-nvidia50.7z",
        "label": "NVIDIA 50 系显卡 (RTX 5070/5080/5090 等)",
        "size_bytes": 8835144925,   # 8.23 GB（权威：ModelScope repo API）
        "sha256": "97b4edcd451c42357db7e26e6c1c877ca5d85144fe97beaff6d7005d35bee008",
    },
    "general": {
        "file": "GPT-SoVITS-v2pro-20250604.7z",
        "label": "其他显卡 (NVIDIA RTX 30/40 系等)",
        "size_bytes": 8185086602,   # 8.19 GB（权威：ModelScope repo API）
        "sha256": "bd60d0796553ff05d8568136e199c13e0dc22ebe2ed24273134e34ed6f215cd6",
    },
}


def _get_dir_size(path):
    """递归计算目录总大小（字节）"""
    if not os.path.exists(path):
        return 0
    total = 0
    for root, dirs, files in os.walk(path):
        for f in files:
            try:
                fp = os.path.join(root, f)
                if not os.path.islink(fp):
                    total += os.path.getsize(fp)
            except OSError:
                pass
    return total


# ============================================================
# 多源下载：自动测速选最快源 + Range 断点续传 + 失败自动换源
#
# 背景（issue #3）：魔搭单源下载在国内部分网络环境下会失败/极慢，
# 用户被迫手改脚本换 hf-mirror。现在安装器自动对所有候选源测速，
# 谁快用谁；一个源中途断了自动换下一个源续传（.part 文件不浪费）。
# ============================================================

# 候选直链源（全部实测支持 Range/206 断点续传）：
# 来自 GPT-SoVITS 官方 release 20250606v2pro 的四个网络源 + ModelScope API 备用通道。
# 顺序仅作为测速全失败时的兜底次序：国内源在前。
MODELSCOPE_REPO = "FlowerCry/gpt-sovits-7z-pacakges"
HF_PKG_REPO = "lj1995/GPT-SoVITS-windows-package"
BUILTIN_SOURCES = [
    "https://www.modelscope.cn/models/" + MODELSCOPE_REPO + "/resolve/master/{file}",
    "https://modelscope.cn/api/v1/models/" + MODELSCOPE_REPO + "/repo?Revision=master&FilePath={file}",
    "https://hf-mirror.com/" + HF_PKG_REPO + "/resolve/main/{file}?download=true",
    "https://huggingface.co/" + HF_PKG_REPO + "/resolve/main/{file}?download=true",
]

_PROBE_BYTES = 2 * 1024 * 1024      # 每源测速采样 2MB
_PROBE_TIMEOUT = (6, 15)


def load_mirror_urls(file_name, base_dir):
    """读取 mirrors.txt（与 install_engine.py 同目录）中的自定义镜像。

    每行一个 URL 模板，{file} 会替换为整合包文件名，# 开头为注释。
    用途：魔搭官方通道整体失效时，用户可自行添加可用镜像自救，
    无需等待客户端发版。"""
    path = os.path.join(base_dir, "mirrors.txt")
    urls = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                urls.append(line.replace("{file}", file_name))
    except FileNotFoundError:
        pass
    except OSError:
        pass
    return urls


def build_source_urls(gpu_pkg, base_dir):
    """候选直链列表：用户自定义镜像优先（往往是用户确认可用的源），
    随后是内置 ModelScope 双通道。实际顺序稍后由测速重排。"""
    fname = gpu_pkg["file"]
    urls = [u.replace("{file}", fname) for u in load_mirror_urls(fname, base_dir)]
    for tpl in BUILTIN_SOURCES:
        u = tpl.replace("{file}", fname)
        if u not in urls:
            urls.append(u)
    return urls


def probe_source_speed(url):
    """单源测速：Range 拉取前 2MB 计时，返回字节/秒；失败返回 None。"""
    import requests  # 延迟导入：与 download_7z_tool 同理
    try:
        t0 = time.time()
        with requests.get(url, headers={"Range": f"bytes=0-{_PROBE_BYTES - 1}"},
                          stream=True, timeout=_PROBE_TIMEOUT,
                          proxies={"http": None, "https": None}) as r:
            if r.status_code not in (200, 206):
                return None
            got = 0
            for chunk in r.iter_content(chunk_size=65536):
                got += len(chunk)
                if got >= _PROBE_BYTES:
                    break
        dt = time.time() - t0
        return got / dt if dt > 0 else None
    except Exception:
        return None


def benchmark_sources(urls, log_cb):
    """并发测速，返回按速度降序的 URL 列表。

    全部失败时保留原始顺序（测速失败可能只是瞬时抖动，下载阶段再给机会），
    并输出每源成绩，方便用户判断网络状况。"""
    if not urls:
        return []
    results = {}

    def _probe(i, u):
        results[i] = probe_source_speed(u)

    threads = [threading.Thread(target=_probe, args=(i, u), daemon=True)
               for i, u in enumerate(urls)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=40)

    scored = [(i, results.get(i)) for i in range(len(urls))]
    ok = sorted(((bps, i) for i, bps in scored if bps), reverse=True)
    dead = [urls[i] for i, bps in scored if not bps]
    for rank, (bps, i) in enumerate(ok, 1):
        log_cb(f"[测速] 第{rank}名 ≈{bps / (1024 * 1024):.1f}MB/s  {urls[i][:88]}")
    for u in dead:
        log_cb(f"[测速] 不可达，暂排除：{u[:88]}")
    if not ok:
        log_cb("[警告] 所有源测速失败（网络抖动或全被墙？），将按默认顺序直接尝试下载...")
        return urls
    return [urls[i] for _, i in ok] + dead


def download_file_resumable(url, dest_path, expected_bytes, progress_cb, log_cb,
                            cancel_cb, stage_base=0.0, stage_weight=0.0):
    """流式下载单源：.part 临时文件 + Range 断点续传 + 每块检查取消。

    换源续传安全策略（防止"换网络/换源后续传卡死"）：
    1. 每次对目标源发起续传前，都先发一个 0 字节 Range 探测头（bytes=0-0），
       确认该源支持 Range 且识别我们的偏移量，才带 Range 续传；
    2. 探测失败 / 返回 200 / 返回 416 / 中途异常——一律把 .part 降级为
       "从头重下"（清掉 .part 重新下载），而不是带着旧偏移反复撞墙。

    返回 True=文件完整；False=失败（.part 保留，换源或下次续传）。"""
    import requests
    part = dest_path + ".part"
    try:
        # .part 可能是目录/被占用/权限异常——一律按无断点从头处理，绝不崩 install()
        offset = os.path.getsize(part) if os.path.exists(part) else 0
    except OSError:
        offset = 0
    if offset >= expected_bytes:
        try:
            os.replace(part, dest_path)
        except OSError:
            return False
        return True

    # --- 服务端 Range 能力探测（仅当已有断点时） ---
    # 目的：换网络/换源后，旧偏移对当前源可能无效（源端内容变了/缓存清了），
    # 若直接带 Range 请求，源可能回 416/200，白等一次。先探测一次最稳。
    resumed = False
    if offset > 0:
        log_cb(f"[状态] 检测到断点 {offset / (1024 ** 3):.2f}GB，探测当前源是否支持续传...")
        try:
            probe = requests.get(url, headers={"Range": "bytes=0-0"},
                                 timeout=(10, 15),
                                 proxies={"http": None, "https": None})
            if probe.status_code == 206:
                content_range = probe.headers.get("Content-Range", "")
                # 形如 "bytes 0-0/9499785293"：尾数 = 服务端当前文件总长。
                total = content_range.rsplit("/", 1)[-1].strip()
                server_total = int(total) if total.isdigit() else None
                if server_total is not None and server_total < offset:
                    # 服务端文件比本地断点还短：旧断点已失效（源被换包/清缓存），从头下
                    log_cb("[警告] 服务端内容已变化（比本地断点短），旧断点失效，从头下载...")
                    offset = 0
                else:
                    resumed = True  # 服务端认可续传
            else:
                # 服务端忽略 Range / 不支持（200）或明确拒绝（416）→ 从头下
                log_cb("[提示] 该源不支持断点续传，将从头下载...")
                offset = 0
        except Exception as e:
            log_cb(f"[提示] 续传探测失败（{type(e).__name__}），将从头下载：{str(e)[:80]}")
            offset = 0

    headers = {"Range": f"bytes={offset}-"} if offset > 0 else {}
    mode = "ab" if offset > 0 else "wb"
    try:
        # 读超时 30s：网络半开时不再让进度条死等 60s 才报错，
        # 30s 内无任何数据即判定源卡死，换下一个源
        with requests.get(url, headers=headers, stream=True, timeout=(15, 30),
                          proxies={"http": None, "https": None}) as r:
            if offset > 0 and r.status_code == 206:
                pass  # 服务端确认断点续传
            elif offset > 0 and r.status_code == 200:
                # 探测通过但实际下载时忽略了 Range（代理层）→ 从头重写
                log_cb("[提示] 下载时源忽略了 Range，从头重新下载...")
                offset = 0
                mode = "wb"
            elif r.status_code not in (200, 206):
                log_cb(f"[警告] 源返回 HTTP {r.status_code}，换源：{url[:64]}")
                return False
            with open(part, mode) as f:
                if offset > 0:
                    f.seek(offset)
                    off_str = (f"{offset / (1024 ** 3):.2f}GB" if offset >= 1024 ** 3
                               else f"{offset / (1024 ** 2):.0f}MB")
                    log_cb(f"[状态] 断点续传：从 {off_str} 处继续")
                else:
                    log_cb("[状态] 开始下载...")
                last_log = time.time()
                last_log_bytes = offset
                while True:
                    chunk = r.raw.read(1024 * 1024, decode_content=True)
                    if not chunk:
                        break
                    if cancel_cb():
                        return False
                    f.write(chunk)
                    offset += len(chunk)
                    if progress_cb and stage_weight > 0:
                        progress_cb(stage_base + min(offset / expected_bytes, 0.95) * stage_weight)
                    now = time.time()
                    if now - last_log >= 5:
                        mbps = (offset - last_log_bytes) / (now - last_log) / (1024 * 1024)
                        remain = max(expected_bytes - offset, 0) / (1024 ** 3)
                        log_cb(f"[状态] 已下载 {offset / (1024 ** 3):.2f}GB / "
                               f"{expected_bytes / (1024 ** 3):.2f}GB | "
                               f"速度 {mbps:.1f}MB/s | 剩余 {remain:.2f}GB")
                        last_log = now
                        last_log_bytes = offset
        if offset >= expected_bytes:
            os.replace(part, dest_path)
            return True
        log_cb(f"[警告] 该源中途截断（{offset}/{expected_bytes} 字节），尝试下一个源续传...")
        return False
    except Exception as e:
        log_cb(f"[警告] 源下载异常（{type(e).__name__}），尝试下一个源：{str(e)[:100]}")
        return False


# 安装阶段定义（阶段名, 权重），用于进度条计算
# 注：不再需要"环境准备/安装 modelscope"阶段——改用 requests 直连多源下载
STAGES = [
    ("下载整合包", 0.50),    # 多源测速 + Range 续传
    ("校验完整性", 0.05),    # 大小 + SHA256
    ("解压整合包", 0.35),    # 7zr 解压
    ("收尾配置", 0.10),      # 目录整理 + 启动脚本
]


def compute_sha256(file_path, progress_cb=None, stage_base=0.0, stage_weight=0.0):
    """分块计算大文件的 SHA256，支持进度回调"""
    h = hashlib.sha256()
    file_size = os.path.getsize(file_path)
    read = 0
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(8 * 1024 * 1024)  # 8MB 块
            if not chunk:
                break
            h.update(chunk)
            read += len(chunk)
            if progress_cb and file_size > 0 and stage_weight > 0:
                pct = stage_base + (read / file_size) * stage_weight
                progress_cb(pct)
    return h.hexdigest()


def download_7z_tool(target_path, log_cb=None):
    log = log_cb or (lambda m: print(m))
    url = "https://www.7-zip.org/a/7zr.exe"
    log("[状态] 正在获取 7z 解压工具 (约 500KB)...")
    import requests  # 延迟导入：避免 venv 未预装 requests 时模块加载即崩溃

    last_err = None
    # 官方站点对国内网络偶发抖动，重试 3 次；仍失败则给出明确的手动放置指引
    for attempt in range(1, 4):
        try:
            r = requests.get(url, stream=True, timeout=20,
                             proxies={"http": None, "https": None})
            r.raise_for_status()
            with open(target_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            # 基本大小校验：防止把错误页存成 exe（7zr 正常约 500KB+）
            if os.path.getsize(target_path) < 100 * 1024:
                raise OSError(f"下载内容过小（{os.path.getsize(target_path)} 字节），疑似错误页")
            log("[状态] 解压工具获取成功！")
            return
        except Exception as e:
            last_err = e
            log(f"[提示] 第 {attempt} 次获取失败: {e}")
            try:
                os.remove(target_path)
            except OSError:
                pass
            time.sleep(2)
    msg = (f"无法自动下载 7z 解压工具（{last_err}）。\n"
           f"请手动下载 https://www.7-zip.org/a/7zr.exe 并保存到 {target_path}，然后重新运行安装。")
    log(f"[错误] {msg}")
    raise RuntimeError(msg)


def _progress_for_stages(idx):
    """计算第 idx 阶段（0-based）开始时的累计进度（0-1）"""
    return sum(w for _, w in STAGES[:idx])


def _weight_for_stage(idx):
    """获取第 idx 阶段的权重"""
    return STAGES[idx][1]


def install(progress_cb=None, log_cb=None, state_cb=None, gpu_type="nvidia50", cancel_cb=None):
    """
    执行完整安装流程，供 launcher 调用。
    参数:
        progress_cb: callback(p: float)  整体进度 0.0~1.0
        log_cb:      callback(msg: str)  状态日志文本
        state_cb:    callback(stage: str) 当前阶段名（STAGES 中的名称）
        gpu_type:    str  显卡类型，"nvidia50" 或 "general"，决定下载哪个整合包
        cancel_cb:   callback() -> bool  协作式取消检查（阶段边界与解压轮询中检查）
    返回: (success: bool, message: str)
    """
    progress_cb = progress_cb or _noop
    log_cb = log_cb or (lambda m: print(m))
    state_cb = state_cb or _noop
    cancel_cb = cancel_cb or _false

    # 根据显卡型号选择对应的整合包文件
    gpu_pkg = GPU_PACKAGES.get(gpu_type, GPU_PACKAGES["nvidia50"])
    target_file = gpu_pkg["file"]

    try:
        log_cb("===================================================")
        log_cb("               MamboTTS 引擎一键安装程序")
        log_cb("===================================================")

        # ===== 阶段 0: 下载整合包（多源测速选最快 + Range 续传 + 失败换源） =====
        state_cb(STAGES[0][0])

        current_dir = os.path.dirname(os.path.abspath(__file__))
        target_dir = os.path.join(current_dir, "engine_temp")
        extract_dir = os.path.join(current_dir, "GPT-SoVITS")
        tool_path = os.path.join(current_dir, "7zr.exe")
        os.makedirs(target_dir, exist_ok=True)

        # 磁盘空间预检：整包下载 + 解压（约 2.5 倍）+ 安全余量，
        # 不等 9GB 下完才发现盘满；已有缓存/半截 .part 不重复计入需求量
        try:
            free_bytes = shutil.disk_usage(current_dir).free
            existing_cache = _get_dir_size(target_dir)
            need_bytes = max(0, int(gpu_pkg["size_bytes"] * 3.6) - existing_cache)
            if free_bytes < need_bytes:
                return False, (
                    f"磁盘剩余空间不足：还需约 {need_bytes / (1024**3):.0f}GB"
                    f"（整合包 {gpu_pkg['size_bytes'] / (1024**3):.1f}GB + 解压产物，已扣除现有缓存"
                    f" {existing_cache / (1024**3):.1f}GB），当前仅剩 {free_bytes / (1024**3):.1f}GB。\n"
                    f"请清理磁盘，或把 MamboTTS 移到空间充足的磁盘后重试。"
                )
        except OSError:
            pass  # 极端环境拿不到磁盘信息时不拦截主流程

        if cancel_cb():
            return False, "下载尚未开始。"

        log_cb(f"[状态] 已选择显卡类型: {gpu_pkg['label']}")
        src_7z = os.path.join(target_dir, target_file)

        # 完整缓存已在（上次成功中断于解压前、或用户手动放置）：跳过下载
        if os.path.exists(src_7z) and os.path.getsize(src_7z) == gpu_pkg["size_bytes"]:
            log_cb("[状态] 检测到完整整合包缓存，跳过下载。")
        else:
            urls = build_source_urls(gpu_pkg, current_dir)
            log_cb(f"[状态] 开始下载 {target_file}（{gpu_pkg['size_bytes'] / (1024**3):.2f}GB），"
                   f"正在对 {len(urls)} 个候选源测速...")
            # 测速期先给一点进度，避免 UI 长时间停在 0% 让人以为卡死
            base0 = _progress_for_stages(0)
            w0 = _weight_for_stage(0)
            progress_cb(base0 + 0.02 * w0)
            ordered = benchmark_sources(urls, log_cb)
            progress_cb(base0 + 0.06 * w0)
            downloaded = False
            part_path = src_7z + ".part"
            # 两轮策略：
            #  第 1 轮：优先尝试断点续传（省流量）——每个源内部会先探测 Range 能力，
            #           源端不认旧断点时自动清 0 从头；源端认但中途断了会保留 .part。
            #  第 2 轮（仅当第 1 轮全部失败且有断点残留时）：说明旧断点已被所有源
            #           拒绝（典型场景：切换了网络/源端清缓存/换包），此时保留 .part
            #           只会让每次重试都白撞一遍 → 清掉断点强制从头下一轮，能下就继续。
            for attempt, force_fresh in enumerate((False, True), 1):
                if downloaded or cancel_cb():
                    break
                if force_fresh:
                    if os.path.exists(part_path):
                        stale = os.path.getsize(part_path)
                        log_cb(f"[警告] 所有源均拒绝旧断点续传（断点 {stale / (1024**3):.2f}GB 已失效，"
                               f"可能切换了网络或源端内容更新），清除断点从头重新下载...")
                        try:
                            os.remove(part_path)
                        except OSError:
                            pass
                    log_cb(f"[状态] 第 2 轮：不携带断点，重新尝试全部源...")
                for url in ordered:
                    if cancel_cb():
                        return False, "下载期间取消（已下载部分保留在 engine_temp，重试自动续传）。"
                    if download_file_resumable(
                            url, src_7z, gpu_pkg["size_bytes"],
                            progress_cb, log_cb, cancel_cb,
                            stage_base=_progress_for_stages(0),
                            stage_weight=_weight_for_stage(0)):
                        downloaded = True
                        break
                    if cancel_cb():
                        return False, "下载期间取消（已下载部分保留在 engine_temp，重试自动续传）。"
                    log_cb("[状态] 当前源失败，自动切换下一个源...")
                if not downloaded and not os.path.exists(part_path):
                    # 没有任何源可连（全网络层失败），第 2 轮清断点无意义，直接跳出
                    break
            if not downloaded:
                return False, (
                    "所有下载源均失败，可任选以下方式自救：\n"
                    "1. 检查网络后直接重试安装——已下载部分自动续传，不浪费流量；\n"
                    f"2. 手动下载 {target_file} 放入 {target_dir}；\n"
                    "3. 若有更快镜像，把 URL 写入 install_engine.py 同目录的 mirrors.txt"
                    "（每行一条，{file} 为文件名占位符）。"
                )
        log_cb("[状态] 整合包下载完成。")
        progress_cb(_progress_for_stages(1))  # 阶段0结束

        # ===== 阶段 1: 校验完整性 =====
        state_cb(STAGES[1][0])
        if cancel_cb():
            return False, "已在下载完成后取消。"

        # 大小一致性硬校验：与记录不符即判定下载损坏/上游换包，
        # 删除缓存要求重下（只警告会让损坏包带着几 GB 的代价进入解压阶段再神秘失败）
        actual_size = os.path.getsize(src_7z)
        if actual_size != gpu_pkg["size_bytes"]:
            log_cb("[错误] 文件大小与记录不符："
                   f"实际 {actual_size / (1024**3):.2f}GB / 期望 {gpu_pkg['size_bytes'] / (1024**3):.2f}GB")
            log_cb("[错误] 已删除损坏缓存，请重新运行安装（将重新下载）。若持续失败，"
                   "可能上游整合包已更新，请到项目页确认新版本客户端。")
            try:
                os.remove(src_7z)
            except OSError:
                pass
            return False, "整合包大小校验失败，缓存已清理，请重试安装。"

        # SHA256 完整性校验：GPU_PACKAGES 内置了从 ModelScope 权威 API 取得的
        # 真实哈希，因此这里始终执行硬校验——下完即验，损坏包绝无机会进入解压。
        expected_sha = gpu_pkg.get("sha256", "")
        log_cb("[状态] 正在计算文件 SHA256...")
        actual = compute_sha256(
            src_7z,
            progress_cb=progress_cb,
            stage_base=_progress_for_stages(1),
            stage_weight=_weight_for_stage(1),
        )
        if expected_sha:
            if actual.lower() != expected_sha.lower():
                log_cb("[错误] 文件校验失败！")
                log_cb(f"  期望: {expected_sha}")
                log_cb(f"  实际: {actual}")
                log_cb("文件可能下载不完整，已自动删除缓存，请重新运行安装程序。")
                try:
                    os.remove(src_7z)
                except OSError:
                    pass
                return False, "文件校验失败，缓存已清理，请重新运行。"
            log_cb("[状态] 文件校验通过 ✓")
        else:
            # 理论上不会走到：GPU_PACKAGES 都带 sha256。留着兜底记录哈希
            log_cb(f"[提示] 本次整合包 SHA256: {actual}（请回填到 GPU_PACKAGES 的 sha256 以启用校验）")
        progress_cb(_progress_for_stages(2))  # 阶段1结束

        # ===== 阶段 2: 解压整合包 =====
        state_cb(STAGES[2][0])
        if cancel_cb():
            return False, "已在校验完成后取消，整合包已缓存，重试可跳过下载。"
        # 已有的 7zr.exe 也要体检：上次下载中断可能留下半截文件或非 PE 内容，
        # 只判存在会跳过下载、然后在解压阶段神秘失败
        if os.path.exists(tool_path):
            try:
                valid = os.path.getsize(tool_path) > 100 * 1024
                if valid:
                    with open(tool_path, "rb") as _f:
                        valid = _f.read(2) == b"MZ"  # PE 可执行文件魔数
                if not valid:
                    log_cb("[警告] 检测到已存在的 7zr.exe 不完整（大小/魔数校验失败），重新获取...")
                    os.remove(tool_path)
            except OSError:
                pass
        if not os.path.exists(tool_path):
            download_7z_tool(tool_path, log_cb)

        log_cb(f"[状态] 正在使用 7-Zip 解压整合包到: {extract_dir} ...")
        log_cb("[提示] 解压大文件约需要 1-2 分钟，请不要关闭窗口...")

        # 7zr 不支持进度回调，用后台线程轮询解压目录增长，避免进度条假死；
        # 同时该线程承担协作式取消：检测到取消请求即终止 7zr 子进程。
        src_size = os.path.getsize(src_7z)
        extract_stop = threading.Event()
        extract_canceled = threading.Event()
        extract_base = _progress_for_stages(2)
        extract_weight = _weight_for_stage(2)
        proc_ref = [None]  # 闭包共享 7zr 进程句柄

        def _poll_extract():
            last_log = 0
            while not extract_stop.is_set():
                size = _get_dir_size(extract_dir)
                # 解压后总大小约为压缩包的 2.5 倍（经验值），用于粗略估算进度
                estimated_total = src_size * 2.5
                pct = min(size / estimated_total, 0.95) if estimated_total > 0 else 0
                if progress_cb and extract_weight > 0:
                    progress_cb(extract_base + pct * extract_weight)
                now = time.time()
                if now - last_log >= 5:
                    size_gb = size / (1024 ** 3)
                    log_cb(f"[状态] 解压中... 已解压约 {size_gb:.2f}GB")
                    last_log = now
                if cancel_cb():
                    extract_canceled.set()
                    if proc_ref[0] is not None:
                        try:
                            proc_ref[0].kill()
                        except OSError:
                            pass
                    break
                time.sleep(2)

        extract_thread = threading.Thread(target=_poll_extract, daemon=True)
        extract_thread.start()
        try:
            # Popen + wait(timeout)：加 timeout（30分钟）防止 7z 卡死导致无限阻塞
            proc = subprocess.Popen(
                [tool_path, "x", src_7z, f"-o{extract_dir}", "-y"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
            )
            proc_ref[0] = proc
            try:
                rc = proc.wait(timeout=1800)
            except subprocess.TimeoutExpired:
                proc.kill()
                log_cb("[错误] 解压超时（30分钟），可能压缩包损坏或磁盘读写异常。")
                return False, "解压超时，请检查磁盘空间和压缩包完整性后重试。"
        finally:
            extract_stop.set()
            extract_thread.join(timeout=2)
        if extract_canceled.is_set():
            return False, ("解压已取消：GPT-SoVITS 目录内为不完整产物。重试安装会继续解压覆盖"
                           "（下载已缓存）；若反复异常，可手动删除 GPT-SoVITS 目录后重试。")
        if rc != 0:
            log_cb(f"[错误] 7zr 解压失败（退出码 {rc}），压缩包可能损坏。")
            return False, (f"解压失败（退出码 {rc}）。可重试安装继续解压；若反复失败，"
                           f"请删除 engine_temp 目录下的 7z 文件与半成品 GPT-SoVITS 目录后重新安装。")
        log_cb("[状态] 解压完成。")
        progress_cb(_progress_for_stages(3))  # 阶段2结束

        # ===== 阶段 3: 收尾配置 =====
        state_cb(STAGES[3][0])
        if cancel_cb():
            return False, "收尾阶段被取消：引擎文件已解压完毕，但启动脚本与完成标记未生成。重新运行安装可快速补完（下载已缓存）。"
        log_cb("[状态] 正在清理临时文件...")
        if os.path.exists(target_dir):
            # 缓存清理失败（文件被杀软/索引器短暂占用）不应中断收尾：
            # GPT-SoVITS 与完成标记已就位，残留缓存下次安装还能复用
            try:
                shutil.rmtree(target_dir)
            except OSError as e:
                log_cb(f"[提示] 临时目录清理失败（不影响安装结果，可稍后手动删除）: {e}")

        # 检查是否有多嵌套一层文件夹，若有则上移
        # 仅当根目录下只有唯一一项且为目录时才扁平化，避免与根目录文件冲突
        entries = os.listdir(extract_dir)
        if len(entries) == 1 and os.path.isdir(os.path.join(extract_dir, entries[0])):
            nested_dir = os.path.join(extract_dir, entries[0])
            log_cb("[状态] 优化文件目录结构...")
            for item in os.listdir(nested_dir):
                shutil.move(os.path.join(nested_dir, item), extract_dir)
            os.rmdir(nested_dir)

        log_cb("[状态] 正在生成本地引擎启动脚本...")
        # 与 run_engine.py 复用同一份路径清单（engine_contract 提供单一来源），
        # 避免模型文件名在两处硬编码漂移；单独运行该脚本参数与主程序完全一致。
        from run_engine import engine_paths
        ep = engine_paths(current_dir)
        api_bat_content = (
            "@echo off\n"
            "title GPT-SoVITS Local API Server\n"
            "cd /d \"%~dp0\"\n"
            "echo Starting GPT-SoVITS API on http://127.0.0.1:9880 ...\n"
            'runtime\\python.exe api.py -a 127.0.0.1 -p 9880 ^\n'
            f'  -s "{ep["sovits"]}" ^\n'
            f'  -g "{ep["gpt"]}" ^\n'
            f'  -dr "{ep["ref_wav"]}" ^\n'
            f'  -dt "{DEFAULT_REF_TEXT}" ^\n'
            '  -dl zh\n'
            "pause\n"
        )
        with open(os.path.join(extract_dir, "go-api-mambo.bat"), "w", encoding="utf-8") as f:
            f.write(api_bat_content)

        # 安装完成标记：is_installed() 用它识别「完整安装」，
        # 避免解压半途中断留下的 api.py+python.exe 被误判为已安装、
        # 之后引擎启动失败又不再进安装流程
        try:
            with open(os.path.join(extract_dir, ".mambo_install_ok"), "w", encoding="utf-8") as f:
                f.write(f"installed_at={time.strftime('%Y-%m-%d %H:%M:%S')}\npackage={target_file}\n")
        except OSError:
            pass  # 标记写失败不致命：is_installed 会走 torch 完整性代理

        progress_cb(1.0)  # 全部完成
        log_cb("===================================================")
        log_cb("🎉 恭喜！GPT-SoVITS 本地 GPU 推理引擎一键安装成功！")
        log_cb("===================================================")
        log_cb(f"安装路径: {extract_dir}")
        log_cb("接下来请启动 MamboTTS 客户端即可开始配音。")
        return True, "安装成功"

    except Exception as e:
        log_cb(f"\n[错误] 安装过程中发生异常: {str(e)}")
        return False, f"安装过程中发生异常: {str(e)}"


def main():
    """独立脚本入口（保留兼容旧 run_installer.bat）"""
    # --record-hash 模式：给手动放入 engine_temp 的整合包计算 SHA256，
    # 便于与 GPU_PACKAGES 里的权威哈希核对（上游换包时用来更新常量）。
    if "--record-hash" in sys.argv:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        target_dir = os.path.join(current_dir, "engine_temp")
        print("[提示] 扫描 engine_temp 中尚存的整合包并打印 SHA256，供与 GPU_PACKAGES 的 sha256 字段核对。")
        found_any = False
        for pkg_info in GPU_PACKAGES.values():
            target_file = pkg_info["file"]
            for root, dirs, files in os.walk(target_dir):
                if target_file in files:
                    fp = os.path.join(root, target_file)
                    print(f"文件: {fp}")
                    print(f"SHA256: {compute_sha256(fp)}")
                    print()
                    found_any = True
                    break
        if not found_any:
            print(f"[错误] 未在 {target_dir} 找到任何整合包文件，请先运行一次正常安装以触发下载。")
        return

    # 解析 --gpu 参数
    gpu_type = "nvidia50"
    for i, arg in enumerate(sys.argv):
        if arg == "--gpu" and i + 1 < len(sys.argv):
            gpu_type = sys.argv[i + 1]
            break

    success, message = install(gpu_type=gpu_type)
    if not success:
        print(f"\n[错误] 安装失败: {message}")
        sys.exit(1)


if __name__ == "__main__":
    main()
