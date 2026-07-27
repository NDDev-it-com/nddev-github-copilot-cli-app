---
name: copilot-agents-subagents
description: Create or review GitHub Copilot CLI custom agent and subagent artifacts for the NDDev builder plugin and setup module.
---

# Copilot Agents And Subagents

Use this skill for `.agent.md` files, built-in subagent policy, and delegation
contracts.

## Native Surface

Custom agent files use Markdown with YAML frontmatter and `.agent.md` or `.md`
extension. Supported frontmatter includes `description`, `infer`,
`mcp-servers`, `model`, `name`, and `tools`. Discovery locations and priority
are summarized in
[`../../references/native-paths-and-schemas.md`](../../references/native-paths-and-schemas.md).

## Builder Practice

- Keep each custom agent role narrow and review-oriented.
- Use `tools: ["*"]` only when the outer permission profile and launcher
  already own the safety posture.
- Avoid hardcoded model names unless the user explicitly requests model
  selection and the module contract is updated to own it.
- Do not rely on Windows-only paths or shell behavior.

## Validation Workflow

Validate frontmatter and markdown links with
`python3 cli-tools/validate_public_contracts.py`. The manager also validates
plugin agent files before native builder installation.
