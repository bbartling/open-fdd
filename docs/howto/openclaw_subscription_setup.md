---
title: OpenClaw subscription setup (Codex OAuth)
parent: How-to guides
nav_order: 16
---

# OpenClaw setup: ChatGPT subscription / Codex OAuth (not API key)

This note captures a setup path that worked for using **OpenClaw with the OpenAI Codex OAuth / ChatGPT subscription path** instead of the plain OpenAI API-key provider.

## Why this matters

A normal ChatGPT subscription and a normal OpenAI API key are **not** the same thing.

That means OpenClaw can appear partly configured, but still fail with errors like:

```text
401 Incorrect API key provided: sk-proj-...
```

if stale `openai/...` API-key settings are still present.

## The key distinction

In OpenClaw, these are separate provider paths:

- **Subscription / OAuth path:** `openai-codex/...`
- **API-key path:** `openai/...`

For the subscription/OAuth setup, the model should look like:

```text
openai-codex/gpt-5.4
```

Not:

```text
openai/gpt-5.4
openai/gpt-5.1-codex
```

## First commands to run

Use this basic command ladder first:

```powershell
openclaw status
openclaw models status --probe
openclaw config get agents.defaults.model
openclaw config get agents.defaults.models
```

What you want to see is the default model set to something like:

```json
{
  "primary": "openai-codex/gpt-5.4"
}
```

## If OpenClaw is still trying to use the API-key provider

If you still see `openai/...` models or a 401 against `sk-proj-...`, the most likely cause is stale config.

## What worked

### 1. Re-auth the OAuth provider

```powershell
openclaw models auth login --provider openai-codex
```

That should complete the browser-based OAuth flow for the subscription path.

### 2. Make sure the default model points to `openai-codex/...`

```powershell
openclaw models set openai-codex/gpt-5.4
```

### 3. Clean `openclaw.json`

The important cleanup is to remove all stale `openai/...` references and keep only `openai-codex/...`.

A working pattern looked like this:

```json
{
  "auth": {
    "profiles": {
      "openai-codex:default": {
        "provider": "openai-codex",
        "mode": "oauth"
      }
    }
  },
  "agents": {
    "defaults": {
      "model": {
        "primary": "openai-codex/gpt-5.4"
      },
      "models": {
        "openai-codex/gpt-5.4": {}
      }
    },
    "list": [
      {
        "id": "main",
        "model": "openai-codex/gpt-5.4"
      }
    ]
  }
}
```

### 4. Remove stale API-key provider entries

Problematic leftovers included things like:

- `openai:default`
- `openai/gpt-5.1-codex`
- aliases like `GPT -> openai/gpt-5.1-codex`
- per-agent model overrides pinned to `openai/...`

Those kept the old API-key path alive even though OAuth was configured.

### 5. Check the agent auth file too

Also inspect:

```powershell
notepad $HOME\.openclaw\agents\main\agent\auth-profiles.json
```

If that file still contains a stale `"openai:default"`, remove it and keep only `"openai-codex:default"`.

### 6. Restart the gateway

```powershell
openclaw gateway stop
openclaw gateway
```

### 7. Verify again

```powershell
openclaw models status --probe
```

What you want to see:

- default = `openai-codex/gpt-5.4`
- no `openai:default (api_key)`
- no `openai/gpt-5.1-codex` in configured models
- healthy `openai-codex:default (oauth)`

## One more gotcha: old sessions

Even after config is corrected, an older session/thread can still behave like it is using the old provider.

So after restarting:

```powershell
openclaw dashboard
```

start a **fresh** chat thread and ask:

```text
Tell me exactly which provider and model you are using right now.
```

You want the answer to be:

```text
openai-codex/gpt-5.4
```

## Practical summary

The OAuth login can work **and** the system can still fail if stale `openai/...` API-key config remains in:

- `openclaw.json`
- `agents.list[].model`
- `agents.defaults.models`
- `auth.profiles`
- `agents/main/agent/auth-profiles.json`

The successful fix was:

1. keep only `openai-codex/...`
2. remove stale `openai/...` references
3. restart the gateway
4. test from a fresh session

## Operational context to save for future setups

When OpenClaw is used with Open-FDD in the field, the agent should expect to ask for and record at least:

- the **Open-FDD base URL** the system is running at
- the **OFDD API key / Bearer token** if API auth is enabled
- whether the Open-FDD host is a **Linux box on the OT LAN** (this is the likely default deployment shape)

Those values should be treated as setup context, not tribal knowledge. They should be written into durable repo notes when appropriate, with secrets handled carefully.

## Why this doc exists

This was learned through actual setup/debugging and should not live only in chat history. It is the kind of practical onboarding/context that future humans and agents will need again.
