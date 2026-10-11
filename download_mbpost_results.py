#!/usr/bin/env python3
"""Download all ``result``-tagged files from MB-POST (https://repository.massbank.jp/).

For every public project, list its files via the public API, keep the entries
whose ``type`` is ``result``, and download them via ``/data/<location>/<name>``.

Naming inside the output directory (default: ``mbpost_results/``):

* single-result project: ``<MBPOSTID><original extension>``
  (e.g. ``MPST000001.xlsx``), matching the files already in ``mbpost_results/``;
* multi-result project: ``<MBPOSTID>__<original file name>``
  (e.g. ``MPST000222__cecum_results.xlsx``), so nothing is overwritten and the
  source file stays traceable.

Each download is verified against the ``size`` and ``checksum`` (MD5) reported
by the API. Existing files with matching size and checksum are skipped, so
re-runs are idempotent. A ``manifest.json`` mapping local files back to their
project / original name / checksum is written to the output directory.

Usage:
    .venv/bin/python download_mbpost_results.py [--out mbpost_results] [--dry-run]
    .venv/bin/python download_mbpost_results.py --projects MPST000001,MPST000003
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import datetime
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = "https://repository.massbank.jp"
PAGE_SIZE = 100
FILE_PAGE_SIZE = 100


def api_get_json(url: str, timeout: float) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def list_projects(base: str, timeout: float) -> list:
    projects: list = []
    offset = 0
    total: int | None = None
    while True:
        url = f"{base}/api/projects?q=&limit={PAGE_SIZE}&offset={offset}"
        data = api_get_json(url, timeout)
        batch = data.get("list", [])
        if total is None:
            total = data.get("meta", {}).get("total", len(batch))
        projects.extend(batch)
        if not batch or len(projects) >= (total or 0):
            break
        offset += PAGE_SIZE
    return projects


def list_files(base: str, location: str, timeout: float) -> list:
    files: list = []
    offset = 0
    total: int | None = None
    while True:
        url = f"{base}/api/projects/{location}/files?limit={FILE_PAGE_SIZE}&offset={offset}"
        data = api_get_json(url, timeout)
        batch = data.get("list", [])
        if total is None:
            total = data.get("meta", {}).get("total", len(batch))
        files.extend(batch)
        if not batch or len(files) >= (total or 0):
            break
        offset += FILE_PAGE_SIZE
    return files


def sanitize_filename(name: str, max_len: int = 120) -> str:
    """Make a server file name safe as a single path component."""
    cleaned = "".join(c if c >= " " and c not in '/\\' else "_" for c in name).strip()
    cleaned = cleaned.strip(". ")
    if not cleaned:
        cleaned = "_unnamed"
    if len(cleaned) > max_len:
        stem, dot, ext = cleaned.rpartition(".")
        if dot and len(ext) <= 10:
            cleaned = stem[: max_len - len(ext) - 1].rstrip(". ") + dot + ext
        else:
            cleaned = cleaned[:max_len]
    return cleaned


def plan_downloads(projects: list, files_by_project: dict) -> list:
    """Build download tasks, resolving local file names per project."""
    tasks: list = []
    seen: set = set()
    for proj in projects:
        mbpost_id = proj["mbpostId"]
        location = proj["location"]
        results = [f for f in files_by_project.get(location, []) if f.get("type") == "result"]
        single = len(results) == 1
        for info in results:
            original = info["name"]
            if single:
                _, ext = os.path.splitext(original)
                local = f"{mbpost_id}{ext}"
            else:
                local = f"{mbpost_id}__{sanitize_filename(original)}"
            # Guard against pathological collisions after sanitising.
            base_local, n = local, 2
            while local.lower() in seen:
                stem, dot, ext = base_local.rpartition(".")
                local = f"{stem}__{n}{dot + ext if dot else ''}"
                n += 1
            seen.add(local.lower())
            url = f"{BASE_URL}/data/{location}/{urllib.parse.quote(original, safe='-_.!~*\'()')}"
            tasks.append(
                {
                    "mbpost_id": mbpost_id,
                    "location": location,
                    "file_id": info.get("id"),
                    "original_name": original,
                    "local_name": local,
                    "size": info.get("size"),
                    "checksum": info.get("checksum"),
                    "url": url,
                }
            )
    return tasks


def md5_of(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download_one(task: dict, out_dir: str, timeout: float, retries: int) -> dict:
    dest = os.path.join(out_dir, task["local_name"])
    expected_size = task["size"]
    expected_md5 = (task["checksum"] or "").lower()

    if os.path.isfile(dest):
        try:
            if expected_size is not None and os.path.getsize(dest) != expected_size:
                pass  # stale: re-download below
            elif not expected_md5 or md5_of(dest) == expected_md5:
                return {**task, "status": "skipped", "path": dest}
        except OSError:
            pass

    tmp = dest + ".part"
    last_err: str | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(task["url"])
            with urllib.request.urlopen(req, timeout=timeout) as resp, open(tmp, "wb") as fh:
                h = hashlib.md5()
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    fh.write(chunk)
                    h.update(chunk)
            if expected_size is not None and os.path.getsize(tmp) != expected_size:
                raise ValueError(
                    f"size mismatch: got {os.path.getsize(tmp)}, expected {expected_size}"
                )
            if expected_md5 and h.hexdigest() != expected_md5:
                raise ValueError(
                    f"checksum mismatch: got {h.hexdigest()}, expected {expected_md5}"
                )
            os.replace(tmp, dest)
            return {**task, "status": "downloaded", "path": dest}
        except (urllib.error.URLError, OSError, ValueError) as exc:  # noqa: BLE001 - report and retry
            last_err = f"{type(exc).__name__}: {exc}"
            try:
                if os.path.isfile(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            if attempt < retries:
                time.sleep(min(2**attempt, 30))
    return {**task, "status": f"failed: {last_err}", "path": dest}


def write_manifest(results: list, manifest_path: str) -> None:
    stamped = [
        {**r, "downloaded_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
        for r in results
    ]
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(stamped, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    csv_path = os.path.splitext(manifest_path)[0] + ".csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "mbpost_id",
                "location",
                "file_id",
                "original_name",
                "local_name",
                "size",
                "checksum",
                "status",
                "url",
            ],
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(stamped)


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="mbpost_results", help="output directory (default: mbpost_results)")
    ap.add_argument("--base-url", default=BASE_URL, help="MB-POST base URL")
    ap.add_argument("--projects", default=None, help="comma-separated MBPOST IDs to restrict the run, e.g. MPST000001,MPST000003")
    ap.add_argument("--workers", type=int, default=4, help="parallel download workers (default: 4)")
    ap.add_argument("--timeout", type=float, default=60.0, help="per-request timeout in seconds (default: 60)")
    ap.add_argument("--retries", type=int, default=3, help="retries per file (default: 3)")
    ap.add_argument("--manifest", default=None, help="manifest JSON path (default: <out>/manifest.json, plus .csv)")
    ap.add_argument("--overwrite", action="store_true", help="re-download even if the local file already verifies")
    ap.add_argument("--dry-run", action="store_true", help="list what would be downloaded without downloading")
    args = ap.parse_args(argv)

    only = None
    if args.projects:
        only = {p.strip().upper() for p in args.projects.split(",") if p.strip()}

    print(f"Listing projects at {args.base_url} ...", flush=True)
    projects = list_projects(args.base_url, args.timeout)
    if only:
        projects = [p for p in projects if p["mbpostId"].upper() in only]
        missing = only - {p["mbpostId"].upper() for p in projects}
        if missing:
            print(f"Warning: not found in public list: {sorted(missing)}", file=sys.stderr)
    print(f"Found {len(projects)} project(s). Listing files ...", flush=True)

    files_by_project: dict = {}
    for i, proj in enumerate(projects, 1):
        loc = proj["location"]
        try:
            files_by_project[loc] = list_files(args.base_url, loc, args.timeout)
        except Exception as exc:  # noqa: BLE001 - keep going, report at the end
            print(f"Warning: file list failed for {loc}: {exc}", file=sys.stderr)
            files_by_project[loc] = []
        if i % 20 == 0 or i == len(projects):
            print(f"  ... {i}/{len(projects)}", flush=True)

    tasks = plan_downloads(projects, files_by_project)
    total_bytes = sum(t["size"] or 0 for t in tasks)
    print(f"Result files: {len(tasks)} ({total_bytes / 1e6:.1f} MB across {len(projects)} projects)")
    for t in tasks:
        print(f"  {t['local_name']}  <- [{t['location']}] {t['original_name']} ({t['size']} bytes)")
    if args.dry_run:
        return 0

    os.makedirs(args.out, exist_ok=True)
    if args.overwrite:
        for t in tasks:
            dest = os.path.join(args.out, t["local_name"])
            try:
                if os.path.isfile(dest):
                    os.remove(dest)
            except OSError as exc:
                print(f"Warning: cannot remove {dest}: {exc}", file=sys.stderr)

    results: list = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        future_to_task = {
            pool.submit(download_one, t, args.out, args.timeout, args.retries): t for t in tasks
        }
        done = 0
        for fut in concurrent.futures.as_completed(future_to_task):
            res = fut.result()
            results.append(res)
            done += 1
            print(f"[{done}/{len(tasks)}] {res['status']}: {res['local_name']}", flush=True)

    manifest_path = args.manifest or os.path.join(args.out, "manifest.json")
    write_manifest(results, manifest_path)
    print(f"Wrote manifest: {manifest_path} (+ .csv)")

    ok = sum(1 for r in results if r["status"] in ("downloaded", "skipped"))
    failed = [r for r in results if r["status"] not in ("downloaded", "skipped")]
    print(f"Done: {ok} ok ({sum(1 for r in results if r['status'] == 'downloaded')} downloaded, "
          f"{sum(1 for r in results if r['status'] == 'skipped')} skipped), {len(failed)} failed.")
    for r in failed:
        print(f"  FAILED {r['local_name']} [{r['location']}] {r['original_name']}: {r['status']}",
              file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
