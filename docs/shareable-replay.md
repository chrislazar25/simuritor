# Shareable replay — 2026-09-29

The original simulator still runs live locally. The shareable demo uses three recorded runs generated from the same sim and wire serializer:

| Run | Scenario | Contract | Standard backup | Seed |
| --- | --- | --- | --- | --- |
| uri-10 | Winter Storm Uri | 10% | 8 h | 0 |
| uri-30 | Winter Storm Uri | 30% | 8 h | 0 |
| normal-30 | Normal week | 30% | 8 h | 0 |

Generate with `uv run python -m scripts.record_demo` from the repo root. Then run `npm run build:demo` in `frontend/`. For a local recorded preview, run `VITE_RECORDED_REPLAY=true npm run dev` there. A normal `npm run dev` / `npm run build` keeps the existing live websocket mode.

The browser fetches a gzip recording, decodes the compact home tuples one tick at a time, and supports play, pause, speed, reset and selecting a different run. It does not compute new simulation results or expose the live qualifying-contract API. The hosted terms panel says this explicitly and links to the public source and Loom.

Transport checks: `node scripts/test-recorded-replay.mjs` in `frontend/`. These cover home decoding, speed, pause/resume, completion, reset, cleanup and unsupported run rejection. `uv run pytest` passed all 241 tests on 2026-09-29; demo production build and frontend lint also passed.

The Uri downloads are approximately 20–24 MB each; the normal-week recording is approximately 1.3 MB. Initial loading depends on connection speed. Basemap tiles still require internet. No paid API, hosted Python process, battery connection or private fleet data is involved.

## Isolation and deployment

- Review branch: `review/shareable-replay-2026-09-29`.
- Worktree: `/home/chrislazar/projects/simuritor-review`.
- Original `/home/chrislazar/projects/simuritor` stays on `main`, unchanged.
- Simulator changes remain uncommitted for human review, per `AGENTS.md`.
- Deployment-only frontend copy: `/home/chrislazar/projects/simuritor-site`, an independent Git repository on a review branch. It contains only public frontend code and synthetic replay assets, with a minimal static asset Worker for Sites.
- The Sites remote has its own configured branch, unrelated to the simulator's GitHub main branch. Only that independent deployment source is committed and pushed.
- `.openai/hosting.json` records the Sites project ID; no credential is stored in the source.

The generated `frontend/public/og.png` is a decorative link card made with the built-in imagegen tool, not a screenshot or geographic evidence. Prompt: dark charcoal/night-map style with amber, teal and grey neighborhood dots; exact text “SIMURITOR”, “3,000 home batteries. One historic storm.” and “Winter Storm Uri replay”; no result numbers, invented interface or Base branding.

## Published demo

[https://simuritor-replay.celinelazar140.chatgpt.site](https://simuritor-replay.celinelazar140.chatgpt.site) — public and verified on 2026-09-29. Sites reports deployment succeeded. The page, replay asset and preview image return HTTP 200. The downloaded normal-week asset decompresses correctly to 3,000 homes and 672 ticks. The originally supplied Sites origin redirects here.
