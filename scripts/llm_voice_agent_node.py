#!/usr/bin/env python
# coding: utf-8

from __future__ import unicode_literals

import os
import sys

import rospy
from std_srvs.srv import Empty, EmptyResponse

from ros_llm_voice_agent.core.agent_harness import AgentHarness
from ros_llm_voice_agent.core.event_types import EVENT_STOP_ALL, SOURCE_SERVICE
from ros_llm_voice_agent.core.session_manager import SessionManager
from ros_llm_voice_agent.llm.generic_chat_client import GenericChatClient
from ros_llm_voice_agent.llm.prompt_builder import PromptBuilder
from ros_llm_voice_agent.memory.jsonl_memory_store import JsonlMemoryStore
from ros_llm_voice_agent.memory.short_term_memory import ShortTermMemory
from ros_llm_voice_agent.ros.ros_adapter import RosAdapter
from ros_llm_voice_agent.ros.ros_params import default_config_path, load_yaml
from ros_llm_voice_agent.ros.ros_subscribers import RosSubscribers
from ros_llm_voice_agent.tools.factory import build_tool_registry
from ros_llm_voice_agent.tools.safety_gate import SafetyGate
from ros_llm_voice_agent.voice.audio_player import AudioPlayer
from ros_llm_voice_agent.voice.stepfun_tts import StepFunTTS
from ros_llm_voice_agent.voice.trigger_router import TriggerRouter
from ros_llm_voice_agent.voice.volcengine_tts import VolcengineTTS


def _param_path(name, default_name):
    return rospy.get_param(name, default_config_path(default_name))


def build_runtime():
    agent_config = load_yaml(_param_path("~agent_config", "agent.yaml"))
    tools_config = load_yaml(_param_path("~tools_config", "tools.yaml"))
    safety_config = load_yaml(_param_path("~safety_config", "safety.yaml"))
    prompts_config = load_yaml(_param_path("~prompts_config", "prompts.yaml"))

    ros_adapter = RosAdapter(rospy, agent_config)
    player = AudioPlayer()
    safety_gate = SafetyGate(safety_config)
    long_memory = JsonlMemoryStore()
    short_memory = ShortTermMemory(agent_config.get("session", {}).get("max_history_turns", 8))
    tool_registry, tool_worker = build_tool_registry(ros_adapter, safety_gate, long_memory, player, tools_config)
    prompt_builder = PromptBuilder(prompts_config)
    chat_client = GenericChatClient(agent_config)
    harness = AgentHarness(chat_client, prompt_builder, tool_registry, short_memory, long_memory)
    trigger_router = TriggerRouter(agent_config.get("session", {}))
    tts = build_tts(agent_config)
    manager = SessionManager(agent_config, trigger_router, harness, tts, player, ros_adapter, tool_worker)
    tool_registry.ctx.session = manager
    player.set_on_play_end(manager.on_play_end)
    return manager, agent_config


def build_tts(agent_config):
    provider = (agent_config.get("tts", {}) or {}).get("provider", "stepfun")
    provider = provider.lower()
    if provider == "volcengine":
        return VolcengineTTS(agent_config)
    if provider == "stepfun":
        return StepFunTTS(agent_config)
    rospy.logwarn("Unknown TTS provider '%s', falling back to StepFunTTS", provider)
    return StepFunTTS(agent_config)


def main():
    rospy.init_node("llm_voice_agent", anonymous=False)
    manager, agent_config = build_runtime()

    enable_realtime_text_topic = bool(
        rospy.get_param("~enable_realtime_text_topic", rospy.get_param("~enable_realtime_stub", False))
    )
    RosSubscribers(rospy, agent_config.get("topics", {}), manager, enable_realtime_text_topic=enable_realtime_text_topic)

    rospy.Service("/llm_voice_agent/start_chat", Empty, lambda req: _start_chat(manager))
    rospy.Service("/llm_voice_agent/stop_chat", Empty, lambda req: _stop_chat(manager))
    rospy.Service("/llm_voice_agent/start_realtime", Empty, lambda req: _start_realtime(manager))
    rospy.Service("/llm_voice_agent/stop_realtime", Empty, lambda req: _stop_realtime(manager))
    rospy.Service("/llm_voice_agent/stop_all", Empty, lambda req: _stop_all(manager))

    rospy.on_shutdown(manager.stop)
    manager.run_forever(rospy)


def _start_chat(manager):
    manager.enqueue_text("和我聊聊天", source=SOURCE_SERVICE, mode="non_realtime")
    return EmptyResponse()


def _stop_chat(manager):
    manager.enqueue_text("退出聊天", source=SOURCE_SERVICE, mode="non_realtime")
    return EmptyResponse()


def _start_realtime(manager):
    manager.enqueue_text("和我聊聊天", source=SOURCE_SERVICE, mode="realtime")
    return EmptyResponse()


def _stop_realtime(manager):
    manager.enqueue_text("退出聊天", source=SOURCE_SERVICE, mode="realtime")
    return EmptyResponse()


def _stop_all(manager):
    manager.enqueue_simple(EVENT_STOP_ALL, source=SOURCE_SERVICE)
    return EmptyResponse()


if __name__ == "__main__":
    try:
        main()
    except rospy.ROSInterruptException:
        pass
    except KeyboardInterrupt:
        pass
