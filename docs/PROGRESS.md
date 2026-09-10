# Progress

## Current phase
**Phase 2 — Tier 0 grammar + remaining tools** (done)

Next up: **Phase 3 — Voice in, voice out**. Needed spec sections: 0, 3, 6D, 8, 12, 13.

## Phase status

| Phase | Name | Status |
| --- | --- | --- |
| 1 | Skeleton, safety core, platform adapter | Done |
| 2 | Tier 0 grammar + remaining tools | Done |
| 3 | Voice in, voice out | Not started |
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
- Free disk on workdir volume: 2.9 GB at last self-check — tight against the
  spec's "fail self-check under 10 GB free" guidance; revisit before Phase 3
  (models land there).

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
