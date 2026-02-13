#!/usr/bin/env python3
"""
peon-ping: Warcraft III Peon voice lines for Claude Code hooks

Cross-platform Python version converted from peon.sh.
Supports macOS, WSL, native Windows, Linux, SSH, and devcontainers.
"""

import json
import os
import platform
import random
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------

def detect_platform() -> str:
    """Detect the runtime platform.

    Returns:
        One of 'mac', 'ssh', 'wsl', 'devcontainer', 'windows', 'linux',
        or 'unknown'.
    """
    system = platform.system()

    if system == "Darwin":
        if os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_CLIENT"):
            return "ssh"
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
        if os.environ.get("REMOTE_CONTAINERS") == "true" or os.environ.get("CODESPACES") == "true":
            return "devcontainer"
        if os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_CLIENT"):
            return "ssh"
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

# Homebrew installs: script lives in Cellar but packs/config are in hooks dir
if not (PEON_DIR / "packs").is_dir():
    _hooks_dir = Path(
        os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude"))
    ) / "hooks" / "peon-ping"
    if (_hooks_dir / "packs").is_dir():
        PEON_DIR = _hooks_dir

CONFIG: Path = PEON_DIR / "config.json"
STATE: Path = PEON_DIR / ".state.json"
PAUSED_FILE: Path = PEON_DIR / ".paused"
SOUND_PID_FILE: Path = PEON_DIR / ".sound.pid"
ICON_PATH: Path = PEON_DIR / "docs" / "peon-icon.png"

# ---------------------------------------------------------------------------
# Cursor IDE event name mapping
# ---------------------------------------------------------------------------
# Cursor sends lowercase camelCase event names via its Third-party skills
# (Claude Code compatibility) mode. Map them to the PascalCase names used
# internally. Claude Code's own PascalCase names pass through unchanged.
_CURSOR_EVENT_MAP: Dict[str, str] = {
    "sessionStart": "SessionStart",
    "sessionEnd": "SessionStart",
    "beforeSubmitPrompt": "UserPromptSubmit",
    "stop": "Stop",
    "preToolUse": "UserPromptSubmit",
    "postToolUse": "Stop",
    "subagentStop": "Stop",
    "preCompact": "Stop",
}

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
# Kill previous / save sound PID
# ---------------------------------------------------------------------------

def _kill_previous_sound() -> None:
    """Kill any previously playing peon-ping sound process."""
    try:
        if SOUND_PID_FILE.exists():
            old_pid_str = SOUND_PID_FILE.read_text().strip()
            if old_pid_str:
                old_pid = int(old_pid_str)
                try:
                    os.kill(old_pid, signal.SIGTERM)
                except (OSError, ProcessLookupError):
                    pass
            SOUND_PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def _save_sound_pid(pid: int) -> None:
    """Save a sound process PID for later cleanup."""
    try:
        SOUND_PID_FILE.write_text(str(pid))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Audio playback
# ---------------------------------------------------------------------------

def play_sound(file_path: Path, volume: float) -> None:
    """Play *file_path* in the background at the given *volume* (0.0 - 1.0)."""
    _kill_previous_sound()

    def _play() -> None:
        if PLATFORM == "mac":
            _play_mac(file_path, volume)
        elif PLATFORM in ("wsl", "windows"):
            _play_windows(file_path, volume)
        elif PLATFORM in ("devcontainer", "ssh"):
            _play_relay(file_path, volume)
        elif PLATFORM == "linux":
            _play_linux(file_path, volume)

    thread = threading.Thread(target=_play, daemon=True)
    thread.start()


def _play_mac(file_path: Path, volume: float) -> None:
    """Play via macOS ``afplay``."""
    try:
        proc = subprocess.Popen(
            ["afplay", "-v", str(volume), str(file_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _save_sound_pid(proc.pid)
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
        proc = subprocess.Popen(
            [ps_exe, "-NoProfile", "-NonInteractive", "-Command", powershell_script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _save_sound_pid(proc.pid)
    except Exception:
        pass


def _play_relay(file_path: Path, volume: float) -> None:
    """Play via HTTP relay for SSH/devcontainer environments."""
    relay_host_default = (
        "host.docker.internal" if PLATFORM == "devcontainer" else "localhost"
    )
    relay_host: str = os.environ.get("PEON_RELAY_HOST", relay_host_default)
    relay_port: str = os.environ.get("PEON_RELAY_PORT", "19998")

    # Send relative path from PEON_DIR
    rel_path = str(file_path).replace(str(PEON_DIR) + os.sep, "").replace("\\", "/")
    encoded_path = urllib.parse.quote(rel_path)
    url = f"http://{relay_host}:{relay_port}/play?file={encoded_path}"

    try:
        req = urllib.request.Request(url, headers={"X-Volume": str(volume)})
        if os.environ.get("PEON_TEST") == "1":
            urllib.request.urlopen(req, timeout=5)
        else:
            # Fire-and-forget in background
            threading.Thread(
                target=lambda: urllib.request.urlopen(req, timeout=5),
                daemon=True,
            ).start()
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
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            _save_sound_pid(proc.pid)
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
            _notify_mac(msg, title, color)
        elif PLATFORM in ("wsl", "windows"):
            _notify_windows(msg, title, color)
        elif PLATFORM in ("devcontainer", "ssh"):
            _notify_relay(msg, title, color)
        elif PLATFORM == "linux":
            _notify_linux(msg, title, color)

    thread = threading.Thread(target=_notify, daemon=True)
    thread.start()


def _notify_mac(msg: str, title: str, color: str) -> None:
    """Send notification on macOS.

    Uses terminal-native escape sequences where supported (iTerm2, Kitty).
    Falls back to terminal-notifier (with peon icon) or osascript.
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
            # Prefer terminal-notifier with icon if available
            if shutil.which("terminal-notifier") and ICON_PATH.exists():
                subprocess.Popen(
                    [
                        "terminal-notifier",
                        "-title", title,
                        "-message", msg,
                        "-appIcon", str(ICON_PATH),
                        "-group", "peon-ping",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
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

    # Resolve icon path for Windows
    icon_win_path = ""
    if ICON_PATH.exists():
        if PLATFORM == "wsl":
            try:
                result = subprocess.run(
                    ["wslpath", "-w", str(ICON_PATH)],
                    capture_output=True, text=True,
                )
                icon_win_path = result.stdout.strip()
            except Exception:
                pass
        else:
            icon_win_path = str(ICON_PATH.resolve())

    # Determine temp dir for popup slot stacking
    slot_dir_expr_ps = "$env:TEMP\\peon-ping-popups"

    # Build icon block for PowerShell
    icon_block = ""
    if icon_win_path:
        icon_ps_path = icon_win_path.replace("'", "''")
        icon_block = f"""
            $iconLeft = 10
            $iconSize = 60
            if (Test-Path '{icon_ps_path}') {{
              $pb = New-Object System.Windows.Forms.PictureBox
              $pb.Image = [System.Drawing.Image]::FromFile('{icon_ps_path}')
              $pb.SizeMode = 'Zoom'
              $pb.Size = New-Object System.Drawing.Size($iconSize, $iconSize)
              $pb.Location = New-Object System.Drawing.Point($iconLeft, 10)
              $pb.BackColor = [System.Drawing.Color]::Transparent
              $form.Controls.Add($pb)
              $label = New-Object System.Windows.Forms.Label
              $label.Location = New-Object System.Drawing.Point(($iconLeft + $iconSize + 5), 0)
              $label.Size = New-Object System.Drawing.Size((500 - $iconLeft - $iconSize - 15), 80)
            }} else {{
              $label = New-Object System.Windows.Forms.Label
              $label.Dock = 'Fill'
            }}"""
    else:
        icon_block = """
            $label = New-Object System.Windows.Forms.Label
            $label.Dock = 'Fill'"""

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
            {icon_block}
            $label.Text = '{msg_escaped}'
            $label.ForeColor = [System.Drawing.Color]::White
            $label.Font = New-Object System.Drawing.Font('Segoe UI', 16, [System.Drawing.FontStyle]::Bold)
            $label.TextAlign = 'MiddleCenter'
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


def _notify_relay(msg: str, title: str, color: str) -> None:
    """Send notification via HTTP relay for SSH/devcontainer environments."""
    relay_host_default = (
        "host.docker.internal" if PLATFORM == "devcontainer" else "localhost"
    )
    relay_host: str = os.environ.get("PEON_RELAY_HOST", relay_host_default)
    relay_port: str = os.environ.get("PEON_RELAY_PORT", "19998")

    url = f"http://{relay_host}:{relay_port}/notify"
    payload = json.dumps({"title": title, "message": msg, "color": color}).encode("utf-8")

    try:
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


def _notify_linux(msg: str, title: str, color: str) -> None:
    """Send notification on Linux via ``notify-send``."""
    if shutil.which("notify-send") is None:
        return

    urgency = "critical" if color == "red" else "normal"

    cmd: List[str] = ["notify-send", f"--urgency={urgency}"]
    if ICON_PATH.exists():
        cmd.append(f"--icon={ICON_PATH}")
    cmd.extend([title, msg])

    try:
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Mobile push notifications (ntfy / pushover / telegram)
# ---------------------------------------------------------------------------

def send_mobile_notification(msg: str, title: str, color: str, config: dict) -> None:
    """Send push notification to phone via ntfy.sh, Pushover, or Telegram.

    Runs in a background thread to avoid blocking the hook.
    """
    mobile_cfg: dict = config.get("mobile_notify", {})
    if not mobile_cfg or not mobile_cfg.get("enabled", True):
        return
    service: str = mobile_cfg.get("service", "")
    if not service:
        return

    def _send() -> None:
        # Map color to priority
        priority_map = {"red": "high", "yellow": "default", "blue": "low"}
        priority = priority_map.get(color, "default")

        try:
            if service == "ntfy":
                _mobile_ntfy(msg, title, priority, mobile_cfg)
            elif service == "pushover":
                _mobile_pushover(msg, title, priority, mobile_cfg)
            elif service == "telegram":
                _mobile_telegram(msg, title, mobile_cfg)
        except Exception:
            pass

    thread = threading.Thread(target=_send, daemon=True)
    thread.start()


def _mobile_ntfy(msg: str, title: str, priority: str, cfg: dict) -> None:
    """Send via ntfy.sh."""
    topic: str = cfg.get("topic", "")
    if not topic:
        return
    server: str = cfg.get("server", "https://ntfy.sh")
    token: str = cfg.get("token", "")

    url = f"{server}/{topic}"
    data = msg.encode("utf-8")
    headers: Dict[str, str] = {
        "Title": title,
        "Priority": priority,
        "Tags": "video_game",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, data=data, headers=headers)
    urllib.request.urlopen(req, timeout=10)


def _mobile_pushover(msg: str, title: str, priority: str, cfg: dict) -> None:
    """Send via Pushover."""
    user_key: str = cfg.get("user_key", "")
    app_token: str = cfg.get("app_token", "")
    if not user_key or not app_token:
        return

    po_priority = 0
    if priority == "high":
        po_priority = 1
    elif priority == "low":
        po_priority = -1

    data = urllib.parse.urlencode({
        "token": app_token,
        "user": user_key,
        "title": title,
        "message": msg,
        "priority": str(po_priority),
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.pushover.net/1/messages.json",
        data=data,
    )
    urllib.request.urlopen(req, timeout=10)


def _mobile_telegram(msg: str, title: str, cfg: dict) -> None:
    """Send via Telegram Bot API."""
    bot_token: str = cfg.get("bot_token", "")
    chat_id: str = cfg.get("chat_id", "")
    if not bot_token or not chat_id:
        return

    text = f"{title}\n{msg}"
    url = (
        f"https://api.telegram.org/bot{bot_token}/sendMessage"
        f"?chat_id={urllib.parse.quote(chat_id)}"
        f"&text={urllib.parse.quote(text)}"
    )
    urllib.request.urlopen(url, timeout=10)


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
        # WSL / Windows / devcontainer / ssh: cannot detect or too slow
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
        # Windows cp1252 can't encode characters like \u25cf (bullet).
        # Write raw UTF-8 bytes directly to the underlying buffer so the
        # terminal (which understands UTF-8) renders the title correctly.
        sys.stdout.buffer.write(escape_sequence.encode("utf-8"))
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# iTerm2 tab color (OSC 6)
# ---------------------------------------------------------------------------

def set_tab_color(status: str, config: dict) -> None:
    """Set iTerm2 tab color based on status. Only works in iTerm2."""
    if os.environ.get("TERM_PROGRAM") != "iTerm.app":
        return

    tab_color_cfg: dict = config.get("tab_color", {})
    # Default enabled unless explicitly disabled
    if str(tab_color_cfg.get("enabled", True)).lower() == "false":
        return

    default_colors: Dict[str, List[int]] = {
        "ready":          [65, 115, 80],   # muted green
        "working":        [130, 105, 50],  # muted amber
        "done":           [65, 100, 140],  # muted blue
        "needs_approval": [150, 70, 70],   # muted red
    }
    custom_colors: dict = tab_color_cfg.get("colors", {})
    colors = {k: custom_colors.get(k, v) for k, v in default_colors.items()}

    status_key = status.replace(" ", "_") if status else ""
    if status_key not in colors:
        return

    rgb = colors[status_key]
    try:
        # Write to /dev/tty so escape sequences reach the terminal directly.
        # Claude Code captures hook stdout, so plain write would be swallowed.
        with open("/dev/tty", "w") as tty:
            tty.write(f"\033]6;1;bg;red;brightness;{rgb[0]}\a")
            tty.write(f"\033]6;1;bg;green;brightness;{rgb[1]}\a")
            tty.write(f"\033]6;1;bg;blue;brightness;{rgb[2]}\a")
            tty.flush()
    except Exception:
        pass


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

def _safe_print(text: str) -> None:
    """Print text, replacing unencodable characters on narrow-encoding consoles (e.g. Windows cp1252)."""
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "utf-8"
        print(text.encode(encoding, errors="replace").decode(encoding, errors="replace"))


def _list_pack_names() -> List[str]:
    """Return sorted list of installed pack directory names with manifests."""
    packs_dir = PEON_DIR / "packs"
    if not packs_dir.is_dir():
        return []
    names: List[str] = []
    for d in sorted(os.listdir(packs_dir)):
        pack_path = packs_dir / d
        if pack_path.is_dir() and (
            (pack_path / "openpeon.json").exists()
            or (pack_path / "manifest.json").exists()
        ):
            names.append(d)
    return names


def _load_manifest(pack_name: str) -> Optional[dict]:
    """Load openpeon.json or manifest.json for a pack."""
    pack_dir = PEON_DIR / "packs" / pack_name
    for manifest_name in ("openpeon.json", "manifest.json"):
        manifest_path = pack_dir / manifest_name
        if manifest_path.exists():
            try:
                with open(manifest_path, "r", encoding="utf-8") as fh:
                    return json.load(fh)
            except Exception:
                continue
    return None


def pick_sound(pack_name: str, category: str, state: dict) -> Optional[Path]:
    """Pick a random sound file for *category*, avoiding the last-played file.

    Supports both ``openpeon.json`` (CESP standard) and legacy
    ``manifest.json`` formats.  Updates ``state['last_played']`` in-place.
    """
    pack_dir = PEON_DIR / "packs" / pack_name
    manifest = _load_manifest(pack_name)

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
        candidate = os.path.realpath(os.path.join(str(pack_dir), file_ref))
    else:
        candidate = os.path.realpath(os.path.join(str(pack_dir), "sounds", file_ref))

    # Path safety: reject paths outside the pack directory
    pack_root = os.path.realpath(str(pack_dir)) + os.sep
    if not candidate.startswith(pack_root):
        return None

    sound_path = Path(candidate)
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
            _safe_print(
                f"peon-ping update available: {current_version} \u2192 {new_version} "
                f"\u2014 run: curl -fsSL "
                f"https://raw.githubusercontent.com/bwright2810/peon-ping/main/install.sh | bash"
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

        silent_window = float(config.get("silent_window_seconds", 0))
        if silent_window > 0:
            prompt_starts = state.get("prompt_start_times", {})
            prompt_starts[session_id] = time.time()
            state_updates["prompt_start_times"] = prompt_starts

    elif event == "Stop":
        category = "task.complete"
        silent = False
        silent_window = float(config.get("silent_window_seconds", 0))
        if silent_window > 0:
            prompt_starts = state.get("prompt_start_times", {})
            # start_time=0 when no prior prompt; 0 is falsy so short-circuits to not-silent
            start_time = prompt_starts.pop(session_id, 0)
            if start_time and (time.time() - start_time) < silent_window:
                silent = True
            state_updates["prompt_start_times"] = prompt_starts
        status = "done"
        if not silent:
            marker = "\u25cf "
            notify = True
            notify_color = "blue"
            msg = f"{project}  \u2014  Task complete"
        else:
            category = ""

    elif event == "Notification":
        if notification_type == "permission_prompt":
            # Sound is handled by the PermissionRequest event; only set tab title
            status = "needs approval"
            marker = "\u25cf "
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
    raw_event: str = event_data.get("hook_event_name", "")
    # Cursor IDE sends lowercase camelCase names; normalize to PascalCase
    event: str = _CURSOR_EVENT_MAP.get(raw_event, raw_event)

    notification_type: str = event_data.get("notification_type", "")

    # Cursor sends workspace_roots[] instead of cwd
    workspace_roots: list = event_data.get("workspace_roots", [])
    cwd: str = event_data.get("cwd", "") or (workspace_roots[0] if workspace_roots else "")

    # Cursor sends conversation_id instead of session_id
    session_id: str = event_data.get("session_id", "") or event_data.get("conversation_id", "")

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

    if pack_rotation and config.get("pack_rotation_mode", "random") != "off":
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

    # --- Debounce rapid Stop events (5-second window) ---
    if event == "Stop":
        now = time.time()
        last_stop = state.get("last_stop_time", 0)
        if now - last_stop < 5:
            category = ""
            notify = False
        state["last_stop_time"] = now
        state_dirty = True

    # --- Suppress sounds during session replay (claude -c) ---
    # When continuing a session, Claude fires SessionStart then immediately
    # replays old events. Suppress all sounds within 3s of SessionStart.
    now = time.time()
    if event == "SessionStart":
        session_starts = state.get("session_start_times", {})
        session_starts[session_id] = now
        state["session_start_times"] = session_starts
        state_dirty = True
    elif category:
        session_starts = state.get("session_start_times", {})
        start_time = session_starts.get(session_id, 0)
        if start_time and (now - start_time) < 3:
            category = ""
            notify = False

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
                "peon-ping: sounds paused \u2014 run 'peon resume' "
                "or '/peon-ping-toggle' to unpause",
                file=sys.stderr,
            )
        # Relay health check guidance for devcontainer/ssh
        if PLATFORM in ("devcontainer", "ssh"):
            relay_host_default = (
                "host.docker.internal" if PLATFORM == "devcontainer" else "localhost"
            )
            relay_host = os.environ.get("PEON_RELAY_HOST", relay_host_default)
            relay_port = os.environ.get("PEON_RELAY_PORT", "19998")
            try:
                urllib.request.urlopen(
                    f"http://{relay_host}:{relay_port}/health", timeout=2
                )
            except Exception:
                print(
                    f"peon-ping: {PLATFORM} detected but audio relay not reachable "
                    f"at {relay_host}:{relay_port}",
                    file=sys.stderr,
                )
                if PLATFORM == "ssh":
                    print(
                        "peon-ping: on your LOCAL machine, run: peon relay",
                        file=sys.stderr,
                    )
                    print(
                        "peon-ping: then reconnect with: ssh -R 19998:localhost:19998 <host>",
                        file=sys.stderr,
                    )
                else:
                    print(
                        "peon-ping: run 'peon relay' on your host machine to enable sounds",
                        file=sys.stderr,
                    )

    # --- Tab title ---
    title = f"{marker}{project}: {status}"
    if title.strip():
        set_terminal_title(title)

    # --- iTerm2 tab color ---
    set_tab_color(status, config)

    # --- Play sound ---
    volume = float(config.get("volume", 0.5))
    if sound_file and sound_file.exists():
        play_sound(sound_file, volume)

    # --- Desktop notification ---
    notifications_enabled = str(config.get("desktop_notifications", False)).lower() != "false"
    if notify and not paused and notifications_enabled:
        if not terminal_is_focused():
            send_notification(msg, title, notify_color or "red")

    # --- Mobile push notification (always sends when configured, regardless of focus) ---
    mobile_cfg = config.get("mobile_notify", {})
    mobile_on = bool(
        mobile_cfg and mobile_cfg.get("service") and mobile_cfg.get("enabled", True)
    )
    if notify and not paused and mobile_on:
        send_mobile_notification(msg, title, notify_color or "red", config)

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

    # Show desktop notification status
    config = load_config_safe()
    desktop_notif = str(config.get("desktop_notifications", False)).lower() != "false"
    print(f"peon-ping: desktop notifications {'on' if desktop_notif else 'off'}")

    # Show mobile notification status
    mobile_cfg = config.get("mobile_notify", {})
    if mobile_cfg and mobile_cfg.get("service"):
        enabled = mobile_cfg.get("enabled", True)
        service = mobile_cfg.get("service", "?")
        print(f"peon-ping: mobile notifications {'on' if enabled else 'off'} ({service})")
    else:
        print("peon-ping: mobile notifications not configured")

    sys.exit(0)


def handle_notifications(args: List[str]) -> None:
    """Toggle desktop notifications on/off."""
    if not args:
        print("Usage: peon notifications <on|off>", file=sys.stderr)
        sys.exit(1)

    sub = args[0]
    if sub == "on":
        config = load_config_safe()
        config["desktop_notifications"] = True
        save_config(config)
        print("peon-ping: desktop notifications on")
    elif sub == "off":
        config = load_config_safe()
        config["desktop_notifications"] = False
        save_config(config)
        print("peon-ping: desktop notifications off")
    else:
        print("Usage: peon notifications <on|off>", file=sys.stderr)
        sys.exit(1)
    sys.exit(0)


def handle_packs_cmd(args: List[str]) -> None:
    """Handle 'packs list|use|next|remove' subcommands."""
    if not args:
        print("Usage: peon packs <list|use|next|remove>", file=sys.stderr)
        sys.exit(1)

    sub = args[0]

    if sub == "list":
        active = load_config_safe().get("active_pack", "peon")
        for name in _list_pack_names():
            manifest = _load_manifest(name)
            if manifest:
                display = manifest.get("display_name", name)
                marker_str = " *" if name == active else ""
                _safe_print(f"  {name:24s} {display}{marker_str}")
        sys.exit(0)

    elif sub == "use":
        if len(args) < 2:
            print("Usage: peon packs use <name>", file=sys.stderr)
            sys.exit(1)
        pack_arg = args[1]
        names = _list_pack_names()
        if pack_arg not in names:
            print(f'Error: pack "{pack_arg}" not found.', file=sys.stderr)
            print(f'Available packs: {", ".join(names)}', file=sys.stderr)
            sys.exit(1)
        config = load_config_safe()
        config["active_pack"] = pack_arg
        save_config(config)
        manifest = _load_manifest(pack_arg)
        display = manifest.get("display_name", pack_arg) if manifest else pack_arg
        print(f"peon-ping: switched to {pack_arg} ({display})")
        sys.exit(0)

    elif sub == "next":
        config = load_config_safe()
        active = config.get("active_pack", "peon")
        names = _list_pack_names()
        if not names:
            print("Error: no packs found", file=sys.stderr)
            sys.exit(1)
        try:
            idx = names.index(active)
            next_pack = names[(idx + 1) % len(names)]
        except ValueError:
            next_pack = names[0]
        config["active_pack"] = next_pack
        save_config(config)
        manifest = _load_manifest(next_pack)
        display = manifest.get("display_name", next_pack) if manifest else next_pack
        print(f"peon-ping: switched to {next_pack} ({display})")
        sys.exit(0)

    elif sub == "remove":
        if len(args) < 2:
            print("Usage: peon packs remove <pack1,pack2,...>", file=sys.stderr)
            print("Run 'peon packs list' to see installed packs.", file=sys.stderr)
            sys.exit(1)

        remove_arg = args[1]
        config = load_config_safe()
        active = config.get("active_pack", "peon")
        installed = _list_pack_names()
        requested = [p.strip() for p in remove_arg.split(",") if p.strip()]

        errors: List[str] = []
        valid: List[str] = []
        for p in requested:
            if p not in installed:
                errors.append(f'Pack "{p}" not found.')
            elif p == active:
                errors.append(
                    f'Cannot remove "{p}" \u2014 it is the active pack. '
                    "Switch first with: peon packs use <other>"
                )
            else:
                valid.append(p)

        if errors:
            for e in errors:
                print(e, file=sys.stderr)
            sys.exit(1)

        remaining = len(installed) - len(valid)
        if remaining < 1:
            print("Cannot remove all packs \u2014 at least 1 must remain.", file=sys.stderr)
            sys.exit(1)

        if not valid:
            sys.exit(0)

        # Confirm removal
        pack_count = len(valid)
        try:
            confirm = input(f"Remove {pack_count} pack(s)? [y/N] ")
        except EOFError:
            confirm = ""
        if confirm.lower() not in ("y", "yes"):
            print("Cancelled.")
            sys.exit(0)

        packs_dir = PEON_DIR / "packs"
        for pack in valid:
            pack_path = packs_dir / pack
            if pack_path.is_dir():
                shutil.rmtree(pack_path)
                print(f"Removed {pack}")

        # Clean pack_rotation in config
        rotation = config.get("pack_rotation", [])
        if rotation:
            config["pack_rotation"] = [p for p in rotation if p not in valid]
            save_config(config)

        sys.exit(0)

    else:
        print("Usage: peon packs <list|use|next|remove>", file=sys.stderr)
        sys.exit(1)


def handle_mobile(args: List[str]) -> None:
    """Handle 'mobile ntfy|pushover|telegram|on|off|status|test' subcommands."""
    if not args:
        _print_mobile_usage()
        sys.exit(1)

    sub = args[0]

    if sub == "ntfy":
        if len(args) < 2:
            print("Usage: peon mobile ntfy <topic> [--server=URL] [--token=TOKEN]", file=sys.stderr)
            print("", file=sys.stderr)
            print("Setup:", file=sys.stderr)
            print("  1. Install ntfy app on your phone (ntfy.sh)", file=sys.stderr)
            print("  2. Subscribe to your topic in the app", file=sys.stderr)
            print("  3. Run: peon mobile ntfy my-unique-topic", file=sys.stderr)
            sys.exit(1)

        topic = args[1]
        server = "https://ntfy.sh"
        token = ""
        for arg in args[2:]:
            if arg.startswith("--server="):
                server = arg.split("=", 1)[1]
            elif arg.startswith("--token="):
                token = arg.split("=", 1)[1]

        config = load_config_safe()
        config["mobile_notify"] = {
            "enabled": True,
            "service": "ntfy",
            "topic": topic,
            "server": server,
            "token": token,
        }
        save_config(config)
        print("peon-ping: mobile notifications enabled via ntfy")
        print(f"  Topic:  {topic}")
        print(f"  Server: {server}")
        print()
        print(f"Install the ntfy app and subscribe to '{topic}'")

        # Send test notification
        try:
            test_url = f"{server}/{topic}"
            data = "Mobile notifications connected!".encode("utf-8")
            req = urllib.request.Request(
                test_url, data=data,
                headers={"Title": "peon-ping", "Tags": "video_game"},
            )
            urllib.request.urlopen(req, timeout=10)
            print("Test notification sent!")
        except Exception:
            print("Warning: could not reach ntfy server")
        sys.exit(0)

    elif sub == "pushover":
        if len(args) < 3:
            print("Usage: peon mobile pushover <user_key> <app_token>", file=sys.stderr)
            sys.exit(1)
        user_key = args[1]
        app_token = args[2]

        config = load_config_safe()
        config["mobile_notify"] = {
            "enabled": True,
            "service": "pushover",
            "user_key": user_key,
            "app_token": app_token,
        }
        save_config(config)
        print("peon-ping: mobile notifications enabled via Pushover")
        sys.exit(0)

    elif sub == "telegram":
        if len(args) < 3:
            print("Usage: peon mobile telegram <bot_token> <chat_id>", file=sys.stderr)
            sys.exit(1)
        bot_token = args[1]
        chat_id = args[2]

        config = load_config_safe()
        config["mobile_notify"] = {
            "enabled": True,
            "service": "telegram",
            "bot_token": bot_token,
            "chat_id": chat_id,
        }
        save_config(config)
        print("peon-ping: mobile notifications enabled via Telegram")
        sys.exit(0)

    elif sub == "off":
        config = load_config_safe()
        mobile_cfg = config.get("mobile_notify", {})
        mobile_cfg["enabled"] = False
        config["mobile_notify"] = mobile_cfg
        save_config(config)
        print("peon-ping: mobile notifications disabled")
        sys.exit(0)

    elif sub == "on":
        config = load_config_safe()
        mobile_cfg = config.get("mobile_notify", {})
        if not mobile_cfg.get("service"):
            print("peon-ping: no mobile service configured. Run: peon mobile ntfy <topic>")
            sys.exit(1)
        mobile_cfg["enabled"] = True
        config["mobile_notify"] = mobile_cfg
        save_config(config)
        print("peon-ping: mobile notifications enabled")
        sys.exit(0)

    elif sub == "status":
        config = load_config_safe()
        mobile_cfg = config.get("mobile_notify", {})
        if not mobile_cfg or not mobile_cfg.get("service"):
            print("peon-ping: mobile notifications not configured")
            print("  Run: peon mobile ntfy <topic>")
        else:
            enabled = mobile_cfg.get("enabled", True)
            service = mobile_cfg.get("service", "?")
            status_str = "on" if enabled else "off"
            print(f"peon-ping: mobile notifications {status_str} ({service})")
            if service == "ntfy":
                print(f'  Topic:  {mobile_cfg.get("topic", "?")}')
                print(f'  Server: {mobile_cfg.get("server", "https://ntfy.sh")}')
            elif service == "pushover":
                user_key = mobile_cfg.get("user_key", "?")
                print(f"  User:   {user_key[:8]}...")
            elif service == "telegram":
                print(f'  Chat:   {mobile_cfg.get("chat_id", "?")}')
        sys.exit(0)

    elif sub == "test":
        config = load_config_safe()
        mobile_cfg = config.get("mobile_notify", {})
        if (
            not mobile_cfg
            or not mobile_cfg.get("service")
            or not mobile_cfg.get("enabled", True)
        ):
            print("peon-ping: mobile not configured", file=sys.stderr)
            sys.exit(1)
        send_mobile_notification(
            "Test notification from peon-ping", "peon-ping", "blue", config
        )
        time.sleep(1)  # wait for background thread
        print("peon-ping: test notification sent")
        sys.exit(0)

    else:
        _print_mobile_usage()
        sys.exit(1)


def _print_mobile_usage() -> None:
    """Print mobile subcommand usage."""
    print("Usage: peon mobile <ntfy|pushover|telegram|on|off|status|test>", file=sys.stderr)
    print("", file=sys.stderr)
    print("Quick start (free, no account needed):", file=sys.stderr)
    print("  1. Install ntfy app on your phone (ntfy.sh)", file=sys.stderr)
    print("  2. Subscribe to a unique topic in the app", file=sys.stderr)
    print("  3. Run: peon mobile ntfy <your-topic>", file=sys.stderr)
    print("", file=sys.stderr)
    print("Commands:", file=sys.stderr)
    print("  ntfy <topic>                Set up ntfy.sh notifications", file=sys.stderr)
    print("  pushover <user> <app>       Set up Pushover notifications", file=sys.stderr)
    print("  telegram <bot_token> <chat>  Set up Telegram notifications", file=sys.stderr)
    print("  on                          Enable mobile notifications", file=sys.stderr)
    print("  off                         Disable mobile notifications", file=sys.stderr)
    print("  status                      Show current mobile config", file=sys.stderr)
    print("  test                        Send a test notification", file=sys.stderr)


def handle_relay(args: List[str]) -> None:
    """Delegate to relay.sh."""
    relay_script = PEON_DIR / "relay.sh"
    if not relay_script.exists():
        print(f"Error: relay.sh not found at {PEON_DIR}", file=sys.stderr)
        print("Re-run the installer to get the relay script.", file=sys.stderr)
        sys.exit(1)
    try:
        os.execvp("bash", ["bash", str(relay_script)] + args)
    except Exception as exc:
        print(f"Error launching relay: {exc}", file=sys.stderr)
        sys.exit(1)


def handle_preview(args: List[str]) -> None:
    """Preview sounds for a category in the active pack."""
    preview_cat = args[0] if args else "session.start"

    config = load_config_safe()
    volume = float(config.get("volume", 0.5))
    active_pack = config.get("active_pack", "peon")
    pack_dir = PEON_DIR / "packs" / active_pack

    manifest = _load_manifest(active_pack)
    if not manifest:
        print(f'peon-ping: no manifest found for pack "{active_pack}".', file=sys.stderr)
        sys.exit(1)

    display_name = manifest.get("display_name", active_pack)
    categories = manifest.get("categories", {})

    # --list: show all categories and sound counts
    if preview_cat == "--list":
        print(f"peon-ping: categories in {display_name}")
        print()
        for cat in sorted(categories):
            sounds = categories[cat].get("sounds", [])
            count = len(sounds)
            unit = "sound" if count == 1 else "sounds"
            print(f"  {cat:24s} {count} {unit}")
        sys.exit(0)

    cat_data = categories.get(preview_cat)
    if not cat_data or not cat_data.get("sounds"):
        avail = ", ".join(sorted(c for c in categories if categories[c].get("sounds")))
        print(f'peon-ping: category "{preview_cat}" not found in pack "{active_pack}".', file=sys.stderr)
        print(f"Available categories: {avail}", file=sys.stderr)
        sys.exit(1)

    print(f"peon-ping: previewing [{preview_cat}] from {display_name}")
    print()

    sounds = cat_data["sounds"]
    for sound_entry in sounds:
        file_ref = sound_entry.get("file", "")
        label = sound_entry.get("label", file_ref)

        if "/" in file_ref:
            fpath = os.path.realpath(os.path.join(str(pack_dir), file_ref))
        else:
            fpath = os.path.realpath(os.path.join(str(pack_dir), "sounds", file_ref))

        # Path safety check
        pack_root = os.path.realpath(str(pack_dir)) + os.sep
        if not fpath.startswith(pack_root):
            continue

        if os.path.isfile(fpath):
            _safe_print(f"  \u25b6 {label}")
            play_sound(Path(fpath), volume)
            time.sleep(1.5)  # wait for sound to play before next
            time.sleep(0.3)  # extra gap between sounds

    sys.exit(0)


# Legacy CLI handlers (kept for backward compatibility with --flag style)

def handle_packs_legacy() -> None:
    """List available sound packs (marks the active one with ``*``). Legacy --packs."""
    active = load_config_safe().get("active_pack", "peon")
    for name in _list_pack_names():
        manifest = _load_manifest(name)
        if manifest:
            display = manifest.get("display_name", name)
            marker_str = " *" if name == active else ""
            _safe_print(f"  {name:24s} {display}{marker_str}")
    sys.exit(0)


def handle_pack_legacy(pack_name: Optional[str]) -> None:
    """Switch to *pack_name*, or cycle to next. Legacy --pack."""
    if not pack_name:
        # Cycle to next
        config = load_config_safe()
        active = config.get("active_pack", "peon")
        names = _list_pack_names()
        if not names:
            print("Error: no packs found", file=sys.stderr)
            sys.exit(1)
        try:
            idx = names.index(active)
            next_pack = names[(idx + 1) % len(names)]
        except ValueError:
            next_pack = names[0]
        config["active_pack"] = next_pack
        save_config(config)
        manifest = _load_manifest(next_pack)
        display = manifest.get("display_name", next_pack) if manifest else next_pack
        print(f"peon-ping: switched to {next_pack} ({display})")
    else:
        names = _list_pack_names()
        if pack_name not in names:
            print(f'Error: pack "{pack_name}" not found.', file=sys.stderr)
            print(f'Available packs: {", ".join(names)}', file=sys.stderr)
            sys.exit(1)
        config = load_config_safe()
        config["active_pack"] = pack_name
        save_config(config)
        manifest = _load_manifest(pack_name)
        display = manifest.get("display_name", pack_name) if manifest else pack_name
        print(f"peon-ping: switched to {pack_name} ({display})")
    sys.exit(0)


def handle_help() -> None:
    """Print usage information."""
    print(
        "Usage: peon <command>\n"
        "\n"
        "Commands:\n"
        "  pause                Mute sounds\n"
        "  resume               Unmute sounds\n"
        "  toggle               Toggle mute on/off\n"
        "  status               Check if paused or active\n"
        "  notifications on     Enable desktop notifications\n"
        "  notifications off    Disable desktop notifications\n"
        "  preview [category]   Play all sounds from a category (default: session.start)\n"
        "  preview --list       List all categories and sound counts in the active pack\n"
        "                       Categories: session.start, task.acknowledge, task.complete,\n"
        "                       task.error, input.required, resource.limit, user.spam\n"
        "  help                 Show this help\n"
        "\n"
        "Pack management:\n"
        "  packs list           List installed sound packs\n"
        "  packs use <name>     Switch to a specific pack\n"
        "  packs next           Cycle to the next pack\n"
        "  packs remove <p1,p2> Remove specific packs\n"
        "\n"
        "Mobile notifications:\n"
        "  mobile ntfy <topic>  Set up ntfy.sh push notifications\n"
        "  mobile off           Disable mobile notifications\n"
        "  mobile status        Show mobile config\n"
        "  mobile test          Send a test notification\n"
        "\n"
        "Relay (SSH/devcontainer/Codespaces):\n"
        "  relay [--port=N]     Start audio relay on your local machine\n"
        "  relay --daemon       Start relay in background\n"
        "  relay --stop         Stop background relay\n"
        "  relay --status       Check if relay is running"
    )
    sys.exit(0)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main() -> None:
    # Manual argument parsing to exactly match the bash ``case`` behaviour.
    args = sys.argv[1:]

    if not args:
        # If stdin is a terminal (not a pipe from Claude Code), the user
        # likely ran `peon` bare — show help instead of blocking on read.
        if sys.stdin.isatty():
            print("Usage: peon <command>")
            print()
            print("Run 'peon help' for full command list.")
            return
        # No CLI flags — act as hook handler (read event from stdin)
        handle_hook_event()
        return

    cmd = args[0]

    # --- Positional subcommands (matching peon.sh) ---
    if cmd == "pause":
        handle_pause()
    elif cmd == "resume":
        handle_resume()
    elif cmd == "toggle":
        handle_toggle()
    elif cmd == "status":
        handle_status()
    elif cmd == "notifications":
        handle_notifications(args[1:])
    elif cmd == "packs":
        handle_packs_cmd(args[1:])
    elif cmd == "mobile":
        handle_mobile(args[1:])
    elif cmd == "relay":
        handle_relay(args[1:])
    elif cmd == "preview":
        handle_preview(args[1:])
    elif cmd in ("help", "--help", "-h"):
        handle_help()

    # --- Legacy --flag aliases for backward compatibility ---
    elif cmd == "--pause":
        handle_pause()
    elif cmd == "--resume":
        handle_resume()
    elif cmd == "--toggle":
        handle_toggle()
    elif cmd == "--status":
        handle_status()
    elif cmd == "--packs":
        handle_packs_legacy()
    elif cmd == "--pack":
        pack_arg = args[1] if len(args) > 1 else None
        handle_pack_legacy(pack_arg)

    elif cmd.startswith("--"):
        print(f"Unknown option: {cmd}", file=sys.stderr)
        print("Run 'peon help' for usage.", file=sys.stderr)
        sys.exit(1)
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        print("Run 'peon help' for usage.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
