# Usage

Reference for the `mbpost2mztabm` public API client. It covers the no-auth
endpoints of the MB-POST repository (`https://repository.massbank.jp`); see
[`../mbpost_api.md`](../mbpost_api.md) for the reverse-engineered HTTP details.

- [Installation](#installation)
- [Quick start](#quick-start)
- [Client lifecycle](#client-lifecycle)
- [Method reference](#method-reference)
  - [Service info](#service-info)
  - [Controlled vocabulary](#controlled-vocabulary)
  - [Projects](#projects)
  - [Project files](#project-files)
  - [Experimental presets (Profile)](#experimental-presets-profile)
  - [Downloads and archives](#downloads-and-archives)
  - [Contact](#contact)
- [Models](#models)
- [Exceptions](#exceptions)
- [Endpoint map](#endpoint-map)
- [Notes and gotchas](#notes-and-gotchas)

## Installation

The project uses [uv](https://docs.astral.sh/uv/):

```bash
uv sync --extra dev      # runtime + test dependencies
```

Or add it to an existing environment:

```bash
uv add httpx
```

## Quick start

```python
from mbpost2mztabm import MassBankPublicClient

with MassBankPublicClient() as client:
    stats = client.get_statistics()
    print(stats.project.total, stats.file.count)

    for project in client.iter_project_list(q="lipidomics"):
        print(project.mbpost_id, project.title)

    detail = client.get_file_detail("MPST000218", "cation_69.d.zip")
    for preset in detail.presets:
        print(preset.category, preset.name)
```

All requests are plain synchronous HTTP. The client only needs `httpx`; no
credentials are required for any method documented here.

## Client lifecycle

```python
MassBankPublicClient(
    base_url: str = "https://repository.massbank.jp",
    *,
    timeout: float = 30.0,
    transport: httpx.BaseTransport | None = None,
    headers: Mapping[str, str] | None = None,
)
```

| Parameter | Meaning |
|---|---|
| `base_url` | API origin. Override for a mirror or a test server. |
| `timeout` | Request timeout in seconds. |
| `transport` | Custom `httpx` transport (useful for testing with `httpx.MockTransport`). |
| `headers` | Extra headers sent with every request. |

The client holds a connection pool, so reuse one instance and close it when
done. Use it as a context manager (recommended) or call `close()` manually:

```python
client = MassBankPublicClient()
try:
    client.get_statistics()
finally:
    client.close()
```

## Method reference

Project references throughout accept any of:

- a `Project` object — its `location` is used;
- a **location** string `"MPST000160.1"` (`mbpostId.revision`);
- a bare **mbpostId** string `"MPST000160"` — resolved automatically via
  `get_project`.

### Service info

#### `get_global_info() -> GlobalInfo`

Static maintenance notice from `/_data/global_info.json`.

```python
info = client.get_global_info()
if info.is_active:
    print(info.title, info.text)
```

#### `get_statistics() -> Statistics`

Global counts from `/api/statistics`.

```python
stats = client.get_statistics()
stats.project.total     # all projects
stats.project.opened    # announced/open projects
stats.file.count        # files
stats.file.amount       # total bytes
```

#### `get_input_items() -> dict`

Submission-form field/preset definitions from `/api/input-items`. The schema is
undocumented, so the raw JSON object is returned (keys: `project`, `sample`,
`preparation`, `analyticalCondition`, `softwareSetting`).

```python
items = client.get_input_items()
for field in items["sample"]:
    print(field["name"], field["label"], field["type"])
```

### Controlled vocabulary

#### `search_cv_terms(category, query="") -> list[CVTerm]`

Autocomplete CV terms from `/api/cv-term/{category}?q={query}`. Unknown
categories are not errors; they return an empty list.

```python
for term in client.search_cv_terms("species", "human"):
    print(term.id, term.text)   # NCBITaxon:9606  Homo sapiens
```

Categories: `sampleCategory`, `species`, `sampleType`, `organTissue`,
`cellType`, `cellLine`, `disease`, `compoundsMeasured`, `methodType`,
`chromatographyType`, `msInstrument`, `ionization`, `instrumentMode`,
`fragmentationMethod`, `software`.

### Projects

#### `list_projects(*, q=None, limit=None, offset=None) -> ProjectPage`

One page of public (announced) projects from `/api/projects`.

```python
page = client.list_projects(q="lipidomics", limit=20, offset=0)
page.total            # total matching
page.list             # list[Project]
```

#### `iter_project_list(*, q=None, limit=100, offset=0) -> Iterator[Project]`

Lazily yields every matching project, following pagination.

```python
for project in client.iter_project_list(q="lipidomics"):
    ...
```

#### `list_project_ids(*, q=None, limit=100, offset=0) -> list[str]`

All matching MB-POST ids, eagerly collected.

#### `iter_project_ids(*, q=None, limit=100, offset=0) -> Iterator[str]`

Lazily yields every matching MB-POST id.

```python
ids = client.list_project_ids()                  # ['MPST000001', ...]
first_ten = [p for p in client.iter_project_ids(limit=10)][:10]
```

#### `get_project(mbpost_id) -> Project`

Public project detail from `/api/projects/{mbpostId}`. Adds `status`
(`"announced"`, `"submitted"`, `"opened"`, ...).

```python
project = client.get_project("MPST000160")
project.location     # "MPST000160.1"  -> used by download/file routes
project.file_count
```

### Project files

The file routes are keyed on the project **location**, not the bare id.

#### `list_project_files(project, *, limit=100, offset=0) -> FilePage`

One page of file records from `/api/projects/{location}/files`. Raw files carry
compact preset references in `profiles`.

```python
page = client.list_project_files("MPST000160.1")
page.total
for f in page.list:
    print(f.name, f.type, [(p.category, p.summary) for p in f.profiles])
```

#### `iter_project_files(project, *, limit=100, offset=0) -> Iterator[ProjectFile]`

Lazily yields every file record, following pagination.

#### `find_project_file(project, name) -> ProjectFile | None`

Exact-name lookup in the file list (returns the compact list entry, without the
full `presets`).

```python
f = client.find_project_file("MPST000218", "cation_69.d.zip")
if f is not None:
    print(f.id, f.checksum)
```

#### `get_project_file(project, file_id) -> ProjectFile`

Single-file detail from `/api/projects/{location}/files/{fileId}`, when you
already know the file id.

```python
detail = client.get_project_file("MPST000218.0", "f_0000075193")
```

### Experimental presets (Profile)

#### `get_file_detail(project, file_name) -> ProjectFile`

Resolves a file by name, then returns its full detail: metadata (`name`, `type`,
`size`, `checksum`) plus the **Profile** metadata set in `presets` (the full
experimental preset datasets). This mirrors the SPA's file "Detail" dialog.

```python
detail = client.get_file_detail("MPST000218", "cation_69.d.zip")
print(detail.name, detail.type, detail.size, detail.checksum)
for preset in detail.presets:
    print(preset.category, preset.id, preset.name)
    for item in preset.items:
        print("  ", item.key, item.value, item.ontology_value)
```

#### `get_experimental_presets(project, file_name) -> list[ExperimentalPreset]`

Same lookup as `get_file_detail`, but returns only `presets`.

```python
presets = client.get_experimental_presets("MPST000218", "cation_69.d.zip")
by_category = {p.category: p for p in presets}
by_category["sample"].name                       # 'El_day2'
by_category["sample"].as_dict()["species"]       # 'Eubacterium limosum'
```

Both raise `MassBankError` if no file with that name exists. Only `raw` files
have presets; other types return an empty list.

#### `iter_raw_file_details(project, *, limit=100) -> Iterator[ProjectFile]`

Lazily yields the detail record (metadata + `presets`) of every `raw` file in a
project. Fetches the file list once, then one detail request per raw file, so it
makes `1 + n_raw` requests.

#### `list_raw_file_details(project, *, limit=100) -> list[ProjectFile]`

Eager version of `iter_raw_file_details`.

#### `get_raw_file_metadata(project, *, limit=100) -> list[dict]`

Returns the **"Detail" dialog metadata** for every `raw` file in a project,
directly comparable to the rows whose File name column has type `raw` on the
entry page, e.g. <https://repository.massbank.jp/entry/MPST000218>. Each dict is
produced by `ProjectFile.detail_metadata()`.

```python
metadata = client.get_raw_file_metadata("MPST000218")
entry = metadata[0]
entry["file_name"]        # 'cation_Blank_4.d.zip'
entry["file_type"]        # 'raw'
entry["file_size"]        # '156.9 MB'  (human readable, as displayed)
entry["file_size_bytes"]  # 164519681
entry["md5_checksum"]     # '9a8e6891...'
entry["profile"]          # [{'id':..., 'category':..., 'name':..., 'fields': {...}}, ...]
```

### Downloads and archives

#### `download(location, destination=None) -> bytes | Path`

Streams the whole project archive from `/api/download/{location}`.

```python
path = client.download("MPST000160.1", "MPST000160.1.tar")   # -> Path
blob = client.download("MPST000160.1")                       # -> bytes (large!)
```

`location` is a location string (a `Project` is not accepted here).

#### `iter_file_names(project, *, trim_root=True) -> Iterator[str]`

Streams the archive and yields member names. The archive is a **POSIX tar**
containing a top-level `MB-POST_files_{location}/` directory, so names are the
project's file names (sample `.d` folders are themselves zipped as `*.d.zip`).
`trim_root` strips that prefix.

```python
import itertools

first_five = list(itertools.islice(client.iter_file_names("MPST000037.0"), 5))
```

> Tar has no random access: iterating all names reads the entire archive. Stop
> early when you only need the first few, or prefer `iter_project_files`, which
> uses the lightweight public file-list endpoint.

#### `list_file_names(project, *, trim_root=True) -> list[str]`

Eager version of `iter_file_names`.

### Contact

#### `send_contact(data=None) -> None`

Posts the public contact form to `/api/contact` (expects `201`). The payload
schema is undocumented; pass a mapping of form fields.

```python
client.send_contact({"message": "Hello"})
```

## Models

All models are frozen dataclasses with a `from_dict` classmethod; they are
read-only views over the API JSON.

### `Project`

`mbpost_id`, `announcement_date`, `revision`, `location`, `created_at`,
`modified_at`, `file_count`, `title`, `keywords`, `description`, `pubmed_id`,
`publication_type`, `principal_investigator`, `affiliation`, `note`,
`submitter`, `status`. Dates are the API's `YYYY/MM/DD` strings.

### `ProjectPage`

`list: list[Project]`, `total`, `from_`, `to` (Zend-style pagination; the `from`
key is exposed as `from_`).

### `ProjectFile`

`id`, `name`, `size`, `type`, `status`, `is_on_server`, `checksum`,
`profiles: list[PresetRef]` (from the list endpoint), `presets:
list[ExperimentalPreset]` (from the detail endpoint).
Properties: `is_raw` (`type == "raw"`).
Method: `detail_metadata()` returns the dict shown in the "Detail" dialog
(`file_name`, `file_type`, `file_size`, `file_size_bytes`, `md5_checksum`,
`profile`).

### `FilePage`

`list: list[ProjectFile]`, `total`, `from_`, `to`, `size` (total bytes).

### `PresetRef`

Compact preset reference in a file-list entry: `id`, `summary`.
Properties: `prefix` (leading letter, e.g. `S`) and `category`.

### `ExperimentalPreset`

Full preset dataset: `id`, `category`, `items: list[PresetItem]`.
Properties: `prefix`, `name` (value of the `presetName` item); method
`as_dict()` flattens the items to a `key -> value` mapping.

### `PresetItem`

One preset field: `key`, `value`, `ontology_value`, `group_id`, `order_key`,
`label`.

### `Statistics`, `ProjectStatistics`, `FileStatistics`

`Statistics.project` (`total`, `opened`) and `Statistics.file` (`count`,
`amount` in bytes).

### `GlobalInfo`, `CVTerm`

`GlobalInfo`: `title`, `text`, `is_active`. `CVTerm`: `id`, `text`.

### `human_readable_size(size) -> str`

Formats a byte count the way the MB-POST UI does (e.g.
`human_readable_size(164519681) == "156.9 MB"`).

### `PRESET_CATEGORY_BY_PREFIX`

Maps a preset id's leading letter to its category:
`S` → `sample`, `P` → `preparation`, `A` → `analyticalCondition`,
`W` → `softwareSetting`.

## Exceptions

| Exception | Raised when |
|---|---|
| `MassBankError` | Base class; also raised by name lookups (`file_name` not found) |
| `MassBankApiError` | An HTTP error response. Has `.status_code`, `.message`, `.url`. |

```python
from mbpost2mztabm import MassBankApiError, MassBankError

try:
    client.get_project("NOPE")
except MassBankApiError as err:
    print(err.status_code, err.message)   # e.g. 404 'Not Found'

try:
    client.get_experimental_presets("MPST000218", "missing.d.zip")
except MassBankError as err:
    print(err)
```

The API's 401 body contains the typo `"Unautorized"`; match on `status_code`,
not the message.

## Endpoint map

| Endpoint (public) | Method |
|---|---|
| `GET /_data/global_info.json` | `get_global_info` |
| `GET /api/statistics` | `get_statistics` |
| `GET /api/input-items` | `get_input_items` |
| `GET /api/cv-term/{category}?q=` | `search_cv_terms` |
| `GET /api/projects` | `list_projects`, `iter_project_list`, `list_project_ids`, `iter_project_ids` |
| `GET /api/projects/{mbpostId}` | `get_project` |
| `GET /api/projects/{location}/files` | `list_project_files`, `iter_project_files`, `find_project_file` |
| `GET /api/projects/{location}/files/{fileId}` | `get_project_file`, `get_file_detail`, `get_experimental_presets` |
| `GET /api/download/{location}` | `download`, `iter_file_names`, `list_file_names` |
| `POST /api/contact` | `send_contact` |

## Notes and gotchas

- **File routes need the location.** `/api/projects/{mbpostId}/files` returns
  `404`; use `/api/projects/{mbpostId}.{revision}/files`.
- **Preset key differs by route.** The file list uses `profiles`
  (`[{id, summary}]`); the single-file detail uses `presets`
  (`[{id, category, presets:[...]}]`).
- **Presets are only on `raw` files.**
- **Unknown CV categories are not errors** — they return an empty list.
- **Download archives are tar**, not zip, and are often hundreds of MB.
- **The API is unofficial** and can change without notice.
