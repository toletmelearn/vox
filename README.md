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
