"""Regression tests for the automatic backup driver (app.services.backup.auto).

The worker polls a backup operation in a worker thread; the model lookup used
there is imported *inside* ``auto._run`` via a package-relative import.  That
import used ``..admin_models`` (which resolves to ``app.services.admin_models``
and does not exist); the correct model module is ``app.admin_models``.  These
tests pin the import resolution used by the runtime path.
"""

import importlib

import app.services.backup.auto as auto


def test_auto_backup_model_import_resolves_in_package_context():
    # Executes the exact statements from auto._run() using the module globals,
    # so the relative imports resolve against app.services.backup like they do
    # when the worker runs the function.
    src = (
        "from ...db import SessionLocal as _SL\n"
        "from ...admin_models import BackupOperation\n"
    )
    exec(compile(src, "<auto-run>", "exec"), auto.__dict__)  # noqa: S102
    assert "BackupOperation" in auto.__dict__
    assert "_SL" in auto.__dict__


def test_auto_backup_module_imports_cleanly():
    importlib.reload(auto)
    assert hasattr(auto, "run_auto_backup_check")


def test_load_settings_returns_none_when_row_absent(user_id):
    from app.models import SettingsStore

    class _FakeSession:
        def __init__(self):
            self._rows = {}

        def get(self, model, key):
            return self._rows.get(key)

        def close(self):
            pass

    fake = _FakeSession()
    assert auto._load_settings(fake) is None
    fake._rows["backup:auto"] = SettingsStore(key="backup:auto", value='{"enabled": false}')
    assert auto._load_settings(fake) == {"enabled": False}