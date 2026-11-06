import sys
from pathlib import Path

# make `import harness` and `import open_fdd` work however pytest is launched
HERE = Path(__file__).resolve().parent
for p in (str(HERE), str(HERE.parents[1])):
    if p not in sys.path:
        sys.path.insert(0, p)
