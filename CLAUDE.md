# vox — project instructions

Local voice + text controlled desktop agent. Python 3.11+. Windows 10 22H2 / 11 primary, Linux secondary.

## The spec

`VOICE_AGENT_BUILD_SPEC.md` in this directory is the complete brief. It is long — **do not read it all every session.**

- At the start of a session, read `PROGRESS.md` to find the current phase.
- Then read **only** the spec sections that phase needs (each phase in Section 10 names them).
- Sections 0, 8 and this file always apply.

## Invariants — never violate these, in any phase

1. **No generic execution tool.** No `run_shell`, `run_python`, `eval`, or any tool taking a command string. If a feature seems to need one, write it in `DECISIONS.md` and do not build it.
2. **Every path goes through the jail** (`security/jail.py`). No tool touches the filesystem without `resolve_in_jail`.
3. **`parent` is a closed keyword set** (`desktop`, `documents`, `downloads`, `workdir`). The LLM never authors an absolute path.
4. **No OS-specific code outside `vox/platform/`.** `sys.platform`, `platform.system()` and `os.name` must not appear anywhere else. This is checked by grep in Phase 1 acceptance.
5. **Audit rows are written before execution**, never edited or deleted by application code. Memory and audit are separate stores.
6. **WhatsApp drafts, never sends.** No synthesised keystrokes in the messaging path, ever.
7. **Telemetry has no free-text fields.** Never transmit transcripts, file names, paths, contact names, message bodies, or URLs.
8. **Push-to-talk only.** No wake word, no always-on listening in v1.
9. **Degrade, never brick.** Missing Ollama, missing capability, expired licence, no network — the agent still starts and Tier 0 still works.
10. **Text input is an equal path to voice**, not a fallback. Both feed the same router.

## Working rules

- Build in phase order (Section 10). One phase per session. **Stop at the end of each phase and report** — do not start the next one.
- Run the phase's acceptance tests and paste the real output. Never claim a test passes without running it.
- Every module under 300 lines. Split rather than grow.
- Tools return `ToolResult(ok=False, ...)` on failure; they do not raise. Only `JailViolation` propagates.
- Type hints everywhere. `mypy --strict` must pass on `vox/tools/` and `vox/security/`.
- No bare `except:`.
- Tests never touch the real Desktop, never open a network connection, never require a running model.

## Files you maintain

- `PROGRESS.md` — current phase, what's done, what's next. Update at the end of every session.
- `DECISIONS.md` — every assumption you made where the spec was ambiguous, and every feature you declined to build under the invariants above.

## Commands

```bash
python run.py --text "make a folder called Test"   # drive the router without a mic
pytest                                              # full suite
pytest tests/test_jail.py -v                        # security core
mypy --strict vox/tools vox/security
```

## End-of-phase report format

1. Files created or changed
2. Acceptance test output, verbatim
3. Anything appended to `DECISIONS.md`
4. One paragraph: what now works that didn't, and the single biggest remaining risk

Do not summarise the code back. Do not re-explain the architecture.
