# 心思维 AI 扒谱助手（XinsW Music Transcriber）

这是从原私有项目中独立整理的公开实验仓库。这里只保留 MusicMaster 扒谱实验所需的程序、网页、Notebook、测试和第三方许可文件；不包含原私有仓库的其他项目、用户音频、私人配置或开发日志。

## Colab 免费临时运行

打开 [XinsW Colab 免费运行版 v2](notebooks/XinsW_Colab_Free_v2.ipynb)。

当前流程面向**已经分离好的人声主唱音轨**，尝试提取主旋律并生成 MIDI、MusicXML 等结果；不会自动从整首混音中分离人声。

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

## 简谱排版：悦谱 Dolce（主引擎）

单旋律扒谱生成 MusicXML 后，服务器会调用固定版本的 **Dolce（悦谱）无头排版入口**，直接使用与悦谱编辑器相同的简谱排版代码：

- Dolce 输出 SVG 矢量谱页；服务器再用 librsvg 从这些 SVG 生成高清 PNG 与可打印 PDF。
- `jianpu.pdf` 是 Dolce 排版后的主 PDF；各页 SVG / PNG 也会作为下载文件提供。
- 服务端默认按 **A4 分页纸**排版（Dolce 原生缺省是连续长图）；可通过 `DOLCE_JIANPU_PAPER` 指定 A4、A5、B5、Letter 等受支持纸张。
- 原有 `jianpu-ly + LilyPond` 流程保留作备用。Dolce 未安装、转换失败或输入不受支持时，不会让扒谱任务整体失败，原有排版产物仍可用。
- 五线谱渲染、音高识别、MIDI 与 MusicXML 生成逻辑不变；复音转录引擎仍按原规则不自动生成单旋律简谱。
- Node.js 20、Dolce CLI 与字体只加入现有 Docker 镜像，不新增 Render 服务，也不要求用户电脑安装 Node 或悦谱。

Dolce 上游版本固定为 `defb7594b00a42cda8030cdf68baa61e3b562b72`，避免构建时跟随上游变化。项目代码采用 MIT 许可；随附 Bravura 字体另按 SIL OFL 1.1 授权，详见 [NOTICE-DOLCE.md](NOTICE-DOLCE.md)。

## 许可

项目代码许可见 [LICENSE](LICENSE)，第三方组件声明见 [NOTICE](NOTICE)，CREPE 上游许可见 [vendor/crepe/LICENSE](vendor/crepe/LICENSE)。模型权重由运行时单独下载，不随仓库分发。商用前应逐项核查代码、模型权重和训练数据的许可。
