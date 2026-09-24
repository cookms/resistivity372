import threading
import time
from types import SimpleNamespace

from resistivity372.core.safety import SafetyLimits
from resistivity372.instruments.ppms_multipyvu import PPMSConfig, RealPPMSController


class FakeMultiPyVuClient:
    def __init__(self):
        self.temperature = SimpleNamespace(approach_mode=SimpleNamespace(fast_settle=1))
        self.field = SimpleNamespace(
            approach_mode=SimpleNamespace(linear=1),
            driven_mode=SimpleNamespace(persistent=2, driven=3),
        )
        self.chamber = SimpleNamespace(mode=SimpleNamespace(seal=1))
        self.temperature_values = [9.8, 10.0]
        self.field_values_oe = [9_900.0, 10_000.0]
        self.temperature_reads = 0
        self.field_reads = 0
        self.is_steady_calls = 0
        self.set_field_args = None

    def get_temperature(self):
        self.temperature_reads += 1
        value = self.temperature_values.pop(0) if len(self.temperature_values) > 1 else 10.0
        return value, "unknown"

    def get_field(self):
        self.field_reads += 1
        value = self.field_values_oe.pop(0) if len(self.field_values_oe) > 1 else 10_000.0
        return value, "unknown"

    def get_chamber(self):
        return "sealed"

    def set_field(self, *args):
        self.set_field_args = args

    def is_steady(self, _mask):
        self.is_steady_calls += 1
        raise AssertionError("MultiPyVu is_steady must not be used")


def _controller(field_read_delay_s=0.0):
    controller = RealPPMSController(
        PPMSConfig(field_read_delay_s=field_read_delay_s),
        SafetyLimits(),
    )
    client = FakeMultiPyVuClient()
    controller._client = client
    controller._connected = True
    return controller, client


def test_temperature_wait_uses_value_tolerance_not_multipyvu_steady_status():
    controller, client = _controller()

    controller.wait_for_temperature(
        target_K=10.0,
        tolerance_K=0.01,
        stable_s=0.0,
        equilibration_s=0.0,
        timeout_s=1.0,
        abort_flag=threading.Event(),
        poll_s=0.001,
    )

    assert client.is_steady_calls == 0


def test_temperature_wait_holds_tolerance_then_applies_equilibration_delay():
    controller, client = _controller()
    client.temperature_values = [10.0]
    started = time.monotonic()

    controller.wait_for_temperature(
        target_K=10.0,
        tolerance_K=0.01,
        stable_s=0.01,
        equilibration_s=0.01,
        timeout_s=1.0,
        abort_flag=threading.Event(),
        poll_s=0.002,
    )

    assert time.monotonic() - started >= 0.018
    assert client.temperature_reads >= 2


def test_read_status_does_not_query_field_during_ppms6000_undefined_interval():
    controller, client = _controller(field_read_delay_s=1.0)
    controller.set_field(1.0, 0.1)

    status = controller.read_status()

    assert client.field_reads == 0
    assert status.field_T is None
    assert status.field_status == "unavailable_after_set_field"
    assert client.set_field_args[-1] == client.field.driven_mode.persistent


def test_dynacool_omits_driven_mode_unless_explicitly_configured():
    controller = RealPPMSController(
        PPMSConfig(platform="dynacool", default_field_driven_mode="auto"),
        SafetyLimits(),
    )
    client = FakeMultiPyVuClient()
    controller._client = client
    controller._connected = True

    controller.set_field(1.0, 0.1)

    assert len(client.set_field_args) == 3


def test_configured_field_mode_is_used_as_sequence_default():
    controller = RealPPMSController(
        PPMSConfig(platform="dynacool", default_field_driven_mode="driven"),
        SafetyLimits(),
    )
    client = FakeMultiPyVuClient()
    controller._client = client
    controller._connected = True

    controller.set_field(1.0, 0.1)

    assert client.set_field_args[-1] == client.field.driven_mode.driven


def test_field_wait_observes_no_read_interval_then_uses_numeric_tolerance():
    controller, client = _controller(field_read_delay_s=0.02)
    controller.set_field(1.0, 0.1)
    started = time.monotonic()

    controller.wait_for_field(
        target_T=1.0,
        tolerance_T=0.001,
        stable_s=0.0,
        equilibration_s=0.0,
        timeout_s=1.0,
        abort_flag=threading.Event(),
        poll_s=0.001,
    )

    assert time.monotonic() - started >= 0.015
    assert client.field_reads == 2
    assert client.is_steady_calls == 0


def test_chamber_wait_matches_requested_final_state_without_is_steady():
    controller, client = _controller()
    client.get_chamber = lambda: "Purged and Sealed"

    controller.wait_for_chamber(
        target_mode="purge_seal",
        stable_s=0.0,
        equilibration_s=0.0,
        timeout_s=1.0,
        abort_flag=threading.Event(),
        poll_s=0.001,
    )

    assert client.is_steady_calls == 0
