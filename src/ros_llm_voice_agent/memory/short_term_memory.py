# coding: utf-8

from ros_llm_voice_agent.compat import to_text


class ShortTermMemory:
    def __init__(self, max_turns=8):
        self.max_messages = max(1, int(max_turns)) * 2
        self._messages = []

    def add_turn(self, user_text, assistant_text):
        if user_text:
            self._messages.append({"role": "user", "content": to_text(user_text)})
        if assistant_text:
            self._messages.append({"role": "assistant", "content": to_text(assistant_text)})
        if len(self._messages) > self.max_messages:
            self._messages = self._messages[-self.max_messages :]

    def messages(self):
        return list(self._messages)

    def replace_last_assistant(self, assistant_text):
        assistant_text = to_text(assistant_text)
        for index in range(len(self._messages) - 1, -1, -1):
            if self._messages[index].get("role") == "assistant":
                self._messages[index]["content"] = assistant_text
                return True
        return False
