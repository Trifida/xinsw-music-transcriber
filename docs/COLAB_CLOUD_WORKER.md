# Google Colab CPU / GPU Worker（V1）

本说明将现有云端任务队列 Worker 运行在用户主动连接的 Colab CPU 或 GPU Runtime 中。它不创建 GPU，不调用 AutoDL provisioning，也不自动安装依赖或下载模型。

## 启动条件

1. Colab 当前运行时必须已经连接；CPU 和 GPU Runtime 均可注册为计算 Worker。CPU 处理速度会明显慢于 GPU。
2. Google Drive 已挂载。
3. 已有 Worker API 凭据通过 Colab Secrets 注入环境变量 `MUSICMASTER_WORKER_TOKEN`；不要把 token 写进 Notebook 源码、输出或 Git。
4. `MUSICMASTER_API_URL` 指向已部署服务的 HTTPS 根地址，不要附加 `/api`。
5. 当前 Colab Python 环境必须能真实导入完整工作流依赖：NumPy、librosa、soundfile、PyTorch（CPU 或 CUDA 版本）、torchaudio、audio-separator 的实际 Separator 模块、TensorFlow、CREPE、hmmlearn、music21。
6. Drive 中必须存在 BS-RoFormer checkpoint 和 YAML。
7. 私有仓库工作副本必须已在 Colab 中取得授权并检出本分支代码。

## Colab 环境变量

在启动单元中设置：

- `MUSICMASTER_API_URL`：Render API 的 HTTPS 根地址，例如 `https://你的服务.onrender.com`。
- `MUSICMASTER_WORKER_TOKEN`：已有 Worker API 凭据，从 Colab Secrets 读取，不要打印。
- 可选 `MUSICMASTER_WORKER_ID`：默认自动使用当前 Colab Runtime 的 hostname。
- 可选 `MUSICMASTER_SEP_MODELS`：默认 `/content/drive/MyDrive/XinsW_Models/BS-RoFormer`。

Launcher 会把 `MUSICMASTER_SEP_PYTHON` 设为当前 Colab 的 `sys.executable`，并再次通过项目实际的 `_sep_python()` 确认分离子进程解析到同一解释器。临时工作目录使用 `/content/xinsw-worker-tmp`。

## 启动命令

在已经取得私有仓库授权工作副本的 Colab 中执行：

```bash
python scripts/run_colab_cloud_worker.py
```

启动前会实际导入完整乐曲处理依赖（包括 torchaudio 和 audio_separator.separator.Separator）及项目入口模块，检查 CUDA、Drive、BS-RoFormer 文件、API URL、Worker 凭据，并确认分离子进程使用当前 Python 解释器。检查失败时不会注册 Worker。

## 页面操作顺序

1. 先在 Colab 连接 CPU Runtime（或用户主动分配的 GPU Runtime）。
2. 挂载 Google Drive，确认 BS-RoFormer checkpoint 和 YAML 存在。
3. 运行 Colab Worker 单元，看到 `[cloud-worker] registered` 后再返回网站。
4. 在首页“完整乐曲”模式上传歌曲。
5. 点击“开始记谱”。API 只允许近期有心跳的已登记 Worker 领取已手动启动的任务；没有 Worker 时任务保持 queued，不会创建 GPU。
6. 任务完成后下载产物；需要停止时在 Colab 中中断 Worker 单元。

## 模型缓存说明

- Launcher 不安装/升级 PyTorch、CUDA、TensorFlow 或其他依赖，不下载任何模型。
- BS-RoFormer 是启动必需模型，必须预先放在 Drive 指定目录。
- 去和声与降噪模型如果尚未缓存，audio-separator 可能在任务实际运行时联网下载；Launcher 会提示缺失项，但不会代替用户下载。
- 最近一次 Colab 环境盘点为 CPU-only，且 audio-separator、CREPE 等依赖未安装；该环境当时尚不能启动本 Worker；本版本允许 CPU Runtime，但仍须通过完整依赖导入检查。

## 当前限制

- Worker 源码必须通过私有仓库的授权副本进入 Colab；不能使用匿名 raw GitHub URL 下载私有仓库文件。
- 真实 Colab GPU 注册、任务领取、音频处理和产物回传仍未执行；不能视为端到端验收通过。
- 本 Launcher 不创建、启动、关闭或释放 GPU，也不触碰付费 GPU provisioning。
