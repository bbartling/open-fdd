# Grok Bot — local Soft-OPEN handoff (Cursor → live stress)

After a Cursor Soft-OPEN patch train merges and GHCR publishes, Grok owns **live**
qualification (Railway, ACME, MEGA, ZAP AF). Cursor writes the mega prompt; this
doc is how Ben kicks Grok Bot on the bench without retyping.

## Flow

1. Cursor finishes S0–S14 and writes the filled prompt to the agent store:
   `docs/grok-stress-prompt-sha-<7>.md` (see plan S14 appendix).
2. Confirm GHCR pin with `./scripts/ghcr_newest_by_created.py openfdd-central openfdd-web openfdd-mqtt openfdd-fieldbus` — use **newest-by-OCI-created** `sha-<7>`, not tag-name sort on `:nightly`.
3. Stage the prompt for Grok Bot:

```bash
python3 ./scripts/ops/kickoff_grok_bot.py /path/to/docs/grok-stress-prompt-sha-<7>.md
```

4. Grok Bot opens via `grokbot://app/v1/open`; the prompt is on the **GTK clipboard**. Paste with **Ctrl+V**, then **Enter** (or use `--send` when `xdotool` is available and the Grok window is focused).

## Smoke (plumbing only)

Does not run stress or touch Railway:

```bash
./scripts/ops/test_kickoff_grok_bot.sh
```

Expect `GROK_KICKOFF_OK` if Grok Bot is installed and clipboard works.

## Notes

- No secrets in the prompt file; lab credentials stay in env / Railway CLI.
- Grok Bot has no documented API to inject chat text — clipboard + deep link is intentional.
- Product FDD/RCx plots stay SQL + roles + `equipType`; Haystack RDF/SPARQL is the export track only (see `openfdd_agent_spec/AGENTS.md`).
