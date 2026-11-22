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

## 简谱排版：原版 jianpu-ly + LilyPond

简谱统一使用项目原有的 **jianpu-ly + LilyPond** 排版链路：

- MusicXML 转换为 jianpu-ly / LilyPond 源稿，再由 LilyPond 生成 SVG 预览和可打印 PDF。
- 简谱 PDF 与 SVG 使用同一套原版排版器，避免多个排版引擎输出不一致。
- 五线谱渲染、音高识别、MIDI 与 MusicXML 生成逻辑保持独立，不因简谱排版器调整而改变。
- Docker 镜像只安装 Python 音频服务、LilyPond 和必要字体；不再构建或携带额外的 Node.js 记谱排版运行时。

## 许可

项目代码许可见 [LICENSE](LICENSE)，第三方组件声明见 [NOTICE](NOTICE)，CREPE 上游许可见 [vendor/crepe/LICENSE](vendor/crepe/LICENSE)。模型权重由运行时单独下载，不随仓库分发。商用前应逐项核查代码、模型权重和训练数据的许可。

## 歌词识别与简谱排版

音频记谱支持可选的歌词识别与逐字排版：

- 可在网页中粘贴歌词；有手动歌词时优先使用，不再调用自动识别服务。
- 留空时可启用自动识别。歌词先按音符顺序初步对齐：中文按单字、连续英文按单词，休止符和跨小节延音的续音不占歌词位置。
- 歌词写入 MusicXML，再交给原版 jianpu-ly + LilyPond 排版；简谱 PDF/SVG 和 Verovio 五线谱预览均从带歌词的 MusicXML 生成。
- 自动识别是可选服务，未配置时扒谱和无歌词排版照常工作。自动识别会将音频发送到你配置的语音识别服务，部署前请确认服务商与隐私要求。

### 自动识别服务配置

在部署服务的环境变量中配置以下项目（不要把密钥写入代码或提交到 Git）：

- `ASR_PROVIDER=openai-compatible`：使用 OpenAI 兼容的语音转写接口；需设置 `ASR_API_KEY`。
- `ASR_BASE_URL`：接口基础地址，默认使用 Groq OpenAI-compatible API。
- `ASR_MODEL`：模型名称，默认 `whisper-large-v3-turbo`。
- 或设置 `ASR_PROVIDER=funasr`、`ASR_BASE_URL=https://你的语音识别服务/v1`；FunASR 默认模型为 `sensevoice`，可不设 API Key（若网关要求鉴权仍可设置 `ASR_API_KEY`）。

可选参数：`ASR_LANGUAGE`（默认 zh）、`ASR_TIMEOUT_SECONDS`（默认 90，范围 5–240）、`ASR_MAX_FILE_MB`（默认 24）。`GET /api/health` 会返回歌词识别服务是否已配置；配置完成但尚未实际请求时，不代表服务端点已验证可用。

歌词自动排词目前是**按旋律音符顺序初排**，不是带时间戳的强制对齐；请试听并核对每字位置，尤其是拖腔、衬词、重复段和多音节英文。

## VocalParse 实验接入（开发分支）

开发分支 feature/vocalparse-event-musicxml 增加了 VocalParse 结果适配层。它把模型返回的歌词、MIDI 音高和音符时值转换为 beat-based 事件，再生成一份 MusicXML，供五线谱与简谱渲染器共同使用。

```python
from musicmaster.core import render_vocalparse_result

parsed = {
    "bpm": 100,
    "words": ["SP", "你", "好"],
    "pitches": [0, 60, 62],
    "notes": ["NOTE_2", "NOTE_4", "NOTE_DOT_4"],
}

artifacts = render_vocalparse_result(
    parsed,
    "output/vocalparse-score",
    require_all=True,  # 五线谱与简谱任一后端缺失或失败时直接报错
)
# artifacts["musicxml"] 统一的记谱源文件
# artifacts.get("staff") 五线谱 SVG（需安装 render extra）
# artifacts.get("jianpu_ly") 简谱 LilyPond 源文件（需安装 jianpu-ly）
# artifacts.get("jianpu") 简谱 SVG/PDF（还需独立安装 LilyPond CLI）
```

也可以直接使用命令行，把已经保存的 VocalParse 推理 JSON 转成双谱，不需要再次加载模型或运行音频推理：

```bash
# 先安装五线谱与简谱渲染依赖；系统还需单独安装 LilyPond CLI
python -m pip install -e ".[render]"
python scripts/render_vocalparse_json.py path/to/vocalparse_result.json output/vocalparse-score
```

输入 JSON 须包含 `bpm`、`words`、`pitches`、`notes` 四个字段。默认严格要求五线谱和简谱都成功生成；若只想尽可能生成可用产物，可追加 `--allow-partial`。脚本只读取已保存的识别结果，不会下载模型、不消耗 GPU，也不会重新进行音频推理。

### 检查已有 TorchCREPE NPZ（不重新运行模型）

确认 NPZ 的真实字段后，可以使用 `scripts/convert_pitch_npz.py` 转换为比较工具所需的 JSON。必须明确指定数组键和时间来源，不会猜测字段名或帧间隔。例如，只有在检查报告确认字段名和时间步长后，才使用类似命令：

```bash
python scripts/convert_pitch_npz.py vocal_pitch_raw.npz reference_pitch_track.json \\
  --time-key <时间数组键> --frequency-key <频率数组键> \\
  --confidence-key <置信度数组键>
```

如果文件没有时间数组，只有在从原始推理参数或保存代码确认了帧间隔后，才使用 `--hop-seconds`；不要凭估计填写。转换后再用比较脚本的 `--reference-time-offset 30` 对齐 30–55 秒 VocalParse 切片。


如果 Google Drive 中已有 `XinsW_Lead_Transcription/TorchCREPE_Test/vocal_pitch_raw.npz`，可直接打开 `notebooks/Inspect_TorchCREPE_NPZ.ipynb`，授权挂载 Drive 后运行唯一代码单元。它只输出 NPZ 内部数组的名称、形状、数据类型、有限值范围和少量样本，并在同一目录保存 `vocal_pitch_raw_inspection.json`。不会导入 TensorFlow/CREPE，不会执行推理，也不会下载模型或占用 GPU。

本地也可运行：

```bash
python scripts/inspect_pitch_npz.py path/to/vocal_pitch_raw.npz --output-json vocal_pitch_raw_inspection.json
```

检查报告用于确认旧文件的真实字段结构；确认前不要猜测数组键名或时间步长，也不要把不确定的数组直接当作音高轨迹。

### VocalParse 音高交叉检查（离线，不重新推理）

为便于检查模型音高是否存在八度偏差或明显半音偏差，新增独立的音高轨迹对照工具。它把已保存的 VocalParse 音符，与另一套音高估计器导出的带时间戳 F0 轨迹逐音符比较；不会重新运行 VocalParse、CREPE，也不会下载模型。

参考轨迹整理为 JSON（时间单位为秒）。每帧可提供 MIDI 浮点音高 `pitch_midi`，也可直接提供 CREPE 常见的频率 `frequency_hz`（Hz）；无声帧分别用 `pitch_midi: null` 或 `frequency_hz: 0` 表示。置信度 `confidence` 可选：

```json
{
  "frames": [
    {"time_sec": 0.01, "frequency_hz": 261.63, "confidence": 0.95},
    {"time_sec": 0.02, "frequency_hz": 0, "confidence": 0.10}
  ]
}
```

运行：

```bash
python scripts/compare_vocalparse_pitch_track.py vocalparse_result.json reference_pitch_track.json output/pitch_comparison.json

如果 VocalParse 输入是原曲的 30–55 秒切片，而参考音高轨迹来自整首歌曲，请增加 `--reference-time-offset 30`，让切片内 0 秒对应参考轨迹的 30 秒。偏移量单位为秒，默认 0；报告会同时保留片段相对时间和参考轨迹绝对时间。
```

报告包含每个音符的参考中位音高、半音误差、八度疑似偏差、置信度，以及休止区间的有声音帧比例。默认只取每个音符中间 60% 的时间窗口，减少音符边界混音影响；可用 `--confidence-threshold` 和 `--central-fraction` 调整。

**重要限制：** 这只是两个算法之间的交叉检查，不等于真实音高准确率。CREPE/torchcrepe 本身也可能出错，最终仍需对照原始人声听辨或人工标注。现有 Colab NPZ 的字段结构尚未确认，因此本工具先定义稳定的通用 JSON 接口，不擅自猜测 NPZ 内部数组格式。

此接口目前属于实验适配层，不替换现有 transcribe() / Target 生产路径。默认 `require_all=False`，按 best-effort 规则运行：未安装可选后端时会跳过对应产物，但仍保留 MusicXML。若验收或正式任务必须同时得到五线谱和简谱，请设置 `require_all=True`；任一渲染后端缺失或渲染失败都会明确报错，避免把不完整的双谱结果误认为成功。歌词 · 延续标记暂时保留为无显示歌词的事件，不将其自动解释为延音或重复字；其语义仍需用更多真实歌曲样本确认。自动化测试与真实谱面视觉验收完成前，不应将此实验路径视为已达到生产准确率。
