from std_msgs.msg import Empty, String

from ros_llm_voice_agent.core.event_types import (
    EVENT_STOP_PLAY,
    EVENT_TEXT,
    EVENT_WAKEUP,
    SOURCE_AIUI,
    SOURCE_REALTIME,
)


class RosSubscribers:
    def __init__(self, rospy, topics, session_manager, enable_realtime_stub=False, enable_realtime_text_topic=False):
        self._rospy = rospy
        self._topics = topics
        self._session_manager = session_manager
        rospy.Subscriber(topics["aiui_nlp"], String, self._aiui_nlp_cb, queue_size=10)
        rospy.Subscriber(topics["wakeup"], String, self._wakeup_cb, queue_size=10)
        rospy.Subscriber(topics["aiui_stop_play"], Empty, self._stop_play_cb, queue_size=10)
        if enable_realtime_stub or enable_realtime_text_topic:
            rospy.Subscriber(topics["realtime_final_text"], String, self._realtime_final_text_cb, queue_size=10)

    def _aiui_nlp_cb(self, msg):
        self._session_manager.enqueue_text(msg.data, source=SOURCE_AIUI, mode="non_realtime")

    def _realtime_final_text_cb(self, msg):
        self._session_manager.enqueue_text(msg.data, source=SOURCE_REALTIME, mode="realtime")

    def _wakeup_cb(self, msg):
        self._session_manager.enqueue_wakeup(msg.data)

    def _stop_play_cb(self, msg):
        self._session_manager.enqueue_simple(EVENT_STOP_PLAY, source="ros")
