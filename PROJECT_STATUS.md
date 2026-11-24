# 2026-11-24｜当前有效开发基线（优先于下方历史记录）

> 本节是当前唯一有效状态。下方 2026-11-20 及更早内容属于历史档案；如与本节冲突，以本节为准。

## 唯一工作入口

- 仓库：`Trifida/xinsw-music-transcriber`
- 当前 Colab 正式工作分支：`feature/vocalparse-event-musicxml`
- 唯一 Colab Notebook：`notebooks/XinsW_Music_Transcriber_Main.ipynb`
- Notebook 会校验分支；发现已有目录位于其他分支时停止，不自动切换、不覆盖工作区。
- **注意：GitHub 默认分支目前仍是 `main`，且 `main` 与 VocalParse 分支存在分叉。禁止在未完成选择性整合和验证前，将 `main` 当作当前 VocalParse 工作版本，也禁止整分支强行合并。**

## 当前产品边界

- V1 唯一主旋律识别方向：VocalParse。
- 当前可复用能力：已保存 VocalParse JSON → 音乐事件 → MusicXML → 简谱/五线谱渲染；离线渲染不需要重新运行模型。
- 当前工作重点：调号、音符拼写、移调，以及 MusicXML、简谱、五线谱之间的一致性。
- V1 歌词只接收用户手动输入并进行编辑/对齐；自动歌词识别属于 V2，不进入 V1 网页、API、任务执行和健康检查。
- 拆声、简谱与五线谱互译、修音/换音色是独立功能，本轮旋律识别清理不删除、不重构它们。
- 历史识别结果、Drive 输出、VocalParse 样本和必要回归夹具保留；归档数据不自动成为正式运行入口。

## 本轮清理约束

1. 旧 CREPE、basic-pitch、ByteDance 旋律识别选择器和旧默认入口不得继续作为 V1 主流程。
2. 旧引擎依赖、旧测试、旧 Notebook 只有在确认没有被保留功能引用后才删除；否则先隔离/归档。
3. 不因旧 CREPE 测试缺依赖而安装 CREPE，也不以旧 CREPE 测试失败判定 VocalParse 输出链路失败。
4. 不重新运行已成功的 VocalParse 推理，不重新下载模型；优先复用 Drive 中已保存的识别结果。
5. 未经 Colab 验证的改动不得标记为已通过；不删除历史分支或历史提交作为“清理”手段。

## 当前尚未完成的整合事项

- `main` 仍保留 CREPE 默认的旧 `autopilot.py` 和多引擎 API/网页入口；尚未从正式默认分支移除。
- VocalParse 事件转换器在当前工作分支中，不能把它误称为已经完整接管 `main` 的在线音频推理入口。
- 两分支目前存在分叉；必须先对 `main` 的近期有效改动与 VocalParse 分支做逐文件选择性整合，再统一默认分支。禁止直接合并整条实验分支。
- 当前已完成的专项验证：V1 手动歌词契约测试 5 项通过；SmartKeyAnalyzer 测试 7 项通过。全量 pytest 中旧 CREPE 路径及缺少可选排版/测试依赖的失败，不代表 VocalParse 离线事件转换链路失败。

---

# 心思维 AI 扒谱助手｜项目总档案

盘点日期：2026-11-20

本文件是后续开发的唯一项目状态入口。每次开始新一轮开发前，先核对本文件、当前 Git 分支和本地工作区，不要凭聊天记录猜测项目位置。

本次整理原则：只建立档案，不删除仓库、分支、文件、模型或本地环境；不合并实验分支；不改动现有可运行程序。

## 1. 产品目标（唯一产品定义）

用户上传一首完整歌曲 MP3/WAV（人声与伴奏混合），系统自动完成：
1. 音频读取与预处理；
2. 自动分离人声和伴奏；
3. 从人声中尽可能提取主唱主旋律，减少和声、混响和伴奏残留干扰；
4. 识别音高、音符起止和节奏；
5. 输出 MIDI、MusicXML、五线谱和简谱；
6. 如启用歌词功能，识别中文歌词并与音符对齐；
7. 保存中间音轨、处理报告和最终产物，便于检查与返工。

**产品入口应当是一次上传完整歌曲的自动工作流。** 不应要求普通用户事先自行分离 vocals，也不能把“只上传已分离人声”的测试页面当作最终产品。

## 2. 唯一正式开发主线

- GitHub 仓库：Trifida/xinsw-music-transcriber
- 地址：https://github.com/Trifida/xinsw-music-transcriber
- 正式分支：main
- 本地目录：D:\xinsw\xinsw-music-transcriber\xinsw-music-transcriber
- 本地启动入口：仓库根目录的 启动.bat
- 主界面：http://127.0.0.1:7860/
- 健康检查：http://127.0.0.1:7860/api/health
- 已知 main 基准提交（本轮盘点时）：3dc0dcfb67f5f91d636c5107ec2a0981c289505e（setup_core 安装顺序修复）
- 正式开发规则：新功能优先在 main 上以小步提交开发；实验先开独立分支，验收后再选择性移植，不整条合并未经验证的实验分支。

### 本地环境已确认

- Windows 笔记本；Intel i7；16GB RAM；Intel 集成显卡；没有 NVIDIA CUDA GPU。
- Python 3.11.9；Git 2.55.0。
- 核心虚拟环境：仓库内 .venv。
- 核心安装脚本：python scripts\setup_core.py，本机此前已成功完成。
- 启动.bat 此前已成功打开本地网页；/api/health 曾返回 {"ok":true,"service":"musicmaster","static":true}。
- CREPE full 模型此前已准备完成。
- LilyPond CLI 尚未确认安装；PDF/SVG 乐谱渲染可能需要它。
- 已知测试音频：D:\HuaweiMoveData\Users\mona\Desktop\soul\vocals.mp3，约 273.08 秒、44.1kHz、双声道。它是预先分离的人声素材，只适合单独测试人声记谱，**不是完整歌曲自动扒谱的最终输入验收样本**。

## 3. 页面与功能入口辨别

### A. 声谱坊主界面（正式 UI 候选入口）

- URL：http://127.0.0.1:7860/
- 文件：musicmaster/web/static/index.html
- 前端桥接脚本：
  - musicmaster/web/static/js/api.js
  - musicmaster/web/static/js/separate.js
  - musicmaster/web/static/js/transcribe.js
  - musicmaster/web/static/js/convert.js
  - musicmaster/web/static/js/vocal.js
- 页面包含拆声、记谱、互译、重塑等功能区。
- 重要说明：HTML 中存在“静态 UI / 艺术设计稿”的注释，但页面同时加载了前端 API 桥接脚本。不能仅凭该注释断定整页没有后台功能。需要逐个核验按钮、请求、服务端路由和实际任务结果。
- 当前定位：保留为主产品界面和后续整合入口；尚不能仅凭 UI 外观宣称所有功能均已端到端验收。

### B. 独立心思维测试页（非正式完整歌曲入口）

- URL：http://127.0.0.1:7860/xinsw.html
- 文件：musicmaster/web/static/xinsw.html 及 musicmaster/web/static/js/xinsw.js
- 已知行为：上传音频后调用 POST /api/transcribe，轮询 /api/job/<job_id>，固定使用 CREPE。
- 定位：测试已分离主唱音轨的记谱流程。
- 限制：它不负责先将完整混音分离成人声和伴奏。不要把它作为用户最终产品入口，也不要要求用户为了正常使用产品先自行制作 vocals.mp3。

## 4. 当前主线代码的已知能力与缺口

### 已存在的组件/接口线索

- musicmaster/web/runners.py 中有 run_transcribe：对输入音频调用现有自动记谱程序。
- 同一文件中有 run_separate：调用独立分离流水线。
- 前端拆声、记谱等模块有各自 API 桥接脚本。
- CREPE 核心安装和单独人声音轨记谱环境已在本机跑通。

### 需要继续核验，不能误报为已完成

- 声谱坊页面每个按钮对应的服务端路由是否存在、是否可用。
- 完整混音上传是否能在一个任务中自动完成拆声和记谱。
- 当前 Windows Intel CPU/集显环境能否运行分离模型，以及耗时和峰值内存。
- 分离模型是否已下载、版本与许可证是否适用。
- 主唱提取质量、八度错误、音符起止、节奏和真实歌曲识别准确度。
- 歌词识别/逐字对齐与简谱歌词排版的端到端质量。
- PDF/SVG、MIDI、MusicXML 等所有产物是否能由真实歌曲稳定生成。

### 已知环境约束

- scripts/setup_sep.py 当前说明的是独立拆声环境，依赖 audio-separator 与 CUDA/PyTorch GPU 路线。
- 本机没有 NVIDIA GPU，因此不能直接把现有 CUDA 拆声安装说明视为本机可用。
- 不安装 CUDA，不把 CREPE 直接应用于完整混音来代替人声分离。
- 本机先做短音频 CPU 可行性验证，再决定是否采用更轻的 CPU 分离模型；不预先承诺处理速度。

## 5. 值得保留的实验成果（不自动合并）

### A. 当前公开仓库的实验分支

- 仓库：Trifida/xinsw-music-transcriber
- 分支：fix/crepe-chunk-progress
- 已知内容：
  - CREPE 模型复用与约 12 秒分块推理、块间重叠；
  - 记谱进度回传；
  - musicmaster/workflows/full_transcribe.py 整曲工作流；
  - AutoDL Pro 云 GPU 工作节点实验；
  - 对拆声与记谱 runner 的复用。
- 本轮比较结果：相对 main 为 diverged，领先 28 个提交、落后 1 个提交。**不要直接整分支合并**；需要按文件和提交逐项审查、挑选移植。
- 整曲工作流设计：完整混音 → run_separate → 定位最终主唱与伴奏 → run_transcribe → 检查 notes.json、MIDI、MusicXML → 写出 job_result.json。
- 重要限制：该工作流调用的拆声 runner 仍依赖独立拆声环境；它是命令行工作流实验，不代表网页单入口已经接通，也不代表本机 CPU 拆声已解决。

### B. 原私有仓库的关键 PR

- 仓库：Trifida/jianpu-gongfang（私有历史仓库，保留，不删除）
- PR #13：https://github.com/Trifida/jianpu-gongfang/pull/13
  - 目标：完整歌曲自动分离主唱并生成乐谱。
  - 设计链路：BS-RoFormer → Karaoke RoFormer 去和声 → UVR 去混响 → CREPE。
  - 另有 faster-whisper 中文歌词识别、WhisperX/CTC 字符级对齐、MusicXML 歌词写入与简谱歌词同步等实验。
  - PR 描述记录了 CPU 测试、若干自动化测试和 GPU 队列/模型缓存保护。
  - 验收边界：尚未在真实中文歌曲与真实 GPU 环境完成完整端到端验收；最终歌词对齐和简谱版面仍需人工核对。
- PR #12：https://github.com/Trifida/jianpu-gongfang/pull/12
  - 目标：将上游 MusicMaster 作为隔离的独立记谱引擎进行实验。
  - 保留 CREPE CPU 推理与独立评估工具的成果。
  - PR 明确未完成生产 React/API 集成、真实歌曲准确度验收及大陆模型下载可靠性验证。
- 以上 PR 都是技术档案，不视为已合并的正式产品能力。

## 6. 历史仓库与外部参考

### 历史仓库（保留但停止作为新开发入口）

- Trifida/jianpu-gongfang：原私有项目，保留全部分支、PR、提交历史；后续按需查阅。
- TrifidaM/jianpu-gongfang：另一个旧公开仓库；与当前正式主线不是同一仓库，不作为新开发入口。

### 上游/第三方参考

- 上游 MusicMaster：https://github.com/Cohenjikan/MusicMaster
- CREPE、audio-separator、UVR/Demucs 等项目：按实际使用的代码、模型权重分别记录版本、许可证和下载来源。
- 不把上游仓库、模型权重或第三方代码误称为本项目自研成果。

## 7. 失败经验与禁止重复的做法

1. 不再从错误的旧仓库启动新开发。
2. 不再把根页面和 /xinsw.html 混为同一个工作流。
3. 不要求最终用户先自行分离人声；完整混音是产品输入。
4. 不把“网页有按钮”当成“后台功能已验证”。
5. 不把“CREPE 能识别 vocals.mp3”当成“完整歌曲自动扒谱成功”。
6. 不在无 NVIDIA GPU 的本机照搬 CUDA 安装步骤。
7. 不因实验分支提交较多就整条合并；必须审查差异、依赖、测试和许可证。
8. 不重复安装已经成功的核心环境，除非检测到环境损坏或版本确有必要变更。
9. 不删除旧仓库、分支、模型或测试结果来“清理”；先建立清单和备份，再经用户确认。

## 8. 正式开发路线（下一步）

### 第 1 步：主线代码审计（优先）

逐项核对声谱坊主页面的四个模块：前端事件 → API URL → 服务端路由 → runner → 输出文件。形成接口矩阵，标明“已接线 / 可运行 / 已实测 / 未验证”。

### 第 2 步：接入单入口完整歌曲工作流

以已存在的 full_transcribe.py 为参考，评估将整曲工作流接入声谱坊主界面所需的最小改动。保留现有拆声、记谱模块，不重做已有算法，不破坏独立模块测试能力。

### 第 3 步：本地 CPU 拆声可行性验证

先评估 Windows、Intel i7、16GB RAM 下可运行的 CPU 分离方案；以短音频进行速度、内存和分离质量测试。通过后再处理完整歌曲。

### 第 4 步：端到端质量验收

以完整混音歌曲验收：人声/伴奏分离、主唱旋律、八度错误、音符时值、MIDI、MusicXML、五线谱、简谱和歌词同步。保存输入、各阶段音轨、日志、报告和输出。

### 第 5 步：部署评估

本机验证后再比较中国大陆 GPU 云方案与按任务启停成本；云部署不是当前本地开发的前置条件。

## 9. 每次继续开发前的检查清单

- [ ] 确认当前仓库是 Trifida/xinsw-music-transcriber。
- [ ] 确认当前分支是 main，或明确说明正在处理哪个实验分支。
- [ ] 先读本文件的“当前状态”和“下一步”。
- [ ] 确认要修改的文件、接口和验收方式。
- [ ] 一次只推进一个明确任务，完成后记录提交号、测试结果和剩余问题。
- [ ] 不把尚未实测的功能标记为完成。

## 10. 状态更新记录

- 2026-11-20：建立项目总档案；确认公开主线仓库、本地运行入口、独立 CREPE 测试页、整曲工作流实验分支及私有仓库 PR #12/#13 的定位。此次仅新增档案文件，不删除、不合并、不改动现有程序。
