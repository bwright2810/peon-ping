#!/usr/bin/env python3
"""
peon-ping uninstaller (cross-platform)

Removes peon hooks, skills, and optionally restores notify.sh.
Works on Windows, macOS, and Linux.
"""

import json
import os
import shutil
import sys
from pathlib import Path


def main() -> None:
    # Determine install directory (same logic as uninstall.sh)
    script_dir = Path(__file__).resolve().parent
    install_dir = script_dir
    base_dir = install_dir.parent.parent  # hooks/peon-ping -> hooks -> .claude

    settings_path = base_dir / "settings.json"

    is_local = str(base_dir) != str(Path.home() / ".claude")

    notify_backup = base_dir / "hooks" / "notify.sh.backup"
    notify_sh = base_dir / "hooks" / "notify.sh"

    print("=== peon-ping uninstaller ===")
    print()

    # --- Remove hook entries from settings.json ---
    if settings_path.exists():
        print("Removing peon hooks from settings.json...")
        try:
            with open(settings_path, "r", encoding="utf-8") as fh:
                settings = json.load(fh)

            hooks = settings.get("hooks", {})
            events_cleaned = []

            for event in list(hooks.keys()):
                entries = hooks[event]
                original_count = len(entries)
                entries = [
                    h for h in entries
                    if not any(
                        "peon.sh" in hk.get("command", "")
                        or "peon.py" in hk.get("command", "")
                        for hk in h.get("hooks", [])
                    )
                ]
                if len(entries) < original_count:
                    events_cleaned.append(event)
                if entries:
                    hooks[event] = entries
                else:
                    del hooks[event]

            settings["hooks"] = hooks

            with open(settings_path, "w", encoding="utf-8") as fh:
                json.dump(settings, fh, indent=2)
                fh.write("\n")

            if events_cleaned:
                print(f"Removed hooks for: {', '.join(events_cleaned)}")
            else:
                print("No peon hooks found in settings.json")
        except Exception as exc:
            print(f"Warning: Could not update settings.json: {exc}")

    # --- Restore notify.sh backup (global install only) ---
    if not is_local and notify_backup.exists():
        print()
        try:
            response = input(
                "Restore original notify.sh from backup? [Y/n] "
            ).strip()
        except EOFError:
            response = "n"

        if response.lower() != "n":
            try:
                with open(settings_path, "r", encoding="utf-8") as fh:
                    settings = json.load(fh)

                hooks = settings.setdefault("hooks", {})
                notify_hook_entry = {
                    "matcher": "",
                    "hooks": [{
                        "type": "command",
                        "command": str(notify_sh),
                        "timeout": 10,
                    }],
                }

                for event in ("SessionStart", "UserPromptSubmit", "Stop", "Notification"):
                    event_hooks = hooks.get(event, [])
                    has_notify = any(
                        "notify.sh" in hk.get("command", "")
                        for h in event_hooks
                        for hk in h.get("hooks", [])
                    )
                    if not has_notify:
                        event_hooks.append(notify_hook_entry)
                    hooks[event] = event_hooks

                settings["hooks"] = hooks

                with open(settings_path, "w", encoding="utf-8") as fh:
                    json.dump(settings, fh, indent=2)
                    fh.write("\n")

                print(
                    "Restored notify.sh hooks for: "
                    "SessionStart, UserPromptSubmit, Stop, Notification"
                )
            except Exception as exc:
                print(f"Warning: Could not restore notify.sh hooks: {exc}")

            shutil.copy2(notify_backup, notify_sh)
            notify_backup.unlink()
            print("notify.sh restored")

    # --- Remove fish completions ---
    fish_completions = Path.home() / ".config" / "fish" / "completions" / "peon.fish"
    if fish_completions.exists():
        fish_completions.unlink()
        print("Removed fish completions")

    # --- Remove skill directories ---
    for skill_name in ("peon-ping-toggle", "peon-ping-config"):
        skill_dir = base_dir / "skills" / skill_name
        if skill_dir.exists():
            print()
            print(f"Removing {skill_dir}...")
            shutil.rmtree(skill_dir)
            print(f"Removed {skill_name} skill")

    # --- Remove install directory (deployed copy only) ---
    # Only remove the install directory when running from the deployed copy
    # inside ~/.claude/hooks/peon-ping.  When running from the source repo
    # (is_local), the directory is the project itself and must not be deleted.
    if not is_local and install_dir.exists():
        print()
        print(f"Removing {install_dir}...")
        # We are running from inside install_dir, so on Windows we may not be
        # able to remove the directory while the script is running.  Delete
        # everything we can and schedule the rest for cleanup.
        errors: list[str] = []
        for item in sorted(install_dir.rglob("*"), reverse=True):
            try:
                if item.is_file() or item.is_symlink():
                    item.unlink()
                elif item.is_dir():
                    item.rmdir()
            except Exception:
                errors.append(str(item))
        # Try removing the directory itself
        try:
            install_dir.rmdir()
            print("Removed")
        except Exception:
            if errors:
                print(
                    "Warning: Could not fully remove install directory "
                    "(some files may be locked by the running script)."
                )
                print(f"Please delete manually: {install_dir}")
            else:
                print(f"Please delete manually: {install_dir}")

    print()
    print("=== Uninstall complete ===")
    print("Me go now.")


if __name__ == "__main__":
    main()
