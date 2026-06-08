# coding: utf-8

import json
import os
import time

import requests

from ros_llm_voice_agent.compat import to_text, to_utf8_bytes
from ros_llm_voice_agent.ros.ros_params import env_value

from .tts_base import BaseTTS, SynthesisResult


class StepFunTTS(BaseTTS):
    """StepFun file-style TTS adapter for the non-realtime voice path."""

    def __init__(self, config):
        tts_cfg = config.get("tts", {})
        self.api_key = env_value(tts_cfg.get("api_key_env", "STEPFUN_TTS_API_KEY"))
        if not self.api_key:
            self.api_key = env_value("LLM_API_KEY")
        self.endpoint = env_value(
            tts_cfg.get("endpoint_env", "STEPFUN_TTS_URL"),
            "https://api.stepfun.ai/v1/audio/speech",
        )
        self.model = env_value(tts_cfg.get("model_env", "STEPFUN_TTS_MODEL")) or tts_cfg.get("model") or "step-tts-2"
        self.voice = env_value(tts_cfg.get("voice_env", "STEPFUN_TTS_VOICE")) or tts_cfg.get("voice") or "lively-girl"
        self.output_dir = tts_cfg.get("output_dir", "/tmp/llm_voice_agent/tts")
        self.audio_format = tts_cfg.get("audio_format", "mp3")
        self.speed = tts_cfg.get("speed", None)
        self.volume = tts_cfg.get("volume", None)
        self.sample_rate = tts_cfg.get("sample_rate", None)
        self.markdown_filter = tts_cfg.get("markdown_filter", None)
        self.instruction = tts_cfg.get("instruction", None)
        self.timeout = float(tts_cfg.get("timeout_seconds", 30))
        if self.output_dir and not os.path.isdir(self.output_dir):
            os.makedirs(self.output_dir)

    def synthesize(self, text):
        text = to_text(text).strip()
        if not text:
            return SynthesisResult(False, message="empty text")
        if not self.endpoint:
            return SynthesisResult(False, message="STEPFUN_TTS_URL is not configured")
        if not self.api_key:
            return SynthesisResult(False, message="STEPFUN_TTS_API_KEY or LLM_API_KEY is not configured")

        headers = {
            "Authorization": "Bearer {}".format(self.api_key),
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "input": text,
            "voice": self.voice,
            "response_format": self.audio_format,
        }
        if self.speed is not None:
            payload["speed"] = float(self.speed)
        if self.volume is not None:
            payload["volume"] = float(self.volume)
        if self.sample_rate is not None:
            payload["sample_rate"] = int(self.sample_rate)
        if self.markdown_filter is not None:
            payload["markdown_filter"] = bool(self.markdown_filter)
        if self.instruction:
            payload["instruction"] = to_text(self.instruction)

        try:
            body = to_utf8_bytes(json.dumps(payload, ensure_ascii=False))
            response = requests.post(self.endpoint, data=body, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            audio_bytes = self._extract_audio_bytes(response)
            if not audio_bytes:
                return SynthesisResult(False, message="stepfun tts response did not contain audio")
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
        if data.get("url"):
            return b""
        return response.content if response.content else b""
