#!/usr/bin/env python
# coding: utf-8

from __future__ import print_function

import argparse
import audioop
import base64
import json
import os
import signal
import sys
import threading
import time
import wave

try:
    import queue
except ImportError:
    import Queue as queue

try:
    import websocket
except Exception:
    websocket = None

try:
    import sounddevice as sd
except Exception:
    sd = None


class StepFunRealtimeLocalTest(object):
    def __init__(self, args):
        self.args = args
        self.running = False
        self.connected = threading.Event()
        self.done = threading.Event()
        self.ws = None
        self.output_stream = None
        self.play_queue = queue.Queue()
        self.audio_wave = None
        self.bytes_in = 0
        self.bytes_out = 0
        self.last_audio_log = 0.0
        self.last_rms = 0
        self.close_info = ""
        self.function_args = {}
        self.completed_calls = set()

    def run(self):
        if self.args.list_devices:
            self._list_devices()
            return
        if websocket is None:
            raise RuntimeError("missing dependency: pip install websocket-client")
        if self.args.mode == "mic" and sd is None:
            raise RuntimeError("missing dependency: pip install sounddevice")

        self.running = True
        self._open_audio_output()
        self._open_audio_file()
        self._start_playback_thread()

        self.ws = websocket.WebSocketApp(
            self._url(),
            header=["Authorization: Bearer {}".format(self.args.api_key)],
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        print("connecting:", self._url())
        ws_thread = threading.Thread(target=self.ws.run_forever)
        ws_thread.daemon = True
        ws_thread.start()

        if not self.connected.wait(self.args.connect_timeout):
            self.stop()
            raise RuntimeError("websocket connect timeout")

        if self.args.mode == "mic":
            self._run_mic_loop()
        else:
            self._send_text_turn(self.args.text)
            self.done.wait(self.args.text_timeout)

        self._drain_playback()
        self.stop()

    def stop(self):
        self.running = False
        if self.ws is not None:
            try:
                self.ws.close()
            except Exception:
                pass
        if self.output_stream is not None:
            try:
                self.output_stream.stop()
                self.output_stream.close()
            except Exception:
                pass
            self.output_stream = None
        if self.audio_wave is not None:
            try:
                self.audio_wave.close()
            except Exception:
                pass
            self.audio_wave = None

    def _on_open(self, *args):
        print("websocket opened")
        self._send_session_update()
        self.connected.set()

    def _on_close(self, *args):
        self.running = False
        code = args[1] if len(args) > 1 else None
        reason = args[2] if len(args) > 2 else None
        self.close_info = "code={} reason={}".format(code, reason)
        print("websocket closed", self.close_info)
        self.done.set()

    def _on_error(self, *args):
        self.running = False
        print("websocket error:", args[-1] if args else "")
        self.done.set()

    def _on_message(self, *args):
        raw = args[-1] if args else ""
        if self.args.raw:
            print("<<", raw)
        try:
            event = json.loads(raw)
        except Exception:
            print("non-json event:", raw)
            return

        event_type = event.get("type", "")
        if event_type == "error":
            print("server error:", json.dumps(event, ensure_ascii=False))
            self.done.set()
            return
        if event_type in ("session.created", "session.updated"):
            print(event_type)
            return
        if event_type in ("input_audio_buffer.speech_started", "input_audio_buffer.speech_stopped"):
            print(event_type)
            return
        if event_type in ("input_audio_buffer.committed", "conversation.item.created", "response.created"):
            print(event_type)
            return
        if event_type in ("response.audio.delta", "response.output_audio.delta"):
            self._handle_audio_delta(event.get("delta") or event.get("audio") or "")
            return
        if event_type in ("response.audio.done", "response.output_audio.done"):
            print(event_type, "bytes_out={}".format(self.bytes_out))
            return
        if event_type in ("response.audio_transcript.delta", "response.text.delta"):
            delta = event.get("delta") or event.get("text") or ""
            if delta:
                if sys.version_info[0] < 3:
                    sys.stdout.write(delta.encode("utf-8"))
                else:
                    sys.stdout.write(delta)
                sys.stdout.flush()
            return
        if event_type in ("response.audio_transcript.done", "response.text.done"):
            text = event.get("transcript") or event.get("text") or ""
            if text:
                print("\nassistant transcript:", text)
            return
        if event_type == "conversation.item.input_audio_transcription.completed":
            print("user transcript:", event.get("transcript", ""))
            return
        if event_type == "response.function_call_arguments.delta":
            self._accumulate_function_arguments(event)
            return
        if event_type == "response.function_call_arguments.done":
            self._handle_function_call(event)
            return
        if event_type == "response.output_item.done":
            item = event.get("item") or {}
            if item.get("type") == "function_call":
                self._handle_function_call(item)
            return
        if event_type == "response.done":
            response = event.get("response") or {}
            status = response.get("status")
            status_details = response.get("status_details")
            # A response whose output is a tool call is NOT the final turn -- we
            # execute the tool, send its result, and a follow-up response with the
            # spoken answer is coming, so don't finish on this one.
            had_function_call = False
            for item in response.get("output") or []:
                if item.get("type") == "function_call":
                    had_function_call = True
                    self._handle_function_call(item)
            print("\nresponse.done bytes_in={} bytes_out={} status={}".format(
                self.bytes_in, self.bytes_out, status))
            if status_details:
                print("response.status_details:", json.dumps(status_details, ensure_ascii=False))
            if had_function_call:
                print("(tool call issued; waiting for follow-up response)")
                return
            if self.bytes_out == 0:
                # No audio came back -- dump the full response so the cause is visible.
                print("NO AUDIO. full response.done:", json.dumps(event, ensure_ascii=False))
            if self.args.mode == "text" or self.args.mic_submit == "commit":
                self.done.set()
            return
        # Print every other event type so nothing is silently swallowed.
        print("event:", event_type)

    def _send_session_update(self):
        instructions = self.args.instructions
        if self.args.model == "step-audio-2-mini" and self.args.voice == "wenrounansheng":
            instructions = instructions.rstrip() + "\n请使用默认男声与用户交流。"
        session = {
            "modalities": ["text", "audio"],
            "instructions": instructions,
            "voice": self.args.voice,
            "input_audio_format": "pcm16",
            "output_audio_format": "pcm16",
        }
        if self.args.turn_detection == "server_vad":
            session["turn_detection"] = {
                "type": "server_vad",
                "prefix_padding_ms": self.args.prefix_padding_ms,
                "silence_duration_ms": self.args.silence_duration_ms,
                "energy_awakeness_threshold": self.args.energy_awakeness_threshold,
                # Without this the server VAD will detect speech and commit the
                # buffer but never auto-create a response -> no audio comes back.
                "create_response": True,
            }
        if self.args.tools:
            session["tools"] = self._tool_specs()
            session["tool_choice"] = "auto"
        self._send_json({"type": "session.update", "session": session})

    def _send_text_turn(self, text):
        print("sending text:", text)
        self._send_json(
            {
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": text}],
                },
            }
        )
        self._send_json({"type": "response.create"})

    def _tool_specs(self):
        # StepFun realtime expects the chat-completions tool shape: the
        # name/description/parameters are nested under a "function" object.
        return [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "查询指定城市的当前天气情况。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "city": {"type": "string", "description": "城市名称，例如 北京、上海"}
                        },
                        "required": ["city"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "calculator",
                    "description": "计算一个数学算式并返回结果。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "expression": {"type": "string", "description": "要计算的算式，例如 (3+5)*2"}
                        },
                        "required": ["expression"],
                    },
                },
            },
        ]

    def _execute_tool(self, name, args):
        # Dummy implementations -- just enough to prove the tool-call round trip.
        if name == "get_weather":
            city = args.get("city") or "未知"
            return {"city": city, "weather": "晴", "temperature_c": 23, "humidity": "45%"}
        if name == "calculator":
            expression = args.get("expression") or ""
            try:
                value = eval(expression, {"__builtins__": {}}, {})  # noqa: S307 (sandboxed dummy)
            except Exception as exc:
                return {"expression": expression, "error": "计算失败: {}".format(exc)}
            return {"expression": expression, "result": value}
        return {"error": "unknown tool: {}".format(name)}

    def _accumulate_function_arguments(self, event):
        key = event.get("call_id") or event.get("item_id") or event.get("id") or "default"
        current = self.function_args.get(key, {})
        current["name"] = event.get("name") or current.get("name")
        current["call_id"] = event.get("call_id") or current.get("call_id")
        current["arguments"] = (current.get("arguments") or "") + (event.get("delta") or "")
        self.function_args[key] = current

    def _handle_function_call(self, event):
        key = event.get("call_id") or event.get("item_id") or event.get("id") or "default"
        cached = self.function_args.pop(key, {})
        name = event.get("name") or cached.get("name") or ""
        call_id = event.get("call_id") or cached.get("call_id") or key
        if not name or call_id in self.completed_calls:
            return
        self.completed_calls.add(call_id)
        arguments_text = event.get("arguments") or cached.get("arguments") or "{}"
        try:
            args = json.loads(arguments_text or "{}")
        except Exception:
            args = {}
        print("\n>> tool call: {}({})".format(name, json.dumps(args, ensure_ascii=False)))
        result = self._execute_tool(name, args)
        print(">> tool result: {}".format(json.dumps(result, ensure_ascii=False)))
        self._send_json(
            {
                "type": "conversation.item.create",
                "item": {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps(result, ensure_ascii=False),
                },
            }
        )
        self._send_json({"type": "response.create"})

    def _run_mic_loop(self):
        blocksize = int(self.args.sample_rate * self.args.chunk_ms / 1000)
        print(
            "mic mode: sample_rate={} blocksize={} input_device={} mic_submit={}".format(
                self.args.sample_rate, blocksize, self.args.input_device, self.args.mic_submit
            )
        )
        if self.args.mic_submit == "commit":
            print("speak now; recording for %.1f seconds" % self.args.record_seconds)
        else:
            print("press Ctrl+C to stop")
        start = time.time()
        with sd.RawInputStream(
            samplerate=self.args.sample_rate,
            channels=1,
            dtype="int16",
            blocksize=blocksize,
            device=self.args.input_device,
        ) as stream:
            while self.running:
                data, overflowed = stream.read(blocksize)
                if overflowed:
                    print("mic input overflow")
                self._send_audio(bytes(data))
                if self.args.mic_submit == "commit" and time.time() - start >= self.args.record_seconds:
                    break
        if self.args.mic_submit == "commit":
            if not self.running:
                print("connection closed before commit", self.close_info)
                return
            print("committing input audio buffer bytes_in={} last_rms={}".format(self.bytes_in, self.last_rms))
            if self._send_json({"type": "input_audio_buffer.commit"}):
                self._send_json({"type": "response.create"})
            self.done.wait(self.args.text_timeout)

    def _send_audio(self, data):
        if not data:
            return
        self.bytes_in += len(data)
        try:
            self.last_rms = audioop.rms(data, 2)
        except Exception:
            self.last_rms = 0
        if not self._send_json({"type": "input_audio_buffer.append", "audio": self._b64(data)}):
            self.running = False
            return
        now = time.time()
        if now - self.last_audio_log > 5:
            self.last_audio_log = now
            print("audio sent bytes_in={} rms={}".format(self.bytes_in, self.last_rms))

    def _handle_audio_delta(self, encoded):
        if not encoded:
            return
        data = base64.b64decode(encoded)
        self.bytes_out += len(data)
        if self.audio_wave is not None:
            self.audio_wave.writeframes(data)
        if self.output_stream is not None:
            self.play_queue.put(data)

    def _drain_playback(self, timeout=10.0):
        # Let queued audio finish playing before stop() closes the stream.
        if self.output_stream is None:
            return
        start = time.time()
        while time.time() - start < timeout:
            if self.play_queue.empty():
                break
            time.sleep(0.05)
        time.sleep(0.3)

    def _start_playback_thread(self):
        thread = threading.Thread(target=self._playback_loop)
        thread.daemon = True
        thread.start()

    def _playback_loop(self):
        while self.running:
            try:
                data = self.play_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if self.output_stream is not None:
                try:
                    self.output_stream.write(data)
                except Exception as exc:
                    print("playback error:", exc)
            self.play_queue.task_done()

    def _open_audio_output(self):
        if self.args.no_play:
            return
        if sd is None:
            print("sounddevice not installed; response audio will only be saved")
            return
        self.output_stream = sd.RawOutputStream(
            samplerate=self.args.sample_rate,
            channels=1,
            dtype="int16",
            blocksize=int(self.args.sample_rate * self.args.chunk_ms / 1000),
            device=self.args.output_device,
        )
        self.output_stream.start()

    def _open_audio_file(self):
        if not self.args.save_wav:
            return
        self.audio_wave = wave.open(self.args.save_wav, "wb")
        self.audio_wave.setnchannels(1)
        self.audio_wave.setsampwidth(2)
        self.audio_wave.setframerate(self.args.sample_rate)
        print("saving response audio:", self.args.save_wav)

    def _send_json(self, payload):
        if not self.running and payload.get("type") != "session.update":
            return False
        text = json.dumps(payload, ensure_ascii=False)
        if sys.version_info[0] < 3:
            text = text.encode("utf-8")
        try:
            self.ws.send(text)
            return True
        except Exception as exc:
            self.running = False
            print("send failed for {}: {}".format(payload.get("type"), exc))
            self.done.set()
            return False

    def _b64(self, data):
        encoded = base64.b64encode(data)
        if hasattr(encoded, "decode"):
            return encoded.decode("ascii")
        return encoded

    def _url(self):
        base = self.args.url
        if "model=" in base:
            return base
        sep = "&" if "?" in base else "?"
        return "{}{}model={}".format(base, sep, self.args.model)

    def _list_devices(self):
        if sd is None:
            raise RuntimeError("missing dependency: pip install sounddevice")
        print(sd.query_devices())


def _device_arg(value):
    # Accept a numeric index ("3" -> 3) or a device-name substring.
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def parse_args():
    parser = argparse.ArgumentParser(description="Local StepFun realtime voice smoke test.")
    parser.add_argument("--mode", choices=["text", "mic"], default="text")
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument("--url", default=os.environ.get("STEPFUN_REALTIME_URL", "wss://api.stepfun.com/v1/realtime"))
    parser.add_argument("--model", default=os.environ.get("STEPFUN_REALTIME_MODEL", "step-audio-2-mini"))
    parser.add_argument("--voice", default=os.environ.get("STEPFUN_REALTIME_VOICE", "wenrounansheng"))
    parser.add_argument("--api-key", default=os.environ.get("STEPFUN_REALTIME_API_KEY") or os.environ.get("LLM_API_KEY"))
    parser.add_argument("--text", default="你好，请用一句话介绍你自己。")
    parser.add_argument("--instructions", default="你是一个实时语音助手，请用简短自然的中文回答。")
    parser.add_argument("--sample-rate", type=int, default=24000)
    parser.add_argument("--chunk-ms", type=int, default=100)
    parser.add_argument("--input-device", type=_device_arg, default=None)
    parser.add_argument("--output-device", type=_device_arg, default=None)
    parser.add_argument("--mic-submit", choices=["vad", "commit"], default="vad")
    parser.add_argument("--turn-detection", choices=["server_vad", "none"], default="server_vad")
    parser.add_argument("--record-seconds", type=float, default=5.0)
    parser.add_argument("--no-play", action="store_true")
    parser.add_argument("--save-wav", default="stepfun_realtime_response.wav")
    parser.add_argument("--connect-timeout", type=float, default=8.0)
    parser.add_argument("--text-timeout", type=float, default=30.0)
    parser.add_argument("--prefix-padding-ms", type=int, default=500)
    parser.add_argument("--silence-duration-ms", type=int, default=600)
    parser.add_argument("--energy-awakeness-threshold", type=int, default=1200)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--raw", action="store_true", help="print every raw event frame from the server")
    parser.add_argument("--tools", dest="tools", action="store_true", default=True,
                        help="advertise the dummy get_weather/calculator tools (default on)")
    parser.add_argument("--no-tools", dest="tools", action="store_false",
                        help="disable the dummy tools")
    return parser.parse_args()


def main():
    args = parse_args()
    if not args.list_devices and not args.api_key:
        raise SystemExit("missing API key: set STEPFUN_REALTIME_API_KEY or LLM_API_KEY")
    tester = StepFunRealtimeLocalTest(args)

    def _stop(signum, frame):
        tester.stop()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    tester.run()


if __name__ == "__main__":
    main()
