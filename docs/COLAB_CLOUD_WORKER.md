# Google Colab GPU Worker（V1）

本说明将已有的 Neon 云端任务队列 Worker 运行在用户主动分配的 Colab GPU Runtime 中。它不创建 GPU，不调用 AutoDL provisioning，也不自动安装依赖或下载模型。

## 启动条件

1. Colab 当前运行时必须已经分配 CUDA GPU；CPU Runtime 不会注册为 GPU Worker。
2. Google Drive 已挂载。
3. 已有 Worker API 凭据通过 Colab Secrets 注入环境变量 `MUSICMASTER_WORKER_TOKEN`；不要把 token 写进 Notebook 源码、输出或 Git。
4. `MUSICMASTER_API_URL` 指向已部署的 HTTPS API。
5. 当前 Colab Python 环境必须已具备 PyTorch CUDA、audio-separator、TensorFlow、CREPE、hmmlearn、music21。
6. Drive 中必须存在 BS-RoFormer checkpoint 和 YAML。

## Colab 环境变量

在启动单元中设置：

- `MUSICMASTER_API_URL`：Render API 的 HTTPS 地址。
- `MUSICMASTER_WORKER_TOKEN`：从 Colab Secrets 读取，不要打印。
- 可选 `MUSICMASTER_WORKER_ID`：默认自动使用当前 Colab Runtime 的 hostname。
- 可选 `MUSICMASTER_SEP_MODELS`：默认 `/content/drive/MyDrive/XinsW_Models/BS-RoFormer`。

Launcher 会把 `MUSICMASTER_SEP_PYTHON` 设为当前 Colab 的 `sys.executable`，让分离子进程使用同一套 CUDA Python；临时工作目录使用 `/content/xinsw-worker-tmp`。

## 启动命令

在已经取得私有仓库工作副本的 Colab 中执行：

```bash
python scripts/run_colab_cloud_worker.py
```

Launcher 会先检查 GPU、依赖、Drive 和模型文件，再调用现有的 `musicmaster.cloud.worker` 长轮询程序。检查失败时不会注册 Worker。

## 页面操作顺序

1. 先在 Colab 选择并启动 GPU Runtime。
2. 挂载 Google Drive，确认模型文件存在。
3. 运行 Colab Worker 单元，看到 Worker 注册成功后再返回网站。
4. 在首页“完整乐曲”模式上传歌曲。
5. 点击“开始记谱”。API 只检查已经运行且近期有心跳的 Worker；没有 Worker 时任务保持 queued，不会创建 GPU。
6. 任务完成后下载产物；需要停止时在 Colab 中中断 Worker 单元。

## 当前限制

- 最近一次 Colab 盘点为 CPU-only，且 audio-separator、CREPE、hmmlearn 未安装；该环境尚不能启动本 Worker。
- 当前 Drive 目录已发现 BS-RoFormer 权重与 YAML；其他阶段的模型可能需要后续单独核对。
- 本 Launcher 不安装/升级 PyTorch、CUDA、TensorFlow 或其他依赖，不下载任何模型。
- Worker 源码仍需通过私有仓库的授权副本进入 Colab；不能使用匿名 raw GitHub URL 下载私有仓库文件。
- 尚未在真实 Colab GPU 上执行，也未完成真实音频端到端验收。
