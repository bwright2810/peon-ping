# Antigravity Adapter Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a filesystem-watcher adapter that translates Google Antigravity agent events into peon-ping CESP sounds.

**Architecture:** A single bash script (`adapters/antigravity.sh`) uses `fswatch` (macOS) or `inotifywait` (Linux) to watch `~/.gemini/antigravity/brain/` for `.metadata.json` changes. A Python one-liner parses each metadata file to determine the artifact type and phase, maps it to a peon.sh hook event, and pipes JSON to `peon.sh`. State is tracked in a bash associative array to detect new sessions vs. phase transitions.

**Tech Stack:** Bash, Python 3 (already required), fswatch/inotifywait, BATS for tests

---

### Task 1: Write the adapter script skeleton with preflight checks

**Files:**
- Create: `adapters/antigravity.sh`

**Step 1: Write the adapter script**

```bash
#!/bin/bash
# peon-ping adapter for Google Antigravity IDE
# Watches ~/.gemini/antigravity/brain/ for agent state changes
# and translates them into peon.sh CESP events.
#
# Requires: fswatch (macOS: brew install fswatch) or inotifywait (Linux: apt install inotify-tools)
# Requires: peon-ping already installed
#
# Usage:
#   bash ~/.claude/hooks/peon-ping/adapters/antigravity.sh        # foreground
#   bash ~/.claude/hooks/peon-ping/adapters/antigravity.sh &      # background

set -euo pipefail

PEON_DIR="${CLAUDE_PEON_DIR:-${CLAUDE_CONFIG_DIR:-$HOME/.claude}/hooks/peon-ping}"
BRAIN_DIR="${ANTIGRAVITY_BRAIN_DIR:-$HOME/.gemini/antigravity/brain}"

# --- Colors ---
BOLD=$'\033[1m' DIM=$'\033[2m' RED=$'\033[31m' GREEN=$'\033[32m' YELLOW=$'\033[33m' RESET=$'\033[0m'

info()  { printf "%s>%s %s\n" "$GREEN" "$RESET" "$*"; }
warn()  { printf "%s!%s %s\n" "$YELLOW" "$RESET" "$*"; }
error() { printf "%sx%s %s\n" "$RED" "$RESET" "$*" >&2; }

# --- Preflight ---
if [ ! -f "$PEON_DIR/peon.sh" ]; then
  error "peon.sh not found at $PEON_DIR/peon.sh"
  error "Install peon-ping first: curl -fsSL peonping.com/install | bash"
  exit 1
fi

if ! command -v python3 &>/dev/null; then
  error "python3 is required but not found."
  exit 1
fi

# Detect filesystem watcher
WATCHER=""
if command -v fswatch &>/dev/null; then
  WATCHER="fswatch"
elif command -v inotifywait &>/dev/null; then
  WATCHER="inotifywait"
else
  error "No filesystem watcher found."
  error "  macOS: brew install fswatch"
  error "  Linux: apt install inotify-tools"
  exit 1
fi

if [ ! -d "$BRAIN_DIR" ]; then
  warn "Antigravity brain directory not found: $BRAIN_DIR"
  warn "Waiting for Antigravity to create it..."
  while [ ! -d "$BRAIN_DIR" ]; do
    sleep 2
  done
  info "Brain directory detected."
fi

# --- State: track known GUIDs and their last-seen artifact type ---
declare -A KNOWN_GUIDS  # GUID -> last artifact type seen (task|implementation_plan|walkthrough)

# --- Emit a peon.sh event ---
emit_event() {
  local event="$1"
  local guid="$2"
  local session_id="antigravity-${guid:0:8}"

  echo "{\"hook_event_name\":\"$event\",\"notification_type\":\"\",\"cwd\":\"$PWD\",\"session_id\":\"$session_id\",\"permission_mode\":\"\"}" \
    | bash "$PEON_DIR/peon.sh" 2>/dev/null || true
}

# --- Parse a metadata file and determine event ---
handle_metadata_change() {
  local filepath="$1"

  # Extract GUID from path: .../brain/<GUID>/file.metadata.json
  local guid
  guid=$(python3 -c "
import sys, os
parts = sys.argv[1].split(os.sep)
# Find 'brain' in path, GUID is next element
for i, p in enumerate(parts):
    if p == 'brain' and i + 1 < len(parts):
        print(parts[i + 1])
        break
" "$filepath" 2>/dev/null) || return

  [ -z "$guid" ] && return

  # Parse metadata to get artifact type
  local artifact_type
  artifact_type=$(python3 -c "
import sys, json
try:
    meta = json.load(open(sys.argv[1]))
    at = meta.get('artifactType', '')
    # Strip prefix: ARTIFACT_TYPE_TASK -> task
    at = at.replace('ARTIFACT_TYPE_', '').lower()
    print(at)
except:
    pass
" "$filepath" 2>/dev/null) || return

  [ -z "$artifact_type" ] && return

  local prev="${KNOWN_GUIDS[$guid]:-}"

  case "$artifact_type" in
    task)
      if [ -z "$prev" ]; then
        # New task = new session
        KNOWN_GUIDS[$guid]="task"
        info "New agent session: ${guid:0:8}"
        emit_event "SessionStart" "$guid"
      fi
      ;;
    implementation_plan)
      if [ "$prev" != "implementation_plan" ] && [ "$prev" != "walkthrough" ]; then
        # Moved to execution phase
        KNOWN_GUIDS[$guid]="implementation_plan"
        info "Agent working: ${guid:0:8}"
        emit_event "UserPromptSubmit" "$guid"
      fi
      ;;
    walkthrough)
      if [ "$prev" != "walkthrough" ]; then
        # Moved to verification = task complete
        KNOWN_GUIDS[$guid]="walkthrough"
        info "Agent completed: ${guid:0:8}"
        emit_event "Stop" "$guid"
      fi
      ;;
  esac
}

# --- Cleanup ---
cleanup() {
  info "Stopping Antigravity watcher..."
  # Kill the watcher subprocess if running
  [ -n "${WATCHER_PID:-}" ] && kill "$WATCHER_PID" 2>/dev/null
  exit 0
}
trap cleanup SIGINT SIGTERM

# --- Start watching ---
info "${BOLD}peon-ping Antigravity adapter${RESET}"
info "Watching: $BRAIN_DIR"
info "Watcher: $WATCHER"
info "Press Ctrl+C to stop."
echo ""

if [ "$WATCHER" = "fswatch" ]; then
  fswatch -r --include '\.metadata\.json$' --exclude '.*' "$BRAIN_DIR" | while read -r changed_file; do
    handle_metadata_change "$changed_file"
  done &
  WATCHER_PID=$!
elif [ "$WATCHER" = "inotifywait" ]; then
  inotifywait -m -r -e modify,create --format '%w%f' "$BRAIN_DIR" 2>/dev/null | while read -r changed_file; do
    [[ "$changed_file" == *.metadata.json ]] || continue
    handle_metadata_change "$changed_file"
  done &
  WATCHER_PID=$!
fi

wait "$WATCHER_PID"
```

**Step 2: Make it executable and verify syntax**

Run: `chmod +x adapters/antigravity.sh && bash -n adapters/antigravity.sh`
Expected: No output (clean syntax)

**Step 3: Commit**

```bash
git add adapters/antigravity.sh
git commit -m "feat: add Google Antigravity adapter (filesystem watcher)

Closes #97"
```

---

### Task 2: Write tests for the adapter

**Files:**
- Create: `tests/antigravity.bats`

**Step 1: Write tests**

The adapter is fundamentally different from peon.sh tests — we can't easily test the fswatch loop in BATS. Instead, we test the core logic by extracting `handle_metadata_change` as a callable function and testing its event emission.

Strategy: Source the adapter in a mode that skips the main loop, then call `handle_metadata_change` with mock metadata files and verify it emits the correct events to peon.sh.

```bash
#!/usr/bin/env bats

load setup.bash

setup() {
  setup_test_env

  # Create a mock Antigravity brain directory
  export ANTIGRAVITY_BRAIN_DIR="$TEST_DIR/brain"
  mkdir -p "$ANTIGRAVITY_BRAIN_DIR"

  # Mock fswatch so preflight passes
  cat > "$MOCK_BIN/fswatch" <<'SCRIPT'
#!/bin/bash
# Mock fswatch: do nothing (we call handle_metadata_change directly)
sleep 999
SCRIPT
  chmod +x "$MOCK_BIN/fswatch"

  ADAPTER_SH="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/adapters/antigravity.sh"
}

teardown() {
  teardown_test_env
}

# Helper: create a metadata file for a GUID
create_metadata() {
  local guid="$1"
  local artifact_type="$2"

  mkdir -p "$ANTIGRAVITY_BRAIN_DIR/$guid"
  cat > "$ANTIGRAVITY_BRAIN_DIR/$guid/${artifact_type}.md.metadata.json" <<JSON
{
  "artifactType": "ARTIFACT_TYPE_$(echo "$artifact_type" | tr '[:lower:]' '[:upper:]')",
  "summary": "Test artifact",
  "updatedAt": "2026-02-12T00:00:00Z",
  "version": 1
}
JSON
}

# Helper: source adapter functions without starting the watcher
# We source in a subshell with PEON_ADAPTER_TEST=1 to skip the main loop
source_adapter() {
  # We can't easily source a script with set -euo pipefail and a main loop.
  # Instead, we extract and test the Python parsing + event emission separately.
  true
}

# --- Tests ---

@test "adapter script has valid bash syntax" {
  bash -n "$ADAPTER_SH"
}

@test "adapter detects missing peon.sh and exits with error" {
  # Point to empty dir with no peon.sh
  export CLAUDE_PEON_DIR="$TEST_DIR/empty_peon"
  mkdir -p "$CLAUDE_PEON_DIR"
  run bash "$ADAPTER_SH"
  [ "$status" -ne 0 ]
  [[ "$output" == *"peon.sh not found"* ]]
}

@test "adapter detects missing fswatch/inotifywait and exits with error" {
  # Remove mock fswatch from PATH
  rm -f "$MOCK_BIN/fswatch"
  # Also ensure inotifywait doesn't exist
  rm -f "$MOCK_BIN/inotifywait" 2>/dev/null || true
  run bash "$ADAPTER_SH"
  [ "$status" -ne 0 ]
  [[ "$output" == *"No filesystem watcher found"* ]]
}

@test "metadata parser extracts artifact type correctly" {
  local guid="test-guid-1234"
  create_metadata "$guid" "task"

  local result
  result=$(python3 -c "
import sys, json
try:
    meta = json.load(open(sys.argv[1]))
    at = meta.get('artifactType', '')
    at = at.replace('ARTIFACT_TYPE_', '').lower()
    print(at)
except:
    pass
" "$ANTIGRAVITY_BRAIN_DIR/$guid/task.md.metadata.json")

  [ "$result" = "task" ]
}

@test "metadata parser handles implementation_plan type" {
  local guid="test-guid-5678"
  create_metadata "$guid" "implementation_plan"

  local result
  result=$(python3 -c "
import sys, json
try:
    meta = json.load(open(sys.argv[1]))
    at = meta.get('artifactType', '')
    at = at.replace('ARTIFACT_TYPE_', '').lower()
    print(at)
except:
    pass
" "$ANTIGRAVITY_BRAIN_DIR/$guid/implementation_plan.md.metadata.json")

  [ "$result" = "implementation_plan" ]
}

@test "metadata parser handles walkthrough type" {
  local guid="test-guid-9012"
  create_metadata "$guid" "walkthrough"

  local result
  result=$(python3 -c "
import sys, json
try:
    meta = json.load(open(sys.argv[1]))
    at = meta.get('artifactType', '')
    at = at.replace('ARTIFACT_TYPE_', '').lower()
    print(at)
except:
    pass
" "$ANTIGRAVITY_BRAIN_DIR/$guid/walkthrough.md.metadata.json")

  [ "$result" = "walkthrough" ]
}

@test "GUID extraction from filepath works" {
  local filepath="$HOME/.gemini/antigravity/brain/abc-def-123/task.md.metadata.json"

  local guid
  guid=$(python3 -c "
import sys, os
parts = sys.argv[1].split(os.sep)
for i, p in enumerate(parts):
    if p == 'brain' and i + 1 < len(parts):
        print(parts[i + 1])
        break
" "$filepath")

  [ "$guid" = "abc-def-123" ]
}
```

**Step 2: Run the tests**

Run: `bats tests/antigravity.bats`
Expected: All tests pass

**Step 3: Commit**

```bash
git add tests/antigravity.bats
git commit -m "test: add Antigravity adapter tests"
```

---

### Task 3: Add test mode to adapter for testability

**Files:**
- Modify: `adapters/antigravity.sh`

**Step 1: Add PEON_ADAPTER_TEST guard around the main watcher loop**

Add this just before the `# --- Start watching ---` section so tests can source the script and call functions without starting the watcher:

```bash
# --- Test mode: skip main loop when sourced for testing ---
if [ "${PEON_ADAPTER_TEST:-0}" = "1" ]; then
  return 0 2>/dev/null || exit 0
fi
```

**Step 2: Add integration test that calls handle_metadata_change via sourcing**

Add to `tests/antigravity.bats`:

```bash
@test "new task metadata emits SessionStart event" {
  local guid="session-test-001"
  create_metadata "$guid" "task"

  # Source adapter in test mode to get functions, then call handle_metadata_change
  export PEON_ADAPTER_TEST=1
  source "$ADAPTER_SH"

  handle_metadata_change "$ANTIGRAVITY_BRAIN_DIR/$guid/task.md.metadata.json"

  # Check that peon.sh was called (afplay was invoked)
  afplay_was_called
  sound=$(afplay_sound)
  [[ "$sound" == *"/packs/peon/sounds/Hello"* ]]
}

@test "walkthrough metadata emits Stop event" {
  local guid="complete-test-001"
  create_metadata "$guid" "task"

  export PEON_ADAPTER_TEST=1
  source "$ADAPTER_SH"

  # First create the session
  handle_metadata_change "$ANTIGRAVITY_BRAIN_DIR/$guid/task.md.metadata.json"

  # Then mark walkthrough
  create_metadata "$guid" "walkthrough"
  handle_metadata_change "$ANTIGRAVITY_BRAIN_DIR/$guid/walkthrough.md.metadata.json"

  # Should have played a complete sound
  local count
  count=$(afplay_call_count)
  [ "$count" -ge 2 ]
}

@test "duplicate task metadata does not re-emit SessionStart" {
  local guid="dedup-test-001"
  create_metadata "$guid" "task"

  export PEON_ADAPTER_TEST=1
  source "$ADAPTER_SH"

  handle_metadata_change "$ANTIGRAVITY_BRAIN_DIR/$guid/task.md.metadata.json"
  handle_metadata_change "$ANTIGRAVITY_BRAIN_DIR/$guid/task.md.metadata.json"

  # Should only have been called once
  local count
  count=$(afplay_call_count)
  [ "$count" = "1" ]
}
```

**Step 3: Run all tests**

Run: `bats tests/antigravity.bats`
Expected: All tests pass

**Step 4: Commit**

```bash
git add adapters/antigravity.sh tests/antigravity.bats
git commit -m "test: add integration tests for Antigravity adapter event emission"
```

---

### Task 4: Update documentation

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md` (add Antigravity to supported IDEs list)

**Step 1: Add Antigravity adapter to CLAUDE.md adapters list**

In the `### Multi-IDE Adapters` section, add:

```markdown
- **`adapters/antigravity.sh`** — Filesystem watcher for Google Antigravity agent events
```

**Step 2: Add Antigravity setup instructions to README.md**

Find the IDE setup section and add an Antigravity subsection with usage instructions.

**Step 3: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "docs: add Antigravity adapter to docs"
```

---

### Task 5: Final integration verification

**Step 1: Run all tests**

Run: `bats tests/`
Expected: All test files pass (peon.bats, install.bats, relay.bats, antigravity.bats)

**Step 2: Verify script runs and prints banner**

Run: `ANTIGRAVITY_BRAIN_DIR=/tmp/fake-brain-dir bash adapters/antigravity.sh &; sleep 2; kill %1`
Expected: Banner prints, watcher starts, clean exit on SIGTERM

**Step 3: Final commit if any fixups needed**

---
