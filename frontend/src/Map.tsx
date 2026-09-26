import type { FeatureCollection } from 'geojson'
import { type GeoJSONSource, MapLibreMap, setWorkerUrl } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import { useEffect, useRef, useState } from 'react'
import { type HomeVisual, homeVisual } from './homeVisual.ts'
import { cssVar } from './tokens.ts'
import type { HomeState, InitMessage, TickMessage } from './types.ts'

const BASEMAP_STYLE = 'https://tiles.openfreemap.org/styles/liberty'
const AUSTIN: [number, number] = [-97.75, 30.3]
const SOURCE = 'homes'

// MapLibre looks for its worker next to its own module, which isn't where Vite puts it.
// `?worker&url` has Vite bundle the worker (and the chunk it imports) and hand us its URL.
setWorkerUrl(workerUrl)

/** One point per home with its visual state. Before the first tick every home shows as on grid. */
function homesGeoJSON(init: InitMessage, tick: TickMessage | null): FeatureCollection {
  const state = new Map<string, HomeState>(tick?.homes.map((h) => [h.id, h]))
  return {
    type: 'FeatureCollection',
    features: init.homes.map((h) => {
      const s = state.get(h.id)
      const visual: HomeVisual = s ? homeVisual(s, h.tier) : 'grid'
      return {
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [h.lon, h.lat] },
        properties: { id: h.id, visual },
      }
    }),
  }
}

/**
 * The scene: an OpenFreeMap basemap with every home as a dot in ONE circle layer.
 * The layer and style are set up once; each tick only replaces the source's data.
 */
export function FleetMap({ init, tick }: { init: InitMessage | null; tick: TickMessage | null }) {
  const container = useRef<HTMLDivElement>(null)
  const map = useRef<MapLibreMap | null>(null)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    const m = new MapLibreMap({ container: container.current!, style: BASEMAP_STYLE, center: AUSTIN, zoom: 10 })
    map.current = m
    m.on('load', () => {
      // State colours come from the CSS tokens, so the map and the rest of the UI share one palette.
      const colour = (token: string) => cssVar(`--state-${token}`)
      m.addSource(SOURCE, { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
      m.addLayer({
        id: SOURCE,
        type: 'circle',
        source: SOURCE,
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 9, 3, 13, 6],
          'circle-color': [
            'match',
            ['get', 'visual'],
            'export',
            colour('export'),
            'backup',
            colour('backup'),
            'dark',
            colour('dark'),
            'dark_contract',
            colour('dark-contract'),
            colour('grid'),
          ],
          // Both darks are hollow as well as grey, so they don't rely on colour alone; dark by
          // contract has the thinner, fainter ring.
          'circle-opacity': ['match', ['get', 'visual'], ['dark', 'dark_contract'], 0, 1],
          'circle-stroke-width': ['match', ['get', 'visual'], 'dark', 1.5, 'dark_contract', 1, 0.5],
          'circle-stroke-opacity': ['match', ['get', 'visual'], 'dark_contract', 0.7, 1],
          'circle-stroke-color': [
            'match',
            ['get', 'visual'],
            'dark',
            colour('dark'),
            'dark_contract',
            colour('dark-contract'),
            cssVar('--surface'),
          ],
        },
      })
      setLoaded(true)
    })
    return () => {
      m.remove()
      map.current = null
      setLoaded(false)
    }
  }, [])

  // Frame the fleet once per init (connect or reset).
  useEffect(() => {
    if (!loaded || !init) return
    const lons = init.homes.map((h) => h.lon)
    const lats = init.homes.map((h) => h.lat)
    map.current?.fitBounds(
      [
        [Math.min(...lons), Math.min(...lats)],
        [Math.max(...lons), Math.max(...lats)],
      ],
      { padding: 40, duration: 0 },
    )
  }, [loaded, init])

  useEffect(() => {
    if (!loaded || !init) return
    map.current?.getSource<GeoJSONSource>(SOURCE)?.setData(homesGeoJSON(init, tick))
  }, [loaded, init, tick])

  return <div ref={container} className="map-canvas" />
}
