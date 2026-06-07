class AgentResponse:
    def __init__(self, reply_text="", tool_calls=None, memory_updates=None):
        self.reply_text = reply_text
        self.tool_calls = tool_calls or []
        self.memory_updates = memory_updates or []


class BaseChatClient:
    def generate(self, messages, tools=None):
        raise NotImplementedError
