"""Typed representations of the MB-POST public API responses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def human_readable_size(size: int) -> str:
    """Format a byte count the way the MB-POST UI does.

    Mirrors the SPA's ``humanReadableFileSize``: divide by 1024 and pick the
    first unit (``kB``, ``MB``, ``GB``, ...) that keeps the value under 1024,
    then round to one decimal.

    >>> human_readable_size(164519681)
    '156.9 MB'
    """
    value = abs(float(size))
    units = ["kB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB"]
    index = -1
    while True:
        value /= 1024
        index += 1
        if value < 1024 or index >= len(units) - 1:
            break
    return f"{value:.1f} {units[index]}"


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


PRESET_CATEGORY_BY_PREFIX: dict[str, str] = {
    "S": "sample",
    "P": "preparation",
    "A": "analyticalCondition",
    "W": "softwareSetting",
}
"""Maps the leading letter of a preset id to its preset category."""


@dataclass(frozen=True)
class PresetRef:
    """A preset reference attached to a file in the file-list response.

    The file-list endpoint embeds a compact ``{id, summary}`` form of each
    preset; the full dataset is only returned by the single-file endpoint
    (see :class:`ExperimentalPreset`).
    """

    id: str = ""
    summary: str = ""

    @property
    def prefix(self) -> str:
        """The category letter encoded in the id, e.g. ``S``."""
        return self.id[:1].upper()

    @property
    def category(self) -> str:
        """Preset category derived from the id prefix (e.g. ``sample``)."""
        return PRESET_CATEGORY_BY_PREFIX.get(self.prefix, "")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PresetRef":
        return cls(id=str(data.get("id", "")), summary=str(data.get("summary", "")))


@dataclass(frozen=True)
class PresetItem:
    """A single key/value entry of an experimental preset."""

    key: str = ""
    value: str = ""
    ontology_value: str = ""
    group_id: str = ""
    order_key: int = 0
    label: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PresetItem":
        return cls(
            key=str(data.get("key", "")),
            value=str(data.get("value", "")),
            ontology_value=str(data.get("ontologyValue", "")),
            group_id=str(data.get("groupId", "")),
            order_key=_as_int(data.get("orderKey")),
            label=str(data.get("label", "")),
        )


@dataclass(frozen=True)
class ExperimentalPreset:
    """The full experimental preset dataset attached to a file.

    Returned as the ``presets`` field of
    ``GET /api/projects/{location}/files/{fileId}``.
    """

    id: str = ""
    category: str = ""
    items: list[PresetItem] = field(default_factory=list)

    @property
    def prefix(self) -> str:
        return self.id[:1].upper()

    @property
    def name(self) -> str:
        """Value of the ``presetName`` item, if present."""
        for item in self.items:
            if item.key == "presetName":
                return item.value
        return ""

    def as_dict(self) -> dict[str, str]:
        """Flatten the items into a ``key -> value`` mapping."""
        return {item.key: item.value for item in self.items}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExperimentalPreset":
        return cls(
            id=str(data.get("id", "")),
            category=str(data.get("category", "")),
            items=[PresetItem.from_dict(item) for item in data.get("presets") or []],
        )


@dataclass(frozen=True)
class ProjectFile:
    """A file entry of an announced project.

    The ``profiles`` field is populated by the list endpoint
    (``GET /api/projects/{location}/files``) and holds compact preset
    references; the ``presets`` field is populated by the single-file endpoint
    (``GET /api/projects/{location}/files/{fileId}``) and holds the full
    experimental preset datasets. Only ``raw`` files carry presets.
    """

    id: str = ""
    name: str = ""
    size: int = 0
    type: str = ""
    status: str = ""
    is_on_server: bool = True
    checksum: str = ""
    profiles: list[PresetRef] = field(default_factory=list)
    presets: list[ExperimentalPreset] = field(default_factory=list)

    @property
    def is_raw(self) -> bool:
        return self.type == "raw"

    def detail_metadata(self) -> dict[str, Any]:
        """Return the values shown in the MB-POST file "Detail" dialog.

        Keys mirror the dialog rows: ``file_name``, ``file_type``,
        ``file_size`` (human readable, as displayed), ``md5_checksum`` and
        ``profile`` (the experimental preset metadata set). ``file_size_bytes``
        is included for convenience. Useful for ``raw`` files, which carry the
        profile; for other types :attr:`presets` is empty.
        """
        return {
            "file_name": self.name,
            "file_type": self.type,
            "file_size": human_readable_size(self.size),
            "file_size_bytes": self.size,
            "md5_checksum": self.checksum,
            "profile": [
                {
                    "id": preset.id,
                    "category": preset.category,
                    "name": preset.name,
                    "fields": preset.as_dict(),
                }
                for preset in self.presets
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectFile":
        return cls(
            id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            size=_as_int(data.get("size")),
            type=str(data.get("type", "")),
            status=str(data.get("status", "")),
            is_on_server=bool(data.get("is_on_server", True)),
            checksum=str(data.get("checksum", "")),
            profiles=[PresetRef.from_dict(item) for item in data.get("profiles") or []],
            presets=[ExperimentalPreset.from_dict(item) for item in data.get("presets") or []],
        )


@dataclass(frozen=True)
class FilePage:
    """Paginated envelope returned by ``GET /api/projects/{location}/files``.

    ``meta`` uses Zend-style ``total`` / ``from`` / ``to`` keys plus ``size``
    (total bytes of the matching files).
    """

    list: list[ProjectFile] = field(default_factory=list)
    total: int = 0
    from_: int = 0
    to: int = 0
    size: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FilePage":
        meta = data.get("meta") or {}
        return cls(
            list=[ProjectFile.from_dict(item) for item in data.get("list") or []],
            total=_as_int(meta.get("total")),
            from_=_as_int(meta.get("from")),
            to=_as_int(meta.get("to")),
            size=_as_int(meta.get("size")),
        )
