# Installing `open-fdd-lab` skill for OpenClaw

Canonical skill file: **`openclaw/SKILL.md`** (this tree). If you are migrating from the old **open-fdd-automated-testing** repo, read **`legacy_automated_testing.md`** first so paths and expectations stay aligned.

OpenClaw resolves skills from:

- `workspace/skills/<skill-name>/SKILL.md`, and
- optional **`skills.load.extraDirs`** in `~/.openclaw/openclaw.json` (behavior depends on OpenClaw version).

## Option A — symlink into workspace skills

From the machine that hosts `~/.openclaw/workspace`:

```bash
mkdir -p ~/.openclaw/workspace/skills
ln -sfn /path/to/open-fdd/openclaw ~/.openclaw/workspace/skills/open-fdd-lab
```

Ensure `SKILL.md` is readable at `.../skills/open-fdd-lab/SKILL.md`. If the symlink points at `openclaw/`, that works because `SKILL.md` lives at the root of `openclaw/`.

## Option B — copy

Copy the whole `open-fdd/openclaw/` directory into `skills/open-fdd-lab/` (heavy if you duplicate `bench/`); prefer symlink or a thin copy of `SKILL.md` + `references/` only.

## Verify

```bash
openclaw doctor
# or
openclaw skills list
```

Fix path warnings per CLI output.

## GitHub

Skill source of truth is tracked under **https://github.com/bbartling/open-fdd** in `openclaw/`. Pull before long lab sessions.
