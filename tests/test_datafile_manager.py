import pytest

from resistivity372.core.exceptions import DataFileError
from resistivity372.measurement.datafile_manager import CsvDataFileManager, make_datafile_manager


def test_refuse_overwrite(tmp_path):
    path = tmp_path / "existing.dat"
    path.write_text("existing", encoding="utf-8")
    manager = CsvDataFileManager()
    with pytest.raises(DataFileError):
        manager.create(path, metadata={}, allow_overwrite=False)


def test_make_csv_backend():
    manager = make_datafile_manager("csv")
    assert isinstance(manager, CsvDataFileManager)


def test_unknown_backend_rejected():
    with pytest.raises(DataFileError):
        make_datafile_manager("nope")
