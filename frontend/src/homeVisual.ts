import type { HomeState } from './types.ts'

/** How a home looks, whatever draws it (docs/design.md, "Home visual states"). */
export type HomeVisual = 'grid' | 'export' | 'backup' | 'dark'

export function homeVisual(home: Pick<HomeState, 'grid' | 'soc' | 'action'>): HomeVisual {
  if (!home.grid) return home.soc > 0 ? 'backup' : 'dark'
  return home.action === 'discharge' ? 'export' : 'grid'
}
