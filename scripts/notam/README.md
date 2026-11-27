# NOTAM/NMS research tools

The guarded production entry point is `nms_operations.py`. Use the
[operator runbook](../../docs/NOTAM_OPERATIONS.md) for read-only preflight,
explicit catch-up approval, publication, and Windows Task Scheduler setup.

This directory contains the offline review, normalization, evidence-capture and
NMS research toolchain. It is intentionally separate from the scheduled routine
collectors in the parent `scripts/` directory.

Run documented commands from the repository root, using the paths in the NOTAM
runbooks. Tests are offline by default. Moving these files does not authorize a
provider request, enable paused acquisition, change a request budget or publish
private capture evidence.

The modules remain a coupled flat toolchain: direct CLI execution and the Python
tests add this directory to Python's import path so existing local imports keep
their behavior on Windows and POSIX systems.
