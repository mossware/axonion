import math
import random


class Neuron:
    def __init__(self, temp_c: float = 37.0):
        self.q10 = 1.0
        self.reset()

    def reset(self):
        self.v = -65.0
        self.prev_v = self.v

        # hh gating
        self.m = 0.05
        self.h = 0.6
        self.n = 0.32

        self.w = 0.0

        # metabolism / structure
        self.ATP = 1.0
        self.mito = 100.0
        self.Ca = 0.0
        self.integrity = 100.0
        self.damage = 0.0
        self.health = 100.0
        self.dead = False

        self.flag_atp_low = False
        self.flag_ca_high = False
        self.flag_mito_stress = False
        self.flag_integrity_low = False
        self.flag_damage_high = False
        self.flag_cascade = False

    # hh rates

    def _alpha_m(self, v: float) -> float:
        return 0.1 * (v + 40.0) / (1.0 - math.exp(-(v + 40.0) / 10.0)) if v != -40.0 else 1.0

    def _beta_m(self, v: float) -> float:
        return 4.0 * math.exp(-(v + 65.0) / 18.0)

    def _alpha_h(self, v: float) -> float:
        return 0.07 * math.exp(-(v + 65.0) / 20.0)

    def _beta_h(self, v: float) -> float:
        return 1.0 / (1.0 + math.exp(-(v + 35.0) / 10.0))

    def _alpha_n(self, v: float) -> float:
        return 0.01 * (v + 55.0) / (1.0 - math.exp(-(v + 55.0) / 10.0)) if v != -55.0 else 0.1

    def _beta_n(self, v: float) -> float:
        return 0.125 * math.exp(-(v + 65.0) / 80.0)

    # kill

    def kill(self):
        if self.dead:
            return
        self.dead = True
        self.v = 0.0
        self.integrity = 0.0
        self.damage = 100.0
        self.health = 0.0
        self.ATP = 0.0
        self.mito = 0.0
        self.Ca = 10.0

    def step(self, dt_ms: float, i_ext: float, kill_mode: bool = False) -> float:
        dt_sec = dt_ms / 1000.0

        # forced collapse
        if kill_mode and not self.dead:
            self.ATP -= 5.0 * dt_sec
            self.Ca += 2.0 * dt_sec
            self.damage += 5.0 * dt_sec
            if self.ATP <= 0.0 or self.damage >= 100.0 or self.Ca > 20.0:
                self.kill()

        if self.dead:
            self.v += (0.0 - self.v) * dt_sec * 0.2 + random.gauss(0.0, 0.5)
            return self.v

        v = self.v

        # membrane
        am = self._alpha_m(v)
        bm = self._beta_m(v)
        ah = self._alpha_h(v)
        bh = self._beta_h(v)
        an = self._alpha_n(v)
        bn = self._beta_n(v)

        self.m += (am * (1.0 - self.m) - bm * self.m) * dt_ms * 0.5
        self.h += (ah * (1.0 - self.h) - bh * self.h) * dt_ms * 0.5
        self.n += (an * (1.0 - self.n) - bn * self.n) * dt_ms * 0.5

        self.m = max(0.0, min(1.0, self.m))
        self.h = max(0.0, min(1.0, self.h))
        self.n = max(0.0, min(1.0, self.n))

        gNa = 120.0
        gK = 36.0
        gL = 0.5

        ENa = 50.0
        EK = -77.0
        EL = -54.4

        INa = gNa * (self.m ** 3) * self.h * (v - ENa)
        IK = gK * (self.n ** 4) * (v - EK)
        IL = gL * (v - EL)

        dv = (i_ext - INa - IK - IL)
        self.v += dv * dt_ms

        # pump
        pump_strength = 0.004 * self.ATP
        self.v += (-65.0 - self.v) * pump_strength * dt_ms

        spike = (self.prev_v < 0.0 <= self.v)

        # calcium
        if spike:
            self.Ca += 0.02

        ca_clear_rate = 0.05 + 2.0 * self.ATP
        self.Ca -= self.Ca * ca_clear_rate * dt_sec
        if self.Ca < 0.0:
            self.Ca = 0.0

        # atp
        prod_rate = 0.008 * (self.mito / 100.0)
        pump_cost_rate = 0.0007 * abs(i_ext)
        ca_cost_rate = 0.006 * self.Ca

        self.ATP += (prod_rate - pump_cost_rate - ca_cost_rate) * dt_sec
        self.ATP = max(0.0, min(1.0, self.ATP))

        if self.ATP <= 0.001:
            self.kill()
            self.prev_v = v
            return self.v

        # mitochondria
        mito_recovery_rate = 0.02 * (100.0 - self.mito)
        load_term = max(0.0, abs(i_ext) - 15.0) * 0.0005
        ca_term = max(0.0, self.Ca - 0.3) * 0.1

        self.mito += (mito_recovery_rate - load_term - ca_term) * dt_sec
        self.mito = max(0.0, min(100.0, self.mito))

        # damage / health
        voltage_term = abs(self.v + 65.0) / 250.0
        ca_term = 1.5 * self.Ca
        atp_term = 1.5 * (1.0 - self.ATP)
        mito_term = (100.0 - self.mito) / 100.0

        stress = voltage_term + ca_term + atp_term + mito_term

        if stress < 0.6:
            self.integrity += 0.1 * dt_sec
        else:
            self.integrity -= (stress - 0.6) * dt_sec

        self.integrity = max(0.0, min(100.0, self.integrity))

        if stress > 1.0:
            self.damage += (stress - 1.0) * 0.5 * dt_sec

        self.damage = max(0.0, min(100.0, self.damage))

        self.health = self.integrity - 0.7 * self.damage
        self.health = max(0.0, min(100.0, self.health))

        if self.health <= 0.0:
            self.kill()
            self.prev_v = v
            return self.v

        self.prev_v = v
        return self.v
