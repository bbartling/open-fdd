"""Render vetted numeric tuning into a PostgreSQL rule; no DB connection required."""
import argparse, json, math, re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent

_INWC_TO_PA = 248.84

def render(rule_id, poll_seconds=300, overrides=None, dialect='postgres', canonical_units=False):
    rules = json.loads((ROOT / 'tuning_catalog.json').read_text())['rules']
    rule = next((r for r in rules if r['rule_id'] == rule_id or rule_id in r.get('aliases',[])), None)
    if rule is None:
        raise ValueError(f'Unknown rule: {rule_id}')
    if not math.isfinite(poll_seconds) or poll_seconds < 1:
        raise ValueError('poll_seconds must be finite and >= 1')
    values = json.loads((ROOT / 'runtime_defaults.json').read_text())
    controls = rule['parameters']
    chosen = {k: d['default'] for k,d in controls.items()}
    for key,value in (overrides or {}).items():
        if key not in controls:
            raise ValueError(f'Unknown tuner {key} for {rule_id}; use catalog keys (confirm_min is minutes)')
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
            raise ValueError(f'{key} must be a finite number')
        d = controls[key]
        lo, hi = d['min'], d['max']
        if canonical_units and d.get('kind') == 'air_pressure':
            lo = lo * _INWC_TO_PA
            hi = hi * _INWC_TO_PA
        if not lo <= value <= hi:
            raise ValueError(f'{key} outside [{d["min"]}, {d["max"]}]')
        chosen[key] = value
        if not d['effect_in_sql']:
            print(f'WARNING: {rule_id}.{key} has no effect in this SQL; see catalog.',file=sys.stderr)
    for key,d in controls.items():
        if key != 'confirm_min':
            values[d['sql_placeholder']] = chosen[key]
    # Apply legacy masters only when explicitly overridden; preserve explicit per-sensor choices.
    if 'mix_tol' in (overrides or {}):
        for key in ('eps_mat','eps_oat','eps_rat','eps_sat'):
            if key not in (overrides or {}):
                values[key.upper()] = chosen['mix_tol']
    if 'supply_tol' in (overrides or {}):
        values['EPS_SAT'] = chosen['supply_tol']
    values['MODE_DELAY_MIN'] = max(values.get('MODE_DELAY_MIN',0), values.get('STARTUP_DELAY_MIN',0))
    values['POLL_SECONDS'] = poll_seconds
    values['CONFIRM_SECONDS'] = chosen['confirm_min'] * 60
    values['CONFIRM_ROWS'] = max(1,math.ceil(values['CONFIRM_SECONDS']/poll_seconds))
    for key,value in list(values.items()):
        if key.endswith('_HOURS') and value > 0:
            prefix = key[:-6]
            rows = max(6 if prefix == 'FIXED_FLOW' else 1,math.ceil(value*3600/poll_seconds))
            values[prefix+'_ROWS'] = rows
            values[prefix+'_ROWS_PRECEDING'] = rows-1
            values[prefix+'_MIN_PERIODS'] = max(3,rows//2)
    for prefix in ('MODE_DELAY','STARTUP_DELAY'):
        rows = max(1,math.ceil(values.get(prefix+'_MIN',0)*60/poll_seconds))
        values[prefix+'_ROWS'] = rows
        values[prefix+'_ROWS_PRECEDING'] = rows-1
    if dialect not in ('postgres','warehouse','datafusion'):
        raise ValueError('dialect must be postgres, warehouse or datafusion')
    folder = ROOT/'original_datafusion' if dialect=='datafusion' else ROOT/dialect/'rules'
    if dialect=='postgres' and not folder.exists():
        folder=ROOT/'rules'
    sql = (folder / rule['sql_file']).read_text(encoding='utf-8')
    # Substitution is numeric only; data scope/identifiers belong in bound application queries.
    def replace(match):
        key = match[1]
        if key not in values:
            raise ValueError(f'Unresolved placeholder {key} in {rule_id}')
        value = values[key]
        return str(int(value)) if float(value).is_integer() else repr(float(value))
    return re.sub(r'\{\{([A-Z_0-9]+)\}\}',replace,sql)

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('rule_id')
    p.add_argument('--poll-seconds',type=float,default=300)
    p.add_argument('--params',default='{}',help='JSON tuner overrides')
    p.add_argument('--dialect',choices=['postgres','warehouse','datafusion'],default='postgres')
    args = p.parse_args()
    try:
        print(render(args.rule_id,args.poll_seconds,json.loads(args.params),args.dialect))
    except (ValueError,TypeError) as exc:
        p.error(str(exc))
