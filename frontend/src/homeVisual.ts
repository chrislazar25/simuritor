import type { HomeInfo, HomeState } from './types.ts'

/** How a home looks, whatever draws it (docs/design.md, "Home visual states"). */
export type HomeVisual = 'grid' | 'export' | 'backup' | 'dark' | 'dark_contract'

/**
 * Grid down splits three ways: a tier `none` home is unpowered by contract (its battery keeps
 * its energy), any other home runs on battery until it runs out.
 */
export function homeVisual(home: Pick<HomeState, 'grid' | 'soc' | 'action'>, tier: HomeInfo['tier']): HomeVisual {
  if (!home.grid) {
    if (tier === 'none') return 'dark_contract'
    return home.soc > 0 ? 'backup' : 'dark'
  }
  return home.action === 'discharge' ? 'export' : 'grid'
}
