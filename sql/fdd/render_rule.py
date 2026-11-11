"""Render vetted numeric tuning into a PostgreSQL rule; no DB connection required.

All tuning values are SI (degC, delta-degC, Pa, L/s, ...); the rules read SI inputs."""
import argparse, importlib.util, json, math, re, sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parents[1]
SWEEP_ROLE_SOURCE = REPO_ROOT / "open_fdd" / "data" / "sensor_sweep_roles.json"
ROLE_MAP_SOURCE = ROOT / "role_map.json"

# The sweep limits are validated by the same module the pandas sweeps use (one SI source of truth:
# open_fdd/data/sensor_sweep_limits.json). Loaded by path so this renderer does not import the pandas package.
_spec = importlib.util.spec_from_file_location("_sensor_sweep_catalog", REPO_ROOT / "open_fdd" / "rules" / "sensor_sweep_catalog.py")
sweep_catalog = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("_sensor_sweep_catalog", sweep_catalog)
_spec.loader.exec_module(sweep_catalog)

_RANGE_SCALE = {"absolute_temperature": "{{RANGE_SCALE_TEMPERATURE}}", "relative_humidity": "{{RANGE_SCALE_HUMIDITY}}",
                "air_pressure": "{{RANGE_SCALE_PRESSURE}}"}
_SPIKE_SCALE = {"absolute_temperature": "{{SPIKE_SCALE_TEMPERATURE}}", "relative_humidity": "{{SPIKE_SCALE_HUMIDITY}}",
                "air_pressure": "{{SPIKE_SCALE_PRESSURE}}"}

def _num(value):
    """Six-decimal SI literal (half-up), e.g. 1.666667, 20.0, 870.94."""
    return repr(float(Decimal(repr(float(value))).quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP)))

def _sweep_fragments(rule, role_limits, sql_by_name, names):
    """SQL fragments for the per-role limits of one sweep rule, in role-limit file order."""
    entries = [role_limits['roles'][n] for n in role_limits['roles'] if n in names]
    frag = {}
    rid = rule['rule_id']
    if rid == 'SV-RANGE':
        terms = []
        for e in entries:
            c = _num((Decimal(repr(e['lo'])) + Decimal(repr(e['hi']))) / 2)
            h = _num((Decimal(repr(e['hi'])) - Decimal(repr(e['lo']))) / 2)
            scale = _RANGE_SCALE.get(e['quantity'])
            hs = h + (' * ' + scale if scale else '')
            terms.append(f"(sensor_role = '{sql_by_name[e['role']]}' AND (value < ({c} - {hs}) OR value > ({c} + {hs})))")
        frag['SV_RANGE_BANDS'] = ' OR '.join(terms)
    elif rid == 'SV-SPIKE':
        terms = []
        for e in entries:
            scale = _SPIKE_SCALE.get(e['quantity'])
            lim = _num(e['spike_delta']) + (' * ' + scale if scale else '')
            terms.append(f"(sensor_role = '{sql_by_name[e['role']]}' AND previous_value IS NOT NULL AND epoch_seconds - previous_epoch <= {{{{MAX_SILENCE_SECONDS}}}} AND ABS(value - previous_value) > {lim})")
        frag['SV_SPIKE_BANDS'] = ' OR '.join(terms)
    elif rid in ('SV-FLATLINE', 'SV-STALE'):
        field, tuner = ('flat_tol', '{{FLATLINE_TOL}}') if rid == 'SV-FLATLINE' else ('stale_tol', '{{STALE_TOL}}')
        groups = {}
        for e in entries:
            v = sweep_catalog.explicit_role_value(e, field, role_limits)
            if v is not None:
                groups.setdefault(_num(v), []).append(sql_by_name[e['role']])
        whens = ''.join(" WHEN sensor_role IN (" + ','.join("'" + r + "'" for r in roles) + ") THEN " + v for v, roles in groups.items())
        frag['SV_FLATLINE_TOL' if rid == 'SV-FLATLINE' else 'SV_STALE_TOL'] = f'CASE{whens} ELSE {tuner} END' if whens else tuner
    elif rid == 'SV-RATE':
        base = '({{STEADY_FAULT_PER_HOUR}} * {{SENSOR_SPAN}} / 100.0)'
        whens = ''
        for e in entries:
            v = sweep_catalog.explicit_role_value(e, 'rate_per_h', role_limits)
            if v is not None:
                whens += f" WHEN sensor_role = '{sql_by_name[e['role']]}' THEN ({_num(v)} * {{{{SENSOR_SPAN}}}} / 100.0)"
        frag['SV_RATE_THRESHOLD'] = f'(CASE{whens} ELSE {base} END)' if whens else base
    return frag

def render(rule_id, poll_seconds=300, overrides=None, parameter_controls=None, role_limits=None):
    rules = json.loads((ROOT / 'tuning_catalog.json').read_text())['rules']
    rule = next((r for r in rules if r['rule_id'] == rule_id or rule_id in r.get('aliases',[])), None)
    if rule is None:
        raise ValueError(f'Unknown rule: {rule_id}')
    if not math.isfinite(poll_seconds) or poll_seconds < 1:
        raise ValueError('poll_seconds must be finite and >= 1')
    values = json.loads((ROOT / 'runtime_defaults.json').read_text())
    controls = parameter_controls if parameter_controls is not None else rule['parameters']
    chosen = {k: d['default'] for k,d in controls.items()}
    for key,value in (overrides or {}).items():
        if key not in controls:
            raise ValueError(f'Unknown tuner {key} for {rule_id}; use catalog keys (confirm_min is minutes)')
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
            raise ValueError(f'{key} must be a finite number')
        d = controls[key]
        if not d['min'] <= value <= d['max']:
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
            values[prefix+'_SECONDS'] = round(value * 3600)
            rows = max(6 if prefix == 'FIXED_FLOW' else 1,math.ceil(value*3600/poll_seconds))
            values[prefix+'_ROWS'] = rows
            values[prefix+'_ROWS_PRECEDING'] = rows-1
            values[prefix+'_MIN_PERIODS'] = max(3,rows//2)
    for prefix in ('MODE_DELAY','STARTUP_DELAY'):
        rows = max(1,math.ceil(values.get(prefix+'_MIN',0)*60/poll_seconds))
        values[prefix+'_ROWS'] = rows
        values[prefix+'_ROWS_PRECEDING'] = rows-1
    # OAT-METEO joins web weather as-of: bound = web cadence + margin (same as central's renderer).
    if 'WEB_CADENCE_SECONDS' in values and 'WEB_ASOF_MARGIN_SECONDS' in values:
        values['WEB_ASOF_BOUND_SECONDS'] = round(values['WEB_CADENCE_SECONDS'] + values['WEB_ASOF_MARGIN_SECONDS'])
    folder = ROOT / 'postgres' / 'rules'
    sql = (folder / rule['sql_file']).read_text(encoding='utf-8')
    if '{{ASSESSABLE_ROLES}}' in sql:
        sweep_roles = json.loads(SWEEP_ROLE_SOURCE.read_text(encoding='utf-8'))
        role_map = json.loads(ROLE_MAP_SOURCE.read_text(encoding='utf-8'))
        inverse = {name: role for role, name in role_map.items()}
        names = sweep_roles.get(rule['rule_id'])
        if not names:
            raise ValueError(f'No canonical assessable roles for {rule_id}')
        missing = [name for name in names if name not in inverse]
        if missing:
            raise ValueError(f'Canonical sweep roles missing SQL mappings for {rule_id}: {missing}')
        sql_roles = [inverse[name] for name in names]
        allowed = ', '.join("'" + role.replace("'", "''") + "'" for role in sql_roles)
        sql = sql.replace('{{ASSESSABLE_ROLES}}', allowed)
        # Per-role SI limits (range bands, spike deltas, flatline/stale tolerances, rate thresholds).
        # role_limits: a sweep_catalog.load_role_limits() result; default = open_fdd/data/sensor_sweep_limits.json.
        limits = role_limits if role_limits is not None else sweep_catalog.load_role_limits()
        for key, text in _sweep_fragments(rule, limits, inverse, set(names)).items():
            sql = sql.replace('{{' + key + '}}', text)
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
    args = p.parse_args()
    try:
        print(render(args.rule_id,args.poll_seconds,json.loads(args.params)))
    except (ValueError,TypeError) as exc:
        p.error(str(exc))
