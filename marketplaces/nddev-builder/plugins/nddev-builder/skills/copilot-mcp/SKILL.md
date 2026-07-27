---
name: copilot-mcp
description: Create or review GitHub Copilot CLI MCP configuration for the NDDev setup module and builder plugin without adding unproven servers or leaking secrets.
---

# Copilot MCP

Use this skill for `mcp-config.json`, `.mcp.json`, MCP server allow/deny
policy, and launch-time MCP posture.

## Native Surface

User-level MCP config uses `COPILOT_HOME/mcp-config.json`. Workspace MCP uses
`.mcp.json` or `.github/mcp.json`. Plugin MCP uses `.mcp.json` or
`.github/mcp.json` in the plugin. The top-level schema is an object with
`mcpServers`.

Discovery order and trust notes are summarized in
[`../../references/native-paths-and-schemas.md`](../../references/native-paths-and-schemas.md).

## Builder Practice

- Keep this public module's default MCP maps empty unless a server has a
  documented install and auth boundary.
- Do not store secrets in MCP config. Use native secret flows when they are
  explicitly documented and tested in isolation.
- Full-auto enables documented GitHub MCP tool availability through the
  code-owned launch bundle. Do not copy the flag list into skill text.

## Validation Workflow

Run `python3 cli-tools/validate_public_contracts.py` and inspect the generated
target `mcp-config.json` in an isolated target if MCP defaults change.
