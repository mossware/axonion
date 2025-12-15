class Stimulator:
    MODES = ["OFF", "CONSTANT", "STEP", "PULSE"]

    def __init__(self):
        self.mode = "OFF"

        # parameters
        self.amplitude = 10.0
        self.duration = 500.0
        self.frequency = 10.0
        self.pulse_width = 5.0

        self.protocol_start_time = 0.0

        # manual step state
        self.step_active = False
        self.step_start_time = 0.0
        self.step_duration = 5.0

    def set_mode(self, mode, current_time=0.0):
        if mode in self.MODES:
            self.mode = mode
            self.protocol_start_time = current_time
            self.step_active = False

    def trigger_step(self, current_time: float):
        self.step_active = True
        self.step_start_time = current_time

    def _step_current(self, t: float) -> float:
        if not self.step_active:
            return 0.0
        rel = t - self.step_start_time
        if 0.0 <= rel < self.step_duration:
            return self.amplitude
        else:
            self.step_active = False
            return 0.0

    def current_at(self, t: float) -> float:
        if self.mode == "OFF":
            return 0.0

        if self.mode == "STEP":
            return self._step_current(t)

        rel_t = t - self.protocol_start_time

        if self.mode == "CONSTANT":
            return self.amplitude

        if self.mode == "PULSE":
            if self.frequency <= 0.0 or rel_t < 0.0:
                return 0.0

            period = 1000.0 / self.frequency
            if period <= 0.0:
                return 0.0

            width = min(self.pulse_width, period)
            phase = rel_t % period
            if phase < width:
                return self.amplitude
            else:
                return 0.0

        return 0.0
