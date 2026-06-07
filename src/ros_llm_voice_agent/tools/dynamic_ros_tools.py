# coding: utf-8

from __future__ import unicode_literals

from ros_llm_voice_agent.compat import to_text

from .schemas import BaseTool, ToolResult


SUPPORTED_DYNAMIC_TOOL_TYPES = ("service", "topic", "listener")


class DynamicRosTool(BaseTool):
    """Tool generated from config/tools.yaml dynamic_ros_tools entries."""

    def __init__(self, definition):
        self.definition = definition or {}
        self.name = to_text(self.definition.get("name", "")).strip()
        self.description = to_text(self.definition.get("description", "")).strip()
        self.risk = to_text(self.definition.get("risk", "low")).strip() or "low"
        self.kind = to_text(self.definition.get("type", self.definition.get("kind", ""))).strip().lower()

        parameters = self.definition.get("parameters")
        if not isinstance(parameters, dict):
            parameters = {"type": "object", "properties": {}}
        self.parameters = parameters

        if not self.description and self.name:
            self.description = "调用动态 ROS 工具 {}".format(self.name)

    def is_valid(self):
        return bool(self.name and self.kind in SUPPORTED_DYNAMIC_TOOL_TYPES)

    def prepare(self, ros_adapter):
        if self.kind == "listener":
            return ros_adapter.register_dynamic_listener(self.definition)
        return {"ok": True, "message": "no preparation needed"}

    def execute(self, args, ctx):
        args = args or {}
        if self.kind == "service":
            result = ctx.ros.call_dynamic_service(self.definition, args)
        elif self.kind == "topic":
            result = ctx.ros.publish_dynamic_topic(self.definition, args)
        elif self.kind == "listener":
            result = ctx.ros.read_dynamic_listener(self.definition, args)
        else:
            result = {"ok": False, "message": "unsupported dynamic tool type: {}".format(self.kind)}

        return ToolResult(bool(result.get("ok")), result.get("message", "dynamic ROS tool finished"), result)


def iter_dynamic_tool_definitions(tools_config):
    dynamic = (tools_config or {}).get("dynamic_ros_tools", {})
    if isinstance(dynamic, dict):
        for name, definition in dynamic.items():
            if not isinstance(definition, dict):
                continue
            item = dict(definition)
            item.setdefault("name", name)
            yield item
    elif isinstance(dynamic, list):
        for definition in dynamic:
            if isinstance(definition, dict):
                yield definition


def build_dynamic_ros_tools(tools_config, ros_adapter=None):
    tools = []
    for definition in iter_dynamic_tool_definitions(tools_config):
        tool = DynamicRosTool(definition)
        if not tool.is_valid():
            _warn(ros_adapter, "Skip invalid dynamic ROS tool definition: %s", definition)
            continue
        if ros_adapter is not None:
            result = tool.prepare(ros_adapter)
            if not result.get("ok"):
                _warn(ros_adapter, "Dynamic ROS tool '%s' preparation failed: %s", tool.name, result.get("message", ""))
        tools.append(tool)
    return tools


def _warn(ros_adapter, message, *args):
    try:
        ros_adapter.rospy.logwarn(message, *args)
    except Exception:
        pass
