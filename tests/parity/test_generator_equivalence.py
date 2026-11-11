"""The Python generator (open_fdd.parity.dataset, profile "basic", seed 0) reproduces the JS generator exactly.

nf-app/hooks/lib/synthetic_dataset.js is what the parity data was born from; the known-difference sets are only valid
for that data, so any drift between the two generators must fail loudly here.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from open_fdd.parity import generate

ROOT = Path(__file__).resolve().parents[2]

JS = """
const { buildDataset } = require(process.argv[1] + '/nf-app/hooks/lib/synthetic_dataset.js');
const pack = require(process.argv[1] + '/nf-app/rules/pack-postgres.json');
const opts = JSON.parse(process.argv[2]);
process.stdout.write(JSON.stringify(buildDataset(pack, opts)));
"""

CASES = [
    dict(equipments=2, days=3, gaps=False, duplicateRole=False, plantSensors=False),   # the pytest dataset
    dict(equipments=3, days=2, gaps=True, duplicateRole=True, plantSensors=True),      # every option on
    dict(equipments=8, days=7, gaps=False, duplicateRole=False, plantSensors=False),   # the stress dataset
]


def _js(opts):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required")
    out = subprocess.run([node, "-e", JS, str(ROOT).replace("\\", "/"), json.dumps({**opts, "stepSeconds": 300})],
                         capture_output=True, check=True, cwd=ROOT).stdout
    return json.loads(out.decode("utf-8"))


@pytest.mark.parametrize("opts", CASES, ids=lambda o: f"{o['equipments']}x{o['days']}")
def test_python_generator_equals_js_generator(opts):
    js = _js(opts)
    py = generate(0, opts["equipments"], opts["days"], "basic", gaps=opts["gaps"], duplicate_role=opts["duplicateRole"],
                  plant_sensors=opts["plantSensors"]).to_engine_input()
    assert set(js) == set(py)
    for key in js:
        a, b = js[key], py[key]
        assert len(a) == len(b), (key, len(a), len(b))
        # exact equality of every value (1 == 1.0 is fine: JSON has one number type)
        for k, (x, y) in enumerate(zip(a, b)):
            assert x == y, (key, k, {c: (x.get(c), y.get(c)) for c in x if x.get(c) != y.get(c)} if isinstance(x, dict) else (x, y))
