from __future__ import annotations

from dataclasses import dataclass

from .exceptions import GeometryError


LENGTH_FACTORS_TO_M = {
    "m": 1.0,
    "cm": 1e-2,
    "mm": 1e-3,
    "um": 1e-6,
    "nm": 1e-9,
}

AREA_FACTORS_TO_M2 = {
    "m^2": 1.0,
    "cm^2": 1e-4,
    "mm^2": 1e-6,
    "um^2": 1e-12,
}


@dataclass(frozen=True)
class SampleGeometry:
    length_m: float | None = None
    area_m2: float | None = None
    width_m: float | None = None
    thickness_m: float | None = None

    @property
    def effective_area_m2(self) -> float | None:
        if self.area_m2 is not None:
            return self.area_m2
        if self.width_m is not None and self.thickness_m is not None:
            return self.width_m * self.thickness_m
        return None

    @property
    def has_geometry(self) -> bool:
        return self.length_m is not None and self.effective_area_m2 is not None

    def validate(self) -> None:
        if self.length_m is not None and self.length_m <= 0:
            raise GeometryError("Voltage-contact length must be positive.")
        if self.area_m2 is not None and self.area_m2 <= 0:
            raise GeometryError("Cross-sectional area must be positive.")
        if self.width_m is not None and self.width_m <= 0:
            raise GeometryError("Sample width must be positive.")
        if self.thickness_m is not None and self.thickness_m <= 0:
            raise GeometryError("Sample thickness must be positive.")

    def resistivity(self, resistance_ohm: float | None) -> tuple[float | None, float | None]:
        if resistance_ohm is None or not self.has_geometry:
            return None, None
        self.validate()
        rho_ohm_m = resistance_ohm * self.effective_area_m2 / self.length_m
        return rho_ohm_m, rho_ohm_m * 100.0


def length_to_m(value: float | int | None, unit: str) -> float | None:
    if value is None:
        return None
    try:
        factor = LENGTH_FACTORS_TO_M[unit]
    except KeyError as exc:
        raise GeometryError(f"Unsupported length unit: {unit}") from exc
    return float(value) * factor


def area_to_m2(value: float | int | None, unit: str) -> float | None:
    if value is None:
        return None
    try:
        factor = AREA_FACTORS_TO_M2[unit]
    except KeyError as exc:
        raise GeometryError(f"Unsupported area unit: {unit}") from exc
    return float(value) * factor


def geometry_from_config(config: dict) -> SampleGeometry:
    geom = config.get("sample_geometry", {})
    length_cfg = geom.get("length", {})
    width_cfg = geom.get("width", {})
    thickness_cfg = geom.get("thickness", {})
    area_cfg = geom.get("area", {})

    length_m = length_to_m(length_cfg.get("value"), length_cfg.get("unit", "m"))
    area_m2 = None
    if "value" in area_cfg and area_cfg.get("value") is not None:
        area_m2 = area_to_m2(area_cfg.get("value"), area_cfg.get("unit", "m^2"))

    width_m = length_to_m(width_cfg.get("value"), width_cfg.get("unit", "m"))
    thickness_m = length_to_m(thickness_cfg.get("value"), thickness_cfg.get("unit", "m"))

    geometry = SampleGeometry(
        length_m=length_m,
        area_m2=area_m2,
        width_m=width_m,
        thickness_m=thickness_m,
    )
    geometry.validate()
    return geometry
