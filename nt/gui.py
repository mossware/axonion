from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QSlider, QPushButton, QGroupBox, QPlainTextEdit, QTabWidget,
    QStackedWidget, QMenuBar, QMenu, QMessageBox
)
from PySide6.QtCore import QTimer, Qt
import pyqtgraph as pg
from collections import deque

from .neuron import Neuron
from .stim import Stimulator
from .daq import DAQ
from .tutorial import TutorialOverlay


MODE_DESCRIPTIONS = {
    "OFF": "No injected current. Cell rests near −65 mV.",
    "CONSTANT": "Continuous current injection. Higher amplitude → more depolarization.",
    "STEP": "Manual single-step pulses to test recovery.",
    "PULSE": "Periodic square pulses at set frequency and width.",
}

TIME_SCALES = {
    "Slow Motion (0.1x)": 0.1,
    "Half Speed (0.5x)": 0.5,
    "Real-time (1.0x)": 1.0,
    "Fast Forward (5.0x)": 5.0,
    "Hyper Speed (20.0x)": 20.0,
}

VIEW_WINDOWS = {
    "Overview (2 s)": 2.0,
    "Spikes (0.1 s)": 0.1,
}


class ClickableLabel(QLabel):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.clicked_callback = None

    def mousePressEvent(self, event):
        if self.clicked_callback is not None:
            self.clicked_callback()
        super().mousePressEvent(event)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("axonion")

        self.neuron = Neuron()
        self.stim = Stimulator()
        self.daq = DAQ()

        # timing
        self.time_ms = 0.0
        self.dt = 0.025
        self.timer_interval = 20
        self.time_scale_factor = 1.0
        self.running = False

        self.plot_dt_ms = 1.0
        self.time_since_last_plot = 0.0

        self.window_sec = 2.0
        self.plot_buffer_size = int(self.window_sec * 1000 / self.plot_dt_ms)
        self.t_data = deque(maxlen=self.plot_buffer_size)
        self.v_data = deque(maxlen=self.plot_buffer_size)

        # voltage history
        self.vm_history_seconds = None
        self.vm_history_maxlen = None
        self.t_full = deque()
        self.v_full = deque()

        self.voltage_view_mode = "LIVE"

        # metabolism history
        self.meta_t = []
        self.meta_atp = []
        self.meta_ca = []
        self.meta_mito = []
        self.meta_integrity = []
        self.meta_damage = []

        self.was_firing = False

        self.last_step_time_ms = None
        self.step_recovery_logged = False

        self.meta_detail_var = None

        self._setup_pg_theme()
        self._build_ui()
        self._build_menubar()

        # tutorial
        self.tutorial_steps = [
            (
                self.combo_mode,
                "Stimulation mode selector.\n\n"
                "OFF — no injected current\n"
                "CONSTANT — continuous depolarization\n"
                "STEP — recovery testing\n"
                "PULSE — periodic stimulation"
            ),
            (
                self.slider_amp,
                "Stimulation amplitude.\n\n"
                "Negative values hyperpolarize the neuron.\n"
                "Positive values depolarize it."
            ),
            (
                self.voltage_plot,
                "Membrane potential trace.\n\n"
                "LIVE mode follows the signal like an oscilloscope.\n"
                "HISTORY mode allows free pan & zoom."
            ),
            (
                self.tabs,
                "Main application views.\n\n"
                "Voltage — electrical activity\n"
                "Metabolism — internal state and damage"
            ),
        ]

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_loop)

        self._apply_vm_history_limit()

    def _setup_pg_theme(self):
        pg.setConfigOption("background", "#0c0e10")
        pg.setConfigOption("foreground", "#9fffba")

    # history

    def _apply_vm_history_limit(self):
        if self.vm_history_seconds is None:
            maxlen = None
        else:
            maxlen = max(1, int(self.vm_history_seconds * 1000.0 / self.plot_dt_ms))

        old_t = list(self.t_full)
        old_v = list(self.v_full)

        self.t_full = deque(old_t[-maxlen:] if maxlen else old_t, maxlen=maxlen)
        self.v_full = deque(old_v[-maxlen:] if maxlen else old_v, maxlen=maxlen)
        self.vm_history_maxlen = maxlen

    def set_voltage_view_mode(self, mode: str):
        self.voltage_view_mode = mode

        if mode == "HISTORY":
            self.voltage_plot.setMouseEnabled(x=True, y=True)
            self.log("Voltage view set to HISTORY.")
            if self.t_full:
                self.curve_vm.setData(x=list(self.t_full), y=list(self.v_full))
        else:
            self.voltage_plot.setMouseEnabled(x=not self.running, y=True)
            self.log("Voltage view set to LIVE.")

    def set_voltage_history_length(self, seconds, label: str):
        self.vm_history_seconds = seconds
        self._apply_vm_history_limit()
        self.log(f"Voltage history length set to {label}.")

    # menubar

    def _build_menubar(self):
        menubar = self.menuBar()

        view_menu = menubar.addMenu("View")

        vv_menu = QMenu("Voltage View", self)
        view_menu.addMenu(vv_menu)
        vv_menu.addAction("Live (follow)").triggered.connect(
            lambda checked=False: self.set_voltage_view_mode("LIVE")
        )
        vv_menu.addAction("History (pan/zoom)").triggered.connect(
            lambda checked=False: self.set_voltage_view_mode("HISTORY")
        )

        hist_menu = QMenu("Voltage History Length", self)
        view_menu.addMenu(hist_menu)
        for label, sec in [
            ("Unlimited", None),
            ("Last 30 s", 30.0),
            ("Last 2 min", 120.0),
            ("Last 10 min", 600.0),
        ]:
            hist_menu.addAction(label).triggered.connect(
                lambda checked=False, s=sec, l=label: self.set_voltage_history_length(s, l)
            )

        time_menu = QMenu("Time Scale", self)
        view_menu.addMenu(time_menu)
        for label, factor in TIME_SCALES.items():
            time_menu.addAction(label).triggered.connect(
                lambda checked=False, f=factor, l=label: self.set_time_scale(f, l)
            )

        window_menu = QMenu("Voltage Window", self)
        view_menu.addMenu(window_menu)
        for label, w in VIEW_WINDOWS.items():
            window_menu.addAction(label).triggered.connect(
                lambda checked=False, width=w, l=label: self.set_voltage_window(width, l)
            )

        sim_menu = menubar.addMenu("Simulation")
        sim_menu.addAction("Generate report").triggered.connect(self.generate_report)

        help_menu = menubar.addMenu("Help")
        help_menu.addAction("About").triggered.connect(self.show_about)
        help_menu.addAction("Tutorial").triggered.connect(self.start_tutorial)

    # tutorial

    def start_tutorial(self):
        self.tutorial_overlay = TutorialOverlay(self, self.tutorial_steps)

    # ui

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(10)

        groupbox_style = (
            "QGroupBox { border: 1px solid #1a1f22; margin-top: 6px; } "
            "QGroupBox::title { subcontrol-origin: margin; left: 7px; padding: 0px 5px; }"
        )

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_panel.setFixedWidth(360)

        title = QLabel("AXONION")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            "color: #ccffd8; font-size: 18px; letter-spacing: 0.18em; font-weight: 600;"
        )
        subtitle = QLabel("Single-neuron HH simulation workstation")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("color: #7ca88a; font-size: 11px;")
        left_layout.addWidget(title)
        left_layout.addWidget(subtitle)

        status_group = QGroupBox("Status")
        status_group.setStyleSheet(groupbox_style)
        s = QVBoxLayout()
        self.lbl_vm = QLabel("Vm: -65.00 mV")
        self.lbl_state = QLabel("State: QUIESCENT")
        self.lbl_health = QLabel("Health: 100%")
        for w in (self.lbl_vm, self.lbl_state, self.lbl_health):
            w.setStyleSheet("color: #d7e1d9; font-size: 11px;")
        s.addWidget(self.lbl_vm)
        s.addWidget(self.lbl_state)
        s.addWidget(self.lbl_health)
        status_group.setLayout(s)
        left_layout.addWidget(status_group)

        meta_group = QGroupBox("Metabolic State")
        meta_group.setStyleSheet(groupbox_style)
        m = QVBoxLayout()
        self.lbl_atp = QLabel("ATP: 1.00")
        self.lbl_ca = QLabel("Ca²⁺: 0.00")
        self.lbl_mito = QLabel("Mitochondria: 100%")
        self.lbl_integrity = QLabel("Integrity: 100%")
        self.lbl_damage = QLabel("Damage: 0%")
        for w in (self.lbl_atp, self.lbl_ca, self.lbl_mito, self.lbl_integrity, self.lbl_damage):
            w.setStyleSheet("color: #d7e1d9; font-size: 11px;")
        m.addWidget(self.lbl_atp)
        m.addWidget(self.lbl_ca)
        m.addWidget(self.lbl_mito)
        m.addWidget(self.lbl_integrity)
        m.addWidget(self.lbl_damage)
        meta_group.setLayout(m)
        left_layout.addWidget(meta_group)

        run_group = QGroupBox("Run Control")
        run_group.setStyleSheet(groupbox_style)
        rc_layout = QVBoxLayout()

        btn_layout = QHBoxLayout()
        self.btn_start = QPushButton("Start")
        self.btn_start.clicked.connect(self.toggle_run)
        self.btn_kill = QPushButton("Kill cell")
        self.btn_kill.clicked.connect(self.kill_cell)
        btn_layout.addWidget(self.btn_start)
        btn_layout.addWidget(self.btn_kill)
        rc_layout.addLayout(btn_layout)

        run_group.setLayout(rc_layout)
        left_layout.addWidget(run_group)

        stim_group = QGroupBox("Stimulation")
        stim_group.setStyleSheet(groupbox_style)
        st = QVBoxLayout()
        st.addWidget(QLabel("Mode:"))
        self.combo_mode = QComboBox()
        self.combo_mode.addItems(self.stim.MODES)
        self.combo_mode.currentTextChanged.connect(self.change_mode)
        st.addWidget(self.combo_mode)

        st.addWidget(QLabel("Amplitude (µA/cm²):"))
        self.slider_amp = QSlider(Qt.Horizontal)
        self.slider_amp.setRange(-20, 40)
        self.slider_amp.setValue(int(self.stim.amplitude))
        self.slider_amp.valueChanged.connect(self.on_amp_changed)
        self.lbl_amp_value = QLabel(f"{self.stim.amplitude:.1f}")
        amp_row = QWidget()
        amp_layout = QHBoxLayout(amp_row)
        amp_layout.setContentsMargins(0, 0, 0, 0)
        amp_layout.addWidget(self.slider_amp, 1)
        amp_layout.addWidget(self.lbl_amp_value)
        st.addWidget(amp_row)

        self.btn_step = QPushButton("Deliver step pulse")
        self.btn_step.clicked.connect(self.deliver_step_pulse)
        st.addWidget(self.btn_step)

        self.lbl_mode_desc = QLabel("")
        self.lbl_mode_desc.setWordWrap(True)
        self.lbl_mode_desc.setStyleSheet("color: #9cb9a2; font-size: 10px;")
        st.addWidget(self.lbl_mode_desc)

        stim_group.setLayout(st)
        left_layout.addWidget(stim_group)

        log_group = QGroupBox("Log")
        log_group.setStyleSheet(groupbox_style)
        lg = QVBoxLayout()
        self.log_widget = QPlainTextEdit()
        self.log_widget.setReadOnly(True)
        self.log_widget.setStyleSheet(
            "background-color: #0b0d10; color: #c7dacf; "
            "font-family: 'Fira Code', monospace; font-size: 13px;"
        )
        lg.addWidget(self.log_widget)
        log_group.setLayout(lg)
        left_layout.addWidget(log_group, 1)

        main_layout.addWidget(left_panel)

        self.tabs = QTabWidget()

        self.tab_voltage = QWidget()
        vlayout = QVBoxLayout(self.tab_voltage)
        self.voltage_plot = pg.PlotWidget(title="Membrane Potential (Vm)")
        self.voltage_plot.setLabel("left", "Voltage", units="mV")
        self.voltage_plot.setLabel("bottom", "Time", units="s")
        self.voltage_plot.setYRange(-80, 50)
        self.voltage_plot.showGrid(x=True, y=True, alpha=0.2)
        self.voltage_plot.setMouseEnabled(x=True, y=True)
        self.curve_vm = self.voltage_plot.plot(pen={"color": "#8bff9e", "width": 2})
        self.curve_vm.setClipToView(True)

        self.curve_vm.setDownsampling(auto=True, method="peak")
        self.curve_vm.setSkipFiniteCheck(True)

        vlayout.addWidget(self.voltage_plot)
        self.tab_voltage.setLayout(vlayout)

        self.tab_meta = QWidget()
        meta_layout = QVBoxLayout(self.tab_meta)

        self.meta_stack = QStackedWidget()

        self.meta_overview = QWidget()
        ov_layout = QVBoxLayout(self.meta_overview)

        self.lbl_atp_plot = ClickableLabel("ATP")
        self.lbl_atp_plot.setStyleSheet("color: #d7e1d9; font-weight: 600;")
        self.lbl_atp_plot.clicked_callback = lambda: self.show_meta_detail("ATP")
        self.plot_atp = pg.PlotWidget()
        self.plot_atp.setLabel("left", "ATP", units="")
        self.curve_atp = self.plot_atp.plot(pen={"color": "#88ff88", "width": 1})

        self.lbl_ca_plot = ClickableLabel("Ca²⁺")
        self.lbl_ca_plot.setStyleSheet("color: #d7e1d9; font-weight: 600;")
        self.lbl_ca_plot.clicked_callback = lambda: self.show_meta_detail("Ca")
        self.plot_ca = pg.PlotWidget()
        self.plot_ca.setLabel("left", "Ca²⁺", units="")
        self.curve_ca = self.plot_ca.plot(pen={"color": "#ff8888", "width": 1})

        self.lbl_mito_plot = ClickableLabel("Mitochondria")
        self.lbl_mito_plot.setStyleSheet("color: #d7e1d9; font-weight: 600;")
        self.lbl_mito_plot.clicked_callback = lambda: self.show_meta_detail("Mito")
        self.plot_mito = pg.PlotWidget()
        self.plot_mito.setLabel("left", "Mito (%)", units="")
        self.curve_mito = self.plot_mito.plot(pen={"color": "#88ccff", "width": 1})

        self.lbl_integrity_plot = ClickableLabel("Integrity")
        self.lbl_integrity_plot.setStyleSheet("color: #d7e1d9; font-weight: 600;")
        self.lbl_integrity_plot.clicked_callback = lambda: self.show_meta_detail("Integrity")
        self.plot_integrity = pg.PlotWidget()
        self.plot_integrity.setLabel("left", "Integrity", units="")
        self.curve_integrity = self.plot_integrity.plot(pen={"color": "#ffff88", "width": 1})

        self.lbl_damage_plot = ClickableLabel("Damage")
        self.lbl_damage_plot.setStyleSheet("color: #d7e1d9; font-weight: 600;")
        self.lbl_damage_plot.clicked_callback = lambda: self.show_meta_detail("Damage")
        self.plot_damage = pg.PlotWidget()
        self.plot_damage.setLabel("left", "Damage", units="")
        self.curve_damage = self.plot_damage.plot(pen={"color": "#ffbb55", "width": 1})

        for lbl, plt in [
            (self.lbl_atp_plot, self.plot_atp),
            (self.lbl_ca_plot, self.plot_ca),
            (self.lbl_mito_plot, self.plot_mito),
            (self.lbl_integrity_plot, self.plot_integrity),
            (self.lbl_damage_plot, self.plot_damage),
        ]:
            ov_layout.addWidget(lbl)
            ov_layout.addWidget(plt)

        self.meta_overview.setLayout(ov_layout)

        self.meta_detail = QWidget()
        detail_layout = QVBoxLayout(self.meta_detail)
        self.btn_meta_back = QPushButton("Back to overview")
        self.btn_meta_back.clicked.connect(self.hide_meta_detail)
        self.lbl_meta_detail_title = QLabel("ATP detail")
        self.lbl_meta_detail_title.setAlignment(Qt.AlignCenter)
        self.lbl_meta_detail_title.setStyleSheet("color: #d7e1d9; font-weight: 600;")
        self.plot_meta_detail = pg.PlotWidget()
        self.plot_meta_detail.setLabel("left", "Value", units="")
        self.plot_meta_detail.setLabel("bottom", "Time", units="s")
        self.curve_meta_detail = self.plot_meta_detail.plot(pen={"color": "#ffffff", "width": 1.5})

        detail_layout.addWidget(self.btn_meta_back)
        detail_layout.addWidget(self.lbl_meta_detail_title)
        detail_layout.addWidget(self.plot_meta_detail)
        self.meta_detail.setLayout(detail_layout)

        self.meta_stack.addWidget(self.meta_overview)
        self.meta_stack.addWidget(self.meta_detail)

        meta_layout.addWidget(self.meta_stack)
        self.tab_meta.setLayout(meta_layout)

        self.tabs.addTab(self.tab_voltage, "Voltage")
        self.tabs.addTab(self.tab_meta, "Metabolism")

        main_layout.addWidget(self.tabs, 1)

        self.setStyleSheet("QMainWindow{background-color:#0c0e10;} QLabel{color:#d7e1d9;}")

        self.update_mode_desc()
        self.update_status_labels()
        self.log("System initialized.")

    # control

    def set_time_scale(self, factor: float, label: str):
        self.time_scale_factor = factor
        self.log(f"Time scale set to {label}.")

    def set_voltage_window(self, width_sec: float, label: str):
        self.window_sec = width_sec
        self.plot_buffer_size = int(self.window_sec * 1000 / self.plot_dt_ms)
        old_t = list(self.t_data)
        old_v = list(self.v_data)
        self.t_data = deque(old_t[-self.plot_buffer_size:], maxlen=self.plot_buffer_size)
        self.v_data = deque(old_v[-self.plot_buffer_size:], maxlen=self.plot_buffer_size)
        self.log(f"Voltage window set to {label}.")

    # logging

    def log(self, msg: str):
        t_sim_sec = self.time_ms / 1000.0
        self.log_widget.appendPlainText(f"[{t_sim_sec:7.3f} s] {msg}")

    def toggle_run(self):
        if self.running:
            self.running = False
            self.timer.stop()
            self.btn_start.setText("Start")
            self.log("Acquisition stopped.")
            self.voltage_plot.setMouseEnabled(x=True, y=True)
        else:
            self.neuron.reset()
            self._reset_log_flags()

            self.t_data.clear()
            self.v_data.clear()
            self.t_full.clear()
            self.v_full.clear()
            self._apply_vm_history_limit()

            self.meta_t.clear()
            self.meta_atp.clear()
            self.meta_ca.clear()
            self.meta_mito.clear()
            self.meta_integrity.clear()
            self.meta_damage.clear()

            self.time_ms = 0.0
            self.time_since_last_plot = 0.0
            self.last_step_time_ms = None
            self.step_recovery_logged = False

            if self.voltage_view_mode == "HISTORY":
                self.voltage_plot.setMouseEnabled(x=True, y=True)
            else:
                self.voltage_plot.setMouseEnabled(x=False, y=True)

            self.running = True
            self.timer.start(self.timer_interval)
            self.btn_start.setText("Stop")
            self.log("Acquisition started.")

    def _reset_log_flags(self):
        n = self.neuron
        for attr in (
            "flag_atp_low",
            "flag_ca_high",
            "flag_mito_stress",
            "flag_integrity_low",
            "flag_damage_high",
            "flag_cascade",
        ):
            if hasattr(n, attr):
                setattr(n, attr, False)

    def kill_cell(self):
        self.neuron.kill()
        self.log("ACTION: Cell killed manually.")
        self.update_status_labels()

    def change_mode(self, mode: str):
        self.stim.set_mode(mode, self.time_ms)
        self.update_mode_desc()
        self.log(f"Stim mode changed to '{mode}'.")

    def on_amp_changed(self, val: int):
        self.stim.amplitude = float(val)
        self.lbl_amp_value.setText(f"{float(val):.1f}")

    def deliver_step_pulse(self):
        if self.stim.mode != "STEP":
            self.log("Step pulses are only delivered in STEP mode.")
            return
        if not self.running:
            self.log("Cannot deliver step pulse while stopped.")
            return
        self.stim.trigger_step(self.time_ms)
        self.last_step_time_ms = self.time_ms
        self.step_recovery_logged = False
        self.log(
            f"Step pulse delivered at t={self.time_ms/1000.0:7.3f} s "
            f"(amplitude {self.stim.amplitude:.1f} µA/cm²)."
        )

    def update_mode_desc(self):
        mode = self.combo_mode.currentText()
        self.lbl_mode_desc.setText(MODE_DESCRIPTIONS.get(mode, ""))

    # metabolism view

    def show_meta_detail(self, var_name: str):
        self.meta_detail_var = var_name
        self.lbl_meta_detail_title.setText(f"{var_name} detail")
        self.meta_stack.setCurrentIndex(1)
        self.update_meta_detail_plot()

    def hide_meta_detail(self):
        self.meta_detail_var = None
        self.meta_stack.setCurrentIndex(0)

    def update_meta_plots(self):
        if not self.meta_t:
            return

        t = self.meta_t
        self.curve_atp.setData(t, self.meta_atp)
        self.curve_ca.setData(t, self.meta_ca)
        self.curve_mito.setData(t, self.meta_mito)
        self.curve_integrity.setData(t, self.meta_integrity)
        self.curve_damage.setData(t, self.meta_damage)

        if self.meta_detail_var is not None:
            self.update_meta_detail_plot()

    def update_meta_detail_plot(self):
        if not self.meta_t:
            return
        t = self.meta_t
        if self.meta_detail_var == "ATP":
            y = self.meta_atp
        elif self.meta_detail_var == "Ca":
            y = self.meta_ca
        elif self.meta_detail_var == "Mito":
            y = self.meta_mito
        elif self.meta_detail_var == "Integrity":
            y = self.meta_integrity
        elif self.meta_detail_var == "Damage":
            y = self.meta_damage
        else:
            return
        self.curve_meta_detail.setData(t, y)

    # main loop

    def update_loop(self):
        if not self.running:
            return

        steps_to_run = int((self.timer_interval / self.dt) * self.time_scale_factor)
        if steps_to_run == 0 and self.time_scale_factor > 0:
            steps_to_run = 1

        for _ in range(steps_to_run):
            i_stim = self.stim.current_at(self.time_ms)
            v_true = self.neuron.step(self.dt, i_stim, kill_mode=False)

            self.time_ms += self.dt
            self.time_since_last_plot += self.dt

            if self.time_since_last_plot >= self.plot_dt_ms:
                self.time_since_last_plot -= self.plot_dt_ms
                v_meas = self.daq.acquire_sample(v_true)
                t_sec = self.time_ms / 1000.0

                self.t_data.append(t_sec)
                self.v_data.append(v_meas)
                self.t_full.append(t_sec)
                self.v_full.append(v_meas)

                self.meta_t.append(t_sec)
                self.meta_atp.append(self.neuron.ATP)
                self.meta_ca.append(self.neuron.Ca)
                self.meta_mito.append(self.neuron.mito)
                self.meta_integrity.append(self.neuron.integrity)
                self.meta_damage.append(self.neuron.damage)

        if self.voltage_view_mode == "HISTORY":
            if self.t_full:
                self.curve_vm.setData(x=list(self.t_full), y=list(self.v_full))
        else:
            if self.t_data:
                self.curve_vm.setData(x=list(self.t_data), y=list(self.v_data))
                t_max = self.t_data[-1]
                t_min = max(0.0, t_max - self.window_sec)
                self.voltage_plot.setXRange(t_min, t_max, padding=0)

        self.update_meta_plots()
        self.update_status_labels()
        self.update_event_logs()

    # events

    def update_event_logs(self):
        n = self.neuron
        stim_on = (self.stim.mode != "OFF")

        if n.dead and self.running:
            self.log("EVENT: Cell has died.")
            self.running = False
            self.timer.stop()
            self.btn_start.setText("Start")
            self.voltage_plot.setMouseEnabled(x=True, y=True)
            return

        if n.ATP < 0.3 and not n.flag_atp_low:
            self.log("WARNING: ATP levels critically low.")
            n.flag_atp_low = True

        if n.Ca > 1.0 and not n.flag_ca_high:
            self.log("WARNING: Intracellular Ca²⁺ overload developing.")
            n.flag_ca_high = True

        if n.mito < 80.0 and not n.flag_mito_stress:
            self.log("NOTICE: Mitochondrial output reduced.")
            n.flag_mito_stress = True

        if n.integrity < 60.0 and not n.flag_integrity_low:
            self.log("NOTICE: Structural integrity declining.")
            n.flag_integrity_low = True

        if n.damage > 20.0 and not n.flag_damage_high:
            self.log("WARNING: Permanent damage accumulating.")
            n.flag_damage_high = True

        if n.ATP < 0.2 and n.Ca > 0.5 and stim_on and not n.flag_cascade:
            self.log("DANGER: Excitotoxic cascade conditions reached.")
            n.flag_cascade = True

        if (
            self.stim.mode == "STEP"
            and self.last_step_time_ms is not None
            and not self.step_recovery_logged
        ):
            if self.time_ms - self.last_step_time_ms > 2.0:
                if abs(n.v + 65.0) < 1.0:
                    recovery_ms = self.time_ms - self.last_step_time_ms
                    self.log(
                        f"Recovery: membrane returned near rest after {recovery_ms:.1f} ms."
                    )
                    self.step_recovery_logged = True

    def update_status_labels(self):
        n = self.neuron
        self.lbl_vm.setText(f"Vm: {n.v:6.2f} mV")
        self.lbl_health.setText(f"Health: {n.health:5.1f}%")
        self.lbl_atp.setText(f"ATP: {n.ATP:4.2f}")
        self.lbl_ca.setText(f"Ca²⁺: {n.Ca:4.2f}")
        self.lbl_mito.setText(f"Mitochondria: {n.mito:5.1f}%")
        self.lbl_integrity.setText(f"Integrity: {n.integrity:5.1f}%")
        self.lbl_damage.setText(f"Damage: {n.damage:5.1f}%")

        if n.dead:
            state = "DEAD"
            color = "#ff4d4d"
        else:
            if n.v > -40.0:
                state = "ACTIVE"
                color = "#9fffba"
            else:
                state = "QUIESCENT"
                color = "#d7e1d9"

            if n.health < 50.0:
                color = "#ffb347"
            elif n.damage > 1.0:
                color = "#ffd966"

        self.lbl_state.setText(f"State: {state}")
        self.lbl_state.setStyleSheet(f"color:{color}; font-weight:600;")

    def generate_report(self):
        n = self.neuron
        t_sim = self.time_ms / 1000.0

        lines = []
        lines.append("==== Simulation Report ====")
        lines.append(f"Total simulated time: {t_sim:.3f} s")
        lines.append("")
        lines.append(f"Final Vm:        {n.v:6.2f} mV")
        lines.append(f"Final ATP:       {n.ATP:5.3f}")
        lines.append(f"Final Ca²⁺:      {n.Ca:5.3f}")
        lines.append(f"Final Mito:      {n.mito:5.1f} %")
        lines.append(f"Final Integrity: {n.integrity:5.1f} %")
        lines.append(f"Final Damage:    {n.damage:5.1f} %")
        lines.append(f"Final Health:    {n.health:5.1f} %")
        lines.append(f"Dead:            {'yes' if n.dead else 'no'}")
        lines.append("")

        if self.meta_t:
            lines.append("Metabolic ranges (over full run):")
            lines.append(f"  ATP:       {min(self.meta_atp):.3f} – {max(self.meta_atp):.3f}")
            lines.append(f"  Ca²⁺:      {min(self.meta_ca):.3f} – {max(self.meta_ca):.3f}")
            lines.append(f"  Mito:      {min(self.meta_mito):.1f} – {max(self.meta_mito):.1f} %")
            lines.append(f"  Integrity: {min(self.meta_integrity):.1f} – {max(self.meta_integrity):.1f} %")
            lines.append(f"  Damage:    {min(self.meta_damage):.1f} – {max(self.meta_damage):.1f} %")
        else:
            lines.append("No metabolic history recorded yet.")

        self.log_widget.appendPlainText("\n".join(lines))

    def show_about(self):
        QMessageBox.about(
            self,
            "About Axonion",
            (
                "<h3>Axonion</h3>"
                "<p><i>Single-neuron electrophysiology workstation</i></p>"
                "<p>"
                "<b>Axonion</b> is an interactive environment for exploring "
                "how a single neuron responds to electrical stimulation "
                "and how its internal metabolic state evolves over time."
                "</p>"
                "<h4>Neuron model</h4>"
                "<p>"
                "The simulation is based on a Hodgkin–Huxley-style membrane model "
                "extended with simplified representations of calcium dynamics, "
                "energy metabolism, mitochondrial stress, structural integrity, "
                "and permanent damage."
                "</p>"
                "<p>"
                "Electrical activity and metabolism are tightly coupled. "
                "A neuron may appear electrically active while internally "
                "approaching failure."
                "</p>"
                "<h4>What this application is for</h4>"
                "<ul>"
                "<li>Exploring stimulation strategies</li>"
                "<li>Observing recovery and fatigue</li>"
                "<li>Understanding calcium overload and energy depletion</li>"
                "<li>Building intuition, not making predictions</li>"
                "</ul>"
                "<h4>Limitations</h4>"
                "<p>"
                "This is not a biophysically exact neuron model and should not "
                "be used for quantitative research conclusions."
                "</p>"
                "<p>"
                "<b>Version:</b> 0.1<br>"
                "<b>Author:</b> mossware"
                "</p>"
            )
        )
