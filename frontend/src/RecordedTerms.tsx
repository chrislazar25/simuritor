import { RUNS } from './recordedReplay.ts'
import type { InitMessage, ReplayParams } from './types.ts'
import type { Terms } from './terms.ts'
const DEFAULTS: ReplayParams = { policy: 'contract', standard_backup_h: 8, max_calls_per_day: 1, emergency_uncapped: false, skip_before_storm: false, fault_rate: 0.001, headroom_mode: 'keep', homes: 3000, spread_by_domain: false, scenario: 'uri', contract: 0.3 }
export function RecordedTerms({ init, rejected, onReplay }: { init: InitMessage | null; rejected: string | null; onReplay: (terms: Terms | null) => void }) {
  return <div className="terms">
    <p className="panel-intro">How much can the fleet promise while protecting home backup?</p>
    <p>Recorded demo · 3,000 simulated batteries · seed 0 · 8 h standard backup.</p>
    {rejected && <p role="alert" className="terms-error">{rejected}</p>}
    <div className="terms-actions">{RUNS.map(run => <button key={run.id} type="button" disabled={!init && !rejected} aria-pressed={init?.params.scenario === run.scenario && init.params.contract === run.contract} onClick={() => onReplay({ ...(init?.params ?? DEFAULTS), scenario: run.scenario as 'uri' | 'normal', contract: run.contract })}>{run.label}</button>)}</div>
    <p>In the three-seed experiment, the largest tested contract meeting our 95% delivery bar was 15% during Uri and 60% in the normal week. The normal week had only one call.</p>
    <p>Real prices, weather and home locations; simulated batteries, load, outages and faults. These results describe this model, not a real fleet guarantee.</p>
    <p><a href="https://github.com/chrislazar25/simuritor" target="_blank" rel="noreferrer">Code, assumptions & full results</a> · <a href="https://www.loom.com/share/2e72a407f1cb4d49aa9815822353747e" target="_blank" rel="noreferrer">5-minute walkthrough</a></p>
    <p className="terms-note">Run locally for editable contract terms and the qualifying-contract sweep. Simuritor is an independent hackathon project.</p>
  </div>
}
