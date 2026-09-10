"""Importing this package populates REGISTRY (spec Section 12: no global
mutable state except REGISTRY, populated at import)."""
from vox.tools import apps, documents, files, system, web  # noqa: F401
