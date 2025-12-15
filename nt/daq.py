import numpy as np

class DAQ:

    def __init__(self):
        self.adc_bits = 12                 # precision
        self.noise_level = 0.5             # mV noise
        self.voltage_range = (-100.0, 100.0)  # mV range

    def quantize(self, val):
        min_v, max_v = self.voltage_range
        steps = 2 ** self.adc_bits
        step_size = (max_v - min_v) / steps

        # clamp
        val = max(min_v, min(val, max_v))

        # quantize
        q_val = round((val - min_v) / step_size) * step_size + min_v
        return q_val

    def acquire_sample(self, true_voltage):
        noisy = true_voltage + np.random.normal(0, self.noise_level)
        digitized = self.quantize(noisy)
        return digitized
