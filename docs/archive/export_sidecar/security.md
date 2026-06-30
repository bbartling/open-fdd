# CSV export sidecar — security

- Token file or secret required; do not embed credentials in cron lines checked into git.
- Exports stay under the configured output directory.
- Filename templates must not contain `..` or absolute paths.
- Rules export requires integrator/agent role when enabled.
