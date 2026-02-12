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
