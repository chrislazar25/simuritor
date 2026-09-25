# Uri Replay: pitch points mapped to the rubric

Tracks: Orchestration (primary) + Open Grid Data. Judged on the 5-min Loom + codebase.

## One-liner
A crisis simulator that replays real Texas grid emergencies against a home-battery fleet and stress-tests the dispatch policy: rules for the obvious cases, a calibrated model for the judgment calls, a safe default when it isn't sure, and a fleet that keeps delivering while parts of it fail.

## USP (why it's different)
1. **Real crisis, real data.** Replays actual ERCOT prices and Austin weather from Uri, not a toy scenario.
2. **Trust built in.** Every decision is labelled rule / Jev / safe default with its confidence. You can see *why* each home did what it did.
3. **Two customers, one fleet.** Makes Base's real tension explicit: grid revenue vs. the household's backup. Hard safety rules the model cannot override.
4. **Built to fail gracefully.** Chaos injection plus a circuit breaker: if devices, telemetry, or the model itself fail, the fleet degrades to rules and keeps its promise.
5. **A tool, not a demo.** Base can plug in its own dispatch policy and replay it against past crises before the next one.

## Innovation
- A System One model (Jev) in a control loop: typed decisions with calibrated confidence, batched (~150 homes/call, under 5 ms/home), gated by confidence.
- A three-tier decision stack: deterministic rules → calibrated model → conservative fallback.
- A policy comparison on real history, producing an insight number instead of just a visualization.

## Rubric → what to show
| Criterion (pts) | What proves it |
|---|---|
| Completeness (15) | The full replay runs end to end without crashing, including under chaos. Rehearse 5×. |
| Technical depth (15) | Async fleet simulator, batched Jev calls, confidence gate, circuit breaker, retries, cache, websocket streaming. Architecture diagram in README. Not a wrapper: Jev is one component. |
| Track problem (15) | Orchestration: thousands of independent agents coordinated; *how it holds up when pieces fail*: kill 15% of batteries, drop telemetry, cut Jev off. Grid Data: real ERCOT prices + weather drive everything. |
| The "why" (15) | Uri is the worst case Texas has lived through. A VPP's value (and risk) peaks exactly then. Promising MW you can't deliver costs money; exporting a medically critical home's reserve costs more. |
| Insight quality (10) | A non-obvious number from the replay, e.g. the reserve % that maximizes revenue while keeping ≥X% of homes powered, and how much a naive policy would have lost or put at risk. |
| Usability (10) | Swappable policy interface + replay any date range. "Base could run its dispatch policy through this tomorrow." |
| Creativity / looks (10) | Austin map: homes dimming across the city while fleet homes stay lit; promised-vs-delivered chart; decision-mix gauge. |
| Performance (10) | On-screen numbers: homes simulated, ticks/sec, Jev ms/home, % decisions needing Jev, $ per replay (and how gating/caching cut it). |

## Challenges (know them, say them)
- **Calibration:** naive prompts gave ~0.55 median confidence. Tune state/questions; pick the gate threshold from data.
- **Cost/latency at scale:** ~$16 per full naive replay. Solved by rules-first gating, packing, caching, replaying key days.
- **Provider risk:** Jev is in beta behind a single upstream. Circuit breaker + rules-only mode.
- **Simulation realism:** fleet is synthetic (Base data is private). Anchor parameters in public facts (battery size, 20% reserve, Austin), be explicit in README provenance.
- **Scope:** 36 build hours. Walking skeleton Friday, freeze Saturday ~9pm.

## Moat (honest version)
Hackathon moat = judgment + framing, not tech anyone couldn't rebuild:
- Domain-correct framing of Base's actual tension (retail promise vs. grid commitment vs. household safety).
- The trust layer: explainable, confidence-gated decisions plus safe degradation. This is the part that's hard to do well and what Chris keeps building.
- For a real product: a library of replayable historical crises + policy scoring becomes a regression suite for dispatch policy. Every new crisis makes it more valuable.

## Likely judge questions
- Why not just an optimizer / MILP? → Rules + optimizer cover the clear cases; the model handles fuzzy, context-heavy calls (household situation, local outage signals) and tells you when it isn't sure.
- How do you know Jev is right? → Hard rules bound it; agreement checks on clear cases; confidence gate; logged per decision.
- What if the model is down? → Circuit breaker → rules-only; show it live.
- How realistic is the fleet? → Real prices/weather/timeline; synthetic homes with public parameters; policy interface accepts Base's real data.
