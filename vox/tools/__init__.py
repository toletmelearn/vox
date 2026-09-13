"""Importing this package populates REGISTRY (spec Section 12: no global
mutable state except REGISTRY, populated at import)."""
from vox.tools import (  # noqa: F401
    apps,
    documents,
    files,
    memory_tools,
    messaging,
    router_tools,
    system,
    targets,
    web,
)
