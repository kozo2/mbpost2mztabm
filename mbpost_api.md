# MassBank Repository (MB-POST) API — Reverse-Engineered Reference

**Host:** `https://repository.massbank.jp/`
**Status:** Undocumented. Everything below was derived by analyzing the site's
JavaScript bundle (`/assets/js/index.js`, a 3.5 MB browserify/React SPA) and by
probing live endpoints. Treat as unofficial and subject to change.

---

## 1. Architecture

`repository.massbank.jp` is an SPA called **MB-POST** (MassBank POST), a project
submission/curation system for MassBank. It is a different system from the
spectrum search at `massbank.jp/MassBank/` and the European mirror
`massbank.eu`.

Key facts extracted from the bundle:

- The API is served from the **same origin** under `/api/...`. The SPA's router
  `basename` is `""`, so every request is a plain same-origin path:
  `https://repository.massbank.jp/api/...`
- There is no documented base URL, version prefix, or OpenAPI/Swagger spec.
- Data is JSON in and JSON out (except file downloads and HTML 405 pages).
- Requests are made with `XMLHttpRequest`. The generic client sets
  `Content-Type: application/json` on POST/PUT/PATCH and always
  `xhr.withCredentials = true` on the authenticated client (cookie/session).
- Errors return a JSON body of the form `{"message": "..."}` with the matching
  HTTP status. A `401` body contains the typo **`"Unautorized"`**.

There are three access tiers:

| Tier | Mechanism |
|---|---|
| **Public** | No credentials; open GETs. |
| **Preview / share link** | Header `X-MB-Post-Preview-Token: base64("<token>:<code>")` |
| **Authenticated** | Header `X-MB-POST-Authorization: <api-token>` (plus session cookie) |

### Authentication

The browser login flow (`GET /api/login`) sends the user's API token in a
custom header:

```http
GET /api/login HTTP/1.1
Host: repository.massbank.jp
X-MB-POST-Authorization: <token>
```

The bundle builds this header literally as
`{key:"X-MB-POST-Authorization", value:token}`. HTTP header names are
case-insensitive, so `X-MB-Post-Authorization` is equivalent.

Preview endpoints use a second, separate header whose value is a Base64 join of
a share token and a numeric/ASCII code:

```js
previewToken = btoa(`${token}:${code}`)   // X-MB-Post-Preview-Token
```

---

## 2. Endpoint inventory

Method/path pairs were recovered from every `xhr.*` call site in the bundle.
`:id` in file routes is a **semicolon-joined list** (e.g. `12;13;14`).

### 2.1 Public endpoints (no auth)

| Method | Path | Notes |
|---|---|---|
| GET | `/_data/global_info.json` | Static maintenance notice: `{title, text, isActive}` |
| GET | `/api/statistics` | `{project:{total,opened}, file:{count, amount}}` |
| GET | `/api/input-items` | Field/preset definitions for the submission form |
| GET | `/api/cv-term/{category}?q={query}` | Controlled-vocabulary autocomplete |
| GET | `/api/projects?q={q}&limit={n}&offset={n}` | Public (announced) project list |
| GET | `/api/projects/{mbpostId}` | Public project detail |
| GET | `/api/download/{location}` | Archive of all files (e.g. `MPST000160.1`) |
| POST | `/api/contact` | Contact form, `201` on success |

### 2.2 Preview / share-link endpoints

Require `X-MB-Post-Preview-Token: base64("<token>:<code>")`.

| Method | Path | Notes |
|---|---|---|
| GET | `/api/previews` | Project entry for a share token |
| GET | `/api/preview-files?limit={n}&offset={n}` | File list |
| GET | `/api/preview-files/{fileId}` | Single file entry |

### 2.3 Authenticated endpoints

Require `X-MB-POST-Authorization: <api-token>` (session cookie also used).

**Account**

| Method | Path | Body |
|---|---|---|
| GET | `/api/login` | — (validate token; then `GET /api/self`) |
| GET | `/api/logout` | — (`204`) |
| GET | `/api/self` | — (user profile) |
| POST | `/api/self` | Sign-up payload |
| PUT | `/api/self` | Profile update payload |
| POST | `/api/self/verify` | Email verification payload |
| POST | `/api/self/tokens` | `{}` (send verification token) |
| POST | `/api/self/password` | Password change payload |
| POST | `/api/reset-tokens` | `{email}` (request password reset) |

**Projects & files**

| Method | Path | Body / notes |
|---|---|---|
| GET | `/api/projects/self?limit=&offset=` | Current user's projects |
| POST | `/api/projects` | Create project |
| GET | `/api/projects/{id}/files?limit=&offset=` | Project file entries |
| GET | `/api/projects/{id}/local-files?limit=&offset=` | Pending/local files |
| GET | `/api/projects/{id}/files/{fileId}` | Single file entry |
| POST | `/api/projects/{id}/files` | Create file records, returns `{list:[...ids]}` |
| PUT | `/api/files/{idList}` | Replace file profile(s) |
| PATCH | `/api/files/{idList}` | Update file profile(s) |
| DELETE | `/api/files/{idList}` | Delete file(s) |
| POST | `/api/projects/{id}/revisions` | `{}` (new revision) |
| PUT | `/api/projects/{id}/status` | `{status:"submitted"}` |
| PUT | `/api/projects/{id}/pubmed-id` | `{publication, type}` |
| PUT | `/api/projects/{id}/announcement-date` | `{announcementDate}` |
| GET | `/api/replicates/{projectId}` | Generates replicate-data Excel file |
| POST | `/api/upload` | Resumable (Presto/tus-style) upload endpoint |
| POST | `/api/mirage` | `multipart/form-data` preset-import preview |

**Presets**

| Method | Path | Body / notes |
|---|---|---|
| GET | `/api/presets/{category}?limit=&offset=&q=&start_date=&end_date=` | List presets |
| POST | `/api/presets/{category}` | `{items:[...]}` create |
| PUT | `/api/presets/{category}/{id}` | `{items:[...]}` update |
| DELETE | `/api/presets/{category}/{id}` | Delete |
| POST | `/api/presets` | Bulk import |

### 2.4 Category names

Preset categories (bundle constant `presetCategories`):

| id | path | label | prefix |
|---|---|---|---|
| `sample` | `sample` | Sample | S |
| `preparation` | `preparation` | Preparation | P |
| `analyticalCondition` | `analytical-condition` | Analytical condition | A |
| `softwareSetting` | `software-setting` | Software setting | W |

CV-term categories (the `external` field of `/api/input-items` entries):

`sampleCategory`, `species`, `sampleType`, `organTissue`, `cellType`,
`cellLine`, `disease`, `compoundsMeasured`, `methodType`, `chromatographyType`,
`msInstrument`, `ionization`, `instrumentMode`, `fragmentationMethod`,
`software`.

---

## 3. Verified live behavior

Probes run against the live host (2026):

```
GET /_data/global_info.json                      200  323 B
GET /api/statistics                              200  {"project":{"total":194,"opened":109},"file":{"count":44127,"amount":3169496732259}}
GET /api/input-items                             200  16,441 B (project/sample/preparation/analyticalCondition/softwareSetting)
GET /api/projects                                200  23,700 B
GET /api/projects?q=test&limit=2&offset=0        200  {"list":[...],"meta":{"total":...,"from":1,"to":...}}
GET /api/projects/MPST000160                     200  full project record
GET /api/download/MPST000160.1                   200  application/octet-stream, ~294 MB
GET /api/cv-term/species?q=homo                  200  {"list":[{"id":"NCBITaxon:9605","text":"Homo"}, ...]}
GET /api/cv-term/foo?q=x                         200  {"list":[]}   (unknown category = empty, not error)
POST /api/contact  {}                            201
GET /api/logout                                  204

GET /api/self                                    401  {"message":"Unautorized"}
GET /api/presets                                 401  {"message":"Unautorized"}
GET /api/presets/sample?...                      401  {"message":"Unautorized"}
GET /api/files/1                                 401  {"message":"Unautorized"}
GET /api/mirage                                  401  {"message":"Unautorized"}
GET /api/replicates/1                            401  {"message":"Unautorized"}
GET /api/previews                                400  {"message":"Bad Request"}   (no token header)
GET /api/preview-files                           400  {"message":"Bad Request"}
GET /api/projects/MPST000160/files               404  (route hidden without auth)
GET /api/projects/self?limit=1                   401
GET /api/projects/MPST000160/revisions           405  HTML "Method not allowed"
GET /api/login  (bad token)                      500
OPTIONS /api/projects                            401
```

### Response schemas observed

`GET /api/projects` (list) — envelope with pagination:

```json
{
  "list": [ { "mbpostId": "MPST000145", "announcementDate": "2026/09/09",
              "revision": 0, "location": "MPST000145.0",
              "createdAt": "2025/12/25", "modifiedAt": "2025/12/25",
              "fileCount": 163, "title": "...", "keywords": "...",
              "description": "...", "pubmedId": "",
              "publicationType": "pubmed", "principalInvestigator": "...",
              "affiliation": "...", "note": "", "submitter": "..." } ],
  "meta": { "total": 109, "from": 1, "to": 1 }
}
```

`meta` uses `total` / `from` / `to` (Zend-style pagination), not `count`.

`GET /api/projects/{mbpostId}` — the same fields plus `status`
(`"announced"`, `"submitted"`, `"opened"`, ...). Dates are strings formatted
`YYYY/MM/DD`. The `location` field is the value passed to `/api/download/`.

`GET /api/statistics`:

```json
{"project":{"total":194,"opened":109},
 "file":{"count":44127,"amount":3169496732259}}
```

`amount` is a byte total.

`GET /api/cv-term/{category}?q=...`:

```json
{ "list": [ {"id":"NCBITaxon:9605","text":"Homo"} ] }
```

IDs are ontology terms (e.g. NCBITaxon) where applicable.

---

## 4. Usage examples

Fetch the public project list and statistics:

```bash
curl -s 'https://repository.massbank.jp/api/statistics'
curl -s 'https://repository.massbank.jp/api/projects?limit=20&offset=0'
curl -s 'https://repository.massbank.jp/api/projects?q=lipidomics&limit=5&offset=0'
```

Fetch one project and download all its files:

```bash
curl -s 'https://repository.massbank.jp/api/projects/MPST000160'
curl -L -o MPST000160.1.zip 'https://repository.massbank.jp/api/download/MPST000160.1'
```

Resolve a CV term:

```bash
curl -s 'https://repository.massbank.jp/api/cv-term/species?q=human'
```

Authenticated (replace `<TOKEN>` with a user API token):

```bash
curl -s -H 'X-MB-POST-Authorization: <TOKEN>' \
     'https://repository.massbank.jp/api/self'

curl -s -H 'X-MB-POST-Authorization: <TOKEN>' \
     'https://repository.massbank.jp/api/projects/self?limit=10&offset=0'
```

Preview a shared project (Base64 of `token:code`):

```bash
TOK=$(printf 'TOKEN:CODE' | base64)
curl -s -H "X-MB-Post-Preview-Token: $TOK" \
     'https://repository.massbank.jp/api/previews'
curl -s -H "X-MB-Post-Preview-Token: $TOK" \
     'https://repository.massbank.jp/api/preview-files?limit=20&offset=0'
```

---

## 5. Gotchas / notes

- **Unofficial.** No documentation exists; these paths can change without
  notice. `/api/input-items` and `/_data/global_info.json` are the only
  "self-describing" endpoints.
- **Typo in 401 body:** `"Unautorized"` (missing `h`). Match on the status code,
  not the message.
- **Inconsistent auth failure codes:** `/api/login` with an invalid token returns
  `500`, not `401`. `OPTIONS` returns `401` (no CORS preflight support).
- **Hidden routes:** authenticated file routes return `404` when called
  anonymously (e.g. `/api/projects/{id}/files`), while `/api/files/{id}` returns
  `401`. Do not assume 404 means the route is wrong.
- **Unknown CV category is not an error:** `/api/cv-term/<anything>?q=x` returns
  `200 {"list":[]}`.
- **Wrong HTTP method** yields an HTML `405` page from the web server, not JSON.
- **`/api/download/{location}` is public** for announced projects and streams the
  whole archive in one response (no range/pagination semantics worth relying on).
- **Download archive is a POSIX tar**, not a zip, despite `.zip`-style locations
  in the examples. It contains a single top-level directory
  `MB-POST_files_{location}/` holding the project's files (sample `.d` folders
  are themselves zipped as `*.d.zip`, alongside result Excel files). There is no
  public file-list endpoint (`/api/projects/{id}/files` needs auth), so file
  names must be read from this tar; tar has no random access, so enumerating all
  names requires downloading the whole archive.
- **Uploads** use a resumable protocol at `/api/upload` (the bundle wraps a
  Presto client); `POST /api/mirage` is a separate multipart import-preview.
- **SPA routes** (for reference when mapping URLs): `/`, `/entry/:id`,
  `/preview/:token`, `/submit`, `/project/:step`, `/preset/:category`,
  `/mypage`, `/help`, `/about`, `/contact`, `/signup`, `/login`, `/verify`,
  `/forgot`, `/reset`.

---

## 6. Related MassBank APIs (contrast)

- `https://massbank.jp/MassBank/` — spectrum search front-end; has its own
  query scripts (e.g. `jsp/ResultList.jsp`) rather than a REST API.
- `https://massbank.eu/MassBank/` — European mirror with a documented API used
  by the MassBank Analytics repository.
- `repository.massbank.jp` (this document) — MB-POST submission/curation API; it
  is **not** a spectrum search API. Spectra live in the main MassBank datasets.

---

*Generated by static analysis of `/assets/js/index.js` plus live HTTP probing.*

