class InstrumentError(RuntimeError):
    """Base class for instrument-related failures."""


class InstrumentConnectionError(InstrumentError):
    """Raised when an instrument cannot be connected or used because it is disconnected."""


class InstrumentTimeoutError(InstrumentError):
    """Raised when an instrument does not reach a requested state in time."""


class SafetyLimitError(ValueError):
    """Raised when a requested instrument command violates configured hard limits."""


class GeometryError(ValueError):
    """Raised when sample geometry is invalid."""


class DataFileError(RuntimeError):
    """Raised when the measurement data file cannot be created or written."""


class SequenceValidationError(ValueError):
    """Raised when a sequence file is malformed or unsafe."""


class MeasurementAborted(RuntimeError):
    """Raised when a measurement is aborted by the user or application."""
