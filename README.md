# 心思维 AI 扒谱助手（XinsW Music Transcriber）

这是从原私有项目中独立整理的公开实验仓库。这里只保留 MusicMaster 扒谱实验所需的程序、网页、Notebook、测试和第三方许可文件；不包含原私有仓库的其他项目、用户音频、私人配置或开发日志。

## Colab 实验 Notebook（非 V1 完整产品入口）

打开 [XinsW Colab 免费运行版 v2](notebooks/XinsW_Colab_Free_v2.ipynb)。

这是用于验证**已分离主唱音轨记谱**的实验 Notebook，不代表 V1 完整产品工作流。V1 产品目标仍是完整歌曲音频进入既定流程，完成必要的人声 / 伴奏分离、主旋律记谱和用户手动歌词输入。当前 Colab 实验 Notebook 的范围与完整 V1 端到端验收状态必须区分。

### 使用前请注意

- Colab 免费 CPU/GPU 是否可用、运行速度和会话时长由 Google 决定，不保证每次都有免费 GPU。
- 首次运行需要安装 Python 依赖，并下载约 57.7 MB 的 CREPE full 模型。
- 上传的音频会传到 Google Colab 临时运行环境；请勿上传不愿交给该服务处理的音频。
- Colab 运行时断开后，临时网页和未下载的结果会消失，请及时下载。
- 导出 MIDI 不代表旋律识别准确。需要试听并检查音高、节奏，不能把合成音测试结果当成真实歌曲准确率。

## 目录说明

- `musicmaster/`：扒谱、谱面渲染和 Web 服务代码
- `notebooks/`：Colab 运行 Notebook
- `scripts/`：模型准备和辅助脚本
- `vendor/crepe/`：保留 CREPE 上游 Python 源码及其 MIT 许可
- `tests/`：基础测试
- `LICENSE`、`NOTICE`：项目与第三方许可声明

## 简谱排版：原版 jianpu-ly + LilyPond

简谱统一使用项目原有的 **jianpu-ly + LilyPond** 排版链路：

- MusicXML 转换为 jianpu-ly / LilyPond 源稿，再由 LilyPond 生成 SVG 预览和可打印 PDF。
- 简谱 PDF 与 SVG 使用同一套原版排版器，避免多个排版引擎输出不一致。
- 五线谱渲染、音高识别、MIDI 与 MusicXML 生成逻辑保持独立，不因简谱排版器调整而改变。
- Docker 镜像只安装 Python 音频服务、LilyPond 和必要字体；不再构建或携带额外的 Node.js 记谱排版运行时。

## 许可

项目代码许可见 [LICENSE](LICENSE)，第三方组件声明见 [NOTICE](NOTICE)，CREPE 上游许可见 [vendor/crepe/LICENSE](vendor/crepe/LICENSE)。模型权重由运行时单独下载，不随仓库分发。商用前应逐项核查代码、模型权重和训练数据的许可。

## V1 歌词输入与简谱排版

V1 采用**用户手动输入歌词**的方式完成带歌词打谱，不进行自动语音转文字或自动歌词识别。

- 用户在网页中粘贴或输入歌词；中文按单字、连续英文按单词拆分。
- 系统按旋律音符顺序将歌词初步对应到音符；休止符和跨小节延音的续音不占歌词位置。
- 用户可检查、逐字编辑和校正歌词位置，处理拖腔、衬词、重复段及空歌词位置。
- 确认后将歌词写入 MusicXML，再由原版 jianpu-ly + LilyPond 排版；简谱 PDF/SVG 和五线谱预览均从带歌词的 MusicXML 生成。
- 不输入歌词时仍可生成无歌词乐谱；V1 不会因此调用任何语音识别服务。

### V2 预留

仓库中保留的 ASR 适配器及其独立测试仅作为 V2 技术储备。它们不属于 V1 功能，不由 V1 网页、API、任务流程或健康检查调用。只有在 V2 正式立项并按路线图验收后，才考虑重新接入自动歌词识别。

版本边界与开发约定见 [V1 / V2 产品路线图](docs/PRODUCT_ROADMAP_V1_V2.md)。
