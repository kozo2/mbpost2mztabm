"""Access the public (no-auth) endpoints of the MB-POST API.

MB-POST is the MassBank project submission/curation system served from
``https://repository.massbank.jp``. This package covers the public tier
documented in ``mbpost_api.md`` section 2.1.
"""

from .exceptions import MassBankApiError, MassBankError
from .models import (
    PRESET_CATEGORY_BY_PREFIX,
    CVTerm,
    ExperimentalPreset,
    FilePage,
    FileStatistics,
    GlobalInfo,
    PresetItem,
    PresetRef,
    Project,
    ProjectFile,
    ProjectPage,
    ProjectStatistics,
    Statistics,
    human_readable_size,
)
from .public import DEFAULT_BASE_URL, MassBankPublicClient

__all__ = [
    "DEFAULT_BASE_URL",
    "PRESET_CATEGORY_BY_PREFIX",
    "CVTerm",
    "ExperimentalPreset",
    "FilePage",
    "FileStatistics",
    "GlobalInfo",
    "MassBankApiError",
    "MassBankError",
    "MassBankPublicClient",
    "PresetItem",
    "PresetRef",
    "Project",
    "ProjectFile",
    "ProjectPage",
    "ProjectStatistics",
    "Statistics",
    "human_readable_size",
]

__version__ = "0.1.0"
