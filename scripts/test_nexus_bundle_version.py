#!/usr/bin/env python3
"""Gate: Nexus bundle version-staleness diagnostics.

Long-running hosts (standalone Orakle spawned by scripts/scheduler.py)
never re-import bundle modules: a Polaris wizard update swaps the files
on disk atomically while the process keeps executing the code it loaded
at startup — the 0.3.4/0.3.5 abs(None) incident class. Exercises the
diagnostics added to NexusSkillProvider:

1. load-time recording of the manifest version (installed + dev shapes)
2. healthy on-disk match -> silent, warning state re-armed
3. version drift -> warn once, not per execution; re-warns after the
   on-disk version changes again
4. manifest missing while the bundle directory exists -> warn once
5. manifest present but unreadable -> warn once
6. bundle directory gone (uninstall/swap) -> deliberately silent
"""

import json
import logging
import pathlib
import shutil
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from ainara.framework.capabilities.nexus import NexusSkillProvider  # noqa: E402


class LogCapture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


def make_provider() -> NexusSkillProvider:
    """Bare instance without __init__ (no config/flask dependencies)."""
    provider = object.__new__(NexusSkillProvider)
    provider._loaded_bundle_versions = {}
    provider._bundle_drift_warnings = {}
    return provider


def write_manifest(root: pathlib.Path, version: str, dev_shape: bool):
    if dev_shape:
        (root / "payload").mkdir(parents=True, exist_ok=True)
        path = root / "nexus.json"
    else:
        path = root / "nexus.json"
    path.write_text(
        json.dumps(
            {
                "manifest": {
                    "schemaVersion": "1.0",
                    "provider": "khromalabs",
                    "name": "ataria",
                    "version": version,
                }
            }
        ),
        encoding="utf-8",
    )
    return path


def make_cap_data():
    return {"vendor": "khromalabs", "bundle": "ataria"}


def warnings_since(cap: LogCapture) -> list:
    return [r.getMessage() for r in cap.records if r.levelno == logging.WARNING]


def gate_load_time_recording(tmp: pathlib.Path):
    """Both bundle shapes record the loaded version + identifiable log."""
    cap = LogCapture()
    logging.getLogger(
        "ainara.framework.capabilities.nexus"
    ).addHandler(cap)

    for dev_shape in (False, True):
        provider = make_provider()
        root = tmp / f"app{'_dev' if dev_shape else '_installed'}"
        root.mkdir(parents=True, exist_ok=True)
        write_manifest(root, "0.3.4", dev_shape)
        bundle_dir = root / "payload" if dev_shape else root
        provider._record_loaded_bundle_version(
            "khromalabs", "ataria", bundle_dir
        )
        loaded = provider._loaded_bundle_versions["khromalabs/ataria"]
        assert loaded["version"] == "0.3.4", loaded
        assert loaded["manifest_path"].is_file(), loaded
        # No drift yet: on-disk matches what was loaded
        provider._check_bundle_version_drift(make_cap_data())
        assert not warnings_since(cap), warnings_since(cap)

    logging.getLogger(
        "ainara.framework.capabilities.nexus"
    ).removeHandler(cap)
    print("ok  load-time version recorded for installed and dev shapes")


def gate_drift_warn_once(tmp: pathlib.Path):
    """Update on disk -> exactly one warning; new drift re-warns."""
    cap = LogCapture()
    logging.getLogger(
        "ainara.framework.capabilities.nexus"
    ).addHandler(cap)

    provider = make_provider()
    root = tmp / "drift_app"
    root.mkdir(parents=True)
    write_manifest(root, "0.3.4", dev_shape=False)
    provider._record_loaded_bundle_version(
        "khromalabs", "ataria", root
    )

    # Update to 0.3.5 while the process keeps the loaded 0.3.4 modules
    write_manifest(root, "0.3.5", dev_shape=False)
    for _ in range(3):  # several executions must not spam
        provider._check_bundle_version_drift(make_cap_data())
    warns = warnings_since(cap)
    assert len(warns) == 1, warns
    assert "0.3.4" in warns[0] and "0.3.5" in warns[0], warns[0]
    assert "restart" in warns[0].lower(), warns[0]

    # Another update (0.3.6) is a new occurrence -> warns again
    write_manifest(root, "0.3.6", dev_shape=False)
    provider._check_bundle_version_drift(make_cap_data())
    assert len(warnings_since(cap)) == 2, warnings_since(cap)

    # Returning to the loaded version re-arms the warn-once state
    write_manifest(root, "0.3.4", dev_shape=False)
    provider._check_bundle_version_drift(make_cap_data())
    assert len(warnings_since(cap)) == 2, warnings_since(cap)
    assert "khromalabs/ataria" not in provider._bundle_drift_warnings

    logging.getLogger(
        "ainara.framework.capabilities.nexus"
    ).removeHandler(cap)
    print("ok  drift warns once per occurrence and re-arms after match")


def gate_manifest_missing(tmp: pathlib.Path):
    """Manifest gone but bundle dir present -> warn once."""
    cap = LogCapture()
    logging.getLogger(
        "ainara.framework.capabilities.nexus"
    ).addHandler(cap)

    provider = make_provider()
    root = tmp / "missing_app"
    root.mkdir(parents=True)
    write_manifest(root, "0.3.5", dev_shape=False)
    provider._record_loaded_bundle_version(
        "khromalabs", "ataria", root
    )
    (root / "nexus.json").unlink()
    for _ in range(2):
        provider._check_bundle_version_drift(make_cap_data())
    warns = warnings_since(cap)
    assert len(warns) == 1, warns
    assert "missing" in warns[0], warns[0]

    logging.getLogger(
        "ainara.framework.capabilities.nexus"
    ).removeHandler(cap)
    print("ok  missing manifest (dir present) warns once")


def gate_manifest_unreadable(tmp: pathlib.Path):
    """Corrupt manifest -> warn once."""
    cap = LogCapture()
    logging.getLogger(
        "ainara.framework.capabilities.nexus"
    ).addHandler(cap)

    provider = make_provider()
    root = tmp / "corrupt_app"
    root.mkdir(parents=True)
    write_manifest(root, "0.3.5", dev_shape=False)
    provider._record_loaded_bundle_version(
        "khromalabs", "ataria", root
    )
    (root / "nexus.json").write_text("{not json", encoding="utf-8")
    for _ in range(2):
        provider._check_bundle_version_drift(make_cap_data())
    warns = warnings_since(cap)
    assert len(warns) == 1, warns
    assert "unreadable" in warns[0], warns[0]

    logging.getLogger(
        "ainara.framework.capabilities.nexus"
    ).removeHandler(cap)
    print("ok  unreadable manifest warns once")


def gate_bundle_dir_gone(tmp: pathlib.Path):
    """Uninstall/swap: directory vanished -> deliberately silent."""
    cap = LogCapture()
    logging.getLogger(
        "ainara.framework.capabilities.nexus"
    ).addHandler(cap)

    provider = make_provider()
    root = tmp / "gone_app"
    root.mkdir(parents=True)
    write_manifest(root, "0.3.5", dev_shape=False)
    provider._record_loaded_bundle_version(
        "khromalabs", "ataria", root
    )
    shutil.rmtree(root)
    provider._check_bundle_version_drift(make_cap_data())
    assert not warnings_since(cap), warnings_since(cap)

    logging.getLogger(
        "ainara.framework.capabilities.nexus"
    ).removeHandler(cap)
    print("ok  vanished bundle directory stays silent")


def main():
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="nexus_version_gate_"))
    try:
        gate_load_time_recording(tmp)
        gate_drift_warn_once(tmp)
        gate_manifest_missing(tmp)
        gate_manifest_unreadable(tmp)
        gate_bundle_dir_gone(tmp)
        print("\nALL GATES PASSED")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
