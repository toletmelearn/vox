"""tray.py tests: only the pure, display-independent icon-image generator is
covered here. TrayApp itself opens a real system tray icon and native
message loop, which spec Section 13 tests must never do."""
from __future__ import annotations

from vox.ui.tray import make_icon_image


def test_make_icon_image_returns_correct_size():
    image = make_icon_image("idle")
    assert image.size == (64, 64)


def test_make_icon_image_states_are_visually_distinct():
    colors = {state: make_icon_image(state).getpixel((32, 32)) for state in (
        "idle", "listening", "thinking", "error"
    )}
    assert len(set(colors.values())) == 4  # every state gets its own color


def test_make_icon_image_unknown_state_falls_back_to_idle():
    assert make_icon_image("bogus").getpixel((32, 32)) == make_icon_image("idle").getpixel((32, 32))
