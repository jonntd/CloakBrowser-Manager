# Agent Instructions

This project uses **bd** (beads) for issue tracking. Run `bd onboard` to get started.

## Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --status in_progress  # Claim work
bd close <id>         # Complete work
bd sync               # Sync with git
```

## Deliverable = installed app (not just a build)

After changing Rust or frontend code, do NOT stop at "bundle built". The user
runs the packaged app from /Applications, so close the loop in one step:

```bash
cd frontend && npm run app:install   # build + quit running app + ditto-replace /Applications/CloakAccounts.app + relaunch + verify
cd frontend && npm run app:reinstall # same, but reuse the last built bundle (no recompile)
```

## Compatibility guardrails

- Adding a field to the `Account` struct (`src-tauri/src/models.rs`): it needs
  `#[serde(default)]`, or old `~/.cloak-accounts/accounts.json` files fail to
  parse and the app panics on startup (it refuses to boot on an unreadable store).
- Adding an updatable account field: also add it to the allow-list in
  `mcp-server/cloak_accounts_mcp.py` (`update_account`) and to
  `frontend/src/lib/api.ts` (`Account` + `AccountCreateData`) and the
  ProfileForm if user-editable.
- Launch-time browser behavior (proxy, fingerprint, Chromium profile prefs)
  lives in `src-tauri/binaries/cloak_launcher.py`; test offline with
  `python3 -m pytest src-tauri/binaries/test_cloak_launcher.py`.

## Landing the Plane (Session Completion)

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd sync
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds

