"""Importing this package populates REGISTRY (spec Section 12: no global
mutable state except REGISTRY, populated at import)."""
from vox.tools import apps, documents, files, router_tools, system, web  # noqa: F401
