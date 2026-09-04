<h1 align="center">MamboTTS</h1>

<p align="center"><strong>面向 B 站 / 抖音曼波讲故事类解说场景的 Windows 本地配音工具</strong></p>

<p align="center">
  <img src="https://img.shields.io/badge/Windows-10%2F11_64位-0A0A0B?style=flat-square" alt="Windows" />
  <img src="https://img.shields.io/badge/GPU-NVIDIA-0A0A0B?style=flat-square" alt="NVIDIA" />
  <img src="https://img.shields.io/badge/Engine-GPT--SoVITS-0A0A0B?style=flat-square" alt="GPT-SoVITS" />
  <img src="https://img.shields.io/badge/Version-v1.2.0-0A0A0B?style=flat-square" alt="v1.2.0" />
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-0A0A0B?style=flat-square" alt="MIT" /></a>
</p>

> 基于 GPT-SoVITS，在本地 NVIDIA GPU 上合成解说语音。仓库不包含引擎本体，首次运行需联网从 ModelScope 下载约 8GB 整合包并解压，合成阶段调用本地引擎推理。v1.2.0 声音模型为重新训练版本。

## 功能

- **文案合成 —** 在主界面文本框输入文案，调用本地 GPT-SoVITS 引擎合成 WAV。
- **语速选择 —** 下拉选择 0.5x–3.0x，默认 1.0x。
- **播放试听 —** 内置播放器，支持进度条拖动。
- **会话历史 —** 显示本次会话的合成记录，重启后清空。
- **运行日志 —** 主界面内显示运行日志面板，用于查看状态。
- **文件命名 —** 默认以文案前 20 字作为文件名，可自定义文件名与保存目录。
- **状态提示 —** 本地引擎离线或未正常响应时显示 Mock 模式提示。

## 快速开始

### 1. 下载并解压

前往 [Releases](https://github.com/Tsukimisaka/MamboTTS/releases) 下载 v1.2.0 发布包，解压到全英文路径，例如 `D:\MamboTTS\`。

| 内容 | 说明 |
| --- | --- |
| 客户端 | 发布包内含桌面图形客户端 |
| `models/refer.wav` | 预设参考音频，随发布包提供 |
| `.pth` / `.ckpt` | 随引擎整合包发布 |
| 引擎本体 | 发布包不含，需首次运行时联网下载 |

当前版本不支持在界面内切换自定义参考音频，如需更换，需直接替换 `models/` 下对应文件。

### 2. 双击启动

双击 `MamboTTS.bat`。首次运行按下载 / 校验 / 解压 / 收尾分阶段显示进度，如检测到引擎未安装，会弹出安装引导，按提示完成即可进入主界面。

| 入口 | 用途 |
| --- | --- |
| `MamboTTS.bat` | 主入口，自动完成 venv / 依赖安装、引擎检测与安装引导、引擎启动、主界面拉起 |
| `run.bat` | 调试用旧入口，日常使用无需执行 |
| `run_local_engine.bat` | 调试用旧入口，日常使用无需执行 |

### 3. 输入并合成

在文本框输入解说文案，选择语速，点击合成，完成后在播放器试听，按需保存或删除文件。

| 项目 | 说明 |
| --- | --- |
| 输出格式 | WAV |
| 文件名 | 默认取文案前 20 字，可在界面中自定义 |
| 保存目录 | 可在界面中自定义 |
| 历史保留 | 仅保留本次会话，需长期保留时自行归档 WAV 文件 |

## 系统要求

| 项目 | 要求 |
| --- | --- |
| 操作系统 | Windows 10 / 11 64 位 |
| 显卡 | NVIDIA GPU，用于本地推理 |
| 网络 | 首次运行需联网，从 ModelScope 下载约 8GB 引擎整合包，合成阶段调用本地引擎 |
| 磁盘空间 | 需容纳约 8GB 下载包及解压后的引擎与模型文件 |
| 解压路径 | 须为全英文路径，中文或特殊字符路径可能导致引擎或模型加载异常 |

## 工作原理

| 步骤 | 内容 |
| --- | --- |
| 1 | 用户双击 `MamboTTS.bat`，脚本检查并准备本地 `venv` 与依赖 |
| 2 | 脚本检测本地引擎目录是否存在，如不存在，进入安装引导流程，从 ModelScope 下载整合包，经校验后以 7z 解压到本地 |
| 3 | 引擎就绪后，脚本启动本地引擎进程，并拉起主界面 |
| 4 | 用户在主界面输入文案并选择语速，客户端将请求发送至本地引擎，由 NVIDIA GPU 完成推理并返回 WAV 文件 |
| 5 | 客户端展示播放器、本次会话历史与运行日志，关闭主窗口时，引擎进程随之退出 |
| 6 | 若本地引擎离线或未正常响应，界面显示 Mock 模式提示 |

本说明仅描述本仓库客户端与本地引擎的调用关系，不对上游引擎的实现细节作额外断言。

## 编辑器扩展

仓库 `Premiere-Pro-UXP/` 目录提供用于 Premiere Pro 的 UXP 配音插件，由 @2710165659 贡献，为独立于主客户端的编辑器扩展，适用于在 Premiere Pro 内发起配音与试听。

| 文件 / 目录 | 说明 |
| --- | --- |
| `index.html` / 相关 JS | 插件面板与逻辑 |
| `styles.css` | 面板样式 |
| `manifest.json` | UXP 插件清单 |
| `install.ps1` | Windows 安装脚本 |
| `preview-player/` | 基于 Rust 的预览播放器 |

具体安装与使用方式以该目录内说明与脚本为准。Premiere Pro 为 Adobe 商标，本项目与其不存在隶属或背书关系。

## 常见问题

<details>
<summary>首次运行需要下载什么，耗时取决于什么</summary>
首次运行需联网从 ModelScope 下载约 8GB 引擎整合包并解压，耗时取决于网络带宽与磁盘速度。安装过程按下载 / 校验 / 解压 / 收尾分阶段显示进度，中断后可重新双击 MamboTTS.bat 继续。
</details>

<details>
<summary>为什么要求解压到全英文路径</summary>
中文或特殊字符路径可能导致引擎或模型加载异常，需解压到例如 D:\MamboTTS\ 的全英文目录。
</details>

<details>
<summary>双击后提示安装引擎是否正常</summary>
正常。如检测到本地引擎未安装，启动时会弹出安装引导，按提示完成下载与解压即可进入主界面。
</details>

<details>
<summary>是否可以离线合成</summary>
引擎安装完成后，合成调用本地引擎进行推理。首次下载与安装阶段必须联网。
</details>

<details>
<summary>语速有哪些选项</summary>
语速为下拉选择，范围 0.5x–3.0x，默认 1.0x。
</details>

<details>
<summary>合成历史为什么重启后不见了</summary>
合成历史仅保留本次会话，重启客户端后清空。如需保留音频，需在合成后保存 WAV 文件并自行归档。
</details>

<details>
<summary>输出文件如何命名，保存在哪里</summary>
输出为 WAV 格式。默认以文案前 20 字作为文件名，可在界面中自定义文件名与保存目录。
</details>

<details>
<summary>什么是 Mock 模式提示</summary>
当本地引擎离线或未正常响应时，界面会显示 Mock 模式提示，表明当前未连接到可用引擎，需检查引擎是否已安装并正常启动。
</details>

<details>
<summary>run.bat 和 run_local_engine.bat 需要用吗</summary>
不需要。这两个为调试用旧入口，日常使用以 MamboTTS.bat 为准。
</details>

## 许可

本项目采用 MIT 许可，详见 [LICENSE](LICENSE)。
