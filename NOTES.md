## Mega nuke prune

### 1) Stop everything

```bash
docker ps -aq | xargs -r docker stop
```

### 2) Remove all containers

```bash
docker ps -aq | xargs -r docker rm -f
```

### 3) Remove all images

```bash
docker images -aq | xargs -r docker rmi -f
```

### 4) Remove all volumes (THIS deletes DB data)

```bash
docker volume ls -q | xargs -r docker volume rm -f
```

### 5) Remove all custom networks

```bash
docker network ls --format '{{.Name}}' | grep -vE '^(bridge|host|none)$' | xargs -r docker network rm
```

### 6) Final system prune (build cache, leftovers)

```bash
docker system prune -a --volumes -f
docker builder prune -a -f
```


## Notes for FDD ideas for the future not to use a Bool flag for a fault based on a white paper

4) Store energy impact in a structured way

Add:

fault_energy_impact(fault_id, metric, low, typical, high, unit, notes, confidence)

Even if early values are coarse, it enables:

ranking + triage

“savings potential” dashboards

5) Test vectors + validation harness (this is huge)

In DB and/or RDF, store:

fault_test_vectors(fault_id, name, input_payload jsonb, expected_output jsonb)

Then build a small runner in your CI:

load vectors

run the fault rule engine

assert outputs

This is how you ensure “no rock left unturned” as your catalog grows.


## Verify weather scrape from open metio

```bash
docker exec -it openfdd_timescale psql -U postgres -d openfdd -c \
"SELECT *
 FROM weather_hourly_raw
 ORDER BY ts DESC
 LIMIT 50;"
```


```bash
 docker exec -it openfdd_timescale psql -U postgres -d openfdd -c \
"SELECT tr.ts, p.external_id, tr.value
 FROM timeseries_readings tr
 JOIN points p ON p.id = tr.point_id
 ORDER BY tr.ts DESC
 LIMIT 50;"
```


## Check Faults Manually From Docker

### Check the FDD Engine Logs


```bash
docker exec -it openfdd_timescale psql -U postgres -d openfdd -c "SELECT run_ts, status, sites_processed, faults_written, error_message FROM fdd_run_log ORDER BY run_ts DESC LIMIT 10;"
```

```bash
$ docker exec -it openfdd_timescale psql -U postgres -d openfdd -c "SELECT fr.ts AS time, fd.name AS fault_name, fr.flag_value AS active FROM fault_results fr JOIN fault_definitions fd ON fd.fault_id = fr.fault_id WHERE fr.site_id = 'TestBenchSite' ORDER BY fr.ts DESC LIMIT 20;"
```

```bash
docker exec -it openfdd_timescale psql -U postgres -d openfdd -c "SELECT external_id AS raw_point_name, fdd_input AS mapped_role, brick_type, equipment_id FROM points WHERE fdd_input IS NOT NULL OR brick_type IS NOT NULL LIMIT 20;"
```