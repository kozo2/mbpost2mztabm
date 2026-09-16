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
:meth:`get_project`              ``GET /api/projects/{mbpostId}``
:meth:`download`                 ``GET /api/download/{location}``
:meth:`send_contact`             ``POST /api/contact``
===============================  =====================================
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator, Mapping
from urllib.parse import quote

import httpx

from .exceptions import MassBankApiError
from .models import (
    CVTerm,
    GlobalInfo,
    Project,
    ProjectPage,
    Statistics,
)

DEFAULT_BASE_URL = "https://repository.massbank.jp"
"""Origin serving the MB-POST API and SPA."""


class MassBankPublicClient:
    """Client for the MB-POST public API tier.

    The client can be used as a context manager::

        with MassBankPublicClient() as client:
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

    def __enter__(self) -> "MassBankPublicClient":
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
        raise MassBankApiError(response.status_code, message, url=str(response.url))

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

    def send_contact(self, data: Mapping[str, Any] | None = None) -> None:
        """Submit the public contact form (``POST /api/contact``).

        The API returns ``201 Created`` on success. The exact payload schema
        is undocumented; pass a mapping of form fields.
        """
        response = self._client.post("/api/contact", json=dict(data or {}))
        self._raise_for_status(response)
