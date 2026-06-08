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


class SetHeadTool(BaseTool):
    name = "set_head"
    description = "控制机器人头部转动。yaw 水平方向（正左负右），pitch 俯仰方向（正抬头负低头），单位度。"
    risk = "low"
    parameters = {
        "type": "object",
        "properties": {
            "yaw_deg": {"type": "number", "description": "水平转动角度，正左负右，约 -60~60"},
            "pitch_deg": {"type": "number", "description": "俯仰角度，正抬头负低头，约 -30~30"},
        },
    }

    def execute(self, args, ctx):
        args = args or {}
        try:
            yaw = float(args.get("yaw_deg", 0.0) or 0.0)
            pitch = float(args.get("pitch_deg", 0.0) or 0.0)
        except Exception:
            yaw, pitch = 0.0, 0.0
        # clamp to a safe range
        yaw = max(-60.0, min(60.0, yaw))
        pitch = max(-30.0, min(30.0, pitch))

        # 1) head publish must carry the current master control id
        control_id = 2
        try:
            id_res = ctx.ros.call_dynamic_service(
                {
                    "service": "/MediumSize/BodyHub/GetMasterID",
                    "service_type": "bodyhub/SrvTLSstring",
                    "timeout_seconds": 2.0,
                    "request": {"constants": {"str": "get"}},
                    "response": {"fields": {"data": "data"}},
                },
                {},
            )
            value = (id_res.get("response") or {}).get("data")
            if value is not None:
                control_id = int(value)
        except Exception:
            control_id = 2

        # 2) publish the head joint command
        result = ctx.ros.publish_dynamic_topic(
            {
                "topic": "/MediumSize/BodyHub/HeadPosition",
                "message_type": "bodyhub/JointControlPoint",
                "queue_size": 10,
                "message": {
                    "fields": {"positions": "positions"},
                    "constants": {"mainControlID": control_id},
                },
            },
            # 机器人头部 pitch 物理正方向是低头，与对外语义相反，发布时取反，
            # 使 pitch_deg>0 = 抬头、pitch_deg<0 = 低头。
            {"positions": [yaw, -pitch]},
        )
        ok = bool(result.get("ok"))
        return ToolResult(
            ok,
            result.get("message", "set head done"),
            {"yaw_deg": yaw, "pitch_deg": pitch, "mainControlID": control_id},
        )
