# mbpost2mztabm
Convert MB-POST "result" file to mzTab-M

## Installation

The package is not published on PyPI; install it with
[uv](https://docs.astral.sh/uv/) from the Git repository.

Add it as a dependency of an existing project:

```bash
uv add git+https://github.com/kozo2/mbpost2mztabm.git
```

Install it into the currently active virtual environment:

```bash
uv pip install git+https://github.com/kozo2/mbpost2mztabm.git
```

Install a specific revision/tag:

```bash
uv add "git+https://github.com/kozo2/mbpost2mztabm.git@main"
```

For development, clone the repo and sync the dev environment:

```bash
git clone https://github.com/kozo2/mbpost2mztabm.git
cd mbpost2mztabm
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
uv run --with git+https://github.com/kozo2/mbpost2mztabm.git python
```

With IPython instead of the standard REPL:

```bash
uv run --with ipython --with git+https://github.com/kozo2/mbpost2mztabm.git ipython
```

Then, at the `>>>` prompt:

```python
>>> from mbpost2mztabm import MassBankPublicClient
>>> with MassBankPublicClient() as client:
...     stats = client.get_statistics()
...     print(stats.project.total, stats.file.count)
...
```

## MB-POST public API client

`mbpost2mztabm` includes a client for the public (no-auth) endpoints of the
MB-POST repository (`https://repository.massbank.jp`), as documented in
[`mbpost_api.md`](mbpost_api.md) section 2.1.

Full API reference: [`docs/usage.md`](docs/usage.md).

```python
from mbpost2mztabm import MassBankPublicClient

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
from mbpost2mztabm import MassBankPublicClient

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
from mbpost2mztabm import MassBankPublicClient

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
from mbpost2mztabm import MassBankPublicClient

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
from mbpost2mztabm import MassBankPublicClient

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

Development uses [uv](https://docs.astral.sh/uv/):

```bash
uv sync --extra dev
uv run pytest
```

Live tests against the real API are opt-in (they are skipped by default):

```bash
MBPOST_RUN_INTEGRATION=1 uv run pytest -m integration
```
