from __future__ import annotations

import csv
import json
import logging
import os
from pathlib import Path
from typing import Iterable, Protocol

from resistivity372.core.exceptions import DataFileError
from resistivity372.core.models import MeasurementRecord

log = logging.getLogger(__name__)

DEFAULT_COLUMNS = [
    "Timestamp UTC",
    "Elapsed Time (s)",
    "PPMS Temperature (K)",
    "PPMS Temperature Status",
    "PPMS Field (T)",
    "PPMS Field Status",
    "PPMS Chamber Status",
    "PPMS Position (deg)",
    "PPMS Position Status",
    "LakeShore Channel",
    "Resistance (Ohm)",
    "Resistivity (Ohm m)",
    "Resistivity (Ohm cm)",
    "LS372 Temperature (K)",
    "Excitation Power (W)",
    "Excitation Current (A)",
    "Quadrature (Ohm)",
    "Sequence Step Index",
    "Sequence Step Name",
    "Comment",
    "Error",
]


class DataFileWriter(Protocol):
    @property
    def is_open(self) -> bool: ...
    def create(self, path: str | Path, metadata: dict, allow_overwrite: bool = False) -> None: ...
    def write_record(self, record: MeasurementRecord) -> None: ...
    def close(self) -> None: ...


class MultiVuDataFileManager:
    """Data-file backend using MultiPyVu.DataFile.

    This is the backend intended for real MultiVu-compatible `.dat` output. The public
    MultiPyVu API is intentionally accessed in a small wrapper so installed-version quirks
    can be patched here without touching measurement logic.
    """

    def __init__(self, columns: Iterable[str] = DEFAULT_COLUMNS):
        self.columns = list(columns)
        self.path: Path | None = None
        self._data = None
        self._open = False

    @property
    def is_open(self) -> bool:
        return self._open

    def create(self, path: str | Path, metadata: dict, allow_overwrite: bool = False) -> None:
        path = Path(path)
        if path.exists() and not allow_overwrite:
            raise DataFileError(f"Refusing to overwrite existing file: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            import MultiPyVu as mpv

            self._data = mpv.DataFile()
            if hasattr(self._data, "add_multiple_columns"):
                self._data.add_multiple_columns(self.columns)
            else:
                for column in self.columns:
                    self._data.add_column(column)
            header_text = _metadata_header(metadata)
            self._data.create_file_and_write_header(str(path), header_text)
            self.path = path
            self._open = True
            log.info("Created MultiVu data file: %s", path)
        except Exception as exc:
            self._data = None
            self._open = False
            raise DataFileError(
                f"Failed to create MultiVu data file {path}: {exc}. "
                "The 'multipyvu' backend does not fall back to CSV automatically. "
                "Install/verify MultiPyVu or set data.backend='csv' for development output."
            ) from exc

    def write_record(self, record: MeasurementRecord) -> None:
        if not self._open or self._data is None:
            raise DataFileError("Data file is not open.")
        try:
            values = record.to_multivu_columns()
            for column in self.columns:
                self._data.set_value(column, _none_to_nan(values.get(column)))
            self._data.write_data()
            self._try_flush()
        except Exception as exc:
            raise DataFileError(f"Failed to write data record: {exc}") from exc

    def close(self) -> None:
        self._try_flush()
        self._open = False

    def _try_flush(self) -> None:
        data = self._data
        if data is None:
            return
        for attr in ("file", "_file", "f", "_f"):
            handle = getattr(data, attr, None)
            if handle and hasattr(handle, "flush"):
                handle.flush()
                try:
                    os.fsync(handle.fileno())
                except Exception:
                    pass
                return


class CsvDataFileManager:
    """Simple development backend.

    This is not a MultiVu-compatible DataFile replacement. It exists so the engine and sequence
    runner can be tested on machines without MultiPyVu installed.
    """

    def __init__(self, columns: Iterable[str] = DEFAULT_COLUMNS):
        self.columns = list(columns)
        self.path: Path | None = None
        self._handle = None
        self._writer: csv.DictWriter | None = None
        self._open = False

    @property
    def is_open(self) -> bool:
        return self._open

    def create(self, path: str | Path, metadata: dict, allow_overwrite: bool = False) -> None:
        path = Path(path)
        if path.exists() and not allow_overwrite:
            raise DataFileError(f"Refusing to overwrite existing file: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._handle = path.open("w", encoding="utf-8", newline="")
            self._handle.write("# CSV fallback backend, not guaranteed MultiVu-compatible\n")
            self._handle.write(f"# metadata={json.dumps(metadata, sort_keys=True, default=str)}\n")
            self._writer = csv.DictWriter(self._handle, fieldnames=self.columns)
            self._writer.writeheader()
            self._handle.flush()
            self.path = path
            self._open = True
        except Exception as exc:
            self._open = False
            raise DataFileError(f"Failed to create CSV data file {path}: {exc}") from exc

    def write_record(self, record: MeasurementRecord) -> None:
        if not self._open or self._writer is None or self._handle is None:
            raise DataFileError("Data file is not open.")
        values = record.to_multivu_columns()
        self._writer.writerow({column: _csv_value(values.get(column)) for column in self.columns})
        self._handle.flush()
        try:
            os.fsync(self._handle.fileno())
        except Exception:
            pass

    def close(self) -> None:
        if self._handle is not None:
            self._handle.flush()
            self._handle.close()
        self._handle = None
        self._writer = None
        self._open = False


def make_datafile_manager(backend: str, columns: Iterable[str] = DEFAULT_COLUMNS) -> DataFileWriter:
    backend_normalized = str(backend).lower().strip()
    if backend_normalized == "multipyvu":
        return MultiVuDataFileManager(columns)
    if backend_normalized == "csv":
        return CsvDataFileManager(columns)
    raise DataFileError(f"Unknown data-file backend: {backend}")


def _metadata_header(metadata: dict) -> str:
    metadata_json = json.dumps(metadata, sort_keys=True, default=str)
    return f"LS372 Resistivity Measurement; metadata={metadata_json}"


def _none_to_nan(value):
    return float("nan") if value is None else value


def _csv_value(value):
    return "" if value is None else value
