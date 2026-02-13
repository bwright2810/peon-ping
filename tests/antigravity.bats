#!/usr/bin/env bats

load setup.bash

setup() {
  setup_test_env

  # Create a mock Antigravity conversations directory
  export ANTIGRAVITY_CONVERSATIONS_DIR="$TEST_DIR/conversations"
  mkdir -p "$ANTIGRAVITY_CONVERSATIONS_DIR"

  # Copy peon.sh into test dir so the adapter can find it
  cp "$PEON_SH" "$TEST_DIR/peon.sh"

  # Mock fswatch so preflight passes
  cat > "$MOCK_BIN/fswatch" <<'SCRIPT'
#!/bin/bash
sleep 999
SCRIPT
  chmod +x "$MOCK_BIN/fswatch"

  ADAPTER_SH="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)/adapters/antigravity.sh"
}

teardown() {
  teardown_test_env
}

# Helper: source the adapter in test mode so all functions are available
# but the main watcher loop is skipped.
source_adapter() {
  export PEON_ADAPTER_TEST=1
  export TMPDIR="$TEST_DIR"
  source "$ADAPTER_SH" 2>/dev/null
  # Restore BATS-friendly settings (adapter sets -euo pipefail)
  set +e +u
  set +o pipefail 2>/dev/null || true
}

# Helper: create a .pb file for a given GUID (simulates a conversation)
create_pb() {
  local guid="$1"
  printf '\x0a\x04test' > "$ANTIGRAVITY_CONVERSATIONS_DIR/${guid}.pb"
}

# ============================================================
# Syntax validation
# ============================================================

@test "adapter script has valid bash syntax" {
  run bash -n "$ADAPTER_SH"
  [ "$status" -eq 0 ]
}

# ============================================================
# Preflight: missing peon.sh
# ============================================================

@test "exits with error when peon.sh is not found" {
  local empty_dir
  empty_dir="$(mktemp -d)"
  CLAUDE_PEON_DIR="$empty_dir" run bash "$ADAPTER_SH"
  [ "$status" -eq 1 ]
  [[ "$output" == *"peon.sh not found"* ]]
  rm -rf "$empty_dir"
}

# ============================================================
# Preflight: missing filesystem watcher
# ============================================================

@test "exits with error when no filesystem watcher is available" {
  rm -f "$MOCK_BIN/fswatch"
  rm -f "$MOCK_BIN/inotifywait"
  # Restrict PATH so real system fswatch/inotifywait are not found
  PATH="$MOCK_BIN:/usr/bin:/bin" run bash "$ADAPTER_SH"
  [ "$status" -eq 1 ]
  [[ "$output" == *"No filesystem watcher found"* ]]
}

# ============================================================
# State tracking: guid_get / guid_set
# ============================================================

@test "guid_get returns empty for unknown GUID" {
  source_adapter
  result=$(guid_get "unknown-guid-1234")
  [ -z "$result" ]
}

@test "guid_set and guid_get round-trip correctly" {
  source_adapter
  guid_set "test-guid-aaaa" "active"
  result=$(guid_get "test-guid-aaaa")
  [ "$result" = "active" ]

  guid_set "test-guid-aaaa" "idle"
  result=$(guid_get "test-guid-aaaa")
  [ "$result" = "idle" ]
}

# ============================================================
# Cooldown tracking: stop_time_get / stop_time_set
# ============================================================

@test "stop_time_get returns 0 for unknown GUID" {
  source_adapter
  result=$(stop_time_get "unknown-guid-5678")
  [ "$result" = "0" ]
}

@test "stop_time_set and stop_time_get round-trip correctly" {
  source_adapter
  stop_time_set "test-guid-bbbb" "1700000000"
  result=$(stop_time_get "test-guid-bbbb")
  [ "$result" = "1700000000" ]
}

# ============================================================
# handle_conversation_change: new .pb triggers SessionStart
# ============================================================

@test "new .pb file triggers SessionStart and plays sound" {
  source_adapter
  local guid="brand-new-guid-0001"
  create_pb "$guid"

  handle_conversation_change "$ANTIGRAVITY_CONVERSATIONS_DIR/${guid}.pb"

  # State should be active
  result=$(guid_get "$guid")
  [ "$result" = "active" ]

  # Give async audio a moment (peon.sh uses nohup &)
  sleep 0.5

  afplay_was_called
  sound=$(afplay_sound)
  [[ "$sound" == *"/packs/peon/sounds/Hello"* ]]
}

# ============================================================
# handle_conversation_change: known GUID no duplicate SessionStart
# ============================================================

@test "known GUID update does not emit duplicate SessionStart" {
  source_adapter
  local guid="known-guid-0002"

  # Pre-register as known (simulates adapter having seen this GUID before)
  guid_set "$guid" "idle"
  create_pb "$guid"

  handle_conversation_change "$ANTIGRAVITY_CONVERSATIONS_DIR/${guid}.pb"

  # State should be active now
  result=$(guid_get "$guid")
  [ "$result" = "active" ]

  # No sound should play (no SessionStart for known GUID)
  sleep 0.3
  count=$(afplay_call_count)
  [ "$count" -eq 0 ]
}

# ============================================================
# check_idle_sessions: emits Stop for stale active sessions
# ============================================================

@test "idle active session emits Stop event" {
  export ANTIGRAVITY_IDLE_SECONDS=1
  source_adapter
  local guid="idle-test-guid-0003"

  # Create .pb and mark active
  create_pb "$guid"
  guid_set "$guid" "active"

  # Wait past the idle threshold
  sleep 2

  check_idle_sessions

  # State should now be idle
  result=$(guid_get "$guid")
  [ "$result" = "idle" ]

  # peon.sh should have played a completion sound
  sleep 0.5
  afplay_was_called
}

# ============================================================
# check_idle_sessions: cooldown prevents duplicate Stop
# ============================================================

@test "cooldown prevents duplicate Stop events" {
  export ANTIGRAVITY_IDLE_SECONDS=1
  export ANTIGRAVITY_STOP_COOLDOWN=60
  source_adapter
  local guid="cooldown-test-0004"

  create_pb "$guid"
  guid_set "$guid" "active"

  # Set a recent stop time (within cooldown window)
  local now
  now=$(date +%s)
  stop_time_set "$guid" "$now"

  # Wait past idle threshold
  sleep 2

  check_idle_sessions

  # State should be idle (marked idle despite cooldown)
  result=$(guid_get "$guid")
  [ "$result" = "idle" ]

  # No sound should play (cooldown suppressed the Stop event)
  sleep 0.3
  count=$(afplay_call_count)
  [ "$count" -eq 0 ]
}
