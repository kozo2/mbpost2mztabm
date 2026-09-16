# mbpost2mztabm
Convert MB-POST "result" file to mzTab-M

## MB-POST public API client

`mbpost2mztabm` includes a client for the public (no-auth) endpoints of the
MB-POST repository (`https://repository.massbank.jp`), as documented in
[`mbpost_api.md`](mbpost_api.md) section 2.1.

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

Development uses [uv](https://docs.astral.sh/uv/):

```bash
uv sync --extra dev
uv run pytest
```
