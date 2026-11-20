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

## 简谱 PDF：由服务器统一排版

普通用户不需要在自己的电脑上安装 LilyPond。项目保留两级输出保障：

- `jianpu.ly`：由 Python 端的 jianpu-ly 生成的可编辑排版源稿；即使 PDF 引擎暂不可用，也会保留。
- `jianpu.pdf`：由服务器上的 LilyPond 命令行程序生成。LilyPond 作为独立进程调用，不作为 Python 库链接进主程序。

仓库根目录的 `Dockerfile` 已把 LilyPond 放入服务器镜像。使用支持 Docker 的部署平台构建该镜像后，PDF 排版由服务器完成，客户设备无需安装额外软件。部署后访问 `/api/health`，查看 `pdf_export.ready` 是否为 `true`。本地 Windows 开发环境没有 LilyPond 时，扒谱仍会保留 `jianpu.ly` 源稿，不影响 MIDI、MusicXML 和五线谱产物。

> 注意：当前 Dockerfile 面向 CPU 核心服务及 PDF 排版。GPU 拆声/重塑仍按项目独立 GPU 环境部署，不会因安装 LilyPond 而自动迁移到该容器。

## 许可

项目代码许可见 [LICENSE](LICENSE)，第三方组件声明见 [NOTICE](NOTICE)，CREPE 上游许可见 [vendor/crepe/LICENSE](vendor/crepe/LICENSE)。模型权重由运行时单独下载，不随仓库分发。商用前应逐项核查代码、模型权重和训练数据的许可。
