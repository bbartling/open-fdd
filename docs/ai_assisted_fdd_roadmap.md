---
title: AI-Assisted FDD Roadmap
nav_order: 14
---

# AI-Assisted FDD: Roadmap & Agentic Workflows

**Future TODO:** State-of-the-art AI-assisted fault detection diagnostics, false positive tuning, and root cause analysis. This document architects how AI agents (like Cursor, Claude, GPT) can help mechanical engineers sift through **hundreds of fault events** and focus on what matters.

## The Problem: Too Many False Positives

open-fdd produces fault flags. A typical run yields:

| flag | events |
|------|--------|
| fc1_flag | 243 |
| fc2_flag | 79 |
| fc3_flag | 31 |
| fc4_flag | 44 |
| bad_sensor_flag | 138 |
| flatline_flag | 76 |
| **Total** | **611** |

**611 events** is too many for a human to review one-by-one. Many are false positives (startup, setpoint change, sensor noise). The mechanical engineer needs help:

1. **Prioritizing** — which events are likely real faults?
2. **Diagnosing** — what caused this fault?
3. **Tuning** — how do we reduce false positives without missing true faults?

---

## Data Format: What the AI Agent Sees

The event summary table is the primary input for AI-assisted workflows:

| flag | start | end | duration_samples |
|------|-------|-----|------------------|
| flatline_flag | 2025-01-01 06:00:00 | 2025-01-01 06:15:00 | 2 |
| fc4_flag | 2025-01-01 18:06:00 | 2025-01-01 21:00:00 | 13 |
| fc1_flag | 2025-01-02 06:30:00 | 2025-01-02 06:30:00 | 1 |
| fc3_flag | 2025-01-02 06:30:00 | 2025-01-02 06:30:00 | 1 |
| bad_sensor_flag | 2025-01-02 06:30:00 | 2025-01-02 06:30:00 | 1 |
| fc4_flag | 2025-01-02 14:15:00 | 2025-01-03 03:15:00 | 53 |
| bad_sensor_flag | 2025-01-03 01:30:00 | 2025-01-03 05:30:00 | 17 |
| ... | ... | ... | ... |
| flatline_flag | 2025-01-14 21:00:00 | 2025-01-15 06:15:00 | 38 |

**Key fields:**
- `flag` — fault type (fc1, fc2, flatline, bad_sensor, etc.)
- `start` / `end` — timestamp range of the event
- `duration_samples` — number of 15‑min intervals flagged (1 = single sample; 53 = ~13 hours)

**Additional context** the agent can request:
- Raw sensor values in the event window (SAT, MAT, OAT, duct static, fan speed, etc.)
- Rule definition (bounds, thresholds, expression)
- Equipment metadata (BRICK model, AHU name, zone)

---

## Architecture: AI Agent Workflows

### 1. **Batch Prioritization**

**Goal:** Rank events by likelihood of being a true fault.

**Input:** Event table (CSV/DataFrame) + optional sensor snapshots.

**Agent workflow:**
1. Load event table and rule metadata.
2. Apply heuristics: duration (longer = more likely real?), time-of-day (startup hours = more likely false?), co-occurrence (fc1 + fc3 + bad_sensor at same time = startup?).
3. Output: prioritized list with scores or tiers (High / Medium / Low / Likely False Positive).

**Best practice:** Provide the agent with a small labeled set (engineer marks 20–50 events as true/false) to calibrate heuristics.

### 2. **Per-Event Root Cause Analysis**

**Goal:** For a single event, explain *why* the rule fired.

**Input:** Event (flag, start, end) + sensor time series in that window.

**Agent workflow:**
1. Fetch sensor data for the event window.
2. Compare to rule logic: "fc1 fired because SA static pressure (0.05 inH₂O) was below setpoint (0.5 inH₂O) while fan was off (0%)."
3. Infer context: "Fan was off — likely unoccupied or startup. Check occupancy schedule."
4. Output: natural-language diagnosis + suggested action.

**Best practice:** Include rule YAML and column map so the agent can interpret signals correctly.

### 3. **Threshold Tuning Suggestions**

**Goal:** Suggest rule parameter changes to reduce false positives.

**Input:** Event table + labels (true/false) + current rule params.

**Agent workflow:**
1. Analyze false-positive patterns (e.g., "fc1 fires at 06:30 every day when fan starts").
2. Propose: "Add minimum fan speed filter: only flag when SF Spd Cmd > 10%."
3. Output: suggested YAML edits or new filter conditions.

**Best practice:** Version-control rule changes; A/B test on historical data before deploying.

### 4. **Interactive Review Loop**

**Goal:** Engineer reviews events with AI assistance in real time.

**Flow:**
1. Engineer opens event in notebook or dashboard.
2. Agent shows zoom plot + diagnosis.
3. Engineer marks: True fault / False positive / Unsure.
4. Agent learns from feedback; suggests similar events to batch-mark.

### 5. **Iterative Refinement: Rerun Until Data Looks Legit**

**Goal:** Mimic how a human weeds out false positives — keep rerunning fault detection, tuning rules, and reviewing until the results look credible.

**Flow:**
1. **Run** — Execute fault detection (RuleRunner) on data.
2. **Review** — Agent summarizes events (counts, patterns, sample diagnoses). LLM aids root cause analysis on a sample.
3. **Assess** — Engineer (or agent) asks: "Does this look legit?" — e.g., too many single-sample fc1 at 06:30? Obvious startup noise?
4. **Tune** — If not legit: agent suggests rule changes (filters, thresholds, occupancy). Engineer applies YAML edits.
5. **Rerun** — Go to step 1. Repeat until event set is plausible (e.g., false-positive rate acceptable, no obvious startup clusters).
6. **Converge** — Final run produces a "clean" event list for deeper RCA or work-order generation.

**LLM role:** At each iteration, the LLM diagnoses a sample of events, identifies patterns ("fc1 fires only when fan is off"), and proposes concrete YAML changes. The human approves or adjusts. This is the same loop a mechanical engineer would do manually — the agent accelerates it.

**Convergence criteria (examples):**
- Event count drops below a threshold (e.g., fewer than 50 high-priority events).
- No obvious false-positive clusters (e.g., daily 06:30 fc1).
- Engineer labels a sample; agent reports "X% of remaining events look like true faults."

---

## Is Jupyter/IPython Best for Agentic Workflows?

**Short answer:** Jupyter is a strong fit for *exploration and prototyping*; for production agentic workflows, consider a hybrid.

| Aspect | Jupyter/IPython | Alternative |
|--------|-----------------|-------------|
| **Exploration** | ✅ Excellent — run cells, inspect DataFrames, plot interactively | Scripts + CLI |
| **AI context** | ✅ Good — agent can read notebook, see outputs, suggest code | API + structured prompts |
| **Reproducibility** | ⚠️ Order-dependent; outputs can drift | Snakemake, Prefect, notebooks as reports |
| **Scale** | ⚠️ Manual "run all" — not ideal for 611 events × 10 sensors | Batch jobs, async workers |
| **Human-in-the-loop** | ✅ Good — engineer runs cells, marks events, iterates | Web UI (Streamlit, Dash) |

**Recommendation:**
- **Phase 1 (now):** Use Jupyter for exploration. Export event table to CSV/JSON. Feed that + sensor snapshots to AI (Cursor, Claude, GPT) via chat or API. Agent suggests code changes, engineer applies them in the notebook.
- **Phase 2:** Add a lightweight API or CLI that:
  - Accepts event IDs and returns agent-generated diagnoses.
  - Accepts engineer labels and updates a training set.
- **Phase 3:** Optional web UI for high-volume review (Streamlit/Dash) that calls the same agent logic.

**Why Jupyter still fits:** The agent needs to *see* the data. Notebooks are a natural format: code + outputs + plots. The agent can read the notebook, understand the schema, and suggest the next cell. Cursor-style AI that edits the notebook directly is a good fit.

---

## Next Steps for open-fdd

### Near-term (TODO)

1. **Export event table to CSV/JSON** — One-click export from the notebook for AI consumption.
2. **Event API** — `get_event_sensors(event_id, result)` returns a small DataFrame for the event window.
3. **Prompt templates** — Ready-made prompts for "diagnose this event" and "prioritize these events."
4. **Label schema** — Standard format for engineer feedback (event_id, label: true_fault | false_positive | unsure, notes).
5. **Iterative refinement loop** — Script or notebook pattern: run → review (LLM sample RCA) → tune rules → rerun until data looks legit.

### Medium-term

5. **Agent skill / rule** — Cursor rule or skill that teaches the AI open-fdd data model and event format.
6. **Batch diagnosis script** — CLI: `python -m open_fdd.diagnose events.csv --output diagnoses.json`.
7. **Threshold tuning helper** — Agent suggests YAML edits; script validates and applies.

### Long-term

8. **Fine-tuned classifier** — Train on labeled events to predict true/false; use for prioritization.
9. **Root cause taxonomy** — Standard categories (startup, sensor fault, setpoint, mechanical) for structured RCA.
10. **Integration with BAS/CMMS** — Push confirmed faults to work orders; close loop with maintenance.

---

## Example: Agent Prompt for Single-Event Diagnosis

```
You are assisting a mechanical engineer with HVAC fault diagnosis.

Event:
- flag: fc1_flag
- start: 2025-01-02 06:30:00
- end: 2025-01-02 06:30:00
- duration_samples: 1

Sensor snapshot (15-min interval):
- SA Static Press: 0.05 inH₂O
- SA Static Press Sp: 0.50 inH₂O
- SF Spd Cmd: 0%
- SAT: 72°F, MAT: 68°F, OAT: 45°F

Rule: fc1 = duct static below setpoint when fan should be running.

Provide:
1. Why did the rule fire? (1–2 sentences)
2. Is this likely a true fault or false positive? Why?
3. Suggested next step for the engineer.
```

**Expected agent output:**
> 1. The rule fired because SA static pressure (0.05 inH₂O) was below setpoint (0.50 inH₂O). The fan was at 0% — it was off.
> 2. Likely **false positive**. The fan was off (unoccupied or before startup). Duct static is expected to be low when the fan is off.
> 3. Add a filter: only flag fc1 when fan speed > 10%. Or check occupancy schedule — suppress fc1 during unoccupied hours.

---

## Links

- **[Fault Visualization]({{ "fault_visualization" | relative_url }})** — Zoom on events, event table, analytics
- **[Getting Started]({{ "getting_started" | relative_url }})** — Install and run
- **[Configuration]({{ "configuration" | relative_url }})** — Rule types, YAML structure
- **[API Reference]({{ "api_reference" | relative_url }})** — `get_fault_events`, `zoom_on_event`, reports
