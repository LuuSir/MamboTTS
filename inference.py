import os
import requests
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# GPT-SoVITS api.py 的 dict_language 支持的语种，用于客户端侧预校验，
# 避免传入不支持的语种触发服务端 KeyError → HTTP 500（对应上游 B10 防御）
SUPPORTED_LANGS = {
    "zh", "en", "ja", "ko", "yue", "auto", "auto_yue",
    "all_zh", "all_yue", "all_ja", "all_ko",
    "中文", "粤语", "英文", "日文", "韩文",
    "中英混合", "粤英混合", "日英混合", "韩英混合",
    "多语种混合", "多语种混合(粤语)",
}


class TTSClient:
    def __init__(self, api_url="http://127.0.0.1:9880"):
        self.api_url = api_url
        # GUI 日志回调：由 app.py 注入，每条日志都会推送到 GUI 日志面板
        self._log_handler = None
        # 默认参考音频和参考文本
        # 路径相对于 app.py 所在目录
        # ref_text 必须和参考音频内容一字不差
        _base_dir = os.path.dirname(os.path.abspath(__file__))
        self.default_ref_audio = os.path.join(_base_dir, "models", "refer.wav")
        self.default_ref_text = "大家好，欢迎来到我的频道，今天给大家分享一个有趣的内容"

    def set_log_handler(self, handler):
        """注入日志回调，handler 签名为 handler(level: str, message: str)"""
        self._log_handler = handler

    def _log(self, level, message):
        """同时输出到控制台和 GUI 日志面板"""
        getattr(logging, level.lower(), logging.info)(message)
        if self._log_handler:
            try:
                self._log_handler(level, message)
            except Exception:
                # 日志回调自身异常不应影响主流程
                pass

    def is_api_running(self):
        """检查本地 GPT-SoVITS API 服务是否在线"""
        try:
            # 请求 /control 接口检查连接，只要服务有响应（任何 HTTP 状态码），就认为在线
            response = requests.get(f"{self.api_url}/control", timeout=2)
            return response.status_code in [200, 400, 404, 405]
        except requests.RequestException:
            return False

    def generate_speech(self, text, save_path, ref_audio="", prompt_text="", text_lang="zh", prompt_lang="zh", speed=1.0):
        """
        调用 GPT-SoVITS 本地 API 生成语音。
        返回: (success: bool, message: str)
            - 成功时: (True, "语音合成成功，已保存至: xxx")
            - 失败时: (False, "具体的错误原因，用户可读")
        """
        if not save_path:
            return False, "保存路径为空，请选择有效的输出路径。"

        # 写文件前预检：父目录必须存在且可写
        parent_dir = os.path.dirname(save_path) or "."
        if not os.path.exists(parent_dir):
            return False, f"输出目录不存在：{parent_dir}\n请点击「浏览...」重新选择保存路径。"
        if not os.path.isdir(parent_dir):
            return False, f"输出路径不是文件夹：{parent_dir}"
        if not os.access(parent_dir, os.W_OK):
            return False, f"没有写入权限的目录：{parent_dir}\n请选择其他位置，或用管理员身份运行。"

        if not self.is_api_running():
            self._log("WARNING", "GPT-SoVITS API 处于离线状态，进入 Mock（模拟生成）模式。")
            return self._mock_generate(text, save_path)

        # 自动检测语种：如果文本中包含日语平假名或片假名，自动切换为日语合成
        def is_japanese(t):
            for char in t:
                cp = ord(char)
                if 0x3040 <= cp <= 0x309F or 0x30A0 <= cp <= 0x30FF:
                    return True
            return False

        if text_lang == "zh" and is_japanese(text):
            text_lang = "ja"
            self._log("INFO", "自动检测文案为日语，已切换为日语合成 (ja)")

        if prompt_text and prompt_lang == "zh" and is_japanese(prompt_text):
            prompt_lang = "ja"

        # 客户端侧语种预校验：避免传入不支持的语种触发服务端 KeyError → 500
        if text_lang not in SUPPORTED_LANGS:
            return False, f"不支持的文本语种: {text_lang}\n支持的语种: zh/en/ja/ko/yue 等"
        if prompt_lang not in SUPPORTED_LANGS:
            return False, f"不支持的参考音频语种: {prompt_lang}\n支持的语种: zh/en/ja/ko/yue 等"

        # GPT-SoVITS 旧版 api.py 参数格式
        # 字段: text_language / prompt_language / speed / ref_audio_path / prompt_text
        # cut_punc: 按标点切分长文本，绕过单次合成长度限制（约208字）
        params = {
            "text": text,
            "text_language": text_lang,
            "speed": float(speed),
            "cut_punc": "，。？！；：、…,.;?!",
        }

        # 参考音频：优先用调用方传入的，否则用默认 refer.wav
        effective_ref_audio = ref_audio if ref_audio else self.default_ref_audio
        effective_ref_text = prompt_text if prompt_text else self.default_ref_text
        if effective_ref_audio and effective_ref_text:
            # GPT-SoVITS api.py 的 GET / 端点期望参数名为 refer_wav_path（非 ref_audio_path）
            params["refer_wav_path"] = effective_ref_audio
            params["prompt_text"] = effective_ref_text
            params["prompt_language"] = prompt_lang

        try:
            self._log("INFO", f"正在请求 GPT-SoVITS API 合成文本: {text[:20]}...")
            # 旧版 api.py 标准接口为 GET / （根路径）
            response = requests.get(f"{self.api_url}/", params=params, timeout=60)

            if response.status_code == 200:
                # 写文件时单独捕获异常，给用户具体提示
                try:
                    with open(save_path, "wb") as f:
                        f.write(response.content)
                except PermissionError:
                    return False, f"文件被占用或无写入权限：{save_path}\n请关闭正在使用该文件的程序后重试。"
                except OSError as e:
                    return False, f"保存文件失败：{e}\n路径：{save_path}"
                self._log("INFO", f"语音合成成功，已保存至: {save_path}")
                return True, f"语音合成成功，已保存至: {save_path}"
            else:
                # 把后端返回的错误体也带给用户，便于排查
                err_body = response.text[:300] if response.text else "(无响应内容)"
                self._log("ERROR", f"API 响应失败，状态码: {response.status_code}, 内容: {err_body}")
                return False, f"API 返回错误（状态码 {response.status_code}）：\n{err_body}"

        except requests.exceptions.ConnectionError:
            return False, f"无法连接到 API 服务：{self.api_url}\n请确认引擎已启动（run_local_engine.bat）。"
        except requests.exceptions.Timeout:
            return False, "API 请求超时（60秒），可能文本过长或显卡负载过高。"
        except Exception as e:
            self._log("ERROR", f"调用 API 异常: {str(e)}")
            return False, f"调用 API 异常：{type(e).__name__}: {e}"

    def _mock_generate(self, text, save_path):
        """
        Mock 模式：API 离线时不写任何文件，仅返回失败提示。
        注意：故意返回 success=False，避免用户误以为合成成功。
        历史版本会写一个 1 秒静音 WAV，但用户看到「失败」后通常会重试，
        导致目录里堆积垃圾文件。现在改为只校验写入权限，不真正写文件。
        """
        # 仅校验目标目录是否可写，不真正生成静音文件
        parent_dir = os.path.dirname(save_path) or "."
        if not os.path.exists(parent_dir):
            return False, f"输出目录不存在：{parent_dir}\n请点击「浏览...」重新选择保存路径。"
        if not os.access(parent_dir, os.W_OK):
            return False, f"没有写入权限的目录：{parent_dir}\n请选择其他位置，或用管理员身份运行。"
        self._log("WARNING", f"[Mock] 引擎离线，未生成文件，目标目录可写：{parent_dir}")
        return False, ("本地 GPT-SoVITS 引擎未启动，无法合成配音。\n"
                       "请确认引擎已启动（运行 run_local_engine.bat 或等待自动启动）后重试。")


if __name__ == "__main__":
    client = TTSClient()
    print("API 是否运行:", client.is_api_running())
    # 测试 Mock 生成
    ok, msg = client.generate_speech("测试一下模拟生成功能是否正常", "test.wav")
    print(f"结果: success={ok}, message={msg}")
