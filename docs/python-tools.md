---
title: Python tools
nav_order: 16
---

# Python tools

Install the PyPI package with the extras needed for your task:

```bash
pip install open-fdd[nf]          # NF client, pandas frames, reference rules
pip install open-fdd[reporting]   # reports
pip install open-fdd[rdf]         # Turtle reader
```

The Python package version is separate from the NF app version. Use `open-fdd-version --pretty` to inspect the
available version information.

## Read NF data

The NF client supports LAN console/API access and the Normal Online portal. Set the required URL and API credentials
in environment variables or a protected env file, then use read commands:

```bash
open-fdd-nf info
open-fdd-nf model
open-fdd-nf rules --days 7
```

The tools read NF and do not write to it. The portal key is read-only. See the
[API reference](fdd-data-access.html) for the underlying routes.

## Python API

```python
from datetime import datetime, timedelta, timezone
from open_fdd.nf import NFClient, load_model, equipment_frames
from open_fdd.rules import run_all

client = NFClient.from_env(via="lan")
model = load_model(client)
end = datetime.now(timezone.utc)
frames = equipment_frames(client, model, end - timedelta(days=7), end)
results = run_all(next(iter(frames.values())))
```

Frames contain SI values mapped to Haystack roles. The pandas rules are reference implementations. The production
engine is SQL. See [Writing pandas rules](pandas-rules.html) and [parity](rules/parity.html).

The package also provides ECM workbooks, reports, anomaly screening, and RDF readers. Use the CLI help for command
options. Source and installation extras are in the repository's pyproject.toml.
