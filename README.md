<h1 align="center">MamboTTS</h1>

<p align="center"><strong>面向 B 站 / 抖音曼波讲故事类解说场景的 Windows 本地配音工具</strong></p>

<p align="center">
  <img src="https://img.shields.io/badge/Windows-10%2F11_64位-0A0A0B?style=flat-square" alt="Windows" />
  <img src="https://img.shields.io/badge/GPU-NVIDIA-0A0A0B?style=flat-square" alt="NVIDIA" />
  <img src="https://img.shields.io/badge/Engine-GPT--SoVITS-0A0A0B?style=flat-square" alt="GPT-SoVITS" />
  <img src="https://img.shields.io/badge/Version-v1.2.1-0A0A0B?style=flat-square" alt="v1.2.1" />
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-0A0A0B?style=flat-square" alt="MIT" /></a>
</p>

> 基于 GPT-SoVITS，在本地 NVIDIA GPU 上合成解说语音。仓库不包含引擎本体，首次运行需联网下载引擎整合包（约 8.2GB，多源自动测速），合成阶段调用本地引擎推理。

## 功能

- **文案合成 —** 在主界面文本框输入文案，调用本地 GPT-SoVITS 引擎合成 WAV；超长文本自动按标点切分。
- **语速调节 —** 0.1x–3.0x 连续滑条调节（引擎原生变速不变调）。
- **播放试听 —** 内置播放器，支持进度条拖动与实时时间预览。
- **历史记录 —** 合成历史跨重启保留（自动过滤已删除文件），支持回放 / 另存 / 删除。
- **运行日志 —** 主界面实时显示运行日志，引擎状态一目了然，问题可自查。
- **文件命名 —** 默认以文案前 20 字作为文件名，可自定义文件名与保存目录。
- **深浅主题 —** 深色 / 浅色一键切换，选择自动记忆。
- **单一入口 —** 双击 `MamboTTS.bat` 自动完成依赖安装、引擎下载与启动、拉起主界面。

## 快速开始

### 1. 下载并解压

前往 [Releases](https://github.com/Tsukimisaka/MamboTTS/releases) 下载 `MamboTTS-v1.2.1-full.zip`，解压到全英文路径，例如 `D:\MamboTTS\`。

| 内容 | 说明 |
| --- | --- |
| 客户端 | 发布包内含桌面图形客户端与预设音色 |
| 引擎本体 | 发布包不含，首次运行时自动下载（约 8.2GB） |

### 2. 双击启动

双击 `MamboTTS.bat`。

- 首次运行自动安装依赖并下载引擎：多源自动测速选最快，支持断点续传与失败自动换源，界面实时显示下载百分比 / 速度 / 剩余量。
- 引擎就绪后进入主界面（首次约 10–30 秒），关闭窗口时引擎自动退出。

### 3. 输入并合成

在文本框输入解说文案 → 调节语速 → 点击「合成配音」。完成后可在播放器试听，历史记录支持回放与另存。

## 系统要求

| 项目 | 要求 |
| --- | --- |
| 操作系统 | Windows 10 / 11 64 位 |
| 显卡 | NVIDIA GPU（50 系与其余 NVIDIA 对应不同整合包，安装时按 nvidia-smi 自动预选） |
| 网络 | 首次运行需联网下载引擎约 8.2GB；合成阶段可离线 |
| 磁盘 | 需容纳下载包及解压后的引擎与模型，建议预留 30GB+ |
| 解压路径 | 须为全英文路径，中文路径可能导致引擎加载异常 |

## 常见问题

<details>
<summary>安装很慢或看起来卡住？</summary>

安装器内置多源下载（ModelScope / hf-mirror / HuggingFace 等自动测速选最快），下载期间实时显示百分比、速度与剩余量；单源失败自动切换，中断后重新双击可断点续传。
</details>

<details>
<summary>所有下载源都失败怎么办？</summary>

两种自救方式：在 `mirrors.txt` 中添加可用镜像；或手动下载整合包放入 `engine_temp/` 后重试安装（安装器会跳过下载直接解压）。详见「高级配置」。
</details>

<details>
<summary>一直显示引擎启动中？</summary>

首次加载约需 10–30 秒属正常。若超时，界面提供「重启引擎」入口，并可在运行日志中查看具体原因。
</details>

## 工作原理

MamboTTS 是 GPT-SoVITS 的 Windows 图形客户端与启动器。本仓库**不包含、也不修改** GPT-SoVITS 本体：引擎整合包在首次运行时从云端下载，客户端通过本地 HTTP API（`127.0.0.1:9880`）调用，接口契约见 `engine_contract.py`。

## 编辑器扩展

仓库 `Premiere-Pro-UXP/` 目录提供用于 Premiere Pro 的 UXP 配音插件，由 [@2710165659](https://github.com/2710165659) 贡献，为独立于主客户端的编辑器扩展，适用于在 Premiere Pro 内发起配音与试听。

| 文件 / 目录 | 说明 |
| --- | --- |
| `index.html` / 相关 JS | 插件面板与逻辑 |
| `styles.css` | 面板样式 |
| `manifest.json` | UXP 插件清单 |
| `install.ps1` | Windows 安装脚本 |
| `preview-player/` | 基于 Rust 的预览播放器 |

Premiere Pro 为 Adobe 商标，本项目与其不存在隶属或背书关系。

## 高级配置

- **自定义下载镜像**：编辑 `mirrors.txt`，每行一个 URL 模板（`{file}` 为整合包文件名占位符）。
- **手动放置整合包**：将 7z 文件放入 `engine_temp/` 后重新运行安装，即可跳过下载。
- **自建 / 远程引擎**：主界面「引擎接口」可填写自定义服务地址（对应 `config.json` 的 `api_url`）。
- **配置文件**：`config.json` 由程序自动生成，模板见 `config.example.json`。

## 开发者

| 模块 | 职责 |
| --- | --- |
| `app.py` | 主界面：合成 / 播放器 / 历史 / 日志 / 主题 |
| `launcher.py` · `bootstrap.py` | 启动引导与一键安装 |
| `install_engine.py` | 引擎多源下载与解压 |
| `inference.py` | 引擎 HTTP 客户端 |
| `theme.py` | 深浅双主题样式 |

## 免责声明

本软件仅供个人学习、技术研究与学术交流使用。用户需自行确保参考音频与生成内容的权利合规，并承担相应使用责任；严禁将生成的声音用于诈骗、仿冒、侵犯他人声音权 / 肖像权等非法用途。

## 致谢与许可

引擎基于 [RVC-Boss/GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS)。

感谢 [@2710165659](https://github.com/2710165659) 贡献的 Premiere Pro UXP 插件支持。

本项目基于 [MIT](LICENSE) 许可开源；GPT-SoVITS 引擎本体遵循其上游许可。
