#!/usr/bin/env python3
"""
peon-ping installer (cross-platform)

Works on Windows (cmd.exe / PowerShell), macOS, and Linux.
Supports both local-clone and curl-pipe installs.
Re-running updates core files while preserving user configuration.
"""

import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path


# All available sound packs (keep in sync with install.sh)
PACKS = (
    "acolyte_ru aom_greek glados peon peon_cz peon_es peon_fr peon_pl peon_ru "
    "peasant peasant_cz peasant_es peasant_fr peasant_ru ra2_kirov "
    "ra2_soviet_engineer sc_battlecruiser sc_firebat sc_kerrigan sc_medic "
    "sc_scv sc_tank sc_terran sc_vessel tf2_engineer wc2_peasant"
).split()

REPO_BASE = "https://raw.githubusercontent.com/PeonPing/peon-ping/main"


# ---------------------------------------------------------------------------
# Platform detection (mirrors peon.py)
# ---------------------------------------------------------------------------

def detect_platform() -> str:
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
    return "unknown"


PLATFORM = detect_platform()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def download(url: str, dest: Path) -> None:
    """Download *url* to *dest*."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=30) as resp:
        with open(dest, "wb") as fh:
            fh.write(resp.read())


def copy_if_exists(src: Path, dst: Path) -> bool:
    """Copy *src* to *dst* if *src* exists.  Returns success."""
    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return True
    return False


# ---------------------------------------------------------------------------
# Main installer
# ---------------------------------------------------------------------------

def main() -> None:
    local_mode = "--local" in sys.argv

    if local_mode:
        base_dir = Path.cwd() / ".claude"
    else:
        base_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude")))

    install_dir = base_dir / "hooks" / "peon-ping"
    settings_path = base_dir / "settings.json"

    # Detect local clone (script directory contains peon.sh or peon.py)
    script_dir = Path(__file__).resolve().parent
    is_local_clone = (script_dir / "peon.sh").exists() or (script_dir / "peon.py").exists()

    updating = (install_dir / "peon.sh").exists() or (install_dir / "peon.py").exists()

    if updating:
        print("=== peon-ping updater ===")
        print()
        print("Existing install found. Updating...")
    else:
        print("=== peon-ping installer ===")
        print()

    # --- Prerequisites ---
    if PLATFORM not in ("mac", "wsl", "windows", "linux"):
        print(f"Error: unsupported platform '{PLATFORM}'")
        sys.exit(1)

    if sys.version_info < (3, 6):
        print(f"Error: Python 3.6+ required, got {sys.version}")
        sys.exit(1)

    if PLATFORM == "mac":
        if shutil.which("afplay") is None:
            print("Error: afplay is required (should be built into macOS)")
            sys.exit(1)
    elif PLATFORM == "wsl":
        if shutil.which("powershell.exe") is None:
            print("Error: powershell.exe is required (should be available in WSL)")
            sys.exit(1)
        if shutil.which("wslpath") is None:
            print("Error: wslpath is required (should be built into WSL)")
            sys.exit(1)
    elif PLATFORM == "windows":
        if shutil.which("powershell") is None:
            print("Error: PowerShell is required (should be built into Windows 10+)")
            sys.exit(1)
    elif PLATFORM == "linux":
        linux_player = ""
        for cmd in ("pw-play", "paplay", "ffplay", "mpv", "aplay"):
            if shutil.which(cmd):
                linux_player = cmd
                break
        if not linux_player:
            print("Error: no supported audio player found.")
            print(
                "Install one of: pw-play (pipewire-audio), paplay (pulseaudio-utils), "
                "ffplay (ffmpeg), mpv, aplay (alsa-utils)"
            )
            sys.exit(1)
        print(f"Audio player: {linux_player}")
        if shutil.which("notify-send"):
            print("Desktop notifications: notify-send")
        else:
            print(
                "Warning: notify-send not found (libnotify-bin). "
                "Desktop notifications will be disabled."
            )

    if not base_dir.exists():
        if local_mode:
            print("Error: .claude/ not found in current directory. Is this a Claude Code project?")
        else:
            print(f"Error: {base_dir} not found. Is Claude Code installed?")
        sys.exit(1)

    # --- Create pack directories ---
    for pack in PACKS:
        (install_dir / "packs" / pack / "sounds").mkdir(parents=True, exist_ok=True)

    # --- Install / update core files ---
    if is_local_clone:
        print("\nInstalling from local clone...")

        # Copy packs
        src_packs = script_dir / "packs"
        if src_packs.exists():
            dst_packs = install_dir / "packs"
            # Copy each pack individually to preserve any user additions
            for item in src_packs.iterdir():
                if item.is_dir():
                    dst = dst_packs / item.name
                    if dst.exists():
                        shutil.rmtree(dst)
                    shutil.copytree(item, dst)

        # Copy core files
        for filename in ("peon.sh", "peon.py", "peon.bat", "completions.bash",
                         "completions.fish", "VERSION", "uninstall.sh"):
            src = script_dir / filename
            if src.exists():
                shutil.copy2(src, install_dir / filename)
                print(f"  Copied {filename}")

        # Copy config only on fresh install
        if not updating:
            copy_if_exists(script_dir / "config.json", install_dir / "config.json")
    else:
        print("\nDownloading from GitHub...")

        # Download core files
        for filename in ("peon.sh", "peon.py", "peon.bat", "completions.bash",
                         "completions.fish", "VERSION", "uninstall.sh"):
            try:
                download(f"{REPO_BASE}/{filename}", install_dir / filename)
                print(f"  Downloaded {filename}")
            except Exception as exc:
                print(f"  Warning: failed to download {filename}: {exc}")

        # Download manifests
        for pack in PACKS:
            try:
                download(
                    f"{REPO_BASE}/packs/{pack}/manifest.json",
                    install_dir / "packs" / pack / "manifest.json",
                )
            except Exception:
                print(f"  Warning: failed to download {pack}/manifest.json")

        # Download sound files referenced in manifests
        for pack in PACKS:
            manifest_path = install_dir / "packs" / pack / "manifest.json"
            if not manifest_path.exists():
                continue
            try:
                with open(manifest_path, "r", encoding="utf-8") as fh:
                    manifest = json.load(fh)
                seen: set = set()
                for cat in manifest.get("categories", {}).values():
                    for s in cat.get("sounds", []):
                        fname = s["file"]
                        if fname not in seen:
                            seen.add(fname)
                            try:
                                download(
                                    f"{REPO_BASE}/packs/{pack}/sounds/{fname}",
                                    install_dir / "packs" / pack / "sounds" / fname,
                                )
                            except Exception:
                                print(f"  Warning: failed to download {pack}/sounds/{fname}")
            except Exception:
                pass

        # Download config only on fresh install
        if not updating:
            try:
                download(f"{REPO_BASE}/config.json", install_dir / "config.json")
            except Exception:
                pass

    # Make peon.sh executable on Unix
    peon_sh = install_dir / "peon.sh"
    if peon_sh.exists() and os.name != "nt":
        peon_sh.chmod(peon_sh.stat().st_mode | 0o755)

    # --- Install skill (slash command) ---
    skill_dir = base_dir / "skills" / "peon-ping-toggle"
    skill_dir.mkdir(parents=True, exist_ok=True)

    if local_mode:
        hook_cmd = ".claude/hooks/peon-ping/peon.sh"
    else:
        hook_cmd = str(install_dir / "peon.sh")

    skill_src = script_dir / "skills" / "peon-ping-toggle" / "SKILL.md" if is_local_clone else None

    if skill_src and skill_src.exists():
        shutil.copy2(skill_src, skill_dir / "SKILL.md")
        if local_mode:
            skill_file = skill_dir / "SKILL.md"
            content = skill_file.read_text(encoding="utf-8")
            content = content.replace(
                'bash "${CLAUDE_CONFIG_DIR:-$HOME/.claude}"/hooks/peon-ping/peon.sh',
                f"bash {hook_cmd}",
            )
            skill_file.write_text(content, encoding="utf-8")
    elif not is_local_clone:
        try:
            download(f"{REPO_BASE}/skills/peon-ping-toggle/SKILL.md", skill_dir / "SKILL.md")
            if local_mode:
                skill_file = skill_dir / "SKILL.md"
                content = skill_file.read_text(encoding="utf-8")
                content = content.replace(
                    'bash "${CLAUDE_CONFIG_DIR:-$HOME/.claude}"/hooks/peon-ping/peon.sh',
                    f"bash {hook_cmd}",
                )
                skill_file.write_text(content, encoding="utf-8")
        except Exception:
            print("Warning: failed to download skill file")

    # --- Shell aliases (global install, Unix only) ---
    if not local_mode and os.name != "nt":
        alias_line = f'alias peon="bash {install_dir}/peon.sh"'
        for rcfile_path in (Path.home() / ".zshrc", Path.home() / ".bashrc"):
            if rcfile_path.exists():
                content = rcfile_path.read_text(encoding="utf-8")
                if "alias peon=" not in content:
                    with open(rcfile_path, "a", encoding="utf-8") as fh:
                        fh.write(f"\n# peon-ping quick controls\n{alias_line}\n")
                    print(f"Added peon alias to {rcfile_path.name}")

        # Tab completions
        completion_line = (
            f"[ -f {install_dir}/completions.bash ] && "
            f"source {install_dir}/completions.bash"
        )
        for rcfile_path in (Path.home() / ".zshrc", Path.home() / ".bashrc"):
            if rcfile_path.exists():
                content = rcfile_path.read_text(encoding="utf-8")
                if "peon-ping/completions.bash" not in content:
                    with open(rcfile_path, "a", encoding="utf-8") as fh:
                        fh.write(f"{completion_line}\n")
                    print(f"Added tab completion to {rcfile_path.name}")

    # --- Fish shell ---
    fish_config = Path.home() / ".config" / "fish" / "config.fish"
    if fish_config.exists():
        content = fish_config.read_text(encoding="utf-8")
        if "function peon" not in content:
            with open(fish_config, "a", encoding="utf-8") as fh:
                fh.write(
                    f"\n# peon-ping quick controls\n"
                    f"function peon; bash {install_dir}/peon.sh $argv; end\n"
                )
            print("Added peon function to config.fish")

    fish_comp_dir = Path.home() / ".config" / "fish" / "completions"
    fish_comp_src = install_dir / "completions.fish"
    if (Path.home() / ".config" / "fish").exists() and fish_comp_src.exists():
        fish_comp_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(fish_comp_src, fish_comp_dir / "peon.fish")
        print(f"Installed fish completions to {fish_comp_dir / 'peon.fish'}")

    # --- Verify sounds ---
    print()
    for pack in PACKS:
        sound_dir = install_dir / "packs" / pack / "sounds"
        sound_count = 0
        if sound_dir.exists():
            for ext in ("*.wav", "*.mp3", "*.ogg"):
                sound_count += len(list(sound_dir.glob(ext)))
        if sound_count == 0:
            print(f"[{pack}] Warning: No sound files found!")
        else:
            print(f"[{pack}] {sound_count} sound files installed.")

    # --- Backup existing notify.sh (global fresh install only) ---
    if not local_mode and not updating:
        notify_sh = base_dir / "hooks" / "notify.sh"
        if notify_sh.exists():
            shutil.copy2(notify_sh, notify_sh.with_suffix(".sh.backup"))
            print()
            print("Backed up notify.sh \u2192 notify.sh.backup")

    # --- Update settings.json ---
    print()
    print("Updating Claude Code hooks in settings.json...")

    if local_mode:
        hook_cmd_setting = ".claude/hooks/peon-ping/peon.sh"
    else:
        hook_cmd_setting = str(install_dir / "peon.sh")

    # On Windows, also register peon.bat alongside peon.sh
    # (peon.sh may not work natively, but peon.bat wraps peon.py)
    if PLATFORM == "windows":
        if local_mode:
            hook_cmd_setting = "python .claude/hooks/peon-ping/peon.py"
        else:
            hook_cmd_setting = f"python {install_dir / 'peon.py'}"

    if settings_path.exists():
        with open(settings_path, "r", encoding="utf-8") as fh:
            settings = json.load(fh)
    else:
        settings = {}

    hooks = settings.setdefault("hooks", {})

    peon_hook = {
        "type": "command",
        "command": hook_cmd_setting,
        "timeout": 10,
    }
    peon_entry = {
        "matcher": "",
        "hooks": [peon_hook],
    }

    events = ["SessionStart", "UserPromptSubmit", "Stop", "Notification", "PermissionRequest"]

    for event in events:
        event_hooks = hooks.get(event, [])
        # Remove existing notify.sh or peon entries
        event_hooks = [
            h for h in event_hooks
            if not any(
                "notify.sh" in hk.get("command", "")
                or "peon.sh" in hk.get("command", "")
                or "peon.py" in hk.get("command", "")
                for hk in h.get("hooks", [])
            )
        ]
        event_hooks.append(peon_entry)
        hooks[event] = event_hooks

    settings["hooks"] = hooks

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    with open(settings_path, "w", encoding="utf-8") as fh:
        json.dump(settings, fh, indent=2)
        fh.write("\n")

    print(f"Hooks registered for: {', '.join(events)}")

    # --- Initialize state (fresh install only) ---
    if not updating:
        state_file = install_dir / ".state.json"
        with open(state_file, "w", encoding="utf-8") as fh:
            fh.write("{}")

    # --- Test sound ---
    print()
    print("Testing sound...")

    try:
        with open(install_dir / "config.json", "r", encoding="utf-8") as fh:
            active_pack = json.load(fh).get("active_pack", "peon")
    except Exception:
        active_pack = "peon"

    pack_sound_dir = install_dir / "packs" / active_pack / "sounds"
    test_sound = None
    if pack_sound_dir.exists():
        for ext in ("*.wav", "*.mp3", "*.ogg"):
            sounds = sorted(pack_sound_dir.glob(ext))
            if sounds:
                test_sound = sounds[0]
                break

    if test_sound:
        try:
            if PLATFORM == "mac":
                subprocess.run(["afplay", "-v", "0.3", str(test_sound)], timeout=10)
            elif PLATFORM == "wsl":
                wpath = subprocess.run(
                    ["wslpath", "-w", str(test_sound)],
                    capture_output=True, text=True,
                ).stdout.strip().replace("\\", "/")
                subprocess.run(
                    [
                        "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                        f"Add-Type -AssemblyName PresentationCore; "
                        f"$p = New-Object System.Windows.Media.MediaPlayer; "
                        f"$p.Open([Uri]::new('file:///{wpath}')); "
                        f"$p.Volume = 0.3; Start-Sleep -Milliseconds 200; "
                        f"$p.Play(); Start-Sleep -Seconds 3; $p.Close()",
                    ],
                    timeout=10,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            elif PLATFORM == "windows":
                wpath = str(test_sound.resolve()).replace("\\", "/")
                subprocess.run(
                    [
                        "powershell", "-NoProfile", "-NonInteractive", "-Command",
                        f"Add-Type -AssemblyName PresentationCore; "
                        f"$p = New-Object System.Windows.Media.MediaPlayer; "
                        f"$p.Open([Uri]::new('file:///{wpath}')); "
                        f"$p.Volume = 0.3; Start-Sleep -Milliseconds 200; "
                        f"$p.Play(); Start-Sleep -Seconds 3; $p.Close()",
                    ],
                    timeout=10,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            elif PLATFORM == "linux":
                for cmd in ("pw-play", "paplay", "ffplay", "mpv", "aplay"):
                    if shutil.which(cmd):
                        if cmd == "pw-play":
                            subprocess.run(
                                ["pw-play", "--volume=0.3", str(test_sound)],
                                timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            )
                        elif cmd == "paplay":
                            pa_vol = int(0.3 * 65536)
                            subprocess.run(
                                ["paplay", f"--volume={pa_vol}", str(test_sound)],
                                timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            )
                        elif cmd == "ffplay":
                            subprocess.run(
                                ["ffplay", "-nodisp", "-autoexit", "-volume", "30", str(test_sound)],
                                timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            )
                        elif cmd == "mpv":
                            subprocess.run(
                                ["mpv", "--no-video", "--volume=30", str(test_sound)],
                                timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            )
                        elif cmd == "aplay":
                            subprocess.run(
                                ["aplay", "-q", str(test_sound)],
                                timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            )
                        break
            print("Sound working!")
        except Exception as exc:
            print(f"Warning: Sound test failed: {exc}")
    else:
        print("Warning: No sound files found. Sounds may not play.")

    # --- Done ---
    print()
    if updating:
        print("=== Update complete! ===")
        print()
        print("Updated: peon.sh, peon.py, manifest.json")
        print("Preserved: config.json, state")
    else:
        print("=== Installation complete! ===")
        print()
        print(f"Config: {install_dir / 'config.json'}")
        print("  - Adjust volume, toggle categories, switch packs")
        print()
        print(f"Uninstall: python {install_dir / 'uninstall.py'}")

    print()
    print("Quick controls:")
    print("  /peon-ping-toggle  \u2014 toggle sounds in Claude Code")
    if not local_mode:
        if PLATFORM == "windows":
            print(f'  python "{install_dir / "peon.py"}" --toggle  \u2014 toggle sounds from any terminal')
            print(f'  python "{install_dir / "peon.py"}" --status  \u2014 check if sounds are paused')
        else:
            print("  peon --toggle      \u2014 toggle sounds from any terminal")
            print("  peon --status      \u2014 check if sounds are paused")
    print()
    print("Ready to work!")


if __name__ == "__main__":
    main()
