#!/usr/bin/env python3
"""
peon-ping: Warcraft III Peon voice lines for Claude Code hooks

Cross-platform Python version converted from peon.sh.
Supports macOS, WSL, native Windows, and Linux.
"""

import argparse
import json
import os
import platform
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------

def detect_platform() -> str:
    """Detect the runtime platform.

    Returns:
        One of 'mac', 'wsl', 'windows', 'linux', or 'unknown'.
    """
    system = platform.system()

    if system == "Darwin":
        return "mac"
    elif system == "Windows":
        return "windows"
    elif system == "Linux":
        try:
            with open("/proc/version", "r") as fh:
                if "microsoft" in fh.read().lower():
                    return "wsl"
        except Exception:
            pass
        return "linux"
    else:
        return "unknown"


PLATFORM: str = os.environ.get("PLATFORM", "") or detect_platform()

# ---------------------------------------------------------------------------
# Path configuration
# ---------------------------------------------------------------------------

# PEON_DIR defaults to the directory containing this script, which mirrors the
# behaviour of peon.sh (``PEON_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)``).
# It can be overridden via the ``CLAUDE_PEON_DIR`` environment variable.
_SCRIPT_DIR = Path(__file__).resolve().parent
PEON_DIR: Path = Path(os.environ.get("CLAUDE_PEON_DIR", str(_SCRIPT_DIR)))
CONFIG: Path = PEON_DIR / "config.json"
STATE: Path = PEON_DIR / ".state.json"
PAUSED_FILE: Path = PEON_DIR / ".paused"

# ---------------------------------------------------------------------------
# Config / state helpers
# ---------------------------------------------------------------------------


def load_config() -> dict:
    """Load configuration from *config.json*."""
    with open(CONFIG, "r", encoding="utf-8") as fh:
        return json.load(fh)


def load_config_safe() -> dict:
    """Load config, returning ``{}`` on any error."""
    try:
        return load_config()
    except Exception:
        return {}


def save_config(config: dict) -> None:
    """Persist *config* to *config.json*."""
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG, "w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2)


def load_state_safe() -> dict:
    """Load runtime state, returning ``{}`` on any error."""
    try:
        with open(STATE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def save_state(state: dict) -> None:
    """Persist runtime *state* to *.state.json*."""
    STATE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as fh:
        json.dump(state, fh)


# ---------------------------------------------------------------------------
# Linux audio backend detection
# ---------------------------------------------------------------------------

def _player_available(cmd: str) -> bool:
    """Return *True* if *cmd* is on ``PATH`` (and not disabled in test mode)."""
    if shutil.which(cmd) is None:
        return False
    # Respect test-mode disable markers (mirrors bash ``PEON_TEST`` logic)
    if os.environ.get("PEON_TEST") == "1":
        disable_marker = PEON_DIR / f".disabled_{cmd}"
        if disable_marker.exists():
            return False
    return True


_WARNED_NO_LINUX_AUDIO = False


def detect_linux_player() -> str:
    """Return the name of the first available Linux audio backend, or ``""``."""
    global _WARNED_NO_LINUX_AUDIO  # noqa: PLW0603

    for cmd in ("pw-play", "paplay", "ffplay", "mpv", "play", "aplay"):
        if _player_available(cmd):
            return cmd

    if not _WARNED_NO_LINUX_AUDIO:
        print(
            "WARNING: No audio backend found. Please install one of: "
            "pw-play, paplay, ffplay, mpv, play (SoX), or aplay",
            file=sys.stderr,
        )
        _WARNED_NO_LINUX_AUDIO = True

    return ""


# ---------------------------------------------------------------------------
# Audio playback
# ---------------------------------------------------------------------------

def play_sound(file_path: Path, volume: float) -> None:
    """Play *file_path* in the background at the given *volume* (0.0 – 1.0)."""

    def _play() -> None:
        if PLATFORM == "mac":
            _play_mac(file_path, volume)
        elif PLATFORM in ("wsl", "windows"):
            _play_windows(file_path, volume)
        elif PLATFORM == "linux":
            _play_linux(file_path, volume)

    thread = threading.Thread(target=_play, daemon=True)
    thread.start()


def _play_mac(file_path: Path, volume: float) -> None:
    """Play via macOS ``afplay``."""
    try:
        subprocess.Popen(
            ["afplay", "-v", str(volume), str(file_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def _play_windows(file_path: Path, volume: float) -> None:
    """Play via PowerShell ``MediaPlayer`` (WSL or native Windows)."""
    if PLATFORM == "wsl":
        try:
            result = subprocess.run(
                ["wslpath", "-w", str(file_path)],
                capture_output=True,
                text=True,
            )
            windows_path = result.stdout.strip()
        except Exception:
            return
    else:
        windows_path = str(file_path.resolve())

    # Convert backslashes to forward slashes for ``file:///`` URI
    windows_path = windows_path.replace("\\", "/")

    powershell_script = f"""
        Add-Type -AssemblyName PresentationCore
        $p = New-Object System.Windows.Media.MediaPlayer
        $p.Open([Uri]::new('file:///{windows_path}'))
        $p.Volume = {volume}
        Start-Sleep -Milliseconds 200
        $p.Play()
        Start-Sleep -Seconds 3
        $p.Close()
    """

    ps_exe = "powershell.exe" if PLATFORM == "wsl" else "powershell"

    try:
        subprocess.Popen(
            [ps_exe, "-NoProfile", "-NonInteractive", "-Command", powershell_script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def _play_linux(file_path: Path, volume: float) -> None:
    """Play via the best available Linux audio backend."""
    player = detect_linux_player()
    if not player:
        return

    use_bg = os.environ.get("PEON_TEST") != "1"
    file_str = str(file_path)

    try:
        if player == "pw-play":
            cmd = ["pw-play", "--volume", str(volume), file_str]
        elif player == "paplay":
            pa_vol = max(0, min(65536, int(volume * 65536)))
            cmd = ["paplay", f"--volume={pa_vol}", file_str]
        elif player == "ffplay":
            ff_vol = max(0, min(100, int(volume * 100)))
            cmd = ["ffplay", "-nodisp", "-autoexit", "-volume", str(ff_vol), file_str]
        elif player == "mpv":
            mpv_vol = max(0, min(100, int(volume * 100)))
            cmd = ["mpv", "--no-video", f"--volume={mpv_vol}", file_str]
        elif player == "play":
            cmd = ["play", "-v", str(volume), file_str]
        elif player == "aplay":
            cmd = ["aplay", "-q", file_str]
        else:
            return

        if use_bg:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

def send_notification(msg: str, title: str, color: str = "red") -> None:
    """Send a desktop notification in the background."""

    def _notify() -> None:
        if PLATFORM == "mac":
            _notify_mac(msg, title)
        elif PLATFORM in ("wsl", "windows"):
            _notify_windows(msg, title, color)
        elif PLATFORM == "linux":
            _notify_linux(msg, title, color)

    thread = threading.Thread(target=_notify, daemon=True)
    thread.start()


def _notify_mac(msg: str, title: str) -> None:
    """Send notification on macOS.

    Uses terminal-native escape sequences where supported (iTerm2, Kitty),
    falling back to ``osascript`` for others (Terminal.app, Warp, Ghostty).
    """
    term_program = os.environ.get("TERM_PROGRAM", "")

    try:
        if term_program == "iTerm.app":
            # iTerm2 OSC 9
            sys.stdout.write(f"\033]9;{title}: {msg}\007")
            sys.stdout.flush()
        elif term_program == "kitty":
            # Kitty OSC 99
            sys.stdout.write(f"\033]99;i=peon:d=0;{title}: {msg}\033\\")
            sys.stdout.flush()
        else:
            applescript = (
                'on run argv\n'
                '  display notification (item 1 of argv) with title (item 2 of argv)\n'
                'end run'
            )
            subprocess.Popen(
                ["osascript", "-e", applescript, msg, title],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    except Exception:
        pass


def _notify_windows(msg: str, title: str, color: str) -> None:
    """Send notification on Windows / WSL using PowerShell Forms."""
    color_map: Dict[str, Tuple[int, int, int]] = {
        "red": (180, 0, 0),
        "blue": (30, 80, 180),
        "yellow": (200, 160, 0),
    }
    rgb_r, rgb_g, rgb_b = color_map.get(color, (180, 0, 0))

    # Escape single quotes for PowerShell string literals
    msg_escaped = msg.replace("'", "''")

    # Determine temp dir for popup slot stacking
    if PLATFORM == "wsl":
        slot_dir_expr = "/tmp/peon-ping-popups"
        slot_mkdir = f'New-Item -ItemType Directory -Force -Path (wsl.exe -- bash -c "mkdir -p {slot_dir_expr}; echo {slot_dir_expr}") | Out-Null'
        # Simpler approach: use $env:TEMP on the Windows side regardless
        slot_dir_expr_ps = "$env:TEMP\\peon-ping-popups"
    else:
        slot_dir_expr_ps = "$env:TEMP\\peon-ping-popups"

    powershell_script = f"""
        $slotDir = "{slot_dir_expr_ps}"
        New-Item -ItemType Directory -Force -Path $slotDir | Out-Null
        $slot = 0
        while (Test-Path "$slotDir\\slot-$slot") {{
            $slot++
        }}
        New-Item -ItemType Directory -Path "$slotDir\\slot-$slot" | Out-Null
        $yOffset = 40 + ($slot * 90)

        Add-Type -AssemblyName System.Windows.Forms
        Add-Type -AssemblyName System.Drawing

        foreach ($screen in [System.Windows.Forms.Screen]::AllScreens) {{
            $form = New-Object System.Windows.Forms.Form
            $form.FormBorderStyle = 'None'
            $form.BackColor = [System.Drawing.Color]::FromArgb({rgb_r}, {rgb_g}, {rgb_b})
            $form.Size = New-Object System.Drawing.Size(500, 80)
            $form.TopMost = $true
            $form.ShowInTaskbar = $false
            $form.StartPosition = 'Manual'
            $form.Location = New-Object System.Drawing.Point(
                ($screen.WorkingArea.X + ($screen.WorkingArea.Width - 500) / 2),
                ($screen.WorkingArea.Y + $yOffset)
            )

            $label = New-Object System.Windows.Forms.Label
            $label.Text = '{msg_escaped}'
            $label.ForeColor = [System.Drawing.Color]::White
            $label.Font = New-Object System.Drawing.Font('Segoe UI', 16, [System.Drawing.FontStyle]::Bold)
            $label.TextAlign = 'MiddleCenter'
            $label.Dock = 'Fill'
            $form.Controls.Add($label)
            $form.Show()
        }}

        Start-Sleep -Seconds 4
        [System.Windows.Forms.Application]::Exit()
        Remove-Item "$slotDir\\slot-$slot" -Force -ErrorAction SilentlyContinue
    """

    ps_exe = "powershell.exe" if PLATFORM == "wsl" else "powershell"

    try:
        subprocess.Popen(
            [ps_exe, "-NoProfile", "-NonInteractive", "-Command", powershell_script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def _notify_linux(msg: str, title: str, color: str) -> None:
    """Send notification on Linux via ``notify-send``."""
    if shutil.which("notify-send") is None:
        return

    urgency = "critical" if color == "red" else "normal"

    try:
        subprocess.Popen(
            ["notify-send", f"--urgency={urgency}", title, msg],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Terminal focus detection
# ---------------------------------------------------------------------------

def terminal_is_focused() -> bool:
    """Return *True* if a terminal application is the frontmost window."""
    if PLATFORM == "mac":
        return _terminal_is_focused_mac()
    elif PLATFORM == "linux":
        return _terminal_is_focused_linux()
    else:
        # WSL / Windows: too much latency to check — always notify
        return False


def _terminal_is_focused_mac() -> bool:
    """Check focus on macOS via ``osascript``."""
    terminal_apps = {
        "Terminal", "iTerm2", "Warp", "Alacritty",
        "kitty", "WezTerm", "Ghostty",
    }
    try:
        result = subprocess.run(
            [
                "osascript", "-e",
                'tell application "System Events" to get name of first '
                'process whose frontmost is true',
            ],
            capture_output=True,
            text=True,
            timeout=2,
        )
        return result.stdout.strip() in terminal_apps
    except Exception:
        return False


def _terminal_is_focused_linux() -> bool:
    """Check focus on Linux via ``xdotool`` (X11 only)."""
    if os.environ.get("XDG_SESSION_TYPE") != "x11":
        return False
    if shutil.which("xdotool") is None:
        return False

    try:
        result = subprocess.run(
            ["xdotool", "getactivewindow", "getwindowname"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        win_name = result.stdout.strip().lower()
        terminal_keywords = (
            "terminal", "konsole", "alacritty", "kitty", "wezterm", "foot",
            "tilix", "gnome-terminal", "xterm", "xfce4-terminal", "sakura",
            "terminator", "st", "urxvt", "ghostty",
        )
        return any(kw in win_name for kw in terminal_keywords)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Terminal title
# ---------------------------------------------------------------------------

def set_terminal_title(title: str) -> None:
    """Set the terminal tab title via ANSI escape code (OSC 0)."""
    # Works in Windows Terminal, modern cmd.exe (Win 10+), PowerShell, and
    # Unix terminals (iTerm2, Terminal.app, Warp, etc.)
    escape_sequence = f"\033]0;{title}\007"
    try:
        sys.stdout.write(escape_sequence)
    except UnicodeEncodeError:
        # Windows cp1252 can't encode characters like ● (\u25cf).
        # Write raw UTF-8 bytes directly to the underlying buffer so the
        # terminal (which understands UTF-8) renders the title correctly.
        sys.stdout.buffer.write(escape_sequence.encode("utf-8"))
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Project name extraction
# ---------------------------------------------------------------------------

def get_project_name(cwd: str) -> str:
    """Derive a short project label from the working directory."""
    if not cwd:
        return "claude"

    # Handle both Unix ``/`` and Windows ``\\`` separators
    project = cwd.replace("\\", "/").rsplit("/", 1)[-1]
    if not project:
        return "claude"

    project = re.sub(r"[^a-zA-Z0-9 ._-]", "", project)
    return project or "claude"


# ---------------------------------------------------------------------------
# Sound picker
# ---------------------------------------------------------------------------

def pick_sound(pack_name: str, category: str, state: dict) -> Optional[Path]:
    """Pick a random sound file for *category*, avoiding the last-played file.

    Supports both ``openpeon.json`` (CESP standard) and legacy
    ``manifest.json`` formats.  Updates ``state['last_played']`` in-place.
    """
    pack_dir = PEON_DIR / "packs" / pack_name

    # Prefer openpeon.json (CESP), fall back to legacy manifest.json
    manifest: Optional[dict] = None
    for manifest_name in ("openpeon.json", "manifest.json"):
        manifest_path = pack_dir / manifest_name
        if manifest_path.exists():
            try:
                with open(manifest_path, "r", encoding="utf-8") as fh:
                    manifest = json.load(fh)
                break
            except Exception:
                continue

    if not manifest:
        return None

    sounds: List[dict] = (
        manifest.get("categories", {}).get(category, {}).get("sounds", [])
    )
    if not sounds:
        return None

    last_played: dict = state.get("last_played", {})
    last_file: str = last_played.get(category, "")

    if len(sounds) > 1:
        candidates = [s for s in sounds if s["file"] != last_file]
    else:
        candidates = sounds

    pick = random.choice(candidates)
    last_played[category] = pick["file"]
    state["last_played"] = last_played

    # openpeon.json uses paths like "sounds/file.wav"; legacy uses just "file.wav"
    file_ref: str = pick["file"]
    if "/" in file_ref:
        sound_path = pack_dir / file_ref
    else:
        sound_path = pack_dir / "sounds" / file_ref
    return sound_path if sound_path.exists() else None


# ---------------------------------------------------------------------------
# Update checking
# ---------------------------------------------------------------------------

def check_for_updates() -> None:
    """Check for a newer version on GitHub (non-blocking, once per day)."""

    def _check() -> None:
        check_file = PEON_DIR / ".last_update_check"
        now = int(time.time())

        try:
            last_check = int(check_file.read_text().strip())
        except Exception:
            last_check = 0

        if now - last_check <= 86400:
            return

        try:
            check_file.write_text(str(now))
        except Exception:
            pass

        version_file = PEON_DIR / "VERSION"
        try:
            local_version = version_file.read_text().strip()
        except Exception:
            local_version = ""

        try:
            with urllib.request.urlopen(
                "https://raw.githubusercontent.com/bwright2810/peon-ping/main/VERSION",
                timeout=5,
            ) as response:
                remote_version = response.read().decode("utf-8").strip()
        except Exception:
            return

        update_file = PEON_DIR / ".update_available"
        if remote_version and local_version and remote_version != local_version:
            try:
                update_file.write_text(remote_version)
            except Exception:
                pass
        else:
            try:
                update_file.unlink(missing_ok=True)
            except Exception:
                pass

    thread = threading.Thread(target=_check, daemon=True)
    thread.start()


def show_update_notice() -> None:
    """Print an update notice to *stderr* if one is pending."""
    update_file = PEON_DIR / ".update_available"
    if not update_file.exists():
        return

    try:
        new_version = update_file.read_text().strip()
        version_file = PEON_DIR / "VERSION"
        current_version = (
            version_file.read_text().strip() if version_file.exists() else "?"
        )
        if new_version:
            print(
                f"peon-ping update available: {current_version} \u2192 {new_version} "
                f"\u2014 run: curl -fsSL "
                f"https://raw.githubusercontent.com/bwright2810/peon-ping/main/install.sh | bash",
                file=sys.stderr,
            )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Event routing
# ---------------------------------------------------------------------------

def route_event(
    event: str,
    notification_type: str,
    config: dict,
    state: dict,
    session_id: str,
    project: str,
) -> Optional[Tuple[str, str, str, bool, str, str, dict]]:
    """Route *event* to a sound category and notification parameters.

    Returns:
        ``(category, status, marker, notify, notify_color, msg, state_updates)``
        or *None* if the event should be ignored.
    """
    category = ""
    status = ""
    marker = ""
    notify = False
    notify_color = ""
    msg = ""
    state_updates: dict = {}

    if event == "SessionStart":
        category = "session.start"
        status = "ready"

    elif event == "UserPromptSubmit":
        status = "working"

        categories_cfg = config.get("categories", {})
        if str(categories_cfg.get("user.spam", True)).lower() != "false":
            annoyed_threshold = int(config.get("annoyed_threshold", 3))
            annoyed_window = float(config.get("annoyed_window_seconds", 10))
            now = time.time()

            all_ts = state.get("prompt_timestamps", {})
            if isinstance(all_ts, list):
                all_ts = {}

            session_ts = [
                t for t in all_ts.get(session_id, []) if now - t < annoyed_window
            ]
            session_ts.append(now)
            all_ts[session_id] = session_ts
            state_updates["prompt_timestamps"] = all_ts

            if len(session_ts) >= annoyed_threshold:
                category = "user.spam"

    elif event == "Stop":
        category = "task.complete"
        status = "done"
        marker = "\u25cf "
        notify = True
        notify_color = "blue"
        msg = f"{project}  \u2014  Task complete"

    elif event == "Notification":
        if notification_type == "permission_prompt":
            category = "input.required"
            status = "needs approval"
            marker = "\u25cf "
            notify = True
            notify_color = "red"
            msg = f"{project}  \u2014  Permission needed"
        elif notification_type == "idle_prompt":
            status = "done"
            marker = "\u25cf "
            notify = True
            notify_color = "yellow"
            msg = f"{project}  \u2014  Waiting for input"
        else:
            return None

    elif event == "PermissionRequest":
        category = "input.required"
        status = "needs approval"
        marker = "\u25cf "
        notify = True
        notify_color = "red"
        msg = f"{project}  \u2014  Permission needed"

    else:
        # Unknown event — exit cleanly
        return None

    return (category, status, marker, notify, notify_color, msg, state_updates)


# ---------------------------------------------------------------------------
# Hook event handler (the main pipeline when no CLI flag is given)
# ---------------------------------------------------------------------------

def handle_hook_event() -> None:
    """Read a hook-event JSON blob from *stdin* and respond with sound/notification."""
    try:
        event_data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    paused = PAUSED_FILE.exists()

    config = load_config_safe()
    state = load_state_safe()
    state_dirty = False

    # Check if enabled
    if str(config.get("enabled", True)).lower() == "false":
        sys.exit(0)

    # Extract event details
    event: str = event_data.get("hook_event_name", "")
    notification_type: str = event_data.get("notification_type", "")
    cwd: str = event_data.get("cwd", "")
    session_id: str = event_data.get("session_id", "")
    permission_mode: str = event_data.get("permission_mode", "")

    # --- Agent detection ---
    agent_modes = {"delegate"}
    agent_sessions = set(state.get("agent_sessions", []))

    if permission_mode and permission_mode in agent_modes:
        agent_sessions.add(session_id)
        state["agent_sessions"] = list(agent_sessions)
        save_state(state)
        sys.exit(0)

    if session_id in agent_sessions:
        sys.exit(0)

    # --- Pack rotation: pin a pack per session ---
    active_pack: str = config.get("active_pack", "peon")
    pack_rotation: list = config.get("pack_rotation", [])

    if pack_rotation:
        session_packs: dict = state.get("session_packs", {})
        if (
            session_id in session_packs
            and session_packs[session_id] in pack_rotation
        ):
            active_pack = session_packs[session_id]
        else:
            rotation_mode = config.get("pack_rotation_mode", "random")
            if rotation_mode == "round-robin":
                rotation_index = state.get("rotation_index", 0) % len(pack_rotation)
                active_pack = pack_rotation[rotation_index]
                state["rotation_index"] = rotation_index + 1
            else:
                active_pack = random.choice(pack_rotation)
            session_packs[session_id] = active_pack
            state["session_packs"] = session_packs
            state_dirty = True

    # --- Project name ---
    project = get_project_name(cwd)

    # --- Route event ---
    result = route_event(event, notification_type, config, state, session_id, project)
    if result is None:
        sys.exit(0)

    category, status, marker, notify, notify_color, msg, state_updates = result

    if state_updates:
        state.update(state_updates)
        state_dirty = True

    # --- Check if category is enabled ---
    cats = config.get("categories", {})
    cat_enabled: Dict[str, bool] = {}
    for c in (
        "session.start", "task.acknowledge", "task.complete", "task.error",
        "input.required", "resource.limit", "user.spam",
    ):
        cat_enabled[c] = str(cats.get(c, True)).lower() != "false"

    if category and not cat_enabled.get(category, True):
        category = ""

    # --- Pick sound ---
    sound_file: Optional[Path] = None
    if category and not paused:
        sound_file = pick_sound(active_pack, category, state)
        if sound_file:
            state_dirty = True

    # --- Persist state ---
    if state_dirty:
        save_state(state)

    # --- Session-start extras ---
    if event == "SessionStart":
        check_for_updates()
        show_update_notice()
        if paused:
            print(
                "peon-ping: sounds paused \u2014 run 'peon --resume' "
                "or '/peon-ping-toggle' to unpause",
                file=sys.stderr,
            )

    # --- Tab title ---
    title = f"{marker}{project}: {status}"
    if title.strip():
        set_terminal_title(title)

    # --- Play sound ---
    if sound_file and sound_file.exists():
        volume = float(config.get("volume", 0.5))
        play_sound(sound_file, volume)

    # --- Notification ---
    notifications_enabled = str(config.get("desktop_notifications", False)).lower() != "false"
    if notify and not paused and notifications_enabled:
        if not terminal_is_focused():
            send_notification(msg, title, notify_color or "red")

    # Wait for background threads (audio, notification) to finish spawning
    # then allow the process to exit.  The daemon threads will be reaped.
    time.sleep(0.05)


# ---------------------------------------------------------------------------
# CLI command handlers
# ---------------------------------------------------------------------------

def handle_pause() -> None:
    PAUSED_FILE.touch()
    print("peon-ping: sounds paused")
    sys.exit(0)


def handle_resume() -> None:
    PAUSED_FILE.unlink(missing_ok=True)
    print("peon-ping: sounds resumed")
    sys.exit(0)


def handle_toggle() -> None:
    if PAUSED_FILE.exists():
        PAUSED_FILE.unlink()
        print("peon-ping: sounds resumed")
    else:
        PAUSED_FILE.touch()
        print("peon-ping: sounds paused")
    sys.exit(0)


def handle_status() -> None:
    if PAUSED_FILE.exists():
        print("peon-ping: paused")
    else:
        print("peon-ping: active")
    sys.exit(0)


def handle_packs() -> None:
    """List available sound packs (marks the active one with ``*``)."""
    active = load_config_safe().get("active_pack", "peon")
    packs_dir = PEON_DIR / "packs"

    for manifest_path in sorted(packs_dir.glob("*/manifest.json")):
        try:
            with open(manifest_path, "r", encoding="utf-8") as fh:
                info = json.load(fh)
            name = info.get("name", manifest_path.parent.name)
            display = info.get("display_name", name)
            marker_str = " *" if name == active else ""
            print(f"  {name:24s} {display}{marker_str}")
        except Exception:
            continue

    sys.exit(0)


def handle_pack(pack_name: Optional[str]) -> None:
    """Switch to *pack_name*, or cycle to the next pack if *None* / empty."""
    if not pack_name:
        _cycle_pack()
    else:
        _set_pack(pack_name)
    sys.exit(0)


def _cycle_pack() -> None:
    """Cycle to the next pack alphabetically."""
    config = load_config_safe()
    active = config.get("active_pack", "peon")
    packs_dir = PEON_DIR / "packs"
    manifests = sorted(packs_dir.glob("*/manifest.json"))

    if not manifests:
        print("Error: no packs found", file=sys.stderr)
        sys.exit(1)

    names = [m.parent.name for m in manifests]

    try:
        idx = names.index(active)
        next_pack = names[(idx + 1) % len(names)]
    except ValueError:
        next_pack = names[0]

    config["active_pack"] = next_pack
    save_config(config)

    with open(packs_dir / next_pack / "manifest.json", "r", encoding="utf-8") as fh:
        info = json.load(fh)
    display = info.get("display_name", next_pack)
    print(f"peon-ping: switched to {next_pack} ({display})")


def _set_pack(pack_name: str) -> None:
    """Set *pack_name* as the active pack."""
    packs_dir = PEON_DIR / "packs"
    manifests = sorted(packs_dir.glob("*/manifest.json"))
    names = [m.parent.name for m in manifests]

    if pack_name not in names:
        print(f'Error: pack "{pack_name}" not found.', file=sys.stderr)
        print(f'Available packs: {", ".join(names)}', file=sys.stderr)
        sys.exit(1)

    config = load_config_safe()
    config["active_pack"] = pack_name
    save_config(config)

    with open(packs_dir / pack_name / "manifest.json", "r", encoding="utf-8") as fh:
        info = json.load(fh)
    display = info.get("display_name", pack_name)
    print(f"peon-ping: switched to {pack_name} ({display})")


def handle_help() -> None:
    """Print usage information."""
    print(
        "Usage: peon <command>\n"
        "\n"
        "Commands:\n"
        "  --pause        Mute sounds\n"
        "  --resume       Unmute sounds\n"
        "  --toggle       Toggle mute on/off\n"
        "  --status       Check if paused or active\n"
        "  --packs        List available sound packs\n"
        "  --pack <name>  Switch to a specific pack\n"
        "  --pack         Cycle to the next pack\n"
        "  --help         Show this help"
    )
    sys.exit(0)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main() -> None:
    # Manual argument parsing to exactly match the bash ``case`` behaviour,
    # including ``--pack`` with optional positional argument.
    args = sys.argv[1:]

    if not args:
        # No CLI flags — act as hook handler (read event from stdin)
        handle_hook_event()
        return

    cmd = args[0]

    if cmd == "--pause":
        handle_pause()
    elif cmd == "--resume":
        handle_resume()
    elif cmd == "--toggle":
        handle_toggle()
    elif cmd == "--status":
        handle_status()
    elif cmd == "--packs":
        handle_packs()
    elif cmd == "--pack":
        pack_arg = args[1] if len(args) > 1 else None
        handle_pack(pack_arg)
    elif cmd in ("--help", "-h"):
        handle_help()
    elif cmd.startswith("--"):
        print(f"Unknown option: {cmd}", file=sys.stderr)
        print("Run 'peon --help' for usage.", file=sys.stderr)
        sys.exit(1)
    else:
        # Unknown positional arg — treat as hook input (shouldn't happen, but
        # fall through gracefully)
        handle_hook_event()


if __name__ == "__main__":
    main()
