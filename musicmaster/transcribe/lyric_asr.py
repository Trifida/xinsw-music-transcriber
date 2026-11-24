"""V2-only dormant ASR adapter. V1 must never import or call this module."""
import os
from pathlib import Path
from urllib.parse import urlparse

import httpx


# Groq remains available as an optional cloud provider. FunASR is the preferred
# self-hosted provider and must be pointed at an independently running API service.
DEFAULT_GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_GROQ_MODEL = "whisper-large-v3-turbo"
DEFAULT_FUNASR_MODEL = "sensevoice"
DEFAULT_ASR_PROMPT = "请识别音频中实际唱出的中文歌词，按顺序转写；听不清的内容不要猜测或补写。"


class ASRNotConfigured(RuntimeError):
    pass


class ASRRequestError(RuntimeError):
    pass


def _provider_config() -> tuple[str, str, str, str]:
    provider = os.getenv("ASR_PROVIDER", "disabled").strip().lower()
    if provider == "funasr":
        base_url = os.getenv("ASR_BASE_URL", "").strip().rstrip("/")
        model = os.getenv("ASR_MODEL", DEFAULT_FUNASR_MODEL).strip()
    else:
        base_url = os.getenv("ASR_BASE_URL", DEFAULT_GROQ_BASE_URL).strip().rstrip("/")
        model = os.getenv("ASR_MODEL", DEFAULT_GROQ_MODEL).strip()
    api_key = os.getenv("ASR_API_KEY", "").strip()
    return provider, base_url, model, api_key


def get_asr_status() -> dict:
    provider, base_url, model, api_key = _provider_config()
    if provider in {"", "disabled", "none"}:
        return {"available": False, "configured": False, "connectionVerified": False, "status": "disabled", "provider": "none"}
    if provider not in {"openai-compatible", "funasr"}:
        return {"available": False, "configured": False, "connectionVerified": False, "status": "unsupported-provider", "provider": provider}
    if not model:
        return {"available": False, "configured": False, "connectionVerified": False, "status": "misconfigured", "provider": provider}
    if provider == "openai-compatible" and not api_key:
        return {"available": False, "configured": False, "connectionVerified": False, "status": "missing-credentials", "provider": provider}
    if provider == "funasr" and not base_url:
        return {"available": False, "configured": False, "connectionVerified": False, "status": "missing-endpoint", "provider": provider}

    try:
        parsed = urlparse(base_url)
        valid_url = parsed.scheme in {"https", "http"} and bool(parsed.netloc) and bool(parsed.hostname)
    except ValueError:
        valid_url = False
        parsed = None
    if not valid_url or parsed is None:
        return {"available": False, "configured": False, "connectionVerified": False, "status": "misconfigured", "provider": provider}
    # Plain HTTP is permitted for loopback development. A self-hosted FunASR
    # endpoint may also opt in when its operator has verified it is private
    # (for example, a Render internal hostname such as service-name:port).
    allow_private_http = os.getenv("ASR_ALLOW_INSECURE_HTTP", "").strip().lower() in {"1", "true", "yes"}
    is_private_http = parsed.hostname in {"localhost", "127.0.0.1"} or (
        provider == "funasr" and allow_private_http
    )
    if parsed.scheme != "https" and not is_private_http:
        return {"available": False, "configured": False, "connectionVerified": False, "status": "insecure-endpoint", "provider": provider}
    return {"available": True, "configured": True, "connectionVerified": False, "status": "configured-not-verified", "provider": provider, "model": model}


def transcribe_lyrics(audio_path: str) -> dict:
    status = get_asr_status()
    if not status["available"]:
        raise ASRNotConfigured(status["status"])

    provider, base_url, model, api_key = _provider_config()
    try:
        timeout_seconds = float(os.getenv("ASR_TIMEOUT_SECONDS", "90"))
    except ValueError:
        timeout_seconds = 90
    if timeout_seconds < 5 or timeout_seconds > 240:
        timeout_seconds = 90

    path = Path(audio_path)
    try:
        max_file_mb = int(os.getenv("ASR_MAX_FILE_MB", "24"))
    except ValueError:
        max_file_mb = 24
    max_file_mb = max(1, min(max_file_mb, 100))
    try:
        if path.stat().st_size > max_file_mb * 1024 * 1024:
            raise ASRRequestError("audio file exceeds the configured ASR size limit")
    except OSError as exc:
        raise ASRRequestError("audio file could not be accessed") from exc

    if provider == "funasr":
        # FunASR's documented OpenAI-compatible endpoint accepts the model alias
        # and verbose_json response format. SenseVoice performs language detection.
        form_data = {"model": model, "response_format": "verbose_json"}
    else:
        language = os.getenv("ASR_LANGUAGE", "zh").strip() or "zh"
        prompt = os.getenv("ASR_PROMPT", DEFAULT_ASR_PROMPT).strip()
        form_data = {
            "model": model,
            "language": language,
            "response_format": "json",
        }
        if prompt:
            # Groq documents a short prompt field (up to 224 tokens).
            form_data["prompt"] = prompt[:100]

    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        with path.open("rb") as audio_file:
            response = httpx.post(
                f"{base_url}/audio/transcriptions",
                headers=headers,
                data=form_data,
                files={"file": (path.name, audio_file, "application/octet-stream")},
                timeout=httpx.Timeout(timeout_seconds, connect=10),
            )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError, OSError) as exc:
        raise ASRRequestError("speech-to-text request failed") from exc

    text = payload.get("text") if isinstance(payload, dict) else None
    if not isinstance(text, str):
        raise ASRRequestError("speech-to-text response did not contain text")
    text = text.strip()
    if len(text) > 20000:
        raise ASRRequestError("speech-to-text response exceeded the lyric length limit")
    return {"text": text, "provider": provider, "model": model}
