#!/usr/bin/env python
# coding: utf-8

from __future__ import unicode_literals

import base64
import audioop
import json
import os
import subprocess
import threading
import time

import rospy
from std_msgs.msg import String, UInt8MultiArray
from std_srvs.srv import Trigger, TriggerResponse

from ros_llm_voice_agent.compat import PY2, to_ros_string, to_text
from ros_llm_voice_agent.ros.ros_params import default_config_path, load_yaml
from ros_llm_voice_agent.srv import ExecuteTool, GetToolSpecs

try:
    import websocket
except Exception:
    websocket = None


class StepFunRealtimeVoiceNode:
    def __init__(self, config):
        self.config = config or {}
        self.realtime_config = self.config.get("stepfun_realtime", {})
        self.audio_config = self.config.get("audio", {})
        self.ros_config = self.config.get("ros", {})

        self.state_pub = rospy.Publisher(
            self.ros_config.get("state_topic", "/llm_voice_agent/stepfun_realtime/state"), String, queue_size=10
        )
        self.transcript_pub = rospy.Publisher(
            self.ros_config.get("transcript_topic", "/llm_voice_agent/transcript"), String, queue_size=10
        )
        self.reply_pub = rospy.Publisher(
            self.ros_config.get("reply_text_topic", "/llm_voice_agent/reply_text"), String, queue_size=10
        )
        self.event_pub = rospy.Publisher(
            self.ros_config.get("event_topic", "/llm_voice_agent/tool_events"), String, queue_size=10
        )
        self.audio_topic = self.audio_config.get("input_topic", "/audio/stream")
        self.audio_sub = rospy.Subscriber(self.audio_topic, UInt8MultiArray, self._audio_topic_cb, queue_size=20)

        self.tool_specs_service = self.ros_config.get("tool_specs_service", "/llm_voice_agent/tool_specs")
        self.execute_tool_service = self.ros_config.get("execute_tool_service", "/llm_voice_agent/execute_tool")

        self._lock = threading.RLock()
        self._running = False
        self._connected = False
        self._connect_event = threading.Event()
        self._last_error = ""
        self._ws = None
        self._ws_thread = None
        self._capture_thread = None
        self._capture_proc = None
        self._play_proc = None
        self._devnull = None
        self._response_text_parts = []
        self._function_args = {}
        self._completed_calls = set()
        self._resample_state = None
        self._audio_bytes_sent = 0
        self._last_audio_progress_time = 0.0
        self._last_rms = 0

    def start_services(self):
        start_service = self.ros_config.get("start_service", "/llm_voice_agent/stepfun_realtime/start")
        stop_service = self.ros_config.get("stop_service", "/llm_voice_agent/stepfun_realtime/stop")
        rospy.Service(start_service, Trigger, self._start_service)
        rospy.Service(stop_service, Trigger, self._stop_service)
        self._publish_state("idle", {"message": "stepfun realtime voice node ready"})
        rospy.loginfo("StepFun realtime voice node ready: start=%s stop=%s", start_service, stop_service)

    def stop(self):
        with self._lock:
            self._running = False
            ws = self._ws
            self._ws = None
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
        self._stop_audio()
        self._publish_state("idle", {"message": "stopped"})

    def _start_service(self, req):
        ok, message = self.start()
        return TriggerResponse(ok, to_ros_string(message))

    def _stop_service(self, req):
        self.stop()
        return TriggerResponse(True, to_ros_string("stepfun realtime voice stopped"))

    def start(self):
        with self._lock:
            if self._running:
                return True, "stepfun realtime voice already running"
            ok, message = self._validate_runtime()
            if not ok:
                self._publish_state("error", {"message": message})
                return False, message
            self._running = True
            self._connected = False
            self._last_error = ""
            self._connect_event.clear()
            self._response_text_parts = []
            self._function_args = {}
            self._completed_calls = set()
            self._resample_state = None
            self._audio_bytes_sent = 0
            self._last_audio_progress_time = 0.0
            self._ws_thread = threading.Thread(target=self._run_websocket)
            self._ws_thread.setDaemon(True)
            self._ws_thread.start()

        timeout = float(self.realtime_config.get("connect_timeout_seconds", 5.0))
        if not self._connect_event.wait(timeout):
            self.stop()
            return False, "stepfun realtime websocket connect timeout"
        if not self._connected:
            message = self._last_error or "stepfun realtime websocket connect failed"
            self.stop()
            return False, message
        return True, "stepfun realtime voice started"

    def _validate_runtime(self):
        if websocket is None:
            return False, "python package websocket-client is not installed"
        if not self._api_key():
            return False, "missing realtime api key; set STEPFUN_REALTIME_API_KEY or LLM_API_KEY"
        return True, ""

    def _run_websocket(self):
        try:
            url = self._websocket_url()
            headers = ["Authorization: Bearer {}".format(self._api_key())]
            headers.extend(self._extra_headers())
            self._publish_state("connecting", {"url": self._safe_url(url)})
            self._ws = websocket.WebSocketApp(
                url,
                header=headers,
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close,
            )
            self._ws.run_forever()
        except Exception as exc:
            self._last_error = to_text(exc)
            self._publish_state("error", {"message": self._last_error})
            self._connect_event.set()
        finally:
            with self._lock:
                self._running = False
                self._connected = False
            self._stop_audio()
            self._publish_state("idle", {"message": "websocket exited"})

    def _on_open(self, *args):
        with self._lock:
            self._connected = True
        self._publish_state("connected")
        self._send_session_update()
        if self._input_source() == "alsa":
            self._start_capture_thread()
        else:
            self._publish_state("listening", {"audio_input": self.audio_topic, "input_source": self._input_source()})
        self._connect_event.set()

    def _on_close(self, *args):
        close_status_code = args[1] if len(args) > 1 else None
        close_msg = args[2] if len(args) > 2 else None
        self._publish_state("closed", {"code": close_status_code, "message": to_text(close_msg)})
        self._connect_event.set()

    def _on_error(self, *args):
        error = args[-1] if args else ""
        self._last_error = to_text(error)
        self._publish_state("error", {"message": self._last_error})
        self._connect_event.set()

    def _on_message(self, *args):
        message = args[-1] if args else ""
        try:
            event = json.loads(to_text(message))
        except Exception as exc:
            self._publish_event({"type": "stepfun_realtime_parse_error", "message": to_text(exc)})
            return

        event_type = to_text(event.get("type", ""))
        if event_type == "error":
            self._publish_event({"type": "stepfun_realtime_error", "event": event})
            return
        if event_type.endswith("speech_started"):
            self._publish_state("listening", {"event": event_type})
            self._stop_playback()
            return
        if event_type.endswith("speech_stopped"):
            self._publish_state("thinking", {"event": event_type})
            return
        if "transcription" in event_type and event_type.endswith("completed"):
            transcript = event.get("transcript") or event.get("text") or ""
            if transcript:
                self.transcript_pub.publish(String(data=to_ros_string(transcript)))
            return
        if event_type in ("response.audio.delta", "response.output_audio.delta"):
            self._write_audio_delta(event.get("delta") or event.get("audio") or "")
            return
        if event_type in ("response.audio.done", "response.output_audio.done"):
            self._publish_state("connected", {"event": event_type})
            return
        if event_type in ("response.text.delta", "response.audio_transcript.delta"):
            delta = event.get("delta") or event.get("text") or ""
            if delta:
                self._response_text_parts.append(to_text(delta))
            return
        if event_type in ("response.text.done", "response.audio_transcript.done"):
            text = event.get("text") or event.get("transcript") or "".join(self._response_text_parts)
            self._response_text_parts = []
            if text:
                self.reply_pub.publish(String(data=to_ros_string(text)))
            return
        if event_type == "response.function_call_arguments.delta":
            self._accumulate_function_arguments(event)
            return
        if event_type == "response.function_call_arguments.done":
            self._handle_function_call_event(event)
            return
        if event_type == "response.output_item.done":
            item = event.get("item") or {}
            if to_text(item.get("type", "")) == "function_call":
                self._handle_function_call_event(item)
            return
        if event_type == "response.done":
            response = event.get("response") or {}
            self._publish_event(
                {
                    "type": "stepfun_realtime_response_done",
                    "status": response.get("status"),
                    "status_details": response.get("status_details"),
                }
            )
            for item in response.get("output") or []:
                if to_text(item.get("type", "")) == "function_call":
                    self._handle_function_call_event(item)
            return

    def _send_session_update(self):
        session = {
            "modalities": self.realtime_config.get("modalities", ["audio", "text"]),
            "instructions": self.realtime_config.get("instructions", ""),
            "voice": self._voice(),
            "input_audio_format": self.realtime_config.get("input_audio_format", "pcm16"),
            "output_audio_format": self.realtime_config.get("output_audio_format", "pcm16"),
            "tool_choice": self.realtime_config.get("tool_choice", "auto"),
            "turn_detection": self.realtime_config.get(
                "turn_detection", {"type": "server_vad", "create_response": True}
            ),
        }
        transcription = self.realtime_config.get("input_audio_transcription")
        if transcription:
            session["input_audio_transcription"] = transcription
        tools = self._load_tool_specs()
        if tools:
            session["tools"] = tools
        self._send_json({"type": "session.update", "session": session})
        self._publish_event({"type": "stepfun_realtime_session_update", "tool_count": len(tools)})

    def _load_tool_specs(self):
        if not bool(self.realtime_config.get("enable_tools", True)):
            return []
        try:
            rospy.wait_for_service(self.tool_specs_service, timeout=float(self.ros_config.get("service_timeout_seconds", 3.0)))
            client = rospy.ServiceProxy(self.tool_specs_service, GetToolSpecs)
            response = client()
            if not response.ok:
                self._publish_event({"type": "stepfun_realtime_tool_specs_error", "message": response.message})
                return []
            specs = json.loads(to_text(response.tools_json))
            excluded = set(self.realtime_config.get("exclude_tools", ["start_realtime_voice"]) or [])
            tools = []
            for spec in specs or []:
                name = to_text(spec.get("name", ""))
                if not name or name in excluded:
                    continue
                tools.append(
                    {
                        "type": "function",
                        # StepFun realtime requires the chat-completions tool shape:
                        # name/description/parameters nested under a "function" object.
                        "function": {
                            "name": name,
                            "description": to_text(spec.get("description", "")),
                            "parameters": spec.get("parameters") or {"type": "object", "properties": {}},
                        },
                    }
                )
            return tools
        except Exception as exc:
            self._publish_event({"type": "stepfun_realtime_tool_specs_error", "message": to_text(exc)})
            return []

    def _accumulate_function_arguments(self, event):
        key = self._function_key(event)
        current = self._function_args.get(key, {})
        current["name"] = event.get("name") or current.get("name")
        current["call_id"] = event.get("call_id") or current.get("call_id")
        current["arguments"] = to_text(current.get("arguments", "")) + to_text(event.get("delta", ""))
        self._function_args[key] = current

    def _handle_function_call_event(self, event):
        key = self._function_key(event)
        cached = self._function_args.pop(key, {})
        name = event.get("name") or cached.get("name") or ""
        call_id = event.get("call_id") or cached.get("call_id") or key
        if call_id in self._completed_calls:
            return
        self._completed_calls.add(call_id)
        arguments_text = event.get("arguments") or cached.get("arguments") or "{}"
        try:
            args = json.loads(to_text(arguments_text) or "{}")
        except Exception:
            args = {}
        result = self._execute_tool(name, args)
        self._send_tool_output(call_id, result)
        if name == "stop_realtime_voice":
            timer = threading.Timer(0.5, self.stop)
            timer.setDaemon(True)
            timer.start()

    def _execute_tool(self, name, args):
        try:
            rospy.wait_for_service(self.execute_tool_service, timeout=float(self.ros_config.get("service_timeout_seconds", 5.0)))
            client = rospy.ServiceProxy(self.execute_tool_service, ExecuteTool)
            response = client(to_ros_string(name), to_ros_string(json.dumps(args or {}, ensure_ascii=False)))
            if response.result_json:
                result = json.loads(to_text(response.result_json))
            else:
                result = {"ok": bool(response.ok), "message": to_text(response.message)}
            self._publish_event({"type": "stepfun_realtime_tool_result", "tool": name, "args": args, "result": result})
            return result
        except Exception as exc:
            result = {"ok": False, "message": to_text(exc)}
            self._publish_event({"type": "stepfun_realtime_tool_error", "tool": name, "args": args, "result": result})
            return result

    def _send_tool_output(self, call_id, result):
        output = json.dumps(result or {}, ensure_ascii=False)
        self._send_json({"type": "conversation.item.create", "item": {"type": "function_call_output", "call_id": call_id, "output": output}})
        if bool(self.realtime_config.get("create_response_after_tool", True)):
            self._send_json({"type": "response.create"})

    def _start_capture_thread(self):
        delay = float(self.audio_config.get("start_capture_delay_seconds", 0.8))
        self._capture_thread = threading.Thread(target=self._capture_loop, args=(delay,))
        self._capture_thread.setDaemon(True)
        self._capture_thread.start()

    def _capture_loop(self, delay):
        if delay > 0:
            time.sleep(delay)
        if not self._is_running():
            return
        sample_rate = int(self.audio_config.get("input_sample_rate", self.audio_config.get("sample_rate", 24000)))
        channels = int(self.audio_config.get("channels", 1))
        chunk_ms = int(self.audio_config.get("chunk_ms", 100))
        chunk_size = int(sample_rate * channels * 2 * chunk_ms / 1000)
        cmd = self._arecord_cmd(sample_rate, channels)
        try:
            self._capture_proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=self._devnull_file())
            self._publish_state("listening", {"audio_input": cmd})
            while self._is_running():
                data = self._capture_proc.stdout.read(chunk_size)
                if not data:
                    if self._capture_proc.poll() is not None:
                        break
                    time.sleep(0.02)
                    continue
                self._send_audio_chunk(data)
        except Exception as exc:
            self._publish_state("error", {"message": "audio capture failed: {}".format(to_text(exc))})
        finally:
            self._stop_capture()

    def _send_audio_chunk(self, data):
        if not data:
            return
        encoded = base64.b64encode(data)
        if hasattr(encoded, "decode"):
            encoded = encoded.decode("ascii")
        self._send_json({"type": "input_audio_buffer.append", "audio": encoded})
        self._publish_audio_progress("alsa", len(data))

    def _audio_topic_cb(self, msg):
        if self._input_source() != "topic" or not self._is_running():
            return
        try:
            data = bytes(bytearray(msg.data))
            data = self._resample_input_if_needed(data)
            try:
                self._last_rms = audioop.rms(data, 2) if data else 0
            except Exception:
                self._last_rms = 0
            self._send_json({"type": "input_audio_buffer.append", "audio": self._base64_audio(data)})
            self._publish_audio_progress("topic", len(data))
        except Exception as exc:
            self._publish_event({"type": "stepfun_realtime_audio_topic_error", "message": to_text(exc)})

    def _base64_audio(self, data):
        encoded = base64.b64encode(data)
        if hasattr(encoded, "decode"):
            return encoded.decode("ascii")
        return encoded

    def _resample_input_if_needed(self, data):
        source_rate = int(self.audio_config.get("topic_sample_rate", 16000))
        target_rate = int(self.audio_config.get("input_sample_rate", self.audio_config.get("sample_rate", 24000)))
        channels = int(self.audio_config.get("channels", 1))
        if source_rate == target_rate:
            return data
        converted, self._resample_state = audioop.ratecv(data, 2, channels, source_rate, target_rate, self._resample_state)
        return converted

    def _publish_audio_progress(self, source, chunk_bytes):
        self._audio_bytes_sent += int(chunk_bytes or 0)
        now = time.time()
        interval = float(self.audio_config.get("progress_event_interval_seconds", 5.0))
        if now - self._last_audio_progress_time < interval:
            return
        self._last_audio_progress_time = now
        self._publish_event(
            {
                "type": "stepfun_realtime_audio_stream",
                "source": source,
                "chunk_bytes": int(chunk_bytes or 0),
                "bytes_total": self._audio_bytes_sent,
                "rms": int(self._last_rms or 0),
            }
        )

    def _write_audio_delta(self, encoded):
        if not encoded:
            return
        try:
            data = base64.b64decode(to_text(encoded))
            gain = float(self.audio_config.get("output_gain", 1.0) or 1.0)
            if gain != 1.0:
                try:
                    data = audioop.mul(data, 2, gain)  # clips to int16 range
                except Exception:
                    pass
            proc = self._ensure_playback()
            if proc and proc.stdin:
                proc.stdin.write(data)
                proc.stdin.flush()
        except Exception as exc:
            self._publish_event({"type": "stepfun_realtime_play_error", "message": to_text(exc)})

    def _ensure_playback(self):
        if self._play_proc is not None and self._play_proc.poll() is None:
            return self._play_proc
        sample_rate = int(self.audio_config.get("output_sample_rate", self.audio_config.get("sample_rate", 24000)))
        channels = int(self.audio_config.get("channels", 1))
        cmd = self._aplay_cmd(sample_rate, channels)
        self._play_proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=self._devnull_file())
        self._publish_state("speaking", {"audio_output": cmd})
        return self._play_proc

    def _send_json(self, payload):
        with self._lock:
            ws = self._ws
            running = self._running
        if ws is None or not running:
            return
        text = json.dumps(payload, ensure_ascii=False)
        if PY2:
            text = text.encode("utf-8")
        try:
            ws.send(text)
        except Exception as exc:
            self._publish_event({"type": "stepfun_realtime_send_error", "message": to_text(exc), "payload_type": payload.get("type")})

    def _input_source(self):
        return to_text(self.audio_config.get("input_source", "alsa")).strip().lower() or "alsa"

    def _arecord_cmd(self, sample_rate, channels):
        command = self.audio_config.get("arecord_command", "arecord")
        device = self.audio_config.get("input_device", "default")
        return [command, "-q", "-t", "raw", "-f", "S16_LE", "-r", str(sample_rate), "-c", str(channels), "-D", device]

    def _aplay_cmd(self, sample_rate, channels):
        command = self.audio_config.get("aplay_command", "aplay")
        device = self.audio_config.get("output_device", "default")
        return [command, "-q", "-t", "raw", "-f", "S16_LE", "-r", str(sample_rate), "-c", str(channels), "-D", device]

    def _websocket_url(self):
        model = self._model()
        base = self._env_first(
            [self.realtime_config.get("endpoint_env", "STEPFUN_REALTIME_URL")],
            self.realtime_config.get("endpoint", "wss://api.stepfun.com/v1/realtime"),
        )
        if "{model}" in base:
            return base.format(model=model)
        if "model=" in base:
            return base
        separator = "&" if "?" in base else "?"
        return "{}{}model={}".format(base, separator, model)

    def _api_key(self):
        return self._env_first(
            [
                self.realtime_config.get("api_key_env", "STEPFUN_REALTIME_API_KEY"),
                "LLM_API_KEY",
                "STEPFUN_TTS_API_KEY",
            ]
        )

    def _model(self):
        return self._env_first(
            [self.realtime_config.get("model_env", "STEPFUN_REALTIME_MODEL")],
            self.realtime_config.get("model", "step-audio-2-mini"),
        )

    def _voice(self):
        return self._env_first(
            [self.realtime_config.get("voice_env", "STEPFUN_REALTIME_VOICE")],
            self.realtime_config.get("voice", "linxi"),
        )

    def _extra_headers(self):
        headers = []
        extra = self.realtime_config.get("extra_headers") or []
        if isinstance(extra, dict):
            extra = ["{}: {}".format(key, value) for key, value in extra.items()]
        for item in extra:
            text = to_text(item).strip()
            if text:
                headers.append(text)
        return headers

    def _env_first(self, names, default=""):
        for name in names or []:
            if not name:
                continue
            value = os.environ.get(name)
            if value:
                return value
        return default

    def _function_key(self, event):
        return to_text(event.get("call_id") or event.get("item_id") or event.get("id") or "default")

    def _is_running(self):
        with self._lock:
            return self._running

    def _stop_audio(self):
        self._stop_capture()
        self._stop_playback()
        if self._devnull is not None:
            try:
                self._devnull.close()
            except Exception:
                pass
            self._devnull = None

    def _stop_capture(self):
        proc = self._capture_proc
        self._capture_proc = None
        self._stop_process(proc)

    def _stop_playback(self):
        proc = self._play_proc
        self._play_proc = None
        if proc is not None and proc.stdin:
            try:
                proc.stdin.close()
            except Exception:
                pass
        self._stop_process(proc)

    def _stop_process(self, proc):
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.terminate()
                for _ in range(10):
                    if proc.poll() is not None:
                        return
                    time.sleep(0.05)
                if proc.poll() is None:
                    proc.kill()
        except Exception:
            pass

    def _devnull_file(self):
        if self._devnull is None:
            self._devnull = open(os.devnull, "wb")
        return self._devnull

    def _publish_state(self, state, extra=None):
        payload = {"state": state}
        if extra:
            payload.update(extra)
        self.state_pub.publish(String(data=to_ros_string(json.dumps(payload, ensure_ascii=False))))

    def _publish_event(self, payload):
        self.event_pub.publish(String(data=to_ros_string(json.dumps(payload, ensure_ascii=False))))

    def _safe_url(self, url):
        if "?" not in url:
            return url
        base, query = url.split("?", 1)
        return "{}?{}".format(base, query)


def main():
    rospy.init_node("stepfun_realtime_voice", anonymous=False)
    config_path = rospy.get_param("~realtime_config", default_config_path("stepfun_realtime.yaml"))
    config = load_yaml(config_path)
    node = StepFunRealtimeVoiceNode(config)
    node.start_services()
    rospy.on_shutdown(node.stop)
    rospy.spin()


if __name__ == "__main__":
    try:
        main()
    except rospy.ROSInterruptException:
        pass
    except KeyboardInterrupt:
        pass
