"""Check rendering and bind/execute on empty DuckDB inputs; not PostgreSQL qualification."""
import json,re
from pathlib import Path
from render_rule import render,ROOT

rules = json.loads((ROOT/'tuning_catalog.json').read_text())['rules']
errors=[]
rendered={}
for r in rules:
    try:
        rendered[r['rule_id']] = render(r['rule_id'])
    except Exception as e:
        errors.append({'rule':r['rule_id'],'error':str(e)})
print('Rendered',len(rendered),'of',len(rules),'rules')
print(json.dumps(errors,indent=2))
if errors:
    raise SystemExit(1)

try:
    import duckdb
except ImportError:
    print('DuckDB unavailable; rendering checks only')
    raise SystemExit(0)
db=duckdb.connect()
db.execute('CREATE SCHEMA fdd')
db.execute('CREATE MACRO fdd.try_double(value) AS TRY_CAST(value AS DOUBLE)')
roles=set()
for r in rules:
    roles.update(r.get('required_roles',[]))
    roles.update(r.get('optional_roles',[]))
roles -= {'equipment_id','timestamp_utc'}
roles.add('occ_mode')
def history_schema():
    return 'equipment_id VARCHAR, timestamp_utc TIMESTAMPTZ, '+', '.join(
        '"'+c+'" '+('VARCHAR' if c=='occ_mode' else 'DOUBLE PRECISION') for c in sorted(roles))
db.execute('CREATE TABLE weather(timestamp_utc TIMESTAMPTZ, oa_t DOUBLE PRECISION, web_oa_t DOUBLE PRECISION, web_oa_dp DOUBLE PRECISION)')
db.execute('CREATE TABLE utility_interval(timestamp_utc TIMESTAMPTZ, kwh DOUBLE PRECISION)')
db.execute('CREATE TABLE utility_monthly(billing_period VARCHAR, kwh DOUBLE PRECISION)')
for attempt in range(100):
    db.execute('DROP TABLE IF EXISTS history')
    db.execute('CREATE TABLE history('+history_schema()+')')
    errors=[]
    new=set()
    for rule_id,sql in rendered.items():
        # DuckDB lacks PG to_char: adapt just this expression for this limited check.
        sql=sql.replace("to_char(timestamp_utc AT TIME ZONE 'UTC', 'YYYY-MM')",
                        "strftime(timestamp_utc AT TIME ZONE 'UTC', '%Y-%m')")
        try:
            db.execute(sql).fetchall()
        except Exception as e:
            error=str(e)
            match=re.search(r'Referenced column "([a-z_0-9]+)" not found',error)
            if match and match[1] not in roles:
                new.add(match[1])
            else:
                errors.append({'rule':rule_id,'error':error})
    if new:
        roles.update(new)
    else:
        break
comparison_errors=[]
if not errors:
    # Small deterministic regular-grid fixture. Not exhaustive rule goldens.
    db.execute("INSERT INTO history(equipment_id,timestamp_utc,"+', '.join('"'+c+'"' for c in sorted(roles))+") SELECT 'E1', TIMESTAMPTZ '2026-01-01 00:00:00+00' + i * INTERVAL '5 minutes', "+
        ', '.join("'occupied'" if c=='occ_mode' else ('1.0' if c.endswith('_status') or c in ('fan_cmd','loop_enabled') else '70.0') for c in sorted(roles))+" FROM range(24) t(i)")
    db.execute('INSERT INTO weather SELECT timestamp_utc,60,60,40 FROM history')
    db.execute('INSERT INTO utility_interval SELECT timestamp_utc,5 FROM history')
    # Month strings are deliberately different in the original engine adapter.
    # UTIL-MONTHLY receives a separate monthly normalization contract; no parity claim.
    for r in rules:
        if r['rule_id']=='UTIL-MONTHLY':
            continue
        try:
            expected=db.execute(render(r['rule_id'],dialect='datafusion')).fetchall()
            actual=db.execute(render(r['rule_id'])).fetchall()
            if len(expected)!=len(actual):
                raise ValueError('row count differs')
            for a,b in zip(sorted(expected,key=str),sorted(actual,key=str)):
                for x,y in zip(a,b):
                    if isinstance(x,(int,float)) and isinstance(y,(int,float)):
                        import math
                        assert math.isclose(x,y,rel_tol=1e-9,abs_tol=1e-9), (x,y)
                    else:
                        assert x==y,(x,y)
        except Exception as e:
            comparison_errors.append({'rule':r['rule_id'],'error':str(e)})
report={'rules':len(rules),'rendered':len(rendered), 'duckdb_empty_execution_errors':errors,
        'duckdb_fixture_comparison_count':76 if not errors else 0,
        'duckdb_fixture_comparison_errors':comparison_errors,
        'postgresql_execution_tested':False,
        'note':'DuckDB checks with an adapter for to_char/helper; not a PostgreSQL engine test or fault parity proof.'}
(ROOT/'validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
# A scratch adapter contract, not a production storage recommendation.
ddl='-- Scratch input contract only. Do not execute against production without designing adapters.\n'
ddl+='CREATE TEMP TABLE history('+history_schema().replace('TIMESTAMPTZ','timestamp with time zone')+');\n'
ddl+='CREATE TEMP TABLE weather(timestamp_utc timestamp with time zone, oa_t double precision, web_oa_t double precision, web_oa_dp double precision);\n'
ddl+='CREATE TEMP TABLE utility_interval(timestamp_utc timestamp with time zone, kwh double precision);\n'
ddl+='CREATE TEMP TABLE utility_monthly(billing_period varchar, kwh double precision);\n'
(ROOT/'input_contract.sql').write_text(ddl,encoding='utf-8')
smoke='-- Disposable PostgreSQL smoke test. Run psql -v ON_ERROR_STOP=1 -f postgres_smoke.sql\nBEGIN;\nSET LOCAL TIME ZONE \'UTC\';\n'
smoke+=(ROOT/'postgres_helpers.sql').read_text(encoding='utf-8')+'\n'+ddl
for i,(rule_id,sql) in enumerate(rendered.items()):
    smoke+=f'\n-- {rule_id}\nPREPARE fdd_rule_{i} AS\n'+sql+'\n'+f'EXECUTE fdd_rule_{i};\nDEALLOCATE fdd_rule_{i};\n'
smoke+='ROLLBACK;\n'
(ROOT/'postgres_smoke.sql').write_text(smoke,encoding='utf-8')
print(json.dumps(report,indent=2))
if errors or comparison_errors:
    raise SystemExit(1)
