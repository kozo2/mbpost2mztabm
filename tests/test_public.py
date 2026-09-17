import csv
import io
import json
import os
import tarfile

import pytest

from pymbpost import (
    MbPostApiError,
    MbPostError,
    MbPostPublicClient,
    Project,
    human_readable_size,
)


def _make_tar(*entries):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as archive:
        for name, payload in entries:
            info = tarfile.TarInfo(name)
            if payload is None:
                info.type = tarfile.DIRTYPE
                info.size = 0
                archive.addfile(info)
            else:
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
    return buf.getvalue()


@pytest.fixture
def client():
    with MbPostPublicClient() as client:
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


def test_list_project_ids(client, httpx_mock):
    httpx_mock.add_response(
        url="https://repository.massbank.jp/api/projects?limit=2&offset=0",
        json={"list": [{"mbpostId": "A"}, {"mbpostId": "B"}], "meta": {"total": 3, "from": 1, "to": 2}},
    )
    httpx_mock.add_response(
        url="https://repository.massbank.jp/api/projects?limit=2&offset=2",
        json={"list": [{"mbpostId": "C"}], "meta": {"total": 3, "from": 3, "to": 3}},
    )
    assert client.list_project_ids(limit=2) == ["A", "B", "C"]


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


def test_list_file_names(client, httpx_mock):
    payload = _make_tar(
        ("MB-POST_files_MPST000037.0/", None),
        ("MB-POST_files_MPST000037.0/TSOGA038_Sample_17.d.zip", b"zip"),
        ("MB-POST_files_MPST000037.0/results.xlsx", b"xlsx"),
    )
    httpx_mock.add_response(
        url="https://repository.massbank.jp/api/download/MPST000037.0",
        content=payload,
    )
    names = client.list_file_names("MPST000037.0")
    assert names == ["TSOGA038_Sample_17.d.zip", "results.xlsx"]


def test_list_file_names_keeps_root(client, httpx_mock):
    payload = _make_tar(
        ("root/", None),
        ("root/a.txt", b"a"),
    )
    httpx_mock.add_response(
        url="https://repository.massbank.jp/api/download/MPST000037.0",
        content=payload,
    )
    assert client.list_file_names("MPST000037.0", trim_root=False) == ["root", "root/a.txt"]


def test_list_file_names_accepts_project(client, httpx_mock):
    payload = _make_tar(("root/", None), ("root/a.txt", b"a"))
    httpx_mock.add_response(
        url="https://repository.massbank.jp/api/download/MPST000160.1",
        content=payload,
    )
    project = Project(location="MPST000160.1")
    assert client.list_file_names(project) == ["a.txt"]


def test_list_project_files(client, httpx_mock):
    httpx_mock.add_response(
        url="https://repository.massbank.jp/api/projects/MPST000160.1/files?limit=3&offset=0",
        json={
            "list": [
                {
                    "id": "f1",
                    "name": "a.csv",
                    "size": 10,
                    "type": "result",
                    "status": "server",
                    "checksum": "x",
                    "profiles": [],
                },
                {
                    "id": "f2",
                    "name": "b.d.zip",
                    "size": 20,
                    "type": "raw",
                    "status": "server",
                    "checksum": "y",
                    "profiles": [{"id": "S0000000319", "summary": "6_TSOGA038"}],
                },
            ],
            "meta": {"total": 2, "from": 1, "to": 2, "size": 30},
        },
    )
    page = client.list_project_files("MPST000160.1", limit=3)
    assert page.total == 2
    assert page.size == 30
    assert page.list[0].is_raw is False
    assert page.list[1].is_raw is True
    assert page.list[1].profiles[0].id == "S0000000319"
    assert page.list[1].profiles[0].category == "sample"
    assert page.list[1].profiles[0].prefix == "S"


def test_list_project_files_resolves_bare_id(client, httpx_mock):
    httpx_mock.add_response(
        url="https://repository.massbank.jp/api/projects/MPST000160",
        json={"mbpostId": "MPST000160", "location": "MPST000160.1"},
    )
    httpx_mock.add_response(
        url="https://repository.massbank.jp/api/projects/MPST000160.1/files?limit=100&offset=0",
        json={"list": [], "meta": {"total": 0, "from": 0, "to": 0, "size": 0}},
    )
    assert client.list_project_files("MPST000160").list == []


def test_iter_project_files_follows_pagination(client, httpx_mock):
    httpx_mock.add_response(
        url="https://repository.massbank.jp/api/projects/MPST000160.1/files?limit=2&offset=0",
        json={"list": [{"id": "1"}, {"id": "2"}], "meta": {"total": 3, "from": 1, "to": 2, "size": 0}},
    )
    httpx_mock.add_response(
        url="https://repository.massbank.jp/api/projects/MPST000160.1/files?limit=2&offset=2",
        json={"list": [{"id": "3"}], "meta": {"total": 3, "from": 3, "to": 3, "size": 0}},
    )
    ids = [f.id for f in client.iter_project_files("MPST000160.1", limit=2)]
    assert ids == ["1", "2", "3"]


def test_get_project_file_parses_presets(client, httpx_mock):
    httpx_mock.add_response(
        url="https://repository.massbank.jp/api/projects/MPST000160.1/files/f2",
        json={
            "id": "f2",
            "name": "b.d.zip",
            "size": 20,
            "type": "raw",
            "is_on_server": 1,
            "checksum": "y",
            "presets": [
                {
                    "id": "S0000000319",
                    "category": "sample",
                    "presets": [
                        {
                            "key": "presetName",
                            "value": "6_TSOGA038",
                            "ontologyValue": "",
                            "groupId": "g",
                            "orderKey": 0,
                            "label": "Preset name",
                        },
                        {
                            "key": "species",
                            "value": "Homo sapiens",
                            "ontologyValue": "NCBITaxon:9606",
                            "groupId": "g2",
                            "orderKey": 4,
                            "label": "Species",
                        },
                    ],
                }
            ],
        },
    )
    file = client.get_project_file("MPST000160.1", "f2")
    assert len(file.presets) == 1
    preset = file.presets[0]
    assert preset.category == "sample"
    assert preset.name == "6_TSOGA038"
    assert preset.as_dict()["species"] == "Homo sapiens"
    assert preset.items[1].ontology_value == "NCBITaxon:9606"


def test_get_experimental_presets(client, httpx_mock):
    httpx_mock.add_response(
        url="https://repository.massbank.jp/api/projects/MPST000160.1/files?limit=100&offset=0",
        json={
            "list": [
                {
                    "id": "f2",
                    "name": "b.d.zip",
                    "type": "raw",
                    "profiles": [{"id": "S1", "summary": "s"}],
                }
            ],
            "meta": {"total": 1, "from": 1, "to": 1, "size": 20},
        },
    )
    httpx_mock.add_response(
        url="https://repository.massbank.jp/api/projects/MPST000160.1/files/f2",
        json={
            "id": "f2",
            "name": "b.d.zip",
            "type": "raw",
            "presets": [
                {
                    "id": "S1",
                    "category": "sample",
                    "presets": [{"key": "presetName", "value": "exp1"}],
                }
            ],
        },
    )
    presets = client.get_experimental_presets("MPST000160.1", "b.d.zip")
    assert [p.name for p in presets] == ["exp1"]


def test_get_experimental_presets_mpst000218(client, httpx_mock):
    httpx_mock.add_response(
        url="https://repository.massbank.jp/api/projects/MPST000218",
        json={"mbpostId": "MPST000218", "location": "MPST000218.0", "revision": 0},
    )
    httpx_mock.add_response(
        url="https://repository.massbank.jp/api/projects/MPST000218.0/files?limit=100&offset=0",
        json={
            "list": [
                {
                    "id": "f_0000075193",
                    "name": "cation_69.d.zip",
                    "size": 123,
                    "type": "raw",
                    "status": "server",
                    "checksum": "abc",
                    "profiles": [
                        {"id": "W0000001749", "summary": "Masterhands"},
                        {"id": "A0000001762", "summary": "CE-TOF/MS cation"},
                        {"id": "P0000001760", "summary": "CE-TOF/MS preparation"},
                        {"id": "S0000001757", "summary": "El_day2"},
                    ],
                }
            ],
            "meta": {"total": 1, "from": 1, "to": 1, "size": 123},
        },
    )
    httpx_mock.add_response(
        url="https://repository.massbank.jp/api/projects/MPST000218.0/files/f_0000075193",
        json={
            "id": "f_0000075193",
            "name": "cation_69.d.zip",
            "type": "raw",
            "presets": [
                {
                    "id": "W0000001749",
                    "category": "softwareSetting",
                    "presets": [
                        {"key": "presetName", "value": "Masterhands"},
                        {"key": "software", "value": "Keio masterhands"},
                    ],
                },
                {
                    "id": "A0000001762",
                    "category": "analyticalCondition",
                    "presets": [
                        {"key": "presetName", "value": "CE-TOF/MS cation"},
                        {"key": "methodType", "value": "CE-MS"},
                        {"key": "polarity", "value": "Positive"},
                    ],
                },
                {
                    "id": "P0000001760",
                    "category": "preparation",
                    "presets": [
                        {"key": "presetName", "value": "CE-TOF/MS preparation"},
                        {"key": "compoundsMeasured", "value": "Metabolome"},
                    ],
                },
                {
                    "id": "S0000001757",
                    "category": "sample",
                    "presets": [
                        {"key": "presetName", "value": "El_day2"},
                        {"key": "species", "value": "Eubacterium limosum"},
                        {"key": "sampleCategory", "value": "Medium"},
                    ],
                },
            ],
        },
    )
    presets = client.get_experimental_presets("MPST000218", "cation_69.d.zip")
    by_category = {p.category: p for p in presets}
    assert set(by_category) == {
        "sample",
        "preparation",
        "analyticalCondition",
        "softwareSetting",
    }
    assert by_category["sample"].name == "El_day2"
    assert by_category["sample"].as_dict()["species"] == "Eubacterium limosum"
    assert by_category["analyticalCondition"].as_dict()["methodType"] == "CE-MS"
    assert by_category["softwareSetting"].name == "Masterhands"


def test_get_file_detail(client, httpx_mock):
    httpx_mock.add_response(
        url="https://repository.massbank.jp/api/projects/MPST000218.0/files?limit=100&offset=0",
        json={
            "list": [
                {
                    "id": "f_0000075193",
                    "name": "cation_69.d.zip",
                    "size": 4242,
                    "type": "raw",
                    "status": "server",
                    "checksum": "deadbeef",
                    "profiles": [{"id": "S0000001757", "summary": "El_day2"}],
                }
            ],
            "meta": {"total": 1, "from": 1, "to": 1, "size": 4242},
        },
    )
    httpx_mock.add_response(
        url="https://repository.massbank.jp/api/projects/MPST000218.0/files/f_0000075193",
        json={
            "id": "f_0000075193",
            "name": "cation_69.d.zip",
            "size": 4242,
            "type": "raw",
            "is_on_server": 1,
            "checksum": "deadbeef",
            "presets": [
                {
                    "id": "S0000001757",
                    "category": "sample",
                    "presets": [
                        {"key": "presetName", "value": "El_day2"},
                        {"key": "species", "value": "Eubacterium limosum"},
                    ],
                }
            ],
        },
    )
    detail = client.get_file_detail("MPST000218.0", "cation_69.d.zip")
    assert detail.name == "cation_69.d.zip"
    assert detail.type == "raw"
    assert detail.size == 4242
    assert detail.checksum == "deadbeef"
    assert detail.presets[0].category == "sample"
    assert detail.presets[0].as_dict()["species"] == "Eubacterium limosum"


def test_human_readable_size():
    assert human_readable_size(164519681) == "156.9 MB"
    assert human_readable_size(1024 * 1024) == "1.0 MB"
    assert human_readable_size(512) == "0.5 kB"


def test_get_raw_file_metadata(client, httpx_mock):
    httpx_mock.add_response(
        url="https://repository.massbank.jp/api/projects/MPST000218",
        json={"mbpostId": "MPST000218", "location": "MPST000218.0", "revision": 0},
    )
    httpx_mock.add_response(
        url="https://repository.massbank.jp/api/projects/MPST000218.0/files?limit=100&offset=0",
        json={
            "list": [
                {
                    "id": "f_raw",
                    "name": "cation_69.d.zip",
                    "size": 167330210,
                    "type": "raw",
                    "checksum": "b406369c",
                    "profiles": [{"id": "S1", "summary": "El_day2"}],
                },
                {
                    "id": "f_result",
                    "name": "results.xlsx",
                    "size": 1000,
                    "type": "result",
                    "checksum": "ffff",
                    "profiles": [],
                },
            ],
            "meta": {"total": 2, "from": 1, "to": 2, "size": 167331210},
        },
    )
    httpx_mock.add_response(
        url="https://repository.massbank.jp/api/projects/MPST000218.0/files/f_raw",
        json={
            "id": "f_raw",
            "name": "cation_69.d.zip",
            "size": 167330210,
            "type": "raw",
            "is_on_server": 1,
            "checksum": "b406369c",
            "presets": [
                {
                    "id": "S1",
                    "category": "sample",
                    "presets": [
                        {"key": "presetName", "value": "El_day2"},
                        {"key": "species", "value": "Eubacterium limosum"},
                    ],
                }
            ],
        },
    )
    metadata = client.get_raw_file_metadata("MPST000218")
    assert len(metadata) == 1
    entry = metadata[0]
    assert entry["file_name"] == "cation_69.d.zip"
    assert entry["file_type"] == "raw"
    assert entry["file_size"] == "159.6 MB"
    assert entry["file_size_bytes"] == 167330210
    assert entry["md5_checksum"] == "b406369c"
    assert entry["profile"] == [
        {
            "id": "S1",
            "category": "sample",
            "name": "El_day2",
            "fields": {"presetName": "El_day2", "species": "Eubacterium limosum"},
        }
    ]


def _mock_input_items(httpx_mock):
    httpx_mock.add_response(
        url="https://repository.massbank.jp/api/input-items",
        json={
            "project": [],
            "sample": [{"name": "presetName"}, {"name": "species"}],
            "preparation": [{"name": "presetName"}],
            "analyticalCondition": [
                {"name": "presetName"},
                {"name": "ionization"},
                {"name": "polarity"},
            ],
            "softwareSetting": [{"name": "presetName"}, {"name": "software"}],
        },
    )


def _mock_mpst000218(httpx_mock):
    httpx_mock.add_response(
        url="https://repository.massbank.jp/api/projects/MPST000218",
        json={"mbpostId": "MPST000218", "location": "MPST000218.0", "revision": 0},
    )
    httpx_mock.add_response(
        url="https://repository.massbank.jp/api/projects/MPST000218.0/files?limit=100&offset=0",
        json={
            "list": [
                {
                    "id": "f_raw",
                    "name": "cation_69.d.zip",
                    "size": 167330210,
                    "type": "raw",
                    "checksum": "b406369c",
                    "profiles": [{"id": "S1", "summary": "El_day2"}],
                },
                {
                    "id": "f_result",
                    "name": "results.xlsx",
                    "size": 1000,
                    "type": "result",
                    "checksum": "ffff",
                    "profiles": [],
                },
            ],
            "meta": {"total": 2, "from": 1, "to": 2, "size": 167331210},
        },
    )
    httpx_mock.add_response(
        url="https://repository.massbank.jp/api/projects/MPST000218.0/files/f_raw",
        json={
            "id": "f_raw",
            "name": "cation_69.d.zip",
            "size": 167330210,
            "type": "raw",
            "is_on_server": 1,
            "checksum": "b406369c",
            "presets": [
                {
                    "id": "A1",
                    "category": "analyticalCondition",
                    "presets": [
                        {"key": "presetName", "value": "CE-TOF/MS cation"},
                        {"key": "ionization", "value": "ESI"},
                        {"key": "polarity", "value": "Positive"},
                    ],
                },
                {
                    "id": "S1",
                    "category": "sample",
                    "presets": [
                        {"key": "presetName", "value": "El_day2"},
                        {"key": "species", "value": "Eubacterium limosum"},
                    ],
                },
            ],
        },
    )


def test_export_profile_metadata_csv(client, httpx_mock, tmp_path):
    _mock_input_items(httpx_mock)
    _mock_mpst000218(httpx_mock)
    out = client.export_profile_metadata_csv(tmp_path / "profiles.csv", projects=["MPST000218"])

    assert out == tmp_path / "profiles.csv"
    with out.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 1
    row = rows[0]
    assert row["mbpost_id"] == "MPST000218"
    assert row["location"] == "MPST000218.0"
    assert row["file_name"] == "cation_69.d.zip"
    assert row["file_type"] == "raw"
    assert row["file_size"] == "159.6 MB"
    assert row["md5_checksum"] == "b406369c"
    assert row["analyticalCondition.id"] == "A1"
    assert row["analyticalCondition.ionization"] == "ESI"
    assert row["analyticalCondition.polarity"] == "Positive"
    assert row["sample.presetName"] == "El_day2"
    assert row["sample.species"] == "Eubacterium limosum"
    assert row["preparation.presetName"] == ""


def test_iter_profile_metadata_rows(client, httpx_mock):
    _mock_mpst000218(httpx_mock)
    rows = list(client.iter_profile_metadata_rows(["MPST000218"]))
    assert len(rows) == 1
    assert rows[0]["analyticalCondition.ionization"] == "ESI"


@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("MBPOST_RUN_INTEGRATION"),
    reason="set MBPOST_RUN_INTEGRATION=1 to hit the live MB-POST API",
)
def test_get_experimental_presets_mpst000218_live():
    with MbPostPublicClient(timeout=60) as client:
        presets = client.get_experimental_presets("MPST000218", "cation_69.d.zip")
    by_category = {p.category: p for p in presets}
    assert set(by_category) == {
        "sample",
        "preparation",
        "analyticalCondition",
        "softwareSetting",
    }
    assert by_category["sample"].name == "El_day2"
    assert by_category["sample"].as_dict()["species"] == "Eubacterium limosum"
    assert by_category["analyticalCondition"].as_dict()["methodType"] == "CE-MS"
    assert by_category["softwareSetting"].name == "Masterhands"


def test_get_experimental_presets_missing_file(client, httpx_mock):
    httpx_mock.add_response(
        url="https://repository.massbank.jp/api/projects/MPST000160.1/files?limit=100&offset=0",
        json={"list": [], "meta": {"total": 0, "from": 0, "to": 0, "size": 0}},
    )
    with pytest.raises(MbPostError):
        client.get_experimental_presets("MPST000160.1", "nope.d.zip")


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
    with pytest.raises(MbPostApiError) as excinfo:
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
    with pytest.raises(MbPostApiError) as excinfo:
        client.get_statistics()
    assert excinfo.value.status_code == 405
    assert excinfo.value.message is None
