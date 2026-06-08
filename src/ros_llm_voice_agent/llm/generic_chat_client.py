# coding: utf-8

import json
import os

import requests

from ros_llm_voice_agent.compat import to_text, to_utf8_bytes
from ros_llm_voice_agent.llm.base import AgentResponse

from .base import BaseChatClient


class GenericChatClient(BaseChatClient):
    """OpenAI-compatible chat-completion client with a safe disabled mode."""

    def __init__(self, config):
        llm_cfg = config.get("llm", {})
        self.api_key = os.environ.get(llm_cfg.get("api_key_env", "LLM_API_KEY"), "")
        self.base_url = os.environ.get(llm_cfg.get("base_url_env", "LLM_BASE_URL"), "")
        self.model = os.environ.get(llm_cfg.get("model_env", "LLM_MODEL"), "") or llm_cfg.get("model", "")
        self.timeout = float(llm_cfg.get("timeout_seconds", 30))
        self.send_tools_native = bool(llm_cfg.get("send_tools_native", False))
        self.tool_choice = llm_cfg.get("tool_choice", "auto")

    @property
    def configured(self):
        return bool(self.base_url and self.model)

    def generate(self, messages, tools=None):
        if not self.configured:
            return ""

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer {}".format(self.api_key)

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
        }
        if tools and self.send_tools_native:
            formatted_tools = self._format_tools(tools)
            if formatted_tools:
                payload["tools"] = formatted_tools
                if self.tool_choice:
                    payload["tool_choice"] = self.tool_choice

        body = to_utf8_bytes(json.dumps(payload, ensure_ascii=False))
        response = requests.post(self.base_url, data=body, headers=headers, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()

        try:
            message = data["choices"][0]["message"]
        except Exception:
            message = None

        if message is not None:
            if self.send_tools_native:
                return AgentResponse(
                    reply_text=to_text(message.get("content", "")),
                    tool_calls=self._parse_native_tool_calls(message.get("tool_calls", [])),
                )
            return to_text(message.get("content", ""))
        if "output_text" in data:
            return to_text(data["output_text"])
        if "text" in data:
            return to_text(data["text"])
        return ""

    def _format_tools(self, tools):
        formatted = []
        for tool in tools or []:
            if not isinstance(tool, dict):
                continue
            if tool.get("type") == "function" and isinstance(tool.get("function"), dict):
                formatted.append(tool)
                continue
            name = tool.get("name")
            if not name:
                continue
            parameters = tool.get("parameters") or {"type": "object", "properties": {}}
            formatted.append(
                {
                    "type": "function",
                    "function": {
                        "name": to_text(name),
                        "description": to_text(tool.get("description", "")),
                        "parameters": parameters,
                    },
                }
            )
        return formatted

    def _parse_native_tool_calls(self, tool_calls):
        parsed = []
        for call in tool_calls or []:
            if not isinstance(call, dict):
                continue
            function = call.get("function") or {}
            name = function.get("name") or call.get("name")
            if not name:
                continue
            raw_arguments = function.get("arguments", call.get("arguments", {}))
            parsed.append(
                {
                    "tool": to_text(name),
                    "args": self._parse_arguments(raw_arguments),
                    "id": to_text(call.get("id", "")),
                    "source": "native_tool_call",
                    "raw_arguments": raw_arguments,
                }
            )
        return parsed

    def _parse_arguments(self, raw_arguments):
        if isinstance(raw_arguments, dict):
            return raw_arguments
        text = to_text(raw_arguments).strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except Exception:
            return {}
        if isinstance(parsed, dict):
            return parsed
        return {"value": parsed}
