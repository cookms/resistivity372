from __future__ import annotations

import sys
import types

import pytest

from resistivity372.core.exceptions import InstrumentConnectionError
from resistivity372.instruments.lakeshore372 import (
    LakeShore372Config,
    RealLakeShore372Controller,
)


def test_gpib_config_builds_resource_from_board_and_address():
    config = LakeShore372Config.from_config(
        {
            "lakeshore372": {
                "connection": {
                    "mode": "gpib",
                    "gpib_board": 1,
                    "gpib_address": 12,
                }
            }
        }
    )

    assert config.mode == "gpib"
    assert config.resolved_gpib_resource == "GPIB1::12::INSTR"


def test_gpib_config_accepts_full_resource_string():
    config = LakeShore372Config.from_config(
        {
            "lakeshore372": {
                "connection": {
                    "mode": "gpib",
                    "gpib_resource": "GPIB0::7::INSTR",
                    "gpib_address": 12,
                }
            }
        }
    )

    assert config.resolved_gpib_resource == "GPIB0::7::INSTR"


def test_gpib_config_requires_resource_or_address():
    config = LakeShore372Config(mode="gpib")

    with pytest.raises(InstrumentConnectionError):
        _ = config.resolved_gpib_resource


def test_gpib_connect_uses_pyvisa_connection_keyword(monkeypatch):
    opened_resources = []
    model_kwargs = {}

    class FakeVisaResource:
        def __init__(self):
            self.timeout = None
            self.read_termination = None
            self.write_termination = None
            self.closed = False

        def query(self, command):
            assert command == "*IDN?"
            return "LSCI,MODEL372,FAKE,1.0"

        def write(self, command):
            return None

        def clear(self):
            return None

        def close(self):
            self.closed = True

    fake_resource = FakeVisaResource()

    class FakeResourceManager:
        def __init__(self, *args, **kwargs):
            self.closed = False

        def open_resource(self, resource_name):
            opened_resources.append(resource_name)
            return fake_resource

        def close(self):
            self.closed = True

    fake_pyvisa = types.SimpleNamespace(ResourceManager=FakeResourceManager)

    class FakeModel372:
        def __init__(self, **kwargs):
            model_kwargs.update(kwargs)

        def query(self, command):
            return "LSCI,MODEL372,FAKE,1.0"

    fake_lakeshore = types.SimpleNamespace(Model372=FakeModel372)
    monkeypatch.setitem(sys.modules, "pyvisa", fake_pyvisa)
    monkeypatch.setitem(sys.modules, "lakeshore", fake_lakeshore)

    controller = RealLakeShore372Controller(
        LakeShore372Config(
            mode="gpib",
            gpib_address=12,
            timeout_s=3.5,
            read_termination="\n",
            write_termination="\n",
        )
    )

    controller.connect()

    assert opened_resources == ["GPIB0::12::INSTR"]
    assert model_kwargs["connection"] is fake_resource
    assert model_kwargs["baud_rate"] == 57600
    assert fake_resource.timeout == 3500
    assert fake_resource.read_termination == "\n"
    assert fake_resource.write_termination == "\n"
    assert controller.metadata()["gpib_resource"] == "GPIB0::12::INSTR"

    controller.disconnect()
    assert fake_resource.closed is True
