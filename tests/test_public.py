import json

import pytest

from mbpost2mztabm import MassBankApiError, MassBankPublicClient


@pytest.fixture
def client():
    with MassBankPublicClient() as client:
        yield client


def test_get_global_info(client, httpx_mock):
    httpx_mock.add_response(
        url="https://repository.massbank.jp/_data/global_info.json",
        json={"title": "Maintenance", "text": "down", "isActive": True},
    )
    info = client.get_global_info()
    assert info.title == "Maintenance"
    assert info.is_active is True


def test_get_statistics(client, httpx_mock):
    httpx_mock.add_response(
        url="https://repository.massbank.jp/api/statistics",
        json={
            "project": {"total": 194, "opened": 109},
            "file": {"count": 44127, "amount": 3169496732259},
        },
    )
    stats = client.get_statistics()
    assert stats.project.total == 194
    assert stats.project.opened == 109
    assert stats.file.count == 44127
    assert stats.file.amount == 3169496732259


def test_get_input_items(client, httpx_mock):
    httpx_mock.add_response(
        url="https://repository.massbank.jp/api/input-items",
        json={"project": [], "sample": []},
    )
    assert client.get_input_items() == {"project": [], "sample": []}


def test_search_cv_terms(client, httpx_mock):
    httpx_mock.add_response(
        url="https://repository.massbank.jp/api/cv-term/species?q=homo",
        json={"list": [{"id": "NCBITaxon:9605", "text": "Homo"}]},
    )
    terms = client.search_cv_terms("species", "homo")
    assert len(terms) == 1
    assert terms[0].id == "NCBITaxon:9605"
    assert terms[0].text == "Homo"


def test_search_cv_terms_unknown_category_is_empty(client, httpx_mock):
    httpx_mock.add_response(
        url="https://repository.massbank.jp/api/cv-term/foo?q=x",
        json={"list": []},
    )
    assert client.search_cv_terms("foo", "x") == []


def test_list_projects(client, httpx_mock):
    httpx_mock.add_response(
        url="https://repository.massbank.jp/api/projects?q=test&limit=2&offset=0",
        json={
            "list": [
                {
                    "mbpostId": "MPST000145",
                    "announcementDate": "2026/09/09",
                    "revision": 0,
                    "location": "MPST000145.0",
                    "fileCount": 163,
                    "title": "A project",
                    "pubmedId": "",
                    "publicationType": "pubmed",
                }
            ],
            "meta": {"total": 109, "from": 1, "to": 1},
        },
    )
    page = client.list_projects(q="test", limit=2, offset=0)
    assert page.total == 109
    assert page.from_ == 1
    assert page.to == 1
    assert len(page.list) == 1
    assert page.list[0].mbpost_id == "MPST000145"
    assert page.list[0].file_count == 163
    assert page.list[0].location == "MPST000145.0"


def test_get_project(client, httpx_mock):
    httpx_mock.add_response(
        url="https://repository.massbank.jp/api/projects/MPST000160",
        json={"mbpostId": "MPST000160", "status": "announced", "title": "T"},
    )
    project = client.get_project("MPST000160")
    assert project.mbpost_id == "MPST000160"
    assert project.status == "announced"


def test_iter_project_list_follows_pagination(client, httpx_mock):
    httpx_mock.add_response(
        url="https://repository.massbank.jp/api/projects?limit=2&offset=0",
        json={"list": [{"mbpostId": "A"}, {"mbpostId": "B"}], "meta": {"total": 3, "from": 1, "to": 2}},
    )
    httpx_mock.add_response(
        url="https://repository.massbank.jp/api/projects?limit=2&offset=2",
        json={"list": [{"mbpostId": "C"}], "meta": {"total": 3, "from": 3, "to": 3}},
    )
    ids = [p.mbpost_id for p in client.iter_project_list(limit=2)]
    assert ids == ["A", "B", "C"]


def test_download_to_bytes(client, httpx_mock):
    httpx_mock.add_response(
        url="https://repository.massbank.jp/api/download/MPST000160.1",
        content=b"PK\x03\x04archive",
    )
    assert client.download("MPST000160.1") == b"PK\x03\x04archive"


def test_download_to_file(client, httpx_mock, tmp_path):
    httpx_mock.add_response(
        url="https://repository.massbank.jp/api/download/MPST000160.1",
        content=b"data",
    )
    target = tmp_path / "out.zip"
    result = client.download("MPST000160.1", target)
    assert result == target
    assert target.read_bytes() == b"data"


def test_send_contact(client, httpx_mock):
    httpx_mock.add_response(
        url="https://repository.massbank.jp/api/contact",
        method="POST",
        status_code=201,
        json={},
    )
    assert client.send_contact({"message": "hi"}) is None
    request = httpx_mock.get_request()
    assert json.loads(request.content) == {"message": "hi"}


def test_error_raises_with_message(client, httpx_mock):
    httpx_mock.add_response(
        url="https://repository.massbank.jp/api/statistics",
        status_code=401,
        json={"message": "Unautorized"},
    )
    with pytest.raises(MassBankApiError) as excinfo:
        client.get_statistics()
    assert excinfo.value.status_code == 401
    assert excinfo.value.message == "Unautorized"


def test_error_with_non_json_body(client, httpx_mock):
    httpx_mock.add_response(
        url="https://repository.massbank.jp/api/statistics",
        status_code=405,
        text="<html>Method not allowed</html>",
        headers={"content-type": "text/html"},
    )
    with pytest.raises(MassBankApiError) as excinfo:
        client.get_statistics()
    assert excinfo.value.status_code == 405
    assert excinfo.value.message is None
