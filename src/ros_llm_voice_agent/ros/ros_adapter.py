# coding: utf-8

import importlib
import os
import subprocess
import sys
import threading
import time

from std_msgs.msg import Bool, Empty, Float64, Float64MultiArray, String
from std_srvs.srv import Empty as EmptyService
from std_srvs.srv import Trigger

from ros_llm_voice_agent.compat import to_text

from .ros_publishers import AgentPublishers

try:
    basestring
except NameError:
    basestring = (str,)

try:
    integer_types = (int, long)
except NameError:
    integer_types = (int,)


class RosAdapter:
    """The only layer that talks directly to rospy and robot ROS APIs."""

    def __init__(self, rospy, config):
        self.rospy = rospy
        self.config = config
        self.topics = config.get("topics", {})
        self.publishers = AgentPublishers(rospy, self.topics)
        self._battery_state = None
        self._walking_status = None
        self._action_process = None
        self._dynamic_publishers = {}
        self._dynamic_listeners = {}
        self._dynamic_listener_values = {}
        self._lock = threading.Lock()

        self.gait_pub = rospy.Publisher("/gaitCommand", Float64MultiArray, queue_size=2)
        rospy.Subscriber("/MediumSize/BodyHub/WalkingStatus", Float64, self._walking_status_cb, queue_size=2)
        try:
            from sensor_msgs.msg import BatteryState

            rospy.Subscriber("/MediumSize/SensorHub/BatteryState", BatteryState, self._battery_state_cb, queue_size=2)
        except Exception as exc:
            rospy.logwarn("BatteryState subscriber unavailable: %s", exc)

    def _walking_status_cb(self, msg):
        self._walking_status = msg.data

    def _battery_state_cb(self, msg):
        self._battery_state = msg

    def publish_state(self, state, extra=None):
        self.publishers.publish_state(state, extra)

    def publish_transcript(self, text):
        self.publishers.publish_transcript(text)

    def publish_reply(self, text):
        self.publishers.publish_reply(text)

    def publish_tool_event(self, payload):
        self.publishers.publish_tool_event(payload)

    def publish_play_end(self):
        self.publishers.publish_play_end()

    def request_aiui_listen(self, need_to_play_reply=False, timeout_sec=2.0):
        service_name = self.config.get("realtime", {}).get("wakeup_mute_service")
        if not service_name:
            service_name = self.topics.get("aiui_wakeup_mute", "/aiui/wakeup_mute")
        try:
            from ros_AIUI_node.srv import SrvWakeupMute

            self.rospy.wait_for_service(service_name, timeout=timeout_sec)
            client = self.rospy.ServiceProxy(service_name, SrvWakeupMute)
            client(bool(need_to_play_reply))
            return {"ok": True, "service": service_name, "need_to_play_reply": bool(need_to_play_reply)}
        except Exception as exc:
            return {"ok": False, "service": service_name, "message": to_text(exc)}

    def call_empty_service(self, service_name, timeout_sec=2.0):
        try:
            self.rospy.wait_for_service(service_name, timeout=timeout_sec)
            client = self.rospy.ServiceProxy(service_name, EmptyService)
            client()
            return {"ok": True, "service": service_name}
        except Exception as exc:
            return {"ok": False, "service": service_name, "message": to_text(exc)}

    def call_trigger_service(self, service_name, timeout_sec=2.0):
        try:
            self.rospy.wait_for_service(service_name, timeout=timeout_sec)
            client = self.rospy.ServiceProxy(service_name, Trigger)
            response = client()
            return {"ok": bool(response.success), "service": service_name, "message": to_text(response.message)}
        except Exception as exc:
            return {"ok": False, "service": service_name, "message": to_text(exc)}

    def get_battery_state(self):
        if self._battery_state is None:
            return {"available": False, "message": "battery state not received"}
        return {
            "available": True,
            "voltage": float(getattr(self._battery_state, "voltage", 0.0)),
            "percentage": float(getattr(self._battery_state, "percentage", 0.0)),
            "power_supply_status": int(getattr(self._battery_state, "power_supply_status", 0)),
        }

    def get_bodyhub_status(self):
        try:
            from bodyhub.srv import SrvString

            self.rospy.wait_for_service("MediumSize/BodyHub/GetStatus", timeout=2)
            client = self.rospy.ServiceProxy("MediumSize/BodyHub/GetStatus", SrvString)
            response = client("get")
            return {
                "available": True,
                "status": response.data,
                "pose_queue_size": getattr(response, "poseQueueSize", None),
                "joint_queue_size": getattr(response, "jointQueueSize", None),
            }
        except Exception as exc:
            return {"available": False, "message": to_text(exc)}

    def _state_jump(self, control_id, state):
        from bodyhub.srv import SrvState

        self.rospy.wait_for_service("MediumSize/BodyHub/StateJump", timeout=2)
        client = self.rospy.ServiceProxy("MediumSize/BodyHub/StateJump", SrvState)
        return client(control_id, state)

    def stop_motion(self):
        try:
            self._state_jump(2, "stop")
            return {"ok": True, "message": "motion stopped"}
        except Exception as exc:
            return {"ok": False, "message": to_text(exc)}

    def walk_delta(self, x_m=0.0, y_m=0.0, theta_deg=0.0):
        try:
            self._ensure_leju_paths()
            from motion.motionControl import ResetBodyhub, SetBodyhubTo_walking, WalkTheDistance, WaitForWalkingDone

            if ResetBodyhub() is not True:
                return {"ok": False, "message": "failed to reset bodyhub"}
            if SetBodyhubTo_walking(2) is not True:
                return {"ok": False, "message": "failed to enter walking state"}
            WalkTheDistance(float(x_m), float(y_m), float(theta_deg))
            WaitForWalkingDone()
            return {"ok": True, "message": "walk command finished", "x_m": x_m, "y_m": y_m, "theta_deg": theta_deg}
        except Exception as exc:
            return {"ok": False, "message": to_text(exc)}

    def play_action(self, action_path):
        if not action_path:
            return {"ok": False, "message": "empty action path"}
        if not os.path.isfile(action_path):
            return {"ok": False, "message": "action path not found: {}".format(action_path)}
        with self._lock:
            if self._action_process and self._action_process.poll() is None:
                return {"ok": False, "message": "another action is running"}
            env = os.environ.copy()
            self._ensure_leju_paths(env)
            self._action_process = subprocess.Popen([sys.executable, action_path], env=env)
        return {"ok": True, "message": "action started", "path": action_path}

    def stop_action(self):
        with self._lock:
            proc = self._action_process
            self._action_process = None
        if proc and proc.poll() is None:
            proc.terminate()
            time.sleep(0.2)
            if proc.poll() is None:
                proc.kill()
            return {"ok": True, "message": "action process stopped"}
        return {"ok": True, "message": "no action process running"}

    def detect_face(self, timeout_sec=2.0):
        try:
            from ros_vision_node.srv import FaceDetectService

            self.rospy.wait_for_service("ros_vision_node/face_detect", timeout=timeout_sec)
            client = self.rospy.ServiceProxy("ros_vision_node/face_detect", FaceDetectService)
            response = client("")
            return {"ok": True, "result": response.result}
        except Exception as exc:
            return {"ok": False, "message": to_text(exc)}

    def call_dynamic_service(self, definition, args):
        service_name = definition.get("service")
        service_type = definition.get("service_type")
        timeout_sec = float(definition.get("timeout_seconds", 2.0))
        if not service_name or not service_type:
            return {"ok": False, "message": "dynamic service tool requires service and service_type"}
        try:
            service_cls, request_cls = self._load_service_type(service_type)
            request = request_cls()
            self._apply_field_assignment(request, definition.get("request", {}), args)
            self.rospy.wait_for_service(service_name, timeout=timeout_sec)
            client = self.rospy.ServiceProxy(service_name, service_cls)
            response = client(request)
            response_data = self._select_fields(response, definition.get("response", {}))
            response_dict = self._ros_message_to_dict(response)
            ok = self._response_ok(response, definition)
            message = self._response_message(response, definition, "service call finished")
            return {
                "ok": ok,
                "message": message,
                "service": service_name,
                "service_type": service_type,
                "response": response_data if response_data else response_dict,
            }
        except Exception as exc:
            return {"ok": False, "message": to_text(exc), "service": service_name, "service_type": service_type}

    def publish_dynamic_topic(self, definition, args):
        topic = definition.get("topic")
        message_type = definition.get("message_type") or definition.get("topic_type")
        queue_size = int(definition.get("queue_size", 2))
        if not topic or not message_type:
            return {"ok": False, "message": "dynamic topic tool requires topic and message_type"}
        try:
            msg_cls = self._load_ros_class(message_type, "msg")
            publisher = self._dynamic_publisher(topic, message_type, msg_cls, queue_size)
            msg = msg_cls()
            self._apply_field_assignment(msg, definition.get("message", {}), args)
            publisher.publish(msg)
            return {
                "ok": True,
                "message": "topic published",
                "topic": topic,
                "message_type": message_type,
                "message_data": self._ros_message_to_dict(msg),
            }
        except Exception as exc:
            return {"ok": False, "message": to_text(exc), "topic": topic, "message_type": message_type}

    def register_dynamic_listener(self, definition):
        topic = definition.get("topic")
        message_type = definition.get("message_type") or definition.get("topic_type")
        queue_size = int(definition.get("queue_size", 1))
        key = self._dynamic_listener_key(definition)
        if not topic or not message_type:
            return {"ok": False, "message": "dynamic listener tool requires topic and message_type"}
        with self._lock:
            if key in self._dynamic_listeners:
                return {"ok": True, "message": "listener already registered", "topic": topic}
        try:
            msg_cls = self._load_ros_class(message_type, "msg")

            def _callback(msg, listener_key=key):
                with self._lock:
                    self._dynamic_listener_values[listener_key] = {"msg": msg, "time": time.time()}

            subscriber = self.rospy.Subscriber(topic, msg_cls, _callback, queue_size=queue_size)
            with self._lock:
                self._dynamic_listeners[key] = {
                    "subscriber": subscriber,
                    "topic": topic,
                    "message_type": message_type,
                    "message_class": msg_cls,
                }
                self._dynamic_listener_values.setdefault(key, {"msg": None, "time": None})
            return {"ok": True, "message": "listener registered", "topic": topic, "message_type": message_type}
        except Exception as exc:
            return {"ok": False, "message": to_text(exc), "topic": topic, "message_type": message_type}

    def read_dynamic_listener(self, definition, args):
        key = self._dynamic_listener_key(definition)
        result = self.register_dynamic_listener(definition)
        if not result.get("ok"):
            return result

        timeout_sec = float(args.get("timeout_sec", definition.get("timeout_seconds", 2.0)))
        wait_for_message = bool(definition.get("wait_for_message", True))
        max_age = definition.get("max_age_seconds")

        value = self._dynamic_listener_value(key)
        if value.get("msg") is None and wait_for_message:
            wait_result = self._wait_for_dynamic_message(definition, timeout_sec, key)
            if not wait_result.get("ok"):
                return wait_result
            value = wait_result

        msg = value.get("msg")
        stamp = value.get("time")
        if msg is None:
            return {"ok": False, "message": "listener has not received a message", "topic": definition.get("topic")}

        if max_age is not None and stamp is not None and time.time() - stamp > float(max_age):
            if wait_for_message:
                wait_result = self._wait_for_dynamic_message(definition, timeout_sec, key)
                if not wait_result.get("ok"):
                    return wait_result
                value = wait_result
                msg = value.get("msg")
                stamp = value.get("time")
            if msg is None or (stamp is not None and time.time() - stamp > float(max_age)):
                return {"ok": False, "message": "listener message is stale", "topic": definition.get("topic")}

        result_data = self._select_fields(msg, definition.get("result", {}))
        return {
            "ok": True,
            "message": "listener data returned",
            "topic": definition.get("topic"),
            "message_type": definition.get("message_type") or definition.get("topic_type"),
            "age_seconds": time.time() - stamp if stamp is not None else None,
            "data": result_data if result_data else self._ros_message_to_dict(msg),
        }

    def _dynamic_publisher(self, topic, message_type, msg_cls, queue_size):
        key = "{}|{}".format(topic, message_type)
        with self._lock:
            publisher = self._dynamic_publishers.get(key)
            if publisher is None:
                publisher = self.rospy.Publisher(topic, msg_cls, queue_size=queue_size)
                self._dynamic_publishers[key] = publisher
            return publisher

    def _dynamic_listener_key(self, definition):
        message_type = definition.get("message_type") or definition.get("topic_type") or ""
        return to_text(definition.get("name") or "{}|{}".format(definition.get("topic", ""), message_type))

    def _dynamic_listener_value(self, key):
        with self._lock:
            value = self._dynamic_listener_values.get(key) or {}
            return {"msg": value.get("msg"), "time": value.get("time")}

    def _wait_for_dynamic_message(self, definition, timeout_sec, key):
        topic = definition.get("topic")
        message_type = definition.get("message_type") or definition.get("topic_type")
        try:
            msg_cls = self._load_ros_class(message_type, "msg")
            msg = self.rospy.wait_for_message(topic, msg_cls, timeout=timeout_sec)
            value = {"ok": True, "msg": msg, "time": time.time()}
            with self._lock:
                self._dynamic_listener_values[key] = {"msg": value.get("msg"), "time": value.get("time")}
            return value
        except Exception as exc:
            return {"ok": False, "message": to_text(exc), "topic": topic, "message_type": message_type}

    def _load_ros_class(self, type_name, namespace):
        type_name = to_text(type_name)
        if "/" not in type_name:
            raise ValueError("ROS type must use package/Type format: {}".format(type_name))
        package, class_name = type_name.split("/", 1)
        module = importlib.import_module("{}.{}".format(package, namespace))
        return getattr(module, class_name)

    def _load_service_type(self, type_name):
        type_name = to_text(type_name)
        if "/" not in type_name:
            raise ValueError("ROS service type must use package/Type format: {}".format(type_name))
        package, class_name = type_name.split("/", 1)
        module = importlib.import_module("{}.srv".format(package))
        return getattr(module, class_name), getattr(module, "{}Request".format(class_name))

    def _apply_field_assignment(self, target, assignment, args):
        args = args or {}
        assignment = assignment or {}
        if not assignment:
            self._apply_default_assignment(target, args)
            return

        fields = assignment.get("fields") if isinstance(assignment, dict) else {}
        constants = assignment.get("constants") if isinstance(assignment, dict) else {}
        if fields or constants:
            for field_path, arg_name in (fields or {}).items():
                self._set_field(target, field_path, args.get(arg_name))
            for field_path, value in (constants or {}).items():
                self._set_field(target, field_path, value)
            return

        for field_path, spec in assignment.items():
            if isinstance(spec, dict):
                if "from_arg" in spec:
                    value = args.get(spec.get("from_arg"), spec.get("default"))
                elif "value" in spec:
                    value = spec.get("value")
                else:
                    continue
            elif isinstance(spec, basestring) and spec in args:
                value = args.get(spec)
            else:
                value = spec
            self._set_field(target, field_path, value)

    def _apply_default_assignment(self, target, args):
        slots = list(getattr(target, "__slots__", []) or [])
        for field_path, value in args.items():
            if self._has_field_path(target, field_path):
                self._set_field(target, field_path, value)
        if len(args) == 1 and len(slots) == 1:
            self._set_field(target, slots[0], list(args.values())[0])

    def _has_field_path(self, target, field_path):
        current = target
        for part in to_text(field_path).split("."):
            if not hasattr(current, part):
                return False
            current = getattr(current, part)
        return True

    def _set_field(self, target, field_path, value):
        parts = to_text(field_path).split(".")
        current = target
        for part in parts[:-1]:
            current = getattr(current, part)
        field = parts[-1]
        current_value = getattr(current, field)
        setattr(current, field, self._coerce_value(current_value, value))

    def _get_field(self, target, field_path):
        current = target
        for part in to_text(field_path).split("."):
            if not hasattr(current, part):
                return None
            current = getattr(current, part)
        return current

    def _coerce_value(self, current_value, value):
        if value is None:
            return value
        if isinstance(current_value, bool):
            if isinstance(value, basestring):
                return to_text(value).strip().lower() in ("1", "true", "yes", "y", "on", "是")
            return bool(value)
        if isinstance(current_value, integer_types) and not isinstance(current_value, bool):
            return int(value)
        if isinstance(current_value, float):
            return float(value)
        if isinstance(current_value, basestring):
            text = to_text(value)
            if sys.version_info[0] < 3:
                return text.encode("utf-8")
            return text
        return value

    def _response_ok(self, response, definition):
        success_field = definition.get("success_field", "success")
        if not success_field:
            return True
        value = self._get_field(response, success_field)
        if value is None:
            return True
        return bool(value)

    def _response_message(self, response, definition, default):
        message_field = definition.get("message_field", "message")
        value = self._get_field(response, message_field) if message_field else None
        if value is None:
            return default
        return to_text(value)

    def _select_fields(self, msg, selection):
        if not selection:
            return {}
        fields = selection.get("fields", selection) if isinstance(selection, dict) else {}
        if not isinstance(fields, dict):
            return {}
        data = {}
        for output_name, field_path in fields.items():
            data[output_name] = self._message_value_to_data(self._get_field(msg, field_path))
        return data

    def _ros_message_to_dict(self, value):
        return self._message_value_to_data(value)

    def _message_value_to_data(self, value):
        if hasattr(value, "__slots__"):
            data = {}
            for slot in getattr(value, "__slots__", []):
                data[slot] = self._message_value_to_data(getattr(value, slot))
            return data
        if isinstance(value, (list, tuple)):
            return [self._message_value_to_data(item) for item in value]
        if isinstance(value, bytes):
            try:
                return value.decode("utf-8")
            except Exception:
                return repr(value)
        if isinstance(value, basestring):
            return to_text(value)
        return value

    def _ensure_leju_paths(self, env=None):
        try:
            import rospkg

            src_path = os.path.join(rospkg.RosPack().get_path("leju_lib_pkg"), "src")
            func_path = os.path.join(src_path, "lejufunc")
            for path in (src_path, func_path):
                if path not in sys.path:
                    sys.path.append(path)
            if env is not None:
                current = env.get("PYTHONPATH", "")
                env["PYTHONPATH"] = os.pathsep.join([src_path, func_path, current]) if current else os.pathsep.join(
                    [src_path, func_path]
                )
        except Exception:
            pass
