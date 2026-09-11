# vox

Local voice + text controlled desktop agent. See `docs/VOICE_AGENT_BUILD_SPEC.md`
for the full design and `docs/PROGRESS.md` for build status.

Full install/usage docs land in Phase 5. For now:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
copy config.example.yaml config.yaml

python run.py --text "make a folder called Test"
pytest
mypy --strict vox/tools vox/security
```

## Low disk space on your system drive?

From Phase 3 on, `pip install` pulls in `faster-whisper`/`ctranslate2`/`onnxruntime`/
`piper-tts`, and first run downloads a Whisper model (~500 MB for `small`/int8) and a
Piper voice (~50-100 MB). If your system drive is tight, redirect all of it to another
drive before installing:

```bash
# Windows (PowerShell), before `pip install`:
$env:PIP_CACHE_DIR = "D:\vox-state\cache\pip"
$env:HF_HOME        = "D:\vox-state\cache\huggingface"
```

and in `config.yaml`:

```yaml
paths:
  state_dir: "D:/vox-state"
```

`state_dir` covers everything vox downloads or writes at runtime (model caches,
`audit.db`, logs) — the app sets `HF_HOME` itself from `state_dir` at startup if the
environment variable isn't already set, so the env var above is only needed once, for
the `pip install` step itself. Piper's voice downloader takes `download_dir` directly
from `state_dir` and needs no separate environment variable.
