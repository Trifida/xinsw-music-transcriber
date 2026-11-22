# -*- coding: utf-8 -*-
"""MusicMaster 端到端冒烟测试(CPU;CREPE 默认权重首次运行会下载)。

覆盖:契约导入 / 简谱⇄五线谱往返 / 合成音频扒谱 / 五线谱渲染。
GPU 部分(分离/修音换音色)需独立 venv 与权重,不在此 CI 范围。
"""
import numpy as np
import pytest
import soundfile as sf
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXAMPLES = REPO / "examples"


def test_contracts_import():
    from musicmaster.core import contracts
    assert hasattr(contracts, "Target")
    assert hasattr(contracts, "Note")
    assert hasattr(contracts, "F0")


def test_convert_roundtrip_lossless():
    """简谱 → music21 Score → 简谱:音级序列往返一致。"""
    from musicmaster.convert import convert as cv

    score = cv.load_any(EXAMPLES / "twinkle.jianpu")
    back = cv.score_to_jianpu(score, key_name="C")
    seq = " ".join(t for t in back.replace("|", " ").split() if t and not t.startswith(("1=", "4/", "tempo")))
    # 小星星开头 1 1 5 5 6 6 5
    assert seq.split()[:7] == ["1", "1", "5", "5", "6", "6", "5"]


def test_jianpu_download_labels_reflect_legacy_renderer():
    from musicmaster.web.runners import _friendly

    pdf = _friendly("jianpu.pdf")
    svg = _friendly("jianpu.svg")
    assert pdf["label"] == "简谱 PDF（原版排版）"
    assert "jianpu-ly + LilyPond" in pdf["desc"]
    assert svg["label"] == "简谱排版图（原版）"
    assert "jianpu-ly + LilyPond" in svg["desc"]


def test_original_jianpu_renderer_generates_svg_and_pdf(tmp_path):
    """Use the original jianpu-ly + LilyPond path to create real SVG and PDF files."""
    import shutil
    from musicmaster.convert import convert as cv
    from musicmaster.core.render import render as render_score

    if not shutil.which("lilypond"):
        pytest.skip("LilyPond CLI is not installed")
    score = cv.load_any(EXAMPLES / "twinkle.jianpu")
    musicxml = tmp_path / "twinkle.musicxml"
    score.write("musicxml", fp=str(musicxml))

    svg_result = render_score(
        str(musicxml), str(tmp_path), formats=("jianpu",), jianpu_format="svg"
    )
    pdf_result = render_score(
        str(musicxml), str(tmp_path), formats=("jianpu",), jianpu_format="pdf"
    )
    svg = svg_result["jianpu"]
    pdf = pdf_result["jianpu"]
    assert svg.is_file() and svg.stat().st_size > 500
    assert "<svg" in svg.read_text(encoding="utf-8")[:500]
    assert pdf.is_file() and pdf.read_bytes().startswith(b"%PDF")


def test_transcribe_synthetic_scale(tmp_path):
    """合成 C 大调音阶 → pyin 扒谱 → 精确还原音高。"""
    import librosa
    from musicmaster.transcribe import transcribe2

    sr = 16000
    notes = [60, 62, 64, 65, 67]
    y = np.concatenate([
        0.3 * np.sin(2 * np.pi * librosa.midi_to_hz(n) * np.arange(int(0.5 * sr)) / sr)
        for n in notes
    ]).astype("float32")
    wav = tmp_path / "scale.wav"
    sf.write(str(wav), y, sr)

    target, info = transcribe2.transcribe(str(wav), f0_method="pyin", fmax="C6")
    midis = [n["midi"] for n in target["notes"]]
    assert midis[:5] == notes


def test_render_staff_svg(tmp_path):
    """MusicXML → 五线谱 SVG(Verovio)。verovio 缺失则跳过。"""
    from musicmaster.core.render import render as render_fn, is_available

    if not is_available(staff=True):
        pytest.skip("verovio 不可用")
    from musicmaster.convert import convert as cv

    score = cv.load_any(EXAMPLES / "twinkle.jianpu")
    mxl = tmp_path / "t.musicxml"
    score.write("musicxml", fp=str(mxl))
    out = render_fn(str(mxl), str(tmp_path), formats=("staff",))
    assert out["staff"].is_file()
    assert out["staff"].stat().st_size > 1000


def test_transcribe_synthetic_scale_crepe(tmp_path):
    """合成 C 大调音阶 → 默认引擎 CREPE 扒谱 → 还原音高(覆盖默认引擎安装链/predict 路径)。"""
    import librosa
    from musicmaster.transcribe import transcribe2

    sr = 16000
    notes = [60, 62, 64, 65, 67]
    y = np.concatenate([
        0.3 * np.sin(2 * np.pi * librosa.midi_to_hz(n) * np.arange(int(0.5 * sr)) / sr)
        for n in notes
    ]).astype("float32")
    wav = tmp_path / "scale.wav"
    sf.write(str(wav), y, sr)
    target, info = transcribe2.transcribe(str(wav), f0_method="crepe", fmax="C6")
    midis = [n["midi"] for n in target["notes"]]
    assert midis[:5] == notes


def test_vocal_redlines_locked():
    """锁定人声「验证配方」红线:默认参数不被悄悄改(CI 无 GPU,只查签名默认值)。"""
    import importlib
    import inspect
    # vocal/__init__ 把 correct/voice 绑成包属性函数,取模块必须 import_module(避开同名陷阱)
    pipeline = importlib.import_module("musicmaster.vocal.pipeline")
    correct_mod = importlib.import_module("musicmaster.vocal.correct")
    voice_mod = importlib.import_module("musicmaster.vocal.voice")

    p = inspect.signature(pipeline.two_stage).parameters
    assert p["shift"].default == -12, "八度锁 shift 必须 -12"
    assert p["correct_steps"].default == 150
    assert p["voice_steps"].default == 50
    assert p["voice_cfg"].default == 0.7
    assert inspect.signature(correct_mod.correct).parameters["shift"].default == -12

    vp = inspect.signature(voice_mod.voice).parameters
    assert vp["auto_f0_adjust"].default is False, "不自动移调(否则身份偏)"
    assert vp["semi_tone_shift"].default == 0
    assert vp["f0_condition"].default is True
    assert vp["inference_cfg_rate"].default == 0.7
    assert inspect.signature(voice_mod.resample).parameters["sr"].default == 44100, "Seed-VC f0 模型要 44.1k"


def test_crepe_autopilot_end_to_end_outputs_editable_scores(tmp_path):
    """CREPE 一键流程:质量门→扒谱→MIDI/MusicXML→五线谱/简谱源→可信度报告。"""
    import json
    import librosa
    from musicmaster.transcribe import autopilot

    sr = 16000
    notes = [60, 62, 64, 65, 67]
    tone = np.arange(int(0.55 * sr)) / sr
    y = np.concatenate([
        0.3 * np.sin(2 * np.pi * librosa.midi_to_hz(n) * tone)
        for n in notes
    ]).astype("float32")
    wav = tmp_path / "lead_scale.wav"
    sf.write(str(wav), y, sr)

    out = tmp_path / "autopilot"
    rc = autopilot.main([str(wav), "--out", str(out), "--engine", "crepe"])
    assert rc == 0
    required = ["notes.json", "out.mid", "out.musicxml", "staff.svg", "confidence.json", "报告.md"]
    assert all((out / name).is_file() for name in required)
    target = json.loads((out / "notes.json").read_text(encoding="utf-8"))
    assert [n["midi"] for n in target["notes"]][:5] == notes
    confidence = json.loads((out / "confidence.json").read_text(encoding="utf-8"))
    assert 0 <= confidence["overall"] <= 100
    # LilyPond 是独立可选 CLI;未安装时至少必须保留可编辑的 .ly 源稿。
    if not (out / "jianpu.pdf").is_file():
        assert (out / "jianpu.ly").is_file()
        report = (out / "报告.md").read_text(encoding="utf-8")
        assert "服务器重新生成 PDF" in report


def test_vendored_crepe_installs_only_full_model():
    """本地 CREPE 安装包只打包默认 full 权重,不再触发五规格下载。"""
    import ast

    setup_path = REPO / "vendor" / "crepe" / "setup.py"
    source = setup_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    setup_call = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "setup"
    )
    package_data = next(
        ast.literal_eval(keyword.value)
        for keyword in setup_call.keywords
        if keyword.arg == "package_data"
    )
    assert package_data == {"crepe": ["model-full.h5"]}
    assert not (REPO / "vendor" / "crepe" / "crepe" / "model-tiny.h5").exists()
    assert not (REPO / "vendor" / "crepe" / "crepe" / "model-small.h5").exists()
    assert not (REPO / "vendor" / "crepe" / "crepe" / "model-medium.h5").exists()
    assert not (REPO / "vendor" / "crepe" / "crepe" / "model-large.h5").exists()


def test_crepe_model_downloader_is_pinned_and_mirror_configurable():
    """模型下载地址固定到上游不可变提交,并允许部署时指定 HTTPS 镜像。"""
    source = (REPO / "scripts" / "prepare_crepe_model.py").read_text(encoding="utf-8")
    assert "bb29b8d99a89924476d112d27ed470e4ac5617c0" in source
    assert "073f07dd696b851136d59c46b777c909502ad9a1" in source
    assert "EXPECTED_ARCHIVE_SIZE = 57689301" in source
    assert 'os.environ.get("CREPE_MODEL_URL", DEFAULT_URL)' in source
    assert 'url.lower().startswith("https://")' in source


def test_reference_midi_evaluator_reports_octave_errors_and_misses():
    """参考 MIDI 评估将八度错音与漏音分开统计。"""
    import importlib.util

    evaluator_path = REPO / "scripts" / "evaluate_reference_midi.py"
    spec = importlib.util.spec_from_file_location("evaluate_reference_midi", evaluator_path)
    evaluator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evaluator)

    predicted = [
        {"pitch": 60, "start": 0.02, "end": 0.40},
        {"pitch": 74, "start": 0.52, "end": 0.90},
        {"pitch": 67, "start": 1.50, "end": 1.80},
    ]
    reference = [
        {"pitch": 60, "start": 0.00, "end": 0.40},
        {"pitch": 62, "start": 0.50, "end": 0.90},
        {"pitch": 64, "start": 1.00, "end": 1.30},
    ]
    result = evaluator.evaluate(predicted, reference, 0.12)
    assert result["onset_matched_count"] == 2
    assert result["exact_pitch_count"] == 1
    assert result["octave_error_count"] == 1
    assert result["missed_reference_count"] == 1
    assert result["unmatched_predicted_count"] == 1
    assert result["pitch_accuracy_on_onset_matches"] == 0.5


def test_reference_midi_matcher_maximizes_sequential_matches():
    """相邻短音情况下，匹配器优先保留最多的顺序匹配，而非贪心抢最近一对。"""
    import importlib.util

    evaluator_path = REPO / "scripts" / "evaluate_reference_midi.py"
    spec = importlib.util.spec_from_file_location("evaluate_reference_midi_optimal", evaluator_path)
    evaluator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evaluator)

    predicted = [
        {"pitch": 60, "start": 0.00, "end": 0.08},
        {"pitch": 62, "start": 0.09, "end": 0.17},
    ]
    reference = [
        {"pitch": 60, "start": 0.08, "end": 0.16},
        {"pitch": 62, "start": 0.17, "end": 0.25},
    ]
    matches, used_predicted, used_reference = evaluator.match_notes(predicted, reference, 0.09)
    assert len(matches) == 2
    assert used_predicted == {0, 1}
    assert used_reference == {0, 1}


def test_real_audio_benchmark_extracts_quality_gate():
    """基准 JSON 正确记录质量门档位，而不是因正则转义错误丢失。"""
    import importlib.util

    benchmark_path = REPO / "scripts" / "benchmark_real_audio.py"
    spec = importlib.util.spec_from_file_location("benchmark_real_audio", benchmark_path)
    benchmark = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(benchmark)

    assert benchmark.extract_quality_gate("门控=pass）其余报告内容") == "pass"
    assert benchmark.extract_quality_gate("门控=block) 体检分数") == "block"
    assert benchmark.extract_quality_gate("报告中没有门控字段") is None



def test_xinsw_frontend_is_a_single_automatic_lead_vocal_entry():
    """心思维独立页面只提供主唱自动识别，不暴露上游多引擎调试选项。"""
    page = (REPO / "musicmaster" / "web" / "static" / "xinsw.html").read_text(encoding="utf-8")
    script = (REPO / "musicmaster" / "web" / "static" / "js" / "xinsw.js").read_text(encoding="utf-8")
    assert 'src="js/xinsw.js"' in page
    assert 'id="audio" type="file" accept="audio/*"' in page
    assert "engine', 'crepe'" in script
    assert "'/api/transcribe'" in script
    assert "job.progress" in script
    assert "result.staff_svg" in script
    assert "result.downloads" in script
    assert "setTimeout(function () { poll(jobId); }, 900)" in script
    assert "basic-pitch" not in script
    assert "bytedance" not in script



def test_full_song_transcription_separates_before_pitch_recognition(tmp_path, monkeypatch):
    """完整歌曲入口必须先产出 vocal.wav，再调用原有主唱扒谱；不得把混音直接送进 CREPE。"""
    from types import SimpleNamespace
    from musicmaster.web import runners

    source = tmp_path / "complete_song.mp3"
    source.write_bytes(b"fake audio bytes")
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    job = SimpleNamespace(
        job_dir=str(job_dir),
        set_stage=lambda stage, progress=None: None,
        set_progress=lambda progress: None,
    )
    calls = {}

    def fake_separate(progress_job, audio_path, stages, denoise):
        calls["separate"] = (audio_path, stages, denoise)
        vocal = Path(progress_job.job_dir) / "1_分离" / "vocal.wav"
        vocal.parent.mkdir(parents=True, exist_ok=True)
        vocal.write_bytes(b"separated vocal")
        return {"ok": True, "tracks": []}

    def fake_transcribe(progress_job, audio_path, engine, key, lyrics_text, auto_lyrics):
        calls["transcribe"] = audio_path
        assert Path(audio_path).read_bytes() == b"separated vocal"
        return {"ok": True, "report_md": "# test report", "downloads": []}

    monkeypatch.setattr(runners, "run_separate", fake_separate)
    monkeypatch.setattr(runners, "run_transcribe", fake_transcribe)

    result = runners.run_full_song_transcribe(
        job, str(source), engine="crepe", key="", lyrics_text="", auto_lyrics=True
    )

    assert calls["separate"] == (str(source), "1", "dereverb")
    assert calls["transcribe"].endswith("1_分离/vocal.wav")
    assert result["ok"] is True
    assert result["source_mode"] == "full-song"
    assert {item["name"] for item in result["downloads"]} >= {
        "source_audio.mp3", "1_分离/vocal.wav"
    }
    assert "完整歌曲处理链" in result["report_md"]


def test_full_song_transcription_stops_when_separation_is_unavailable(tmp_path, monkeypatch):
    """没有 GPU 分离环境时必须明确失败，不能把完整混音误送进单旋律识别器。"""
    from types import SimpleNamespace
    from musicmaster.web import runners

    source = tmp_path / "complete_song.wav"
    source.write_bytes(b"fake audio bytes")
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    job = SimpleNamespace(
        job_dir=str(job_dir),
        set_stage=lambda stage, progress=None: None,
        set_progress=lambda progress: None,
    )
    monkeypatch.setattr(
        runners, "run_separate",
        lambda *args, **kwargs: {"ok": False, "message": "未找到分离环境"},
    )
    monkeypatch.setattr(
        runners, "run_transcribe",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not transcribe mixed audio")),
    )

    result = runners.run_full_song_transcribe(job, str(source))
    assert result["ok"] is False
    assert result["source_mode"] == "full-song"
    assert "未找到分离环境" in result["message"]
    assert result["downloads"][0]["name"] == "source_audio.wav"
