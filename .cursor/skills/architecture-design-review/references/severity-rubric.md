# Review severity rubric

- `blocker`: Must be fixed before merge/release. Evidence suggests likely production breakage, security exposure, data loss/corruption, compliance failure, or irreversible migration risk.
- `high`: Should be fixed soon. Evidence suggests likely user impact, correctness gap, serious test gap, high operational cost, or meaningful security/reliability risk.
- `medium`: Important but not immediately blocking. Evidence suggests maintainability risk, incomplete coverage, edge-case bug, compatibility issue, or moderate operational concern.
- `low`: Useful improvement with narrow or low impact.
- `info`: Context, observation, or non-actionable note.

A finding without evidence should be downgraded to an unknown or follow-up question, not reported as a defect.
