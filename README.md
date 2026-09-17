# pymbpost
Fetch metadata from MB-POST

## Installation

The package is not published on PyPI; install it with
[uv](https://docs.astral.sh/uv/) from the Git repository.

Add it as a dependency of an existing project:

```bash
uv add git+https://github.com/kozo2/pymbpost.git
```

Install it into the currently active virtual environment:

```bash
uv pip install git+https://github.com/kozo2/pymbpost.git
```

Install a specific revision/tag:

```bash
uv add "git+https://github.com/kozo2/pymbpost.git@main"
```

For development, clone the repo and sync the dev environment:

```bash
git clone https://github.com/kozo2/pymbpost.git
cd pymbpost
uv sync --extra dev
```

### Interactive Python (REPL)

`uv run` executes a command inside the project environment, so use it to start
an interpreter that can import the package.

In a project that depends on it (after `uv add`) or in the cloned repo (after
`uv sync`):

```bash
uv run python
```

Ad hoc, without adding it to a project (uv builds a temporary environment):

```bash
uv run --with git+https://github.com/kozo2/pymbpost.git python
```

With IPython instead of the standard REPL:

```bash
uv run --with ipython --with git+https://github.com/kozo2/pymbpost.git ipython
```

Then, at the `>>>` prompt:

```python
>>> from pymbpost import MassBankPublicClient
>>> with MassBankPublicClient() as client:
...     stats = client.get_statistics()
...     print(stats.project.total, stats.file.count)
...
```

## MB-POST public API client

`pymbpost` includes a client for the public (no-auth) endpoints of the
MB-POST repository (`https://repository.massbank.jp`), as documented in
[`mbpost_api.md`](mbpost_api.md) section 2.1.

Full API reference: [`docs/usage.md`](docs/usage.md).

```python
from pymbpost import MassBankPublicClient

with MassBankPublicClient() as client:
    stats = client.get_statistics()
    page = client.list_projects(q="lipidomics", limit=20)
    project = client.get_project("MPST000160")
    terms = client.search_cv_terms("species", "human")
    client.download(project.location, "MPST000160.1.zip")
```

### Retrieve all project ids

`GET /api/projects` is paginated, so fetching every id means walking the
pages. Use `iter_project_ids` (lazy, good for large result sets) or
`list_project_ids` (eager):

```python
from pymbpost import MassBankPublicClient

with MassBankPublicClient() as client:
    # >>> ['MPST000001', 'MPST000002', ...]
    ids = client.list_project_ids()

    # Lazy variant, e.g. to process one project at a time:
    for mbpost_id in client.iter_project_ids(limit=100):
        print(mbpost_id)
```

Both accept optional `q` (text search), `limit` (page size) and `offset`
parameters. For example, ids for projects matching a query:

```python
ids = client.list_project_ids(q="lipidomics")
```

### Retrieve the file name list of a project

There is **no public file-list endpoint**: `/api/projects/{id}/files` requires
authentication, and a public project record only carries `fileCount`. The
public file names therefore come from the project archive served by
`GET /api/download/{location}`, which is a **POSIX tar** (despite the `.zip`
name in the API examples). Use `iter_file_names` (streaming, lazy) or
`list_file_names` (eager):

```python
from pymbpost import MassBankPublicClient

with MassBankPublicClient() as client:
    project = client.get_project("MPST000037")
    # >>> ['TSOGA038_p_20241106_Sample_16.d.zip',
    #      'TSOGA038_p_20241106_Sample_18.d.zip', ...]
    names = client.list_file_names(project)
```

Both accept either a `Project` (its `location` is used) or a location string
such as `"MPST000037.0"`, and strip the archive's top-level directory prefix
(`MB-POST_files_MPST000037.0/`) by default; pass `trim_root=False` to keep it.

> **Warning:** the tar format has no random access, so listing every name reads
> the entire archive (typically hundreds of MB). `iter_file_names` yields names
> as it goes, so stop early when you only need the first few:

```python
import itertools

first = list(itertools.islice(client.iter_file_names(project), 5))
```

Alternatively, the **file-list endpoint is public** when addressed by the
project *location* (`mbpostId.revision`); see below.

### Get the experimental preset dataset for a file

Each raw file in an announced project is linked to its experimental procedure
presets: **Sample (S)**, **Preparation (P)**, **Analytical condition (A)** and
**Software setting (W)**. Both the file list and per-file detail are public when
the route is addressed by the project **location** (e.g. `MPST000160.1`), not
the bare `mbpostId` (which returns `404`).

```python
from pymbpost import MassBankPublicClient

with MassBankPublicClient() as client:
    # 1. List files (paginated). Each raw file carries compact preset refs.
    page = client.list_project_files("MPST000160.1")
    for f in page.list:
        summaries = [(p.category, p.summary) for p in f.profiles]
        print(f.name, f.type, summaries)

    # 2. Get the full experimental preset dataset for one file by name.
    presets = client.get_experimental_presets(
        "MPST000160.1", "260206_Tomita_69_neg_202602091225_tags.xml"
    )
    for preset in presets:
        print(preset.id, preset.category, preset.name)
        print(preset.as_dict())  # key -> value

    # Or fetch a file's detail directly when you already have its id:
    detail = client.get_project_file("MPST000160.1", "f_0000065325")
    print(detail.presets)
```

`list_project_files` / `iter_project_files` accept a `Project`, a location
string, or a bare `mbpostId` (resolved automatically via `get_project`).
Only `raw` files carry presets; other file types return an empty list.

Result shape:

```python
ExperimentalPreset(
    id="S0000000319",
    category="sample",
    items=[
        PresetItem(key="presetName", value="6_TSOGA038", ontology_value="", ...),
        PresetItem(key="species", value="Mus musculus (Mouse)",
                   ontology_value="NCBITaxon:10090", ...),
        ...
    ],
)
```

### Get the file detail (Profile metadata set) by file name

`get_file_detail` resolves a file by name and returns the full record behind
MB-POST's "Detail" view: file metadata (`name`, `type`, `size`, `checksum`)
plus the **Profile** metadata set in `presets` (the full experimental preset
datasets). It is the same endpoint as above, but returns the metadata rather
than only the presets.

```python
from pymbpost import MassBankPublicClient

with MassBankPublicClient() as client:
    detail = client.get_file_detail("MPST000218", "cation_69.d.zip")

    print(detail.id, detail.name, detail.type, detail.size, detail.checksum)
    # Profile metadata set, grouped by preset category (S/P/A/W):
    for preset in detail.presets:
        print(preset.category, preset.id, preset.name)
        for item in preset.items:
            print("  ", item.key, item.value, item.ontology_value)
```

Accepting a file **id** instead, call `get_project_file(project, file_id)`
directly to skip the name lookup. Both helpers raise `MassBankError` when the
name is not found.

### Get the "Detail" metadata for every raw file in a project

`get_raw_file_metadata` returns, for all rows on the entry page whose File name
column is of type `raw`, exactly the metadata shown after clicking **Detail**
(File name / File type / File size / MD5 checksum / Profile). Example for
<https://repository.massbank.jp/entry/MPST000218>:

```python
from pymbpost import MassBankPublicClient

with MassBankPublicClient() as client:
    metadata = client.get_raw_file_metadata("MPST000218")
    for entry in metadata:
        print(entry["file_name"], entry["file_type"], entry["file_size"])
        print("  MD5:", entry["md5_checksum"])
        for profile in entry["profile"]:
            print("  ", profile["category"], profile["name"], profile["fields"])
```

Each item is a dict:

```python
{
    "file_name": "cation_Blank_4.d.zip",
    "file_type": "raw",
    "file_size": "156.9 MB",        # human readable, as displayed
    "file_size_bytes": 164519681,
    "md5_checksum": "9a8e6891...",
    "profile": [
        {"id": "W0000001749", "category": "softwareSetting",
         "name": "Masterhands", "fields": {"presetName": "Masterhands", ...}},
        ...
    ],
}
```

`list_raw_file_details` returns the same data as `ProjectFile` objects, and
`iter_raw_file_details` yields them lazily. These make `1 + n_raw` requests
(one file-list call, then one detail call per raw file), so use the iterator to
stop early on large projects.

### Export Profile metadata of all raw files to CSV

`export_profile_metadata_csv` writes the Profile metadata of every `raw` file
across projects into one CSV file. It streams rows to disk (constant memory).

```python
from pymbpost import MassBankPublicClient

with MassBankPublicClient() as client:
    # Every public project (slow: one file-list request per project and one
    # detail request per raw file):
    client.export_profile_metadata_csv("mbpost_profiles.csv")

    # Or restrict the scan:
    client.export_profile_metadata_csv("one_project.csv", projects=["MPST000218"])
```

The header is derived from the authoritative field definitions in
`/api/input-items`: file metadata columns followed, per preset category, by
`<category>.id` and one `<category>.<field>` column:

```
mbpost_id,location,file_name,file_type,file_size,file_size_bytes,md5_checksum,
sample.id,sample.presetName,sample.species,...,analyticalCondition.ionization,
analyticalCondition.polarity,...,softwareSetting.software,...
```

Use `iter_profile_metadata_rows` if you want the rows as dicts without writing
a file.

> **Note:** a full export can issue tens of thousands of HTTP requests (one per
> raw file). Narrow it with `projects=` and/or run it once and cache the result.

#### Create `mbpost_profiles.csv` (full export)

The complete Profile-metadata file for every `raw` file in every public project
is produced by calling the export with no `projects` filter. A full run over all
110 public projects makes ~18,500 detail requests (one per raw file) and takes a
few minutes.

Run it with `uv` (see [Installation](#installation)); no project checkout is
needed if the package is installed:

```bash
uv run --with git+https://github.com/kozo2/pymbpost.git python - <<'PY'
from pymbpost import MassBankPublicClient

with MassBankPublicClient(timeout=60) as client:
    path = client.export_profile_metadata_csv("mbpost_profiles.csv")
    print("wrote", path.resolve())
PY
```

Or, inside this repository / any project that depends on it:

```bash
uv run python - <<'PY'
from pymbpost import MassBankPublicClient

with MassBankPublicClient(timeout=60) as client:
    path = client.export_profile_metadata_csv("mbpost_profiles.csv")
    print("wrote", path.resolve())
PY
```

A full run writes all 110 public projects to `mbpost_profiles.csv` (28 MB):

- **Rows:** 18,518 — one per `raw` file
- **Columns:** 51 — `mbpost_id`, `location`, `file_name`, `file_type`,
  `file_size`, `file_size_bytes`, `md5_checksum`, then per preset category
  `<category>.id` and `<category>.<field>` (Sample, Preparation, Analytical
  condition, Software setting)
- **Runtime:** ~6.5 minutes on a normal connection

To inspect the result:

```bash
head -1 mbpost_profiles.csv                 # header
wc -l mbpost_profiles.csv                   # row count (header + data)
```

To speed up iteration, export only some projects and append later, or use
`iter_profile_metadata_rows` and handle rows yourself:

```python
with MassBankPublicClient() as client:
    client.export_profile_metadata_csv("mpst218.csv", projects=["MPST000218"])
```

Development uses [uv](https://docs.astral.sh/uv/):

```bash
uv sync --extra dev
uv run pytest
```

Live tests against the real API are opt-in (they are skipped by default):

```bash
MBPOST_RUN_INTEGRATION=1 uv run pytest -m integration
```
