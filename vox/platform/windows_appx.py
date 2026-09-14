"""Microsoft Store (MSIX/UWP) app detection for `WindowsAdapter.find_installed_app`
(spec Section 6A Step 2). Split out of windows.py rather than grown inline -
that module is already over CLAUDE.md's 300-line guideline, and this is
genuinely separate logic from the App Paths/Start Menu `.lnk` strategies it
sits alongside, with no overlap between them.

Confirmed live against this dev machine's real WhatsApp Desktop install
(Store-installed, not a classic Win32 setup): it has no `App Paths` registry
entry and no Start Menu `.lnk` file, so neither existing strategy can ever
find it. The reliable, version-independent lookup is:

1. Enumerate `...\\AppModel\\Repository\\Packages` and match a subkey against
   the configured package family name (`Name_PublisherId`) - not the full
   package name, which embeds a version (`Name_Version_Arch__PublisherId`)
   that changes on every update and would silently stop matching the moment
   the app updates itself.
2. Read that subkey's `PackageRootFolder` and parse its `AppxManifest.xml`
   for the application id.
3. Build `shell:AppsFolder\\<family>!<id>` - the shell-namespace path that
   launches a packaged app directly. The real exe lives in an ACL-locked
   package directory and can't be `Popen`'d the way a normal install's exe
   can.
"""
from __future__ import annotations

import logging
import winreg
import xml.etree.ElementTree as ET
from pathlib import Path

logger = logging.getLogger("vox.platform.windows_appx")

_PACKAGES_KEY = (
    r"Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel\Repository\Packages"
)


def _split_family_name(family_name: str) -> tuple[str, str] | None:
    """`Name_PublisherId` -> (name, publisher_id). No underscore means this
    isn't a real family name; treat it as unmatchable rather than raising."""
    if "_" not in family_name:
        return None
    name, _, publisher_id = family_name.rpartition("_")
    return name, publisher_id


def _matches_family(full_package_name: str, name: str, publisher_id: str) -> bool:
    """A full package name is `Name_Version_Architecture_ResourceId_PublisherId`
    - the middle segments vary release to release and aren't needed here.
    Matching on the fixed prefix and suffix stays correct across a version
    bump; matching the full name directly would not."""
    return full_package_name.startswith(f"{name}_") and full_package_name.endswith(
        f"__{publisher_id}"
    )


def _application_id(manifest_path: Path) -> str | None:
    try:
        root = ET.parse(manifest_path).getroot()
    except (OSError, ET.ParseError):
        return None
    for element in root.iter():
        if element.tag == "Application" or element.tag.endswith("}Application"):
            app_id = element.get("Id")
            if app_id:
                return app_id
    return None


def find_appx_package(family_name: str) -> str | None:
    """Returns a `shell:AppsFolder\\...` launch string for an installed
    package matching `family_name`, or None if nothing matches. Never
    raises - a missing/malformed registry key or manifest just means "not
    found", the same policy as the strategies it sits alongside."""
    split = _split_family_name(family_name)
    if split is None:
        return None
    name, publisher_id = split

    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, _PACKAGES_KEY) as packages_key:
            index = 0
            while True:
                try:
                    full_package_name = winreg.EnumKey(packages_key, index)
                except OSError:
                    break
                index += 1
                if not _matches_family(full_package_name, name, publisher_id):
                    continue
                try:
                    with winreg.OpenKey(packages_key, full_package_name) as package_key:
                        root_folder, _ = winreg.QueryValueEx(package_key, "PackageRootFolder")
                except OSError:
                    continue
                app_id = _application_id(Path(root_folder) / "AppxManifest.xml")
                if app_id:
                    return f"shell:AppsFolder\\{family_name}!{app_id}"
    except OSError:
        logger.warning(
            "find_appx_package(%r): registry lookup failed", family_name, exc_info=True
        )
        return None
    return None
