# 心思维 AI 扒谱助手｜开发交接存档

**存档日期：** 2026-11-24  
**用途：** 明天在办公室电脑继续开发时，作为唯一交接依据。  
**仓库：** `Trifida/xinsw-music-transcriber`  
**开发分支：** `deploy/v1-production`  
**PR：** [#12 — Build durable cloud jobs and GPU worker API](https://github.com/Trifida/xinsw-music-transcriber/pull/12)

## 一、当前工作位置

- 所有本轮改动都在 `deploy/v1-production`，没有合并 `main`。
- PR #12 仍为 Draft / Open。
- 本轮最后一个已确认提交：`13f6c12742121aafd98b7ec1324e829354c20249`。
- 未部署新生产服务，未修改生产 Neon main，未创建或启动付费 AutoDL GPU 实例。
- 明天继续前，先检查 PR 当前 HEAD SHA；如果分支有更新，以 GitHub 最新状态为准。

## 二、今天完成的工作

### 1. Worker 租约与重复下载修复

此前提交：
- `6efcc2bd5474b759789e7283ff308a3984c947cf`
- `3d43aec57e0067c5dd5b89f2354b5df054d2cb89`

修复 Worker 重复下载源音频，以及下载/推理/产物上传期间 heartbeat 不连续的问题；补充回归测试。

### 2. 私有 GitHub 代码包交付第一阶段

新增：
- `musicmaster/cloud/source_bundle.py`
  - 通过可信 API 主机上的 GitHub 只读令牌，获取指定完整 Commit SHA 的私有仓库 tar.gz。
  - 校验 GitHub 返回的 Commit SHA。
  - 限制最大包体积 512 MiB。
  - 计算 SHA256。
  - 上传到私有对象存储的不可变路径：`worker-bundles/<commit_sha>/<sha256>.tar.gz`。
- `scripts/publish_worker_bundle.py`
  - 供可信 API 主机执行的发布命令。
- `musicmaster/web/cloud_api.py`
  - 新增受 Worker Bearer 认证保护的 `GET /api/internal/worker/bundle`。
  - 只按服务端环境变量中配置的 Commit、SHA256 和对象路径签发 10 分钟预签名下载 URL。
  - 校验 Commit、SHA256 格式及对象路径匹配。
- `tests/test_source_bundle.py`
  - 覆盖密钥/仓库配置、固定 SHA、摘要、错误响应、gzip 格式及包体积限制。
- `.github/workflows/cloud-jobs-smoke.yml`
  - 将 source bundle 测试纳入 cloud jobs workflow。
- `docs/WORKER_SOURCE_BUNDLE.md`
  - 记录发布和环境配置方式。

本阶段关键提交：
- `63ddad878c27fa3aee517eb2cbebc4d944e30b1c`
- `de396e32dabfe2476a944295c9206b4e57dcd6a6`
- `b0385c91a71f2c7249fbc9e4197246dd4c1104c3`
- `9d1af4f68471788e0e446c836d7208f0b78ba842`
- `bb7e8e2da3f9cc0ce290362764d68c2410d85540`
- `c12eebd19558e8cdb2beee14739d44bf91a3307a`
- `b161455d4d0346c6a9e9f4fa955b6836fd3269dd`
- `13f6c12742121aafd98b7ec1324e829354c20249`

## 三、测试现状（不可误报）

截至今晚最新 Cloud jobs workflow run：
- Run ID：`45427658498`
- Head SHA：`c12eebd19558e8cdb2beee14739d44bf91a3307a`
- 结果：failure。
- Job ID：`138563954374`。
- GitHub Jobs 返回的 `steps` 和 `logs_url` 均为空；尝试取日志得到 BlobNotFound 404。

后续还有提交进入分支，因此明天必须对最新 HEAD 再检查 Actions。当前不能声称测试通过，也不能确定失败来自代码、依赖、workflow 还是 GitHub 日志系统。优先修复 CI 可观测性：让测试步骤输出可见，必要时增加独立、清晰的安装/编译/测试步骤和失败日志保留。

## 四、下一步开发顺序

### P0：先恢复可靠测试反馈
1. 检查 PR #12 最新 HEAD、Actions workflow 与最新失败运行。
2. 找到失败的真实步骤；若日志仍不可取，调整 workflow 以确保步骤状态和日志可诊断。
3. 本地或可用的安全测试环境运行新增 source bundle 测试及 cloud jobs 测试。没有真实运行结果前，不标记通过。

### P1：完成 GPU Bootstrap（下一项实际开发）
GPU 端目前没有项目代码，因此启动命令必须能独立运行最小 bootstrap，不能依赖尚未下载的仓库脚本。

预期流程：
1. AutoDL 实例启动命令运行一个最小 Python 标准库 bootstrap。
2. 使用一次性 bootstrap token 向网站内部 API 交换短期授权。
3. 获取 worker token、代码包 Commit、SHA256 和短期对象下载 URL。
4. 下载代码包并校验 SHA256。
5. 安全解压 tar.gz，必须防止路径穿越（tar path traversal）；只允许解压到专用工作目录。
6. 启动 `python -m musicmaster.cloud.worker`。
7. GitHub 长期令牌不得进入 GPU 环境变量、启动命令、日志或 GPU 文件。

注意：当前新增的 `GET /api/internal/worker/bundle` 是 Worker Bearer 认证端点。需要核实 bootstrap token exchange 现有接口的返回结构和认证约定，再决定如何把 bundle manifest 安全地接到一次性 bootstrap 流程；不要想当然地假设接口已经打通。

### P2：持久化 AutoDL 调度器
1. PostgreSQL 持久化调度状态，避免网站重启丢失。
2. 多副本互斥（数据库 lease 或 advisory lock）。
3. 待处理任务出现时才创建/启动 GPU。
4. 监控实例启动、Worker 注册、任务领取和心跳。
5. 无任务后自动关机；确认关机后才释放实例。
6. 异常重试与遗留实例回收。

### P3：端到端验证
Render 独立服务配置、Neon 测试分支、AutoDL 按任务启动、完整音频处理、结果回传和自动释放的全链路验证。

## 五、不可越过的安全边界

- 只在 `deploy/v1-production` 和 PR #12 开发，不直接改 `main`。
- 不合并 PR，不部署生产，不修改生产 Neon main。
- 不创建、启动或释放付费 GPU 实例，除非用户明确授权。
- 不把 GitHub 长期令牌交给 GPU。
- 不将密钥写入代码、提交记录、日志或聊天存档。
- 生产环境变量变更、数据库破坏性操作、服务部署均需用户明确授权。
- 不因 CI 绿色就跳过完整音频端到端验证。

## 六、明天跨电脑恢复方式

在办公室电脑打开同一个 ChatGPT 账号和本项目对话，发送：

> 继续开发心思维 AI 扒谱助手。请先读取 GitHub 仓库 `docs/DEV_HANDOFF_2026-11-24.md`，检查 PR #12 和 `deploy/v1-production` 最新状态，然后从 P0 测试排查开始，按存档中的顺序继续。不要修改 main，不要启动付费 GPU。

也可直接打开 PR：
https://github.com/Trifida/xinsw-music-transcriber/pull/12

**交接原则：** 先核实远端真实状态，再继续写代码；不以聊天中的旧 SHA 覆盖 GitHub 最新状态。


---

## 七、2026-11-25 开发续接记录

**本轮最新 PR HEAD：** `e09fc63bc393469676dc329d8cbe9d6335e7e6b2`  
**分支：** `deploy/v1-production`  
**PR #12：** 仍为 Draft / Open；未合并 main。

### 已完成的 GPU worker source bootstrap 实现

新增：
- `scripts/bootstrap_worker_bundle.py`
  - 使用一次性 Bootstrap Token 调用 `POST /api/internal/bootstrap` 换取 Worker Token。
  - 使用 Worker Bearer Token 调用 `GET /api/internal/worker/bundle`。
  - 验证 Commit SHA、SHA256 和对象 key 三者匹配。
  - 只允许 HTTPS 下载，下载上限 512 MiB。
  - 下载后校验完整 SHA256。
  - tar.gz 解压前拒绝绝对路径、路径穿越、软链接、硬链接及特殊文件。
  - 解压后要求存在 `musicmaster/cloud/worker.py`。
  - 安装到按 Commit SHA 隔离的用户缓存目录；保留摘要标记。
- `scripts/run_autodl_cloud_worker.sh`
  - 增加启动前 bundle bootstrap。
  - 从已校验的版本目录重新启动 Worker launcher。
  - Bootstrap Token 在交换后从环境中清除；不落盘保存 Worker Token。
- `tests/test_worker_bundle_bootstrap.py`
  - 覆盖正常解压、路径穿越、链接文件、缺少 worker 入口、HTTPS 校验及完整 token→bundle 下载流程。
- `.github/workflows/cloud-jobs-smoke.yml`
  - 将 bootstrap 编译检查和测试加入 Cloud jobs CI。
- `docs/WORKER_SOURCE_BUNDLE.md`
  - 记录 AutoDL bootstrap 顺序和部署边界。

### 关键限制，尚不能标记为 GPU 自动部署完成

当前 launcher 必须先存在于 AutoDL 镜像或持久启动卷中，至少包含：
- `scripts/run_autodl_cloud_worker.sh`
- `scripts/bootstrap_worker_bundle.py`

这两个文件是独立 bootstrap carrier；下载完成后，真正运行的应用代码来自 SHA256 验证通过的私有代码包。尚未实现 AutoDL 创建实例时自动注入这两个 carrier，也尚未完成实例创建/启动/关机/释放调度器。

### 最新 CI 状态

- 最新 Cloud jobs run：Run ID `45526409176`，Run #58。
- Head SHA：`e09fc63bc393469676dc329d8cbe9d6335e7e6b2`。
- 第一次运行失败；重跑 attempt 2 仍失败。
- Job ID：`138910972012`。
- GitHub Jobs API 的 steps 仍为空；下载日志返回 BlobNotFound 404。
- 因此新增 bootstrap 测试没有获得可确认的执行结果，不能声称通过。
- 同一 PR 的 Original jianpu renderer workflow 也仍失败，需独立追查。

### 下一步

1. **P0**：继续解决 Actions 失败无步骤/无日志的问题。检查 workflow run/job 的真实 GitHub 页面及仓库 Actions 设置；不能把空 steps 当成代码错误，也不能把测试标记通过。
2. **P1**：为 bootstrap 增加完整端到端 mock 测试与 shell launcher 静态校验；在可用的安全 Linux 环境实际运行测试。
3. **P1**：明确 AutoDL 镜像如何预置 bootstrap carrier；这一步需要先验证 AutoDL start_command / 镜像机制，不能假设 carrier 已存在。
4. **P2**：实现持久化 dispatcher 和 AutoDL 生命周期状态机；付费 GPU 仍不得启动，除非用户明确授权。
5. **P3**：Neon 测试分支、Render 配置、AutoDL 测试实例及真实音频全链路验证。

### 安全边界重申

- 只改 `deploy/v1-production`；不改 `main`、不合并 PR、不部署生产。
- 不启动付费 GPU。
- GitHub 长期令牌不得进入 GPU。
- 不将 Worker Token 写入代码包、文件或日志。
- 所有生产环境变量、数据库和部署变更必须先获得用户明确授权。


## 2026-11-25 continued — self-contained AutoDL bootstrap carrier

- Rechecked PR #12 live: still open, Draft, base `main`, head `deploy/v1-production`; no merge or deployment. At the start of this work the head was `7b563bdead40679994fc92bac8914ca1694e76dd`.
- Confirmed the real API response contract in `musicmaster/web/cloud_api.py`: bootstrap exchange returns `worker_token`, `worker_id`, `instance_uuid`; worker bundle manifest returns `repository_commit`, `sha256`, `object_key`, `url`. These match the bootstrap helper.
- Added `build_worker_start_command(api_url, bootstrap_token)` in `musicmaster/cloud/autodl_pro.py`. It embeds a compressed copy of the bootstrap helper into the AutoDL startup command, so a fresh image can fetch the pinned source bundle without a preinstalled repository checkout. The command uses only a short-lived, single-use bootstrap token, exchanges it for the worker token, removes the bootstrap token from the process environment, and execs the launcher from the verified bundle.
- Added unit tests for embedded helper integrity, HTTPS URL validation, and bootstrap-token length. Updated `docs/WORKER_SOURCE_BUNDLE.md` with the no-preinstalled-checkout flow and provider command-history sensitivity.
- This builder is not yet wired into a complete dispatcher/token-issuance workflow. The caller must create a short-expiry single-use bootstrap token and pass the generated command into `AutoDLProClient.create_instance(start_command=...)` or `power_on(start_command=...)`. No GPU instance was created or powered on.
- GitHub Actions still reports failed jobs with `steps: null` and `logs_url: null`; no usable logs or artifacts are available. Tests are authored but not yet verified by a functioning CI execution.
- Next: inspect the actual generated command with `bash -n` in a Linux test environment; run the focused pytest suites; wire token issuance and generated start command into the dispatcher only after lifecycle safety checks; then revisit Actions runner/log availability.

- Follow-up: the AutoDL command test now also runs `bash -n` when Bash is available, so CI can catch malformed multiline startup commands without launching an instance. This is authored test coverage only; Actions still does not expose execution steps/logs.
- CI diagnosis refinement: on head `6f89ecd7793b78abd1cbb5bc14fa17d84bd9d39e`, the GitHub check-run API shows three failed check runs (two cloud-jobs invocations and one legacy-jianpu), each completing roughly 1–2 seconds after start and each reporting exactly one annotation. The jobs endpoint still returns `steps: null` and `logs_url: null`; the available GitHub fetch surface cannot retrieve annotation bodies. This strongly suggests failure before normal test steps, but the exact runner/annotation cause remains unverified. Do not interpret these as pytest failures.


## 2026-11-25 continued — AutoDL worker provisioning sequence

- Added `musicmaster/cloud/dispatcher.py` with explicit `create_autodl_worker(...)` orchestration.
- It generates a high-entropy one-time bootstrap token, stores only its SHA-256 hash in the bootstrap-token table, and creates the worker row.
- Important race fix: AutoDL instance creation is called **without** a startup command first. The returned `pro-...` instance ID is persisted to both the bootstrap-token record and worker record. Only then does the dispatcher call `power_on(..., start_command=...)`. This prevents a fast boot from consuming the one-time token before its instance ID is associated in Postgres.
- On failure, the worker is marked `error`. If an instance was already created, its ID is intentionally retained for operator recovery; the helper does not automatically power off or release a paid resource.
- Added `tests/test_cloud_dispatcher.py` for operation ordering, token hashing, link-failure safety, and invalid worker IDs. Added it to the Cloud jobs CI test command.
- At the time of this earlier note it was not yet exposed through HTTP; the subsequent section records the authenticated manual endpoint added afterward. It is not wired to queue-depth polling, AutoDL status monitoring, idle shutdown, or release. It has not been executed against AutoDL; no GPU instance was created or powered on.
- Current PR head before this note: `cd05d2dadcf1fc003d46f4e3585f8220fc8a9db6`; subsequent workflow/docs/handoff commits may advance it. Always re-read the PR head.
- CI has not yet provided a usable test result. The new tests are authored but not verified in a functioning runner.
- Next: add an authenticated dispatcher endpoint/config validation, test it with injected fake AutoDL client and store; then implement durable single-dispatcher lease/queue trigger and instance lifecycle monitoring. Do not run paid GPU.


## 2026-11-25 continued — authenticated manual provisioning endpoint

- Added `POST /api/internal/dispatcher/workers` to `musicmaster/web/cloud_api.py`, protected by a separate `MUSICMASTER_DISPATCHER_TOKEN` (requires at least 32 characters and constant-time comparison). Worker credentials do not authorize provisioning.
- Provisioning settings are server-side only: `MUSICMASTER_API_URL`, `MUSICMASTER_AUTODL_IMAGE_UUID`, `MUSICMASTER_AUTODL_CUDA_V_FROM`, and `AUTODL_PRO_TOKEN`. No image, GPU type, AutoDL token, or bootstrap token is accepted from the caller.
- The endpoint provisions exactly one worker per authorized POST. It is manual-only; upload/queue events do not call it. **Calling it can incur GPU charges.** It has not been called in this development session.
- Added API tests for missing dispatcher configuration, bad credentials, and server-side settings injection. CI includes the dispatcher orchestration test; the existing API test file already runs in the cloud-jobs workflow.
- Remaining before safe real use: ensure the dispatcher credential is generated/stored securely in the API host, validate the AutoDL image and `cuda_v_from` against the selected image, implement a durable capacity/lease gate to prevent multiple concurrent requests from creating excess instances, add provider status/heartbeat/idle shutdown/release handling, and run tests in a functioning CI environment. No GPU was created or powered on.

- Latest verification snapshot after the manual endpoint/docs commits: PR head `1f6dbcadc6a925b7d09430b84c2e69249521c9df`, PR remains Open/Draft and unmerged. Three check runs (two cloud-jobs and one legacy-jianpu) again failed within about 1–2 seconds, each with one annotation. The current tool surface still cannot retrieve annotation bodies or usable job steps/logs. Treat this as an unresolved Actions pre-step/runner issue, not evidence that pytest failed or passed.


## 2026-11-25 continued — PostgreSQL dispatcher lock and capacity control

- Added `PostgresJobStore.run_with_dispatch_capacity(max_workers, operation)`.
- Uses a transaction-scoped PostgreSQL advisory lock (`pg_try_advisory_xact_lock(20261125, 1)`) to serialize provisioning across multiple API processes. A concurrent request fails fast instead of creating another instance.
- While holding the lock, counts workers in `starting`, `idle`, `busy`, and `stopping`. If count reaches the configured cap, provisioning is rejected. Stale active rows intentionally count against capacity until lifecycle reconciliation is implemented.
- Updated the authenticated manual endpoint to use this gate and added `MUSICMASTER_AUTODL_MAX_WORKERS` (integer 1–10, default 1). Capacity contention/full returns HTTP 409; invalid configuration returns HTTP 503.
- Added tests for lock-held operation ordering, lock contention, full capacity, invalid limits, endpoint capacity injection and conflict response. No schema migration is required.
- This lock is held across the provider create/power-on operation. This is deliberate for cross-process exclusion; keep the AutoDL API timeout bounded. It is not a queue autoscaler and does not provide crash recovery for provider-side partial creation. Active stale worker records are conservative capacity reservations until the lifecycle reconciler is built.
- No paid GPU instance was created or powered on. Tests have been authored but still require a functioning GitHub Actions run.


## 2026-11-25 continued — idle worker shutdown and confirmed release

- Added `musicmaster/cloud/lifecycle.py` with a conservative, manual reconciliation function.
- Added Postgres methods to read a worker, atomically mark only stale `idle` workers as `stopping` (requires `active_job_id IS NULL`, linked instance ID, and old heartbeat), and mark `stopped` only after provider release succeeds.
- Added authenticated endpoint `POST /api/internal/dispatcher/workers/{worker_id}/reconcile`. `MUSICMASTER_AUTODL_IDLE_SECONDS` defaults to 300 seconds and is bounded to 60–86400.
- Lifecycle sequence: stale idle → DB `stopping` → query provider status → if `running`, request power-off and wait; if provider explicitly reports `shutdown` or `stopped`, call release; only after successful release write DB `stopped`. Unknown/transitional provider states are non-destructive and remain `stopping`.
- AutoDL official API docs confirm the Pro status, power-off, and release endpoints and state that release should follow shutdown. Status values other than the documented `running` example are treated conservatively; only `shutdown`/`stopped` permit release.
- Added lifecycle unit tests for power-off-before-release, confirmed shutdown, unknown status, busy worker, non-stale worker, and missing instance ID. Added API tests for dispatcher auth and heartbeat restrictions.
- Shutdown race protections: worker heartbeat now accepts only `idle`/`busy`; the SQL update refuses to revive `stopping`/`stopped`/error workers and requires active-job consistency. Job claiming locks the worker row and refuses new claims once stopping. Re-registration cannot resurrect a stopping worker.
- Removed the worker-side idle auto-exit path; idle shutdown is now owned by the server-side lifecycle controller rather than a GPU process attempting to mark itself stopping.
- This is manual-only and has not been called. No GPU was created, powered on, powered off, or released. Provider/Postgres cannot be atomic; a process crash after successful provider release but before DB finalization still requires operator reconciliation. No automated scheduler or lifecycle sweeper is wired yet.


- Follow-up hardening: `claim_next` now locks the worker row and permits a claim only for `starting`/`idle` workers with no active job; an already-busy worker cannot claim a second job. Re-registration cannot change a busy worker back to idle. Added regression coverage.
- The worker no longer has its own idle auto-exit branch. It continues heartbeating while idle; only the server-side, dispatcher-authenticated lifecycle reconciler may reserve shutdown.
