#!/usr/bin/env python3
"""Kick off local Grok Bot with a Soft-OPEN (or smoke) prompt file.

Grok Bot (desktop) exposes deep links like ``grokbot://app/v1/open``. There is
no documented API to inject prompt text into a chat, so this helper:

1. Validates the prompt file
2. Copies its contents to the GTK clipboard
3. Launches / focuses Grok Bot via ``grokbot://app/v1/open``
4. Optionally tries Ctrl+V / Enter via ``xdotool`` when ``--send`` is set

Exit codes:
  0  kickoff steps succeeded (clipboard + open). ``--send`` may still be skipped.
  2  usage / missing prompt
  3  clipboard failed
  4  grok-bot binary missing / open failed
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


OPEN_URL = "grokbot://app/v1/open"


def _copy_clipboard(text: str) -> None:
    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, GLib, Gtk

    clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
    clipboard.set_text(text, -1)
    clipboard.store()
    GLib.timeout_add(250, Gtk.main_quit)
    Gtk.main()
    got = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).wait_for_text()
    if got != text:
        raise RuntimeError("clipboard verify failed (GTK clipboard mismatch)")


def _open_grok(url: str) -> None:
    binary = shutil.which("grok-bot") or "/usr/bin/grok-bot"
    if not Path(binary).exists():
        raise FileNotFoundError(f"grok-bot not found ({binary})")
    # Second-instance deep link; do not wait on the Electron process.
    subprocess.Popen(
        [binary, url],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _try_send() -> str:
    """Best-effort paste+submit. Returns status string."""
    if shutil.which("xdotool") is None:
        return "skipped_no_xdotool"
    time.sleep(1.2)
    # Prefer a window whose class/name looks like Grok Bot.
    try:
        ids = subprocess.check_output(
            ["xdotool", "search", "--class", "grok-bot"], text=True
        ).split()
    except subprocess.CalledProcessError:
        ids = []
    if not ids:
        try:
            ids = subprocess.check_output(
                ["xdotool", "search", "--name", "Grok"], text=True
            ).split()
        except subprocess.CalledProcessError:
            ids = []
    if not ids:
        return "skipped_no_window"
    wid = ids[-1]
    subprocess.check_call(["xdotool", "windowactivate", "--sync", wid])
    time.sleep(0.3)
    subprocess.check_call(["xdotool", "key", "--clearmodifiers", "ctrl+v"])
    time.sleep(0.2)
    subprocess.check_call(["xdotool", "key", "--clearmodifiers", "Return"])
    return "sent"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("prompt", type=Path, help="Markdown prompt file to hand to Grok Bot")
    ap.add_argument(
        "--url",
        default=OPEN_URL,
        help=f"Deep link to open (default {OPEN_URL})",
    )
    ap.add_argument(
        "--send",
        action="store_true",
        help="Also try xdotool Ctrl+V Enter after open (best-effort)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate prompt + print actions only",
    )
    args = ap.parse_args()
    path: Path = args.prompt.expanduser().resolve()
    if not path.is_file():
        print(f"missing prompt: {path}", file=sys.stderr)
        return 2
    text = path.read_text(encoding="utf-8")
    if len(text.strip()) < 8:
        print("prompt too short", file=sys.stderr)
        return 2
    if len(text) > 900_000:
        print("prompt too large for clipboard kickoff", file=sys.stderr)
        return 2

    print(f"prompt={path}")
    print(f"bytes={len(text)}")
    print(f"url={args.url}")
    if args.dry_run:
        print("dry_run=1")
        return 0

    try:
        _copy_clipboard(text)
        print("clipboard=ok")
    except Exception as exc:  # noqa: BLE001 — operator-facing CLI
        print(f"clipboard_error={exc}", file=sys.stderr)
        return 3

    try:
        _open_grok(args.url)
        print("open=ok")
    except Exception as exc:  # noqa: BLE001
        print(f"open_error={exc}", file=sys.stderr)
        return 4

    if args.send:
        status = _try_send()
        print(f"send={status}")
    else:
        print("send=manual_paste_ctrl_v_enter")
        print(
            "Grok Bot should be focused with the Soft-OPEN prompt on the clipboard.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    # Prefer Wayland-unfriendly hosts still having DISPLAY for GTK clipboard.
    os.environ.setdefault("GDK_BACKEND", os.environ.get("GDK_BACKEND", "x11"))
    raise SystemExit(main())
