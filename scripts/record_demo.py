"""Export three reproducible, compact demo recordings from the wire serializer."""
import gzip
import json
from pathlib import Path
from backend.schema import ReplayParams
from backend.serialize import init_message, replay_sim, tick_message

RUNS = [('uri-10', 'uri', .1), ('uri-30', 'uri', .3), ('normal-30', 'normal', .3)]

def main():
    out = Path('frontend/public/replays')
    out.mkdir(parents=True, exist_ok=True)
    for name, scenario, contract in RUNS:
        params = ReplayParams(scenario=scenario, contract=contract)
        sim = replay_sim(params)
        init = init_message(sim, params).model_dump(mode='json')
        ticks = []
        while not sim.done:
            tick = tick_message(sim.fleet, sim.step()).model_dump(mode='json')
            tick['homes'] = [[h['soc'], h['grid'], h['action'], h['kw']] for h in tick['homes']]
            ticks.append(tick)
        payload = json.dumps({'init': init, 'ticks': ticks}, separators=(',', ':'), allow_nan=False).encode()
        target = out / f'{name}.json.gz'
        target.write_bytes(gzip.compress(payload, compresslevel=6, mtime=0))
        print(f'{name}: {len(ticks)} ticks, {target.stat().st_size / 1e6:.1f} MB')

if __name__ == '__main__':
    main()
