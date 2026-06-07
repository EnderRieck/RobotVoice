from .action_tools import PlayActionTool
from .memory_tools import RecallMemoryTool, RememberFactTool
from .motion_tools import StopMotionTool, TurnTool, WalkBackwardTool, WalkForwardTool
from .registry import ToolContext, ToolRegistry, ToolWorker
from .robot_status_tools import GetBatteryStateTool, GetBodyhubStatusTool
from .speech_tools import StopAllTool, StopSpeakingTool
from .vision_tools import DetectFaceTool


def build_tool_registry(ros_adapter, safety_gate, memory_store, player, tools_config):
    ctx = ToolContext(ros_adapter, safety_gate, memory_store, player)
    registry = ToolRegistry(ctx)
    registry.register(StopSpeakingTool())
    registry.register(StopAllTool())
    registry.register(StopMotionTool())
    registry.register(GetBodyhubStatusTool())
    registry.register(GetBatteryStateTool())
    registry.register(WalkForwardTool())
    registry.register(WalkBackwardTool())
    registry.register(TurnTool())
    registry.register(PlayActionTool((tools_config or {}).get("actions", {})))
    registry.register(DetectFaceTool())
    registry.register(RememberFactTool())
    registry.register(RecallMemoryTool())
    worker = ToolWorker(registry, ros_adapter)
    return registry, worker
