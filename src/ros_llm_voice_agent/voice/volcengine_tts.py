# coding: utf-8

import base64
import json
import os
import time

import requests

from ros_llm_voice_agent.compat import string_types, to_text, to_utf8_bytes
from ros_llm_voice_agent.ros.ros_params import env_value

from .tts_base import BaseTTS, SynthesisResult


class VolcengineTTS(BaseTTS):
    """Configurable file-style TTS adapter.

    The endpoint is intentionally configurable because Volcengine deployments
    can differ by product/version. It accepts either raw audio responses or JSON
    responses with base64 audio in common fields.
    """

    def __init__(self, config):
        tts_cfg = config.get("tts", {})
        self.api_key = env_value(tts_cfg.get("api_key_env", "VOLCENGINE_TTS_API_KEY"))
        self.endpoint = env_value(tts_cfg.get("endpoint_env", "VOLCENGINE_TTS_URL"))
        self.voice = env_value(tts_cfg.get("voice_env", "VOLCENGINE_TTS_VOICE"), "default")
        self.output_dir = tts_cfg.get("output_dir", "/tmp/llm_voice_agent/tts")
        self.audio_format = tts_cfg.get("audio_format", "wav")
        self.timeout = float(tts_cfg.get("timeout_seconds", 30))
        if self.output_dir and not os.path.isdir(self.output_dir):
            os.makedirs(self.output_dir)

    def synthesize(self, text):
        text = to_text(text).strip()
        if not text:
            return SynthesisResult(False, message="empty text")
        if not self.endpoint:
            return SynthesisResult(False, message="VOLCENGINE_TTS_URL is not configured")

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer {}".format(self.api_key)

        payload = {
            "text": text,
            "voice": self.voice,
            "format": self.audio_format,
        }

        try:
            body = to_utf8_bytes(json.dumps(payload, ensure_ascii=False))
            response = requests.post(self.endpoint, data=body, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            audio_bytes = self._extract_audio_bytes(response)
            if not audio_bytes:
                return SynthesisResult(False, message="tts response did not contain audio")
            path = os.path.join(self.output_dir, "{}.{}".format(int(time.time() * 1000), self.audio_format))
            with open(path, "wb") as f:
                f.write(audio_bytes)
            return SynthesisResult(True, path=path)
        except Exception as exc:
            return SynthesisResult(False, message=to_text(exc))

    def _extract_audio_bytes(self, response):
        content_type = response.headers.get("Content-Type", "")
        if content_type.startswith("audio/") or content_type in ("application/octet-stream", "binary/octet-stream"):
            return response.content

        try:
            data = response.json()
        except Exception:
            return response.content if response.content else b""

        for key in ("audio_base64", "audio", "data", "result"):
            value = data.get(key)
            if isinstance(value, string_types):
                try:
                    return base64.b64decode(value)
                except Exception:
                    continue
            if isinstance(value, dict):
                nested = value.get("audio") or value.get("audio_base64") or value.get("data")
                if isinstance(nested, string_types):
                    try:
                        return base64.b64decode(nested)
                    except Exception:
                        continue
        return b""
