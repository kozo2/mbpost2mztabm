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

Development uses [uv](https://docs.astral.sh/uv/):

```bash
uv sync --extra dev
uv run pytest
```
