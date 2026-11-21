import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import httpx

from musicmaster.transcribe.lyric_asr import ASRNotConfigured, ASRRequestError, get_asr_status, transcribe_lyrics


class LyricASRConfigTests(unittest.TestCase):
    def test_asr_is_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(get_asr_status()["available"])
            with self.assertRaises(ASRNotConfigured):
                transcribe_lyrics("unused.wav")

    def test_missing_api_key_does_not_enable_groq_provider(self):
        with patch.dict(os.environ, {"ASR_PROVIDER": "openai-compatible"}, clear=True):
            self.assertEqual(get_asr_status()["status"], "missing-credentials")

    def test_groq_is_the_default_compatible_endpoint_and_model(self):
        with patch.dict(os.environ, {
            "ASR_PROVIDER": "openai-compatible",
            "ASR_API_KEY": "test-secret",
        }, clear=True):
            status = get_asr_status()
        self.assertTrue(status["available"])
        self.assertEqual(status["model"], "whisper-large-v3-turbo")

    def test_funasr_requires_an_explicit_service_endpoint(self):
        with patch.dict(os.environ, {"ASR_PROVIDER": "funasr"}, clear=True):
            status = get_asr_status()
        self.assertFalse(status["available"])
        self.assertEqual(status["status"], "missing-endpoint")
        self.assertEqual(status["provider"], "funasr")

    def test_funasr_uses_sensevoice_default_without_api_key(self):
        with patch.dict(os.environ, {
            "ASR_PROVIDER": "funasr",
            "ASR_BASE_URL": "https://speech.example/v1",
        }, clear=True):
            status = get_asr_status()
        self.assertTrue(status["available"])
        self.assertTrue(status["configured"])
        self.assertFalse(status["connectionVerified"])
        self.assertEqual(status["status"], "configured-not-verified")
        self.assertEqual(status["model"], "sensevoice")

    def test_malformed_endpoint_is_reported_without_crashing_health_status(self):
        with patch.dict(os.environ, {
            "ASR_PROVIDER": "funasr",
            "ASR_BASE_URL": "http://[",
        }, clear=True):
            status = get_asr_status()
        self.assertFalse(status["available"])
        self.assertEqual(status["status"], "misconfigured")

    def test_non_https_public_endpoint_is_rejected(self):
        with patch.dict(os.environ, {
            "ASR_PROVIDER": "openai-compatible",
            "ASR_API_KEY": "test-secret",
            "ASR_BASE_URL": "http://example.com/v1",
        }, clear=True):
            self.assertEqual(get_asr_status()["status"], "insecure-endpoint")

    def test_funasr_http_requires_explicit_private_network_opt_in(self):
        with patch.dict(os.environ, {
            "ASR_PROVIDER": "funasr",
            "ASR_BASE_URL": "http://speech-engine:8000/v1",
        }, clear=True):
            self.assertEqual(get_asr_status()["status"], "insecure-endpoint")
        with patch.dict(os.environ, {
            "ASR_PROVIDER": "funasr",
            "ASR_BASE_URL": "http://speech-engine:8000/v1",
            "ASR_ALLOW_INSECURE_HTTP": "true",
        }, clear=True):
            self.assertTrue(get_asr_status()["available"])


class LyricASRRequestTests(unittest.TestCase):
    def test_sends_audio_to_compatible_endpoint_and_returns_text(self):
        response = Mock()
        response.json.return_value = {"text": "春风又绿江南岸"}
        response.raise_for_status.return_value = None
        with tempfile.TemporaryDirectory() as directory:
            audio_path = Path(directory) / "sample.wav"
            audio_path.write_bytes(b"fake-audio")
            with patch.dict(os.environ, {
                "ASR_PROVIDER": "openai-compatible",
                "ASR_API_KEY": "test-secret",
                "ASR_BASE_URL": "https://speech.example/v1",
                "ASR_MODEL": "whisper-test",
                "ASR_LANGUAGE": "zh",
                "ASR_PROMPT": "请按实际听到的内容转写中文歌词。",
            }, clear=True), patch("app.lyric_asr.httpx.post", return_value=response) as post:
                result = transcribe_lyrics(str(audio_path))
        self.assertEqual(result["text"], "春风又绿江南岸")
        self.assertEqual(result["provider"], "openai-compatible")
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://speech.example/v1/audio/transcriptions")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-secret")
        self.assertEqual(kwargs["data"]["language"], "zh")
        self.assertEqual(kwargs["data"]["model"], "whisper-test")
        self.assertEqual(kwargs["data"]["prompt"], "请按实际听到的内容转写中文歌词。")
        self.assertIn("file", kwargs["files"])

    def test_funasr_uses_sensevoice_verbose_json_without_required_api_key(self):
        response = Mock()
        response.json.return_value = {"text": "春风又绿江南岸", "segments": []}
        response.raise_for_status.return_value = None
        with tempfile.TemporaryDirectory() as directory:
            audio_path = Path(directory) / "sample.wav"
            audio_path.write_bytes(b"fake-audio")
            with patch.dict(os.environ, {
                "ASR_PROVIDER": "funasr",
                "ASR_BASE_URL": "https://speech.example/v1",
            }, clear=True), patch("app.lyric_asr.httpx.post", return_value=response) as post:
                result = transcribe_lyrics(str(audio_path))
        self.assertEqual(result, {
            "text": "春风又绿江南岸",
            "provider": "funasr",
            "model": "sensevoice",
        })
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://speech.example/v1/audio/transcriptions")
        self.assertEqual(kwargs["data"], {
            "model": "sensevoice",
            "response_format": "verbose_json",
        })
        self.assertEqual(kwargs["headers"], {})
        self.assertIn("file", kwargs["files"])

    def test_funasr_sends_optional_gateway_token_when_configured(self):
        response = Mock()
        response.json.return_value = {"text": "歌词"}
        response.raise_for_status.return_value = None
        with tempfile.TemporaryDirectory() as directory:
            audio_path = Path(directory) / "sample.wav"
            audio_path.write_bytes(b"fake-audio")
            with patch.dict(os.environ, {
                "ASR_PROVIDER": "funasr",
                "ASR_BASE_URL": "https://speech.example/v1",
                "ASR_API_KEY": "gateway-secret",
            }, clear=True), patch("app.lyric_asr.httpx.post", return_value=response) as post:
                transcribe_lyrics(str(audio_path))
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer gateway-secret")

    def test_provider_http_error_is_reported_as_safe_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            audio_path = Path(directory) / "sample.wav"
            audio_path.write_bytes(b"fake-audio")
            with patch.dict(os.environ, {
                "ASR_PROVIDER": "openai-compatible",
                "ASR_API_KEY": "test-secret",
            }, clear=True), patch("app.lyric_asr.httpx.post", side_effect=httpx.TimeoutException("private details")):
                with self.assertRaises(ASRRequestError):
                    transcribe_lyrics(str(audio_path))


if __name__ == "__main__":
    unittest.main()
