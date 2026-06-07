# coding: utf-8

from __future__ import unicode_literals

from .schemas import BaseTool, ToolResult


class RememberFactTool(BaseTool):
    name = "remember_fact"
    description = "写入一条长期记忆。"
    risk = "low"
    parameters = {
        "type": "object",
        "properties": {
            "key": {"type": "string"},
            "value": {"type": "string"},
            "reason": {"type": "string"},
        },
        "required": ["key", "value"],
    }

    def execute(self, args, ctx):
        record = ctx.memory.remember(args.get("key", ""), args.get("value", ""), args.get("reason", ""))
        return ToolResult(True, "memory saved", record)


class RecallMemoryTool(BaseTool):
    name = "recall_memory"
    description = "查询长期记忆。"
    risk = "low"
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer"},
        },
    }

    def execute(self, args, ctx):
        records = ctx.memory.recall(args.get("query", ""), args.get("limit", 5))
        return ToolResult(True, "memory recalled", {"records": records})
