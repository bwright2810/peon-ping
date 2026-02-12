# peon-ping (fork)

This is a custom fork of [PeonPing/peon-ping](https://github.com/PeonPing/peon-ping). It adds Windows cmd.exe / PowerShell / clink compatibility along with a few tweaks.

These tweaks are documented in the "Fork changelog" section of the README.

## Merging upstream

When merging commits from the upstream repo (`https://github.com/PeonPing/peon-ping`):

- Merge cleanly whenever possible. During merge conflicts, grab everything new from upstream but keep our custom additions.
- Anywhere the original repo URL (`PeonPing/peon-ping`) is referenced, replace it with our fork URL (`bwright2810/peon-ping`).
- We default `desktop_notifications` to `false` (upstream defaults to `true`). Preserve our default during merges.
- After merging, ensure that our Windows-specific `.py` files match the behavior of any new changes to the associated `.sh` files:
  - `install.sh` ↔ `install.py`
  - `peon.sh` ↔ `peon.py`
  - `uninstall.sh` ↔ `uninstall.py`
  - `peon.bat` wraps `peon.py`

### Expected upstream deletions

Upstream does not maintain our Windows files. Merges will show deletions of `install.py`, `peon.py`, `peon.bat`, and `uninstall.py`. This is expected — git will keep our versions as long as they have local modifications. Do not be alarmed by these appearing in the diff.

### Post-merge checklist

After every upstream merge, verify the following:

**Fork URLs** — these files contain raw GitHub URLs that upstream points to `PeonPing/peon-ping`. Ours must point to `bwright2810/peon-ping`:
- `install.sh` — `REPO_BASE` variable
- `peon.sh` — VERSION check URL (~line 695), update available message (~line 712)
- `README.md` — all install command curl URLs

**`desktop_notifications` default = `false`** — upstream defaults to `true`. Check all of these locations:
- `config.json` — the `desktop_notifications` field
- `peon.sh` — embedded Python status display (`c.get('desktop_notifications', False)`), main config read (`cfg.get('desktop_notifications', False)`), smart notification fallback (`${DESKTOP_NOTIF:-false}`)
- `peon.py` — `config.get("desktop_notifications", False)`
- `skills/peon-ping-config/SKILL.md` — the `desktop_notifications` field description and default
- `README.md` — the desktop_notifications documentation line

**`uninstall.sh`** — must remove both `peon-ping-toggle` AND `peon-ping-config` skill directories. Upstream only removes `peon-ping-toggle`.

**`FALLBACK_PACKS` in `install.py`** — keep in sync with `FALLBACK_PACKS` in `install.sh` when upstream adds new packs.

**`DEFAULT_PACKS` in `install.py`** — keep in sync with `DEFAULT_PACKS` in `install.sh`.

## What This Is

peon-ping is a Claude Code hook that plays game character voice lines and sends desktop notifications when Claude Code needs attention. It handles 5 hook events: `SessionStart`, `UserPromptSubmit`, `Stop`, `Notification`, `PermissionRequest`. Written entirely in bash + embedded Python (no npm/node runtime needed). This fork adds native Windows support via `peon.py` and `install.py`.

## Commands

```bash
# Run all tests (requires bats-core: brew install bats-core)
bats tests/

# Run a single test file
bats tests/peon.bats
bats tests/install.bats

# Run a specific test by name
bats tests/peon.bats -f "plays session.start sound"

# Install locally for development
bash install.sh --local

# Install only specific packs
bash install.sh --packs=peon,glados,peasant
```

There is no build step, linter, or formatter configured for the shell codebase.

## Architecture

### Core Files

- **`peon.sh`** — Main hook script (Unix). Receives JSON event data on stdin from Claude Code, routes events via an embedded Python block that handles config loading, event parsing, sound selection, and state management in a single invocation. Shell code then handles async audio playback (`nohup` + background processes) and desktop notifications.
- **`peon.py`** — Main hook script (Windows). Pure Python equivalent of `peon.sh` for native Windows support.
- **`install.sh`** — Installer (Unix). Fetches pack registry from GitHub Pages, downloads selected packs, registers hooks in `~/.claude/settings.json`.
- **`install.py`** — Installer (Windows). Cross-platform Python equivalent of `install.sh`.
- **`config.json`** — Default configuration template.

### Event Flow

Claude Code triggers hook → `peon.sh`/`peon.py` reads JSON stdin → maps events to CESP categories (`session.start`, `task.complete`, `input.required`, `user.spam`, etc.) → picks a sound (no-repeat logic) → plays audio async and optionally sends desktop notification.

### Platform Audio Backends

- **macOS:** `afplay`
- **Windows:** PowerShell `MediaPlayer`
- **WSL2:** PowerShell `MediaPlayer` via `powershell.exe`
- **Linux:** priority chain: `pw-play` → `paplay` → `ffplay` → `mpv` → `play` (SoX) → `aplay` (each with different volume scaling)

### State Management

`.state.json` persists across invocations: agent session tracking (suppresses sounds in delegate mode), pack rotation index, prompt timestamps (for annoyed easter egg), last-played sounds (no-repeat), and stop debouncing.

### Multi-IDE Adapters

`adapters/cursor.sh` and `adapters/codex.sh` translate IDE-specific events into the standardized CESP JSON format that `peon.sh` expects.

### Pack Format

Packs use `openpeon.json` (CESP standard) with categories mapping to arrays of `{ "file": "sound.wav", "label": "text" }` entries. Packs are downloaded from the [OpenPeon registry](https://github.com/PeonPing/registry) at install time into `~/.claude/hooks/peon-ping/packs/`.

## Testing

Tests use [BATS](https://github.com/bats-core/bats-core) (Bash Automated Testing System). Test setup (`tests/setup.bash`) creates isolated temp directories with mock audio backends, manifests, and config so tests never touch real state. Key mock: `afplay` is replaced with a script that logs calls instead of playing audio.

CI runs on macOS (`macos-latest`) via GitHub Actions.

## Skills

Two Claude Code skills live in `skills/`:
- `/peon-ping-toggle` — Mute/unmute sounds
- `/peon-ping-config` — Modify any peon-ping setting (volume, packs, categories, etc.)

## Website

`docs/` contains the static landing page (peonping.com), deployed via Vercel. `video/` is a separate Remotion project for promotional videos (React + TypeScript, independent from the main codebase).
