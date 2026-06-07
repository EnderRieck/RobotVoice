#!/usr/bin/env python
# coding: utf-8

from __future__ import unicode_literals

import rospy
from std_msgs.msg import String

from ros_llm_voice_agent.compat import to_ros_string


def main():
    rospy.init_node("llm_voice_realtime_text_stub", anonymous=False)
    pub = rospy.Publisher("/llm_voice_agent/realtime/final_text", String, queue_size=10)
    initial_text = rospy.get_param("~initial_text", "")
    rospy.sleep(0.5)
    if initial_text:
        pub.publish(String(data=to_ros_string(initial_text)))
    rospy.loginfo("Realtime text stub is ready. Publish std_msgs/String to /llm_voice_agent/realtime/final_text.")
    rospy.spin()


if __name__ == "__main__":
    main()
