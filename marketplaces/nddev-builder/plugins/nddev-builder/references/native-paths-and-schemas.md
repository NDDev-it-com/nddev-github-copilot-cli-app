# GitHub Copilot CLI Native Paths And Schemas

Use this as a concise native-surface map for this public builder toolkit. For
volatile release pins, supported profile lists, launch flags, and command
enumerations, read the module code and contract files instead of copying
values here.

## Configuration Directory

`COPILOT_HOME` overrides the default user configuration directory. In this
module, every manager operation requires an explicit target and binds
`COPILOT_HOME` to that target for child Copilot CLI processes.

Important user-level paths under `COPILOT_HOME`:

- `settings.json`: JSONC settings. This module writes deterministic JSON.
- `permissions-config.json`: saved tool and directory permissions.
- `copilot-instructions.md`: personal instructions.
- `instructions/*.instructions.md`: modular personal instructions.
- `mcp-config.json`: user-level MCP server definitions.
- `agents/*.agent.md`: personal custom agents.
- `skills/<name>/SKILL.md`: personal skills.
- `hooks/*.json`: user-level hook files.
- `installed-plugins/<marketplace>/<plugin>/`: marketplace-installed plugin
  cache. Manage it with native plugin commands, not manual copying.
- `plugin-data/`: plugin-owned persistent data.
- `session-store.db` and `session-state/`: runtime-owned session and memory
  state. Do not model these as public module memory settings.

## Settings And Permissions

Relevant documented settings include `askUser`, `autoUpdate`,
`autoUpdatesChannel`, `remote`, `remoteExport`, `sandbox.enabled`,
`sandbox.allowBypass`, `sandbox.gitAuth`, `sandbox.ghAuth`,
`sandbox.userPolicy.network.allowLocalNetwork`,
`sandbox.userPolicy.seatbelt.keychainAccess`, `storeTokenPlaintext`,
`stayInAutopilot`, `toolSearch`, `disabledSkills`, `enabledPlugins`,
`extraKnownMarketplaces`, `keepAlive`, and
`permissions.disableBypassPermissionsMode`.

The documented permission kind `memory` controls storage of new facts. There is
no documented boolean memory settings toggle for this module to write.

## Agents

Agent files are Markdown files ending in `.agent.md` or `.md`. Required
frontmatter: `description`. Supported frontmatter includes `infer`,
`mcp-servers`, `model`, `name`, and `tools`.

Project agents live under `.github/agents/` or `.claude/agents/`. User agents
live under `COPILOT_HOME/agents/`. Plugin agents live under the plugin's
`agents/` directory unless overridden by `plugin.json`.

## Skills

Each skill lives in a directory with `SKILL.md`. Required frontmatter:
`name` and `description`. Optional frontmatter includes `argument-hint`,
`allowed-tools`, `user-invocable`, and `disable-model-invocation`.

Project skill directories include `.github/skills/`, `.agents/skills/`, and
`.claude/skills/`. User skill directories include `COPILOT_HOME/skills/` and
`~/.agents/skills/`. Plugin skills live under the plugin's `skills/` directory
unless overridden by `plugin.json`.

## Plugins And Marketplace

A plugin directory must contain `plugin.json` at its root. This module uses the
documented component fields `agents`, `skills`, `hooks`, and `mcpServers`.

A marketplace can be a local directory with a manifest at
`.github/plugin/marketplace.json`. Plugin entries include `name` and `source`;
metadata fields such as `description`, `version`, `author`, `license`,
`keywords`, `category`, `tags`, and `strict` are supported on marketplace
entries.

Native local install flow:

```bash
copilot plugin marketplace add /absolute/path/to/marketplace
copilot plugin install plugin-name@marketplace-name
```

## Hooks

Hook files use JSON with:

```json
{
  "version": 1,
  "hooks": {
    "eventName": [
      {
        "type": "command",
        "command": "..."
      }
    ]
  }
}
```

Hook sources include policy files, repository `.github/hooks/*.json`, user
`COPILOT_HOME/hooks/*.json`, inline `hooks` blocks in settings, and plugin
`hooks.json` or `hooks/hooks.json`.

## MCP

User MCP configuration uses `COPILOT_HOME/mcp-config.json`. Workspace MCP uses
`.mcp.json` or `.github/mcp.json`. Plugin MCP uses `.mcp.json` or
`.github/mcp.json` inside the plugin. The top-level shape is:

```json
{
  "mcpServers": {}
}
```

Built-in MCP servers, external registry installation, OAuth, and enterprise
allowlists are native Copilot CLI concerns. This public module does not add
undocumented MCP install flows.

## Official Documentation

- https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference
- https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-config-dir-reference
- https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-plugin-reference
- https://docs.github.com/en/copilot/reference/hooks-reference
