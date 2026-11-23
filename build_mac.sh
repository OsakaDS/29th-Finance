#!/usr/bin/env bash
# Build "29th Donations.app" on macOS in one step.
#
#     ./build_mac.sh
#
# Picks a Python that has Tkinter (installing Homebrew's python-tk if needed),
# sets up a .venv, installs the requirements and runs build_app.py.
set -euo pipefail
cd "$(dirname "$0")"

has_tk() {
    # Tk 8.5 (Apple's old system Python) crashes on current macOS, so require 8.6+.
    "$1" -c 'import tkinter, sys; tkinter.Tcl(); sys.exit(0 if tkinter.TkVersion >= 8.6 else 1)' \
        >/dev/null 2>&1
}

# Prefer the python.org install (always ships Tkinter), then whatever is on PATH.
PY=""
for candidate in /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
                 "$(command -v python3 || true)"; do
    if [ -n "$candidate" ] && [ -x "$candidate" ]; then
        PY="$candidate"
        has_tk "$PY" && break
    fi
done

if [ -z "$PY" ]; then
    echo "Python 3 was not found. Install it from https://www.python.org/downloads/macos/"
    exit 1
fi

if ! has_tk "$PY"; then
    VER="$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
    if command -v brew >/dev/null 2>&1 \
            && [[ "$("$PY" -c 'import sys; print(sys.prefix)')" == "$(brew --prefix)"* ]]; then
        echo "Homebrew Python $VER has no Tkinter; installing python-tk@$VER..."
        brew install "python-tk@$VER"
    fi
fi

if ! has_tk "$PY"; then
    echo "The Python at $PY has no working Tkinter, which the app needs."
    echo "Install Python from https://www.python.org/downloads/macos/ and run this again."
    exit 1
fi
echo "Using $PY ($("$PY" --version))"

# A .venv made from a different Python may still lack Tkinter; rebuild it then.
if [ -d .venv ] && ! has_tk .venv/bin/python; then
    echo "Recreating .venv (it has no Tkinter)..."
    rm -rf .venv
fi
[ -d .venv ] || "$PY" -m venv .venv

.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -r requirements.txt
.venv/bin/python build_app.py "$@"
