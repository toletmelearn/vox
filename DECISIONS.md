# Decisions and declined features

Every assumption made where the spec was ambiguous, and every feature
declined under the invariants in CLAUDE.md, goes here.

## Phase 1

### Extended `PlatformAdapter` beyond the spec's literal listing
Spec Section 3A.5 lists the `PlatformAdapter` Protocol methods, but three
things are needed that aren't in that list, and adding them elsewhere would
put OS-specific code outside `vox/platform/`, breaking invariant 4:

- `os_build() -> str` — a human-readable OS/build string for the startup
  self-check (Section 3A.1 asks for the OS build to be checked "not just by
  trying to connect [to Ollama]"; there was no adapter method to hang that
  off).
- `cpu_supports_avx2() -> bool` — Section 3A.2 asks for an AVX2 probe via
  "`cpuinfo` or a platform-level probe." `py-cpuinfo` is not in the Section 3
  dependency list, so this is implemented as a real platform-level probe:
  `ctypes.windll.kernel32.IsProcessorFeaturePresent` on Windows, `/proc/cpuinfo`
  parsing on Linux. No new dependency added.
- `open_path(path: Path) -> bool` — opening a file/folder in the OS default
  app (`os.startfile` on Windows, `xdg-open` on Linux) is inherently
  OS-specific and has no other adapter method to use. Needed by
  `tools/files.py::open_path`, a Phase 1 deliverable.

### `set_volume` is unimplemented on Windows (capability absent, not faked)
Spec 3A.1 casually mentions "pycaw volume control" as something that "works
identically" on Windows 10/11, but `pycaw` (and the `comtypes` it depends on)
is **not** in the Section 3 pinned dependency list. Per the invariant "never
invent a dependency ... not listed in Section 3," `set_volume` raises
`UnsupportedCapability` on Windows rather than either (a) adding an
unlisted dependency or (b) shipping an imprecise hack (e.g. blind
volume-up/down key presses that can't reach an exact level). This is a gap
to close explicitly when `tools/system.py::set_volume` is built in Phase 2 —
either amend Section 3 to add `pycaw`+`comtypes`, or accept relative-only
volume control. Not decided here; flagging for that session.

### `notify()` does not yet produce a real toast/balloon
Spec 3A.1 mandates pystray balloon notifications only, but `pystray` is a
Phase 5 deliverable (tray icon). Until a tray icon instance exists there is
nothing to attach a balloon to. Phase 1/2's `notify()` logs at INFO instead
of silently no-op'ing. Real balloon wiring happens in Phase 5 when
`ui/tray.py` is built.

### `find_installed_app` is unimplemented in both concrete adapters
Its signature takes a `Target` (spec 3A.5), but `Target` is defined in
`resolver/targets.py`, a Phase 7 deliverable that does not exist yet. Typed
as `target: Any` for now with a comment; both adapters raise
`UnsupportedCapability`. Real implementation (registry `App Paths`, Start
Menu scan, `wmctrl`/process match) lands in Phase 7 alongside `Target`.

### Minimal text-command stub in `app.py`, not a real Tier 0 grammar
Phase 1's acceptance requires `python run.py --text "make a folder called
Test"` to work end-to-end, but `router/tier0_grammar.py` is an explicit
Phase 2 deliverable. `app.py::_stub_parse` implements exactly the two
patterns needed to pass Phase 1's acceptance (`create_folder`, `get_time`)
using the same regex shape the spec gives for Tier 0's `create_folder`
pattern in Section 7, so Phase 2 can drop this stub in favour of the real
grammar file without behavioural surprise. This stub is intentionally not
named `tier0_grammar.py` and is not registered as a router tier, to avoid it
being mistaken for the Phase 2 deliverable.

### Filename sanitisation runs on the resolved leaf component, not the raw input
Section 8.3 says filename sanitisation must strip `\ / : * ? " < > |` among
other things. Section 8's acceptance test for Phase 1 requires
`"make a folder called ../../evil"` to be **rejected by the jail**, not
silently sanitised into a harmless folder named `evil` and created anyway.
Resolution: `resolve_in_jail()` runs first on the raw (unsanitised) name, so
path-traversal sequences are caught as an escape attempt (`JailViolation`,
audit status `rejected`). Only after that succeeds is
`sanitize_filename()` applied to the final path's leaf component — which by
construction never contains a separator — to strip characters that are
illegal on the filesystem but not a jail-escape vector (`:`, `*`, `?`, etc.).

### Only `audit.db` is created in Phase 1, not the full `~/.vox/` tree
Section 6C's full state directory tree (`memory/`, `artifacts/`, `cache/`,
`transcripts/`) is an explicit Phase 6 deliverable. Phase 1 only needs the
audit log, so `security/audit.py` creates `state_dir/audit.db` and its
parent directory; nothing else under `~/.vox/` is created yet.

### `mypy` and `types-PyYAML` added to dev dependencies
Not listed in Section 3's Dev list (only `pytest`, `pytest-mock`), but
CLAUDE.md's working rules mandate `mypy --strict` on `vox/tools/` and
`vox/security/`. Treated as tooling, not a new runtime/feature dependency,
so it doesn't trigger the "never invent a dependency" invariant.

### Declined: no additional generic execution primitive
No feature in Phase 1 needed one. Recorded here per the standing instruction
in invariant 1 — nothing to add yet.

## Phase 2

### Tier 0 grammar omits patterns for tools that don't exist yet
Section 7's pattern list includes phrasings for `open_target`, `play_on_target`,
`compose_whatsapp_message`, and `recall_activity` — none of which are built
until Phase 6/7. Matching those phrasings now would route to a tool name the
registry doesn't have, which `app.py`'s guard layer already handles
gracefully ("I don't have that tool") but would be a dead pattern with no
real behaviour. Deferred to their respective phases instead.

### Context-pronoun patterns always return a clarification
"open it", "make that a PDF", etc. are registered in the grammar (so the
phrasing is recognised) but always produce `RouteResult(clarification=...)`
rather than resolving a pronoun, because `Context.last_artifact` doesn't
exist until Phase 6. This matches the spec's own fallback rule ("if context
is empty or expired, return a clarification") — it's honest about the
current state rather than silently no-op'ing.

### Hindi/Hinglish grammar coverage is intentionally minimal
Only the literal example from spec Section 6F is implemented: a verb-alias
substitution map for verbs whose word order matches English (kholo→open,
chalao→play, dhoondo→search, bhejo→send, band karo→stop) plus one dedicated
reversed-word-order pattern for folder creation ("`<name>` ke naam se ek
folder banao"). Building a general Hindi/Hinglish grammar engine is exactly
what the spec says Tier 1 is for ("Route anything Tier 0 misses to Tier 1");
Tier 0's job here is the cheap, high-value literal case only.

### `set_volume` remains unsupported on Windows
Reaffirming the Phase 1 decision now that the tool is actually wired up: no
`pycaw`/`comtypes` in Section 3, so `WindowsAdapter.set_volume` still raises
`UnsupportedCapability` and the tool reports `ok=False` with a clear spoken
reason. Linux's `pactl`-backed version works. Still flagging this as a gap
to close deliberately (amend Section 3, or accept relative-only volume) —
not decided here.

### `convert_docx_to_pdf` added to `PlatformAdapter`
`tools/documents.py::convert_to_pdf`'s second fallback (Word COM via
`pywin32`) is inherently Windows-specific, so it's a new adapter method
(`windows.py` implements it with `win32com.client.DispatchEx` +
`pythoncom.CoInitialize`/`CoUninitialize`; `linux.py`/`null.py` raise
`UnsupportedCapability`) rather than living directly in `tools/documents.py`
— keeping the grep gate (invariant 4) clean. The LibreOffice `soffice` path
stays directly in `tools/documents.py` since checking for a binary on PATH
isn't OS-specific branching.

### Pillow: fixed for real, not suppressed
Per explicit instruction: Pillow was already implicitly sanctioned by
Section 3 ("pystray + pillow # tray icon", Windows-only) but missing from
`pyproject.toml`. Added it properly (`pillow; sys_platform == 'win32'`),
moved the `PIL.ImageGrab` import to module level in `windows.py`, and
removed the `type: ignore[import-not-found]` that was papering over the
missing declaration. `capabilities()` no longer needs a runtime
`try/except ImportError` probe for "screenshot" either, since Pillow is now
guaranteed present on Windows.

### `python-docx` / `reportlab` / `yt-dlp`: no stubs exist anywhere, unlike Pillow
Unlike the Pillow case above, these three genuinely ship no type
information and no `types-*` stub package exists to install — there is no
equivalent "real fix." Scoped via the standard mypy mechanism for
stub-less third-party libraries (`[[tool.mypy.overrides]]` with
`ignore_missing_imports = true` for `docx.*`, `reportlab.*`, `yt_dlp.*` in
`pyproject.toml`), rather than a `type: ignore` comment scattered across
every call site. One unavoidable single-site ignore remains:
`win32com.client.DispatchEx(...)  # type: ignore[no-untyped-call]` in
`convert_docx_to_pdf` — COM dynamic dispatch has no static type to give it.

### PDF test verification avoids adding a PDF-parsing dependency
`tests/test_documents.py` checks `create_pdf`'s output "opens cleanly" by
checking the `%PDF-`/`%%EOF` structural markers rather than parsing it with
a library like `pypdf`, which is not in Section 3. `python-docx`'s own
`Document(path)` re-open is used for the `.docx` case since that's already
a pinned dependency doing real structural validation.

### `open_app`'s default map has some bare exe names that need a per-machine path
`edge`, `firefox`, `word`, `excel`, `vscode`, `terminal` default to bare exe
names (`msedge.exe`, `winword.exe`, etc.) that rely on the OS resolving them
via PATH, which several of these are not on by default. This mirrors
`config.example.yaml`'s own "extend per machine" comment for `chrome`'s
full path — not a bug, just a caveat worth stating plainly rather than
pretending every machine's defaults will work unmodified.
