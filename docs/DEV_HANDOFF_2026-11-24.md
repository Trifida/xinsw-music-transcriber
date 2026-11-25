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


## 2026-11-25 continued — interrupted AutoDL release recovery

- Rechecked PR #12 at HEAD `35fdb1455ce9b8f3a01eae9e5b0207ea069ae9f1`: Open / Draft, base `main`, head `deploy/v1-production`; no merge or production deployment.
- The previous lifecycle flow had a crash window: AutoDL release could succeed, then the API process could fail before `mark_worker_stopped_after_release`. A later status lookup might fail because the instance no longer exists, leaving the DB row permanently `stopping` and consuming capacity.
- Added `AutoDLProClient.find_instance()`: validates the documented list response, scans every page up to the provider's advertised `max_page`, rejects malformed/incomplete pagination, and returns `None` only after a complete scan.
- Updated `reconcile_idle_worker()`: if the status lookup errors, it performs the complete list scan. If the instance is still listed, it keeps the worker `stopping`; if absent from the complete list, it finalizes DB state to `stopped`. If the list lookup also fails or is incomplete, it does not finalize or release anything.
- Added tests for multi-page match, complete absence, malformed pagination, interrupted-release recovery, still-listed instances, and list API failure.
- No migration is needed: existing worker states already support `stopping` and `stopped`.
- This remains conservative recovery only. No GPU API was called; no instance was created, started, powered off, or released. The endpoint remains manual-only; no scheduler/sweeper is wired.
- AutoDL's official Pro API documents the paginated `/api/v1/dev/instance/pro/list` response with `data.list` and `data.max_page`, plus the status and release endpoints: https://autodl.com/docs/instance_pro_api/.
- Latest observed Actions at the prior HEAD still fail within 1–2 seconds with empty steps/log URLs; this is unresolved and must not be represented as a pytest failure or success.

### Next
1. Verify the focused tests in a real Python/Linux environment and inspect the new commit's Actions checks.
2. Add a bounded batch stale-idle sweep endpoint (dry-run by default; no provider mutations in dry-run), still manual-only.
3. Add durable queue-trigger/idempotency before enabling any automatic provisioning.
4. Keep all production, Neon-main, Render deploy, and paid AutoDL operations behind explicit authorization.

- Follow-up hardening: status recovery catches only the AutoDL provider API error type (not arbitrary programming exceptions), preserves the original status error if the list lookup also fails, and accepts a valid empty listing (`max_page: 0`, empty list) while rejecting inconsistent zero-page responses.


## 2026-11-25 continued — bounded idle-worker sweep

- Added `PostgresJobStore.list_stale_idle_workers()`, a read-only query for stale workers with status idle, no active job, and a linked AutoDL instance. Candidates are ordered oldest heartbeat first and bounded to 25.
- Added dispatcher-authenticated `POST /api/internal/dispatcher/workers/reconcile-idle` with `dry_run: true` by default. Dry-run only lists candidates and does not instantiate AutoDL client or mutate provider/DB state.
- Explicit `dry_run: false` runs the existing conservative reconciler sequentially for at most 25 candidates. Per-worker failures are isolated and only exception class is returned; provider messages and secrets are not exposed.
- Added fake-DB and API tests for query filters/bounds, default dry-run, auth, and explicit execution with per-worker error isolation.
- No cron job or queue-triggered automation is configured. No GPU/provider API was called. The batch endpoint can power off/release resources only when explicitly invoked with authenticated `dry_run: false`.


## 2026-11-25 session close — release recovery and idle sweep

**Branch / PR snapshot before this handoff update**
- PR #12: Open / Draft / unmerged; base main; head branch deploy/v1-production.
- Latest implementation commit before this documentation-only update: 75070c99ae763f3be07f7be56192bff4065c0d15.
- PR had 112 commits at the time of verification.
- No production deployment, main merge, Neon production-main change, or paid AutoDL operation occurred.

### Code added in this session
- AutoDL list-based recovery for interrupted release:
  - AutoDLProClient.find_instance() validates and fully scans paginated data.list / data.max_page.
  - A missing instance is accepted only after a complete valid scan; malformed/incomplete pagination is an error.
  - Lifecycle catches only AutoDLProError from status lookup. If the instance remains listed, worker stays stopping; if absent after a complete scan, DB may finalize to stopped. If listing fails, the original status error is preserved and DB is not finalized.
  - Handles valid empty listing (max_page: 0, empty list) and rejects inconsistent zero-page records.
- Bounded manual idle-worker sweep:
  - PostgresJobStore.list_stale_idle_workers() is read-only and selects only stale idle rows with no active job and a linked instance.
  - POST /api/internal/dispatcher/workers/reconcile-idle is dispatcher-authenticated, defaults to dry_run: true, and caps batches at 25.
  - Dry-run never creates an AutoDL client or mutates DB/provider state.
  - dry_run: false explicitly invokes the conservative reconciler sequentially; failures are isolated and provider error details are not exposed.
- Added tests for paginated listing, empty/malformed pages, release recovery, dry-run, auth, query constraints, batch bounds and per-worker error isolation.
- Updated docs/WORKER_SOURCE_BUNDLE.md with the recovery and sweep contracts.

### CI status — still unresolved
- At HEAD 75070c99ae763f3be07f7be56192bff4065c0d15, the Cloud jobs and legacy jianpu checks both completed as failure within approximately 1–2 seconds.
- GitHub job responses again returned steps: null and logs_url: null; fetching the log archive returned BlobNotFound.
- This does not establish that pytest or compilation ran, and does not establish pass/fail of the new tests. No local test execution was available in this session.
- Continue treating CI runner/check annotation diagnostics as P0. Do not claim the code tests passed until an actual test process has run and produced results.

### Safety / next steps
1. On next session, recheck PR HEAD and Actions before editing.
2. Obtain a functioning Linux/Python test run for the focused cloud suites; investigate the check-run annotation/runner failure separately from application tests.
3. Review the idle sweep endpoint and release recovery in an executable test environment.
4. Only after test confidence, consider a scheduled sweep (Render Cron or equivalent), but keep it disabled/manual until explicitly authorized.
5. Queue-triggered provisioning still needs durable idempotency/deduplication and must not automatically incur GPU charges without explicit approval.
6. Do not merge, deploy, change Neon production main, or create/start/power-off/release paid AutoDL instances without explicit authorization.

**Cross-computer resume prompt:** Continue from this handoff, first inspect PR #12 and the latest deploy/v1-production HEAD/checks, then validate the release-recovery and dry-run sweep changes. Do not modify main, deploy production, or call AutoDL provider mutation endpoints.


## 2026-11-25 continued — isolate GitHub Actions runner failure

- Rechecked PR #12 at HEAD 216c8d3928a37015670a4611aec9f91b03b44455: Open / Draft / unmerged; no production changes.
- Retried the failed Cloud jobs and original jianpu workflow runs using GitHub's failed-job rerun operation. Both retries again completed as failure within seconds; job details still had null steps/log URLs and log downloads returned BlobNotFound.
- Added a deliberately minimal workflow at .github/workflows/ci-runner-diagnostic.yml. It uses no checkout/setup actions or dependencies: it only runs a shell step, prints OS/architecture, and checks python3 --version. It is triggered by push/PR to deploy/v1-production and can also be manually dispatched.
- Interpretation:
  - If this minimal job also fails before exposing a step, investigate repository Actions availability, hosted-runner allocation, account/org policy, or GitHub service/runner infrastructure.
  - If it succeeds, the runner is functional and the failure is specific to the existing workflow/action/job configuration; compare the first failing step and logs.
- No production deployment, main merge, Neon production-main modification, or AutoDL API mutation was performed.


## 2026-11-25 continued — orphaned error-worker safety

- Code review found a capacity-accounting gap: a worker could be marked error after AutoDL creation had succeeded, leaving a linked (and potentially billable) instance while the capacity query excluded error rows.
- Capacity now counts error workers only when an AutoDL instance UUID is linked. Errors before instance creation do not consume GPU capacity.
- Read-only stale reconciliation candidates now include both idle and error workers, still requiring no active job, a linked instance, and an expired heartbeat threshold.
- The atomic idle-to-stopping transition now also accepts stale error rows. Fresh error rows are not touched; the lifecycle still confirms provider state before any power-off/release.
- Added tests for error-worker capacity accounting, candidate discovery, stale-error shutdown, and fresh-error protection.
- No schema change was needed because the existing status check constraint already includes error. No provider API mutation was performed.


## CI runner diagnostic result (2026-11-25)

- The new minimal workflow (.github/workflows/ci-runner-diagnostic.yml) was triggered by push on commit 03fb2fafad02bd3fccd6eefaaea28ae1d0aa215e.
- It completed as failure in approximately 3 seconds. Its only job returned steps: null and logs_url: null; log download again returned BlobNotFound.
- Because this diagnostic contains no checkout, setup action, dependency installation, Python test, or repository code, the failure occurs before any authored shell step can be confirmed as executed.
- This is strong evidence of a GitHub Actions job/runner provisioning or reporting problem, not evidence of a failing application test. The exact GitHub-side root cause remains unconfirmed because the job exposes no steps, annotations, or logs.
- Do not keep changing application code to chase these failures. The next CI task is to inspect repository Actions settings/hosted-runner availability and GitHub service/account restrictions in the GitHub UI or account owner settings. Then rerun the minimal diagnostic. Only after it succeeds should cloud and jianpu pytest workflows be used as code-quality gates.

## 2026-11-25 continued — unresolved AutoDL create timeout safety

- Rechecked PR #12 before editing: Open / Draft / unmerged; branch `deploy/v1-production`; HEAD was `5cfc171a658025b737de03b43a9eed6435e9a0e4`.
- Reviewed the AutoDL create call window. If AutoDL creates a paid instance but the response is lost/times out before `instance_uuid` is persisted, the worker is marked `error` with no linked instance ID. The prior capacity query excluded this row, which could permit a second paid create request.
- Fixed `PostgresJobStore.run_with_dispatch_capacity()`: every `error` worker now reserves capacity, whether or not `instance_uuid` is known. This intentionally trades temporary capacity blockage for protection against duplicate paid instances. An unresolved error row requires operator investigation before another provisioning attempt.
- Updated `tests/test_cloud_dispatcher.py` to assert that unresolved error rows are included in the capacity predicate, including the no-instance-ID case. Updated `docs/WORKER_SOURCE_BUNDLE.md` with the operational rule.
- Commits from this safety fix: `7b8b00c73071a87f6330c4234ecefd604610483c` (capacity SQL), `ac278a49c1af1863ec22aaa64c66afa329036100` (regression test), followed by the documentation commits recorded below.
- Latest CI snapshot before this fix: on HEAD `5cfc171a658025b737de03b43a9eed6435e9a0e4`, the minimal runner diagnostic, cloud-jobs, and legacy-jianpu jobs all failed in 1–2 seconds. All three jobs had `steps: null` and `logs_url: null`; log downloads returned BlobNotFound. The GitHub check-run records each had one annotation, but the current GitHub fetch surface rejected the annotations endpoint. No pytest execution can be confirmed.
- GitHub's public status history contains resolved Actions incidents earlier in November, but that does not establish a current incident or explain this repository's failures. The current observed failure remains unclassified at the GitHub job/check layer.
- No CI tests have been represented as passing. No paid AutoDL create/start/power-off/release API was called. No production deploy, main merge, or Neon production-main change occurred.

### Next actions
1. Recheck the new HEAD and its workflow runs after the documentation commits.
2. Investigate the check-run annotation through the GitHub web UI or repository owner account; the API currently shows only annotation count, with no accessible step/log details.
3. Run the focused dispatcher/lifecycle/bootstrap pytest suites in a functioning Linux/Python environment before relying on the change.
4. Design an operator recovery path for ambiguous `error` rows with no instance ID. Do not automatically retry or free capacity based only on a missing ID; AutoDL create may have succeeded remotely.
5. Keep all paid provider mutations, production deployment, main merge, and Neon production changes behind explicit user authorization.

## Post-fix verification snapshot — 2026-11-25

- The safety fix and its documentation advanced PR #12 to HEAD `33d105d7edbf31c26f6e230ff97eb1768f9f44c9`; PR remains Open / Draft / unmerged, base `main`, head `deploy/v1-production`.
- New Cloud jobs, runner diagnostic, and legacy jianpu checks were triggered for the updated branch. All three completed as failure within about 1–2 seconds. The job API again returned `steps: null` and `logs_url: null`. No test execution is confirmed.
- The current PR head has no successful CI result. Do not interpret the failure as proof that the capacity fix is wrong, and do not interpret the missing logs as proof that tests passed.
- The latest capacity query now reserves a slot for every `error` worker row, including rows without an AutoDL instance ID. This closes the duplicate-create retry gap conservatively but can leave capacity blocked until an operator investigates an ambiguous create result.
- No paid GPU/provider mutation, production deployment, main merge, or Neon production-main modification was performed.

## 2026-11-25 continued — deterministic AutoDL instance recovery

- Rechecked PR #12 before this work: Open / Draft / unmerged, branch `deploy/v1-production`; prior HEAD `820bb3b3e7da75a9797c3277264329cfaeeebc1d`.
- Verified the official AutoDL Pro create/list API contract: create accepts optional `instance_name`; the paginated list returns `uuid`, `name`, `status`, and `created_at`. Sources: https://www.autodl.com/docs/instance_pro_api/ and https://www.autodl.com/docs/instance_pro_api/ (create and list sections).
- New workers now use a deterministic compact provider name `XW-<24 hex chars>` derived from the worker ID. This allows a later exact-name lookup without adding a DB migration or storing a second correlation field.
- Added `AutoDLProClient.find_instances_by_name()`: it validates and scans every advertised page, checks pagination consistency, returns all exact-name matches, and fails closed on malformed/incomplete listings. It deliberately does not stop at the first match, so duplicates are detected.
- Added dispatcher-authenticated manual endpoint `POST /api/internal/dispatcher/workers/{worker_id}/recover-instance`. It accepts only an `error` worker with no instance UUID and no active job. Exactly one exact-name match is linked to the worker and unused bootstrap-token rows. No match returns `retry_safe: false`; multiple matches remain unlinked; incomplete listing fails closed.
- Added `PostgresJobStore.recover_worker_instance()`, which conditionally links only an unresolved error row and updates matching bootstrap-token rows in the same DB transaction. The method performs no AutoDL provider mutation.
- The recovery endpoint never powers on, powers off, or releases the provider instance. After a successful DB link, an operator must inspect the instance in AutoDL before deciding on a separate manual action.
- Important limitation: legacy ambiguous errors created before deterministic names used the generic instance label, so this exact-name recovery cannot identify them. They require manual investigation in the AutoDL console. A zero-match listing is not proof that a create request is safe to retry because provider listing may lag.
- Added tests for deterministic labels, complete paginated exact-name search, duplicate detection, malformed pagination, conditional DB linking, and endpoint outcomes (one match / no match / multiple matches / non-error worker). Also corrected an obsolete capacity-SQL assertion in `tests/test_cloud_dispatcher.py` that still expected the pre-error status predicate.
- CI on the implementation HEAD `0dbcb4511ae7ccdb53f88fa315ab2e0a2841f022`: Cloud jobs, legacy jianpu, and minimal runner diagnostic again failed in about 1–2 seconds. Every job response still had `steps: null` and `logs_url: null`; no test execution can be confirmed. A later code-only cleanup commit was added after that check snapshot, so the newest HEAD still needs a fresh check observation.
- No AutoDL API was called. No GPU was created, powered on/off, or released. No production deploy, main merge, or Neon production-main change occurred.

### Next
1. Fetch the newest branch HEAD and inspect the complete diff, especially the new recovery route and its database transaction.
2. Obtain a working Python/Linux test environment; CI currently cannot expose executed steps or logs.
3. Consider a safe operator workflow for legacy generic-name error rows. Do not infer a match from timestamps or GPU type alone.
4. Keep recovery manual and database-only. Do not automatically power on a recovered instance or retry a create request after a zero-match listing.

## Final check snapshot for this development turn — 2026-11-25

- Latest reviewed implementation commit before this note: `8018a7f6ccb77910f8c772962500a01e0f6c7612`; handoff/docs commit at the time of this check: `b7da0465979b57426bf260d3a37a87619274daf7`.
- PR #12 remained Open / Draft / unmerged, base `main`, head `deploy/v1-production`, 137 commits, 31 changed files.
- On HEAD `b7da0465979b57426bf260d3a37a87619274daf7`, runner diagnostic, cloud-jobs, and legacy-jianpu checks all completed as failure. Job responses again contained `steps: null` and `logs_url: null`. No test execution is confirmed.
- Reviewed the latest recovery diff: provider name is deterministic and worker-derived; matching scans all pages and detects duplicates; DB linking is conditional on unresolved error state; the endpoint is dispatcher-authenticated and makes no provider mutations.
- Remaining confidence gap: the Python test suite has not executed in a visible functioning runner. Do not merge or deploy based on static review alone.
- No AutoDL provider mutation, GPU start/stop/release, production deploy, main merge, or Neon production-main modification occurred.

## 2026-11-25 continued — idempotent manual worker provisioning

- Rechecked PR #12 at HEAD `5d8ddfd2de559ebe63c4f06541b187fd47a03602`: Open / Draft / unmerged; base `main`; head `deploy/v1-production`.
- Code review identified a duplicate-provisioning gap: the manual dispatcher endpoint previously generated a fresh worker ID on every POST. If a client timed out and retried while capacity allowed multiple workers, the retry could create another paid AutoDL instance.
- `POST /api/internal/dispatcher/workers` now requires a 16–128 character printable ASCII `Idempotency-Key` header. The server hashes it into a deterministic `dispatch-<sha256>` worker ID; the raw key is neither persisted nor returned.
- A replay finds the existing worker row and returns its state without creating an AutoDL client or calling create/power_on. An unresolved error row is returned with `retry_safe: false`; it must go through manual instance recovery rather than a new request key.
- `create_autodl_worker` accepts an optional caller-supplied worker ID while preserving its random-ID behavior for other callers.
- Added API tests for missing key, stable worker ID, replay behavior, and distinct keys against the capacity gate. Updated worker source bundle documentation.
- No database migration was added: the existing unique worker ID is the durable idempotency record. No AutoDL API was called; no GPU was created, powered on/off, or released.
- CI at the pre-change HEAD `5d8ddfd2de559ebe63c4f06541b187fd47a03602` again failed in 1–2 seconds. All three checks (runner diagnostic, cloud-jobs, legacy-jianpu) had `steps: null` and `logs_url: null`; GitHub check runs each showed one annotation but the annotations endpoint was unavailable through the current integration. No pytest execution is confirmed.

### Next
1. Review the idempotency implementation and tests at the new HEAD.
2. Restore a functioning Actions runner or run focused tests in a real Linux/Python environment; do not claim tests passed until an actual test process runs.
3. Before using the endpoint, callers must generate and retain one unique idempotency key per intentional worker request, reusing that exact key for all retries.
4. Keep all AutoDL provider mutations, production deployment, main merge, and Neon production changes behind explicit authorization.

## Idempotency follow-up implementation details — 2026-11-25

- The dispatcher route now validates `Idempotency-Key` (16–128 printable ASCII characters) and derives the worker ID as `dispatch-` plus the full SHA-256 digest.
- It checks `PostgresJobStore.get_worker()` before provisioning. Any existing row is returned as an idempotent replay, including unresolved errors; replay never constructs `AutoDLProClient` and never calls `create_autodl_worker`.
- The deterministic worker ID is passed into `create_autodl_worker(worker_id=...)`. Its prior random worker-ID behavior remains the default for other callers.
- Added tests for missing keys, stable worker ID propagation, idempotent replay without provider access, and distinct keys through the capacity gate. The invalid-capacity test now supplies a valid key.
- No migration was added; the worker primary key is the durable replay record. A concurrent same-key request may receive the existing fail-fast 409 while the first request holds the advisory lock; retrying with the same key after the first completes returns its durable record.
- On HEAD `cb2fc2113bb3f28d1da537be6ffb5a12cc904675`, all three GitHub Actions checks (cloud-jobs, runner diagnostic, legacy-jianpu) again failed immediately with `steps: null` and `logs_url: null`. This does not confirm pytest execution.

## 2026-11-25 继续开发与全路线图盘点

**PR #12 当前代码 HEAD（本轮盘点时）：** 93d2723aec6cdd7e8f3b1c63f4667a26942c37f0，后续文档提交会继续更新 HEAD。仍为 Draft / Open；未合并 main、未部署生产。

### 本轮新增开发

1. 云端任务上传 API 新增手动歌词字段，限制 100,000 字符，并把歌词文本写入任务 options。
2. GPU Worker 将任务 options 中的歌词传入整曲工作流。
3. 整曲工作流将歌词传入 V1 runner，并把 lyrics.txt、lyrics_alignment.json 纳入云端结果清单；manifest 增加歌词对齐状态。
4. 补充云端上传歌词保存、超长歌词拒绝、整曲工作流传递歌词的测试。
5. 发现并修复同一 Idempotency-Key 并发竞态：两次请求可能都在首轮查询时看到“无 Worker”；现在在 PostgreSQL advisory lock 内执行二次幂等检查，再决定是否检查容量和创建实例；AutoDL client 延迟到锁内幂等检查通过后才创建。新增竞态回归测试。

### 本轮路线图复核发现的真实缺口

- 当前本地记谱 UI 有整段歌词输入框和自动初步对齐；但在当前分支前端代码中未找到逐音编辑控件或人工修改回写 API。此前交接中将“逐音歌词编辑已完成”描述得过于乐观，需按本次代码核对结果更正。
- 当前云端上传 API 和 Worker 之前没有传递歌词；本轮已补代码和测试，但尚未通过可见 CI 或真实 GPU 验证。
- 当前整曲流程保留伴奏音轨，但只对主唱音轨做主旋律识别；没有完成真实伴奏多声部扒谱。
- Dispatcher 创建、实例恢复、空闲关机/释放目前均是人工触发；自动队列调度和定时生命周期管理尚未完成。
- 当前 Actions 仍没有可见 steps/logs，新增测试未确认执行。

### 测试 / 安全边界

- 本轮只更新 deploy/v1-production。
- 未调用 AutoDL；未创建、启动、关机或释放 GPU。
- 未修改 Neon production main，未部署 Render 生产服务，未合并 PR。
- 所有本轮新增测试均为“已编写、待真实运行”，不能标记为通过。
- 下一步先核验最新 HEAD 的 workflow 结果，再恢复测试运行；随后优先补齐逐音歌词编辑，而不是继续堆叠未验证的云调度功能。

### Final check snapshot for this continuation

- After the roadmap and handoff commits, PR #12 HEAD was 83a0cf9cc1e0beb1340aa50c9691a3c4c7152c29 (159 commits, 32 changed files; still Draft / Open / unmerged).
- On that HEAD, the CI runner diagnostic, cloud-jobs, and legacy-jianpu checks again failed within approximately 1–2 seconds. The latest Jobs API responses had steps=null and logs_url=null. The check-run API showed one annotation per failed check but its annotation endpoint was not accessible through the current GitHub integration. No pytest execution is confirmed.
- New cloud-lyrics tests and the advisory-lock idempotency-race regression test are therefore authored but unverified.
- The product roadmap snapshot is in docs/PRODUCT_ROADMAP_V1_V2.md. It explicitly corrects the prior overstatement about per-note lyric editing: current checked-in UI has a whole-lyrics text area and automatic first-pass alignment, but no per-note editing and save-back workflow was found.
