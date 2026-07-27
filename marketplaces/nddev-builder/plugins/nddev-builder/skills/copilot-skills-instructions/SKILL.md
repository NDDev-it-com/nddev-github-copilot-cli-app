---
name: copilot-skills-instructions
description: Create or review GitHub Copilot CLI Agent Skills, personal instructions, and modular instructions for the NDDev builder plugin.
---

# Copilot Skills And Instructions

Use this skill for `SKILL.md`, `copilot-instructions.md`, and
`*.instructions.md` work.

## Native Surface

Skills are directories containing `SKILL.md` with required `name` and
`description` frontmatter. Personal instructions live at
`COPILOT_HOME/copilot-instructions.md`; modular personal instructions live
under `COPILOT_HOME/instructions/` as `*.instructions.md` files. Discovery
locations and priority are summarized in
[`../../references/native-paths-and-schemas.md`](../../references/native-paths-and-schemas.md).

## Skill Design

- Keep the entry skill small and route to focused skills.
- Put detail in one-hop `references/` files.
- Validate every relative markdown link.
- Point to code-owned contracts for volatile versions, pins, launch flags,
  profile lists, and managed path enumerations.
- Keep repository artifacts in English.

## Validation Workflow

Run `python3 cli-tools/validate_public_contracts.py`; it validates routed
builder skills, references, and relative links. Run `list --json` to verify the
managed setup/profile catalog remains low entropy.
