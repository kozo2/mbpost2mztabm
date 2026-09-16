"""Access the public (no-auth) endpoints of the MB-POST API.

MB-POST is the MassBank project submission/curation system served from
``https://repository.massbank.jp``. This package covers the public tier
documented in ``mbpost_api.md`` section 2.1.
"""

from .exceptions import MassBankApiError, MassBankError
from .models import (
    CVTerm,
    FileStatistics,
    GlobalInfo,
    Project,
    ProjectPage,
    ProjectStatistics,
    Statistics,
)
from .public import DEFAULT_BASE_URL, MassBankPublicClient

__all__ = [
    "DEFAULT_BASE_URL",
    "CVTerm",
    "FileStatistics",
    "GlobalInfo",
    "MassBankApiError",
    "MassBankError",
    "MassBankPublicClient",
    "Project",
    "ProjectPage",
    "ProjectStatistics",
    "Statistics",
]

__version__ = "0.1.0"
