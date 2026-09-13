"""resolver/targets.py: catalogue loading and fuzzy target matching (spec
Section 6A). No filesystem/network beyond reading a YAML fixture."""
from __future__ import annotations

from pathlib import Path

import pytest

from vox.resolver.targets import Target, find_target, load_targets

_YOUTUBE = Target(
    key="youtube",
    display="YouTube",
    aliases=["you tube", "yt", "utube"],
    deep_link=None,
    web_url="https://www.youtube.com",
    web_search_url="https://www.youtube.com/results?search_query={q}",
    window_title_match=["YouTube"],
    windows_app_ids=[],
    process_names=[],
    prefer="web",
)
_WHATSAPP = Target(
    key="whatsapp",
    display="WhatsApp",
    aliases=["whats up", "whatsup"],
    deep_link="whatsapp://",
    web_url="https://web.whatsapp.com",
    web_search_url=None,
    window_title_match=["WhatsApp"],
    windows_app_ids=["WhatsApp"],
    process_names=["WhatsApp.exe"],
    prefer="app",
)
_CATALOGUE = {"youtube": _YOUTUBE, "whatsapp": _WHATSAPP}


def test_load_targets_missing_file_returns_empty_catalogue(tmp_path):
    assert load_targets(tmp_path / "nope.yaml") == {}


def test_load_targets_reads_the_real_shipped_catalogue():
    catalogue = load_targets(Path("targets.yaml"))
    for key in ("youtube", "whatsapp", "gmail", "google_drive", "spotify", "telegram", "chatgpt", "maps", "github"):
        assert key in catalogue, f"targets.yaml is missing {key!r}"


def test_find_target_exact_key():
    assert find_target("youtube", _CATALOGUE).target is _YOUTUBE


def test_find_target_exact_alias_case_insensitive():
    assert find_target("Whats Up", _CATALOGUE).target is _WHATSAPP


@pytest.mark.parametrize("query", ["you tube", "utube", "whats up"])
def test_find_target_fuzzy_matches_whisper_mishears(query):
    match = find_target(query, _CATALOGUE)
    assert match.target is not None, query


def test_find_target_unknown_service_returns_clarification_not_a_guess():
    match = find_target("flipkart", _CATALOGUE)
    assert match.target is None
    assert match.suggestions == [] or len(match.suggestions) <= 2
