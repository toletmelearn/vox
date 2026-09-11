"""Pydantic settings loaded from config.yaml, falling back to built-in defaults
matching config.example.yaml. See spec Section 9."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class HotkeysConfig(BaseModel):
    voice: str = "ctrl+alt+space"
    text: str = "ctrl+alt+k"
    abort: str = "esc"


class PathsConfig(BaseModel):
    desktop: str = "~/Desktop"
    documents: str = "~/Documents"
    downloads: str = "~/Downloads"
    workdir: str = "~/vox-workspace"
    state_dir: str = "~/.vox"


class MemoryConfig(BaseModel):
    context_ttl_minutes: int = 15
    recent_turns: int = 6
    keep_artifact_copies: bool = True
    store_transcripts: bool = True
    store_message_bodies: bool = False
    transcript_retention_days: int = 90


class ResolverConfig(BaseModel):
    prefer_native_app: bool = True
    reuse_open_window: bool = True
    install_cache_ttl_hours: int = 24
    preferred_browser: str | None = None


class MessagingConfig(BaseModel):
    whatsapp_auto_send: bool = False
    contact_match_cutoff: float = 0.8


class SecurityConfig(BaseModel):
    jail_roots: list[str] = Field(
        default_factory=lambda: [
            "~/Desktop",
            "~/Documents",
            "~/Downloads",
            "~/vox-workspace",
        ]
    )
    max_download_mb: int = 500
    blocked_hosts: list[str] = Field(default_factory=list)
    confirm_destructive: bool = True
    undo_window_s: int = 4


class SttConfig(BaseModel):
    model: Literal["base", "small", "medium"] = "small"
    device: Literal["cpu", "cuda"] = "cpu"
    compute_type: str = "int8"
    language: str | None = None
    hindi_aliases: bool = True
    min_confidence: float = 0.55


class TtsConfig(BaseModel):
    enabled: bool = True
    voice: str = "en_US-amy-medium"
    rate: float = 1.0


class Tier1Config(BaseModel):
    enabled: bool = True
    provider: str = "ollama"
    model: str = "qwen3:8b"
    thinking: bool = False
    timeout_s: int = 12
    min_confidence: float = 0.6


class Tier2Config(BaseModel):
    enabled: bool = False
    provider: str = "anthropic"
    model: str = "claude-haiku-4-5-20251001"


class LoggingConfig(BaseModel):
    level: str = "INFO"
    file: str = "~/.vox/vox.log"


class Settings(BaseModel):
    hotkeys: HotkeysConfig = Field(default_factory=HotkeysConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    resolver: ResolverConfig = Field(default_factory=ResolverConfig)
    messaging: MessagingConfig = Field(default_factory=MessagingConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    stt: SttConfig = Field(default_factory=SttConfig)
    tts: TtsConfig = Field(default_factory=TtsConfig)
    tier1: Tier1Config = Field(default_factory=Tier1Config)
    tier2: Tier2Config = Field(default_factory=Tier2Config)
    apps: dict[str, str] = Field(
        default_factory=lambda: {
            "chrome": "C:/Program Files/Google/Chrome/Application/chrome.exe",
            "edge": "msedge.exe",
            "firefox": "firefox.exe",
            "notepad": "notepad.exe",
            "explorer": "explorer.exe",
            "calculator": "calc.exe",
            "word": "winword.exe",
            "excel": "excel.exe",
            "vscode": "code.exe",
            "terminal": "wt.exe",
        }
    )
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


def save_settings(settings: Settings, path: Path | None = None) -> None:
    """Persist settings back to config.yaml (spec Section 6E: a hotkey
    rebind must survive a restart, not just live in the in-memory Settings
    the rest of the process shares via get_settings())."""
    if path is None:
        path = Path("config.yaml")
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(settings.model_dump(), f, sort_keys=False)


def load_settings(path: Path | None = None) -> Settings:
    """Load settings from a YAML file. Missing file -> defaults. Never raises
    on a missing file; a malformed one still raises so a broken config.yaml
    is loud rather than silently ignored."""
    if path is None:
        path = Path("config.yaml")
    if not path.exists():
        return Settings()
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return Settings.model_validate(raw)


_settings: Settings | None = None


def get_settings() -> Settings:
    """Process-wide cached settings. Call set_settings() in tests to override."""
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def set_settings(settings: Settings) -> None:
    """Test/startup hook to override the cached settings."""
    global _settings
    _settings = settings


def reset_settings() -> None:
    """Test teardown hook: forget the cached settings."""
    global _settings
    _settings = None
