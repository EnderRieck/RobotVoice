# coding: utf-8

from __future__ import unicode_literals

from .schemas import BaseTool, ToolResult


class GetBodyhubStatusTool(BaseTool):
    name = "get_bodyhub_status"
    description = "查询机器人 BodyHub 状态。"
    risk = "low"
    parameters = {"type": "object", "properties": {}}

    def execute(self, args, ctx):
        data = ctx.ros.get_bodyhub_status()
        return ToolResult(bool(data.get("available")), data.get("message", "bodyhub status queried"), data)


class GetBatteryStateTool(BaseTool):
    name = "get_battery_state"
    description = "查询机器人电池状态。"
    risk = "low"
    parameters = {"type": "object", "properties": {}}

    def execute(self, args, ctx):
        data = ctx.ros.get_battery_state()
        return ToolResult(bool(data.get("available")), data.get("message", "battery state queried"), data)
