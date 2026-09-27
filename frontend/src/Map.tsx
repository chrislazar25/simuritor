import type { FeatureCollection } from 'geojson'
import { type AddLayerObject, type GeoJSONSource, MapLibreMap, setWorkerUrl } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import { useEffect, useMemo, useRef, useState } from 'react'
import { BASEMAP_STYLE, BUILDINGS_LAYER, nightStyle } from './basemap.ts'
import { type HomeVisual, homeVisual } from './homeVisual.ts'
import { cssVar } from './tokens.ts'
import type { FailoverEvent, InitMessage, TickMessage } from './types.ts'

const AUSTIN: [number, number] = [-97.75, 30.3]
const CAMERA = { pitch: 50, bearing: -15 }
// Room for the top bar above the fleet.
const FRAME_PADDING = { top: 96, bottom: 48, left: 48, right: 48 }
const SOURCE = 'homes'
const GLOW = 'homes-glow'
// Zoomed in, each home is a small 3D box with a halo on the ground (the "3D view").
const BOXES = 'home-boxes'
const HALO = 'home-halo'
const OUTLINE = 'home-outline'
const DARK_RING = 'home-dark-ring'
const BOX_HALF_M = 7 // a 14 m square footprint
const BOX_HEIGHT_M = 8
const HALO_M = 22 // halo radius on the ground
const DARK_RING_M = 13 // just clear of the box's corners
// Dots fade out and boxes fade in across this zoom range.
const FADE_FROM = 14.25
const FADE_TO = 14.75
const RINGS = 'failover-rings'
const RING_MS = 1000

// MapLibre looks for its worker next to its own module, which isn't where Vite puts it.
// `?worker&url` has Vite bundle the worker (and the chunk it imports) and hand us its URL.
setWorkerUrl(workerUrl)

type CirclePaint = NonNullable<Extract<AddLayerObject, { type: 'circle' }>['paint']>

/** MapLibre types expressions as literal tuples, which expressions built in code can't match; this vouches for one. */
const expr = (e: unknown[]) => e as never

/** The home dot's radius by zoom, times `scale` (a number or a per-feature expression). */
function dotRadius(scale: unknown = 1) {
  const stops: [number, number][] = [
    [9, 3],
    [12, 5],
    [15, 9],
    [18, 16],
  ]
  return expr(['interpolate', ['exponential', 1.5], ['zoom'], ...stops.flatMap(([z, r]) => [z, scale === 1 ? r : ['*', r, scale]])])
}

/** Pixels per metre on the ground at `zoom`, at the fleet's latitude (Austin). */
const pxPerMetre = (zoom: number) => 2 ** zoom / (156543.03 * Math.cos((AUSTIN[1] * Math.PI) / 180))

/** A ground distance as a circle radius that stays `metres` wide at every zoom. */
const metres = (m: number) => expr(['interpolate', ['exponential', 2], ['zoom'], 14, m * pxPerMetre(14), 22, m * pxPerMetre(22)])

/**
 * `a` below the fade and `b` above it: the dot and 3D views cross-fade on zoom. The ends may be
 * per-feature expressions.
 */
const crossFade = (a: unknown, b: unknown) => expr(['interpolate', ['linear'], ['zoom'], FADE_FROM, a, FADE_TO, b])

// Geometry is built once per init and never changes. Each feature's `id` is the home's index in
// init.homes; its visual state lives in feature-state, so a tick only touches homes that changed.
function pointsGeoJSON(init: InitMessage): FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: init.homes.map((h, i) => ({
      type: 'Feature',
      id: i,
      geometry: { type: 'Point', coordinates: [h.lon, h.lat] },
      properties: {},
    })),
  }
}

/** A square footprint per home, BOX_HALF_M each side of its point. */
function boxesGeoJSON(init: InitMessage): FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: init.homes.map((h, i) => {
      const dLat = BOX_HALF_M / 111_320
      const dLon = dLat / Math.cos((h.lat * Math.PI) / 180)
      const [w, e, s, n] = [h.lon - dLon, h.lon + dLon, h.lat - dLat, h.lat + dLat]
      return {
        type: 'Feature',
        id: i,
        geometry: {
          type: 'Polygon',
          coordinates: [
            [
              [w, s],
              [e, s],
              [e, n],
              [w, n],
              [w, s],
            ],
          ],
        },
        properties: {},
      }
    }),
  }
}

/** Each home's visual state; before the first tick every home shows as on grid. */
function visuals(init: InitMessage, tick: TickMessage | null): HomeVisual[] {
  const state = new Map(tick?.homes.map((h) => [h.id, h]))
  return init.homes.map((h) => {
    const s = state.get(h.id)
    return s ? homeVisual(s, h.tier) : 'grid'
  })
}

/** A failover ring: where, which kind, and when it started (performance.now()). */
type Ring = { at: [number, number]; kind: FailoverEvent['kind']; start: number }

/**
 * The rings at `now`: each grows from just outside the dot and fades out over RING_MS.
 * With `still` (prefers-reduced-motion) they hold one size at full strength instead.
 */
function ringsGeoJSON(rings: Iterable<Ring>, now: number, still: boolean): FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: [...rings].map((r) => {
      const t = still ? 0.3 : Math.min((now - r.start) / RING_MS, 1)
      return {
        type: 'Feature',
        geometry: { type: 'Point', coordinates: r.at },
        properties: { kind: r.kind, grow: 2 + 3.5 * (1 - (1 - t) ** 3), alpha: still ? 1 : 1 - t * t },
      }
    }),
  }
}

const reducedMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches

/**
 * The scene: a muted night basemap (basemap.ts), tilted, with every home as a dot in ONE circle
 * layer plus a soft glow under it; zoomed in past ~14.5 the dots cross-fade to small 3D boxes
 * with a halo on the ground (dark homes: a ring and footprint outline instead). A red ring
 * flashes on homes that fail over, in either view.
 * Layers and style are set up once; each tick only updates the homes that changed.
 */
export function FleetMap({ init, tick }: { init: InitMessage | null; tick: TickMessage | null }) {
  const container = useRef<HTMLDivElement>(null)
  const map = useRef<MapLibreMap | null>(null)
  const [loaded, setLoaded] = useState(false)
  // What each home's feature-state holds now, so a tick only sets the ones that changed.
  const shown = useRef<HomeVisual[]>([])
  const rings = useRef(new Map<string, Ring>())
  const frame = useRef<number | null>(null)

  const positions = useMemo(
    () => new Map<string, [number, number]>(init?.homes.map((h) => [h.id, [h.lon, h.lat]])),
    [init],
  )

  useEffect(() => {
    const m = new MapLibreMap({ container: container.current!, center: AUSTIN, zoom: 10, ...CAMERA })
    m.setStyle(BASEMAP_STYLE, { transformStyle: nightStyle })
    map.current = m
    m.on('load', () => {
      // State colours come from the CSS tokens, so the map and the rest of the UI share one palette.
      const colour = (token: string) => cssVar(`--state-${token}`)
      const visual = ['coalesce', ['feature-state', 'visual'], 'grid']
      const byVisual = (dark: string, darkContract: string) =>
        expr([
          'match',
          visual,
          'export',
          colour('export'),
          'backup',
          colour('backup'),
          'dark',
          dark,
          'dark_contract',
          darkContract,
          colour('grid'),
        ])
      const powered = (on: number) => ['match', visual, ['dark', 'dark_contract'], 0, on]
      // Dark homes are hollow rings in both views, so they don't rely on colour alone: dark has a
      // heavier ring, dark by contract a thinner, fainter one. `other` is everyone else's stroke.
      const darkRing = (other: { width: number; opacity: number }) => ({
        width: expr(['match', visual, 'dark', 1.5, 'dark_contract', 1, other.width]),
        opacity: ['match', visual, 'dark', 1, 'dark_contract', 0.7, other.opacity],
        colour: expr(['match', visual, 'dark', colour('dark'), 'dark_contract', colour('dark-contract'), cssVar('--surface')]),
      })
      const dotRing = darkRing({ width: 0.5, opacity: 1 })
      const groundRing = darkRing({ width: 0, opacity: 0 })
      const empty: FeatureCollection = { type: 'FeatureCollection', features: [] }
      m.addSource(SOURCE, { type: 'geojson', data: empty })
      m.addSource(BOXES, { type: 'geojson', data: empty })
      m.addSource(RINGS, { type: 'geojson', data: empty })
      // Dot view. A soft glow under powered homes; dark homes get none, so they read as gone.
      m.addLayer({
        id: GLOW,
        type: 'circle',
        source: SOURCE,
        maxzoom: FADE_TO,
        paint: {
          'circle-radius': dotRadius(3),
          'circle-color': byVisual(colour('dark'), colour('dark-contract')),
          'circle-blur': 1,
          'circle-opacity': crossFade(powered(0.22), 0),
        },
      })
      // 3D view: the same glow as a halo lying on the ground under each powered box.
      m.addLayer({
        id: HALO,
        type: 'circle',
        source: SOURCE,
        minzoom: FADE_FROM,
        paint: {
          'circle-radius': metres(HALO_M),
          'circle-color': byVisual(colour('dark'), colour('dark-contract')),
          'circle-blur': 1,
          'circle-pitch-alignment': 'map',
          'circle-opacity': crossFade(0, powered(0.5)),
        },
      })
      // Dark homes keep their hollow ring in the 3D view, lying on the ground around the box. It
      // starts at the dot's size, so the cross-fade doesn't jump, and is true ground size by z17.
      m.addLayer({
        id: DARK_RING,
        type: 'circle',
        source: SOURCE,
        minzoom: FADE_FROM,
        paint: {
          'circle-radius': expr([
            'interpolate',
            ['exponential', 2],
            ['zoom'],
            FADE_FROM,
            8,
            17,
            DARK_RING_M * pxPerMetre(17),
            22,
            DARK_RING_M * pxPerMetre(22),
          ]),
          'circle-color': 'transparent',
          'circle-pitch-alignment': 'map',
          // Thicker close up, where a hairline on the tilted ground all but vanishes.
          'circle-stroke-width': expr(['interpolate', ['linear'], ['zoom'], 15, groundRing.width, 18, ['*', 2, groundRing.width]]),
          'circle-stroke-color': groundRing.colour,
          'circle-stroke-opacity': crossFade(0, groundRing.opacity),
        },
      })
      // A thin outline round dark homes' footprints, so the box's base edge reads against the
      // land. It sits under the basemap's buildings: a flat layer drawn after an extrusion paints
      // over it, and the boxes often stand inside a real building.
      m.addLayer(
        {
          id: OUTLINE,
          type: 'line',
          source: BOXES,
          minzoom: FADE_FROM,
          paint: {
            'line-color': groundRing.colour,
            'line-width': 1,
            'line-opacity': crossFade(0, groundRing.opacity),
          },
        },
        BUILDINGS_LAYER,
      )
      // A plain box per home, no roof. Dark homes are dim grey boxes, well below any lit one.
      m.addLayer({
        id: BOXES,
        type: 'fill-extrusion',
        source: BOXES,
        minzoom: FADE_FROM,
        paint: {
          'fill-extrusion-color': byVisual(colour('dark'), colour('dark-contract')),
          'fill-extrusion-height': BOX_HEIGHT_M,
          'fill-extrusion-opacity': crossFade(0, 1),
        },
      })
      m.addLayer({
        id: SOURCE,
        type: 'circle',
        source: SOURCE,
        maxzoom: FADE_TO,
        paint: {
          'circle-radius': dotRadius(),
          'circle-color': byVisual(colour('dark'), colour('dark-contract')),
          'circle-opacity': crossFade(powered(1), 0),
          'circle-stroke-width': dotRing.width,
          'circle-stroke-opacity': crossFade(dotRing.opacity, 0),
          'circle-stroke-color': dotRing.colour,
        },
      })
      // Failover rings, red. Shape tells the kinds apart, not colour: warned is one ring,
      // silent (no warning, caught by missed heartbeats) is a heavier double ring.
      const ring: CirclePaint = {
        'circle-color': 'transparent',
        'circle-stroke-color': cssVar('--grid-off'),
        'circle-stroke-opacity': ['get', 'alpha'],
      }
      m.addLayer({
        id: RINGS,
        type: 'circle',
        source: RINGS,
        paint: {
          ...ring,
          'circle-radius': dotRadius(['get', 'grow']),
          'circle-stroke-width': ['match', ['get', 'kind'], 'silent', 2, 1.5],
        },
      })
      m.addLayer({
        id: `${RINGS}-inner`,
        type: 'circle',
        source: RINGS,
        filter: ['==', ['get', 'kind'], 'silent'],
        paint: { ...ring, 'circle-radius': dotRadius(['*', 0.5, ['get', 'grow']]), 'circle-stroke-width': 2 },
      })
      setLoaded(true)
    })
    return () => {
      if (frame.current !== null) cancelAnimationFrame(frame.current)
      frame.current = null
      m.remove()
      map.current = null
      setLoaded(false)
    }
  }, [])

  // Frame the fleet once per init (connect or reset), and drop any rings from the last replay.
  useEffect(() => {
    if (!loaded || !init) return
    const lons = init.homes.map((h) => h.lon)
    const lats = init.homes.map((h) => h.lat)
    map.current?.fitBounds(
      [
        [Math.min(...lons), Math.min(...lats)],
        [Math.max(...lons), Math.max(...lats)],
      ],
      { ...CAMERA, padding: FRAME_PADDING, duration: 0 },
    )
    rings.current.clear()
    map.current?.getSource<GeoJSONSource>(RINGS)?.setData(ringsGeoJSON([], 0, false))
  }, [loaded, init])

  // Home geometry, once per init. Feature-state is cleared so every home starts as on grid.
  useEffect(() => {
    const m = map.current
    if (!loaded || !init || !m) return
    for (const [source, data] of [
      [SOURCE, pointsGeoJSON(init)],
      [BOXES, boxesGeoJSON(init)],
    ] as const) {
      m.removeFeatureState({ source })
      m.getSource<GeoJSONSource>(source)?.setData(data)
    }
    shown.current = init.homes.map(() => 'grid')
  }, [loaded, init])

  // Per tick, only homes whose visual state changed get new feature-state, in both views.
  useEffect(() => {
    const m = map.current
    if (!loaded || !init || !m) return
    visuals(init, tick).forEach((visual, id) => {
      if (shown.current[id] === visual) return
      shown.current[id] = visual
      m.setFeatureState({ source: SOURCE, id }, { visual })
      m.setFeatureState({ source: BOXES, id }, { visual })
    })
  }, [loaded, init, tick])

  // Failover rings run on real time (~1 s each), not tick time. Reduced motion: a still ring on
  // this tick's failovers only, replaced by the next tick.
  useEffect(() => {
    const source = map.current?.getSource<GeoJSONSource>(RINGS)
    if (!loaded || !tick || !source) return
    const still = reducedMotion()
    const now = performance.now()
    if (still) rings.current.clear()
    for (const e of tick.failovers) {
      const at = positions.get(e.home_id)
      if (at) rings.current.set(e.home_id, { at, kind: e.kind, start: now })
    }
    if (still) {
      source.setData(ringsGeoJSON(rings.current.values(), now, true))
      return
    }
    if (rings.current.size === 0 || frame.current !== null) return
    const step = () => {
      const t = performance.now()
      for (const [id, r] of rings.current) if (t - r.start >= RING_MS) rings.current.delete(id)
      source.setData(ringsGeoJSON(rings.current.values(), t, false))
      frame.current = rings.current.size > 0 ? requestAnimationFrame(step) : null
    }
    frame.current = requestAnimationFrame(step)
  }, [loaded, tick, positions])

  return <div ref={container} className="map-canvas" />
}
