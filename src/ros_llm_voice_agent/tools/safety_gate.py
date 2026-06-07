class SafetyGate:
    def __init__(self, config):
        motion = (config or {}).get("motion", {})
        self.max_forward_m = float(motion.get("max_forward_m", 0.3))
        self.max_backward_m = float(motion.get("max_backward_m", 0.3))
        self.max_turn_deg = float(motion.get("max_turn_deg", 30))

    @staticmethod
    def _clamp(value, low, high):
        value = float(value)
        return max(low, min(high, value))

    def clamp_forward(self, value):
        return self._clamp(value, 0.0, self.max_forward_m)

    def clamp_backward(self, value):
        return self._clamp(value, 0.0, self.max_backward_m)

    def clamp_turn(self, value):
        return self._clamp(value, -self.max_turn_deg, self.max_turn_deg)
