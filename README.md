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

Development uses [uv](https://docs.astral.sh/uv/):

```bash
uv sync --extra dev
uv run pytest
```
