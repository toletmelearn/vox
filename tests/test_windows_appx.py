"""Microsoft Store (MSIX/UWP) app detection tests (vox/platform/windows_appx.py).
Regression coverage for a real gap: WhatsApp Desktop on this project's own
dev machine is Store-installed and has neither an `App Paths` registry entry
nor a Start Menu `.lnk` - confirmed live against the real registry - so
`find_installed_app`'s first two strategies could never find it. All
`winreg` access here is mocked; nothing touches the real registry."""
from __future__ import annotations

from types import SimpleNamespace

from vox.platform.windows import WindowsAdapter
from vox.platform.windows_appx import (
    _application_id,
    _matches_family,
    _split_family_name,
    find_appx_package,
)

_REAL_FAMILY_NAME = "5319275A.WhatsAppDesktop_cv1g1gvanyjgm"


def test_split_family_name_splits_on_last_underscore():
    assert _split_family_name(_REAL_FAMILY_NAME) == ("5319275A.WhatsAppDesktop", "cv1g1gvanyjgm")


def test_split_family_name_rejects_a_name_with_no_underscore():
    assert _split_family_name("nowaythisisreal") is None


def test_matches_family_ignores_version_and_architecture():
    """The whole point of matching on the family name instead of the full
    package name: a version bump (or an architecture change) must not break
    detection - confirmed live by simulating a hypothetical future WhatsApp
    version against the real family name on this machine."""
    name, publisher_id = _split_family_name(_REAL_FAMILY_NAME)
    assert _matches_family(
        "5319275A.WhatsAppDesktop_2.2635.100.0_x64__cv1g1gvanyjgm", name, publisher_id
    )
    assert _matches_family(
        "5319275A.WhatsAppDesktop_9.9999.999.0_x64__cv1g1gvanyjgm", name, publisher_id
    )
    assert _matches_family(
        "5319275A.WhatsAppDesktop_2.2635.100.0_arm64__cv1g1gvanyjgm", name, publisher_id
    )


def test_matches_family_rejects_a_different_app_with_the_same_publisher():
    name, publisher_id = _split_family_name(_REAL_FAMILY_NAME)
    assert not _matches_family(
        "5319275A.SomethingElseDesktop_2.2635.100.0_x64__cv1g1gvanyjgm", name, publisher_id
    )


def test_matches_family_rejects_the_same_name_with_a_different_publisher():
    name, publisher_id = _split_family_name(_REAL_FAMILY_NAME)
    assert not _matches_family(
        "5319275A.WhatsAppDesktop_2.2635.100.0_x64__differentpublisher", name, publisher_id
    )


_MANIFEST_XML = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10">'
    "<Applications>"
    '<Application Id="App" Executable="WhatsApp.Root.exe" />'
    "</Applications>"
    "</Package>"
)


def test_application_id_parses_a_real_shaped_manifest(tmp_path):
    manifest = tmp_path / "AppxManifest.xml"
    manifest.write_text(_MANIFEST_XML, encoding="utf-8")
    assert _application_id(manifest) == "App"


def test_application_id_returns_none_for_a_missing_manifest(tmp_path):
    assert _application_id(tmp_path / "AppxManifest.xml") is None


def test_application_id_returns_none_for_a_malformed_manifest(tmp_path):
    manifest = tmp_path / "AppxManifest.xml"
    manifest.write_text("<not><valid", encoding="utf-8")
    assert _application_id(manifest) is None


def _context_manager_mock(mocker, enter_value=None):
    mock = mocker.MagicMock()
    mock.__enter__.return_value = enter_value if enter_value is not None else mock
    mock.__exit__.return_value = False
    return mock


def test_find_appx_package_returns_shell_uri_on_match(tmp_path, mocker):
    manifest_dir = tmp_path
    (manifest_dir / "AppxManifest.xml").write_text(_MANIFEST_XML, encoding="utf-8")

    mock_winreg = mocker.patch("vox.platform.windows_appx.winreg")
    packages_key_cm = _context_manager_mock(mocker)
    package_key_cm = _context_manager_mock(mocker)
    mock_winreg.OpenKey.side_effect = [packages_key_cm, package_key_cm]
    mock_winreg.EnumKey.side_effect = [
        "5319275A.WhatsAppDesktop_2.2635.100.0_x64__cv1g1gvanyjgm",
        OSError("no more subkeys"),
    ]
    mock_winreg.QueryValueEx.return_value = (str(manifest_dir), 1)

    result = find_appx_package(_REAL_FAMILY_NAME)

    assert result == f"shell:AppsFolder\\{_REAL_FAMILY_NAME}!App"


def test_find_appx_package_returns_none_when_no_package_matches(mocker):
    mock_winreg = mocker.patch("vox.platform.windows_appx.winreg")
    packages_key_cm = _context_manager_mock(mocker)
    mock_winreg.OpenKey.return_value = packages_key_cm
    mock_winreg.EnumKey.side_effect = [
        "SomeOtherPublisher.OtherApp_1.0.0.0_x64__abcdef123",
        OSError("no more subkeys"),
    ]

    assert find_appx_package(_REAL_FAMILY_NAME) is None
    mock_winreg.QueryValueEx.assert_not_called()


def test_find_appx_package_returns_none_when_registry_key_is_missing(mocker):
    mock_winreg = mocker.patch("vox.platform.windows_appx.winreg")
    mock_winreg.OpenKey.side_effect = OSError("key not found")

    assert find_appx_package(_REAL_FAMILY_NAME) is None


def test_find_appx_package_returns_none_when_manifest_has_no_application_id(tmp_path, mocker):
    (tmp_path / "AppxManifest.xml").write_text(
        '<?xml version="1.0"?><Package xmlns="urn:x"><Applications /></Package>',
        encoding="utf-8",
    )

    mock_winreg = mocker.patch("vox.platform.windows_appx.winreg")
    packages_key_cm = _context_manager_mock(mocker)
    package_key_cm = _context_manager_mock(mocker)
    mock_winreg.OpenKey.side_effect = [packages_key_cm, package_key_cm]
    mock_winreg.EnumKey.side_effect = [
        "5319275A.WhatsAppDesktop_2.2635.100.0_x64__cv1g1gvanyjgm",
        OSError("no more subkeys"),
    ]
    mock_winreg.QueryValueEx.return_value = (str(tmp_path), 1)

    assert find_appx_package(_REAL_FAMILY_NAME) is None


def test_find_appx_package_returns_none_for_an_unparseable_family_name(mocker):
    mock_winreg = mocker.patch("vox.platform.windows_appx.winreg")
    assert find_appx_package("nowaythisisreal") is None
    mock_winreg.OpenKey.assert_not_called()


def test_adapter_find_installed_app_falls_through_to_appx_when_app_paths_and_start_menu_miss(
    mocker,
):
    """The exact real-world shape: a target with a (wrong or absent) exe-based
    id and no Start Menu shortcut, but a real Store package family name."""
    mocker.patch("vox.platform.windows._registry_app_path", return_value=None)
    mocker.patch("vox.platform.windows._find_start_menu_shortcut", return_value=None)
    mock_find_appx = mocker.patch(
        "vox.platform.windows.find_appx_package",
        return_value=f"shell:AppsFolder\\{_REAL_FAMILY_NAME}!App",
    )

    target = SimpleNamespace(
        windows_app_ids=["WhatsApp"],
        process_names=["WhatsApp.Root.exe"],
        windows_package_family_names=[_REAL_FAMILY_NAME],
    )

    adapter = WindowsAdapter()
    result = adapter.find_installed_app(target)

    assert result == f"shell:AppsFolder\\{_REAL_FAMILY_NAME}!App"
    mock_find_appx.assert_called_once_with(_REAL_FAMILY_NAME)


def test_adapter_find_installed_app_never_reaches_appx_once_app_paths_matches(mocker):
    mocker.patch("vox.platform.windows._registry_app_path", return_value=r"C:\Chrome\chrome.exe")
    mock_find_appx = mocker.patch("vox.platform.windows.find_appx_package")

    target = SimpleNamespace(
        windows_app_ids=["Chrome"],
        process_names=[],
        windows_package_family_names=["irrelevant_pub"],
    )

    adapter = WindowsAdapter()
    assert adapter.find_installed_app(target) == r"C:\Chrome\chrome.exe"
    mock_find_appx.assert_not_called()


def test_launch_routes_a_shell_appsfolder_uri_through_startfile(mocker):
    mock_startfile = mocker.patch("vox.platform.windows.os.startfile")
    mock_popen = mocker.patch("vox.platform.windows.subprocess.Popen")

    adapter = WindowsAdapter()
    uri = f"shell:AppsFolder\\{_REAL_FAMILY_NAME}!App"
    assert adapter.launch(uri) is True

    mock_startfile.assert_called_once_with(uri)
    mock_popen.assert_not_called()
