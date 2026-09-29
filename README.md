# Out Brake, Overtake

A historical Formula 1 analysis tool for studying overtakes created through late braking.

Out Brake, Overtake is an independent community project and is not affiliated
with or endorsed by Formula 1, the FIA, any team, driver, or OpenF1. Formula 1,
FIA, team, and driver names and marks belong to their respective owners.

## Project status

- The Predictive Model UI now evaluates the exported Max Verstappen baseline
  logistic-regression artifact in the browser; it is no longer a placeholder
  formula.
- The production direction is an all-driver pooled model. The Max-only artifact
  remains an exploratory baseline until the pooled model is trained and exported.
- The UI includes Home, Predictive Model, Overtakes, and About Our Model tabs.
- This repository is initialized on `main`. The application source and local
  training data will be migrated deliberately; raw data and local model binaries
  are not intended for publication.

## Stack

- React + TypeScript + Vite
- TanStack Query for OpenF1 data fetching and caching
- Recharts for charts
- Vitest for tests

## Getting started

```sh
npm ci
npm run dev
```

Copy `.env.example` to `.env` if you need to override environment settings.
`VITE_*` values are public browser configuration, never secrets.

## Overtakes-tab data

The Overtakes tab reads compact static JSON from `public/overtakes/`; it does
not call the OpenF1 API in the browser. After completed local sessions change,
refresh those publishable files with:

```sh
PYTHONPATH=ml/src .venv/bin/python3 scripts/export_overtake_views.py
```

The exporter processes only sessions marked complete and retains just the
fields rendered by the UI. It never copies raw telemetry or Parquet files.

Use Node 22 and Python 3.12 for development. Python setup:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r scripts/requirements.txt -r ml/requirements.txt
```

## Checks

```sh
npm run lint
npm run build
PYTHONPATH=scripts:ml/src .venv/bin/python -m unittest discover -s scripts
PYTHONPATH=ml/src .venv/bin/python -m unittest discover -s ml/src
```

`npm test` currently fails because web tests have not been added. Python
dependency ranges are not yet an exact reproducible lockfile. The current
browser prediction uses the exported Max Verstappen baseline; it is not the
future all-driver pooled model. See [review findings](docs/CODE_REVIEW.md)
before publishing.

## Project structure

- `src/api/` — OpenF1 client, endpoints, and data types
- `src/features/` — feature-specific UI and analysis logic
- `src/components/` — reusable UI components
- `src/pages/` — application pages
- `scripts/` — acquisition scripts, tests, and [documentation](scripts/README.md)
- `ml/src/` — local preprocessing, audit, training, export, and tests
- `ml/*.md` — [modeling](ml/README.md) and [pooled preprocessing](ml/POOLED_PREPROCESSING.md)
- `public/` — static assets and reviewed browser model JSON exports
- `docs/` — project review and release guidance
- `data/` — downloaded and processed data; local only
- `ml/models/`, `ml/reports/` — local model binaries, reports, and telemetry reviews

No directory relocation is required. Keep custom download outputs under `data/`.
Generated report links in modeling docs require local reports and are not shipped.

## Publishing and licensing

Original project code is [MIT licensed](LICENSE). See [third-party notices](THIRD_PARTY_NOTICES.md)
for OpenF1 attribution, upstream licensing, asset provenance, and data rights.
This project is independent of Formula 1, the FIA, teams, drivers, and OpenF1.

Git is initialized and `main` tracks the GitHub remote. `.gitignore` excludes
data, binary model artifacts, generated reports, local runtimes, dependencies,
build outputs, and `.env` secrets; `.env.example` remains publishable. Browser
model JSON exports are intentionally eligible for publication and need review.
Inspect `git status --short` and `git diff --cached --stat` before committing.
Ignore rules do not protect force-added or previously tracked files. Do not copy
raw API records into public assets or committed examples.
