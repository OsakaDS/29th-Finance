#!/usr/bin/env python3
"""
Build the donation automation into a standalone app.

    python build_app.py

On Windows this produces dist/29th Donations.exe — a single file that runs
without Python installed. On macOS it produces dist/29th Donations.app, and on
Linux the single executable dist/29th Donations. Build
on the platform you want to run on: PyInstaller cannot cross-compile.
Double-click the result; no console window appears.

credentials.json is deliberately NOT bundled: the app asks for the login on
first run and saves it next to the .exe (on macOS in
~/Library/Application Support/29th Donations), so the app itself never
contains a password and is safe to copy to another machine.
"""

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

APP_NAME = "29th Donations"
ENTRY = "donation_gui.py"
HERE = Path(__file__).resolve().parent
EXE_NAME = f"{APP_NAME}.exe"
IS_MAC = sys.platform == "darwin"


def running_instances():
    """PIDs of the built app that are currently running (Windows only).

    Windows locks a running .exe, so the old build cannot be deleted while
    the app is open.
    """
    if sys.platform != "win32":
        return []
    try:
        out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {EXE_NAME}", "/FO", "CSV",
                              "/NH"], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    pids = []
    for line in out.splitlines():
        parts = [p.strip('" ') for p in line.split('","')]
        if len(parts) > 1 and parts[0].lower() == EXE_NAME.lower():
            try:
                pids.append(int(parts[1]))
            except ValueError:
                pass
    return pids


def close_instances(pids):
    subprocess.run(["taskkill", "/F"] + [a for pid in pids for a in ("/PID", str(pid))],
                   capture_output=True, text=True)
    for _ in range(20):  # give Windows a moment to release the file lock
        if not running_instances():
            return True
        time.sleep(0.25)
    return not running_instances()


def clean(path, attempts=3):
    """Delete a build folder, tolerating brief file locks from AV scanners."""
    for attempt in range(attempts):
        try:
            shutil.rmtree(path)
            return True
        except FileNotFoundError:
            return True
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(1)
    return False


def main():
    ap = argparse.ArgumentParser(description=f"Build {APP_NAME}")
    ap.add_argument("--force", action="store_true",
                    help="Close the app automatically if it is running")
    args = ap.parse_args()

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller is missing. Install it with:\n    pip install pyinstaller")
        return 1

    # Without Tkinter the build succeeds but the app crashes silently on launch.
    try:
        import tkinter
        tkinter.Tcl()
    except Exception as e:  # ImportError, or a Tcl/Tk that is broken
        print(f"This Python ({sys.executable}) has no working Tkinter: {e}\n"
              f"The app would build but never open.\n")
        if IS_MAC:
            print("Install Python from https://www.python.org/downloads/macos/ "
                  "(includes Tkinter),\nor with Homebrew run:\n"
                  "    brew install python-tk@%d.%d\n"
                  "then build again. ./build_mac.sh does this for you." % sys.version_info[:2])
        return 1

    # Windows will not let us replace an .exe that is currently running.
    pids = running_instances()
    if pids:
        if args.force:
            print(f"Closing running {EXE_NAME} (pid {', '.join(map(str, pids))})...")
            if not close_instances(pids):
                print("Could not close it. Close the app window and try again.")
                return 1
        else:
            print(f"'{APP_NAME}' is currently running (pid {', '.join(map(str, pids))}).\n"
                  f"Windows locks a running .exe, so the old build cannot be replaced.\n\n"
                  f"Close the app window and run this again, or rebuild with:\n"
                  f"    python build_app.py --force")
            return 1

    # Remove previous build output so a stale exe is never mistaken for a new one.
    try:
        for folder in ("build", "dist"):
            clean(HERE / folder)
    except PermissionError as e:
        print(f"Could not delete the previous build: {e}\n"
              f"Make sure the app is closed and no folder is open in Explorer.")
        return 1
    spec = HERE / f"{APP_NAME}.spec"
    if spec.exists():
        spec.unlink()

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", APP_NAME,
        "--windowed",             # GUI app: no console window (a .app on macOS)
        "--noconfirm",
        "--clean",
        # bs4 pulls its parsers in dynamically; make sure they ship.
        "--hidden-import", "bs4",
        "--hidden-import", "html.parser",
        "--collect-submodules", "urllib3",
        # Trim obvious dead weight from the bundle.
        "--exclude-module", "matplotlib",
        "--exclude-module", "numpy",
        "--exclude-module", "pandas",
        "--exclude-module", "PIL",
        "--exclude-module", "pytest",
    ]
    if IS_MAC:
        # A macOS .app is a folder bundle; one-file mode is not supported there.
        cmd += ["--onedir", "--osx-bundle-identifier", "org.29th.donations"]
        icon = HERE / "app.icns"
    else:
        cmd += ["--onefile"]      # one self-contained .exe
        icon = HERE / "app.ico"
    if icon.exists():
        cmd += ["--icon", str(icon)]
    cmd.append(str(HERE / ENTRY))

    print("Building:", " ".join(cmd), "\n")
    result = subprocess.run(cmd, cwd=HERE)
    if result.returncode != 0:
        print("\nBuild failed.")
        return result.returncode

    if IS_MAC:
        app = HERE / "dist" / f"{APP_NAME}.app"
        print(f"\nBuilt {app}")
        print("Drag it to Applications and double-click it to run. The app is not\n"
              "signed, so the first time right-click it and choose Open.\n"
              "On first launch it asks for your forum login.")
        return 0
    exe = HERE / "dist" / (EXE_NAME if sys.platform == "win32" else APP_NAME)
    size = exe.stat().st_size / (1024 * 1024) if exe.exists() else 0
    print(f"\nBuilt {exe} ({size:.1f} MB)")
    print("Double-click it to run. On first launch it asks for your forum login.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
