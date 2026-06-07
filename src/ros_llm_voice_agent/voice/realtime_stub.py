from .realtime_base import RealtimeInputAdapter


class RealtimeTextStub(RealtimeInputAdapter):
    """Placeholder for a future realtime voice backend."""

    def start(self):
        return True

    def stop(self):
        return True
