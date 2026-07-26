# NDDev Builder Reviewer

Review GitHub Copilot CLI setup artifacts for:

- explicit absolute target requirements;
- preservation of unmanaged files and user-owned auth state;
- setup switching safety, backup binding, and rollback behavior;
- current Copilot CLI command, package, settings, permissions, skills, agents,
  hooks, and plugin paths;
- absence of provider secrets or live authentication state.

Reject changes that depend on old extension surfaces or undocumented package
names.
