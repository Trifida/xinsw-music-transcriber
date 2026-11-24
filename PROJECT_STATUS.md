# 心思维 AI 扒谱助手｜项目总档案

盘点日期：2026-11-20

本文件是项目状态交接入口；产品范围以 docs/PRODUCT_ROADMAP_V1_V2.md 为准。每次开始新一轮开发前，先阅读路线图和本文件，再核对 GitHub 指定分支及 Google Colab 运行状态。

本次整理原则：只建立档案，不删除仓库、分支、文件、模型或本地环境；不合并实验分支；不改动现有可运行程序。

## 1. 产品目标与版本边界（以产品路线图为准）

本项目当前正式开发版本为 V1，唯一详细产品范围见：
docs/PRODUCT_ROADMAP_V1_V2.md

### V1：带歌词打谱

用户上传歌曲音频，系统按既定流程分离人声 / 伴奏，从主唱人声提取旋律音高和节奏；歌词由用户手动输入或粘贴，系统按音符顺序初步对齐，用户检查、逐字修改后生成带歌词的 MusicXML、简谱、五线谱及相关文件。

V1 包含：音频处理、人声分离、主旋律音高与节奏识别、自动定调、手动歌词输入、歌词逐音对齐与人工校正、拖腔延续和空歌词处理、MIDI / MusicXML / 简谱 / 五线谱 / SVG / PDF 输出。

**V1 不包含自动语音识别（ASR）、自动歌词识别或自动听写歌词。** 用户没有输入歌词时，V1 只生成无歌词乐谱，不得自动调用语音识别服务。

### V2：自动歌词识别与辅助对齐

自动语音识别、自动歌词转写及自动辅助对齐属于 V2。仓库中现存的 ASR 适配器和相关测试仅作为技术储备，必须与 V1 运行链路隔离；未经 V2 正式规划和验收，不得接入 V1 页面、API、任务流程或健康检查。

伴奏谱必须基于真实伴奏音频识别，不得根据人声主旋律凭空编造钢琴伴奏。人声分离音轨可能残留混响、合唱和伴奏，模型评估必须记录来源与质量。

## 2. 唯一正式开发主线

- GitHub 仓库：Trifida/xinsw-music-transcriber
- 地址：https://github.com/Trifida/xinsw-music-transcriber
- 正式分支：main
- 统一运行环境：Google Colab；后续代码测试和音频运行均在 Colab 执行，不要求本地电脑运行。
- 统一 Notebook：Google Drive 中的 XinsW_Music_Transcriber_Main.ipynb。
- 模型与测试数据：Google Drive；程序代码以 GitHub 指定分支为准。
- 已知 main 基准提交（本轮盘点时）：3dc0dcfb67f5f91d636c5107ec2a0981c289505e（setup_core 安装顺序修复）
- 正式开发规则：新功能优先在 main 上以小步提交开发；实验先开独立分支，验收后再选择性移植，不整条合并未经验证的实验分支。

### 历史本地环境记录（仅供追溯）

此前 Windows 本地环境曾用于核心程序和网页验证，这些记录保留作历史参考。当前统一执行环境已经改为 Google Colab，不再要求办公室或家中电脑分别配置 Python、安装依赖或运行测试。

当前 Colab 曾盘点到 Python 3.13.18、PyTorch 2.14.1+cpu、CUDA unavailable；这是当次运行时状态，不是最终环境配置。后续先核对旧 Notebook 的成功运行记录，再决定是否迁移依赖和模型加载步骤。

## 3. 页面与功能入口辨别

### A. 声谱坊主界面（正式 UI 候选入口）

- 服务页面：由当前运行环境提供的主界面（Colab 测试时以实际访问地址为准）
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

- 页面路径：/xinsw.html（Colab 测试时以实际访问地址为准）
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
- 当前 Colab 分配的 GPU / CPU 环境能否运行分离模型，以及耗时和峰值内存。
- 分离模型是否已下载、版本与许可证是否适用。
- 主唱提取质量、八度错误、音符起止、节奏和真实歌曲识别准确度。
- V1 手动歌词输入、逐字对齐与简谱歌词排版的端到端质量；自动歌词识别明确留到 V2。
- PDF/SVG、MIDI、MusicXML 等所有产物是否能由真实歌曲稳定生成。

### 已知环境约束

- scripts/setup_sep.py 当前说明的是独立拆声环境，依赖 audio-separator 与 CUDA/PyTorch GPU 路线。
- Colab 当前运行时可能没有 GPU；不得把 CPU 版 PyTorch 当作 GPU 环境。
- 不在环境盘点阶段安装或替换 PyTorch / CUDA；先核对旧 Notebook 成功记录。
- 不把 CREPE 直接应用于完整混音来代替人声分离。

## 5. 值得保留的实验成果（不自动合并）

历史私有 PR 中的 faster-whisper / WhisperX / CTC 自动歌词识别与对齐代码属于 V2 技术储备，不属于当前 V1 交付范围。

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

## 8. 正式开发路线（按 V1 优先）

1. 在统一 Colab Notebook 中完成只读环境与 Drive 目录盘点。
2. 核对旧 Notebook 的成功运行代码、执行输出、模型路径和依赖版本。
3. 明确 BS-RoFormer 人声分离和旋律识别各自可复现的运行流程。
4. 在 Colab 中按旧环境证据恢复依赖与模型，不盲目重装。
5. 运行 SmartKeyAnalyzer 单元测试，再用真实歌曲验证自动定调。
6. 使用标注清楚来源与质量的人声音轨验证音高、节奏、八度和乐句。
7. 复核 V1 手动歌词输入、逐音对齐、拖腔、空歌词及 MusicXML / 简谱 / 五线谱输出。
8. 单独验证伴奏音轨分析；任何钢琴伴奏谱必须来自伴奏音频的实际分析。
9. 完成 V1 端到端测试后，再单独规划 V2 自动歌词识别。

## 9. 每次继续开发前的检查清单

- [ ] 确认当前仓库是 Trifida/xinsw-music-transcriber。
- [ ] 确认当前 GitHub 指定分支。
- [ ] 先读 docs/PRODUCT_ROADMAP_V1_V2.md 和本文件。
- [ ] 确认本轮修改属于 V1；V2 功能不得混入 V1 运行链路。
- [ ] 确认统一 Colab Notebook 和 Google Drive 数据位置。
- [ ] 确认要修改的文件、接口和验收方式。
- [ ] 一次只推进一个明确任务，完成后记录提交号、测试结果和剩余问题。
- [ ] 不把尚未实测的功能标记为完成。

## 10. 状态更新记录

- 2026-11-20：建立项目总档案；确认公开主线仓库、独立 CREPE 测试页、整曲工作流实验分支及私有仓库 PR #12/#13 的定位。
- 2026-11-24：产品范围统一到 V1 / V2 路线图；V1 改为用户手动输入歌词，ASR 归入 V2 技术储备；统一运行环境改为 Google Colab。
