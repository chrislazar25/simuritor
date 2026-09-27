# Simuritor demo — five minutes

Before recording, start the backend and frontend using the README commands. Give the backend about 30 seconds to warm its default contract comparisons. Open the app at a desktop viewport, restore default terms by opening `/`, and keep the backend console available. Use the live backend; the frontend alone does not replay data. Keep your camera on as requested by the hackathon guide.

| Time | Show | Explain |
|---|---|---|
| 0:00–0:30 | Team intro and the map; start Play at 32 ticks/s | “Simuritor stress-tests a home-battery fleet's utility commitments against Winter Storm Uri, while accounting for the backup promised to homeowners.” |
| 0:30–1:30 | Pause during Feb 15; allow queued ticks to settle. Point out neighborhoods on battery and the failover log. | Real ERCOT prices and Austin temperatures drive 3,000 simulated batteries. Whole neighborhoods lose grid power; devices also fail silently. Homes with spare capacity take over lost commitments. Recovery delays are modeled assumptions. |
| 1:30–2:30 | Find qualifying contract | The default comparison gives 5.4 MW / 15% in Uri, averaging 95.6% of called intervals kept. The comparison week passes through 21.6 MW / 60%, the largest tested size. Explain the 95% bar and the normal week's single call. |
| 2:30–3:15 | Close the comparison, enable Storm clause, evaluate again, then Apply 20% · Uri | One contract term changes the result: avoiding calls before severe cold raises the qualifying size. Applying the result resets the map with those terms; press Play to run it. |
| 3:15–4:15 | Briefly show the architecture diagram and backend console | Simulation, policy, faults and commitments are separate pieces. A typed serializer feeds the live map. Tests cover physical limits, reserve protection, failure coverage, accounting and replay reproducibility. |
| 4:15–5:00 | Return to the comparison and expand What qualifies? | The useful finding: energy exhaustion can break a commitment even when every device failure is covered. The next validation steps are actual fleet loads, forecast error, real feeder topology and actual contract terms. |

Use the displayed results for the selected terms; don't quote a result from another run. The live Fleet panel reports intervals kept across the entire replay so far, while the Uri comparison scores only Feb 14–18 and averages three seeds. They need not match.

Avoid calling the result a guaranteed safe contract, interpreting modeled cash flow as Base's P&L, or presenting 5/11-second recovery as a device benchmark. The simulator currently knows future weather and excludes replacement homes that would fail later in the same tick.

Before submitting, add the final Loom link to the README and supply the team roster and 150–300 word write-up through the submission form. The screenshots in the README document the app; the video should demonstrate the live loop.
