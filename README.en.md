<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/logo/orca-logo-escuro.png">
  <source media="(prefers-color-scheme: light)" srcset="docs/logo/orca-logo-claro.png">
  <img src="docs/logo/orca-logo-claro.png" alt="ORCA logo: an orca jumping over a wave, with a mountain, a warning icon and a raindrop" width="320">
</picture>

# ORCA
*Open Risk and Catastrophe Aggregator*

**Brazil's official geological risk sectors (CPRM/SGB) cross-referenced with recent rainfall, in a static dashboard.**

[![Release](https://img.shields.io/github/v/release/hcristosm/ORCA)](CHANGELOG.md)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](#installation)
[![Live dashboard](https://img.shields.io/badge/dashboard-live%20on%20GitHub%20Pages-c0472f)](https://hcristosm.github.io/ORCA/)
[![CI](https://github.com/hcristosm/ORCA/actions/workflows/ci.yml/badge.svg)](.github/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-BSD%203--Clause-blue)](LICENSE)

*[Leia em português](README.md)*

</div>

---

## About

ORCA downloads the geological risk sectorization published by CPRM/SGB
(Brazil's geological survey), cross-references each sector with publicly
available recent rainfall, and shows on a map which sectors are above a
threshold you choose.

The idea came from a concrete problem: as a geologist who's mapped risk areas
in the field, I wanted to see risk data and rainfall data side by side without
needing a backend, a server, or any cost. Both datasets are public, but they
almost never show up together.

**Live dashboard:** [hcristosm.github.io/ORCA/](https://hcristosm.github.io/ORCA/),
published on GitHub Pages and refreshed daily by cron.

<p align="center">
  <img src="docs/screenshots/dashboard-claro.png" alt="ORCA dashboard in light theme: map of geological risk sectors colored by degree, count cards, table of sectors of concern, and a rainfall time series chart" width="49%">
  <img src="docs/screenshots/dashboard-escuro.png" alt="Same ORCA dashboard in dark theme" width="49%">
</p>

## What the project does today

- Covers all **27 Brazilian states**, with a state selector on the dashboard.
- Downloads CPRM/SGB risk sectors incrementally and stores them in
  GeoPackage.
- Fetches hourly rainfall from **Open-Meteo**, queried at each sector's
  centroid — no weather station needed.
- Computes 24h and 72h accumulated rainfall and a predicted 72h alert
  trajectory.
- Exports everything as static GeoJSON/JSON and serves a dashboard in plain
  HTML, CSS and JS, with a map (Leaflet), table, counters and chart
  (Chart.js). Risk degree is shown as hachure patterns, in the style of a
  geological map, so color stays reserved for one thing only: a sector above
  the threshold. A ruler at the top plots every sector against the
  threshold, which you can drag.
- Lets visitors upload their own area (GeoJSON, KML, or a zipped shapefile)
  and see rainfall calculated for it, entirely in the browser, without
  uploading the file anywhere.
- Runs two separate workflows: sectors once a month, rainfall once a day.
- 174 tests with mocked HTTP, running in CI on every push.

## Data sources

| Source | What it provides | Endpoint |
|---|---|---|
| [CPRM/SGB](https://www.sgb.gov.br/) | Risk sectorization polygons (degree, typology, affected households and people) | `geoportal.sgb.gov.br/.../risco/FeatureServer/0` (ArcGIS REST) |
| [Open-Meteo](https://open-meteo.com/) | Hourly rainfall by coordinate, no station needed. The only rainfall source | `api.open-meteo.com/v1/forecast` |

CPRM was renamed to SGB. The old domains (`geoportal.cprm.gov.br` and
similar) still respond partially, but the risk layer now lives at
`geoportal.sgb.gov.br`.

The map's municipality choropleth uses IBGE's mesh, fetched live by the
browser. It's the only IBGE dependency left, and it lives only in the
front-end. If IBGE goes down, the map degrades for the viewer but the
pipeline doesn't notice.

## Architecture

```mermaid
flowchart LR
    CPRM[("CPRM/SGB")] --> ING1["src/ingest/cprm.py"]
    OM[("Open-Meteo")] --> ING4["src/ingest/openmeteo.py"]
    ING1 --> STORE["src/storage/<br/>GeoPackage"]
    STORE --> PROC["src/processing/cruzamento.py<br/>centroids + 24h/72h rainfall"]
    STORE --> GRADE["src/processing/grade_espacial.py<br/>national grid by budget"]
    GRADE --> NAC["src/export/nacional.py"]
    PROC --> PREV["src/processing/previsao.py<br/>72h predicted alert"]
    PROC --> EXPORT["src/export/dashboard_data.py"]
    NAC --> EXPORT
    PREV --> EXPORT
    ING4 --> EXPORT
    EXPORT --> DASH["docs/dashboard/<br/>Leaflet + Chart.js"]
```

`src/cli.py` gathers the commands. `src/storage/` is a thin layer over
GeoPackage (sectors), no database.
`src/storage_cache_openmeteo.py` keeps a SQLite history of what's already
been downloaded from Open-Meteo, so it doesn't re-fetch hours it already
has.

The dashboard used to be a Streamlit app. It became a static site because
that gives full control over layout and aesthetics, lets it be published as
a page, and drops the need for a running Python process.

## Installation

Requires Python 3.11+.

```bash
git clone https://github.com/hcristosm/ORCA
cd ORCA
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Usage

### Download the risk sectors

```bash
python -m src.cli ingest-cprm --uf SP         # one state -> data/risco_sp.gpkg
python -m src.cli ingerir-setores             # all 27 states
```

### Export the dashboard data

```bash
python -m src.cli exportar-dashboard --uf SP
# -> docs/dashboard/data/setores_sp.geojson, series_sp.json, meta_sp.json, previsao_sp.json
```

It only needs the already-ingested sectors; rainfall comes from Open-Meteo
at export time.

For all states at once:

```bash
python -m src.cli atualizar-nacional --ufs SP,RJ,MG   # no --ufs = all 27
```

This command computes a single national spatial grid before exporting, so
that nearby sectors (even across neighboring states) share the same query
point. This keeps the total point count within `--orcamento-alvo` (default
6,000; Open-Meteo's free tier cap is 10,000/day). It doesn't ingest
anything: it expects the GeoPackages to already be in `data/`.

### Open the dashboard

```bash
scripts/rodar_dashboard.sh    # shortcut for python -m http.server 8000 --directory docs
# then open http://localhost:8000/dashboard/
```

Needs to be served over HTTP because the browser's `fetch()` doesn't read
`file://`.

## How it runs in production

Risk sectors change on a scale of months. Rainfall changes on a scale of
hours. That's why there are two workflows:

- **Monthly** ([`ingerir-setores.yml`](.github/workflows/ingerir-setores.yml)):
  downloads sectors for all 27 states and publishes the GeoPackages to the
  `dados-base` branch. It's the only part of the project that talks to SGB.
  Generous timeouts (120s, 5 retries) and no cache fallback: if SGB goes
  down, the run fails loudly instead of closing green with empty data.
- **Daily** ([`atualizar-dados.yml`](.github/workflows/atualizar-dados.yml),
  `0 9 * * *`): reads the sectors from `dados-base`, runs
  `atualizar-nacional`, and publishes to `gh-pages`. Doesn't touch any
  `.gov.br` source.

If SGB goes down, the dashboard stays up with the sectors from `dados-base`.

Publishing is non-destructive: before pushing, the job fetches the current
`gh-pages` and preserves the data for any state this run didn't regenerate
([`scripts/mesclar_publicado.py`](scripts/mesclar_publicado.py)). A state
that failed doesn't disappear from the dashboard, it just goes stale. Three
guards protect this merge, and every rejection fails the run:

- rejects if the run exported zero states;
- rejects if new coverage falls below a floor (default 60%, adjustable via
  `ORCA_PISO_COBERTURA`). That 0.6 came from the 12 clean runs between
  2026-08-10 and 2026-08-23, where coverage ranged from 70% to 100%: it sits
  below the worst normal case while still blocking the real degenerate cases
  (4% and 7%);
- rejects an empty set, an unreadable published count, or a regression in
  total states versus what's already live.

These guards exist because on 2026-08-22 and 2026-08-23 two runs published 1
and 2 states out of 27 while closing as `success`, with CPRM ingestion
failing on timeout.

## Known limitations

- **Rainfall is modelled, not measured.** Open-Meteo returns reanalysis and
  forecast by coordinate, not rain-gauge readings. That's what makes covering
  27 states possible without depending on station density, but it isn't
  direct observation.
- **There is no alternative rainfall source.** Open-Meteo is the only one; if
  it goes down, the state is left out of the run and the dashboard ages (the
  `gh-pages` merge keeps the previous day's data) instead of disappearing.
- **The attention threshold (default 100mm/72h) is illustrative.** It's a
  common reference in landslide literature, not an official value calibrated
  for CPRM/SGB sectors. The dashboard flags this and lets you adjust the
  value.
- **Publishing to `gh-pages` isn't reversible yet.** The deploy uses
  `force_orphan: true`, so the branch has a single commit. That's because of
  the Open-Meteo cache blob (~45MB) that changes daily. Getting the cache
  out of there is a prerequisite for dropping `force_orphan`. Until then the
  protection is preventive, not reversible.
- **No staleness badge and no post-deploy smoke test.** The dashboard shows
  when it was generated, but doesn't highlight when the data crosses a
  cycle, and nothing checks after deploy whether the public URL actually
  serves all 27 states.
- **Open-Meteo rate-limits by volume, not just frequency.** Tested with a
  real request: a single POST with SP's ~900 coordinates works fine, but
  repeating that volume consistently triggers `429`.
  `src/ingest/openmeteo.py` batches in groups of 50 points, uses a short
  history window, and waits 60s on `429`.
- **No authentication and no multi-user support.** It's a local, portfolio
  tool.
- **The dashboard doesn't update on demand.** It shows the last export,
  which runs once a day. To see fresher data right away, run
  `exportar-dashboard` locally.

## Tests

```bash
pytest
```

144 tests covering CPRM ingestion (ArcGIS REST, pagination, incremental
watermark, retry), Open-Meteo batching and retry, SQLite cache, national
spatial grid, rainfall accumulation, forecasting, export, the publication
anti-regression guard, and the non-destructive merge with `gh-pages`. Every
network call is mocked, so the suite runs without internet.

The dashboard itself (HTML and JS) has no automated tests, validation is
manual.

## Decisions and investigations

The bigger decisions were tested with real requests, not assumed:

- **Streamlit for a static site:** solved aesthetics, layout and
  distribution.
- **Open-Meteo as the only rainfall source:** answers rainfall by coordinate,
  without depending on a station. INMET and ANA were implemented and dropped:
  INMET only publishes the annual ZIP (days of lag) and ANA's network is
  mostly fluviometric. Keeping both paths cost ~1,900 lines that no workflow
  ever ran.
- **National coverage:** incremental CPRM ingestion plus a spatial grid
  calibrated by binary search, instead of a hand-picked density threshold.

## Roadmap

- Get the Open-Meteo cache out of `gh-pages` to drop `force_orphan` and
  recover the published branch's history.
- Staleness badge on the dashboard and a smoke test against the public URL
  after deploy.
- Municipal fallback: city-level layers on ArcGIS REST. Investigated for
  Itaquaquecetuba/SP on 2026-08-14, no confirmed public endpoint. Pending a
  pilot municipality with open data.
- Better orchestration of Open-Meteo requests: pagination, more complete
  backoff, and maybe a queue to space out requests.

## How this was built

I'm a geologist, not a developer by training. ORCA was largely built by
vibe coding with Claude Code: I bring the problem, the domain knowledge and
the decisions, and Claude writes most of the code. I review, test, and
correct course when the result doesn't match the reality of the data.

I figured it's better to be upfront about this than to pretend otherwise.
If you find something odd in the code, that's probably why, and an issue is
welcome.

## Contributing

Issues, PRs and suggestions are welcome. See the
[contributing guide](CONTRIBUTING.md) and the
[Code of Conduct](CODE_OF_CONDUCT.md).

## License

[BSD 3-Clause](LICENSE): free use, copying, modification and
redistribution, commercial included, as long as the copyright notice and
license are kept and credit to the original author (Mateus Hcristos
Leptokarydis) is preserved.

The public data belongs to their respective agencies:
[CPRM/SGB](https://www.sgb.gov.br/) and [Open-Meteo](https://open-meteo.com/).
Check each one's terms of use before redistributing.
