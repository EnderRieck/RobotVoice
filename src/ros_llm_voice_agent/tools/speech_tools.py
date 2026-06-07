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


class StartRealtimeVoiceTool(BaseTool):
    name = "start_realtime_voice"
    description = "进入实时语音/连续对话模式。用户希望持续聊天、免唤醒连续说话、开始实时语音或陪他聊天时调用。"
    risk = "low"
    parameters = {"type": "object", "properties": {}}

    def execute(self, args, ctx):
        if ctx.session is None:
            return ToolResult(False, "session manager is not attached")
        result = ctx.session.start_realtime_from_tool()
        return ToolResult(bool(result.get("ok")), result.get("message", "realtime voice requested"), result)


class StopRealtimeVoiceTool(BaseTool):
    name = "stop_realtime_voice"
    description = "退出实时语音/连续对话模式。用户表示不聊了、退出实时语音、停止连续监听时调用。"
    risk = "low"
    parameters = {"type": "object", "properties": {}}

    def execute(self, args, ctx):
        if ctx.session is None:
            return ToolResult(False, "session manager is not attached")
        result = ctx.session.stop_realtime_from_tool()
        return ToolResult(bool(result.get("ok")), result.get("message", "realtime voice stop requested"), result)
