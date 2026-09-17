"""Synchronous client for the public (no-auth) MB-POST endpoints.

Implements section 2.1 of ``mbpost_api.md``:

===============================  =====================================
Method                           Endpoint
===============================  =====================================
:meth:`get_global_info`          ``GET /_data/global_info.json``
:meth:`get_statistics`           ``GET /api/statistics``
:meth:`get_input_items`          ``GET /api/input-items``
:meth:`search_cv_terms`          ``GET /api/cv-term/{category}?q=...``
:meth:`list_projects`            ``GET /api/projects``
:meth:`get_project`                ``GET /api/projects/{mbpostId}``
:meth:`list_project_files`       ``GET /api/projects/{location}/files``
:meth:`iter_project_files`       ``GET /api/projects/{location}/files``
:meth:`get_project_file`         ``GET /api/projects/{location}/files/{fileId}``
:meth:`get_file_detail`          ``GET /api/projects/{location}/files/{fileId}``
:meth:`get_experimental_presets` ``GET /api/projects/{location}/files/{fileId}``
:meth:`iter_raw_file_details`    ``GET /api/projects/{location}/files/{fileId}``
:meth:`list_raw_file_details`    ``GET /api/projects/{location}/files/{fileId}``
:meth:`get_raw_file_metadata`    ``GET /api/projects/{location}/files/{fileId}``
:meth:`iter_profile_metadata_rows` ``GET /api/projects/{location}/files/{fileId}``
:meth:`export_profile_metadata_csv` ``GET /api/projects/{location}/files/{fileId}``
:meth:`download`                 ``GET /api/download/{location}``
:meth:`iter_file_names`          ``GET /api/download/{location}`` (tar listing)
:meth:`list_file_names`          ``GET /api/download/{location}`` (tar listing)
:meth:`send_contact`             ``POST /api/contact``
===============================  =====================================
"""

from __future__ import annotations

import csv
import io
import tarfile
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping
from urllib.parse import quote

import httpx

from .exceptions import MbPostApiError, MbPostError
from .models import (
    CVTerm,
    ExperimentalPreset,
    FilePage,
    GlobalInfo,
    Project,
    ProjectFile,
    ProjectPage,
    Statistics,
    human_readable_size,
)

PRESET_CATEGORIES: tuple[str, ...] = (
    "sample",
    "preparation",
    "analyticalCondition",
    "softwareSetting",
)
"""Preset categories, in the order used for exported columns."""

DEFAULT_BASE_URL = "https://repository.massbank.jp"
"""Origin serving the MB-POST API and SPA."""


class _HttpByteStream(io.RawIOBase):
    """Adapt an iterator of byte chunks into a read-only file-like object.

    Lets :mod:`tarfile` stream-parse an HTTP response without buffering the
    whole archive in memory.
    """

    def __init__(self, chunks: Iterable[bytes]) -> None:
        self._chunks = iter(chunks)
        self._buffer = b""

    def readable(self) -> bool:
        return True

    def readinto(self, target: bytearray) -> int:
        while not self._buffer:
            try:
                self._buffer = bytes(next(self._chunks))
            except StopIteration:
                return 0
        size = min(len(target), len(self._buffer))
        target[:size] = self._buffer[:size]
        self._buffer = self._buffer[size:]
        return size


class MbPostPublicClient:
    """Client for the MB-POST public API tier.

    The client can be used as a context manager::

        with MbPostPublicClient() as client:
            stats = client.get_statistics()

    :param base_url: API origin. Defaults to :data:`DEFAULT_BASE_URL`.
    :param timeout: Request timeout in seconds.
    :param transport: Optional ``httpx`` transport (useful for tests).
    :param headers: Extra headers sent with every request.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        *,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            transport=transport,
            headers=headers,
            follow_redirects=True,
        )

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._client.close()

    def __enter__(self) -> "MbPostPublicClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    @staticmethod
    def _quote(value: str) -> str:
        return quote(str(value), safe="")

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.is_success:
            return
        message: str | None = None
        try:
            body = response.json()
        except ValueError:
            body = None
        if isinstance(body, dict):
            raw = body.get("message")
            if raw is not None:
                message = str(raw)
        raise MbPostApiError(response.status_code, message, url=str(response.url))

    def _get(self, path: str, params: Mapping[str, Any] | None = None) -> httpx.Response:
        response = self._client.get(path, params=params)
        self._raise_for_status(response)
        return response

    def get_global_info(self) -> GlobalInfo:
        """Fetch the static maintenance notice (``/_data/global_info.json``)."""
        return GlobalInfo.from_dict(self._get("/_data/global_info.json").json())

    def get_statistics(self) -> Statistics:
        """Fetch global project/file statistics (``/api/statistics``)."""
        return Statistics.from_dict(self._get("/api/statistics").json())

    def get_input_items(self) -> dict[str, Any]:
        """Fetch submission-form field/preset definitions (``/api/input-items``).

        The schema is undocumented, so the raw JSON object is returned.
        """
        return self._get("/api/input-items").json()

    def search_cv_terms(self, category: str, query: str = "") -> list[CVTerm]:
        """Look up controlled-vocabulary terms.

        Unknown categories are not errors: the API returns an empty list.

        :param category: One of the CV categories (e.g. ``species``,
            ``msInstrument``). See the API reference for the full list.
        :param query: Autocomplete query string.
        """
        path = f"/api/cv-term/{self._quote(category)}"
        params = {"q": query} if query else None
        body = self._get(path, params=params).json()
        return [CVTerm.from_dict(item) for item in body.get("list") or []]

    def list_projects(
        self,
        *,
        q: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> ProjectPage:
        """List announced/public projects (``/api/projects``).

        :param q: Optional free-text search query.
        :param limit: Maximum number of records to return.
        :param offset: Zero-based record offset.
        """
        params: dict[str, Any] = {}
        if q is not None:
            params["q"] = q
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset
        return ProjectPage.from_dict(self._get("/api/projects", params=params or None).json())

    def get_project(self, mbpost_id: str) -> Project:
        """Fetch a single public project by its MB-POST id (e.g. ``MPST000160``)."""
        path = f"/api/projects/{self._quote(mbpost_id)}"
        return Project.from_dict(self._get(path).json())

    def iter_project_list(
        self,
        *,
        q: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Iterator[Project]:
        """Yield every matching project, following Zend-style pagination.

        :param q: Optional free-text search query.
        :param limit: Page size.
        :param offset: Starting offset.
        """
        current = offset
        while True:
            page = self.list_projects(q=q, limit=limit, offset=current)
            yield from page.list
            if not page.list:
                return
            current += len(page.list)
            if page.to and page.total and current >= page.total:
                return

    def iter_project_ids(
        self,
        *,
        q: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Iterator[str]:
        """Yield the MB-POST id of every public project.

        This walks the paginated ``/api/projects`` endpoint, so it makes
        ``ceil(total / limit)`` requests.

        :param q: Optional free-text search query.
        :param limit: Page size.
        :param offset: Starting offset.
        """
        for project in self.iter_project_list(q=q, limit=limit, offset=offset):
            yield project.mbpost_id

    def list_project_ids(
        self,
        *,
        q: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[str]:
        """Return the MB-POST ids of all public projects.

        Convenience wrapper around :meth:`iter_project_ids`. Use the iterator
        instead for large result sets.
        """
        return list(self.iter_project_ids(q=q, limit=limit, offset=offset))

    def download(self, location: str, destination: str | Path | None = None) -> bytes | Path:
        """Download an announced project's archive (``/api/download/{location}``).

        This streams the whole archive in a single response; the API exposes
        no reliable range/pagination semantics.

        :param location: Project location, e.g. ``MPST000160.1``.
        :param destination: If given, the archive is streamed to this path and
            the :class:`~pathlib.Path` is returned. Otherwise the raw bytes are
            returned (may be very large).
        """
        path = f"/api/download/{self._quote(location)}"
        with self._client.stream("GET", path) as response:
            self._raise_for_status(response)
            if destination is None:
                return response.read()
            target = Path(destination)
            with target.open("wb") as handle:
                for chunk in response.iter_bytes():
                    handle.write(chunk)
            return target

    def _resolve_location(self, project: Project | str) -> str:
        """Return the ``mbpostId.revision`` location for a project reference.

        Accepts a :class:`~pymbpost.models.Project`, a location string
        (``MPST000160.1``) or a bare MB-POST id (``MPST000160``). A bare id is
        resolved through :meth:`get_project`, which always carries a
        ``location``. File routes are keyed on the location, not the id.
        """
        if isinstance(project, Project):
            if project.location:
                return project.location
            return self.get_project(project.mbpost_id).location
        value = str(project)
        if "." in value:
            return value
        return self.get_project(value).location

    def list_project_files(
        self,
        project: Project | str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> FilePage:
        """List the files of a public project.

        Endpoint: ``GET /api/projects/{location}/files``. The route is keyed on
        the project **location** (``mbpostId.revision``); the bare
        ``/api/projects/{mbpostId}/files`` form returns ``404`` even for
        announced projects, so a :class:`~pymbpost.models.Project` or a
        location string should be passed.

        :param project: Project, location (``MPST000160.1``) or bare id.
        :param limit: Page size.
        :param offset: Zero-based record offset.
        """
        location = self._resolve_location(project)
        path = f"/api/projects/{self._quote(location)}/files"
        params = {"limit": limit, "offset": offset}
        return FilePage.from_dict(self._get(path, params=params).json())

    def iter_project_files(
        self,
        project: Project | str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> Iterator[ProjectFile]:
        """Yield every file of a public project, following pagination."""
        current = offset
        while True:
            page = self.list_project_files(project, limit=limit, offset=current)
            yield from page.list
            if not page.list:
                return
            current += len(page.list)
            if page.to and page.total and current >= page.total:
                return

    def get_project_file(self, project: Project | str, file_id: str) -> ProjectFile:
        """Fetch a single file entry including its full experimental presets.

        Endpoint: ``GET /api/projects/{location}/files/{fileId}``.
        """
        location = self._resolve_location(project)
        path = f"/api/projects/{self._quote(location)}/files/{self._quote(file_id)}"
        return ProjectFile.from_dict(self._get(path).json())

    def find_project_file(self, project: Project | str, name: str) -> ProjectFile | None:
        """Return the file whose ``name`` matches exactly, or ``None``.

        This walks the paginated file list; the returned entry carries compact
        preset references in :attr:`ProjectFile.profiles`.
        """
        for file in self.iter_project_files(project):
            if file.name == name:
                return file
        return None

    def get_file_detail(
        self,
        project: Project | str,
        file_name: str,
    ) -> ProjectFile:
        """Return the full detail record of a named project file.

        Resolves the file by name in the public file list, then fetches its
        single-file entry. The result carries the file metadata shown in the
        MB-POST "Detail" view (``name``, ``type``, ``size``, ``checksum``) plus
        the **Profile** metadata set under :attr:`ProjectFile.presets` (the full
        experimental preset datasets, only present on ``raw`` files).

        :param project: Project, location (``MPST000160.1``) or bare id.
        :param file_name: Exact file name, e.g. ``cation_69.d.zip``.
        :raises MbPostError: if no file with that name exists.
        """
        location = self._resolve_location(project)
        file = self.find_project_file(location, file_name)
        if file is None:
            raise MbPostError(f"no file named {file_name!r} in {project!r}")
        return self.get_project_file(location, file.id)

    def get_experimental_presets(
        self,
        project: Project | str,
        file_name: str,
    ) -> list[ExperimentalPreset]:
        """Return the experimental preset dataset (Profile) for a named file.

        Equivalent to :meth:`get_file_detail` then reading
        :attr:`ProjectFile.presets`. Each preset carries ``category`` and
        key/value/ontology items. Only ``raw`` files have presets; other file
        types return an empty list.

        :param project: Project, location (``MPST000160.1``) or bare id.
        :param file_name: Exact file name, e.g.
            ``TSOGA038_p_20241106_Sample_17.d.zip``.
        :raises MbPostError: if no file with that name exists.
        """
        return self.get_file_detail(project, file_name).presets

    def iter_raw_file_details(
        self,
        project: Project | str,
        *,
        limit: int = 100,
    ) -> Iterator[ProjectFile]:
        """Yield the detail record of every ``raw`` file in a project.

        This mirrors the rows of the entry page whose "File name" column has
        type ``raw``. It fetches the file list once, then one single-file
        detail request per raw file (for the full Profile/preset metadata), so
        it makes ``1 + n_raw`` requests. Use laziness to stop early.
        """
        location = self._resolve_location(project)
        for file in self.iter_project_files(location, limit=limit):
            if file.is_raw:
                yield self.get_project_file(location, file.id)

    def list_raw_file_details(
        self,
        project: Project | str,
        *,
        limit: int = 100,
    ) -> list[ProjectFile]:
        """Return the detail records of all ``raw`` files in a project.

        Eager version of :meth:`iter_raw_file_details`; see that method for the
        request cost.
        """
        return list(self.iter_raw_file_details(project, limit=limit))

    def get_raw_file_metadata(
        self,
        project: Project | str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return the "Detail" metadata values for every ``raw`` file.

        Convenience wrapper around :meth:`list_raw_file_details`: each item is
        the dict from :meth:`ProjectFile.detail_metadata` (``file_name``,
        ``file_type``, ``file_size``, ``md5_checksum``, ``profile``), i.e. the
        values displayed after clicking "Detail" on a ``raw`` row of the entry
        page, e.g. https://repository.massbank.jp/entry/MPST000218.

        ::

            >>> meta = client.get_raw_file_metadata("MPST000218")
            >>> meta[0]["file_name"]
            'cation_Blank_4.d.zip'
            >>> meta[0]["file_type"]
            'raw'
            >>> {p["category"] for p in meta[0]["profile"]}
            {'sample', 'preparation', 'analyticalCondition', 'softwareSetting'}
        """
        return [file.detail_metadata() for file in self.iter_raw_file_details(project, limit=limit)]

    def _profile_csv_fieldnames(self) -> list[str]:
        """Build the CSV header from the authoritative input-items vocabulary.

        Columns are the file metadata followed, per preset category, by
        ``<category>.id`` and one ``<category>.<field>`` per field defined by
        ``/api/input-items``. The schema is stable regardless of which presets
        a given file happens to carry.
        """
        items = self.get_input_items()
        columns = [
            "mbpost_id",
            "location",
            "file_name",
            "file_type",
            "file_size",
            "file_size_bytes",
            "md5_checksum",
        ]
        for category in PRESET_CATEGORIES:
            columns.append(f"{category}.id")
            for field in items.get(category) or []:
                name = field.get("name") if isinstance(field, dict) else None
                if name:
                    columns.append(f"{category}.{name}")
        return columns

    def iter_profile_metadata_rows(
        self,
        projects: Iterable[Project | str] | None = None,
        *,
        file_limit: int = 100,
        project_limit: int = 200,
    ) -> Iterator[dict[str, str]]:
        """Yield one flattened CSV row per ``raw`` file across projects.

        Each row contains the file metadata plus the **Profile** metadata set
        flattened to ``<category>.<field>`` columns (see
        :meth:`_profile_csv_fieldnames`). Only ``raw`` files are included.

        :param projects: Projects (or ids/locations) to scan. Defaults to all
            public projects via :meth:`iter_project_list`.
        :param file_limit: Page size for each project's file list.
        :param project_limit: Page size when enumerating all public projects.

        This performs one file-list request per project plus one detail request
        per raw file, so exporting every project can make tens of thousands of
        requests.
        """
        source: Iterable[Project | str]
        if projects is None:
            source = self.iter_project_list(limit=project_limit)
        else:
            source = projects

        for project in source:
            if isinstance(project, Project):
                location = self._resolve_location(project)
                mbpost_id = project.mbpost_id or location.split(".")[0]
            else:
                reference = str(project)
                if "." in reference:
                    location = reference
                    mbpost_id = reference.split(".")[0]
                else:
                    resolved = self.get_project(reference)
                    location = resolved.location
                    mbpost_id = resolved.mbpost_id or reference

            for file in self.iter_project_files(location, limit=file_limit):
                if not file.is_raw:
                    continue
                detail = self.get_project_file(location, file.id)
                row: dict[str, str] = {
                    "mbpost_id": mbpost_id,
                    "location": location,
                    "file_name": detail.name,
                    "file_type": detail.type,
                    "file_size": human_readable_size(detail.size),
                    "file_size_bytes": str(detail.size),
                    "md5_checksum": detail.checksum,
                }
                for preset in detail.presets:
                    category = preset.category
                    row[f"{category}.id"] = preset.id
                    for key, value in preset.as_dict().items():
                        row[f"{category}.{key}"] = value
                yield row

    def export_profile_metadata_csv(
        self,
        destination: str | Path,
        *,
        projects: Iterable[Project | str] | None = None,
        file_limit: int = 100,
        project_limit: int = 200,
    ) -> Path:
        """Export the Profile metadata of all ``raw`` files to a CSV file.

        Writes one row per raw file across the given projects (default: every
        public project), including the file metadata and the full Profile
        metadata set flattened to ``<category>.<field>`` columns. Values are
        streamed to disk, so the export uses constant memory.

        :param destination: Output CSV path.
        :param projects: Projects (or ids/locations) to scan. Defaults to all
            public projects.
        :param file_limit: Page size for each project's file list.
        :param project_limit: Page size when enumerating all public projects.
        :returns: The :class:`~pathlib.Path` written.

        ::

            client.export_profile_metadata_csv("mbpost_profiles.csv")
            client.export_profile_metadata_csv(
                "one_project.csv", projects=["MPST000218"]
            )
        """
        target = Path(destination)
        fieldnames = self._profile_csv_fieldnames()
        with target.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in self.iter_profile_metadata_rows(
                projects, file_limit=file_limit, project_limit=project_limit
            ):
                writer.writerow(row)
        return target

    def iter_file_names(
        self,
        project: Project | str,
        *,
        trim_root: bool = True,
    ) -> Iterator[str]:
        """Yield the file names of a project's downloadable archive.

        Unlike :meth:`iter_project_files` (which queries the lightweight public
        file-list endpoint), this reads names from the tar archive returned by
        ``/api/download/{location}``. The archive is stream-parsed, but ``tar``
        has no random access: walking every name reads the whole (often
        multi-hundred-MB) archive. Stop iterating early to avoid downloading
        the remainder.

        :param project: A :class:`~pymbpost.models.Project` (its
            ``location`` is used) or a location string such as ``MPST000160.1``.
        :param trim_root: Strip the archive's top-level directory prefix
            (e.g. ``MB-POST_files_MPST000160.1/``) from each name.
        """
        location = self._resolve_location(project)
        path = f"/api/download/{self._quote(location)}"
        with self._client.stream("GET", path) as response:
            self._raise_for_status(response)
            stream = _HttpByteStream(response.iter_bytes())
            root: str | None = None
            with tarfile.open(fileobj=stream, mode="r|") as archive:
                for member in archive:
                    name = member.name
                    if root is None and member.isdir():
                        root = name.rstrip("/") + "/"
                    if trim_root and root:
                        if name.rstrip("/") + "/" == root:
                            continue
                        if name.startswith(root):
                            name = name[len(root) :]
                    if name:
                        yield name

    def list_file_names(
        self,
        project: Project | str,
        *,
        trim_root: bool = True,
    ) -> list[str]:
        """Return the file names of a project's downloadable archive.

        Convenience wrapper around :meth:`iter_file_names` that reads the
        entire archive; see that method for the caveats.
        """
        return list(self.iter_file_names(project, trim_root=trim_root))

    def send_contact(self, data: Mapping[str, Any] | None = None) -> None:
        """Submit the public contact form (``POST /api/contact``).

        The API returns ``201 Created`` on success. The exact payload schema
        is undocumented; pass a mapping of form fields.
        """
        response = self._client.post("/api/contact", json=dict(data or {}))
        self._raise_for_status(response)
