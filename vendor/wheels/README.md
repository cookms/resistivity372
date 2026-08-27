# Vendored wheels

This directory contains local wheel files used for lab-internal installation when
an upstream package is unavailable or unreliable through `pip install`.

Currently included:

- `MultiPyVu-2.2.0-py3-none-any.whl`
  - Package: `MultiPyVu`
  - Version: `2.2.0`
  - Source: supplied manually by the lab/user, intended to match the installed
    Quantum Design / MultiVu environment.
  - License metadata in the wheel reports MIT License.

Use:

```powershell
python -m pip install -r requirements-lab.txt
```

Do not publish this repository or wheel to a public package index without first
reviewing the Quantum Design licensing and redistribution terms for the exact
wheel being bundled.
