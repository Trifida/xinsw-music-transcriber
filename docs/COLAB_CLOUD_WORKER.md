# Google Colab GPU Worker（V1 稳定启动流程）

本项目 V1 使用用户主动连接的 Google Colab GPU Runtime（当前验收设备为 Tesla T4）。网站只负责任务队列和结果展示；Colab Worker 主动连接网站 API。网站不会创建、启动、关闭或释放 GPU。

## 一次性准备

1. 在 Colab 左侧 Secrets 中添加 `MUSICMASTER_WORKER_TOKEN`，并允许本 Notebook 读取。
2. 确认 Colab Runtime 已选择 GPU（例如 Tesla T4），不要使用 CPU Runtime 进行本轮 GPU 验收。
3. Google Drive 中必须已有以下两个 BS-RoFormer 文件：

   `MyDrive/XinsW_Models/BS-RoFormer/model_bs_roformer_ep_317_sdr_12.9755.ckpt`

   `MyDrive/XinsW_Models/BS-RoFormer/model_bs_roformer_ep_317_sdr_12.9755.yaml`

4. 打开并运行 `notebooks/XinsW_Colab_GPU_Worker_V1.ipynb` 中唯一的启动代码单元。

## 每次启动

每次新建或重新连接 Colab Runtime 后，只需重新运行该 Notebook 的启动单元。它会自动：

1. 挂载 Google Drive，并从 Colab Secrets 读取 Worker 凭据（不打印凭据）。
2. 从开发网站 API 获取当前固定版本的 Worker Source Bundle。
3. 校验 commit SHA、SHA-256 和 HTTPS 下载地址；拒绝路径穿越、链接、特殊文件及超大归档。
4. 从固定源码包启动 `scripts/bootstrap_colab_worker.py --start`。
5. 自动建立 Python 3.11 核心环境和独立 CUDA 分离环境；安装缺少的 LilyPond；验证核心依赖、PyTorch、torchaudio、audio-separator、CUDA 和模型文件。
6. 启动 Worker。看到 `[cloud-worker] registered` 后，返回网站上传完整乐曲并点击“开始记谱”。

启动单元会持续运行，这是正常现象。不要关闭 Colab Runtime；要停止 Worker 时，在 Colab 中中断该代码单元即可。

## 持久化与重建规则

Colab 的 Python 进程、虚拟环境和本地磁盘属于临时 Runtime，Google 不保证 Runtime 重启后仍保留。因此本项目不把虚拟环境直接放进 Google Drive，而是把可重复重建所需的资料持久化：

| 内容 | 保存位置 | 新 Runtime 行为 |
|---|---|---|
| BS-RoFormer checkpoint/YAML | `MyDrive/XinsW_Models/BS-RoFormer/` | 直接复用，不重新下载 |
| CREPE 模型 | 首次运行后保存至 `MyDrive/XinsW_Models/CREPE/model-full.h5` | 自动从 Drive 恢复 |
| CUDA 分离环境精确依赖锁 | 首次成功安装后保存至 `MyDrive/XinsW_Runtime/colab-separator-cu130.lock` | 按固定版本锁重建 |
| 核心环境依赖锁 | 仓库 `requirements/locks/core-cpu.txt` | 按 Git 固定版本重建 |
| Python 虚拟环境、uv 缓存 | Colab `/content/` 临时磁盘 | 自动重建；不会写入 Drive |
| Worker 源码包 | Colab `/content/xinsw-worker-bundles/` 临时缓存 | 先校验缓存；缺失时从 API 下载 |

第一次运行需要安装依赖，并会把实际成功安装的 CUDA 分离环境版本写入 Drive 锁文件。之后的新 Runtime 仍需重建本地虚拟环境，但会使用同一份精确版本锁；BS-RoFormer 和 CREPE 模型不需要重新下载。LilyPond 是系统程序，Colab 新 Runtime 中若不存在会自动安装。

## 已验证的 GPU 处理能力

2026-11-26，Tesla T4 上使用项目正式流水线：

```bash
python -m musicmaster.separate.pipeline <audio> --stages 1 --sep-model bs_roformer --out-dir <tmpdir>
```

已完成 76.46 秒歌曲的人声/伴奏分离，进程退出码为 0；生成的 vocal.wav 与 accomp.wav 均非空，44.1 kHz、双声道、时长一致。用户试听确认效果满意。原始测试产物保存在 `MyDrive/XinsW_TestResults/BS-RoFormer/`。

这项测试证明 BS-RoFormer 在 T4 上可以完成真实推理；它不等于网站 Worker 的完整任务领取、整曲识别、记谱文件生成和产物回传已经验收。后者仍须通过网页端完整任务测试。

## 网页端任务规则

1. 先启动 Colab Worker，并确认日志出现 `[cloud-worker] registered`。
2. 在网站首页选择“完整乐曲”并上传。
3. 点击“开始记谱”后，Worker 才能领取该任务。
4. 如果没有在线 Worker，网站提示等待，任务保持 queued；不会自动创建或启动 GPU。
5. 任务完成后，在网页下载结果并检查 MusicXML、简谱 SVG/PDF 和五线谱 SVG。

## 更新源码版本

Worker 启动时以网站 API 配置的 commit 和 SHA-256 为准。发布新的 Worker 代码后，必须先更新开发服务的 Source Bundle 配置并重新发布源码包；之后 Notebook 会自动获取新版本，不需要手工改 Notebook 中的 commit。

## 安全与限制

- Worker Token 只从 Colab Secrets 读取，不要写入 Notebook 源码、Git、截图或日志。
- Notebook 不会创建、启动、关闭或释放 GPU，也不调用付费 GPU provisioning。
- 模型权重不打包进源码归档。
- 不要把虚拟环境目录复制到 Drive；Python venv 含有指向 Runtime 本地路径的解释器和脚本，跨 Runtime 复用不可靠。
- V1 当前以 Colab GPU 为唯一验收运行环境；GPU Docker 和其他云 GPU 调度不属于本轮范围。
