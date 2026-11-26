# Google Colab CPU / GPU Worker（V1）

本说明将现有云端任务队列 Worker 运行在用户主动连接的 Colab CPU 或 GPU Runtime 中。它不创建 GPU，不调用 AutoDL provisioning，也不自动安装依赖或下载模型。

## 启动条件

1. Colab 当前运行时必须已经连接；CPU 和 GPU Runtime 均可注册为计算 Worker。CPU 处理速度会明显慢于 GPU。
2. Google Drive 已挂载。
3. 已有 Worker API 凭据通过 Colab Secrets 注入环境变量 `MUSICMASTER_WORKER_TOKEN`；不要把 token 写进 Notebook 源码、输出或 Git。
4. `MUSICMASTER_API_URL` 指向已部署服务的 HTTPS 根地址，不要附加 `/api`。
5. 核心 Python 3.11 环境必须能导入 NumPy、librosa、soundfile、TensorFlow、CREPE、hmmlearn、music21、Verovio、jianpu-ly；同时系统必须安装 LilyPond CLI，供整曲任务生成简谱 SVG/PDF。人声分离使用独立 Python 环境，导入 PyTorch、torchaudio 和 audio-separator。两套环境不能混装：核心 TensorFlow 2.15 需要 NumPy <2，而当前 audio-separator 需要 NumPy 2。
6. Drive 中必须存在 BS-RoFormer checkpoint 和 YAML。
7. 私有仓库工作副本必须已在 Colab 中取得授权并检出本分支代码。

## 一键初始化（推荐）

仓库提供统一初始化脚本 `scripts/bootstrap_colab_worker.py`。它会在 Colab 本地 `/content` 下安装并配置 Python 3.11、核心环境、CUDA 13.0 分离环境和 LilyPond，最后检查 TensorFlow/CREPE、PyTorch、torchaudio、audio-separator、CUDA 与 BS-RoFormer 模型。uv 缓存、Python 和虚拟环境都不写入 Google Drive；Drive 只保存模型权重。

在已授权并检出本分支的仓库目录中，先在 Colab 的 Secrets 中添加 `MUSICMASTER_WORKER_TOKEN`，然后运行一个单元：

```python
from google.colab import userdata
import os

os.environ["MUSICMASTER_API_URL"] = "https://xinsw-transcriber-dev.onrender.com"
os.environ["MUSICMASTER_WORKER_TOKEN"] = userdata.get("MUSICMASTER_WORKER_TOKEN")
!python scripts/bootstrap_colab_worker.py --start
```

首次运行会安装依赖并启动 Worker；Colab Runtime 重启后再次运行同一单元即可重建本地环境并启动。安装缓存只在当前 Runtime 生命周期内有效，因此重启后可能重新下载依赖；不要将虚拟环境或 uv 缓存放进 Drive。若只想安装和检查环境、不启动 Worker，去掉命令末尾的 `--start`。

该脚本的 CUDA 分离环境固定使用 PyTorch 2.11.0 / torchvision 0.26.0 / torchaudio 2.11.0 的 cu130 轮子。若 Colab GPU 驱动不兼容或 CUDA 不可用，脚本会在 Worker 注册前失败，不会把 CPU 伪装成 GPU Worker。

## Colab 环境变量

在启动单元中设置：

- `MUSICMASTER_API_URL`：Render API 的 HTTPS 根地址，例如 `https://你的服务.onrender.com`。
- `MUSICMASTER_WORKER_TOKEN`：已有 Worker API 凭据，从 Colab Secrets 读取，不要打印。
- 可选 `MUSICMASTER_WORKER_ID`：默认自动使用当前 Colab Runtime 的 hostname。
- `MUSICMASTER_SEP_PYTHON`：必须指向独立分离环境的 Python，例如 `/content/xinsw-sep-venv/bin/python`。
- 可选 `MUSICMASTER_SEP_MODELS`：默认 `/content/drive/MyDrive/XinsW_Models/BS-RoFormer`。

先在 Colab 建立核心环境（本项目既有步骤），并安装系统级简谱排版程序，再用核心环境 Python 创建分离环境：

```bash
!apt-get update -qq && apt-get install -y lilypond
```

安装完成后确认 `lilypond --version` 可正常返回版本。

```bash
/content/xinsw-worker-venv/bin/python scripts/setup_sep.py --venv /content/xinsw-sep-venv --device cpu
```

CPU 模式只安装 CPU 版 PyTorch / torchaudio 和 audio-separator[cpu]，不会申请 GPU。若用户主动连接 GPU 并需要 CUDA 分离，可显式指定 `--device cuda --cuda cu124`（CUDA 标签必须与实际运行时匹配）。

Launcher 分别检查核心环境和 `MUSICMASTER_SEP_PYTHON` 指向的分离环境；分离子进程通过项目实际的 `_sep_python()` 使用独立解释器。临时工作目录使用 `/content/xinsw-worker-tmp`。

## 启动命令

在已经取得私有仓库授权工作副本的 Colab 中执行：

```bash
python scripts/run_colab_cloud_worker.py
```

启动前会分别检查核心模块（包括 Verovio、jianpu-ly）、LilyPond CLI、项目入口模块，以及独立分离环境中的 PyTorch、torchaudio、audio_separator.separator.Separator；同时检查分离设备、Drive、BS-RoFormer 文件、API URL 和 Worker 凭据。检查失败时不会注册 Worker。

## 页面操作顺序

1. 先在 Colab 连接 CPU Runtime（或用户主动分配的 GPU Runtime）。
2. 挂载 Google Drive，确认 BS-RoFormer checkpoint 和 YAML 存在。
3. 运行 Colab Worker 单元，看到 `[cloud-worker] registered` 后再返回网站。
4. 在首页“完整乐曲”模式上传歌曲。
5. 点击“开始记谱”。API 只允许近期有心跳的已登记 Worker 领取已手动启动的任务；没有 Worker 时任务保持 queued，不会创建 GPU。
6. 任务完成后下载产物；需要停止时在 Colab 中中断 Worker 单元。

## 模型缓存说明

- Launcher 不安装/升级 PyTorch、CUDA、TensorFlow 或其他依赖，不下载任何模型。环境安装由用户单独执行 `scripts/setup_sep.py`。
- BS-RoFormer 是启动必需模型，必须预先放在 Drive 指定目录。
- 去和声与降噪模型如果尚未缓存，audio-separator 可能在任务实际运行时联网下载；Launcher 会提示缺失项，但不会代替用户下载。
- 最近一次 Colab 环境盘点为 CPU-only，且 audio-separator、CREPE 等依赖未安装；该环境当时尚不能启动本 Worker；本版本允许 CPU Runtime，但仍须通过完整依赖导入检查。

## 当前限制

- Worker 源码必须通过私有仓库的授权副本进入 Colab；不能使用匿名 raw GitHub URL 下载私有仓库文件。
- 真实 Colab GPU 注册、任务领取、音频处理和产物回传仍未执行；不能视为端到端验收通过。
- 本 Launcher 不创建、启动、关闭或释放 GPU，也不触碰付费 GPU provisioning。
