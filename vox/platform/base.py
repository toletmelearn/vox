"""PlatformAdapter protocol. All OS-specific code must live behind this
interface — see spec Section 3A.5 and CLAUDE.md invariant 4.

Three methods extend the spec's literal listing (os_build, cpu_supports_avx2,
open_path). They are needed so the startup self-check and the file-opening
tool never need to branch on sys.platform outside this package. See
DECISIONS.md."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


class UnsupportedCapability(Exception):
    """Raised when a caller invokes an adapter method the current platform
    (or the test null adapter) does not support."""


@dataclass(frozen=True)
class WindowInfo:
    handle: int | str
    title: str
    process_name: str = ""


class PlatformAdapter(Protocol):
    name: str  # "windows" | "linux" | "darwin" | "null"

    def list_windows(self) -> list[WindowInfo]: ...

    def focus_window(self, handle: int | str) -> bool: ...

    def find_installed_app(self, target: Any) -> str | None: ...

    def launch(self, exe_or_uri: str, args: list[str] | None = None) -> bool: ...

    def running_processes(self) -> set[str]: ...

    def open_default_browser(self, url: str) -> bool: ...

    def running_browsers(self) -> list[str]: ...

    def set_volume(self, level: int) -> bool: ...

    def lock_screen(self) -> bool: ...

    def screenshot(self, dest: Path) -> bool: ...

    def notify(self, title: str, body: str) -> None: ...

    def open_path(self, path: Path) -> bool: ...

    def convert_docx_to_pdf(self, src: Path, dest_dir: Path) -> bool: ...

    def verify_hotkey_available(self, chord: str) -> bool: ...

    def os_build(self) -> str: ...

    def cpu_supports_avx2(self) -> bool: ...

    def capabilities(self) -> set[str]: ...
