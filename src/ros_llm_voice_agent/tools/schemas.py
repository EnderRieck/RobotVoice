class ToolResult:
    def __init__(self, ok, message, data=None):
        self.ok = ok
        self.message = message
        self.data = data or {}

    def to_dict(self):
        payload = {"ok": self.ok, "message": self.message}
        if self.data:
            payload["data"] = self.data
        return payload


class BaseTool:
    name = ""
    description = ""
    risk = "low"
    parameters = {}

    def spec(self):
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "risk": self.risk,
        }

    def execute(self, args, ctx):
        raise NotImplementedError
