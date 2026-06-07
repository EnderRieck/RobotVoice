# coding: utf-8

from __future__ import unicode_literals

from .schemas import BaseTool, ToolResult


class StopMotionTool(BaseTool):
    name = "stop_motion"
    description = "停止机器人运动。"
    risk = "low"
    parameters = {"type": "object", "properties": {}}

    def execute(self, args, ctx):
        result = ctx.ros.stop_motion()
        return ToolResult(bool(result.get("ok")), result.get("message", "motion stop requested"), result)


class WalkForwardTool(BaseTool):
    name = "walk_forward"
    description = "让机器人向前短距离行走。"
    risk = "motion"
    parameters = {
        "type": "object",
        "properties": {"distance_m": {"type": "number", "description": "前进距离，米"}},
        "required": ["distance_m"],
    }

    def execute(self, args, ctx):
        distance = ctx.safety.clamp_forward(args.get("distance_m", 0.1))
        result = ctx.ros.walk_delta(x_m=distance)
        return ToolResult(bool(result.get("ok")), result.get("message", "walk forward done"), result)


class WalkBackwardTool(BaseTool):
    name = "walk_backward"
    description = "让机器人向后短距离行走。"
    risk = "motion"
    parameters = {
        "type": "object",
        "properties": {"distance_m": {"type": "number", "description": "后退距离，米"}},
        "required": ["distance_m"],
    }

    def execute(self, args, ctx):
        distance = ctx.safety.clamp_backward(args.get("distance_m", 0.1))
        result = ctx.ros.walk_delta(x_m=-distance)
        return ToolResult(bool(result.get("ok")), result.get("message", "walk backward done"), result)


class TurnTool(BaseTool):
    name = "turn"
    description = "让机器人原地小角度转向，正数左转，负数右转。"
    risk = "motion"
    parameters = {
        "type": "object",
        "properties": {"angle_deg": {"type": "number", "description": "旋转角度，度"}},
        "required": ["angle_deg"],
    }

    def execute(self, args, ctx):
        angle = ctx.safety.clamp_turn(args.get("angle_deg", 10))
        result = ctx.ros.walk_delta(theta_deg=angle)
        return ToolResult(bool(result.get("ok")), result.get("message", "turn done"), result)
