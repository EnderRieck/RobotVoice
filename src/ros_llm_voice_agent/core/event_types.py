EVENT_TEXT = "text"
EVENT_WAKEUP = "wakeup"
EVENT_STOP_PLAY = "stop_play"
EVENT_STOP_ALL = "stop_all"
EVENT_TOOL_CALL = "tool_call"
EVENT_SHUTDOWN = "shutdown"


SOURCE_AIUI = "aiui_nlp"
SOURCE_REALTIME = "realtime"
SOURCE_SERVICE = "service"


class AgentEvent:
    def __init__(self, event_type, source, payload=None):
        self.event_type = event_type
        self.source = source
        self.payload = payload or {}
