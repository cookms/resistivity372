import pytest

from resistivity372.core.exceptions import SafetyLimitError
from resistivity372.core.safety import SafetyLimits


def test_field_limit_rejected():
    safety = SafetyLimits(field_abs_max_T=9.0)
    with pytest.raises(SafetyLimitError):
        safety.check_field(9.1, 0.1)


def test_field_rate_limit_rejected():
    safety = SafetyLimits(field_rate_max_T_per_min=0.2)
    with pytest.raises(SafetyLimitError):
        safety.check_field(1.0, 0.25)


def test_temperature_boundary_allowed():
    safety = SafetyLimits(temperature_min_K=1.8, temperature_max_K=350.0)
    safety.check_temperature(1.8, 1.0)
    safety.check_temperature(350.0, 1.0)


def test_chamber_rejected():
    safety = SafetyLimits(allowed_chamber_modes=("seal",))
    with pytest.raises(SafetyLimitError):
        safety.check_chamber("vent_continuous")
