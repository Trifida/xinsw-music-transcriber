# AutoDL 自动调度与空闲释放

本流程分成两个独立开关。代码默认关闭，不会因为上传歌曲而创建 GPU，也不会自动关闭或释放任何 AutoDL 实例。

## 1. 上传后自动检查/启动 Worker

在运行云端 API 的 Render 服务中，只有明确设置下面的环境变量为 `true`，上传任务后才会安排后台调度：

- `MUSICMASTER_AUTODL_AUTO_DISPATCH=true`

还必须配置现有 Dispatcher 所需的服务端环境：

- `MUSICMASTER_DISPATCHER_TOKEN`：至少 32 个字符的独立强凭据
- `AUTODL_PRO_TOKEN`：AutoDL Pro API 凭据
- `MUSICMASTER_API_URL`：Worker 回连的 HTTPS API 地址
- `MUSICMASTER_AUTODL_IMAGE_UUID`：已验证的 AutoDL 镜像
- `MUSICMASTER_AUTODL_CUDA_V_FROM`：镜像要求的 CUDA 版本值
- `MUSICMASTER_AUTODL_MAX_WORKERS`：并发 Worker 上限，默认 1，允许 1–10

用户上传成功后，任务先可靠写入对象存储和 PostgreSQL 队列，再由 FastAPI 后台任务使用稳定的任务幂等键请求 Dispatcher。容量已满或另一项创建操作正在进行时，任务保持 queued；已运行的 Worker 会继续轮询并领取队列任务。Dispatcher 不会因重试而为同一任务重复创建实例。

## 2. Worker 实际执行链

1. Dispatcher 创建并启动 AutoDL 实例。
2. Worker 启动脚本使用一次性 bootstrap token 获取 Worker 凭据，并下载固定版本的 Worker bundle。
3. Worker 注册后轮询任务队列并领取任务。
4. Worker 执行完整歌曲工作流，上传人声、伴奏、MIDI、MusicXML、notes 等产物。
5. API 将任务状态和产物记录为完成，页面可查询状态并下载文件。

上传入队不等于 GPU 已启动；只有任务进入 running 才代表 Worker 已领取并开始处理。

## 3. 自动释放空闲 GPU（独立开关）

`.github/workflows/autodl-idle-release.yml` 每 5 分钟运行一次，但默认只报告“未启用”，不会调用 AutoDL。

只有在 GitHub 仓库设置中明确配置以下项目后，定时流程才会执行释放检查：

- Repository Variable：`MUSICMASTER_AUTODL_AUTO_RELEASE=true`
- Repository Variable：`MUSICMASTER_API_URL`（云端 API 的 HTTPS 地址）
- Repository Secret：`MUSICMASTER_DISPATCHER_TOKEN`（与 Render 服务端相同的 Dispatcher 凭据）

Render 服务端的 `MUSICMASTER_AUTODL_IDLE_SECONDS` 控制空闲门槛，默认 300 秒，允许 60–86400 秒。

释放流程先检查数据库中的 Worker 状态和空闲时间，再向 AutoDL 查询实例状态；只会处理确认空闲且没有活动任务的实例。先请求关机，只有 AutoDL 明确确认实例已停止后才释放实例。忙碌、正在停止、状态未知或无法确认的实例不会被释放。

## 4. 启用前的成本确认

- 开启自动调度后，新的完整歌曲任务可能触发按量计费的 GPU 实例。
- 开启自动释放后，空闲达到门槛的 Worker 会被关机并释放；下一首歌曲可能需要重新创建和启动实例。
- 不要仅为了测试而在生产环境开启开关。先确认镜像、GPU 型号、计费方式、API 凭据和预算，再进行一次受控端到端测试。
- 本次代码改动不会设置 Render 环境变量、GitHub Secret/Variable，也不会创建、启动、关闭或释放任何 GPU 实例。
