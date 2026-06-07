# coding: utf-8

from __future__ import unicode_literals

import json

from ros_llm_voice_agent.compat import to_text
from ros_llm_voice_agent.llm.base import AgentResponse
from ros_llm_voice_agent.llm.tool_call_parser import parse_agent_response


class AgentHarness:
    def __init__(self, chat_client, prompt_builder, tool_registry, short_memory, long_memory):
        self.chat_client = chat_client
        self.prompt_builder = prompt_builder
        self.tool_registry = tool_registry
        self.short_memory = short_memory
        self.long_memory = long_memory

    def run_turn(self, session_id, mode, user_text):
        response = self._generate_response(user_text, mode)
        reply_text = response.reply_text or "好的。"

        for update in response.memory_updates:
            if isinstance(update, dict):
                self.long_memory.remember(update.get("key", ""), update.get("value", ""), update.get("reason", ""))

        self.short_memory.add_turn(user_text, reply_text)
        return {
            "session_id": session_id,
            "mode": mode,
            "reply_text": reply_text,
            "tool_calls": response.tool_calls,
            "memory_updates": response.memory_updates,
        }

    def execute_realtime_tool_call(self, session_id, tool_name, arguments):
        result = self.tool_registry.execute(tool_name, arguments or {})
        return {
            "session_id": session_id,
            "source": "realtime",
            "tool_name": tool_name,
            "result": result,
        }

    def summarize_tool_results(self, user_text, mode, turn_result, tool_results):
        if not tool_results:
            return ""
        messages = self.prompt_builder.build_messages(
            user_text,
            mode=mode,
            history=self._history_without_current_turn(user_text),
            tool_specs=[],
            memory_items=self.long_memory.recall(user_text, limit=3),
        )
        messages.append({"role": "assistant", "content": to_text(turn_result.get("reply_text", "")) or "我已经调用了工具。"})
        messages.append(
            {
                "role": "user",
                "content": (
                    "工具执行结果如下：\n{}\n\n"
                    "请只根据这些工具结果，用简短自然的中文回答用户。"
                    "不要编造没有出现在工具结果里的数值；不要再次调用工具；不要输出JSON。"
                    "只报告结果，不要自行诊断、警告或给建议；"
                    "如果传感器字段是0、unknown或缺失，只说这是当前返回值，不要推断故障。"
                ).format(json.dumps(tool_results, ensure_ascii=False, indent=2)),
            }
        )
        raw = self.chat_client.generate(messages, tools=None)
        summary = self._response_text(raw)
        if summary:
            self.short_memory.replace_last_assistant(summary)
        return summary

    def _generate_response(self, user_text, mode):
        messages = self.prompt_builder.build_messages(
            user_text,
            mode=mode,
            history=self.short_memory.messages(),
            tool_specs=self.tool_registry.specs(),
            memory_items=self.long_memory.recall(user_text, limit=3),
        )

        raw = self.chat_client.generate(messages, tools=self.tool_registry.specs())
        if isinstance(raw, AgentResponse):
            return raw
        if raw:
            return parse_agent_response(raw)
        return self._fallback_response(user_text)

    def _fallback_response(self, text):
        text = to_text(text)
        compact = "".join(text.split())
        calls = []
        reply = ""

        if any(word in compact for word in ("停止", "停下", "别动")):
            calls.append({"tool": "stop_all", "args": {}})
            reply = "好的，我先停下。"
        elif "电量" in compact or "电池" in compact:
            calls.append({"tool": "get_battery_state", "args": {}})
            reply = "我来查看电量。"
        elif "状态" in compact:
            calls.append({"tool": "get_bodyhub_status", "args": {}})
            reply = "我来查看机器人状态。"
        elif "往前" in compact or "前进" in compact:
            calls.append({"tool": "walk_forward", "args": {"distance_m": 0.2}})
            reply = "好的，我向前走一点。"
        elif "后退" in compact or "往后" in compact:
            calls.append({"tool": "walk_backward", "args": {"distance_m": 0.2}})
            reply = "好的，我向后退一点。"
        elif "左转" in compact:
            calls.append({"tool": "turn", "args": {"angle_deg": 15}})
            reply = "好的，我向左转一点。"
        elif "右转" in compact:
            calls.append({"tool": "turn", "args": {"angle_deg": -15}})
            reply = "好的，我向右转一点。"
        elif "挥手" in compact or "举手" in compact:
            calls.append({"tool": "play_action", "args": {"action_name": "wave"}})
            reply = "好的，我做一个动作。"
        elif "人脸" in compact or "看见" in compact:
            calls.append({"tool": "detect_face", "args": {"timeout_sec": 2.0}})
            reply = "我来看看前面有没有人脸。"
        else:
            reply = "我收到了：{}".format(text)

        return AgentResponse(reply_text=reply, tool_calls=calls)

    def _history_without_current_turn(self, user_text):
        history = self.short_memory.messages()
        if len(history) >= 2:
            last_user = history[-2]
            last_assistant = history[-1]
            if (
                last_user.get("role") == "user"
                and last_assistant.get("role") == "assistant"
                and to_text(last_user.get("content", "")) == to_text(user_text)
            ):
                return history[:-2]
        return history

    def _response_text(self, raw):
        if isinstance(raw, AgentResponse):
            return to_text(raw.reply_text).strip()
        if raw:
            parsed = parse_agent_response(raw)
            if parsed.reply_text:
                return to_text(parsed.reply_text).strip()
            return to_text(raw).strip()
        return ""
