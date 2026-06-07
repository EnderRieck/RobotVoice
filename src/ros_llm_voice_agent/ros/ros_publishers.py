# coding: utf-8

import json

from std_msgs.msg import Empty, String

from ros_llm_voice_agent.compat import to_ros_string


class AgentPublishers:
    def __init__(self, rospy, topics):
        self._rospy = rospy
        self.state_pub = rospy.Publisher(topics["state"], String, queue_size=10)
        self.transcript_pub = rospy.Publisher(topics["transcript"], String, queue_size=10)
        self.reply_pub = rospy.Publisher(topics["reply_text"], String, queue_size=10)
        self.tool_pub = rospy.Publisher(topics["tool_events"], String, queue_size=10)
        self.play_end_pub = rospy.Publisher(topics["play_end"], Empty, queue_size=10)

    def publish_state(self, state, extra=None):
        payload = {"state": state}
        if extra:
            payload.update(extra)
        self.state_pub.publish(String(data=to_ros_string(json.dumps(payload, ensure_ascii=False))))

    def publish_transcript(self, text):
        self.transcript_pub.publish(String(data=to_ros_string(text)))

    def publish_reply(self, text):
        self.reply_pub.publish(String(data=to_ros_string(text)))

    def publish_tool_event(self, payload):
        self.tool_pub.publish(String(data=to_ros_string(json.dumps(payload, ensure_ascii=False))))

    def publish_play_end(self):
        self.play_end_pub.publish(Empty())
