# HANDOFF.md

This is an engineering handoff for the current `resistivity372` backbone repository. It is intentionally specific to the code that exists now. Do not treat this file as an operator manual or as proof that the software is ready for real hardware.

## 1. Project Summary

`resistivity372` is a Python backbone for resistivity measurements using a Lake Shore 372 AC Resistance Bridge for sample resistance readout and a Quantum Design PPMS/MultiVu system controlled through MultiPyVu for temperature, magnetic field, chamber, and optional position state/control.

The intended full application is a GUI-driven measurement program that lets a lab user connect instruments, choose or build a measurement sequence, configure sample geometry, select an output `.dat` file, monitor live status, and run/pause/abort measurements. The measurement engine computes resistivity from resistance and sample geometry when geometry is available, or logs raw resistance when geometry is missing.

The intended data-output backend is `MultiPyVu.DataFile` so generated `.dat` files can be opened in PPMS MultiVu. The current repository also includes a CSV fallback backend for development and CI-like testing on machines without MultiPyVu or instruments installed.

## 2. Current Repository State

### Readable tree

```text
resistivity372_backbone/
  pyproject.toml
  README.md
  HANDOFF.md
  PACKAGE_FILE_LIST.txt
  requirements-lab.txt
  requirements-sim.txt

  configs/
    example_config.yaml

  sequences/
    field_sweep_10K.yaml
    smoke_simulation.yaml

  scripts/
    install_lab.ps1
    install_simulation.ps1
    verify_multipyvu_install.py

  vendor/
    wheels/
      README.md
      MultiPyVu-2.2.0-py3-none-any.whl

  resistivity372/
    __init__.py
    main.py
    runtime.py

    core/
      __init__.py
      config.py
      exceptions.py
      geometry.py
      logging_setup.py
      models.py
      safety.py

    instruments/
      __init__.py
      lakeshore372.py
      ppms_multipyvu.py
      position.py
      mocks.py

    measurement/
      __init__.py
      datafile_manager.py
      engine.py
      sequence.py
      sequence_runner.py

    app/
      __init__.py
      gui_main.py
      qt_worker.py
      widgets/
        __init__.py
        connection_panel.py
        geometry_panel.py
        log_panel.py
        plot_panel.py
        sequence_editor.py
        status_panel.py

  tests/
    test_datafile_manager.py
    test_engine_with_mocks.py
    test_geometry.py
    test_safety.py
    test_sequence.py
```

### Main entry points

- `resistivity372/main.py`
  - Defines CLI argument parsing and `main()`.
  - Exposed as a console script through `pyproject.toml`:
    - `resistivity372 = "resistivity372.main:main"`
  - Supports `--config`, `--sequence`, `--output`, `--simulate`, `--dry-run`, `--allow-overwrite`, `--validate-only`, and `--gui`.
- `resistivity372/app/gui_main.py`
  - Starts a minimal PySide6 GUI placeholder via `run_gui(args)`.
  - The GUI currently does not run the measurement worker.
- `resistivity372/runtime.py`
  - Builds controllers, data-file writer, measurement engine, and sequence runner through `RuntimeFactory`.

### GUI framework

- PySide6 is the chosen GUI framework.
- GUI dependencies are optional under the `gui` extra in `pyproject.toml`.
- Current GUI is a placeholder window with config, sequence, and output path fields plus placeholder Start and Abort buttons.
- `app/widgets/*.py` currently contain placeholder classes that raise `NotImplementedError`.

### Core modules and responsibilities

- `core/models.py`
  - Dataclasses for `LakeShoreReading`, `PPMSStatus`, and `MeasurementRecord`.
  - `MeasurementRecord.to_multivu_columns()` defines the current data columns written by both data backends.
- `core/geometry.py`
  - Unit conversion and `SampleGeometry`.
  - Resistivity formula implementation.
  - `geometry_from_config(config)`.
- `core/safety.py`
  - `SafetyLimits` and `safety_from_config(config)`.
  - Checks temperature, field, ramp rates, chamber modes, and position limits.
- `core/config.py`
  - YAML loader and small nested-dict helpers.
- `core/logging_setup.py`
  - Root logger configuration with console plus rotating file handler.
- `core/exceptions.py`
  - Custom exception classes for instruments, safety, geometry, data files, sequence validation, and aborts.

### Instrument modules

- `instruments/lakeshore372.py`
  - `LakeShore372Interface` protocol.
  - `LakeShore372Config`.
  - `RealLakeShore372Controller` wrapper around `lakeshore.Model372`.
- `instruments/ppms_multipyvu.py`
  - `PPMSInterface` protocol.
  - `PPMSConfig`.
  - `RealPPMSController` wrapper around `MultiPyVu.Client`.
- `instruments/position.py`
  - `PositionAdapter` protocol.
  - `DisabledPositionAdapter`.
  - `PPMSPositionAdapter` that delegates to the PPMS controller.
- `instruments/mocks.py`
  - `MockLakeShore372Controller`.
  - `MockPPMSController`.

### Measurement modules

- `measurement/datafile_manager.py`
  - `DataFileWriter` protocol.
  - `MultiVuDataFileManager` using `MultiPyVu.DataFile`.
  - `CsvDataFileManager` development fallback.
  - `make_datafile_manager(backend)` factory.
- `measurement/engine.py`
  - `ResistivityMeasurementEngine`.
  - Periodic readout, resistivity calculation, writing records, pause/abort checks.
- `measurement/sequence.py`
  - YAML sequence loading.
  - Loop expansion and variable substitution.
- `measurement/sequence_runner.py`
  - Sequence validation against `SafetyLimits`.
  - Step-by-step command execution.

### Configuration files

- `configs/example_config.yaml`
  - Default simulation/dry-run config.
  - Uses `data.backend: "csv"` by default.
  - Defines LS372 connection fields, PPMS host/port, geometry, safety limits, emergency-abort settings, logging, and GUI settings.

### Example sequence files

- `sequences/field_sweep_10K.yaml`
  - Simulated 10 K field sweep from -9 T to +9 T in 1 T steps, with 3 fast points per field.
  - It is intentionally fast for smoke testing; it is not an operator-approved real-hardware recipe.
- `sequences/smoke_simulation.yaml`
  - Very short mock-only sequence with field values `[-0.1, 0.0, 0.1]` and two points per field.

### Tests

- `tests/test_geometry.py`
- `tests/test_safety.py`
- `tests/test_sequence.py`
- `tests/test_engine_with_mocks.py`
- `tests/test_datafile_manager.py`
- `tests/test_backend_selection.py`
- `tests/test_lakeshore372_connection_config.py`

The tests currently cover core geometry, safety checks, loop expansion, mock engine logging through the CSV backend, data-file overwrite/backend selection behavior, and LS372 GPIB config/connection wiring with fake `lakeshore` and `pyvisa` modules.

### Mock/simulation components

- `MockLakeShore372Controller` returns simulated resistance with sinusoidal drift plus Gaussian noise.
- `MockPPMSController` stores simulated temperature, field, chamber, and optional position in memory.
- CLI `--simulate` sets `mode.simulation = true` only. It no longer changes `data.backend`; select `csv` or `multipyvu` explicitly in config.

### CLI commands

Typical commands supported by the current CLI:

```bash
python -m resistivity372.main --validate-only --config configs/example_config.yaml --sequence sequences/smoke_simulation.yaml
python -m resistivity372.main --simulate --dry-run --config configs/example_config.yaml --sequence sequences/smoke_simulation.yaml --output smoke.dat
python -m resistivity372.main --gui --config configs/example_config.yaml
```

After editable install, the equivalent console-script entry point is:

```bash
resistivity372 --simulate --dry-run --config configs/example_config.yaml --sequence sequences/smoke_simulation.yaml --output smoke.dat
```

## 3. How to Run the Current Software

### Python version expected

- `pyproject.toml` requires Python `>=3.10`.
- The README examples use Python 3.11 on Windows.
- The code uses modern type annotations but no features that obviously require Python newer than 3.10.

### Create and activate a virtual environment

Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

Linux/macOS shell:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

### Install dependencies

For development without GUI or hardware, use the simulation requirements file from the repository root:

```bash
python -m pip install -r requirements-sim.txt
```

Equivalent editable install command:

```bash
pip install -e .[dev]
```

For GUI development without hardware:

```bash
pip install -e .[dev,gui]
```

For lab/hardware installs, use the local-wheel requirements file:

```bash
python -m pip install -r requirements-lab.txt
python scripts/verify_multipyvu_install.py
```

`requirements-lab.txt` installs `-e .[gui,hardware]` plus the bundled wheel at `vendor/wheels/MultiPyVu-2.2.0-py3-none-any.whl`. This avoids relying on `pip install MultiPyVu` from the package index. The `hardware` extra in `pyproject.toml` now contains hardware-adjacent dependencies such as `lakeshore`, `pandas`, `pillow`, and Windows-only `pywin32`; it intentionally does **not** include `MultiPyVu`.

If a developer has a machine where package-index MultiPyVu install works, `pyproject.toml` also provides an explicit `multipyvu-pypi` extra:

```bash
pip install -e .[gui,hardware,multipyvu-pypi]
```

The bundled wheel has not been validated against every lab PC. Verify the installed version and import path with `scripts/verify_multipyvu_install.py`.

### Run without instruments / simulation mode

Use the short smoke sequence first:

```bash
python -m resistivity372.main \
  --simulate \
  --dry-run \
  --config configs/example_config.yaml \
  --sequence sequences/smoke_simulation.yaml \
  --output smoke_simulation.dat
```

Notes:

- `--simulate` uses mock instruments.
- `--simulate` does not change `data.backend`; simulation can be paired with either `csv` or `multipyvu` output.
- `--dry-run` is mostly relevant for real PPMS commands; in simulation mode, mock commands just update internal state.
- With `data.backend: "csv"`, the output is CSV-style fallback output with a `.dat` extension and is not confirmed MultiVu-compatible. With `data.backend: "multipyvu"`, the output path uses `MultiPyVu.DataFile` and must still be validated in MultiVu.

Validate config and sequence without opening instruments or creating a data file:

```bash
python -m resistivity372.main \
  --validate-only \
  --config configs/example_config.yaml \
  --sequence sequences/smoke_simulation.yaml
```

Run tests:

```bash
pytest
```

Compile/syntax check:

```bash
python -m compileall -q resistivity372
```

### Run the GUI

Install GUI extras first:

```bash
pip install -e .[dev,gui]
```

Run:

```bash
python -m resistivity372.main --gui --config configs/example_config.yaml
```

or after editable install:

```bash
resistivity372 --gui --config configs/example_config.yaml
```

Important: the current GUI is a placeholder. It does not start a measurement. Use the CLI for current smoke runs, or wire `MeasurementWorker` into a `QThread` before using the GUI for measurement execution.

### Run with real Lake Shore 372

1. Install hardware extras:

   ```bash
   python -m pip install -r requirements-lab.txt
   python scripts/verify_multipyvu_install.py
   ```

2. Edit `configs/example_config.yaml` or create a lab-specific config:

   ```yaml
   mode:
     simulation: false
     dry_run: true

   lakeshore372:
     connection:
       mode: "tcp"          # "tcp", "usb", or "gpib"
       ip_address: "192.168.1.50"
       tcp_port: 7777
       com_port: null
       serial_number: null
       gpib_resource: null  # e.g. "GPIB0::12::INSTR" when mode is "gpib"
       gpib_board: 0
       gpib_address: null
       visa_library: null
       baud_rate: 57600
       timeout_s: 2.0
   ```

3. Start with PPMS dry-run if needed, but note that `RealLakeShore372Controller.connect()` will still attempt real LS372 connection when `simulation: false`.

4. For GPIB checkout, first verify VISA visibility outside the app with NI MAX or a simple PyVISA resource-list script. Then run:

   ```bash
   python scripts/verify_lakeshore_gpib.py --resource GPIB0::12::INSTR --channel 1
   ```

5. Verify one-channel readout using a short sequence and safe settings. The dedicated GPIB helper is present, but there is still no generic `read-ls372-once` CLI command for TCP/USB.

What must be verified:

- Actual transport: TCP/IP, USB/COM, GPIB/PyVISA, or other adapter.
- Whether `lakeshore.Model372(**kwargs)` accepts the current keyword names for the installed driver.
- Channel identifier format expected by the driver.
- Whether `get_all_input_readings(channel)` returns keys exactly named `resistance`, `kelvin`, `power`, and `quadrature`.

### Run with real PPMS/MultiPyVu

1. Install hardware extras:

   ```bash
   python -m pip install -r requirements-lab.txt
   python scripts/verify_multipyvu_install.py
   ```

2. On the MultiVu computer, start MultiVu, then start the MultiPyVu server:

   ```bash
   python -m MultiPyVu
   ```

3. Configure the PPMS connection:

   ```yaml
   mode:
     simulation: false
     dry_run: true

   ppms:
     host: "127.0.0.1"   # or the MultiVu computer's reachable IP
     port: 5000
     socket_timeout_s: 10.0
     platform: "ppms"
     use_position: false
   ```

4. For first connection tests, keep `mode.dry_run: true` so setpoint commands log instead of calling MultiPyVu setpoint methods. Note that status reads still require a working MultiPyVu client/server connection.

5. Before changing setpoints, verify:

   - `Client(host=..., port=..., socket_timeout=...)` keyword compatibility.
   - `client.open()` and `client.close_client()` behavior.
   - `get_temperature()`, `get_field()`, and `get_chamber()` return shapes.
   - enum names used for temperature approach, field approach, driven mode, and chamber modes.

## 4. Instrument Interfaces

### Lake Shore 372

Current module/class:

- `resistivity372/instruments/lakeshore372.py`
- `RealLakeShore372Controller`
- `LakeShore372Config`
- `LakeShore372Interface` protocol

Connection parameters:

- Loaded through `LakeShore372Config.from_config(config)`.
- Config path: `lakeshore372.connection`.
- Supported fields:
  - `mode`: currently `"tcp"`, `"usb"`, or `"gpib"`.
  - `ip_address`
  - `tcp_port`
  - `com_port`
  - `serial_number`
  - `gpib_resource`, e.g. `"GPIB0::12::INSTR"`
  - `gpib_board` and `gpib_address`, used to build a resource string when `gpib_resource` is omitted
  - `visa_library`, usually `null` for NI-VISA
  - `read_termination` and `write_termination`, default `"\n"`
  - `baud_rate`
  - `timeout_s`
- `configure_on_connect` exists in config and dataclass but is not currently used by `connect()` to apply a preset.

Implemented driver/API calls:

- Imports `Model372` from `lakeshore`.
- Instantiates `Model372(**kwargs)`.
- For `mode: "gpib"`, imports `pyvisa`, opens the configured VISA resource, sets timeout/read/write terminations, and passes the PyVISA resource to `Model372` as `connection=...`.
- Calls `query("*IDN?")` if available to populate metadata.
- Disconnects with `disconnect_tcp()` or `disconnect_usb()` if those methods exist. For GPIB, closes the PyVISA resource and resource manager.
- `configure_channel(channel, settings)` builds `Model372InputSetupSettings` using enum names supplied in `settings`, then calls `inst.configure_input(channel, setup)`.
- `read_channel(channel)` prefers `inst.get_all_input_readings(channel)` if available.
- Fallback read path calls `inst.get_resistance_reading(channel)` and optionally `inst.get_kelvin_reading(channel)`.
- `metadata()` returns driver/model/connection/idn and optionally `get_scanner_status()`.

Supported readings:

- Resistance in ohms.
- Temperature in K if returned by the bridge or fallback `get_kelvin_reading()`.
- Excitation power if returned under key `power`.
- Quadrature if returned under key `quadrature`.
- Excitation current exists in the `LakeShoreReading` dataclass but is not populated by the real controller yet.

What is mocked:

- `MockLakeShore372Controller` in `instruments/mocks.py`.
- Simulates connection state.
- Simulates resistance with drift/noise.
- Returns `excitation_power_W=1e-12` and quadrature noise.
- Does not simulate channel configuration beyond checking connection state.

Needs real-hardware verification:

- Exact connection constructor arguments for the installed `lakeshore` driver.
- Whether the installed `lakeshore` driver accepts the PyVISA resource through `connection=...` for `Model372`.
- LS372 transport mode and physical wiring in the lab.
- GPIB resource string, NI-VISA/NI-488.2 installation, and read/write termination behavior if GPIB is used.
- Channel numbering/naming convention.
- Return format and key names for `get_all_input_readings()`.
- Whether `get_kelvin_reading()` is valid for the measurement channel.
- Whether channel configuration enum names in config match the installed package.
- Safe excitation presets for actual samples.

### PPMS / MultiPyVu

Current module/class:

- `resistivity372/instruments/ppms_multipyvu.py`
- `RealPPMSController`
- `PPMSConfig`
- `PPMSInterface` protocol

Connection configuration:

- Loaded through `PPMSConfig.from_config(config)`.
- Config path: `ppms`.
- Supported fields:
  - `host`, default `127.0.0.1`.
  - `port`, default `5000`.
  - `socket_timeout_s`, default `10.0`.
  - `platform`, stored but not currently used.
  - `use_position`, default `false`.
- `connect()` imports `MultiPyVu as mpv`, creates `mpv.Client(host=..., port=..., socket_timeout=...)`, falls back to no `socket_timeout` if the constructor raises `TypeError`, then calls `client.open()`.

Implemented commands/status:

- `read_status()`:
  - `client.get_temperature()`.
  - `client.get_field()`.
  - `client.get_chamber()`.
  - Optional `client.get_position()` if `use_position` and method exists.
  - Converts field from Oe to T for application-level status.
- `set_temperature(setpoint_K, rate_K_per_min, approach)`:
  - Validates safety.
  - Resolves `client.temperature.approach_mode` enum by name.
  - Calls `client.set_temperature(...)` unless `dry_run`.
- `set_field(setpoint_T, rate_T_per_min, approach, driven_mode)`:
  - Validates safety.
  - Converts T to Oe and T/min to Oe/s.
  - Resolves `client.field.approach_mode` and optional `client.field.driven_mode`.
  - Calls `client.set_field(...)` unless `dry_run`.
- `set_chamber(mode_name)`:
  - Validates configured chamber mode.
  - Resolves `client.chamber.mode`.
  - Calls `client.set_chamber(...)` unless `dry_run`.
- `set_position(position_deg, rate_deg_per_s)`:
  - Validates position limits.
  - Requires `client.set_position` to exist.
  - Calls `client.set_position(...)` unless `dry_run`.
- `wait_until_steady(targets, timeout_s, settle_s, abort_flag, poll_s=2.0)`:
  - Builds a MultiPyVu wait mask from `temperature.waitfor`, `field.waitfor`, and/or `chamber.waitfor`.
  - Polls `client.is_steady(mask)` in a loop so abort can be checked.

Position support status:

- `RealPPMSController.set_position()` is implemented as a direct MultiPyVu delegation if the installed client has `set_position`.
- `read_status()` can call `get_position()` when `ppms.use_position: true`.
- `instruments/position.py` provides a lightweight adapter layer, but it is not currently integrated into runtime or GUI.
- Position support is therefore partially implemented but unverified.

What is mocked:

- `MockPPMSController` in `instruments/mocks.py`.
- Simulates connection state, temperature, field, chamber, and position.
- Commands immediately update internal state after safety validation.
- `wait_until_steady()` sleeps briefly and returns.

Needs MultiPyVu verification:

- `Client` constructor keyword support, especially `socket_timeout`.
- One-client/server behavior in the lab setup.
- Return units and status enum/string types from `get_temperature()`, `get_field()`, and `get_chamber()`.
- Exact enum names for approach modes, driven modes, and chamber modes.
- Whether `client.close_client()` is the correct close method in the installed version.
- Whether `get_position()` / `set_position()` exists and whether PPMS ignores or respects rate.
- Real chamber-command behavior and allowed operations for the installed PPMS.

## 5. Data File System

Current module/classes:

- `resistivity372/measurement/datafile_manager.py`
- `DataFileWriter` protocol
- `MultiVuDataFileManager`
- `CsvDataFileManager`
- `make_datafile_manager(backend)`

Backends:

- `MultiVuDataFileManager` uses `MultiPyVu.DataFile` and is the intended backend for real MultiVu-compatible `.dat` files.
- `CsvDataFileManager` is a fallback writer for development and tests. It writes a CSV-like file with comment header lines and is explicitly not guaranteed MultiVu-compatible.
- `configs/example_config.yaml` currently sets `data.backend: "csv"`.
- `main.py --simulate` no longer forces `data.backend`; use the config to select `"csv"` or `"multipyvu"`.

Current columns written:

```text
Timestamp UTC
Elapsed Time (s)
PPMS Temperature (K)
PPMS Temperature Status
PPMS Field (T)
PPMS Field Status
PPMS Chamber Status
PPMS Position (deg)
PPMS Position Status
LakeShore Channel
Resistance (Ohm)
Resistivity (Ohm m)
Resistivity (Ohm cm)
LS372 Temperature (K)
Excitation Power (W)
Excitation Current (A)
Quadrature (Ohm)
Sequence Step Index
Sequence Step Name
Comment
Error
```

Metadata/header behavior:

- `RuntimeFactory.create_bundle()` builds metadata from:
  - `config.sample_metadata`
  - `sequence.metadata`
  - `run_metadata`
  - `controllers.lakeshore.metadata()`
- `MultiVuDataFileManager` serializes this to JSON and passes a single string header:
  - `LS372 Resistivity Measurement; metadata={...}`
- `CsvDataFileManager` writes:
  - `# CSV fallback backend, not guaranteed MultiVu-compatible`
  - `# metadata={...}`
  - CSV header row

Overwrite protection:

- Both backends refuse to overwrite existing files unless `allow_overwrite=True`.
- CLI exposes `--allow-overwrite`.
- GUI does not yet implement overwrite confirmation.

Flush behavior:

- `CsvDataFileManager.write_record()` flushes and attempts `os.fsync()` after every row.
- `MultiVuDataFileManager.write_record()` calls `write_data()` then `_try_flush()`.
- `_try_flush()` looks for internal handle attributes named `file`, `_file`, `f`, or `_f`; this is guarded and may do nothing depending on MultiPyVu internals.
- No documented MultiPyVu close/flush method has been verified in this repo.

MultiVu compatibility status:

- Not confirmed.
- The `MultiVuDataFileManager` code is structured around `MultiPyVu.DataFile`, but it has not been tested with the installed PPMS/MultiVu environment.
- The CSV fallback output is not intended to be MultiVu-compatible.

Must still be validated in MultiVu:

- Generated `MultiVuDataFileManager` files open in MultiVu.
- Header/title formatting is acceptable to MultiVu.
- Custom column names display correctly.
- String columns such as ISO timestamp/status/comment/error are accepted or need different handling.
- `NaN` values are handled as expected.
- Frequent flush strategy does not corrupt files or break MultiPyVu's writer.
- A generated file can be parsed again by MultiPyVu if that is required.

Known compatibility risks:

- MultiVu may expect certain standard columns, header sections, or timestamp behavior.
- MultiPyVu's `DataFile` may not support arbitrary string values for all columns.
- The header metadata JSON may be too long or not displayed nicely in MultiVu.
- The current writer does not add unit metadata beyond units embedded in column names.

## 6. GUI Status

Framework:

- PySide6.
- Optional install extra: `gui`.

Main window/module:

- `resistivity372/app/gui_main.py`.
- `run_gui(args)` builds a local `MainWindow` class and starts `QApplication`.

Panels/widgets currently present:

- `gui_main.py` includes only a single placeholder main window.
- It has line edits for:
  - Config path.
  - Sequence path.
  - Output path.
- It has buttons for:
  - Browse config.
  - Browse sequence.
  - Choose output.
  - Start placeholder.
  - Abort placeholder.
- It has a read-only `QTextEdit` log area.
- `app/widgets/connection_panel.py`, `status_panel.py`, `geometry_panel.py`, `sequence_editor.py`, `plot_panel.py`, and `log_panel.py` are placeholders that raise `NotImplementedError`.

Connection workflow:

- Not implemented in the GUI.
- `MeasurementWorker` has a `start_sequence()` slot that creates a runtime bundle and connects instruments indirectly, but it is not currently wired to the GUI or moved to a `QThread` by `gui_main.py`.

Data-file selection workflow:

- GUI has a file dialog to choose an output path.
- GUI does not currently pass that path into a worker run.
- No overwrite confirmation is implemented.

Sequence editor status:

- No real sequence editor is implemented.
- GUI only has a sequence file path picker.
- `MeasurementWorker.validate_sequence(sequence_path)` can load a sequence and emit a log message, but this is not wired to GUI controls.

Start/stop/abort behavior:

- GUI `Start placeholder` only logs the selected paths.
- GUI `Abort placeholder` only logs a message.
- Real pause/resume/abort logic exists in `MeasurementWorker`, `SequenceRunner`, and `ResistivityMeasurementEngine`, but is not connected to the GUI.

Live status display:

- Not implemented.
- Status rows/labels need to be built, probably in `app/widgets/status_panel.py`.

Live plotting:

- Not implemented.
- `pyqtgraph` is listed in the `gui` extra but not used yet.

Missing or incomplete GUI features:

- Real connection panel.
- Real status panel.
- Geometry input panel.
- Sequence editor or table/YAML editor.
- Worker/QThread wiring.
- Start/pause/resume/abort state machine.
- Live plot.
- File overwrite confirmation.
- Safety confirmation dialogs.
- Config editing/loading into GUI controls.
- Error dialogs and clear user-facing messages.

## 7. Measurement Sequence System

File format:

- YAML.
- Versioned with `version: 1`.

Parsing modules:

- `measurement/sequence.py`
  - `load_sequence(path)`
  - `expanded_steps(steps)`
  - `loop_values(loop)`
  - `substitute(obj, variable, value)`
- `measurement/sequence_runner.py`
  - `SequenceRunner`
  - `validate_sequence_against_safety(sequence, safety)`

Supported step types:

- `comment`
- `set_temperature`
- `wait_temperature`
- `set_field`
- `wait_field`
- `set_chamber`
- `set_position`
- `measure`
- `loop` wrapper around nested steps

Current execution model:

- `SequenceRunner.run(sequence)` validates the sequence, expands loops, then executes each step in order on the current thread.
- In CLI mode this happens in the main process/thread.
- In the intended GUI path it should happen inside `MeasurementWorker` running in a `QThread`; this is not yet wired in `gui_main.py`.
- Each step checks `abort_flag` between steps.
- Measurement loops and wait loops also check abort flags.

Loop/sweep representation:

A loop step looks like:

```yaml
- name: "Field loop"
  loop:
    variable: "field_T"
    values: [-1.0, 0.0, 1.0]
    steps:
      - name: "Set field ${field_T} T"
        set_field:
          setpoint_T: "${field_T}"
          rate_T_per_min: 0.1
```

`loop` can also use numeric `start`, `stop`, and `step`. Substitution converts a string that is exactly the token, such as `"${field_T}"`, into a numeric float.

Stability waits:

- `set_temperature`, `set_field`, and `set_chamber` can include `wait: true`.
- Explicit `wait_temperature` and `wait_field` steps are supported.
- `RealPPMSController.wait_until_steady()` polls `client.is_steady(mask)` and applies `timeout_s` plus `settle_s`.
- Mock waits sleep briefly and return.

Errors/aborts:

- Invalid version or missing `steps` list raises `SequenceValidationError`.
- Unknown step raises `SequenceValidationError`.
- Unsafe temperature/field/chamber/position commands fail validation before execution.
- `measure` steps must include `points` or `duration_s`.
- `abort_flag` stops execution between steps and during measurement/wait loops.
- There is no automatic final marker row for abort yet.

Example sequence path:

- `sequences/smoke_simulation.yaml`
- `sequences/field_sweep_10K.yaml`

Minimal valid sequence:

```yaml
version: 1
metadata:
  sample_id: "MinimalExample"
steps:
  - name: "Initial marker"
    comment: "Starting minimal measurement"
  - name: "Measure resistance"
    measure:
      channel: 1
      interval_s: 0.5
      points: 5
      name: "raw resistance"
```

## 8. Resistivity Calculation

Where it is calculated:

- `core/geometry.py`
  - `SampleGeometry.resistivity(resistance_ohm)`
- Used by:
  - `measurement/engine.py` in `ResistivityMeasurementEngine._read_one()`

Required geometry inputs:

- Either:
  - `length` plus `area`, or
  - `length` plus `width` plus `thickness`
- Config path:
  - `sample_geometry.length`
  - `sample_geometry.area`
  - `sample_geometry.width`
  - `sample_geometry.thickness`

Units supported now:

- Length units:
  - `m`, `cm`, `mm`, `um`, `nm`
- Area units:
  - `m^2`, `cm^2`, `mm^2`, `um^2`

Formula:

```text
rho = R * A / L
```

where:

- `rho` is resistivity in ohm-m.
- `R` is measured resistance in ohms.
- `A` is cross-sectional area in square meters.
- `L` is voltage-contact length in meters.

Outputs:

- `Resistivity (Ohm m)`
- `Resistivity (Ohm cm)` where `ohm cm = ohm m * 100`

Handling missing geometry:

- If geometry is incomplete, `SampleGeometry.has_geometry` is false.
- `resistivity()` returns `(None, None)`.
- Measurement still logs resistance-only records.

Current limitations:

- No uncertainty propagation.
- No Van der Pauw mode.
- No geometric correction factors.
- No contact geometry validation.
- No sample-orientation/current-direction metadata model beyond generic metadata.
- No validation that the LS372 channel is appropriate for the geometry/sample.
- Unit strings do not currently include the micro symbol variant `µm`; only `um` is supported.
- No GUI-side geometry validation yet.

## 9. Threading / Async / Responsiveness

Current implementation:

- CLI path runs synchronously in the main thread.
- Instrument controllers use `threading.RLock()` internally:
  - `RealLakeShore372Controller`
  - `RealPPMSController`
- `ResistivityMeasurementEngine` uses `threading.Event` for:
  - `abort_flag`
  - `pause_flag`
- `SequenceRunner` also checks the same flags.

GUI-intended implementation:

- `app/qt_worker.py` defines `MeasurementWorker(QObject)` with PySide6 `Signal` and `Slot` attributes.
- Intended signals:
  - `statusChanged(dict)`
  - `recordReady(object)`
  - `logMessage(str)`
  - `errorMessage(str)`
  - `finished()`
- Intended slots:
  - `validate_sequence(sequence_path)`
  - `start_sequence(config_path, sequence_path, output_path, run_metadata)`
  - `pause()`
  - `resume()`
  - `abort()`
- The worker is not currently moved into a `QThread` anywhere in `gui_main.py`.

Progress communication:

- `ResistivityMeasurementEngine` calls `on_record(record)` after every successful write.
- `SequenceRunner` calls `on_log(message)` at step start and for comments.
- `MeasurementWorker` wires these to Qt signals when used.

Abort/stop behavior:

- `MeasurementWorker.abort()` sets `abort_flag`.
- `SequenceRunner.run()` checks `abort_flag` between expanded sequence steps.
- `ResistivityMeasurementEngine.measure()` checks abort before points and during sleep.
- `RealPPMSController.wait_until_steady()` checks abort while polling.
- There is no hard thread kill, and that is good; instrument operations should remain cooperative.

Known thread-safety concerns:

- GUI is not yet wired, so thread behavior is not exercised by tests.
- Data-file writes happen in whichever thread runs the engine. That should remain a single worker thread.
- No queue-based command serialization beyond the worker/controller locks.
- If a real instrument call blocks inside a driver method, abort may not become responsive until that call returns.
- `MeasurementWorker.start_sequence()` closes the data file but does not disconnect instruments in its `finally` block. CLI `main.py` does disconnect in `finally`.

## 10. Safety Features

Implemented safety features:

- `SafetyLimits` in `core/safety.py`:
  - Temperature min/max.
  - Temperature ramp-rate max.
  - Absolute field max.
  - Field ramp-rate max.
  - Allowed chamber modes.
  - Position min/max.
  - Position rate max.
- Safety config in `configs/example_config.yaml`:
  - `temperature_min_K: 1.8`
  - `temperature_max_K: 350.0`
  - `temperature_rate_max_K_per_min: 5.0`
  - `field_abs_max_T: 9.0`
  - `field_rate_max_T_per_min: 0.25`
  - chamber mode allowlist
  - position limits `-180` to `180` deg
  - position rate max `5.0` deg/s
- Sequence validation checks safety before execution through `validate_sequence_against_safety()`.
- Controllers also check safety immediately before commands.
- Dry-run mode in `RealPPMSController` logs setpoint commands instead of sending them.
- Abort flags stop sequence/measurement loops cooperatively.
- Data-file overwrite protection exists in both writer backends.

Configured but not implemented:

- `emergency_abort` settings exist in `configs/example_config.yaml`, but no policy executor currently uses them.
- `set_field_to_zero`, `zero_field_rate_T_per_min`, chamber abort settings, and temperature abort behavior are not implemented.

Confirmation dialogs:

- Not implemented.
- GUI has no safety confirmation dialogs for dangerous temperature, field, chamber, or position operations.

Emergency abort behavior:

- Implemented only as cooperative stop of measurement/sequence loops via `abort_flag`.
- Does not automatically ramp field to zero.
- Does not change temperature.
- Does not change chamber state.
- Does not currently write a final abort marker row.

Safe shutdown behavior:

- CLI closes the data file and disconnects LS372 and PPMS in `finally`.
- GUI worker closes the data file but currently does not disconnect controllers in `finally`.
- No safe-state PPMS command policy is implemented.

Missing safety features before real lab use:

- Lab-reviewed hard limits in a separate config, not just example defaults.
- GUI confirmation dialogs above configured warning thresholds.
- Emergency-abort policy executor with explicit lab approval.
- Safe shutdown command flow.
- Dedicated hardware checkout commands for read-only status.
- Prevention of accidental real setpoint command when `dry_run` is false.
- Better chamber-operation review and interlocks.
- Consecutive instrument error policy exposed in config.
- Measurement start checklist and operator confirmation.

## 11. Logging and Error Handling

Logging module/configuration:

- `core/logging_setup.py` defines `setup_logging(config)`.
- It configures the root logger with:
  - console `StreamHandler`
  - rotating file handler
- Log config path in YAML:

```yaml
logging:
  log_dir: "./logs"
  level: "INFO"
  rotate_bytes: 5000000
  backups: 10
```

Log file location:

- Default from `configs/example_config.yaml`: `./logs/resistivity372.log` relative to current working directory.

GUI log/status display:

- Placeholder GUI has a `QTextEdit` log area.
- `MeasurementWorker` emits `logMessage` and `errorMessage` signals.
- No integrated GUI log panel is implemented yet.

Exception types:

- `InstrumentError`
- `InstrumentConnectionError`
- `InstrumentTimeoutError`
- `SafetyLimitError`
- `GeometryError`
- `DataFileError`
- `SequenceValidationError`
- `MeasurementAborted`

Current behavior:

- Instrument disconnects:
  - Real controllers raise `InstrumentConnectionError` if used while disconnected.
  - Engine catches read errors and writes error records with NaNs for failed portions.
- Instrument timeouts:
  - `RealPPMSController.wait_until_steady()` raises `InstrumentTimeoutError` on timeout.
  - No specific LS372 timeout handling beyond wrapping driver exceptions as `InstrumentError`.
- Bad sequence files:
  - `load_sequence()` and `validate_sequence_against_safety()` raise `SequenceValidationError`.
- Invalid geometry:
  - `geometry_from_config()` and `SampleGeometry.validate()` raise `GeometryError` when provided geometry is invalid.
  - Missing geometry is allowed and results in raw-resistance-only logging.
- Failed data-file creation:
  - Data managers raise `DataFileError`.
  - CLI does not start sequence if bundle creation fails.
- Data-file write failure:
  - Propagates out of `engine.measure()` and stops the run.

Known gaps:

- GUI does not present polished error dialogs.
- GUI worker does not disconnect instruments after a failed run.
- No retry/backoff policy for transient instrument disconnects.
- No typed sequence schema with exact missing-key messages.
- No log-file path display in GUI.
- No final run summary or final abort/error marker row.
- `MeasurementAborted` exception class exists but is not currently used.

## 12. Tests

How to run:

```bash
pip install -e .[dev]
pytest
```

Optional syntax check:

```bash
python -m compileall -q resistivity372
```

Current tests:

- `tests/test_geometry.py`
  - `test_resistivity_width_thickness`
  - `test_resistivity_area`
  - `test_missing_geometry_logs_raw_only`
  - `test_negative_length_rejected`
- `tests/test_safety.py`
  - `test_field_limit_rejected`
  - `test_field_rate_limit_rejected`
  - `test_temperature_boundary_allowed`
  - `test_chamber_rejected`
- `tests/test_sequence.py`
  - `test_loop_values_positive`
  - `test_loop_values_negative`
  - `test_loop_zero_step_rejected`
  - `test_expand_substitutes_numeric_values`
- `tests/test_engine_with_mocks.py`
  - `test_engine_writes_n_points`
- `tests/test_datafile_manager.py`
  - `test_refuse_overwrite`
  - `test_make_csv_backend`
  - `test_unknown_backend_rejected`
- `tests/test_backend_selection.py`
  - `test_simulation_mode_does_not_force_multipyvu_backend_to_csv`
  - `test_simulation_mode_keeps_csv_backend_when_config_requests_csv`
- `tests/test_lakeshore372_connection_config.py`
  - `test_gpib_config_builds_resource_from_board_and_address`
  - `test_gpib_config_accepts_full_resource_string`
  - `test_gpib_config_requires_resource_or_address`
  - `test_gpib_connect_uses_pyvisa_connection_keyword`

What is covered by mocks:

- Engine writes a fixed number of points.
- Mock LS372 and mock PPMS basic read/status flow.
- CSV fallback writer.
- Safety validation and geometry math.
- Basic sequence loop expansion.

What is not tested:

- Real `lakeshore` driver integration, including real PyVISA/GPIB behavior.
- Real `MultiPyVu.Client` integration.
- Real `MultiPyVu.DataFile` output compatibility.
- GUI startup in CI.
- Worker/QThread integration.
- Pause/resume behavior.
- Abort behavior.
- Timeout behavior.
- Chamber and position commands.
- Sequence validation for many malformed inputs.
- CLI success/failure paths as subprocesses.
- Logging setup behavior.

Recommended next tests:

- CLI smoke test using `subprocess.run()` and `sequences/smoke_simulation.yaml`.
- `validate-only` test proving no data file is created.
- Engine abort test.
- Engine pause/resume test.
- Consecutive read error stop test.
- Sequence validation tests for missing required keys.
- `MultiVuDataFileManager` test behind an optional marker when MultiPyVu is installed.
- GUI import/startup smoke test behind an optional marker when PySide6 is installed.
- Mock PPMS tests for chamber and position safety validation.
- Hardware-gated test for `scripts/verify_lakeshore_gpib.py` after the lab VISA stack is confirmed.

## 13. Known Limitations and Technical Debt

- Real hardware has not been validated.
- MultiVu `.dat` compatibility has not been confirmed.
- `data.backend: "csv"` is the default in the example config, so simulation output is not MultiVu-compatible.
- `MultiVuDataFileManager` may need changes after testing with the installed `MultiPyVu.DataFile`.
- LS372 driver constructor kwargs may not match the actual installed `lakeshore` package or lab transport. GPIB support is implemented through PyVISA's alternate connection object but is not hardware-validated.
- LS372 channel configuration exists but is risky and unverified.
- `lakeshore372.configure_on_connect` is defined but not used.
- `LakeShoreReading.excitation_current_A` is not populated by the real controller.
- PPMS position control is partially implemented but unverified and not integrated as a first-class runtime adapter.
- Chamber command support and enum names need verification on the installed PPMS/MultiPyVu version.
- GUI is a placeholder and cannot run measurements yet.
- Widget modules under `app/widgets/` are placeholders that raise `NotImplementedError`.
- Sequence editor is not implemented.
- Live plotting is not implemented.
- GUI overwrite confirmation is not implemented.
- GUI safety confirmations are not implemented.
- GUI geometry validation is not implemented.
- `MeasurementWorker` is not wired into `gui_main.py` and is not moved to a `QThread`.
- `MeasurementWorker` closes the data file but does not disconnect instruments after a run.
- Emergency-abort config exists but no emergency-abort policy is implemented.
- No automatic abort marker row is written to the data file.
- `MeasurementAborted` exception class exists but is unused.
- No dependency pinning beyond broad version minimums; `MultiPyVu` is pinned only by the bundled `MultiPyVu-2.2.0` wheel in `vendor/wheels/`.
- Packaging now includes local install requirement files and PowerShell helper scripts, but there is still no built/released wheel for `resistivity372` itself.
- Bundling `MultiPyVu-2.2.0-py3-none-any.whl` is a practical lab-internal workaround; redistribution/licensing should be reviewed before publishing outside the lab.
- No CI configuration.
- No lab-operator documentation.
- No hardware dry-run/read-only commands for checking a single LS372 channel or PPMS status.
- No typed schema library such as Pydantic or JSON Schema; validation is hand-rolled.
- `PACKAGE_FILE_LIST.txt` may become stale if files are added and should not be treated as authoritative.
- Grep found placeholder/TODO-like content in `README.md`, `main.py`, `app/gui_main.py`, and every `app/widgets/*.py`; no literal `TODO` or `FIXME` comments were found.

## 14. Recommended Development Sequence / Next Steps

### Phase 1 - Stabilize and Verify the Existing App

Goal: make sure a new agent can install, run, test, and understand the current backbone without hardware.

Tasks:

- [ ] Create a fresh virtual environment and run `python -m pip install -r requirements-sim.txt`.
- [ ] Run `python -m compileall -q resistivity372`.
- [ ] Run `pytest` and confirm all tests pass.
- [ ] Run CLI validation:

  ```bash
  python -m resistivity372.main --validate-only --config configs/example_config.yaml --sequence sequences/smoke_simulation.yaml
  ```

- [ ] Run mock smoke measurement:

  ```bash
  python -m resistivity372.main --simulate --dry-run --config configs/example_config.yaml --sequence sequences/smoke_simulation.yaml --output smoke_simulation.dat
  ```

- [ ] Confirm logging creates `logs/resistivity372.log`.
- [ ] Add a CLI smoke test under `tests/` using `subprocess.run()`.
- [ ] Add a generic `--read-status-once` or similar CLI helper for future TCP/USB hardware checkout. A GPIB-specific helper now exists at `scripts/verify_lakeshore_gpib.py`.

Likely files/modules touched:

- `resistivity372/main.py`
- `resistivity372/runtime.py`
- `resistivity372/core/logging_setup.py`
- `tests/test_cli.py` new
- `README.md`

### Phase 2 - Validate Instrument APIs

Goal: prove that the real LS372 and PPMS/MultiPyVu paths work against the installed lab software.

Tasks:

- [ ] Verify `RealLakeShore372Controller.connect()` with the actual Lake Shore 372.
- [ ] Confirm connection mode and kwargs for TCP/IP, USB/COM, GPIB/PyVISA, or adapter transport.
- [ ] If using GPIB, run `python scripts/verify_lakeshore_gpib.py --resource GPIB0::<address>::INSTR --channel <channel>` on the lab PC.
- [ ] Confirm `read_channel()` with the actual measurement channel.
- [ ] Confirm `get_all_input_readings()` keys and types.
- [ ] Decide whether GUI/channel preset configuration should be enabled or blocked for V1.
- [ ] Install with `python -m pip install -r requirements-lab.txt` and verify the vendored `MultiPyVu-2.2.0` wheel imports with `python scripts/verify_multipyvu_install.py`.
- [ ] Verify MultiPyVu server/client connection with `RealPPMSController.connect()`.
- [ ] Confirm `read_status()` returns temperature, field, and chamber status correctly.
- [ ] Verify `set_temperature()` in dry-run first, then with a safe small real command.
- [ ] Verify `set_field()` conversion and enum names using a safe small field command.
- [ ] Verify chamber commands, or explicitly disable them if the installed system should not be controlled by this app.
- [ ] Investigate `get_position()` and `set_position()` availability; integrate or document unsupported status.
- [ ] Add hardware integration notes to `README.md` and this handoff.

Likely files/modules touched:

- `resistivity372/instruments/lakeshore372.py`
- `resistivity372/instruments/ppms_multipyvu.py`
- `resistivity372/instruments/position.py`
- `configs/example_config.yaml`
- new `configs/lab_ppms_example.yaml` or local ignored config
- `README.md`
- `HANDOFF.md`

### Phase 3 - Validate MultiVu-Compatible Data Files

Goal: make sure generated `.dat` files open cleanly in MultiVu and preserve all useful columns.

Tasks:

- [ ] Set `data.backend: "multipyvu"` in a test config on a machine with MultiPyVu installed.
- [ ] Generate a short simulation or mock-backed data file through `MultiVuDataFileManager` if possible.
- [ ] Open generated file in MultiVu.
- [ ] Compare header and columns against a known-good MultiVu file.
- [ ] Test string-valued columns: timestamp, status, comments, errors.
- [ ] Confirm `NaN` handling.
- [ ] Determine whether explicit units/metadata need a different MultiPyVu API.
- [ ] Determine whether a public close/flush method exists and replace `_try_flush()` if needed.
- [ ] Add a regression test behind a `pytest.mark.multipyvu` marker.
- [ ] Commit or document a small known-good output file if allowed by lab policy.

Likely files/modules touched:

- `resistivity372/measurement/datafile_manager.py`
- `resistivity372/core/models.py`
- `configs/example_config.yaml`
- `tests/test_datafile_manager.py`
- `tests/test_backend_selection.py`
- new `tests/test_multipyvu_datafile.py`

### Phase 4 - Improve Measurement Sequencing

Goal: make sequence execution robust enough for real experiments.

Tasks:

- [ ] Harden sequence schema validation with explicit missing-key messages.
- [ ] Add tests for invalid/malformed sequence files.
- [ ] Add better error reporting for failed steps.
- [ ] Add support for comments/markers written to data files, not just logs.
- [ ] Add final abort and final complete marker rows.
- [ ] Add optional `measure_until_stable` or `measure_while_sweeping` only if needed by lab workflows.
- [ ] Confirm pause/resume behavior in tests.
- [ ] Add stable wait conditions for combined temperature+field waits if needed.
- [ ] Decide whether loops should support nested loops; current expansion only handles one loop level at a time as written.

Likely files/modules touched:

- `resistivity372/measurement/sequence.py`
- `resistivity372/measurement/sequence_runner.py`
- `resistivity372/measurement/engine.py`
- `resistivity372/measurement/datafile_manager.py`
- `tests/test_sequence.py`
- new `tests/test_sequence_runner.py`

### Phase 5 - Improve GUI Usability

Goal: turn the placeholder GUI into a usable lab-facing application.

Tasks:

- [ ] Wire `MeasurementWorker` into a real `QThread` in `gui_main.py`.
- [ ] Implement `ConnectionPanel` for LS372/PPMS settings and connection status.
- [ ] Implement `StatusPanel` for live temperature, field, chamber, position, resistance, and resistivity.
- [ ] Implement `GeometryPanel` with units and validation.
- [ ] Implement `SequenceEditor` as either a YAML editor or a simple table-backed editor.
- [ ] Implement `LogPanel` using the worker's log/error signals.
- [ ] Implement `PlotPanel` using `pyqtgraph`.
- [ ] Add file overwrite confirmation.
- [ ] Add Start/Pause/Resume/Abort state transitions.
- [ ] Disable unsafe controls while a sequence is running.
- [ ] Add clear visual indicators for simulation and dry-run mode.

Likely files/modules touched:

- `resistivity372/app/gui_main.py`
- `resistivity372/app/qt_worker.py`
- all `resistivity372/app/widgets/*.py`
- `resistivity372/runtime.py`
- `resistivity372/core/geometry.py`
- `resistivity372/core/safety.py`

### Phase 6 - Safety and Lab Readiness

Goal: make the app safe enough for supervised real lab use.

Tasks:

- [ ] Move lab-approved hard limits into a lab-specific config.
- [ ] Add warning thresholds separate from hard limits.
- [ ] Add confirmation dialogs for dangerous operations.
- [ ] Implement emergency abort policy using `emergency_abort` config.
- [ ] Add safe shutdown policy and operator choice.
- [ ] Add read-only hardware checkout mode.
- [ ] Add a real-hardware dry-run checklist to docs.
- [ ] Add an interlock that requires explicit confirmation when `simulation=false` and `dry_run=false`.
- [ ] Add chamber-operation restrictions and documentation.
- [ ] Add run metadata fields for operator, sample, and lab notebook reference.

Likely files/modules touched:

- `resistivity372/core/safety.py`
- `resistivity372/runtime.py`
- `resistivity372/measurement/sequence_runner.py`
- `resistivity372/app/gui_main.py`
- `configs/example_config.yaml`
- new `docs/` or README sections

### Phase 7 - Packaging and Documentation

Goal: make the project easier to install, run, and maintain.

Tasks:

- [ ] Improve `README.md` once the GUI is real.
- [ ] Keep `HANDOFF.md` updated after major changes.
- [ ] Add example configs for simulation, PPMS-local, and PPMS-remote modes.
- [ ] Decide whether the vendored `MultiPyVu-2.2.0` wheel remains the lab standard or should be replaced by a private package index.
- [ ] Add dependency pinning or a lock-file strategy for lab computers.
- [ ] Add CI configuration for tests and linting.
- [ ] Decide whether to package with `setuptools` only or add a fuller build/release workflow.
- [ ] Add operator-facing documentation separate from developer handoff.
- [ ] Add developer notes for installed driver quirks.

Likely files/modules touched:

- `pyproject.toml`
- `requirements-lab.txt`
- `requirements-sim.txt`
- `scripts/install_lab.ps1`
- `scripts/verify_multipyvu_install.py`
- `vendor/wheels/`
- `README.md`
- `HANDOFF.md`
- `configs/`
- `sequences/`
- new `.github/workflows/` if using GitHub Actions
- new `docs/` if desired

## 15. Suggested Immediate Next Issues

- [ ] Confirm fresh lab install with `python -m pip install -r requirements-lab.txt`.
- [ ] Verify `python scripts/verify_multipyvu_install.py` using the bundled `MultiPyVu-2.2.0` wheel.
- [ ] Verify `RealLakeShore372Controller` against real Model 372 hardware.
- [ ] Add a read-only CLI command for one LS372 channel read and one PPMS status read.
- [ ] Confirm generated `MultiVuDataFileManager` `.dat` files open in MultiVu.
- [ ] Replace or confirm the position-control path in `RealPPMSController.set_position()`.
- [ ] Decide whether chamber commands should be enabled in V1 or disabled by config.
- [ ] Wire `MeasurementWorker` into `gui_main.py` with a real `QThread`.
- [ ] Implement `ConnectionPanel` and `StatusPanel` first; defer plot polish.
- [ ] Add GUI validation for sample geometry.
- [ ] Add GUI file-overwrite confirmation.
- [ ] Add sequence schema validation tests for missing keys and bad types.
- [ ] Add pause/resume and abort tests for `ResistivityMeasurementEngine`.
- [ ] Add final abort marker and complete marker rows to output files.
- [ ] Expose `max_consecutive_read_errors` in config.
- [ ] Add emergency-abort integration test using mocks.
- [ ] Update `PACKAGE_FILE_LIST.txt` or remove it if it will not be maintained.

## 16. Open Questions for the Human Developer

- What transport is used for the Lake Shore 372 connection: TCP/IP, USB/COM, GPIB adapter, serial adapter, or something else?
- If GPIB is used, what is the VISA resource string and GPIB primary address?
- What are the actual LS372 connection settings: IP address, port, COM port, baud rate, serial number, VISA resource?
- Which Lake Shore 372 channel or channels are used for the resistivity measurement?
- Should the application ever configure LS372 excitation/ranges, or should those remain front-panel/manual for V1?
- What safe excitation presets are approved for typical samples?
- What exact sample geometry fields are required by the lab workflow?
- Is this standard four-probe bar resistivity only, or should Van der Pauw/geometric correction modes be supported later?
- What sample metadata must be written into every file: sample ID, wafer, device, cooldown, operator, notebook page, contact configuration?
- Which PPMS options are installed: rotator/positioner, chamber control, magnet type, dilution/He3 option, resistivity option?
- Should chamber operations be controllable from this software, or read-only?
- What are lab-approved temperature, field, ramp-rate, and position hard limits?
- What warning thresholds should require GUI confirmation?
- What should emergency abort do on this system: stop logging only, ramp field to zero, hold temperature, change chamber state, or ask the operator?
- What directory convention should be used for data files?
- Should the filename include sample ID, date/time, sequence name, temperature, field sweep direction, or operator?
- Should the software command PPMS directly during measurements, or should some workflows only log PPMS state while the operator controls MultiVu manually?
- Should MultiPyVu run on the MultiVu computer only, or will remote TCP clients be used?
- Is one-client-at-a-time behavior a concern with other lab automation tools?
- What is the accepted known-good MultiVu `.dat` file format to compare against?

## 17. Final Handoff Summary

What works now: the repository is a buildable Python package skeleton with mock LS372/PPMS controllers, safety and geometry models, YAML sequence loading with loop expansion, a synchronous sequence runner, a measurement engine, a CSV fallback data writer, a MultiPyVu DataFile wrapper, CLI smoke execution, and mock-based tests.

What is most risky: none of the real hardware interfaces or MultiVu-compatible data output have been validated against the installed lab software. The GUI is only a placeholder and cannot run measurements yet. Position, chamber, and LS372 channel configuration are especially dependent on actual installed hardware and driver enum names.

What the next agent should do first: start with a clean virtual environment, run the tests and mock smoke sequence, then add read-only hardware checkout commands. After that, verify LS372 and MultiPyVu APIs one at a time before changing any real PPMS setpoints or relying on generated `.dat` files in MultiVu.

## Update Note — Data Backend Selection Fix

A bug was found after the vendored MultiPyVu wheel was added: simulation mode silently
forced `data.backend` from `"multipyvu"` to `"csv"` in both the CLI and runtime factory.
That made `.dat` output identical even when the config requested the MultiPyVu backend.

Current behavior after this update:

- `mode.simulation` controls only mock-vs-real instruments.
- `data.backend: "multipyvu"` now uses `MultiVuDataFileManager` even with mock instruments.
- `data.backend: "csv"` uses `CsvDataFileManager`.
- The selected backend is included in run metadata as `data_backend`.
- The runtime logs `Using data-file backend: <backend>` when an `on_log` callback is provided.
- The app no longer silently falls back from MultiPyVu to CSV. MultiPyVu import/DataFile failures now raise a clear `DataFileError`.
- Added `scripts/smoke_multipyvu_datafile.py` to create a MultiPyVu-backed smoke `.dat` file using mock instruments.

Files changed for this fix:

- `resistivity372/runtime.py`
- `resistivity372/main.py`
- `resistivity372/measurement/datafile_manager.py`
- `scripts/smoke_multipyvu_datafile.py`
- `tests/test_backend_selection.py`
- `README.md`
- `HANDOFF.md`

Immediate validation task for the next agent/lab user:

```powershell
python scripts\smoke_multipyvu_datafile.py --output multipyvu_backend_smoke.dat --allow-overwrite
```

Confirm that the file contains `[Header]` and `[Data]`, not the CSV fallback comment,
and then open it in MultiVu.

## Update Note — Desktop Mixed-Mode LS372 GPIB + MultiPyVu Simulation Test

The runtime now supports per-instrument simulation flags. This was added for the
desktop setup where the Lake Shore 372 is physically connected over GPIB, while PPMS
status/control comes from a MultiPyVu scaffolding/simulation server rather than an
actual PPMS.

Current simulation resolution is implemented in:

- `resistivity372/runtime.py`
  - `InstrumentSimulationMode`
  - `resolve_instrument_simulation_mode()`
  - updated `RuntimeFactory.create_controllers()`

Rules:

- `mode.simulation: true` still preserves the original behavior and mocks both LS372
  and PPMS.
- `mode.simulation: false` allows independent instrument settings:
  - `lakeshore372.simulation: false` means use `RealLakeShore372Controller`.
  - `lakeshore372.simulation: true` means use `MockLakeShore372Controller`.
  - `ppms.simulation: false` means use `RealPPMSController` through `MultiPyVu.Client`.
  - `ppms.simulation: true` means use `MockPPMSController`.

New desktop test files:

- `configs/desktop_lakeshore_gpib_multipyvu_sim.yaml`
- `sequences/desktop_readonly_smoke.yaml`
- `scripts/run_desktop_gpib_multipyvu_sim_test.py`

The desktop read-only sequence intentionally sends no PPMS setpoint commands. It only
reads PPMS/MultiPyVu status and reads LS372 resistance. This makes it suitable for
checking a desktop acquisition path before connecting to a real PPMS.

Recommended command for Matt's current setup:

```powershell
python scripts\run_desktop_gpib_multipyvu_sim_test.py `
  --gpib-resource GPIB0::12::INSTR `
  --channel 1 `
  --points 20 `
  --interval 1 `
  --output desktop_gpib_test.dat `
  --allow-overwrite
```

If a MultiPyVu simulation/scaffolding server is not available, use the internal mock
PPMS just to test the real LS372 read path and measurement engine:

```powershell
python scripts\run_desktop_gpib_multipyvu_sim_test.py `
  --gpib-resource GPIB0::12::INSTR `
  --channel 1 `
  --points 20 `
  --interval 1 `
  --output desktop_gpib_ppms_mock_test.dat `
  --backend csv `
  --ppms-mock `
  --allow-overwrite
```

Important distinction:

- `ppms.simulation: false` with a MultiPyVu scaffolding server still exercises the real
  `MultiPyVu.Client` path.
- `ppms.simulation: true` uses the package's internal Python mock and does not require
  MultiPyVu server connectivity.

Tests added/updated:

- `tests/test_backend_selection.py`
  - verifies real LS372 + real MultiPyVu-client selection from config;
  - verifies real LS372 + mock PPMS selection from config;
  - verifies global simulation still forces both instruments to mocks.

Immediate validation task:

1. Start the MultiPyVu scaffolding/simulation server.
2. Confirm the LS372 is visible with VISA tools or `scripts/verify_lakeshore_gpib.py`.
3. Run `scripts/run_desktop_gpib_multipyvu_sim_test.py` with the actual GPIB resource.
4. Confirm the output file contains changing or stable real LS372 resistance values and
   simulated PPMS temperature/field status.
5. Only after that, repeat with the real PPMS MultiPyVu server using a read-only sequence.
