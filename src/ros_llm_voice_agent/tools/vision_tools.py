# coding: utf-8

from __future__ import unicode_literals

from .schemas import BaseTool, ToolResult


class DetectFaceTool(BaseTool):
    name = "detect_face"
    description = "调用视觉服务检测当前画面中的人脸。"
    risk = "low"
    parameters = {
        "type": "object",
        "properties": {"timeout_sec": {"type": "number", "description": "等待视觉服务超时时间"}},
    }

    def execute(self, args, ctx):
        timeout_sec = float(args.get("timeout_sec", 2.0))
        result = ctx.ros.detect_face(timeout_sec=timeout_sec)
        return ToolResult(bool(result.get("ok")), result.get("message", "face detection requested"), result)
