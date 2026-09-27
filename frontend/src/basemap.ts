import type { TransformStyleFunction } from 'maplibre-gl'

type Style = ReturnType<TransformStyleFunction>
type Layer = Style['layers'][number]

/** The stock style we start from; `nightStyle` keeps a few of its layers and repaints them. */
export const BASEMAP_STYLE = 'https://tiles.openfreemap.org/styles/dark'

// The night palette (docs/design.md, "The scene"). Everything sits well below the home dots in
// brightness, so the fleet is the brightest thing on the map.
const NIGHT = {
  background: '#0a0a0b',
  park: '#0e1310',
  water: '#0b1219',
  road: { minor: '#171718', major: '#1f1f20', motorway: '#29292a' },
  building: '#161618',
  label: '#56544f',
  labelHalo: '#0a0a0b',
}

const dimLabel = { 'text-color': NIGHT.label, 'text-halo-color': NIGHT.labelHalo, 'text-halo-width': 1, 'text-halo-blur': 0 }

/** Thin lines that widen a little with zoom. */
const roadWidth = (min: number, max: number) => ['interpolate', ['exponential', 1.5], ['zoom'], 10, min, 18, max]

/**
 * Per kept layer id, the paint (and layout) to put over the stock one. Layers not listed are dropped:
 * road shields and names, one-way arrows, POIs, rail, boundaries, and every place label above
 * neighbourhoods and suburbs.
 */
const KEEP: Record<string, { paint?: Record<string, unknown>; layout?: Record<string, unknown> }> = {
  background: { paint: { 'background-color': NIGHT.background } },
  water: { paint: { 'fill-color': NIGHT.water } },
  waterway: { paint: { 'line-color': NIGHT.water } },
  landuse_park: { paint: { 'fill-color': NIGHT.park, 'fill-opacity': 0.8 } },
  highway_minor: { paint: { 'line-color': NIGHT.road.minor, 'line-width': roadWidth(0.3, 4), 'line-opacity': 1 } },
  highway_major_inner: { paint: { 'line-color': NIGHT.road.major, 'line-width': roadWidth(0.6, 8) } },
  highway_motorway_inner: { paint: { 'line-color': NIGHT.road.motorway, 'line-width': roadWidth(1, 10) } },
  // A generous collision padding thins the labels out to a few.
  water_name: { paint: dimLabel, layout: { 'text-size': 11, 'text-padding': 48 } },
  place_suburb: { paint: dimLabel, layout: { 'text-size': 10, 'text-padding': 48, 'text-letter-spacing': 0.1 } },
  place_other: { paint: dimLabel, layout: { 'text-size': 9, 'text-padding': 64, 'text-letter-spacing': 0.1 } },
}

/** Dim 3D buildings, in place of the stock flat footprints (same tiles and fields as OpenFreeMap's liberty style). */
const BUILDINGS: Layer = {
  id: 'building-3d',
  type: 'fill-extrusion',
  source: 'openmaptiles',
  'source-layer': 'building',
  minzoom: 13,
  paint: {
    'fill-extrusion-color': NIGHT.building,
    'fill-extrusion-height': ['get', 'render_height'],
    'fill-extrusion-base': ['get', 'render_min_height'],
    'fill-extrusion-opacity': 0.6,
  },
}

/** OpenFreeMap's dark style, restyled into Simuritor's muted night basemap. Pass as `transformStyle`. */
export const nightStyle: TransformStyleFunction = (_previous, next) => {
  const kept = next.layers.flatMap((layer): Layer[] => {
    const over = KEEP[layer.id]
    if (!over) return []
    return [
      {
        ...layer,
        paint: { ...(layer as { paint?: object }).paint, ...over.paint },
        layout: { ...(layer as { layout?: object }).layout, ...over.layout },
      } as Layer,
    ]
  })
  // Buildings above the ground layers, labels above everything.
  const isLabel = (l: Layer) => l.type === 'symbol'
  return { ...next, layers: [...kept.filter((l) => !isLabel(l)), BUILDINGS, ...kept.filter(isLabel)] }
}
