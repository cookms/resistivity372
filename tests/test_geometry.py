import math

import pytest

from resistivity372.core.exceptions import GeometryError
from resistivity372.core.geometry import SampleGeometry, area_to_m2, length_to_m


def test_resistivity_width_thickness():
    geom = SampleGeometry(
        length_m=length_to_m(1.0, "mm"),
        width_m=length_to_m(0.5, "mm"),
        thickness_m=length_to_m(20.0, "um"),
    )
    rho_m, rho_cm = geom.resistivity(100.0)
    assert math.isclose(rho_m, 1.0e-3)
    assert math.isclose(rho_cm, 0.1)


def test_resistivity_area():
    geom = SampleGeometry(length_m=1e-3, area_m2=area_to_m2(0.02, "mm^2"))
    rho_m, _ = geom.resistivity(100.0)
    assert math.isclose(rho_m, 2.0e-3)


def test_missing_geometry_logs_raw_only():
    geom = SampleGeometry()
    assert geom.resistivity(100.0) == (None, None)


def test_negative_length_rejected():
    geom = SampleGeometry(length_m=-1.0, area_m2=1e-6)
    with pytest.raises(GeometryError):
        geom.validate()


def test_negative_partial_dimension_rejected_even_when_geometry_incomplete():
    geom = SampleGeometry(width_m=-1.0)
    with pytest.raises(GeometryError):
        geom.validate()
