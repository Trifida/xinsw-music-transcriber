# -*- coding: utf-8 -*-
"""MusicMaster 的 FastAPI 服务:把设计稿(static/index.html)接到真实后端。

启动:
  .venv\\Scripts\\python.exe -m musicmaster.web.server      # 或双击根目录「启动.bat」
浏览器自动打开 http://127.0.0.1:7860(被占用则顺延)。

路由:
  GET  /                         设计稿首页(StaticFiles,html=True)
  GET  /fonts/* /js/* ...        静态资源
  POST /api/convert|transcribe|separate|vocal   提交任务(multipart),返回 {job_id}
  GET  /api/job/{id}             轮询任务状态/结果
  GET  /api/file/{id}/{name}     下载/预览某任务的产物(防目录穿越)
  GET  /api/health               健康检查
"""
from __future__ import annotations

import os
import shutil
import socket
import sys
import threading
import uuid
import webbrowser
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from musicmaster.web.jobs import JobManager
from musicmaster.web import runners
from musicmaster.web.cloud_api import router as cloud_router

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

REPO = Path(__file__).resolve().parents[2]
OUTPUT = REPO / "output"
STATIC = Path(__file__).resolve().parent / "static"
UPLOADS = OUTPUT / "_uploads"

JM = JobManager(OUTPUT, max_workers=int(os.environ.get("MUSICMASTER_WORKERS", "2")))

app = FastAPI(title="MusicMaster", docs_url="/api/docs", openapi_url="/api/openapi.json")
app.include_router(cloud_router)

class LyricEditsRequest(BaseModel):
    assignments: list[str]




def _save_upload(up: UploadFile | None) -> str | None:
    """把上传文件落盘到 output/_uploads/<uuid>/<原名>,返回路径;无文件返回 None。
    放进独立子目录(而非给文件名加前缀),既保证唯一又保留原始文件名 —— 这样下游产物
    (如 twinkle.musicxml、分离的 *_(Vocals)_*.wav)命名干净。文件名只取 basename 防穿越。"""
    if up is None or not up.filename:
        return None
    # 文件名清洗:只取 basename,去首尾空白与 Windows 非法尾部(空格/点),空则回退 'upload'
    # ——纯空白名(' ')在 Windows 上 open() 会抛 PermissionError,必须拦在前面(修压测 H1)。
    safe = (Path(up.filename).name or "").strip().rstrip(" .") or "upload"
    sub = UPLOADS / uuid.uuid4().hex[:8]
    try:
        sub.mkdir(parents=True, exist_ok=True)
        dest = sub / safe
        with open(dest, "wb") as f:
            shutil.copyfileobj(up.file, f)
    except OSError as e:
        shutil.rmtree(sub, ignore_errors=True)  # 落盘失败清理刚建的子目录,不残留空目录(修压测 L)
        raise HTTPException(status_code=400, detail=f"文件名或文件不合法,请重命名后重试({type(e).__name__})")
    return str(dest)


# ─────────────────────────── API ─────────────────────────── #
@app.get("/api/health")
def health() -> dict:
    # 排版引擎属于服务器能力，不要求客户设备安装。健康检查同时报告 PDF 是否就绪；
    # 即使 LilyPond 暂缺，API 仍健康，简谱 .ly 源稿照常保留。
    try:
        from musicmaster.core.render import lilypond_executable, is_jianpu_source_available
        lilypond = lilypond_executable()
        source_ready = is_jianpu_source_available()
    except Exception:
        lilypond = None
        source_ready = False
    return {
        "ok": True,
        "service": "musicmaster",
        "static": STATIC.is_dir(),
        "pdf_export": {
            "ready": bool(lilypond and source_ready),
            "engine": "LilyPond" if lilypond and source_ready else None,
            "source_fallback": source_ready,
        },
    }


@app.post("/api/convert")
def api_convert(file: UploadFile = File(...), direction: str = Form("j2s"),
                key: str = Form("")) -> dict:
    if direction not in ("j2s", "s2j"):
        raise HTTPException(status_code=422, detail="未知转换方向,仅支持 j2s / s2j")
    path = _save_upload(file)
    job = JM.submit("convert", runners.run_convert, path, direction, key)
    return {"job_id": job.id}


@app.post("/api/transcribe")
def api_transcribe(audio: UploadFile = File(...), engine: str = Form("crepe"),
                   key: str = Form(""), lyrics: str = Form("")) -> dict:
    """V1 仅接受用户输入的歌词；不提供自动歌词识别参数。"""
    path = _save_upload(audio)
    job = JM.submit("transcribe", runners.run_transcribe, path, engine, key, lyrics)
    return {"job_id": job.id}


@app.post("/api/separate")
def api_separate(audio: UploadFile = File(...), stages: str = Form("1,2,3"),
                 denoise: str = Form("dereverb")) -> dict:
    # 校验而非依赖 Form 默认回填掩盖空输入(修压测 L:stages=''/denoise='' 曾被静默当默认)
    stage_list = [s.strip() for s in stages.split(",") if s.strip()]
    if not stage_list or any(s not in ("1", "2", "3") for s in stage_list):
        raise HTTPException(status_code=422, detail="处理段 stages 必须是 1/2/3 的非空子集,如 1,2,3")
    if denoise not in ("dereverb", "deecho"):
        raise HTTPException(status_code=422, detail="降噪方法 denoise 仅支持 dereverb / deecho")
    path = _save_upload(audio)
    job = JM.submit("separate", runners.run_separate, path, ",".join(stage_list), denoise)
    return {"job_id": job.id}


@app.post("/api/vocal")
def api_vocal(raw: UploadFile = File(...), ref: UploadFile = File(...),
              self_ref: UploadFile = File(...), correct_steps: int = Form(150),
              voice_steps: int = Form(50), voice_cfg: float = Form(0.7)) -> dict:
    # 数值参数夹紧 + 拒绝 NaN/Inf(修压测 M:负数/超界/天文数曾原样下传至 GPU 子进程)
    import math
    if not math.isfinite(voice_cfg):
        raise HTTPException(status_code=422, detail="voice_cfg 必须是 0~1 的有限数")
    correct_steps = max(1, min(1000, int(correct_steps)))
    voice_steps = max(1, min(1000, int(voice_steps)))
    voice_cfg = max(0.0, min(1.0, float(voice_cfg)))
    p_raw = _save_upload(raw)
    p_ref = _save_upload(ref)
    p_self = _save_upload(self_ref)
    job = JM.submit("vocal", runners.run_vocal, p_raw, p_ref, p_self,
                    correct_steps, voice_steps, voice_cfg)
    return {"job_id": job.id}


@app.post("/api/job/{job_id}/lyrics")
def api_save_lyrics(job_id: str, payload: LyricEditsRequest) -> dict:
    """Save per-note manual lyric corrections and regenerate all score previews."""
    job = JM.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="未知 job_id")
    if job.kind != "transcribe":
        raise HTTPException(status_code=409, detail="只有记谱任务支持逐音歌词编辑。")
    with job._lock:
        if job.status != "done" or not isinstance(job.result, dict) or not job.result.get("ok"):
            raise HTTPException(status_code=409, detail="记谱任务尚未成功完成，暂时不能编辑歌词。")
        result = job.result
        if result.get("lyrics_slots") is None:
            raise HTTPException(status_code=409, detail="当前识别引擎不支持逐音歌词编辑，请使用主唱 CREPE 单旋律模式。")
        if len(payload.assignments) > 1000:
            raise HTTPException(status_code=413, detail="一次最多编辑 1000 个歌词位置。")
        if any(len(value) > 80 for value in payload.assignments):
            raise HTTPException(status_code=413, detail="单个歌词位置最多 80 个字符。")
        musicxml = JM.file_path(job_id, "out.musicxml")
        if musicxml is None:
            raise HTTPException(status_code=404, detail="找不到本次任务的 MusicXML 文件。")
        try:
            from musicmaster.transcribe.lyrics import apply_lyric_assignments
            import json
            applied = apply_lyric_assignments(musicxml, payload.assignments)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"歌词写入失败：{type(exc).__name__}") from exc

        job_dir = Path(job.job_dir)
        slots = applied["assignments"]
        lyrics_info = {
            "source": "user-edited",
            "status": "completed",
            "alignmentStatus": "manually-edited",
            "tokenCount": len(slots),
            "assignedCount": applied["assignedCount"],
            "unassignedCount": applied["emptyCount"],
            "message": "已保存逐音人工校正；空白位置保持无歌词，“—”作为拖腔标记保留。",
        }
        (job_dir / "lyrics.txt").write_text(
            "".join(item["lyric"] for item in slots), encoding="utf-8"
        )
        (job_dir / "lyrics_alignment.json").write_text(
            json.dumps({**lyrics_info, "assignments": slots}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        render_warnings = []
        staff_svg = result.get("staff_svg")
        jianpu_svg = result.get("jianpu_svg")
        try:
            from musicmaster.core.render import render as render_score
            rendered = render_score(
                str(musicxml), str(job_dir), formats=("staff", "jianpu"), jianpu_format="svg"
            )
            if rendered.get("staff"):
                staff_svg = runners._read_svg(Path(rendered["staff"]))
            if rendered.get("jianpu"):
                jianpu_svg = runners._read_svg(Path(rendered["jianpu"]))
            try:
                render_score(str(musicxml), str(job_dir), formats=("jianpu",), jianpu_format="pdf")
            except Exception as exc:  # noqa: BLE001
                render_warnings.append(f"简谱 PDF 未能重新生成：{type(exc).__name__}")
        except Exception as exc:  # noqa: BLE001
            render_warnings.append(f"谱面预览未能全部重新生成：{type(exc).__name__}")

        wanted = [
            "notes.json", "out.mid", "out.musicxml", "jianpu.pdf", "jianpu.ly",
            "jianpu.svg", "lyrics.txt", "lyrics_alignment.json",
            "confidence.json", "staff.svg",
        ]
        downloads = runners._downloads(job_dir, only=wanted)
        result.update({
            "lyrics_info": lyrics_info,
            "lyrics_slots": slots,
            "lyrics_text": "".join(item["lyric"] for item in slots),
            "staff_svg": staff_svg,
            "jianpu_svg": jianpu_svg,
            "jianpu_page_count": 1 if jianpu_svg else None,
            "downloads": downloads,
        })
        if render_warnings:
            result["lyrics_render_warnings"] = render_warnings
        else:
            result.pop("lyrics_render_warnings", None)
        result["report_md"] = (result.get("report_md") or "") + (
            "\\n\\n## 逐音歌词人工校正\\n"
            + f"- 已保存：{applied['assignedCount']}/{applied['lyricSlots']} 个位置有歌词。\\n"
            + "- MusicXML 已更新；谱面预览与 PDF 已尽力重新生成。\\n"
        )
        job.updated_at = __import__("time").time()
        return {
            "ok": True,
            "lyrics_info": lyrics_info,
            "lyrics_slots": slots,
            "staff_svg": staff_svg,
            "jianpu_svg": jianpu_svg,
            "downloads": downloads,
            "render_warnings": render_warnings,
        }


@app.get("/api/job/{job_id}")
def api_job(job_id: str) -> JSONResponse:
    job = JM.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="未知 job_id")
    return JSONResponse(job.to_public())


@app.get("/api/file/{job_id}/{name:path}")
def api_file(job_id: str, name: str, as_: str | None = Query(None, alias="as")) -> FileResponse:
    p = JM.file_path(job_id, name)
    if p is None:
        raise HTTPException(status_code=404, detail="文件不存在")
    # 另存名:优先用前端传来的友好英文名(?as=),否则磁盘原名。只取 basename 防注入。
    # (同源响应里 Content-Disposition 的 filename 优先级高于 <a download>,故必须在此对齐。)
    dl_name = (Path(as_).name.strip() if as_ else "") or Path(name).name
    return FileResponse(str(p), filename=dl_name)


# ─────────── 静态站(必须在所有 /api 路由之后挂载,否则会吞掉它们)─────────── #
if STATIC.is_dir():
    app.mount("/", StaticFiles(directory=str(STATIC), html=True), name="static")
else:
    @app.get("/")
    def _no_static() -> dict:
        return {"ok": False, "message": f"静态目录缺失:{STATIC}。请确认 design 已复制到 web/static/。"}


# ─────────────────────────── 启动 ─────────────────────────── #
def _free_port(host: str, preferred: int) -> int:
    for p in [preferred, *range(preferred + 1, preferred + 50)]:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, p))
                return p
            except OSError:
                continue
    return preferred


def main() -> None:
    import uvicorn
    host = os.environ.get("MUSICMASTER_HOST", "127.0.0.1")
    try:
        preferred = int(os.environ.get("MUSICMASTER_PORT", "7860"))
    except ValueError:
        preferred = 7860
    port = _free_port(host, preferred)
    url = f"http://{host}:{port}"
    print(
        "\n========================================\n"
        "  MusicMaster 启动中(首次约 10-30 秒)...\n"
        f"  就绪后浏览器自动打开:{url}\n"
        "  若没弹出,手动访问上面的地址。关闭本窗口即停止服务。\n"
        "========================================\n",
        flush=True,
    )
    # 自动开浏览器:改为「显式开启」——启动.bat 会设 MUSICMASTER_OPEN_BROWSER=1,
    # 这样用户双击启动器照常弹浏览器;而开发/预览直接跑模块时不乱弹。
    if os.environ.get("MUSICMASTER_OPEN_BROWSER") == "1":
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
