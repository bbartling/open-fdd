"""Machine-learning FDD benchmark and detectors (optional extra ``open-fdd[ml]``).

Nothing here is imported by the core package. The modules need pandas and numpy; the one-class
detectors need scikit-learn; COPOD needs ``pyod`` (skipped when it is not installed).

- :mod:`open_fdd.ml.lbnl` downloads a small subset of the public LBNL FDD data library (CC BY 4.0)
  into a cache directory and maps it to Open-FDD roles in SI.
- :mod:`open_fdd.ml.detectors` holds the detectors: PCA + SPE with contributions, gray-box residuals,
  mode-gated one-class models, and an adapter over the existing z-score / MAD detectors.
- :mod:`open_fdd.ml.baseline` runs the existing pandas rule pack as the baseline.
- :mod:`open_fdd.ml.metrics` scores sample flags against labels (TPR, FPR, detection delay).
- :mod:`open_fdd.ml.benchmark` ties them together and writes the results table.
- :mod:`open_fdd.ml.cli` is the ``open-fdd-ml`` command.
"""

from __future__ import annotations

__all__ = ["baseline", "benchmark", "detectors", "lbnl", "metrics"]
