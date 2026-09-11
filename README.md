# vox

Local voice + text controlled desktop agent. It listens for a hotkey, decides
what you meant, and runs it through narrow, typed Python functions — never by
simulating clicks or shelling out to a generic command. See
`docs/VOICE_AGENT_BUILD_SPEC.md` for the full design and `docs/PROGRESS.md`
for build status.

## Install

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
copy config.example.yaml config.yaml
```

`pip install` pulls in everything vox needs, including `faster-whisper`,
`onnxruntime`, `piper-tts`, and, on Windows, `pywin32` and `pystray`. Nothing
is downloaded from the network beyond the packages themselves at this step.

### Low disk space on your system drive?

From Phase 3 on, first run downloads a Whisper model (~500 MB for
`small`/int8) and a Piper voice (~50-100 MB); Tier 1 additionally needs
`qwen3:8b` pulled through Ollama (~5 GB). If your system drive is tight,
redirect all of it to another drive before installing:

```powershell
# Windows (PowerShell), before `pip install`:
$env:PIP_CACHE_DIR = "D:\vox-state\cache\pip"
$env:HF_HOME        = "D:\vox-state\cache\huggingface"
```

and in `config.yaml`:

```yaml
paths:
  state_dir: "D:/vox-state"
```

`state_dir` covers everything vox downloads or writes at runtime (model
caches, `audit.db`, logs) — the app sets `HF_HOME` itself from `state_dir` at
startup if the environment variable isn't already set, so the env var above
is only needed once, for the `pip install` step itself. Piper's voice
downloader takes `download_dir` directly from `state_dir` and needs no
separate environment variable.

## Model download

Nothing is bundled with the app (spec Section 15.8) — everything downloads on
first use, into `state_dir/cache/`:

| Model | When it downloads | Approx. size |
| --- | --- | --- |
| Whisper (`stt.model`, default `small`, int8) | First voice command | ~500 MB |
| Piper voice (`tts.voice`) | First spoken response | ~50-100 MB |
| `qwen3:8b` (Tier 1) | Not automatic — run `ollama pull qwen3:8b` yourself | ~5 GB |

Tier 1 needs [Ollama](https://ollama.com) installed and reachable at
`localhost:11434`, and a machine with at least 16 GB RAM (checked at
startup — see the self-check table below). Below that, or with Ollama
unreachable, the agent still starts and Tier 0 still works; it just can't
handle requests outside Tier 0's fixed grammar.

## Running it

```bash
python run.py                    # tray icon + voice hotkey + command bar (normal use)
python run.py --no-tray          # headless voice-only loop, no display needed
python run.py --text "make a folder called Test"   # one-shot, no mic or tray
```

`run.py` with no arguments prints a startup self-check table (jail roots,
OS/AVX2/RAM/disk, Tier 1 reachability, hotkey availability, platform
capabilities) and then starts the tray icon. Anything red in that table means
the corresponding feature is disabled for this session, not that the app
failed to start (spec invariant: degrade, never brick).

## Hotkeys

| Action | Default | Behaviour |
| --- | --- | --- |
| Voice | `Ctrl+Alt+Space` | **Hold** to talk, release to send. Push-to-talk only — there is no wake word and no always-on listening. |
| Text | `Ctrl+Alt+K` | **Tap** to open the command bar. Type a command, `Enter` to send, `Esc` to close without acting. Type the last 5 commands back with `Up`/`Down`. |
| Abort | `Esc` | Not rebindable. Stops the in-flight action and any speech immediately, anywhere. |

Voice and text are equal, not a fallback pair — everything reachable by
voice is reachable by typing it into the command bar instead, and it's
often faster for exact filenames and URLs.

### Rebinding hotkeys

Right-click the tray icon → **Settings**, click **Change** next to Voice or
Text, then press the new key combination. Changes take effect immediately —
no restart. A combination is rejected outright if it has no modifier
(Ctrl/Alt/Shift/Win) or if it's reserved by Windows (`Ctrl+Alt+Del`,
`Win+L`, `Ctrl+Shift+Esc`, `Alt+Tab`, `Win+Tab`); a handful of common app
shortcuts (`Ctrl+C/V/S/Z`, `Alt+F4`) are accepted with a warning instead of
a hard block. If another application already holds the chord you pick, the
change rolls back to whatever was working before and says so.

You can also edit `config.yaml`'s `hotkeys:` block directly and restart.

## Tray icon

The tray icon's color shows what the agent is doing right now:

| Color | State |
| --- | --- |
| Gray | Idle |
| Green | Listening (voice hotkey held) |
| Blue | Thinking (routing/running a command) |
| Red | Error (the last command's pipeline raised) |

Right-click for **Open command bar**, **Settings**, **Undo last action**
(enabled only inside the undo window below), and **Quit**.

## Guard rails

- **Safe** actions (making a folder, reading the time) run immediately.
- **Medium**-risk actions (opening an app, opening a URL, downloading a
  file) run immediately too, but if they created something, the tray shows
  a toast with a short **undo window** (`security.undo_window_s` in
  `config.yaml`, default 4s) — click **Undo last action** in the tray menu
  within that window to send it to the recycle bin.
- **Destructive** actions (moving something to the recycle bin, locking the
  screen) block on a confirmation dialog naming the exact tool and its
  resolved arguments. **Cancel is the default button** — nothing destructive
  ever runs without an explicit confirmation click.
- **Esc**, anywhere, aborts the in-flight action (a download's chunk loop,
  in-progress speech) and cleans up any partial file.

## Reading the audit log

Every command — voice or text, executed or refused — writes a row to a
SQLite database at `<state_dir>/audit.db` (default `~/.vox/audit.db`)
*before* it runs, and updates that row's status afterward. Rows are never
edited or deleted by the app itself, so it's a reliable record of exactly
what vox was asked to do and what it actually did. Browse it with any SQLite
tool, or from the command line:

```bash
sqlite3 ~/.vox/audit.db "SELECT ts, tool, risk, status, transcript FROM events ORDER BY id DESC LIMIT 20;"
```

Columns: `ts` (UTC timestamp), `transcript` (what was said/typed),
`stt_confidence`, `tier` (`tier0`/`tier1`/`tier2`), `tool`, `args_json`,
`risk`, `confirmed`, `status` (`pending` → one of `executed`, `rejected`,
`failed`, `cancelled`), `error`, `duration_ms`. `args_json` never contains a
raw path outside the jailed roots — anything that would have escaped them is
recorded as `rejected` instead of running.

## Memory: what it remembers, and how to make it forget

The audit log above is a security record; it's never edited. A *separate*
database, `<state_dir>/memory/memory.db`, tracks what's actually useful day
to day — recent activity and the files vox has created — and is meant to
be editable:

- **"What did I do today / yesterday / this week"** answers from this
  database directly, with a fixed template — never by asking a model, so
  it can't invent activity that didn't happen.
- **"Make that a PDF" / "open it"** work because the last file vox created
  is remembered in-process for `memory.context_ttl_minutes` (default 15) of
  inactivity; ask again after that and it'll ask which file you mean
  instead of guessing.
- **"Forget what I did today"** (`forget_activity`) clears rows from
  `memory.db` only — it never touches `audit.db`, and it's a destructive
  action like any other, so it blocks on the same confirmation dialog.
- Set `memory.store_transcripts: false` in `config.yaml` to stop spoken
  text from being written to disk anywhere — activity rows then record
  only which tool ran, not what was said.

`<state_dir>/memory/{contacts,aliases,preferences}.json` are plain,
user-editable JSON files — safe to hand-edit while vox isn't running.

## Development

```bash
pytest                                              # full suite
pytest tests/test_jail.py -v                        # security core
mypy --strict vox/tools vox/security                # mandated subset
python run.py --text "make a folder called Test"    # drive the router without a mic
```

Tests never touch the real Desktop/Documents/Downloads, never open a network
connection, and never require a running Ollama server or a display —  see
`docs/VOICE_AGENT_BUILD_SPEC.md` Section 13.
#   v o x  
 