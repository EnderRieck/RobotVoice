# coding: utf-8

from __future__ import unicode_literals

import json

from ros_llm_voice_agent.compat import to_text


class PromptBuilder:
    def __init__(self, prompts_config):
        self.system_prompt = prompts_config.get("system_prompt", "")
        self.tool_protocol = prompts_config.get("tool_protocol", "")

    def build_messages(self, user_text, mode=None, history=None, tool_specs=None, memory_items=None):
        user_text = to_text(user_text)
        mode = to_text(mode)
        history = history or []
        tool_specs = tool_specs or []
        memory_items = memory_items or []

        system_parts = [self.system_prompt, self.tool_protocol]
        if mode:
            if mode == "realtime":
                system_parts.append("当前是实时语音模式。回复要短、口语化，通常一到两句；不要使用 Markdown 或列表；需要控制机器人时照常调用工具。")
            else:
                system_parts.append("当前交互模式: {}".format(mode))
        if tool_specs:
            system_parts.append("可用工具:\n{}".format(json.dumps(tool_specs, ensure_ascii=False, indent=2)))
        if memory_items:
            system_parts.append("相关记忆:\n{}".format(json.dumps(memory_items, ensure_ascii=False, indent=2)))

        messages = [{"role": "system", "content": "\n\n".join([p for p in system_parts if p])}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_text})
        return messages
