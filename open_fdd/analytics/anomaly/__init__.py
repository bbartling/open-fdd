"""Offline AHU IO anomaly screening (history_wide + column_map).

SQL-portable detectors (rolling Z-score, rolling MAD) live in ``detectors`` and
use only pandas/numpy. STL and Isolation Forest live in ``detectors_ml`` and
need the ``anomaly`` extra (``statsmodels``, ``scikit-learn``).
"""

from open_fdd.analytics.anomaly.screen import screen_folder

__all__ = ["screen_folder"]
