# coding: utf-8

import json
import re

from ros_llm_voice_agent.compat import to_text

from .base import AgentResponse


def _strip_code_fence(text):
    text = (text or "").strip()
    match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, flags=re.S)
    return match.group(1).strip() if match else text


def parse_agent_response(text):
    text = _strip_code_fence(text)
    if not text:
        return AgentResponse(reply_text="")

    try:
        payload = json.loads(text)
    except Exception:
        return AgentResponse(reply_text=text)

    if not isinstance(payload, dict):
        return AgentResponse(reply_text=text)

    return AgentResponse(
        reply_text=to_text(payload.get("reply_text", "")),
        tool_calls=payload.get("tool_calls", []) or [],
        memory_updates=payload.get("memory_updates", []) or [],
    )
