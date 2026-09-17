# pymbpost
Fetch metadata from MB-POST

## Installation

The package is published on [PyPI](https://pypi.org/project/pymbpost/); install
it with [uv](https://docs.astral.sh/uv/).

Add it as a dependency of an existing project:

```bash
uv add pymbpost
```

Install it into the currently active virtual environment:

```bash
uv pip install pymbpost
```

Install a specific version:

```bash
uv add pymbpost==0.1.0
```

For development, clone the repo and sync the dev environment:

```bash
git clone https://github.com/kozo2/pymbpost.git
cd pymbpost
uv sync --extra dev
```

## Generate `mbpost_profiles.csv`

Start a uv Python REPL — either in a project that depends on `pymbpost` (after
`uv add` or `uv sync`):

```bash
uv run python
```

or ad hoc, without adding it to a project (uv builds a temporary environment):

```bash
uv run --with pymbpost python
```

Then, at the `>>>` prompt, export the Profile metadata of every `raw` file in
every public project to `mbpost_profiles.csv`:

```python
>>> from pymbpost import MbPostPublicClient
>>> with MbPostPublicClient(timeout=60) as client:
...     path = client.export_profile_metadata_csv("mbpost_profiles.csv")
...     print(path.resolve())
...
```

A full run writes **18,518 rows** (one per `raw` file) and **51 columns**
(`mbpost_id`, `location`, `file_name`, `file_type`, `file_size`,
`file_size_bytes`, `md5_checksum`, then per preset category `<category>.id` and
`<category>.<field>`) in about **6.5 minutes**.

To restrict the scan to selected projects, pass `projects`:

```python
>>> with MbPostPublicClient(timeout=60) as client:
...     client.export_profile_metadata_csv("mpst218.csv", projects=["MPST000218"])
...
```

Full API reference: [`docs/usage.md`](docs/usage.md).
