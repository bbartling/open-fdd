# Local auth (developers only)

The login form accepts **plaintext passwords only**. Do not paste values from `OFDD_*_PASSWORD_HASH=` lines in `workspace/auth.env.local` — those are bcrypt hashes for the bridge, not login passwords.

## First bootstrap

```bash
./scripts/openfdd_auth_init.sh --show-secrets --restart
```

Save the printed passwords (or `workspace/bootstrap_credentials.once.txt`), then delete the handoff file when done.

Passwords are **14 characters** (plaintext only). The lines in `auth.env.local` starting with `$2b$` are bcrypt hashes — never paste those into the login form.

## Forgot password / login fails after rotate

```bash
./scripts/openfdd_auth_init.sh --rotate --all --show-secrets --restart
```

The `--restart` flag recreates the bridge so it loads the new hashes.

## Verify login

```bash
./scripts/openfdd_auth_smoke.sh
./scripts/openfdd_inspection_build.sh --smoke
```

## Roles

| Role | Typical use |
|------|-------------|
| `integrator` | Full writes, validation, reports |
| `operator` | Day-to-day operations |
| `agent` | Read-only proposals |

Usernames default to the role name unless overridden in `auth.env.local`.
