---
title: Machine Learning for FDD — Ideas & Roadmap
nav_order: 20
---

# Machine Learning for FDD: Ideas & Roadmap

This document outlines possible machine learning (ML) enhancements for open-fdd. These are **ideas only** — not yet implemented. The goal is to complement rule-based FDD with data-driven methods.

---

## Why ML alongside rules?

- **Rules** — Interpretable, based on physics and heuristics. Good for known fault types.
- **ML** — Can learn patterns from data, handle novel faults, and reduce false positives by learning "normal" vs "fault" from historical runs.

Hybrid approaches (rules + ML) are common in building FDD research.

---

## Idea 1: Anomaly detection on rule outputs

**Concept:** Run rule-based FDD, then use an anomaly detector on the resulting flag patterns (e.g. event counts, durations, co-occurrence) to flag *unusual* rule behavior.

**Example:**  
- Rules produce `fc1_flag`, `fc2_flag`, etc. per timestamp.  
- Aggregate to hourly/daily counts per flag.  
- Train Isolation Forest or One-Class SVM on "normal" periods.  
- Flag when the pattern deviates.

**Use case:** Detect novel fault combinations or rule interactions that no single rule catches.

---

## Idea 2: Learned threshold tuning

**Concept:** Rules use thresholds (e.g. `static_err_thres`, `mix_err_thres`). ML can learn site-specific thresholds from labeled or semi-labeled data.

**Example:**  
- Collect (timestamp, sensor values, expert label: fault/not fault).  
- Use grid search or Bayesian optimization to find thresholds that maximize F1 or minimize false positives.  
- Update rule params per site.

**Use case:** Reduce false positives when generic thresholds don't fit a particular building.

---

## Idea 3: Sequence models for fault prediction

**Concept:** Use LSTM or Transformer on time-series to predict the *next* fault or to classify sequences as "leading to fault" vs "normal."

**Example:**  
- Input: Rolling window of SAT, MAT, OAT, valve positions, etc.  
- Output: probability of fault in next N steps, or fault type.  
- Train on historical FDD results (rule flags as labels).

**Use case:** Early warning before a fault fully manifests.

---

## Idea 4: Transfer learning from simulation

**Concept:** Train ML models in simulation (e.g. EnergyPlus, Modelica) where faults are injected, then fine-tune on real building data.

**Example:**  
- Generate synthetic fault scenarios in simulation.  
- Train a classifier or autoencoder.  
- Fine-tune on small amounts of real data.

**Use case:** Mitigate lack of labeled fault data in real buildings.

---

## Idea 5: Clustering for fault grouping

**Concept:** Cluster fault events by sensor patterns (e.g. k-means, DBSCAN). Similar clusters may share root cause.

**Example:**  
- Extract features from each fault event (mean sensor values, duration, co-occurring flags).  
- Cluster.  
- Label clusters via domain expert or majority rule.

**Use case:** Discover fault subtypes and prioritize investigation.

---

## Idea 6: Autoencoder for reconstruction error

**Concept:** Train autoencoder on "normal" data. High reconstruction error indicates anomaly (potential fault).

**Example:**  
- Input: Vector of sensor values per timestep.  
- Train on fault-free periods (or low-fault periods).  
- Flag when reconstruction error exceeds threshold.

**Use case:** Detect faults without explicit rule definitions.

---

## Implementation sketch (optional)

If pursuing ML integration, a possible structure:

```
open_fdd/
  ml/
    __init__.py
    anomaly.py      # Isolation Forest, One-Class SVM
    threshold_tune.py  # Bayesian / grid search for params
    sequence.py     # LSTM / simple RNN for sequence classification
    clustering.py   # Cluster fault events
```

Dependencies would be optional (e.g. `scikit-learn`, `torch` or `tensorflow` in extras).

---

## References & further reading

- ASHRAE Guideline 36, RP-1312
- Research on hybrid rule+ML FDD for HVAC
- Time-series anomaly detection surveys

---

**Status:** Ideas only. No ML code in open-fdd core yet. Contributions welcome.
