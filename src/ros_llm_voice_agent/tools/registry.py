# coding: utf-8

import threading

try:
    import queue
except ImportError:
    import Queue as queue

from ros_llm_voice_agent.compat import to_text

from .schemas import ToolResult


class ToolContext:
    def __init__(self, ros, safety, memory, player):
        self.ros = ros
        self.safety = safety
        self.memory = memory
        self.player = player


class ToolRegistry:
    def __init__(self, ctx):
        self.ctx = ctx
        self._tools = {}

    def register(self, tool):
        self._tools[tool.name] = tool

    def specs(self):
        return [tool.spec() for tool in self._tools.values()]

    def execute(self, tool_name, args=None):
        args = args or {}
        tool = self._tools.get(tool_name)
        if not tool:
            return ToolResult(False, "unknown tool: {}".format(tool_name)).to_dict()
        try:
            return tool.execute(args, self.ctx).to_dict()
        except Exception as exc:
            return ToolResult(False, to_text(exc)).to_dict()

    def execute_calls(self, calls):
        results = []
        for call in calls or []:
            name = call.get("tool") or call.get("name") or call.get("tool_name")
            args = call.get("args") or call.get("arguments") or {}
            result = self.execute(name, args)
            results.append({"tool": name, "args": args, "result": result})
        return results


class ToolWorker:
    def __init__(self, registry, ros):
        self.registry = registry
        self.ros = ros
        self._queue = queue.Queue()
        self._thread = threading.Thread(target=self._run)
        self._thread.setDaemon(True)
        self._thread.start()

    def submit(self, tool_name, args=None, immediate=False):
        if immediate:
            result = self.registry.execute(tool_name, args or {})
            self.ros.publish_tool_event({"tool": tool_name, "args": args or {}, "result": result, "immediate": True})
            return result
        self._queue.put((tool_name, args or {}))
        return {"ok": True, "message": "queued"}

    def _run(self):
        while True:
            tool_name, args = self._queue.get()
            result = self.registry.execute(tool_name, args)
            self.ros.publish_tool_event({"tool": tool_name, "args": args, "result": result, "immediate": False})
            self._queue.task_done()
