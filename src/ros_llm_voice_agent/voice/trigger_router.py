# coding: utf-8

from ros_llm_voice_agent.compat import to_text


class TriggerRouter:
    def __init__(self, session_config):
        self.chat_triggers = [to_text(x) for x in session_config.get("chat_triggers", [])]
        self.exit_triggers = [to_text(x) for x in session_config.get("exit_triggers", [])]

    @staticmethod
    def _normalize(text):
        return "".join(to_text(text).strip().split())

    def is_chat_trigger(self, text):
        compact = self._normalize(text)
        return any(self._normalize(trigger) in compact for trigger in self.chat_triggers)

    def is_exit_trigger(self, text):
        compact = self._normalize(text)
        return any(self._normalize(trigger) in compact for trigger in self.exit_triggers)
