STATE_IDLE = "idle"
STATE_CHAT = "chat"
STATE_REALTIME = "realtime"
STATE_SPEAKING = "speaking"
STATE_BUSY = "busy"


class AgentStateMachine:
    def __init__(self, initial_state=STATE_IDLE):
        self._state = initial_state

    @property
    def state(self):
        return self._state

    def set_idle(self):
        self._state = STATE_IDLE
        return self._state

    def set_chat(self):
        self._state = STATE_CHAT
        return self._state

    def set_realtime(self):
        self._state = STATE_REALTIME
        return self._state

    def set_speaking(self):
        self._state = STATE_SPEAKING
        return self._state

    def set_busy(self):
        self._state = STATE_BUSY
        return self._state
