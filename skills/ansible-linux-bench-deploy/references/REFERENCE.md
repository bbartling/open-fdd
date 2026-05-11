# Ansible bench — reference

Paths: `infra/ansible/site.yml`, `ansible.cfg`, `group_vars/bench.yml`, roles under `infra/ansible/roles/`.

Ports: bridge 8765, MCP 8090, UI 5173, easy-aso 18090, diy-bacnet 8080.

Secrets placeholders: `ofdd_mcp_ofdd_api_key`, `supervisor_api_key`, `bacnet_rpc_api_key` — use vault in production.
