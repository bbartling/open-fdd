# Issue drafts (lab)

These Markdown files were carried over from the **open-fdd-automated-testing** repo as **draft** issue text and parity notes. They are not published on GitHub Pages.

Promote content into real GitHub issues or into [`docs/`](../../docs/) when a finding is still accurate and should be canonical.

## Product-defect draft gate (required)

Before opening a GitHub issue from this folder, include:
- exact failing query file name and query text (or committed path + SHA)
- expected vs actual (row counts + sample binding diff)
- UTC timestamps and log file path
- auth preflight state from the same run (`healthy` or classified drift)
- bench context: API URL, frontend URL, branch/commit, active BACnet/weather loops

If auth preflight is not healthy, classify as harness/runtime drift first and do not file as a product defect yet.
