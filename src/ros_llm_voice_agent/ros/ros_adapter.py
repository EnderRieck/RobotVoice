# coding: utf-8

import os
import subprocess
import sys
import threading
import time

from std_msgs.msg import Bool, Empty, Float64, Float64MultiArray, String

from ros_llm_voice_agent.compat import to_text

from .ros_publishers import AgentPublishers


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
