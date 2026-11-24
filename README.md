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
- **视觉验收标准：采用已由用户确认的正规出版式简谱作为参考**，不是把识别出的音符简单堆成文本。音符、节奏记号、附点、升降号、小节线、延音/连音和歌词应清楚、规范；歌词字与对应音符对齐，系统间距舒适，页面适合打印。
- PDF 是正式打印产物，SVG 用于网页预览；两者必须来自同一份 MusicXML 和同一套排版规则，不能出现预览与打印内容不一致。
- 长曲应按纸张分页并保持每页可读，避免横向无限延伸、音符或歌词挤压、页面裁切；具体字号和分页参数以真实样本渲染结果验收，不凭空调整。
- 五线谱渲染、音高识别、MIDI 与 MusicXML 生成逻辑保持独立，不因简谱排版器调整而改变。
- Docker 镜像只安装 Python 音频服务、LilyPond 和必要字体；不再构建或携带额外的 Node.js 记谱排版运行时。

## 许可

项目代码许可见 [LICENSE](LICENSE)，第三方组件声明见 [NOTICE](NOTICE)，CREPE 上游许可见 [vendor/crepe/LICENSE](vendor/crepe/LICENSE)。模型权重由运行时单独下载，不随仓库分发。商用前应逐项核查代码、模型权重和训练数据的许可。

## V1 手动歌词输入与带歌词打谱

V1 的重点是**用户提供正确歌词，系统把歌词排到识别出的旋律上**。当前版本不自动识别音频歌词，也不会因为没有配置 ASR 服务而影响扒谱。

- 在记谱页面粘贴已经确认的歌词；不粘贴则生成无歌词乐谱。
- 中文按单字、连续英文按单词切分，按旋律音符顺序进行初步对齐。
- 休止符和跨小节连音的续音不占用新的歌词单位。
- 手动输入拖腔时，可用“—”表示同一歌词音节延续到后续音符；用“·”表示该音符不填写歌词。VocalParse 模型原始的中点标记仍按待确认数据处理，不自动推断为拖腔。
- 歌词写入 MusicXML，再由 jianpu-ly + LilyPond 生成简谱，由 Verovio 生成五线谱；两种谱共用同一份带歌词 MusicXML。
- 当前自动排词属于初步对齐，不是逐字时间戳强制对齐。拖腔、重复字、衬词和复杂断句仍需人工检查；V1 的后续重点是完善歌词—音符的人工校正与谱面显示。

### V2 预留：自动歌词识别

自动识别接口与服务配置暂时保留作 V2 技术储备，但不属于 V1 的默认使用流程。V1 网页不启用自动识别，也不需要配置 ASR 密钥或服务地址。

#### V2 自动识别服务配置（当前 V1 不调用）

在部署服务的环境变量中配置以下项目（不要把密钥写入代码或提交到 Git）：

- `ASR_PROVIDER=openai-compatible`：使用 OpenAI 兼容的语音转写接口；需设置 `ASR_API_KEY`。
- `ASR_BASE_URL`：接口基础地址，默认使用 Groq OpenAI-compatible API。
- `ASR_MODEL`：模型名称，默认 `whisper-large-v3-turbo`。
- 或设置 `ASR_PROVIDER=funasr`、`ASR_BASE_URL=https://你的语音识别服务/v1`；FunASR 默认模型为 `sensevoice`，可不设 API Key（若网关要求鉴权仍可设置 `ASR_API_KEY`）。

可选参数：`ASR_LANGUAGE`（默认 zh）、`ASR_TIMEOUT_SECONDS`（默认 90，范围 5–240）、`ASR_MAX_FILE_MB`（默认 24）。`GET /api/health` 会返回歌词识别服务是否已配置；配置完成但尚未实际请求时，不代表服务端点已验证可用。

歌词自动排词目前是**按旋律音符顺序初排**，不是带时间戳的强制对齐；请试听并核对每字位置，尤其是拖腔、衬词、重复段和多音节英文。

### V1 逐音歌词校正

记谱完成后，谱面页会显示逐音歌词校正区：每个输入格对应 MusicXML 中一个可分配歌词的旋律音符，可直接修改文字；拖腔续音填 `—`，无歌词音符留空。点击“保存歌词修改并更新两种谱面”后，服务端只修改本次任务的 MusicXML，并重新生成简谱 SVG/PDF 与五线谱 SVG，不会重新运行音频模型。休止符和 tie 的续音片段不会额外占用歌词格。

该编辑接口仅接受已完成的 CREPE 记谱任务，并校验歌词格数量；若双谱渲染后端不可用或渲染失败，不会用未验证的临时文件覆盖原谱面。

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

已检查 Google Drive 中现有的 `vocal_pitch_raw.npz`，确认其字段为：

- `pitch`：27309 帧，`float32`，频率单位为 Hz，范围约 91.24–706.67。
- `periodicity`：27309 帧，`float32`，周期性指标，范围约 0–0.9863，可作为置信度筛选指标。
- `sample_rate=16000`、`hop_length=160`，因此帧间隔为 0.01 秒（100 帧/秒），总覆盖约 273.09 秒。

可以直接转换，不需要再次运行 TorchCREPE：

```bash
python scripts/convert_pitch_npz.py vocal_pitch_raw.npz reference_pitch_track.json \
  --hop-seconds 0.01 --frequency-key pitch --confidence-key periodicity
```

对 30–55 秒 VocalParse 切片进行比较时，使用整首歌曲参考轨迹，并增加 `--reference-time-offset 30`。比较工具默认置信度阈值为 0.5，只采样每个音符中间 60% 的区间。注意：periodicity 是算法指标，不是人工标注的真值；交叉比较只能发现两套算法之间的差异，不能单独证明哪一套音高正确。


如果 Google Drive 中已有 `XinsW_Lead_Transcription/TorchCREPE_Test/vocal_pitch_raw.npz`，可直接打开 `notebooks/Inspect_TorchCREPE_NPZ.ipynb`，授权挂载 Drive 后运行唯一代码单元。它只输出 NPZ 内部数组的名称、形状、数据类型、有限值范围和少量样本，并在同一目录保存 `vocal_pitch_raw_inspection.json`。不会导入 TensorFlow/CREPE，不会执行推理，也不会下载模型或占用 GPU。

本地也可运行：

```bash
python scripts/inspect_pitch_npz.py path/to/vocal_pitch_raw.npz --output-json vocal_pitch_raw_inspection.json
```

检查报告用于确认旧文件的真实字段结构。若文件同时包含标量 `sample_rate` 和 `hop_length`，检查器会按 `hop_length / sample_rate` 算出帧间隔；若存在 `periodicity`，还会列出与它帧数相同的数值数组候选。候选只代表形状相符，不代表它一定是 F0/音高数组。确认字段语义后，再显式指定 `--frequency-key`、`--confidence-key` 和 `--hop-seconds`；不要猜测数组键名，也不要把不确定的数组直接当作音高轨迹。

### Colab 一键交叉验证（已有 NPZ，不重新推理）

已增加 `notebooks/TorchCREPE_VocalParse_CrossCheck.ipynb`。在 Colab 打开并运行唯一代码单元后，它会：

1. 挂载 Google Drive，读取已有的 `TorchCREPE_Test/vocal_pitch_raw.npz`。
2. 使用已确认的 `pitch`、`periodicity`、0.01 秒帧间隔转换参考音高轨迹。
3. 读取仓库内已保存的 25 秒 VocalParse 测试样本。
4. 将该片段按 30 秒偏移与整首 TorchCREPE 轨迹对齐，输出逐音符半音误差、疑似八度偏差和休止区间有声比例。
5. 将完整结果写入 Drive 的 `TorchCREPE_Test/vocalparse_pitch_comparison_30_55s.json`，同时保存 `reference_pitch_track.json`。

该 Notebook 将 NPZ 转换、事件换算、逐音符比较和时间映射网格搜索逻辑内嵌在单个代码单元中，不访问 GitHub、不安装项目、不下载模型、不运行推理，也不需要 GPU。它验证的是仓库中保存的 25 秒测试样本，并非未经确认的整首 VocalParse 推理结果。

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

#### 自动校准切片时间轴（新增）

如果 VocalParse 输入是歌曲中的一个切片，而参考 F0 是整首歌的轨迹，可以同时搜索切片起点偏移和时间尺度：

```bash
python scripts/compare_vocalparse_pitch_track.py vocalparse_result.json reference_pitch_track.json output/pitch_comparison.json \
  --reference-time-offset 30 \
  --calibrate-time-mapping \
  --calibrate-offset-range 29.5 31.0 0.1 \
  --calibrate-scale-range 0.96 1.10 0.01 \
  --minimum-coverage 0.8
```

- 时间映射公式：`参考轨迹时间 = 起点偏移 + VocalParse片段时间 × 时间尺度`。
- `--reference-time-offset` 和 `--reference-time-scale` 用于固定参数比较；时间尺度默认 1.0。
- `--calibrate-time-mapping` 会按指定网格搜索偏移与时间尺度，并将排名写入输出 JSON 的 `time_mapping_calibration` 字段。
- 默认只接受至少覆盖 80% VocalParse 音符的候选，避免某个参数因为只碰巧比较到少数简单音符而胜出。
- 候选按中位绝对音高误差排序，再以覆盖率作为次级排序依据。多个候选可能同样好，尤其当旋律重复或长音较多时；这时应保留并检查候选列表，不能把第一名当成唯一真实时间轴。
- 时间尺度大于 1 表示参考音轨的时间跨度比按 VocalParse BPM 换算的跨度更长；它只是时间轴诊断参数，不会自动改写 BPM、音符时值或 MIDI 音高。


**重要限制：** 这只是两个算法之间的交叉检查，不等于真实音高准确率。CREPE/torchcrepe 本身也可能出错，最终仍需对照原始人声听辨或人工标注。当前已确认 TorchCREPE NPZ 的字段名与帧间隔，转换时应使用上述明确参数；其他来源的 NPZ 仍须先检查字段语义，不可直接套用。

此接口目前属于实验适配层，不替换现有 transcribe() / Target 生产路径。默认 `require_all=False`，按 best-effort 规则运行：未安装可选后端时会跳过对应产物，但仍保留 MusicXML。若验收或正式任务必须同时得到五线谱和简谱，请设置 `require_all=True`；任一渲染后端缺失或渲染失败都会明确报错，避免把不完整的双谱结果误认为成功。歌词 · 延续标记暂时保留为无显示歌词的事件，不将其自动解释为延音或重复字；其语义仍需用更多真实歌曲样本确认。自动化测试与真实谱面视觉验收完成前，不应将此实验路径视为已达到生产准确率。


### VocalParse 双模式受控对照

可打开 [VocalParse Audio-only vs Audio-lyric Notebook](notebooks/VocalParse_AudioOnly_vs_AudioLyric.ipynb)，在同一段原曲 30–55 秒音频、同一个 checkpoint 和相同生成参数下，对比两种提示模式：

- `audio-only`：只输入音频，模型同时预测歌词和音乐事件。
- `audio-lyric`：输入同一段音频，并提供已知歌词作为提示，模型预测音乐事件。

Notebook 只加载一次模型权重，随后顺序运行两次推理；输出原始解码文本、解析后的 BPM/歌词/音高/时值、歌词序列对齐及逐索引差异，并保存 JSON 到 Google Drive。它不会自动安装依赖或下载模型；若现有 Colab 环境、checkpoint 或音频路径不可用，会停止并提示，不会擅自启动其他下载。

**解释限制：** 该实验用于观察“提供歌词提示”是否改变 VocalParse 的音乐事件输出，不是人工真值准确率测试。当前分离人声仍含混响与合唱/叠唱，不能把模型间差异或单个模型的稳定输出当作主唱真实音高。实验结果不自动回写生产识别流程。
