class SynthesisResult:
    def __init__(self, ok, path="", message=""):
        self.ok = ok
        self.path = path
        self.message = message


class BaseTTS:
    def synthesize(self, text):
        raise NotImplementedError
