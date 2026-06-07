# coding: utf-8

from __future__ import unicode_literals

from ros_llm_voice_agent.compat import to_text

from .schemas import BaseTool, ToolResult


class PlayActionTool(BaseTool):
    name = "play_action"
    description = "播放白名单中的机器人动作。"
    risk = "medium"
    parameters = {
        "type": "object",
        "properties": {"action_name": {"type": "string", "description": "动作白名单名称"}},
        "required": ["action_name"],
    }

    def __init__(self, actions_config):
        self.actions = actions_config or {}
        action_schema = dict(self.parameters["properties"]["action_name"])
        action_schema["enum"] = sorted(self.actions.keys())
        self.parameters = {
            "type": "object",
            "properties": {"action_name": action_schema},
            "required": ["action_name"],
        }

    def execute(self, args, ctx):
        action_name = to_text(args.get("action_name", "")).strip()
        action = self.actions.get(action_name)
        if not action:
            return ToolResult(False, "unknown whitelisted action: {}".format(action_name))
        result = ctx.ros.play_action(action.get("path", ""))
        return ToolResult(bool(result.get("ok")), result.get("message", "action requested"), result)
