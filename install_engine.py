import os
import sys
import hashlib
import shutil
import subprocess
import threading
import time
from collections import deque


def _noop(*args, **kwargs):
    pass


# GPU 型号 → 整合包文件名映射
# 两种整合包均在同一个魔搭仓库 FlowerCry/gpt-sovits-7z-pacakges 中
# size_bytes 为魔搭仓库标注的精确文件大小，用于下载进度与 ETA 计算
GPU_PACKAGES = {
    "nvidia50": {
        "file": "GPT-SoVITS-v2pro-20250604-nvidia50.7z",
        "label": "NVIDIA 50 系显卡 (RTX 5070/5080/5090 等)",
        "size_bytes": 9499785293,   # 8.84 GB
    },
    "general": {
        "file": "GPT-SoVITS-v2pro-20250604.7z",
        "label": "其他显卡 (NVIDIA RTX 30/40 系、AMD 等)",
        "size_bytes": 8792863048,   # 8.19 GB
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


class DownloadProgressPoller:
    """后台轮询缓存目录大小，估算下载进度"""

    def __init__(self, cache_dir, progress_cb, log_cb=None, stage_base=0.0, stage_weight=0.0, expected_bytes=None):
        self.cache_dir = cache_dir
        self.progress_cb = progress_cb
        self.log_cb = log_cb or (lambda m: None)
        self.stage_base = stage_base
        self.stage_weight = stage_weight
        self.expected_bytes = expected_bytes
        self.expected_gb = self.expected_bytes / (1024 * 1024 * 1024)
        self._stop = False
        self._thread = None
        self._last_size = 0
        self._last_time = 0
        self._start_time = 0
        # 滑动窗口采样队列：最近 20 秒的 (timestamp, size)，用于计算平滑速度
        # 比累计平均更准确反映当前速度，比瞬时速度更平滑
        self._samples = deque(maxlen=20)

    def start(self):
        self._stop = False
        self._start_time = time.time()
        self._last_time = self._start_time
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop = True
        if self._thread:
            self._thread.join(timeout=2)

    def _loop(self):
        while not self._stop:
            size = _get_dir_size(self.cache_dir)
            now = time.time()
            elapsed = now - self._start_time

            # 记录采样点到滑动窗口（每秒一个点，保留最近 20 秒）
            self._samples.append((now, size))

            # 计算百分比（上限 95%，留余量给完成确认）
            pct = min(size / self.expected_bytes, 0.95)
            if self.progress_cb and self.stage_weight > 0:
                overall = self.stage_base + pct * self.stage_weight
                self.progress_cb(overall)

            # 每 5 秒打印一次下载速度和剩余时间
            if now - self._last_time >= 5:
                size_gb = size / (1024 * 1024 * 1024)
                remaining_bytes = max(self.expected_bytes - size, 0)
                remaining_gb = remaining_bytes / (1024 * 1024 * 1024)

                # 瞬时速度（最近 5 秒），仅用于显示当前下载速度
                inst_speed = (size - self._last_size) / max(now - self._last_time, 0.1)
                inst_speed_mb = inst_speed / (1024 * 1024)

                # 滑动窗口平均速度（最近 20 秒），用于 ETA 计算
                # 取窗口首尾的差值除以时间差，既平滑又反映当前实际速度
                # 速度骤降时窗口会在 20 秒内逐步反映新速度，不会像累计平均那样被前期高速永远拉高
                if len(self._samples) >= 2:
                    oldest_time, oldest_size = self._samples[0]
                    window_sec = now - oldest_time
                    window_bytes = size - oldest_size
                    smooth_speed = window_bytes / max(window_sec, 0.1)
                else:
                    smooth_speed = inst_speed
                smooth_speed_mb = smooth_speed / (1024 * 1024)

                if smooth_speed_mb > 0.1 and remaining_bytes > 0:
                    # ETA = 剩余字节 / 滑动窗口速度
                    eta_sec = remaining_bytes / smooth_speed
                    # 动态单位：<60秒显秒，<1小时显分钟，否则显小时
                    if eta_sec < 60:
                        eta_str = f"{eta_sec:.0f} 秒"
                    elif eta_sec < 3600:
                        eta_min = eta_sec / 60
                        eta_str = f"{eta_min:.1f} 分钟"
                    else:
                        eta_hour = eta_sec / 3600
                        eta_str = f"{eta_hour:.1f} 小时"
                    self.log_cb(
                        f"已下载 {size_gb:.2f}GB / {self.expected_gb:.2f}GB | "
                        f"速度 {inst_speed_mb:.1f}MB/s | 剩余 {remaining_gb:.2f}GB | "
                        f"预计还需 {eta_str}"
                    )
                elif remaining_bytes == 0:
                    self.log_cb(f"已下载 {size_gb:.2f}GB / {self.expected_gb:.2f}GB | 即将完成...")
                else:
                    self.log_cb(f"已下载 {size_gb:.2f}GB / {self.expected_gb:.2f}GB | 剩余 {remaining_gb:.2f}GB")
                self._last_size = size
                self._last_time = now

            time.sleep(1)


def install_and_import(package, log_cb=None):
    log = log_cb or (lambda m: print(m))
    try:
        __import__(package)
    except ImportError:
        log(f"[状态] 正在安装依赖 {package}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", package, "-i", "https://mirrors.aliyun.com/pypi/simple/"])


# 整合包预期 SHA256。留空则跳过校验（首次安装时建议先留空，安装成功后
# 用 --record-hash 模式打印实际哈希，再填回此处，避免下次下载损坏导致玄学失败）。
EXPECTED_SHA256 = ""

# 安装阶段定义（阶段名, 权重），用于进度条计算
STAGES = [
    ("环境准备", 0.05),      # 检查/安装 modelscope
    ("下载整合包", 0.45),    # 从 modelscope 拉取 7z
    ("校验完整性", 0.05),    # SHA256
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
    try:
        import requests  # 延迟导入：避免 venv 未预装 requests 时模块加载即崩溃
        r = requests.get(url, stream=True, timeout=15)
        r.raise_for_status()
        with open(target_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        log("[状态] 解压工具获取成功！")
    except Exception as e:
        log(f"[错误] 无法从官方下载 7z 解压工具: {str(e)}")
        raise


def _progress_for_stages(idx):
    """计算第 idx 阶段（0-based）开始时的累计进度（0-1）"""
    return sum(w for _, w in STAGES[:idx])


def _weight_for_stage(idx):
    """获取第 idx 阶段的权重"""
    return STAGES[idx][1]


def install(progress_cb=None, log_cb=None, state_cb=None, gpu_type="nvidia50"):
    """
    执行完整安装流程，供 launcher 调用。
    参数:
        progress_cb: callback(p: float)  整体进度 0.0~1.0
        log_cb:      callback(msg: str)  状态日志文本
        state_cb:    callback(stage: str) 当前阶段名（STAGES 中的名称）
        gpu_type:    str  显卡类型，"nvidia50" 或 "general"，决定下载哪个整合包
    返回: (success: bool, message: str)
    """
    progress_cb = progress_cb or _noop
    log_cb = log_cb or (lambda m: print(m))
    state_cb = state_cb or _noop

    # 根据显卡型号选择对应的整合包文件
    gpu_pkg = GPU_PACKAGES.get(gpu_type, GPU_PACKAGES["nvidia50"])
    target_file = gpu_pkg["file"]

    try:
        # ===== 阶段 0: 环境准备（安装 modelscope） =====
        state_cb(STAGES[0][0])
        log_cb("===================================================")
        log_cb("               MamboTTS 引擎一键安装程序")
        log_cb("===================================================")
        install_and_import("modelscope", log_cb)
        from modelscope import snapshot_download
        progress_cb(_progress_for_stages(1))  # 阶段0结束 = 阶段1开始

        # ===== 阶段 1: 下载整合包 =====
        state_cb(STAGES[1][0])
        repo_id = "FlowerCry/gpt-sovits-7z-pacakges"

        current_dir = os.path.dirname(os.path.abspath(__file__))
        target_dir = os.path.join(current_dir, "engine_temp")
        extract_dir = os.path.join(current_dir, "GPT-SoVITS")
        tool_path = os.path.join(current_dir, "7zr.exe")

        log_cb(f"[状态] 已选择显卡类型: {gpu_pkg['label']}")
        log_cb(f"[状态] 开始通过魔搭社区极速通道下载 GPT-SoVITS 整合包: {target_file}")
        log_cb(f"[提示] 文件大小 {gpu_pkg['size_bytes'] / (1024**3):.2f}GB，国内镜像源速度通常较快，请耐心等待...")

        # modelscope snapshot_download 不提供字节级进度回调
        # 用一个后台线程轮询缓存目录大小，估算下载进度
        # 使用 GPU_PACKAGES 中记录的精确文件大小
        poller = DownloadProgressPoller(
            cache_dir=target_dir,
            progress_cb=progress_cb,
            log_cb=log_cb,
            stage_base=_progress_for_stages(1),
            stage_weight=_weight_for_stage(1),
            expected_bytes=gpu_pkg["size_bytes"],
        )
        poller.start()
        try:
            download_path = snapshot_download(
                repo_id,
                allow_file_pattern=target_file,
                cache_dir=target_dir
            )
        finally:
            poller.stop()
        log_cb("[状态] 整合包下载完成。")
        progress_cb(_progress_for_stages(2))  # 阶段1结束

        # 定位下载的 7z 文件
        src_7z = None
        for root, dirs, files in os.walk(download_path):
            if target_file in files:
                src_7z = os.path.join(root, target_file)
                break

        if not src_7z or not os.path.exists(src_7z):
            return False, "未找到下载的整合包文件，请重试！"

        # ===== 阶段 2: 校验完整性 =====
        state_cb(STAGES[2][0])
        if EXPECTED_SHA256:
            log_cb("[状态] 正在校验文件完整性 (SHA256)...")
            actual = compute_sha256(
                src_7z,
                progress_cb=progress_cb,
                stage_base=_progress_for_stages(2),
                stage_weight=_weight_for_stage(2),
            )
            if actual.lower() != EXPECTED_SHA256.lower():
                log_cb("[错误] 文件校验失败！")
                log_cb(f"  期望: {EXPECTED_SHA256}")
                log_cb(f"  实际: {actual}")
                log_cb("文件可能下载不完整，已自动删除缓存，请重新运行安装程序。")
                try:
                    os.remove(src_7z)
                except OSError:
                    pass
                return False, "文件校验失败，缓存已清理，请重新运行。"
            log_cb("[状态] 文件校验通过 ✓")
        else:
            log_cb("[状态] 未配置 EXPECTED_SHA256，跳过完整性校验。")
            log_cb("[提示] 安装成功后，建议运行 `python install_engine.py --record-hash` 获取哈希值，")
            log_cb("[提示] 并填回 install_engine.py 顶部的 EXPECTED_SHA256 常量，以启用下载校验。")
        progress_cb(_progress_for_stages(3))  # 阶段2结束

        # ===== 阶段 3: 解压整合包 =====
        state_cb(STAGES[3][0])
        if not os.path.exists(tool_path):
            download_7z_tool(tool_path, log_cb)

        log_cb(f"[状态] 正在使用 7-Zip 解压整合包到: {extract_dir} ...")
        log_cb("[提示] 解压大文件约需要 1-2 分钟，请不要关闭窗口...")

        # 7zr 不支持进度回调，用后台线程轮询解压目录增长，避免进度条假死
        src_size = os.path.getsize(src_7z)
        extract_stop = threading.Event()
        extract_base = _progress_for_stages(3)
        extract_weight = _weight_for_stage(3)

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
                time.sleep(2)

        extract_thread = threading.Thread(target=_poll_extract, daemon=True)
        extract_thread.start()
        try:
            # 加 timeout（30分钟）防止 7z 卡死导致无限阻塞
            subprocess.check_call(
                [tool_path, "x", src_7z, f"-o{extract_dir}", "-y"],
                timeout=1800,
            )
        except subprocess.TimeoutExpired:
            log_cb("[错误] 解压超时（30分钟），可能压缩包损坏或磁盘读写异常。")
            return False, "解压超时，请检查磁盘空间和压缩包完整性后重试。"
        finally:
            extract_stop.set()
            extract_thread.join(timeout=2)
        log_cb("[状态] 解压完成。")
        progress_cb(_progress_for_stages(4))  # 阶段3结束

        # ===== 阶段 4: 收尾配置 =====
        state_cb(STAGES[4][0])
        log_cb("[状态] 正在清理临时文件...")
        if os.path.exists(target_dir):
            shutil.rmtree(target_dir)

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
        api_bat_content = (
            "@echo off\n"
            "title GPT-SoVITS Local API Server\n"
            "cd /d \"%~dp0\"\n"
            "echo Starting GPT-SoVITS API on http://127.0.0.1:9880 ...\n"
            "runtime\\python.exe api.py -a 127.0.0.1 -p 9880\n"
            "pause\n"
        )
        with open(os.path.join(extract_dir, "go-api-mambo.bat"), "w", encoding="utf-8") as f:
            f.write(api_bat_content)

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
    # --record-hash 模式：打印所有已下载整合包的 SHA256
    if "--record-hash" in sys.argv:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        target_dir = os.path.join(current_dir, "engine_temp")
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
