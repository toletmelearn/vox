"""compose_whatsapp_message (spec Section 6B): draft-only, never sends —
CLAUDE.md invariant 6. No real window enumeration/launch — get_adapter is
mocked throughout."""
from __future__ import annotations

from datetime import datetime, timezone

from vox.resolver.targets import Target, set_target_catalogue
from vox.tools.messaging import compose_whatsapp_message

_WHATSAPP = Target(
    key="whatsapp",
    display="WhatsApp",
    aliases=[],
    deep_link="whatsapp://",
    web_url="https://web.whatsapp.com",
    web_search_url=None,
    window_title_match=["WhatsApp"],
    windows_app_ids=["WhatsApp"],
    process_names=["WhatsApp.exe"],
    prefer="app",
)


def _patch_adapter(mocker, **overrides):
    adapter = mocker.MagicMock()
    adapter.capabilities.return_value = {
        "list_windows",
        "focus_window",
        "launch",
        "running_processes",
        "find_installed_app",
        "open_default_browser",
        "running_browsers",
    }
    for name, value in overrides.items():
        getattr(adapter, name).return_value = value
    mocker.patch("vox.resolver.resolve.get_adapter", return_value=adapter)
    mocker.patch("vox.resolver.detect.get_adapter", return_value=adapter)
    return adapter


def test_compose_whatsapp_message_opens_prefilled_chat_and_asks_for_enter(
    jail_settings, alias_store, mocker, memory_store
):
    set_target_catalogue({"whatsapp": _WHATSAPP})
    alias_store.contacts.set("subodh", {"phone": "+919876543210", "display": "Subodh Kumar"})
    adapter = _patch_adapter(mocker, running_processes={"WhatsApp.exe"}, launch=True)

    result = compose_whatsapp_message(contact="subodh", message="I'll be late")

    assert result.ok
    assert "press Enter" in result.speech.lower() or "press enter" in result.speech.lower()
    adapter.launch.assert_called_once_with("whatsapp://send?phone=919876543210&text=I%27ll%20be%20late")


def test_compose_whatsapp_message_fuzzy_contact_states_resolved_name(jail_settings, alias_store, mocker):
    set_target_catalogue({"whatsapp": _WHATSAPP})
    alias_store.contacts.set("subodh", {"phone": "+919876543210", "display": "Subodh Kumar"})
    _patch_adapter(mocker, running_processes=set(), find_installed_app=None, open_default_browser=True)

    result = compose_whatsapp_message(contact="subod", message="hi")  # one letter short

    assert result.ok
    assert "Subodh Kumar" in result.speech


def test_compose_whatsapp_message_unknown_contact_clarifies_and_opens_nothing(jail_settings, alias_store, mocker):
    set_target_catalogue({"whatsapp": _WHATSAPP})
    alias_store.contacts.set("subodh", {"phone": "+919876543210", "display": "Subodh Kumar"})
    alias_store.contacts.set("amma", {"phone": "+919812345678", "display": "Mummy"})
    adapter = _patch_adapter(mocker)

    result = compose_whatsapp_message(contact="rajesh", message="are you free?")

    assert not result.ok
    assert "Subodh Kumar" in result.speech
    assert "Mummy" in result.speech
    adapter.launch.assert_not_called()
    adapter.open_default_browser.assert_not_called()


def test_compose_whatsapp_message_never_instantiates_pynput_keyboard_controller(
    jail_settings, alias_store, mocker, memory_store
):
    """Acceptance: 'add a test that fails if pynput.keyboard.Controller is
    instantiated anywhere in the messaging path.'"""
    import pynput.keyboard

    def _boom(*args, **kwargs):
        raise AssertionError("pynput.keyboard.Controller must never be used in the messaging path")

    mocker.patch.object(pynput.keyboard, "Controller", side_effect=_boom)

    set_target_catalogue({"whatsapp": _WHATSAPP})
    alias_store.contacts.set("subodh", {"phone": "+919876543210", "display": "Subodh Kumar"})
    _patch_adapter(mocker, running_processes={"WhatsApp.exe"}, launch=True)

    result = compose_whatsapp_message(contact="subodh", message="I'll be late")

    assert result.ok  # would have raised AssertionError above if it tried to synthesise a keypress


def test_compose_whatsapp_message_body_redacted_from_memory_unless_configured(
    jail_settings, alias_store, mocker, memory_store
):
    """Spec Section 6C: store the contact key and message length, not the
    body, unless config.memory.store_message_bodies is explicitly true."""
    from vox.memory.tracking import record_execution
    from vox.router.base import ToolCall

    set_target_catalogue({"whatsapp": _WHATSAPP})
    alias_store.contacts.set("subodh", {"phone": "+919876543210", "display": "Subodh Kumar"})
    jail_settings.memory.store_transcripts = False
    jail_settings.memory.store_message_bodies = False

    call = ToolCall(name="compose_whatsapp_message", args={"contact": "subodh", "message": "a secret plan"})
    from vox.tools.registry import ToolResult

    record_execution(
        call,
        transcript="message subodh saying a secret plan",
        outcome="ok",
        result=ToolResult(ok=True, speech="Message ready for Subodh Kumar. Press Enter to send."),
    )

    rows = memory_store.activity_between(
        datetime(2000, 1, 1, tzinfo=timezone.utc),
        datetime(2100, 1, 1, tzinfo=timezone.utc),
    )
    assert len(rows) == 1
    stored = memory_store._conn.execute("SELECT args_json FROM activity WHERE id = ?", (rows[0].id,)).fetchone()[0]
    assert "a secret plan" not in stored
    assert "13 chars" in stored  # len("a secret plan") == 13
