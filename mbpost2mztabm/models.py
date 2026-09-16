"""Typed representations of the MB-POST public API responses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class GlobalInfo:
    """Contents of ``GET /_data/global_info.json`` (static maintenance notice)."""

    title: str = ""
    text: str = ""
    is_active: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GlobalInfo":
        return cls(
            title=data.get("title", ""),
            text=data.get("text", ""),
            is_active=bool(data.get("isActive", False)),
        )


@dataclass(frozen=True)
class ProjectStatistics:
    total: int = 0
    opened: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectStatistics":
        return cls(total=_as_int(data.get("total")), opened=_as_int(data.get("opened")))


@dataclass(frozen=True)
class FileStatistics:
    count: int = 0
    amount: int = 0
    """Total size in bytes."""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FileStatistics":
        return cls(count=_as_int(data.get("count")), amount=_as_int(data.get("amount")))


@dataclass(frozen=True)
class Statistics:
    """Contents of ``GET /api/statistics``."""

    project: ProjectStatistics = field(default_factory=ProjectStatistics)
    file: FileStatistics = field(default_factory=FileStatistics)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Statistics":
        return cls(
            project=ProjectStatistics.from_dict(data.get("project") or {}),
            file=FileStatistics.from_dict(data.get("file") or {}),
        )


@dataclass(frozen=True)
class CVTerm:
    """A controlled-vocabulary term returned by ``/api/cv-term/{category}``."""

    id: str = ""
    text: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CVTerm":
        return cls(id=str(data.get("id", "")), text=str(data.get("text", "")))


@dataclass(frozen=True)
class Project:
    """A public project record.

    Fields mirror ``GET /api/projects`` entries and
    ``GET /api/projects/{mbpostId}``. Dates are kept as the ``YYYY/MM/DD``
    strings returned by the API. ``location`` is the value accepted by
    :meth:`MassBankPublicClient.download`.
    """

    mbpost_id: str = ""
    announcement_date: str = ""
    revision: int = 0
    location: str = ""
    created_at: str = ""
    modified_at: str = ""
    file_count: int = 0
    title: str = ""
    keywords: str = ""
    description: str = ""
    pubmed_id: str = ""
    publication_type: str = ""
    principal_investigator: str = ""
    affiliation: str = ""
    note: str = ""
    submitter: str = ""
    status: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Project":
        return cls(
            mbpost_id=str(data.get("mbpostId", "")),
            announcement_date=str(data.get("announcementDate", "")),
            revision=_as_int(data.get("revision")),
            location=str(data.get("location", "")),
            created_at=str(data.get("createdAt", "")),
            modified_at=str(data.get("modifiedAt", "")),
            file_count=_as_int(data.get("fileCount")),
            title=str(data.get("title", "")),
            keywords=str(data.get("keywords", "")),
            description=str(data.get("description", "")),
            pubmed_id=str(data.get("pubmedId", "")),
            publication_type=str(data.get("publicationType", "")),
            principal_investigator=str(data.get("principalInvestigator", "")),
            affiliation=str(data.get("affiliation", "")),
            note=str(data.get("note", "")),
            submitter=str(data.get("submitter", "")),
            status=str(data.get("status", "")),
        )


@dataclass(frozen=True)
class ProjectPage:
    """Paginated envelope returned by ``GET /api/projects``.

    ``meta`` uses Zend-style ``total`` / ``from`` / ``to`` keys.
    """

    list: list[Project] = field(default_factory=list)
    total: int = 0
    from_: int = 0
    to: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectPage":
        meta = data.get("meta") or {}
        return cls(
            list=[Project.from_dict(item) for item in data.get("list") or []],
            total=_as_int(meta.get("total")),
            from_=_as_int(meta.get("from")),
            to=_as_int(meta.get("to")),
        )
