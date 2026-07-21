"""NEXCISION: precise region-based excision from NEXUS matrices."""

from ._version import VERSION as __version__
from .core import (
    FilterResult,
    NexusFilterError,
    Region,
    filter_nexus_file,
    filter_nexus_text,
    load_regions,
)

__all__ = [
    "FilterResult",
    "NexusFilterError",
    "Region",
    "filter_nexus_file",
    "filter_nexus_text",
    "load_regions",
]
