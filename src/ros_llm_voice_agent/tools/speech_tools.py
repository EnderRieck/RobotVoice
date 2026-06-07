# coding: utf-8

from __future__ import unicode_literals

from .schemas import BaseTool, ToolResult


class StopSpeakingTool(BaseTool):
    name = "stop_speaking"
    description = "停止当前语音播放。"
    risk = "low"
    parameters = {"type": "object", "properties": {}}

    def execute(self, args, ctx):
        ctx.player.stop()
        return ToolResult(True, "speaking stopped")


class StopAllTool(BaseTool):
    name = "stop_all"
    description = "停止语音、动作和运动。"
    risk = "low"
    parameters = {"type": "object", "properties": {}}

    def execute(self, args, ctx):
        ctx.player.stop()
        action = ctx.ros.stop_action()
        motion = ctx.ros.stop_motion()
        return ToolResult(True, "all stop requested", {"action": action, "motion": motion})
