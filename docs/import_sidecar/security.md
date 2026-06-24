# CSV import sidecar — security

- Use `OPENFDD_IMPORT_SIDECAR_AUTH_TOKEN_FILE` or Docker secrets — never commit tokens.
- Logs redact `Authorization` headers.
- Reject symlinks and path traversal in filenames.
- Limit file size with `OPENFDD_IMPORT_SIDECAR_MAX_FILE_MB`.
- Grant **integrator/agent** (or future `import_service`) only — not BACnet write privileges.
