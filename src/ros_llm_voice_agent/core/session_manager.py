# coding: utf-8

from __future__ import unicode_literals

try:
    import queue
except ImportError:
    import Queue as queue

import threading
import time

from ros_llm_voice_agent.core.event_types import (
    EVENT_STOP_ALL,
    EVENT_STOP_PLAY,
    EVENT_TEXT,
    EVENT_TOOL_CALL,
    EVENT_WAKEUP,
    AgentEvent,
    SOURCE_AIUI,
    SOURCE_REALTIME,
)
from ros_llm_voice_agent.core.state_machine import AgentStateMachine, STATE_CHAT, STATE_IDLE, STATE_REALTIME
from ros_llm_voice_agent.compat import to_text
from ros_llm_voice_agent.voice.text_sanitizer import sanitize_for_tts


class SessionManager:
    def __init__(self, config, trigger_router, harness, tts, player, ros_adapter, tool_worker):
        self.config = config
        self.session_config = config.get("session", {})
        self.realtime_config = config.get("realtime", {})
        self.session_id = self.session_config.get("default_session_id", "main")
        self.trigger_router = trigger_router
        self.harness = harness
        self.tts = tts
        self.player = player
        self.ros = ros_adapter
        self.tool_worker = tool_worker
        self.state = AgentStateMachine()
        self.events = queue.Queue()
        self._running = False
        self._listen_arm_pending = False
        self._listen_watchdog_timer = None
        self._listen_generation = 0
        self._last_input_text = ""
        self._last_input_time = 0.0

    def enqueue_text(self, text, source, mode):
        self.events.put(AgentEvent(EVENT_TEXT, source, {"text": text, "mode": mode}))

    def enqueue_wakeup(self, raw):
        self.events.put(AgentEvent(EVENT_WAKEUP, "ros", {"raw": raw}))

    def enqueue_simple(self, event_type, source="system"):
        self.events.put(AgentEvent(event_type, source, {}))

    def enqueue_tool_call(self, tool_name, arguments=None, source="realtime"):
        self.events.put(AgentEvent(EVENT_TOOL_CALL, source, {"tool_name": tool_name, "arguments": arguments or {}}))

    def run_forever(self, rospy):
        self._running = True
        self.ros.publish_state(self.state.state)
        rate = rospy.Rate(20)
        while not rospy.is_shutdown() and self._running:
            try:
                event = self.events.get(timeout=0.05)
            except queue.Empty:
                rate.sleep()
                continue
            self._handle_event(event)
            self.events.task_done()
            rate.sleep()

    def stop(self):
        self._running = False
        self._cancel_listen_watchdog()

    def on_play_end(self):
        self.ros.publish_play_end()
        if self._is_realtime_state():
            delay = float(self.realtime_config.get("listen_after_reply_delay_seconds", 0.5))
            self._schedule_realtime_listen(delay=delay, reason="play_end")

    def _handle_event(self, event):
        if event.event_type == EVENT_TEXT:
            self._handle_text(event)
        elif event.event_type == EVENT_WAKEUP:
            self._handle_wakeup(event)
        elif event.event_type == EVENT_STOP_PLAY:
            self.player.stop()
            if self._is_realtime_state():
                self._schedule_realtime_listen(delay=0.2, reason="stop_play")
        elif event.event_type == EVENT_STOP_ALL:
            self.tool_worker.submit("stop_all", {}, immediate=True)
        elif event.event_type == EVENT_TOOL_CALL:
            self._handle_realtime_tool_call(event)

    def _handle_text(self, event):
        text = to_text(event.payload.get("text", "")).strip()
        if not text:
            if self._is_realtime_state():
                delay = float(self.realtime_config.get("empty_text_rearm_delay_seconds", 0.2))
                self._schedule_realtime_listen(delay=delay, reason="empty_text")
            return
        self._cancel_listen_watchdog()

        mode = event.payload.get("mode", "non_realtime")
        self.ros.publish_transcript(text)

        if self.trigger_router.is_exit_trigger(text):
            self.state.set_idle()
            self.ros.publish_state(self.state.state)
            self.player.stop()
            self._cancel_listen_watchdog()
            self._speak(self.realtime_config.get("exit_ack", "好的，我退出聊天模式。"))
            return

        if self.trigger_router.is_chat_trigger(text):
            if self._realtime_enabled():
                self.state.set_realtime()
                self.ros.publish_state(self.state.state, {"mode": "realtime"})
                self._speak(self.realtime_config.get("enter_ack", "好的，我们来聊天。"))
            else:
                self.state.set_chat()
                self.ros.publish_state(self.state.state)
                self._speak("好的，我们来聊天。")
            return

        mode = self._effective_mode(mode, event.source)
        if self._should_drop_text(text, mode):
            return

        if mode == "realtime":
            self.state.set_realtime()
        elif self.state.state == STATE_IDLE:
            self.state.set_chat()
        self.ros.publish_state(self.state.state)

        result = self.harness.run_turn(self.session_id, self.state.state, text)
        tool_results = []
        for call in result.get("tool_calls", []) or []:
            name = call.get("tool") or call.get("name") or call.get("tool_name")
            args = call.get("args") or call.get("arguments") or {}
            immediate = self._should_execute_tool_immediately(name)
            queue_result = self.tool_worker.submit(name, args, immediate=immediate)
            if immediate:
                tool_results.append({"tool": name, "args": args, "result": queue_result})
            self.ros.publish_tool_event({"type": "agent_tool_submit", "tool": name, "args": args, "result": queue_result})
        self.ros.publish_tool_event({"type": "agent_turn", "result": result})
        reply_text = result.get("reply_text", "")
        if tool_results:
            summarized = self.harness.summarize_tool_results(text, self.state.state, result, tool_results)
            if summarized:
                reply_text = summarized
        self._speak(reply_text)

    def _handle_realtime_tool_call(self, event):
        tool_name = event.payload.get("tool_name")
        args = event.payload.get("arguments") or {}
        immediate = self._should_execute_tool_immediately(tool_name)
        if immediate:
            result = self.tool_worker.submit(tool_name, args, immediate=True)
        else:
            result = self.tool_worker.submit(tool_name, args, immediate=False)
        self.ros.publish_tool_event({"type": "realtime_tool_call", "tool": tool_name, "args": args, "result": result})

    def _should_execute_tool_immediately(self, tool_name):
        tool_name = to_text(tool_name)
        if tool_name in ("stop_all", "stop_motion", "stop_speaking", "get_bodyhub_status", "get_battery_state", "detect_face"):
            return True
        if tool_name.startswith("dynamic_get_") or tool_name.startswith("dynamic_detect_") or tool_name == "dynamic_stop_aiui_playback":
            return True
        return False

    def _speak(self, text):
        text = to_text(text).strip()
        if not text:
            return
        self.ros.publish_reply(text)
        tts_text = sanitize_for_tts(text)
        if not tts_text:
            self.ros.publish_tool_event({"type": "tts_error", "message": "sanitized text is empty"})
            if self._is_realtime_state():
                self._schedule_realtime_listen(delay=0.2, reason="tts_empty")
            return
        if tts_text != text:
            self.ros.publish_tool_event({"type": "tts_text_sanitized", "raw_length": len(text), "tts_length": len(tts_text)})
        result = self.tts.synthesize(tts_text)
        if not result.ok:
            self.ros.publish_tool_event({"type": "tts_error", "message": result.message})
            if self._is_realtime_state():
                self._schedule_realtime_listen(delay=0.2, reason="tts_error")
            return
        ok, message = self.player.play(result.path)
        if not ok:
            self.ros.publish_tool_event({"type": "play_error", "message": message, "path": result.path})
            if self._is_realtime_state():
                self._schedule_realtime_listen(delay=0.2, reason="play_error")

    def _handle_wakeup(self, event):
        raw = to_text(event.payload.get("raw", ""))
        self.ros.publish_state(self.state.state, {"wakeup": raw})
        if self._is_realtime_state() and bool(self.realtime_config.get("interrupt_on_wakeup", True)):
            if self.player.is_playing():
                self.player.stop()
                self.ros.publish_tool_event({"type": "realtime_interrupt", "reason": "wakeup"})
            self._schedule_realtime_listen(delay=0.2, reason="wakeup")

    def _realtime_enabled(self):
        return bool(self.realtime_config.get("enabled", True))

    def _is_realtime_state(self):
        return self.state.state == STATE_REALTIME and self._realtime_enabled()

    def _effective_mode(self, mode, source):
        if mode == "realtime":
            return "realtime"
        if self._is_realtime_state() and source in (SOURCE_AIUI, SOURCE_REALTIME):
            return "realtime"
        return mode

    def _should_drop_text(self, text, mode):
        now = time.time()
        duplicate_window = float(self.realtime_config.get("duplicate_text_window_seconds", 1.5))
        if text == self._last_input_text and now - self._last_input_time < duplicate_window:
            self.ros.publish_tool_event({"type": "drop_text", "reason": "duplicate", "text": text})
            return True

        if mode != "realtime":
            self._last_input_text = text
            self._last_input_time = now
            return False

        if bool(self.realtime_config.get("ignore_while_speaking", True)) and self.player.is_playing():
            self.ros.publish_tool_event({"type": "drop_text", "reason": "speaking", "text": text})
            return True

        grace = float(self.realtime_config.get("self_speech_grace_seconds", 0.2))
        since_end = self.player.seconds_since_end()
        if since_end is not None and since_end < grace:
            self.ros.publish_tool_event({"type": "drop_text", "reason": "play_end_grace", "text": text})
            return True

        self._last_input_text = text
        self._last_input_time = now
        return False

    def _schedule_realtime_listen(self, delay=0.5, reason="unknown"):
        if not bool(self.realtime_config.get("auto_listen_after_reply", True)):
            return
        if self._listen_arm_pending:
            return
        self._listen_arm_pending = True
        timer = threading.Timer(delay, self._arm_realtime_listen, args=(reason,))
        timer.setDaemon(True)
        timer.start()

    def _arm_realtime_listen(self, reason):
        self._listen_arm_pending = False
        if not self._is_realtime_state() or not self._running:
            return
        result = self.ros.request_aiui_listen(
            need_to_play_reply=bool(self.realtime_config.get("need_to_play_wakeup_reply", False)),
            timeout_sec=float(self.realtime_config.get("wakeup_mute_timeout_seconds", 2.0)),
        )
        result["type"] = "realtime_listen_arm"
        result["reason"] = reason
        self.ros.publish_tool_event(result)
        if result.get("ok"):
            self._schedule_listen_watchdog(reason)

    def _schedule_listen_watchdog(self, reason):
        if not bool(self.realtime_config.get("listen_watchdog_enabled", True)):
            return
        self._cancel_listen_watchdog()
        self._listen_generation += 1
        generation = self._listen_generation
        timeout_sec = float(self.realtime_config.get("listen_watchdog_seconds", 8.0))
        timer = threading.Timer(timeout_sec, self._listen_watchdog_timeout, args=(generation, reason))
        timer.setDaemon(True)
        self._listen_watchdog_timer = timer
        timer.start()
        self.ros.publish_tool_event({"type": "listen_watchdog_start", "seconds": timeout_sec, "reason": reason})

    def _cancel_listen_watchdog(self):
        self._listen_generation += 1
        timer = self._listen_watchdog_timer
        self._listen_watchdog_timer = None
        if timer is not None:
            try:
                timer.cancel()
            except Exception:
                pass

    def _listen_watchdog_timeout(self, generation, reason):
        if generation != self._listen_generation:
            return
        self._listen_watchdog_timer = None
        if not self._is_realtime_state() or not self._running:
            return
        if self.player.is_playing():
            self._schedule_listen_watchdog("speaking")
            return
        self.ros.publish_tool_event({"type": "listen_watchdog_timeout", "reason": reason})
        self._schedule_realtime_listen(delay=0.0, reason="listen_watchdog")
