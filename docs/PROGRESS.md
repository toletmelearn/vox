# Progress

## Current phase
**Phase 3 — Voice in, voice out** (done, verified end-to-end with real hardware)

Next up: **Phase 4 — Tier 1 local LLM**. Needed spec sections: 0, 3, 7, 8, 12, 13.

## Phase status

| Phase | Name | Status |
| --- | --- | --- |
| 1 | Skeleton, safety core, platform adapter | Done |
| 2 | Tier 0 grammar + remaining tools | Done |
| 3 | Voice in, voice out | Done (verified live; 1 perf risk open) |
| 4 | Tier 1 local LLM | Not started |
| 5 | Guard rails, tray, command bar, packaging prep | Not started |
| 6 | Memory store | Not started |
| 7 | Target resolver and messaging | Not started |
| 8 | Licensing, telemetry and packaging | Not started |
| 9 | GUI fallback (OPTIONAL — needs explicit go-ahead) | Not started |

## Environment notes
- OS: Windows 10 22H2 (build 19045)
- Python version: 3.14.3
- RAM / AVX2 / GPU: 15.9 GB RAM, AVX2 present, GPU not probed (not needed yet)
- Ollama installed: not checked yet (Phase 4)
- CPU: 4 cores. Real end-to-end Whisper "small"/int8 latency measured at
  ~11-13s for a ~4s clip — far above spec's 2s target. Investigated (ruled
  out beam_size, added explicit cpu_threads); likely the fixed-cost 30s
  encoder pass, or this tool-execution sandbox throttling CPU differently
  from what the OS self-check reports. **Verify on real end-user hardware
  before relying on the 2s figure.** See DECISIONS.md.
- C: drive has ~3 GB free (98% used) — real constraint on this dev machine,
  not a spec requirement. Fixed by redirecting `paths.state_dir` to
  `D:/dev/vox-state` in the real (gitignored) `config.yaml`, plus
  `PIP_CACHE_DIR`/`HF_HOME` for install-time downloads. See README.md
  "Low disk space" section and DECISIONS.md Phase 3.
- Audio hardware confirmed present and working: real mic input devices and
  speaker output enumerate correctly via sounddevice; TTS played audibly
  through real speakers during Phase 3 verification.
- Default input device uses the legacy MME driver, whose stream-startup
  latency (~0.06-0.36s observed) means a hold shorter than that records
  nothing. Comfortably clear of it for any real hold (0.7s+ all worked).
- Voice hotkey is `ctrl+shift+space` on this machine, not the spec example's
  `ctrl+alt+space` — that chord is claimed by another application here
  (confirmed via a real `RegisterHotKey` probe, not a guess). Real
  `config.yaml` also sets `stt.min_confidence: 0.35` (spec's 0.55 default
  rejected valid real speech — see DECISIONS.md).

## Session log

- 2026-09-10 — Phase 1 built: config.py, logging_setup.py, platform/ (base,
  windows, linux, null, factory), security/jail.py, security/audit.py,
  tools/registry.py, tools/files.py, tools/system.py (get_time only),
  router/base.py (core contracts), app.py (guard/audit wiring + a temporary
  minimal text-command stub standing in for Tier 0 until Phase 2), run.py.
  30 tests pass; mypy --strict passes on the whole vox/ package, not just
  the mandated tools/security subset. Grep gate clean. Real acceptance run
  against the actual machine created `~/Desktop/Test` and `~/.vox/audit.db`
  — left in place as evidence per the acceptance instructions; delete
  `~/Desktop/Test` if unwanted. Nothing broke. See DECISIONS.md for the
  three PlatformAdapter methods added beyond the spec's literal listing,
  and for why set_volume is unimplemented on Windows for now.

- 2026-09-10 — Phase 2 built: router/tier0_grammar.py (real Tier 0 grammar,
  replacing Phase 1's _stub_parse), tools/web.py, tools/documents.py,
  tools/apps.py, and the rest of tools/system.py (set_volume,
  take_screenshot, lock_screen). Added `convert_docx_to_pdf` to
  PlatformAdapter (Word COM on Windows) for the LibreOffice-not-present
  fallback. Fixed the Pillow dependency properly (added to pyproject.toml,
  removed the type: ignore) rather than leaving it suppressed. 58 tests pass
  (28 new); mypy --strict clean on the whole vox/ package; grep gate clean.
  Found and fixed a real regex-ordering bug during manual acceptance
  testing ("search for X" was matching the bare "search" alternative first,
  producing "Searching for for X"). Real acceptance runs against the actual
  machine left behind `~/Desktop/Physics Notes`, `~/Desktop/Screenshot_*.png`,
  `~/Documents/Draft Report.docx`, and `~/Documents/Draft Report.pdf` —
  left in place as evidence, delete if unwanted. Nothing broke. See
  DECISIONS.md for: which Section 7 patterns were deferred to Phase 6/7
  (tools don't exist yet), why context-pronoun patterns always clarify,
  the minimal-by-design Hindi/Hinglish coverage, and the mypy stub-override
  approach for python-docx/reportlab/yt-dlp.

- 2026-09-10 — Phase 3 built: audio/capture.py (hotkey-gated mic capture:
  ChordTracker, Recorder, HotkeyCapture), audio/vad.py (Silero VAD, ONNX
  model vendored directly rather than via the `silero-vad` PyPI package —
  it hard-depends on torch), audio/tts.py (Piper wrapper), stt/whisper.py
  (faster-whisper wrapper), hotkey wiring in app.py/run.py
  (`start_voice_mode`), and unified the text/voice pipeline into one
  `route_and_execute(transcript)` per spec Section 6D ("do not fork the
  pipeline"). 81 tests pass (23 new); mypy --strict clean on the whole
  vox/ package (bumped python_version to 3.14 — numpy's stubs need 3.12+
  syntax); grep gate clean. Found and fixed a real bug:
  `resolve_in_jail` didn't catch `OSError` from `Path.resolve()` on an
  unreachable UNC path, which intermittently broke a Phase 1 jail test
  depending on network adapter state — now caught and treated as
  `JailViolation` (regression test added).

  Real end-to-end verification: real Piper TTS audio played through actual
  speakers and re-recorded via hardware loopback; real Whisper model
  downloaded and correctly transcribed that audio ("Open Chrome and search
  for Laravel Q tutorials, please" — "queue"→"Q" is a reasonable ASR
  slip). Two open risks surfaced by this real-hardware testing, not yet
  resolved as of this entry (see the 2026-09-11 entry below for the
  resolution): (1) Silero VAD's positive "has speech" case didn't trigger
  on synthetic TTS audio from either Piper or Windows SAPI; (2) Whisper CPU
  latency (~11-13s for a ~4s clip) well above the spec's 2s target.

  The literal "hold the hotkey and speak" flow could not be run end-to-end
  by a human in this session (no physical keyboard interaction available to
  the agent); every component it's built from was verified individually
  instead. Real acceptance/verification runs downloaded real models to
  `D:/dev/vox-state/cache/` (redirected off the system drive) and are left
  in place; no stray files left on the real Desktop this phase.

- 2026-09-11 — Live acceptance-testing session with the user actually
  holding the hotkey and speaking, following up on Phase 3's two open
  risks. Found and fixed four real, previously-unknown bugs, all in
  DECISIONS.md with full investigation detail:
  1. **Hotkey collision**: `ctrl+alt+space` was silently intercepted by
     another application on this machine before vox's listener ever saw
     it. Added a real verification step (`PlatformAdapter.verify_hotkey_available`,
     Windows `RegisterHotKey`/`UnregisterHotKey` probe — spec Section 6E's
     "verify it took," not an assumption) and switched to
     `ctrl+shift+space`/`ctrl+shift+k`.
  2. **Blocking work on pynput's hook-callback thread**: `_on_press`/
     `_on_release` called the mic stream and (on release) the full
     VAD+Whisper+TTS pipeline inline, on the thread Windows expects a
     low-level keyboard hook to return from near-instantly. Moved all real
     work to a dedicated worker thread via a queue.
  3. **The actual VAD bug** (this is what open risk #1 above turned out to
     be): `speech_probability()` was missing Silero v5's required
     64-sample lookback context prepended to each 512-sample chunk. Without
     it, every input — synthetic TTS and real human speech alike — scored
     near zero regardless of content. Fixed; verified against real speech
     that previously failed (`has_speech` flipped False→True).
  4. **`stt.min_confidence: 0.55` rejects valid real speech**: real
     confidence scores on this mic/Whisper-small setup land 0.3-0.7, never
     near 1.0. Lowered to 0.35 in this machine's `config.yaml`.

  Also found: MME input-device stream-startup latency (~0.06-0.36s
  observed) means holds shorter than that record nothing — a real, minor
  UX limitation, not a bug, documented rather than fixed (any real-length
  hold clears it easily).

  Final confirmation, with the user actually speaking into the real
  microphone: "Hi, can you miss me?" and "Bye." both transcribed accurately
  and correctly fell through as non-Tier-0 phrases; **"what's the time" was
  heard, transcribed, routed, executed, and the correct answer was spoken
  back** through real speakers. This exercises every stage of Phase 3's
  acceptance criteria with real audio, not mocks. 91 tests pass (2 new: a
  real-speech fixture regression test for the VAD bug, a context-carried
  test); mypy --strict and the grep gate remain clean. Whisper CPU latency
  (open risk #2) is **still open** — real speech now works correctly, just
  slower than the spec's 2s target; needs checking on non-sandboxed
  hardware. See DECISIONS.md "Phase 3 acceptance: fully verified
  end-to-end with real hardware, not just believed fixed" for the full
  closing summary.
