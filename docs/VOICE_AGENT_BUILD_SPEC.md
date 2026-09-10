# Local Voice Agent — Build Specification

**Project codename:** `vox`
**Audience:** Claude Code (this document is the complete brief — build from it without asking clarifying questions)
**Owner:** Amar JS Saxena
**Target OS:** Windows 10 22H2 and Windows 11 (tier 1 support); Linux/X11 (tier 2 support). See Section 3A for the full matrix and degradation rules.
**Language:** Python 3.11+

---

## 0. How to use this document

Read this entire file before writing any code.

Build in the phase order given in Section 10. **Do not skip ahead.** Each phase has explicit acceptance criteria. After finishing a phase, run its acceptance test, print the result, and stop for review before starting the next phase.

If something in this spec is genuinely ambiguous, make the most conservative choice (the one that does less, fails louder, and touches fewer files), write the assumption into `DECISIONS.md`, and continue. Do not stop to ask.

**Never** invent a dependency, API, or model name that is not listed in Section 3. If a listed package is unavailable at install time, stop and report it rather than substituting.

---

## 1. What we are building

A local daemon that listens to a voice command, decides what the user meant, and executes it on the computer through **narrow, typed Python functions** — not by simulating mouse clicks.

Example commands that must work in v1:

| Spoken | Result |
| --- | --- |
| "search for Laravel queue tutorial" | Default browser opens the search |
| "play Kishore Kumar songs on YouTube" | Browser opens the top YouTube result |
| "make a folder called Physics Notes on desktop" | Folder created |
| "make a text file called todo in Physics Notes" | Empty `.txt` created |
| "make a Word file about the water cycle" | `.docx` generated with headings and paragraphs |
| "make that a PDF" | Previous file converted to PDF |
| "open Chrome" / "open Notepad" | App launched |
| "download this file <url>" | Downloaded to the downloads folder |
| "what's the time" | Spoken answer |
| "stop" / "cancel" | Aborts the running action |
| "go to YouTube and play Munni Badnaam Hui" | Resolver finds the best way to reach YouTube (already-open tab → installed app → browser), then opens the video |
| "open WhatsApp and message Subodh saying I'll be late" | Resolver reaches WhatsApp (desktop app → open browser tab → web.whatsapp.com), opens Subodh's chat with the text pre-filled, and **stops for the user to press Enter** |
| "what did I do yesterday" | Reads back recent activity from the memory store |
| "make that a PDF" | Uses remembered last artifact |

### Explicit non-goals for v1

- No screen-reading / vision agent. No `pyautogui` pixel clicking. (Phase 6 only, optional.)
- No wake word. Push-to-talk only.
- No cloud speech-to-text.
- No generic `run_shell(command)` tool. **Ever.** This is a hard rule, see Section 8.
- No multi-user support, no network listener, no web server.

---

## 2. Architecture

```
┌────────────────────────────────────────────────────────┐
│ TRIGGER   global hotkey (Ctrl+Alt+Space), hold to talk  │
└───────────────┬────────────────────────────────────────┘
                ▼
┌────────────────────────────────────────────────────────┐
│ AUDIO     sounddevice capture 16kHz mono                │
│           Silero VAD trims silence                      │
└───────────────┬────────────────────────────────────────┘
                ▼
┌────────────────────────────────────────────────────────┐
│ STT       faster-whisper, local, int8                   │
│           returns text + avg_logprob confidence         │
└───────────────┬────────────────────────────────────────┘
                ▼
┌────────────────────────────────────────────────────────┐
│ ROUTER    Tier 0  regex grammar      (instant, offline) │
│           Tier 1  Ollama tool-calling (local LLM)       │
│           Tier 2  cloud API           (opt-in, off dflt)│
│           → produces a ToolCall(name, args, confidence)  │
└───────────────┬────────────────────────────────────────┘
                ▼
┌────────────────────────────────────────────────────────┐
│ GUARD     risk tier check → confirm dialog if needed    │
│           path jail check → reject out-of-jail paths    │
│           audit log write (always, before execution)    │
└───────────────┬────────────────────────────────────────┘
                ▼
┌────────────────────────────────────────────────────────┐
│ EXECUTE   registered tool function, typed args          │
└───────────────┬────────────────────────────────────────┘
                ▼
┌────────────────────────────────────────────────────────┐
│ FEEDBACK  Piper TTS + tray notification + audit result  │
└────────────────────────────────────────────────────────┘
```

**The single most important architectural rule:** every capability is a small, typed, individually-validated Python function registered in a tool registry. The LLM never produces code, shell strings, or file paths that bypass validation. It only chooses a tool name and fills typed arguments.

---

## 3. Dependency list (pinned intent, not exact versions)

Install with `uv` if available, else `pip` into a venv.

**Core**
```
sounddevice          # mic capture
numpy
faster-whisper       # STT (CTranslate2 Whisper)
silero-vad           # voice activity detection (torch hub or pip pkg)
piper-tts            # local TTS
pynput               # global hotkey
pydantic>=2          # tool arg schemas + validation
pyyaml               # config
rich                 # console output during dev
```

**Tools layer**
```
python-docx          # .docx generation
reportlab            # .pdf generation
requests             # downloads
yt-dlp               # YouTube search/resolve (do NOT download video by default)
send2trash           # safe deletes
psutil               # process checks
```

**Windows only**
```
pywin32              # COM automation, app launching
pywinauto            # accessibility-tree automation (Phase 6 only)
pystray + pillow     # tray icon
```

**Tier 1 brain**
```
ollama               # python client
```
Model: `qwen3:8b` (Apache 2.0, native tool-calling support in Ollama). Verify with `ollama show qwen3:8b` that `tools` appears under Capabilities before relying on it. If the machine has under 16 GB RAM, the router must fall back to Tier 0 only and log a warning at startup.

**Tier 2 (optional, disabled by default)**
```
anthropic            # only used if config.tier2.enabled = true
```

**Dev**
```
pytest
pytest-mock
```

---

## 3A. Platform support matrix

### Supported

| Platform | Status | Notes |
| --- | --- | --- |
| Windows 11 | Full | Reference platform |
| Windows 10 **22H2** | Full | Everything works. This is the floor for Tier 1. |
| Windows 10 pre-22H2 (1809–21H2) | Degraded | Ollama is unsupported below 22H2 → **no Tier 1**. Tier 0 works fully; Tier 2 cloud works if enabled. |
| Linux / X11 | Full | Window enumeration via `wmctrl` or `xdotool` |
| Linux / **Wayland** | Degraded | See below — resolver Step 1 is unavailable |
| macOS | Not in v1 | Port is one adapter file. See Section 3A.4. |
| Windows 8.1 and older | **Unsupported** | Current CPython releases no longer target these. Do not attempt. |

### 3A.1 Windows 10 — what actually differs

These work **identically** on Windows 10 22H2 and Windows 11; write one code path, no branching:

- `win32gui.EnumWindows`, `GetWindowText`, `SetForegroundWindow`, `ShowWindow` — Win32 APIs, unchanged for decades
- Registry `App Paths` lookup (`HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths`)
- Start Menu shortcut scan (`%ProgramData%` and `%AppData%` `\Microsoft\Windows\Start Menu\Programs`)
- Protocol handler detection (`HKCR\<scheme>\shell\open\command`) — this is how `whatsapp://` and `youtube://` are found
- Word COM automation via `pywin32`
- `pystray` tray icon and balloon notifications
- `pycaw` volume control
- `sounddevice` / WASAPI capture

These need attention:

| Item | Windows 11 | Windows 10 22H2 | Action |
| --- | --- | --- | --- |
| Ollama (Tier 1) | Works | Works (22H2 is the documented minimum) | Startup check must read the OS build, not just try to connect |
| WebView2 runtime | Preinstalled | May be absent | Affects WhatsApp Desktop. Resolver ladder already falls through to web — no code change needed |
| Toast notifications | WinRT | WinRT available 1809+, but flakier | **Use `pystray` balloon notifications only.** Do not add a WinRT toast dependency. One code path, both OSes. |
| Default terminal / console encoding | UTF-8 | Legacy codepage common | Set `PYTHONUTF8=1` in the launcher. Log files must be opened `encoding="utf-8"` explicitly. |

**Do not gate features on `platform.release()` returning `"11"`.** Windows 10 and 11 both report build numbers; read `sys.getwindowsversion().build` and compare (Windows 11 is build ≥ 22000; Windows 10 22H2 is build 19045). Add this to `platform/windows.py` as `windows_build()` and use it in the startup self-check only.

### 3A.2 Hardware floor — matters more than the OS version

Many Windows 10 machines are old hardware. Check these at startup and report them in the self-check table:

- **AVX2 support** — `faster-whisper` (CTranslate2) is dramatically slower without it. Detect via `cpuinfo` or a `platform`-level probe. If absent, force `stt.model: "base"` and warn that transcription will be slow.
- **RAM** — under 16 GB, disable Tier 1 and say so once at startup.
- **Disk** — Whisper `small` int8 plus a Piper voice plus `qwen3:8b` is roughly 6 GB. Fail the self-check if under 10 GB free.

These checks are the honest answer to "will it run on my machine" — far more predictive than the Windows version number.

### 3A.3 Linux — the Wayland problem

On X11, window enumeration and focus work via `wmctrl` / `xdotool`. On Wayland they **do not**, by design: the protocol deliberately prevents an application from listing or raising other applications' windows. This is a security feature, not a bug to route around.

Consequences for the resolver (Section 6A):

- Step 1 (focus an already-open window) is **unavailable under Wayland**. Detect the session type via `XDG_SESSION_TYPE` at startup and skip Step 1 entirely.
- Do not attempt `ydotool`, uinput injection, or a portal workaround in v1. Log the limitation once and move on.
- Under Wayland the ladder becomes: installed app → running browser → default browser. Reusing an open tab is lost. Say so in the README rather than pretending it works.

### 3A.4 macOS — what a port would take

Out of scope for v1, but build so it isn't a rewrite. The macOS-specific work is confined to one adapter file:

- Window enumeration/focus: Quartz `CGWindowListCopyWindowInfo` + AppleScript `activate`, and it requires the user to grant **Accessibility** permission in System Settings
- App detection: scan `/Applications`, or `mdfind "kMDItemKind == 'Application'"`, matched on bundle ID
- Launch: `open -b <bundle-id>` or `open -a <name>`
- Microphone requires a TCC permission prompt on first capture
- Word COM → AppleScript, or LibreOffice which behaves the same as elsewhere

Whisper, Piper, Ollama, python-docx and reportlab are all cross-platform already.

### 3A.5 Platform adapter — required design

**All OS-specific code lives behind one interface.** No `if sys.platform == "win32"` anywhere outside `vox/platform/`. This is what makes Windows 10 quirks, Wayland, and a future macOS port cheap instead of a rewrite.

```python
# vox/platform/base.py
class PlatformAdapter(Protocol):
    name: str                                    # "windows" | "linux" | "darwin"

    def list_windows(self) -> list[WindowInfo]: ...
    def focus_window(self, handle: int | str) -> bool: ...
    def find_installed_app(self, target: Target) -> str | None: ...
    def launch(self, exe_or_uri: str, args: list[str] = []) -> bool: ...
    def running_processes(self) -> set[str]: ...
    def open_default_browser(self, url: str) -> bool: ...
    def running_browsers(self) -> list[str]: ...
    def set_volume(self, level: int) -> bool: ...
    def lock_screen(self) -> bool: ...
    def screenshot(self, dest: Path) -> bool: ...
    def notify(self, title: str, body: str) -> None: ...
    def capabilities(self) -> set[str]: ...      # e.g. {"focus_window", "volume", "lock"}
```

Files: `platform/__init__.py` (factory returning the right adapter), `platform/base.py`, `platform/windows.py`, `platform/linux.py`, `platform/null.py` (raises `UnsupportedCapability` for everything — used in tests).

**Capability-based degradation, not version checks.** Every caller asks `adapter.capabilities()` before using a feature. If `"focus_window"` is absent (Wayland), the resolver skips Step 1. If `"volume"` is absent, `set_volume` returns `ToolResult(ok=False, speech="Volume control isn't available on this system.")`. The agent never crashes because of a missing platform feature, and never silently does nothing.

Add to the startup self-check table one row per capability, showing present/absent. This is the first thing the user sees, and it tells them exactly what their machine can and cannot do.

---

## 4. Directory structure

Create exactly this. Do not add top-level directories.

```
vox/
├── pyproject.toml
├── README.md
├── DECISIONS.md              # you append assumptions here
├── config.example.yaml
├── config.yaml               # gitignored
├── .gitignore
├── run.py                    # entrypoint: python run.py
├── vox/
│   ├── __init__.py
│   ├── app.py                # wires everything, owns the main loop
│   ├── config.py             # pydantic Settings loaded from config.yaml
│   ├── logging_setup.py
│   ├── audio/
│   │   ├── __init__.py
│   │   ├── capture.py        # hotkey-gated mic capture
│   │   ├── vad.py            # Silero wrapper
│   │   └── tts.py            # Piper wrapper, speak(text)
│   ├── stt/
│   │   ├── __init__.py
│   │   └── whisper.py        # transcribe(pcm) -> Transcript
│   ├── router/
│   │   ├── __init__.py
│   │   ├── base.py           # ToolCall, RouteResult dataclasses
│   │   ├── tier0_grammar.py  # regex rules
│   │   ├── tier1_local.py    # Ollama tool-calling
│   │   └── tier2_cloud.py    # Anthropic API, off by default
│   ├── platform/
│   │   ├── __init__.py       # factory: returns the adapter for this OS
│   │   ├── base.py           # PlatformAdapter protocol, WindowInfo, capabilities
│   │   ├── windows.py        # win32 + registry + Start Menu + pycaw
│   │   ├── linux.py          # X11 via wmctrl/xdotool; Wayland = reduced capabilities
│   │   └── null.py           # raises UnsupportedCapability; used in tests
│   ├── resolver/
│   │   ├── __init__.py
│   │   ├── targets.py        # Target catalogue (youtube, whatsapp, ...)
│   │   ├── detect.py         # is it installed? is it already open?
│   │   └── resolve.py        # the 4-step resolution ladder
│   ├── memory/
│   │   ├── __init__.py
│   │   ├── store.py          # SQLite: activity, artifacts, sessions
│   │   ├── context.py        # short-term: last artifact, last target, last N turns
│   │   ├── aliases.py        # user-editable JSON: contacts, app names, shortcuts
│   │   └── recall.py         # natural-language queries over activity
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── registry.py       # @tool decorator, schema export
│   │   ├── files.py
│   │   ├── documents.py      # docx + pdf
│   │   ├── web.py            # search, youtube, download
│   │   ├── apps.py           # open_app
│   │   ├── targets.py        # open_target, play_on_target
│   │   ├── messaging.py      # compose_whatsapp_message (draft, never auto-send)
│   │   ├── memory_tools.py   # recall_activity, forget_activity
│   │   └── system.py         # time, volume, screenshot
│   ├── security/
│   │   ├── __init__.py
│   │   ├── jail.py           # path allowlist resolution
│   │   ├── confirm.py        # risk-tier confirmation UI
│   │   └── audit.py          # SQLite audit log
│   └── ui/
│       ├── __init__.py
│       ├── tray.py           # pystray icon + status
│       ├── command_bar.py    # Tkinter text-input bar
│       └── settings.py       # settings window incl. hotkey capture widget
└── tests/
    ├── test_jail.py
    ├── test_grammar.py
    ├── test_registry.py
    └── test_tools_files.py
```

---

## 5. Core contracts

Define these first, in `vox/router/base.py` and `vox/tools/registry.py`. Everything else depends on them.

```python
# vox/router/base.py
from dataclasses import dataclass, field
from typing import Any, Literal

@dataclass
class Transcript:
    text: str
    confidence: float          # 0..1, derived from whisper avg_logprob
    language: str
    duration_s: float

@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]

@dataclass
class RouteResult:
    call: ToolCall | None
    confidence: float
    tier: Literal["tier0", "tier1", "tier2", "none"]
    clarification: str | None = None   # set when the router needs to ask back
```

```python
# vox/tools/registry.py
Risk = Literal["safe", "medium", "destructive"]

class ToolResult(BaseModel):
    ok: bool
    speech: str            # short sentence to speak aloud, <= 15 words
    detail: str = ""       # longer text for the log / tray tooltip
    artifact_path: str | None = None   # file created, if any

def tool(*, name: str, risk: Risk, description: str):
    """Decorator. Registers fn in REGISTRY with a pydantic-derived JSON schema
    built from the function's type hints. Enforces:
      - every parameter is annotated
      - every parameter type is str | int | float | bool | list[str] | Literal[...]
      - the return type is ToolResult
    Raises at import time if violated."""
```

The registry must expose `REGISTRY.as_ollama_tools()` returning the JSON-schema tool list for the Ollama `tools=` parameter, generated automatically from the signatures. **Never hand-write the schema twice.**

---

## 6. Tool catalogue for v1

Implement exactly these. Signatures are binding.

### `vox/tools/files.py`

```python
@tool(name="create_folder", risk="safe",
      description="Create a new folder. Use for 'make a folder called X'.")
def create_folder(name: str, parent: str = "desktop") -> ToolResult

@tool(name="create_text_file", risk="safe",
      description="Create a plain text file with optional content.")
def create_text_file(name: str, content: str = "", parent: str = "desktop") -> ToolResult

@tool(name="open_path", risk="safe",
      description="Open a file or folder in the system file manager or default app.")
def open_path(path: str) -> ToolResult

@tool(name="find_files", risk="safe",
      description="Search for files by name fragment inside the jailed roots.")
def find_files(query: str, limit: int = 20) -> ToolResult

@tool(name="move_to_trash", risk="destructive",
      description="Send a file or folder to the recycle bin. Always confirmed.")
def move_to_trash(path: str) -> ToolResult
```

`parent` accepts only these literal keywords, resolved via config: `desktop`, `documents`, `downloads`, `workdir`. Any other value is rejected. This prevents the LLM from inventing absolute paths.

### `vox/tools/documents.py`

```python
@tool(name="create_word_document", risk="safe",
      description="Create a .docx with a title and body sections.")
def create_word_document(
    filename: str,
    title: str,
    sections: list[str],       # each item is "Heading|Paragraph text"
    parent: str = "documents",
) -> ToolResult

@tool(name="create_pdf", risk="safe",
      description="Create a .pdf with a title and body paragraphs.")
def create_pdf(
    filename: str,
    title: str,
    paragraphs: list[str],
    parent: str = "documents",
) -> ToolResult

@tool(name="convert_to_pdf", risk="safe",
      description="Convert an existing .docx to .pdf.")
def convert_to_pdf(path: str) -> ToolResult
```

`convert_to_pdf` implementation order:
1. If LibreOffice is on PATH: `soffice --headless --convert-to pdf --outdir <dir> <file>`.
2. Else on Windows, use Word COM via `pywin32` (`Documents.Open` → `SaveAs2` with `FileFormat=17`), and always `Quit()` in a `finally`.
3. Else return `ok=False` with a clear message. Do not silently produce a broken file.

**Content generation note:** the `sections` / `paragraphs` content is written by the *router*, not by these functions. For "make a Word file about the water cycle", Tier 1/2 fills `sections`. Tier 0 cannot handle content generation — its grammar for documents only matches when the user gives an explicit filename and no topic, in which case it creates an empty titled document.

### `vox/tools/web.py`

```python
@tool(name="web_search", risk="safe",
      description="Open the default browser on a search results page.")
def web_search(query: str) -> ToolResult

@tool(name="play_youtube", risk="safe",
      description="Find a YouTube video by description and open it in the browser.")
def play_youtube(query: str) -> ToolResult

@tool(name="open_url", risk="medium",
      description="Open a specific URL in the default browser.")
def open_url(url: str) -> ToolResult

@tool(name="download_file", risk="medium",
      description="Download a file from a URL into the downloads folder.")
def download_file(url: str, filename: str = "") -> ToolResult
```

Rules:
- `play_youtube` uses `yt-dlp` in **search-only** mode (`ytsearch1:`, `--skip-download`, extract flat) to resolve the video ID, then opens `https://www.youtube.com/watch?v=<id>` in the browser. It must not download media.
- `open_url` and `download_file` validate the URL: scheme must be `http`/`https`, host must not be a private/loopback/link-local IP, and must not be in `config.security.blocked_hosts`. Reject `file://`, `data:`, `javascript:`.
- `download_file` streams to a temp file, enforces `config.security.max_download_mb`, and only then moves it into the downloads jail root. Filename is sanitised: strip path separators, strip leading dots, cap at 120 chars.

### `vox/tools/apps.py`

```python
@tool(name="open_app", risk="medium",
      description="Launch a known desktop application by friendly name.")
def open_app(app: str) -> ToolResult
```

Backed by `config.apps`, a dict of friendly name → executable path or Windows AppUserModelID. **If the name is not in the map, fail.** No searching PATH, no `os.system`. Ship a default map covering: chrome, edge, firefox, notepad, explorer, calculator, word, excel, vscode, terminal.

### `vox/tools/system.py`

```python
@tool(name="get_time", risk="safe", description="Say the current date and time.")
def get_time() -> ToolResult

@tool(name="set_volume", risk="safe", description="Set system volume 0-100.")
def set_volume(level: int) -> ToolResult

@tool(name="take_screenshot", risk="safe", description="Save a screenshot.")
def take_screenshot() -> ToolResult

@tool(name="lock_screen", risk="destructive", description="Lock the workstation.")
def lock_screen() -> ToolResult
```

---

## 6A. Target resolver

### Problem

The user says "go to YouTube and play X" or "open WhatsApp". They do not know or care whether the desktop app is installed, whether a tab is already open, or which browser is default. The agent must work that out.

Do **not** hardcode this logic inside individual tools. Build one resolver that every "reach a service" tool calls.

### The Target descriptor

`resolver/targets.py` defines a catalogue. This is data, not code — it lives in a YAML file (`targets.yaml`) shipped with sensible defaults and overridable by the user.

```python
@dataclass(frozen=True)
class Target:
    key: str                       # "youtube"
    display: str                   # "YouTube"
    aliases: list[str]             # ["you tube", "yt", "youtub"]  <- Whisper mishears
    deep_link: str | None          # "youtube://" or "whatsapp://"
    web_url: str                   # "https://www.youtube.com"
    web_search_url: str | None     # "https://www.youtube.com/results?search_query={q}"
    window_title_match: list[str]  # ["YouTube", "WhatsApp"]  for open-tab detection
    windows_app_ids: list[str]     # AppUserModelIDs / exe names to detect installation
    process_names: list[str]       # ["WhatsApp.exe", "Spotify.exe"]
    prefer: Literal["app", "web"] = "app"
```

Ship entries for at least: `youtube`, `whatsapp`, `gmail`, `google_drive`, `spotify`, `telegram`, `chatgpt`, `maps`, `github`.

### The resolution ladder

`resolver/resolve.py` — try in this exact order, stop at the first success:

**Step 1 — Is it already open?**
Enumerate top-level windows (`win32gui.EnumWindows` on Windows, `wmctrl`/`xdotool` on Linux). Match window title against `window_title_match`. If found, `SetForegroundWindow` and return `Resolution(method="focused_existing", handle=hwnd)`.

This is the step that matters most for perceived quality — reusing an open WhatsApp Web tab instead of opening a fourth one is what makes the agent feel like it understands the machine.

**Step 2 — Is the native app installed?**
Check in order: a running process matching `process_names`; the Windows registry `App Paths` key; the Start Menu shortcut index; the user's `config.apps` map. If installed, launch via `deep_link` if one exists (deep links let you pass a payload), else launch the executable. Return `method="launched_app"`.

**Step 3 — Is a browser already running?**
If yes, open the `web_url` in **that** browser rather than the system default. Return `method="existing_browser"`.

**Step 4 — Default browser.**
`webbrowser.open(web_url)`. Return `method="default_browser"`.

If all four fail, return `Resolution(ok=False, reason=...)` and speak the reason. Never silently do nothing.

### Caching

Installation detection is slow (registry walks, Start Menu scan). Cache results in the memory store with a 24-hour TTL, keyed by target. Invalidate on explicit "rescan apps" command. Window-open detection is **never** cached — it must be live.

### Tools that use it

```python
@tool(name="open_target", risk="medium",
      description="Open a known service or app such as YouTube, WhatsApp, Gmail, "
                  "Spotify. Automatically picks the installed app, an already-open "
                  "window, or the browser.")
def open_target(target: str) -> ToolResult

@tool(name="play_on_target", risk="safe",
      description="Search for and play something on a media service, e.g. a song on "
                  "YouTube or Spotify.")
def play_on_target(target: str, query: str) -> ToolResult
```

`play_on_target("youtube", "munni badnaam hui")` resolves YouTube, then:
- If it landed in a browser: use `yt-dlp` search-only to get the video ID and open the watch URL directly. Opening a search results page and expecting the user to click is a worse outcome — resolve to the actual video.
- If it landed in the native app: use the deep link with the search payload if the app supports it, else fall back to the browser path.

`target` is validated against the catalogue keys **plus aliases**, with fuzzy matching (`difflib.get_close_matches`, cutoff 0.75) to absorb Whisper errors like "you tube" or "whats up". If the match is below cutoff, return a clarification rather than guessing.

---

## 6B. Messaging — WhatsApp

**Read this whole subsection before implementing. There is a hard constraint here.**

### The constraint

WhatsApp has no supported local API for sending messages from a personal account. The available mechanisms are:

| Mechanism | Can it send? | Verdict |
| --- | --- | --- |
| `whatsapp://send?phone=&text=` deep link | Opens chat with text pre-filled. **Does not send.** | Use this |
| `https://web.whatsapp.com/send?phone=&text=` | Same — pre-fills only | Use this as web fallback |
| Simulating an Enter keypress after the deep link | Sends, but blindly | **Do not implement in v1** |
| WhatsApp Business Cloud API | Official, but requires a Business account, a separate number, and template approval for user-initiated messages | Out of scope |

### The rule for v1: draft, do not send

The agent opens the correct chat with the message text pre-filled and speaks *"Message ready for Subodh — press Enter to send."* The human presses Enter.

This is a deliberate design decision, not a limitation to be worked around later. The reasoning:

- Speech-to-text mishears names constantly. "Subodh" and "Subhash" are one phoneme apart. A wrongly-addressed message is unrecoverable — you cannot un-send it from the recipient's memory.
- A blind Enter keypress has no way to verify the correct chat is focused. If the window did not load in time, or a different chat was open, the message goes to the wrong person.
- The keystroke saved is one. The risk avoided is large. This trade is not close.

Write this reasoning into `DECISIONS.md`. If the user later asks for auto-send, implement it as an **opt-in config flag, off by default**, gated behind: contact resolved with confidence ≥ 0.9, a confirmation dialog showing the exact contact name and message text, and a verified check that the focused window title contains the contact's name. Do not implement it in v1.

### Contact resolution

Contacts live in `memory/aliases.py`, backed by `~/.vox/memory/contacts.json` — a user-editable file:

```json
{
  "subodh": { "phone": "+919876543210", "display": "Subodh Kumar" },
  "amma":   { "phone": "+919812345678", "display": "Mummy" }
}
```

Resolution: exact key → case-insensitive → fuzzy (cutoff 0.8). On a fuzzy match, the spoken confirmation must state the resolved display name: *"Message ready for Subodh Kumar."* On no match, return a clarification listing the closest two names. **Never guess a phone number, never construct one.**

### Tool

```python
@tool(name="compose_whatsapp_message", risk="medium",
      description="Open a WhatsApp chat with a contact and pre-fill a message. "
                  "The message is NOT sent automatically; the user presses Enter.")
def compose_whatsapp_message(contact: str, message: str) -> ToolResult
```

Implementation: resolve contact → resolve the `whatsapp` target via Section 6A → build the deep link or web URL with `urllib.parse.quote` on the message → open → return `ToolResult(ok=True, speech="Message ready for <display>. Press Enter to send.")`.

The same pattern generalises to Telegram (`tg://msg?to=`) and SMS on Windows. Build the tool so a second messaging service is a config entry, not a new module.

---

## 6C. Memory and activity store

There are **two separate stores** and they must not be merged.

| Store | Purpose | Mutable? |
| --- | --- | --- |
| **Audit log** (Section 8.6) | Security record: what was executed, when, with what arguments | Append-only, never edited or deleted by app code |
| **Memory store** (this section) | Usefulness: context, artifacts, aliases, recall | Editable, prunable, user can say "forget that" |

Keeping them separate matters: the audit log is only trustworthy if nothing can rewrite it, and memory is only useful if it can be corrected.

### Folder layout

Everything lives under a single dedicated root, `~/.vox/` (override via `config.paths.state_dir`):

```
~/.vox/
├── audit.db                  # append-only security log
├── vox.log                   # rotating application log
├── memory/
│   ├── memory.db             # SQLite: activity, artifacts, sessions, app_cache
│   ├── contacts.json         # user-editable
│   ├── aliases.json          # user-editable: folder shortcuts, app nicknames
│   └── preferences.json      # learned defaults (preferred browser, default parent folder)
├── artifacts/
│   └── YYYY-MM-DD/           # copies or hardlinks of files the agent created
├── cache/
│   ├── models/               # whisper + piper voices
│   └── app_detection.json    # 24h TTL install detection cache
└── transcripts/
    └── YYYY-MM.jsonl         # raw transcripts, retention-controlled
```

Create this tree on first run. Set directory permissions to user-only (`0o700` on Linux; on Windows set an ACL granting only the current user).

### Schema — `memory/memory.db`

```sql
CREATE TABLE activity (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL,
  session_id TEXT NOT NULL,
  transcript TEXT NOT NULL,
  tool TEXT,
  args_json TEXT,
  outcome TEXT,              -- 'ok' | 'failed' | 'clarified' | 'cancelled'
  speech TEXT,               -- what the agent said back
  artifact_id INTEGER
);

CREATE TABLE artifacts (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL,
  path TEXT NOT NULL,
  kind TEXT,                 -- 'docx' | 'pdf' | 'txt' | 'folder' | 'download' | 'screenshot'
  title TEXT,
  source_transcript TEXT,
  still_exists INTEGER DEFAULT 1
);

CREATE TABLE sessions (
  id TEXT PRIMARY KEY,
  started_at TEXT, ended_at TEXT, command_count INTEGER
);

CREATE TABLE app_cache (
  target TEXT PRIMARY KEY,
  installed INTEGER, exe_path TEXT, checked_at TEXT
);

CREATE INDEX idx_activity_ts ON activity(ts);
CREATE INDEX idx_artifacts_ts ON artifacts(ts);
```

### Short-term context (`memory/context.py`)

Held in process, rebuilt from the DB on start. This is what makes follow-up commands work:

```python
class Context:
    last_artifact: Artifact | None      # → "make that a PDF", "open it", "rename it"
    last_target: str | None             # → "play another one"
    last_folder: Path | None            # → "put it in there too"
    recent_turns: deque[Turn]           # last 6, passed to Tier 1 as conversation history
    session_id: str
```

Rules:
- Context expires after `config.memory.context_ttl_minutes` (default 15) of inactivity, then a new session starts. Stale context causes wrong actions — "make that a PDF" three hours later should ask *which* file, not act on yesterday's document.
- Pronouns (`it`, `that`, `there`, `the same`) are resolved by Tier 0 **before** routing, by substituting the context value. If the pronoun cannot be resolved, return a clarification.
- Tier 1 receives `recent_turns` as prior messages. Cap at 6 turns to keep latency and token count down.

### Artifact tracking

Every tool that produces a file returns `artifact_path`. The guard layer, after a successful execution, writes an `artifacts` row and — if `config.memory.keep_artifact_copies` is true — hardlinks (not copies, to save disk) the file into `~/.vox/artifacts/YYYY-MM-DD/`. On Windows, fall back to a copy if the hardlink fails across volumes.

A daily background check sets `still_exists = 0` for artifacts whose path has vanished. Do not delete the row — knowing a file *was* created and is now gone is useful.

### Recall tools

```python
@tool(name="recall_activity", risk="safe",
      description="Answer questions about what the agent did recently, e.g. "
                  "'what did I do yesterday', 'what files did you make this week'.")
def recall_activity(query: str, days: int = 7) -> ToolResult

@tool(name="find_recent_artifact", risk="safe",
      description="Find a file the agent created recently, by description or type.")
def find_recent_artifact(description: str = "", kind: str = "", days: int = 30) -> ToolResult

@tool(name="forget_activity", risk="destructive",
      description="Delete stored memory entries. Requires confirmation.")
def forget_activity(scope: Literal["last", "today", "all"]) -> ToolResult
```

`recall_activity` must **not** call an LLM to answer. Query the DB, format the rows, speak a summary. Model calls for "what did I do yesterday" are slow and can hallucinate activity that never happened — which defeats the point of having a record. Use parameterised SQL over the `days` window and a deterministic template.

`forget_activity` deletes from the **memory** store only. It never touches `audit.db`. Say so aloud when confirming: *"This clears memory, not the security log."*

### Retention and privacy

Transcripts are recordings of everything spoken to the machine. Treat them accordingly.

- `config.memory.transcript_retention_days` (default 90). A startup job prunes older `transcripts/*.jsonl` entries and `activity` rows.
- `config.memory.store_transcripts` (default true) — when false, `activity.transcript` stores the matched tool name only, not the spoken text.
- Never write `contacts.json`, `transcripts/`, or `*.db` outside `~/.vox/`. Add all of them to `.gitignore`.
- If `compose_whatsapp_message` runs, store the contact key and message **length**, not the message body, unless `config.memory.store_message_bodies` is explicitly true.

---

## 6D. Input modes — voice is one of two, not the only one

The agent has **two equal input paths** into the router. Voice is not privileged; text is not a debug fallback.

```
Voice hotkey  (default Ctrl+Alt+Space, hold)  -> mic -> VAD -> STT -> ROUTER
Text hotkey   (default Ctrl+Alt+K, tap)       -> command bar     -> ROUTER
```

Both produce a `Transcript`. Text input sets `confidence = 1.0` and `source = "text"`. Everything downstream — router, guard, jail, audit, memory — is identical. Do not fork the pipeline.

### Why text is a first-class path

- **Speech impairment, heavy accent, or an unusual name.** STT quality is not evenly distributed across speakers. A user the model transcribes poorly must still have a fully working product.
- **Noise.** A staffroom, a classroom, a fan overhead.
- **Privacy.** An open office, or a message you don't want to say out loud.
- **Precision.** Exact filenames, URLs, and long text are faster and more accurate typed than dictated.
- **Silence.** Late at night, in a shared room.

Any of these alone justifies it. Together they mean a voice-only product is unusable for a meaningful share of users.

### The command bar

A small always-on-top input window, Spotlight/Alfred style. Requirements:

- Opens centred, focused, ~600 px wide, single line, with the last 5 commands available on ↑
- `Enter` submits, `Esc` closes without acting
- Live inline hint showing which tool Tier 0 would match, updated as the user types. This teaches the grammar faster than any documentation.
- Closes automatically on submit; the result is spoken and shown in the tray as usual
- Never steals focus from a full-screen app without the user pressing the hotkey

Implementation: `vox/ui/command_bar.py`, Tkinter (in the standard library, no extra dependency, adequate for one input box). It is a thin UI over the existing `run.py --text` path built in Phase 1.

### Mixed use

Both hotkeys work in the same session and share the same `Context`. Speak *"make a Word file about the water cycle"*, then type *"rename it to Chapter 3 Notes"* — the pronoun resolves against the same last artifact. This is a common real pattern: dictate the bulk, type the exact string.

---

## 6E. Hotkey configuration

Hotkeys are **user-configurable from the settings window**, not only by editing YAML.

```yaml
hotkeys:
  voice: "ctrl+alt+space"     # hold to talk
  text:  "ctrl+alt+k"         # tap to open command bar
  abort: "esc"                # not rebindable
```

### Settings UI

A capture widget: the user clicks "Change", the widget records the next chord pressed and displays it. Standard behaviour, and far better than asking a teacher to hand-edit a YAML string.

### Validation — reject before saving

| Rule | Reason |
| --- | --- |
| Must include at least one modifier (Ctrl/Alt/Shift/Win) | A bare letter key would fire while typing anywhere |
| Reject `Ctrl+Alt+Del`, `Win+L`, `Ctrl+Shift+Esc`, `Alt+Tab`, `Win+Tab` | Reserved by Windows; cannot be captured, and attempting it looks like malware behaviour |
| Warn (don't block) on common app shortcuts — `Ctrl+C`, `Ctrl+V`, `Ctrl+S`, `Ctrl+Z`, `Alt+F4` | The user may have a reason, but they should be told |
| Voice and text hotkeys must differ | Obvious, but check it |

### Registration failure is normal — handle it

Another application may already hold the chord. `pynput` registration can fail silently, which produces the worst possible outcome: the user presses the key, nothing happens, and they conclude the product is broken.

Required behaviour: after registering, verify it took. If it did not, show a **visible** message naming the chord and asking for a different one, and surface it in the startup self-check table. Never fail silently.

Changes apply immediately — unregister the old chord, register the new one, no restart. If the new one fails, roll back to the previous working chord and say so.

---

## 6F. Language support

There are **two independent layers**, and they have different language coverage. Conflating them is the most likely design error in this area.

| Layer | What it does | Language coverage |
| --- | --- | --- |
| STT (Whisper) | Audio → text | ~99 languages, quality varies enormously |
| Router | Text → tool call | Tier 0 grammar: whatever patterns you write. Tier 1: whatever the LLM handles. |

Whisper transcribing Hindi perfectly is worthless if the Tier 0 grammar only matches English verbs. **Language support is a routing problem at least as much as a transcription problem.**

### v1 supported languages

| Tier | Languages | Path |
| --- | --- | --- |
| Full | English (Indian, US, UK accents) | Tier 0 grammar + Tier 1 |
| Full | Hindi, and Hinglish (romanised code-mixed) | Hindi keyword aliases in Tier 0 + Tier 1 |
| Best-effort | The other ~96 Whisper languages | Tier 1 only; no Tier 0 patterns |

### The Hinglish problem — read carefully

Real Indian usage is code-mixed mid-sentence: *"desktop pe ek folder banao Physics Notes ke naam se."* This is the hardest case for Whisper, which has **no native mid-sentence code-switching support**. Pin `language: "hi"` and it renders English words in Devanagari; pin `"en"` and it mangles the Hindi.

What to do:

1. **Leave `stt.language: null`** (autodetect) by default. Do not pin unless the user is consistently monolingual.
2. **Add romanised Hindi verb aliases to the Tier 0 grammar** — this is cheap and covers most real commands:

```
banao | bana do            -> make/create
kholo | khol do            -> open
chalao | baja do           -> play
dhoondo | search karo      -> search
bhejo | bhej do            -> send
band karo                  -> close/stop
```

   Patterns should accept Hindi word order too: `(?P<name>.+?) (naam se )?(ek )?folder banao` alongside the English form.
3. **Route anything Tier 0 misses to Tier 1.** Qwen3 is multilingual and handles Hindi and Hinglish considerably better than a regex ever will. This is the main reason a Hindi-speaking user benefits from having Tier 1 available.
4. **Do not use Whisper's `task="translate"`** as a shortcut to force everything into English. It mangles proper nouns — exactly the words in a command that must survive intact (a filename, a contact, a song title).

### Model size drives non-English quality

| Model | English | Hindi / other | Note |
| --- | --- | --- | --- |
| `base` | Adequate | Poor | Do not ship for non-English use |
| `small` | Good | Usable | Sensible default |
| `medium` | Very good | Good | Recommended if the machine can take it |

The startup self-check must warn if `stt.language` is set to a non-English language while `stt.model` is `base`.

### Honest limits to put in the README

- Regional Indian languages (Marathi, Tamil, Telugu, Bengali, Gujarati, Punjabi) are transcribed by Whisper but with materially lower accuracy than Hindi, and have **no Tier 0 patterns**. They work through Tier 1 only, more slowly and less reliably.
- Heavy background noise degrades every language.
- **The command bar (Section 6D) is the reliable fallback for every language.** Typing is always accurate. Say so plainly rather than overselling multilingual voice.

---

## 7. Router specification

### Tier 0 — grammar (`tier0_grammar.py`)

A list of `(compiled_regex, tool_name, arg_builder)` triples, tried in order. Must cover at minimum these patterns (write case-insensitive, tolerant of Indian-English phrasing and filler words like "please", "just", "can you"):

```
(search|google|look up|search for) (?P<query>.+)                      -> web_search
play (?P<query>.+?) (on youtube|youtube)                              -> play_youtube
(play|open) youtube (?P<query>.+)                                     -> play_youtube
(make|create|new) (a )?folder (called|named)? (?P<name>.+?)( (on|in) (?P<parent>desktop|documents|downloads))?$
                                                                       -> create_folder
(make|create|new) (a )?(text )?file (called|named)? (?P<name>.+?)(...)  -> create_text_file
open (?P<app>chrome|edge|firefox|notepad|word|excel|calculator|...)    -> open_app
(what'?s the |tell me the )?time( now)?$                              -> get_time
(set |turn )?volume (to )?(?P<level>\d+)                              -> set_volume
(take a |take )?screenshot                                            -> take_screenshot
lock (the )?(screen|computer|pc)                                      -> lock_screen
download (?P<url>https?://\S+)                                        -> download_file
(go to|open|launch) (?P<target>youtube|whatsapp|gmail|spotify|...)    -> open_target
(go to |open )?(?P<target>youtube|spotify) (and )?play (?P<query>.+)  -> play_on_target
play (?P<query>.+?) on (?P<target>youtube|spotify)                    -> play_on_target
(go to |open )?whatsapp( and)? (send|message|msg) (a message )?to (?P<contact>\w+) (saying|that) (?P<message>.+)
                                                                       -> compose_whatsapp_message
(message|msg|text) (?P<contact>\w+) on whatsapp (saying )?(?P<message>.+)
                                                                       -> compose_whatsapp_message
what did (i|you) do (?P<when>today|yesterday|this week)                -> recall_activity
(make|convert|turn) (that|it|this) (in)?to (a )?pdf                   -> convert_to_pdf  [context]
open (it|that|the file)$                                              -> open_path       [context]
```

Patterns marked `[context]` resolve their argument from `Context.last_artifact` before dispatch. If context is empty or expired, return a clarification — never fall through to Tier 1 with an unresolved pronoun.

Tier 0 returns `confidence = 0.95` on a match, `None` otherwise. It never guesses.

**Cleanup step before matching:** lowercase, strip trailing punctuation, collapse whitespace, remove leading wake-filler ("hey", "ok", "please", "computer"). Normalise common Whisper artefacts for filenames — spoken "dot txt" → `.txt`, "underscore" → `_`, "dash" → `-`.

### Tier 1 — local LLM (`tier1_local.py`)

- Ollama chat call with `model=config.tier1.model`, `tools=REGISTRY.as_ollama_tools()`, `think=False` for latency (enable thinking only if `config.tier1.thinking = true`).
- System prompt must state: the assistant controls a desktop; it must respond **only** with a tool call; if the request is ambiguous or not covered by a tool, it must call the special `ask_clarification(question: str)` tool rather than guessing.
- Register `ask_clarification` as a real tool with `risk="safe"` that simply returns the question as speech. This gives the model a legal escape hatch and stops it fabricating calls.
- Validate the returned args through the tool's pydantic model. On validation failure, retry **once** with the error text appended, then give up and route to clarification.
- Timeout: `config.tier1.timeout_s`, default 12. On timeout, speak "that took too long" and abort.

### Tier 2 — cloud (`tier2_cloud.py`)

Disabled by default. Same interface as Tier 1. Reads `ANTHROPIC_API_KEY` from the environment only — never from `config.yaml`, never hardcoded. If enabled but the key is missing, log a warning at startup and behave as if disabled.

### Escalation logic in `app.py`

```
t0 = tier0.route(text)
if t0.call:                      -> execute
elif tier1 available:            -> t1 = tier1.route(text)
    if t1.call and t1.confidence >= threshold  -> execute
    else                                        -> clarify
elif tier2 enabled:              -> t2 = tier2.route(text)
else:                            -> speak "I didn't understand that"
```

Also: if `Transcript.confidence < config.stt.min_confidence` (default 0.55), **do not route at all**. Speak "sorry, I didn't catch that" and stop. A misheard command executing is worse than no command executing.

---

## 8. Security requirements — non-negotiable

These are not suggestions. Implement all of them, and add a test for each.

1. **No generic execution tool.** No `run_shell`, `run_python`, `eval`, or any tool taking a command string. If a future feature seems to need one, write it in `DECISIONS.md` and do not implement it.

2. **Path jail** (`security/jail.py`). Config defines `jail_roots` (default: Desktop, Documents, Downloads, and a `workdir`). Every path argument goes through:
   ```python
   def resolve_in_jail(user_path: str, parent_key: str | None = None) -> Path:
       # 1. expand user, resolve to absolute with .resolve(strict=False)
       # 2. reject if any component is '..' after resolution escapes a root
       # 3. reject symlinks that point outside the roots
       # 4. raise JailViolation otherwise
   ```
   Test cases required: `../../Windows/System32`, `C:\Windows\System32`, `~/.ssh`, a symlink pointing outside, a UNC path `\\server\share`, and a valid nested path.

3. **Filename sanitisation.** Strip `\ / : * ? " < > |`, strip control chars, strip leading/trailing dots and spaces, reject Windows reserved names (`CON`, `PRN`, `AUX`, `NUL`, `COM1-9`, `LPT1-9`), cap length at 120 chars.

4. **Risk tiers.**
   - `safe` → execute immediately.
   - `medium` → execute, but show a tray toast with a 4-second **undo** window where undo is possible (file creation, download).
   - `destructive` → block on a modal confirmation dialog showing the exact tool name and resolved arguments. Default button is Cancel. Also require spoken or clicked confirmation. Never auto-confirm.

5. **Push-to-talk only.** Audio capture begins on hotkey **press** and ends on **release**. No always-on listening in v1. Rationale: audio is not an authenticated channel — anyone in the room, or the user's own speakers playing a video, can otherwise issue commands.

6. **Audit log** (`security/audit.py`), SQLite at `~/.vox/audit.db`, append-only:
   ```sql
   CREATE TABLE IF NOT EXISTS events (
     id INTEGER PRIMARY KEY,
     ts TEXT NOT NULL,
     transcript TEXT,
     stt_confidence REAL,
     tier TEXT,
     tool TEXT,
     args_json TEXT,
     risk TEXT,
     confirmed INTEGER,
     status TEXT,          -- 'executed' | 'rejected' | 'failed' | 'cancelled'
     error TEXT,
     duration_ms INTEGER
   );
   ```
   Write the row **before** execution with status `pending`, update after. Never delete rows from application code.

7. **Kill switch.** `Esc` anywhere aborts the in-flight action and stops TTS. Implement as an `threading.Event` checked by long-running tools (download loop, conversion).

8. **No secrets in config.yaml.** API keys come from environment variables only. `.gitignore` must include `config.yaml`, `*.db`, `.env`, `models/`.

9. **Startup self-check.** On boot, verify: jail roots exist and are writable, whisper model present, Ollama reachable (if Tier 1 enabled), Piper voice present, hotkey registered. Print a green/red table. If any red, still start but disable the affected subsystem and say so aloud once.

---

## 9. Configuration file

`config.example.yaml` — ship this, with `config.yaml` gitignored.

```yaml
hotkeys:
  voice: "ctrl+alt+space"      # hold to talk
  text:  "ctrl+alt+k"          # tap to open the command bar

paths:
  desktop: "~/Desktop"
  documents: "~/Documents"
  downloads: "~/Downloads"
  workdir: "~/vox-workspace"
  state_dir: "~/.vox"          # everything the agent owns lives here

memory:
  context_ttl_minutes: 15
  recent_turns: 6
  keep_artifact_copies: true
  store_transcripts: true
  store_message_bodies: false
  transcript_retention_days: 90

resolver:
  prefer_native_app: true
  reuse_open_window: true
  install_cache_ttl_hours: 24
  preferred_browser: null      # null = system default; else a key from `apps`

messaging:
  whatsapp_auto_send: false    # DO NOT enable. See Section 6B.
  contact_match_cutoff: 0.8

security:
  jail_roots: ["~/Desktop", "~/Documents", "~/Downloads", "~/vox-workspace"]
  max_download_mb: 500
  blocked_hosts: []
  confirm_destructive: true
  undo_window_s: 4

stt:
  model: "small"            # base | small | medium
  device: "cpu"             # cpu | cuda
  compute_type: "int8"
  language: null            # null = autodetect. Leave null for Hinglish.
  hindi_aliases: true       # enable romanised Hindi verbs in the Tier 0 grammar
  min_confidence: 0.55

tts:
  enabled: true
  voice: "en_US-amy-medium"
  rate: 1.0

tier1:
  enabled: true
  provider: "ollama"
  model: "qwen3:8b"
  thinking: false
  timeout_s: 12
  min_confidence: 0.6

tier2:
  enabled: false
  provider: "anthropic"
  model: "claude-haiku-4-5-20251001"
  # API key read from ANTHROPIC_API_KEY env var only

apps:
  chrome: "C:/Program Files/Google/Chrome/Application/chrome.exe"
  notepad: "notepad.exe"
  explorer: "explorer.exe"
  calculator: "calc.exe"
  # ... extend per machine

logging:
  level: "INFO"
  file: "~/.vox/vox.log"
```

---

## 10. Build phases

Build strictly in this order. Stop after each phase and report.

### Phase 1 — Skeleton, safety core, platform adapter
Build: `config.py`, `logging_setup.py`, `platform/` (all five files), `security/jail.py`, `security/audit.py`, `tools/registry.py`, `tools/files.py`, `tools/system.py` (`get_time` only).

No audio yet. Provide `run.py --text "make a folder called Test on desktop"` so the whole pipeline below STT can be driven from the keyboard.

Build the platform adapter **first**, before any tool that touches the OS. It is cheap now and expensive to retrofit.

**Acceptance:**
- `pytest tests/test_jail.py` passes, including all six attack cases in 8.2.
- `python run.py --text "make a folder called Test"` creates the folder and writes one audit row.
- `python run.py --text "make a folder called ../../evil"` is rejected, audit status `rejected`, no folder created.
- Importing a tool with an unannotated parameter raises at import time.
- `grep -r "sys.platform\|platform.system\|os.name" vox/ --include=*.py` returns matches **only** inside `vox/platform/`. This is a hard gate — fix any leak before proceeding.
- The whole test suite passes with the adapter forced to `null.py`, proving nothing crashes when a capability is missing.
- Startup self-check prints one row per capability with present/absent, plus OS build, RAM, AVX2 and free disk.

### Phase 2 — Tier 0 grammar + remaining tools
Build: `router/tier0_grammar.py`, `tools/web.py`, `tools/documents.py`, `tools/apps.py`, rest of `tools/system.py`.

**Acceptance:**
- `tests/test_grammar.py` covers ≥ 30 phrasings across all Tier 0 patterns, with expected tool + args.
- `python run.py --text "..."` works end-to-end for every row in the Section 1 table that Tier 0 can handle.
- `create_word_document` and `create_pdf` produce files that open cleanly.
- URL validation tests reject `file://`, `http://127.0.0.1`, `http://192.168.1.1`, `javascript:alert(1)`.

### Phase 3 — Voice in, voice out
Build: `audio/capture.py`, `audio/vad.py`, `audio/tts.py`, `stt/whisper.py`, hotkey wiring in `app.py`.

**Acceptance:**
- Holding the hotkey records; releasing transcribes within 2s for a 3-second clip on `small`/int8/CPU.
- VAD trims leading/trailing silence; a hotkey press with no speech produces **no** routing attempt.
- Low-confidence transcripts are refused, not routed.
- Every executed command produces a spoken confirmation under 15 words.

### Phase 4 — Tier 1 local LLM
Build: `router/tier1_local.py`, `ask_clarification` tool, escalation logic.

**Acceptance:**
- "make me a Word document explaining photosynthesis for class 8" produces a `.docx` with a title and at least three headed sections.
- An unsupported request ("book me a flight") triggers `ask_clarification`, not a fabricated tool call.
- A malformed tool call from the model is retried once, then falls back to clarification. Verify with a mocked bad response.
- Startup with Ollama unreachable logs a warning and the app still runs Tier 0 only.

### Phase 5 — Guard rails, tray, packaging
Build: `security/confirm.py`, `ui/tray.py`, `ui/command_bar.py`, `ui/settings.py`, undo window, kill switch, startup self-check, `README.md`.

**Acceptance:**
- `move_to_trash` shows a modal with the resolved absolute path; Cancel is the default; cancelling writes audit status `cancelled`.
- Tray icon shows idle / listening / thinking / error states.
- `Esc` during a large download aborts it and cleans up the temp file.
- README documents install, model download, config, hotkeys, and how to read the audit log.
- The command bar opens on its hotkey, submits to the same router as voice, and produces an identical audit row apart from `source="text"`.
- A command started by voice and continued by text resolves context correctly ("make a Word file about X", then typed "rename it to Y").
- Rebinding a hotkey in the settings window takes effect with no restart; rebinding to `Win+L` is rejected with a reason; rebinding to a chord already held by another app rolls back and shows a visible message.
- With the microphone physically disconnected, the command bar path still works end to end.

### Phase 6 — Memory store
Build: `memory/store.py`, `memory/context.py`, `memory/aliases.py`, `memory/recall.py`, `tools/memory_tools.py`, the `~/.vox/` tree, retention job, artifact tracking hook in the guard layer.

**Acceptance:**
- First run creates the full `~/.vox/` tree with user-only permissions.
- "make a Word file called Notes" then "make that a PDF" works — the second command resolves `it` from context with no LLM call.
- The same pair, with the clock advanced past `context_ttl_minutes`, returns a clarification instead of acting.
- "what did I do today" returns a deterministic DB-backed summary. Verify no model call is made (assert with a mocked client that would raise if called).
- `forget_activity("today")` clears memory rows and leaves `audit.db` byte-identical. Test by hashing the file before and after.
- With `store_transcripts: false`, no spoken text is written to disk anywhere.

### Phase 7 — Target resolver and messaging
Build: `resolver/`, `targets.yaml`, `tools/targets.py`, `tools/messaging.py`, plus the new Tier 0 patterns.

**Acceptance:**
- With a browser tab already showing YouTube, "go to YouTube" focuses that window and opens no new tab. Verify by counting browser windows before and after.
- With WhatsApp Desktop installed, "open WhatsApp" launches the app. With it uninstalled (simulate by emptying `process_names` and `windows_app_ids` in a test fixture), it opens `web.whatsapp.com`.
- "play munni badnaam hui on YouTube" opens a `watch?v=` URL, not a search results page.
- "message Subodh saying I'll be late" opens the chat pre-filled and returns speech containing "press Enter". Assert that **no keyboard event is ever synthesised** — add a test that fails if `pynput.keyboard.Controller` is instantiated anywhere in the messaging path.
- An unknown contact returns a clarification naming the two closest matches, and no URL is opened.
- Fuzzy target matching: "you tube", "whats up", "utube" all resolve. "flipkart" (not in catalogue) returns a clarification.
- Install detection is cached; a second `open_target` call within the TTL performs no registry access (assert with a spy).

### Phase 8 — Licensing, telemetry and packaging
Build: `vox/licensing/` (`client.py`, `entitlement.py`, `fingerprint.py`, `telemetry.py`), the install-time consent screen, tray licence status, Nuitka build script, Inno Setup script. The Laravel server is a separate repository — build against the contract in Section 11.1.

Do this **last**, not first. Licensing a product nobody has used yet is effort spent on the wrong problem.

**Acceptance:**
- With no network at all, the agent starts and every Tier 0 command works. Verify by blocking the licence host in `hosts`.
- Entitlement expiry inside the grace window: full features, tray warning. Past grace: degraded mode, clear message, **no crash, no data deletion**.
- A tampered entitlement JWT (one byte flipped) is rejected by signature verification.
- Telemetry schema test: no event field is a free-form `str`. The test must fail if one is added.
- Run 20 mixed commands, capture the outgoing telemetry payload, and assert it contains **zero** transcripts, file names, contact names, URLs or message bodies. This is the single most important test in the licensing phase.
- Declining analytics consent at install results in heartbeats only, no telemetry events, and full product functionality.
- The signed installer runs on a clean Windows 10 22H2 VM without admin rights and completes first-run model download.

### Phase 9 — OPTIONAL, do not start without explicit go-ahead
GUI fallback via `pywinauto` accessibility tree. Vision-based clicking is out of scope entirely.

---

## 11. Licensing, distribution and telemetry

### 15.0 What this can and cannot achieve — read first

A Python desktop app compiled to `.exe` **cannot be made piracy-proof.** Bytecode is recoverable, and any client-side check can be patched out. Do not let the implementation pretend otherwise, and do not spend effort on heavy obfuscation — it costs a lot, breaks your own debugging, and buys days of delay at most.

The achievable goals, in order of value:

1. **Stop casual re-sharing.** Someone forwarding the installer to a friend should hit an activation wall. This is 95% of real-world leakage and licensing handles it completely.
2. **Know who is using it.** Device count, versions, feature usage — the data that lets you make product decisions and later price a SaaS tier.
3. **Make the server worth having.** The real anti-piracy lever is architectural, not cryptographic: put capability on the server that a cracked client simply does not have.

For this product, the server-side value candidates are: cloud routing for complex commands (Tier 2 proxied through your server, so you hold the API key and they don't), grammar and `targets.yaml` pack updates, a document template library, and memory backup/sync across machines. Build at least one of these before worrying about crackers.

### 15.1 Server — Laravel

The server is a separate Laravel application, not part of this repo. This spec defines the **contract** the agent must implement against.

**Endpoints (all HTTPS, all JSON):**

```
POST /api/v1/activate     { license_key, fingerprint, os, app_version }
                          -> { entitlement_jwt, expires_at, features[], device_id }
POST /api/v1/heartbeat    Bearer <device_token>
                          -> { entitlement_jwt, features[], min_app_version, notice? }
POST /api/v1/telemetry    Bearer <device_token>  { events: [...] }
                          -> { accepted: n }
POST /api/v1/deactivate   Bearer <device_token>   # frees the seat
```

**Schema (Laravel migrations, tenant-ready from day one):**

```
tenants          id, name, plan, created_at
licenses         id, tenant_id, key_hash, plan, seat_limit, expires_at,
                 status(active|suspended|revoked), notes
devices          id, license_id, tenant_id, fingerprint_hash, hostname_hash,
                 os, os_build, app_version, first_seen, last_seen,
                 status(active|released|blocked)
heartbeats       id, device_id, at, app_version, ip_country
telemetry_events id, device_id, tenant_id, at, event_name, tool_name,
                 tier, outcome, duration_ms, error_code
```

Put `tenant_id` on every table **now**, even while it is always `1`. Adding it later means backfilling every query in the application. This one column is the difference between "add a SaaS tier in a sprint" and "rewrite the data layer."

### 15.2 Entitlement tokens — Ed25519, not a boolean

**Never** design the client to ask "am I licensed?" and act on a `true`/`false`. That is one byte to patch.

Instead:
- The server signs a short-lived **entitlement JWT** (Ed25519, `EdDSA`) containing `device_id`, `tenant_id`, `plan`, `features[]`, `exp`.
- The agent embeds only the **public key** and verifies the signature locally.
- Features are read from the verified token. To forge entitlements an attacker must either steal your private key or patch the feature-gate logic in many places, not one.

Store the token at `~/.vox/license/entitlement.jwt`, mode `0o600`.

### 15.3 Device fingerprint

Must be stable across reboots, unstable across machines, and must **not** be personally identifying.

```
raw = MachineGuid (HKLM\SOFTWARE\Microsoft\Cryptography)
    + system volume serial
    + CPU vendor+family string
fingerprint = SHA256(raw + BUILD_SALT)     # BUILD_SALT compiled in
```

Send **only the hash**. Never send the raw MachineGuid, the hostname, the username, or the MAC address. Hostname, if needed for the admin UI, is sent as `SHA256(hostname + salt)` truncated to 12 chars — enough to distinguish two machines on one licence, not enough to identify a person.

**Hardware changes break fingerprints.** Plan for it: `seat_limit` with self-service release, an admin "reset devices" button, and a 30-day rolling window so a reinstall doesn't permanently burn a seat. Without this you will spend more time on support tickets than on the product.

### 15.4 Offline behaviour — the decision that matters most

The agent must work without a network. It is a *local* desktop assistant; a user whose broadband is down still expects "make a folder" to work.

```
Entitlement valid                      -> full features
Entitlement expired, within grace      -> full features, quiet warning in tray
                                          (grace = config.license.grace_days, default 14)
Grace exhausted, still offline         -> Tier 0 + local tools only.
                                          Server-backed features disabled.
                                          NEVER refuse to start. NEVER delete user data.
Licence revoked (explicit server reply)-> same degraded mode + clear message
```

Degrade, do not brick. A tool that stops working because a heartbeat failed will be uninstalled and badmouthed, and it converts a paying customer into someone looking for a crack.

Heartbeat cadence: once every 24h, plus on startup, with jitter. Exponential backoff on failure. Never block the UI or a command on a network call.

### 15.5 Telemetry — the hard privacy line

This agent hears everything said near the microphone and touches the user's files. What you collect defines whether it is a product or a liability.

**Never transmit, under any configuration:**
- Transcripts or any spoken text
- Message bodies or contact names/numbers
- File names, file paths, or file contents
- URLs visited, search queries, or video titles
- Anything from `~/.vox/transcripts/`, `contacts.json`, or `memory.db` content rows

**Safe to transmit:**
- `device_id` (opaque), app version, OS name and build
- Tool **name** and outcome (`create_folder` / `ok`), counts, durations
- Which tier handled the command (`tier0` / `tier1` / `tier2`)
- Error codes and exception **types** — never messages, which can contain paths
- Session counts and startup self-check capability flags

Implement as an allowlist in `licensing/telemetry.py`: a fixed set of event names with a fixed set of typed fields. **No free-text field anywhere in the telemetry payload.** If a field cannot be enumerated, it does not get sent. Add a test that fails if any telemetry event schema contains a `str` field not backed by a `Literal` or an enum.

Batch to `~/.vox/telemetry/queue.jsonl`, flush on heartbeat, cap at 5 MB, drop oldest on overflow. Telemetry failure must never affect agent behaviour.

**Config:**
```yaml
license:
  server: "https://licence.yourdomain.com"
  grace_days: 14
telemetry:
  enabled: true         # usage analytics — user can turn off
  # licence heartbeat is separate and cannot be disabled while licensed
```

### 15.6 Indian data protection — DPDP

You are in India and will hold device and usage records tied to identifiable customers. The Digital Personal Data Protection Rules, 2025 were notified on 13 November 2025, with the substantive Data Fiduciary obligations — notice, consent, security safeguards, breach reporting, retention, data principal rights — commencing on 13 May 2027. 2026 is the build window. Penalties run to ₹250 crore per violation category.

Build these in now, while it is cheap:

- **Notice and consent at install**, separately for (a) licence validation, which is contractual and necessary, and (b) usage analytics, which is optional and must be refusable without losing the product.
- **Purpose limitation** — the telemetry allowlist above is the technical implementation of this.
- **Retention** — set a policy (e.g. telemetry 12 months, heartbeats 24 months) and implement the pruning job in Laravel from the start, not later.
- **Data principal rights** — a customer can ask what you hold and ask for erasure. Design the admin panel with an "export device data" and "erase device data" action from day one.
- **Breach notification** — have the process written down before you need it.

*This is a summary of the framework as it stands, not legal advice. Confirm your specific obligations with an Indian data protection practitioner before you take payments.*

### 15.7 Security constraint on the server relationship

You are shipping software with filesystem access and app-launching rights to other people's machines, and it phones home to your server. That makes your server a high-value target.

**Hard rule: the server may never send executable content to the client.**

- Feature flags are booleans and enums, validated against a compiled-in allowlist. An unknown flag is ignored, not stored.
- `targets.yaml` and grammar pack updates, if implemented, must be **signed with your Ed25519 key and validated before use**, and must be pure data — no code, no shell strings, no paths outside the jail.
- The server must never be able to add a tool, change a tool's risk tier, or widen the path jail. Those live in the client binary only.

If your server is compromised and it can only flip booleans, the blast radius is a feature outage. If it can push tool definitions, you have handed an attacker a botnet on your customers' machines. Write this constraint into `DECISIONS.md` and never relax it.

### 15.8 Packaging the `.exe`

| Choice | Recommendation | Why |
| --- | --- | --- |
| Compiler | **Nuitka**, not PyInstaller | Compiles to C. PyInstaller archives are trivially extractable with public tools. |
| Mode | `--standalone` (onedir), not onefile | Onefile extracts to temp on every launch: slow startup and a strong antivirus heuristic trigger. |
| Installer | **Inno Setup** (free) | Mature, scriptable, handles shortcuts, uninstall, per-user install without admin. |
| Models | Downloaded on first run | Keeps the installer ~80 MB instead of ~6 GB. Show a progress screen. |
| Ollama | Not bundled | Detect it; link to the installer if missing. Bundling someone else's runtime is a support burden. |

**Code signing — get the current facts right, because CA marketing pages are misleading on this.**

- Since 1 June 2023, the private key for any publicly trusted code signing certificate (OV **or** EV) must live on a FIPS 140-2 Level 2 hardware token or cloud HSM. The old "install the cert on your laptop" workflow no longer exists.
- **EV no longer grants instant SmartScreen reputation.** Microsoft removed that behaviour in 2024; per Microsoft's own developer documentation, paying the EV premium solely to avoid SmartScreen warnings is no longer justified — you will see the same warnings as with OV. Several certificate resellers still advertise instant SmartScreen bypass as an EV benefit. **Microsoft's documentation is authoritative here; the reseller pages are outdated marketing.**
- SmartScreen reputation accrues to the **certificate**, based on clean download volume, and resets if you switch certificates. Sign every release with the same identity, and don't swap certificates right before a big launch.
- **Self-signed certificates are unsuitable for distribution** — Windows will hard-block them for anyone who hasn't manually trusted your root.
- Cheapest credible path: Microsoft's own **Artifact Signing** (formerly Trusted Signing), from $9.99/month, which Microsoft names as its recommended service for non-Store distribution. A traditional OV certificate runs roughly $130–300/year plus token or HSM costs.
- One source reports the CA/B Forum reduced maximum code signing certificate lifetime to 459 days effective 23 February 2026. Treat as likely but **verify with your CA before purchasing** — it affects renewal planning.

Expect antivirus false positives on unsigned Python-compiled binaries regardless. Sign the binary, use onedir, and submit false positives to Microsoft's analysis portal.

### 15.9 Admin panel

Laravel + Filament is the fastest path to a usable panel for a solo developer. Minimum views:

- **Licences** — key, plan, seats used/limit, expiry, status; actions: suspend, revoke, extend, reset devices
- **Devices** — per licence: fingerprint short-hash, OS + build, app version, first/last seen, status; actions: block, release seat
- **Fleet health** — version distribution, OS distribution, capability flags (how many users actually have Tier 1?), daily active devices
- **Feature usage** — commands per tool per week, tier split, error rates. This is what tells you which tools to build next.
- **Data rights** — export and erase all data for a device or licence, for DPDP requests

Every destructive admin action writes to an admin audit log. You will want it the first time a customer disputes a revocation.

### 15.10 SaaS seam — decisions to make now, work to defer

Cheap now, expensive later:
- `tenant_id` on every table
- Features driven by the entitlement token, never compiled in
- A `plans` → `features` mapping table rather than `if plan == "pro"` in code
- Versioned API (`/api/v1/`) from the first request

Explicitly **defer**: billing integration, self-service signup, per-seat invoicing, trial automation, a customer-facing web portal. Leave the seam, don't build the wall.

---

## 12. Coding standards

- Type hints everywhere; the codebase must pass `mypy --strict` on `vox/tools/` and `vox/security/` at minimum.
- No bare `except:`. Catch specific exceptions; log with `exc_info=True`.
- Tools never raise to the caller — they catch, log, and return `ToolResult(ok=False, ...)`. The only exception is `JailViolation`, which propagates so the guard layer records a `rejected` audit row.
- No global mutable state except the tool `REGISTRY`, populated at import.
- Every module under 300 lines. Split rather than grow.
- Docstrings on every tool function — they become the LLM-facing description, so write them for the model, not for a human reader.
- Windows path handling: `pathlib` only, never string concatenation, never hardcoded `/` or `\`.

---

## 13. Testing

- Unit tests for jail, registry schema generation, grammar matching, filename sanitisation, URL validation.
- Tool tests use `tmp_path` and a jail root pointed at it. Never touch the real Desktop in tests.
- Router Tier 1 tests mock the Ollama client. No test may require a running model.
- No test may create a network connection. Mock `requests` and `yt-dlp`.
- Add a `tests/fixtures/commands.yaml` listing spoken-phrase → expected-tool-call pairs, and a single parametrised test that runs the whole list through Tier 0. This file is where new phrasings get added over time.

---

## 14. What Claude Code should hand back at the end of each phase

1. Files created or changed.
2. The acceptance test output, verbatim.
3. Anything appended to `DECISIONS.md`.
4. One short paragraph: what is now working that wasn't before, and the single biggest remaining risk.

Do not summarise the code back. Do not re-explain the architecture.

---

## 15. Known risks to keep in mind while building

| Risk | Mitigation already in this spec |
| --- | --- |
| Whisper hallucinates text on silence | VAD gate + `min_confidence` refusal |
| LLM invents a file path | `parent` is a closed keyword set; jail resolves it |
| Misheard command deletes something | `destructive` tier requires modal confirm; delete is trash, not unlink |
| Model returns malformed JSON | Pydantic validation + one retry + clarification fallback |
| Slow first response kills usability | Tier 0 handles the common 80% with zero model calls |
| Project grows into an unmaintainable "Jarvis" | 300-line module cap, phase gates, explicit non-goals |
| Anyone in the room can issue commands | Push-to-talk only; no wake word in v1 |
| Message sent to the wrong contact | Draft-only, never auto-send; resolved display name spoken back before the user presses Enter |
| Whisper mishears a service name | Target aliases + fuzzy match with a cutoff, clarification below it |
| Stale context makes "that" mean the wrong file | Context TTL, expiry returns a clarification instead of acting |
| Transcripts become a permanent record of everything said near the machine | Retention window, `store_transcripts` off switch, user-only folder permissions, `forget_activity` |
| Memory edits used to cover tracks | Memory and audit are separate stores; `forget_activity` cannot touch `audit.db` |
| Resolver opens a fifth YouTube tab every time | Step 1 of the ladder is always live window detection, never cached |
| Windows 10 user finds Tier 1 silently missing | Startup self-check reads the OS build and states plainly that Ollama needs 22H2+; agent runs Tier 0 |
| Old CPU makes transcription unusably slow | AVX2 probe at startup, auto-downgrade to `base` model, warning printed |
| A user's speech is transcribed poorly and the product is useless to them | Command bar is a first-class equal path, not a fallback |
| Hotkey silently fails to register and the app looks broken | Post-registration verification, visible error, self-check row |
| Hinglish commands fail | Autodetect language, romanised Hindi aliases in Tier 0, Tier 1 for the rest |
| Multilingual voice oversold in marketing | README states per-language limits plainly and points to the command bar |
| Wayland user gets a broken resolver | `XDG_SESSION_TYPE` check disables Step 1; capability table shows it as absent |
| OS-specific code sprawls through the codebase | `grep` gate in Phase 1 acceptance; all OS calls behind `PlatformAdapter` |
| Cracked client bypasses licensing | Accepted as unavoidable; mitigated by putting real capability server-side rather than by obfuscation |
| Licence server outage bricks paying customers | 14-day offline grace, then degrade to local-only — never refuse to start |
| Telemetry leaks transcripts or file names | Enumerated allowlist, no free-text fields, payload assertion test in Phase 8 |
| Compromised licence server pushes malicious config | Server can only flip validated boolean flags; tool definitions and the path jail live in the client binary only |
| Hardware change burns a seat permanently | Self-service release, admin reset, 30-day rolling device window |
| DPDP obligations arrive before the product is compliant | Consent, purpose limitation, retention and erasure built during the 2026 window, ahead of May 2027 |
