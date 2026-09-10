from __future__ import annotations

import os
from pathlib import Path

import pytest

from vox import config as config_module
from vox import platform as platform_module
from vox.security import audit as audit_module

if os.environ.get("VOX_FORCE_NULL_ADAPTER") == "1":
    from vox.platform.null import NullAdapter

    platform_module.set_adapter(NullAdapter())


@pytest.fixture
def jail_settings(tmp_path: Path) -> config_module.Settings:
    """Settings whose jail roots are all under tmp_path. Tests must never
    touch the real Desktop/Documents/Downloads (spec Section 13)."""
    desktop = tmp_path / "Desktop"
    documents = tmp_path / "Documents"
    downloads = tmp_path / "Downloads"
    workdir = tmp_path / "workdir"
    for d in (desktop, documents, downloads, workdir):
        d.mkdir()

    settings = config_module.Settings(
        paths=config_module.PathsConfig(
            desktop=str(desktop),
            documents=str(documents),
            downloads=str(downloads),
            workdir=str(workdir),
            state_dir=str(tmp_path / "state"),
        ),
        security=config_module.SecurityConfig(
            jail_roots=[str(desktop), str(documents), str(downloads), str(workdir)]
        ),
    )
    config_module.set_settings(settings)
    yield settings
    config_module.reset_settings()


@pytest.fixture
def audit_log(jail_settings: config_module.Settings) -> audit_module.AuditLog:
    log = audit_module.AuditLog(Path(jail_settings.paths.state_dir).expanduser() / "audit.db")
    audit_module.set_audit_log(log)
    yield log
    log.close()
    audit_module.reset_audit_log()


@pytest.fixture
def null_adapter() -> None:
    from vox.platform.null import NullAdapter

    platform_module.set_adapter(NullAdapter())
    yield
    platform_module.reset_adapter()
