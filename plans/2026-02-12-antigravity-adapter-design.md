# Antigravity Adapter Design

**Date:** 2026-02-12
**Issue:** [#97](https://github.com/PeonPing/peon-ping/issues/97)
**Status:** Approved

## Summary

A filesystem-watcher bash script (`adapters/antigravity.sh`) that monitors Google Antigravity's artifact directory for agent state changes and translates them into peon.sh CESP events.

## Context

Google Antigravity has no shell hooks or event callbacks. Agent state lives as files in `~/.gemini/antigravity/brain/<GUID>/` with markdown artifacts and `.metadata.json` sidecar files. The adapter watches these files for changes using `fswatch` (macOS) or `inotifywait` (Linux).

## Event Mapping

| Filesystem signal | Peon event | CESP category |
|---|---|---|
| New `<GUID>/task.md.metadata.json` created | `SessionStart` | `session.start` |
| Metadata updated + task items `in-progress` | `UserPromptSubmit` | `task.acknowledge` |
| `walkthrough.md.metadata.json` appears (VERIFICATION) | `Stop` | `task.complete` |
| All task items `completed` | `Stop` | `task.complete` |
| Error keywords in task metadata | `Stop` | `task.error` |

## Architecture

Single file: `adapters/antigravity.sh`

### Components

1. **Preflight** - Check for `fswatch`/`inotifywait`, verify peon.sh exists
2. **State tracking** - Bash associative array of known GUIDs and their last-seen phases
3. **Metadata parser** - Python one-liner to read `.metadata.json` and extract artifact type, phase, status
4. **Event mapper** - Translate artifact phase/type changes to peon.sh hook events
5. **Main loop** - `fswatch` piped to event handler, each event pipes JSON to `peon.sh`
6. **Cleanup** - Trap SIGINT/SIGTERM for graceful shutdown

### Usage

```bash
# Foreground
bash ~/.claude/hooks/peon-ping/adapters/antigravity.sh

# Background
bash ~/.claude/hooks/peon-ping/adapters/antigravity.sh &
```

### Dependencies

- `fswatch` (macOS: `brew install fswatch`) or `inotifywait` (Linux: `apt install inotify-tools`)
- Python 3 (already required by peon.sh)
- peon-ping installed (packs + config in place)

## Scope

- No installer script (assumes peon-ping already installed)
- No auto-start/service management
- No VS Code extension
- Relies on documented `~/.gemini/antigravity/brain/` structure

## Risks

- Antigravity is in public preview; artifact directory structure may change
- Metadata JSON fields may evolve (same risk all adapters carry)
