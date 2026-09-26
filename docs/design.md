# Simuritor: design direction

Status: **vibe not locked.** Tonight ships a thin, neutral version whose seams let it grow into either reference below without a rewrite.

## Purpose and audience
- **Job:** watch a real crisis (Winter Storm Uri) roll through a city and see, home by home, how a battery fleet's dispatch policy holds up.
- **Who:** Base engineers and judges watching a 5-minute demo; later, an operator replaying past crises against their own policy.
- **First viewport:** the Austin map with homes on it and time moving. No landing page, no hero copy.
- **Feel:** simulation software. The map is the scene; readouts, charts and counters tick along around it like instruments. (Which metrics fill those instruments is decided later; this doc only reserves the slots.)

## The two references

| | Simile (simile.com) | Base (basepowercompany.com) |
|---|---|---|
| Idiom | Isometric city diorama, pixel art (SimCity / Pokémon feel) | Isometric 3D-rendered house on a lawn tile |
| Palette | Saturated, playful; navy + coral accents | Muted and warm: off-white `#f0eeeb`, deep green `#1e4d2b`, grey scale `#292826`–`#d8d7d5`; accents blue `#048ee5`, orange `#ed6c30`, amber `#f7c33c`; a dedicated `grid-off` red `#bf5249` |
| Type | Clean sans (GT Standard) + pixel sprites | PP Neue Montreal (sans), Clarendon Wide (display) |
| Signature interaction | Rotating city dioramas; scenario cards with confidence levels | "Grid ON/OFF" switch: two renders of one house cross-fade (300 ms). **On:** cyan line flows pole → battery → house, windows lit. **Off:** pole wires cut, battery glows, cyan line only battery → house, windows *still lit*. |
| What we take | Playfulness, sprite-per-state homes, the diorama-as-scene idea | Restraint, the palette discipline, and the grid switch's visual language: **lit windows = home has power; cyan line = where power flows** |

Both share the same structure (an isometric scene of homes whose state is visible at a glance), which is why one data model and one set of seams can serve either.

Both sites are references, not sources: we don't use their images, fonts or logos, and Simuritor never presents itself as a Base product.

## Memorable detail
**The city dims, the fleet stays lit.** When outages hit Feb 15, homes lose the grid but keep their lights on from the battery, until some don't. The one state we design hardest for is **dark**: a home, possibly a medical-device home, with no power at all. This is already the pitch's map idea (`docs/pitch-points.md`).

## Home visual states (the core seam)
One function maps wire data to a visual state; every renderer and theme consumes only this.

| Visual state | From the wire (`HomeState`) | Meaning | Tonight (dot) | Base-style later | Pixel-style later |
|---|---|---|---|---|---|
| `grid` | `grid` and action `hold`/`charge` | On grid, idle or charging | green | lit windows, cyan line from pole | lit sprite |
| `export` | `grid` and action `discharge` | Selling to the grid | blue | cyan line flowing *out* to the pole | lit sprite + outbound spark |
| `backup` | not `grid`, `soc > 0` | Grid down, battery powering the house | amber | wires cut, battery glows, windows lit | lit sprite, pole broken |
| `dark` | not `grid`, `soc == 0` | Lights out | dim grey, hollow | windows dark, no glow | unlit sprite |

- Matches the spec's dot colours (`docs/slice-spec.md`). `charge` may get its own treatment later.
- Colour is never the only signal: `dark` is also hollow and dim, so it reads for colour-blind viewers and on a grayscale screenshot.
- Household type (medical, elderly, wfh) is an **overlay**, not a state (e.g. a ring or badge), added when we decide how to highlight at-risk homes.

## Layout (slots, not content)
```
┌──────────────────────────────────────────────────────────────┐
│ SIMURITOR   Feb 15 05:00 CT   [EEA3]   $9,618/MWh   ▶ ⏸ 8× ↺ │  top bar: clock, grid status, price, playback
├────────────────────────────────────────────┬─────────────────┤
│                                            │  counters slot  │
│                                            │  (homes on grid │
│             Austin map (the scene)         │   / battery /   │
│                                            │   dark, revenue)│
│                                            ├─────────────────┤
│                                            │  chart slot     │
│                                            │  (price +       │
│                                            │   delivered MW) │
└────────────────────────────────────────────┴─────────────────┘
```
- Map takes the most space and never shifts; panels have fixed widths so ticking numbers don't reflow the layout.
- Instruments sit beside the map, not on top of it, tonight. A later theme may float them over the map as a HUD.
- Narrow screens: panels stack under the map. Not a priority; the demo is desktop.

## Theming seams (what keeps it swappable)
1. **Semantic tokens** as CSS variables: `--surface`, `--text`, `--muted`, `--accent`, `--state-grid`, `--state-export`, `--state-backup`, `--state-dark`, `--grid-off`, `--font-ui`, `--font-num`. Components use only these names; a theme is one block of values under `[data-theme="…"]`.
2. **`homeVisual(state) → visual state`**: one pure function, shared by map, legend and tooltips.
3. **Home renderer** behind one component: tonight a MapLibre circle layer coloured by visual state; later a symbol layer with per-state house icons (Base-style renders or pixel sprites), same input.
4. **Basemap style per theme**: a style URL in the theme, not hard-coded in the map.
5. **Scene lighting from simulated time** (below): its own small module, so a theme can restyle it or turn it off.
6. Growth path toward the diorama look: MapLibre can tilt the camera (pitch) and extrude buildings, which gets close to the isometric feel without a game engine.

## Scene lighting: the sim's own sun
The map's day/night follows the simulated clock, so there is no light-or-dark default to pick.
- **Input:** tick `t` plus Austin's lat/lon → sun elevation (computed in the frontend, e.g. with `suncalc`; no schema change).
- **Output:** a daylight factor 0–1 that cross-fades two raster basemaps (Carto light and Carto dark) by opacity. One cheap paint update per tick; the home layer is untouched.
- **Smooth, not a switch:** the factor ramps through twilight, because at 8 ticks/s a simulated day lasts ~12 s and a hard flip would strobe.
- **Only the scene changes.** Top bar, panels and numbers keep one fixed theme so instruments read the same at noon and 3 am.
- State colours must pass contrast on both basemaps; `dark` homes stay hollow and dim either way.
- The story lands at night on its own: outages begin Feb 15 02:00, so "the city dims" happens in the dark.
- `prefers-reduced-motion`: hold the scene at a fixed light level.

## Tonight's theme: neutral (Base-leaning)
- UI chrome (bars, panels): one fixed dark-neutral theme, independent of scene lighting.
- State colours from Base's palette, used as reference values only: grid `#77a45a`, export `#048ee5`, backup `#f7c33c` (warm window light), dark `#54524f`, grid-off `#bf5249`.
- Type: free, open-licence fonts. A clean grotesk for UI (e.g. Inter Tight) and a monospace with tabular figures for every number (e.g. JetBrains Mono), so readouts don't jitter as they tick. Pixel theme later: Silkscreen or Press Start 2P.

## Motion
- Everything moves with the tick. State transitions must finish within one tick (125 ms at 8 ticks/s) or the map lags behind the data; above ~16 ticks/s, snap instead of animating.
- Motion only to clarify change (a home going dark, the EEA badge changing). No decorative animation tonight.
- Honour `prefers-reduced-motion`.

## Performance constraints
- 500 homes tonight, 2,000+ Saturday, updating 8+ times a second: homes are drawn in one WebGL layer (MapLibre), never as DOM markers.
- Per-tick updates change only the home state data, not the layer or the map style.

## Not doing
- No landing page, hero copy, gradients or decorative blobs; no cards inside cards.
- No Base or Simile assets, fonts or logos.
- No theme switcher UI tonight; the seam exists, the second theme doesn't.

## Open (decide when locking the vibe)
- Base-style clean vs pixel diorama vs a blend (clean UI chrome, pixel scene)?
- Light or dark UI chrome (the scene follows the sun either way).
- How to flag at-risk homes (medical, elderly) on the map.
- Whether instruments stay beside the map or float over it as a HUD.
