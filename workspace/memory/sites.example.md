# Site memory (example)

- Edge: no local MCP (`enable_mcp: false`)
- **BACnet poll:** FDD-minimal only (~76 points for current Acme rules). Never bulk-enable all discovered objects.
- Commission script: `infra/ansible/scripts/acme_commission_fdd_minimal.sh`
