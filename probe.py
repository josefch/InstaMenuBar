#!/usr/bin/env python3
"""
Menu bar probe — answers, with facts rather than inference, why a new status
item is not visible on this Mac.

Creates a plainly-labelled status item, waits for AppKit to lay it out, and
records: every screen and its coordinate space, the status bar geometry, where
the item's window actually landed, and which screen (if any) it landed on.

    ~/.instawatch/venv/bin/python ~/.instawatch/probe.py

Runs for ~14 seconds, prints to the terminal and writes ~/.instawatch/probe.log
"""

import os
import sys
import time

from AppKit import (NSApplication, NSApplicationActivationPolicyAccessory,
                    NSScreen, NSStatusBar, NSVariableStatusItemLength)
from Foundation import NSRunLoop, NSDate

LOG = os.path.expanduser("~/.instawatch/probe.log")
lines = []


def say(msg):
    print(msg, flush=True)
    lines.append(str(msg))


def dump_screens():
    say("--- screens ---")
    try:
        screens = NSScreen.screens()
        main = NSScreen.mainScreen()
        say(f"count: {len(screens)}")
        for i, s in enumerate(screens):
            f, vf = s.frame(), s.visibleFrame()
            tag = []
            if main is not None and s.frame().origin.x == main.frame().origin.x \
                    and s.frame().origin.y == main.frame().origin.y:
                tag.append("main")
            if f.origin.x == 0 and f.origin.y == 0:
                tag.append("PRIMARY (menu bar)")
            say(f"  [{i}] frame  x={f.origin.x:.0f} y={f.origin.y:.0f} "
                f"{f.size.width:.0f}x{f.size.height:.0f}  "
                f"visible h={vf.size.height:.0f}  {' '.join(tag)}")
    except Exception as exc:  # noqa: BLE001
        say(f"  screen dump failed: {exc}")


def report(item, label):
    say(f"--- {label} ---")
    try:
        say(f"  isVisible : {item.isVisible() if hasattr(item, 'isVisible') else 'n/a'}")
        say(f"  length    : {item.length()}")
        btn = item.button()
        if btn is None:
            say("  button    : NONE")
            return
        say(f"  title     : {btn.title()!r}")
        win = btn.window()
        if win is None:
            say("  window    : NONE (never placed)")
            return
        f = win.frame()
        say(f"  window    : x={f.origin.x:.0f} y={f.origin.y:.0f} "
            f"w={f.size.width:.0f} h={f.size.height:.0f}")
        scr = win.screen()
        if scr is None:
            say("  on screen : NONE  <-- the window is not on any display")
        else:
            sf = scr.frame()
            say(f"  on screen : x={sf.origin.x:.0f} y={sf.origin.y:.0f} "
                f"{sf.size.width:.0f}x{sf.size.height:.0f}")
        # Does it fall inside any screen's rect?
        inside = []
        for i, s in enumerate(NSScreen.screens()):
            sf = s.frame()
            if (f.origin.x < sf.origin.x + sf.size.width
                    and f.origin.x + f.size.width > sf.origin.x
                    and f.origin.y < sf.origin.y + sf.size.height
                    and f.origin.y + f.size.height > sf.origin.y):
                inside.append(i)
        say(f"  intersects: {inside if inside else 'NO SCREEN — off-screen'}")
    except Exception as exc:  # noqa: BLE001
        say(f"  report failed: {exc}")


def main():
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    bar = NSStatusBar.systemStatusBar()
    say(f"status bar thickness: {bar.thickness()}")
    dump_screens()

    item = bar.statusItemWithLength_(NSVariableStatusItemLength)
    item.button().setTitle_("PROBE-A")
    item2 = bar.statusItemWithLength_(NSVariableStatusItemLength)
    item2.button().setTitle_("PROBE-B")
    say("created two status items titled PROBE-A and PROBE-B")

    deadline = time.time() + 14
    marks = {1: False, 5: False, 12: False}
    start = time.time()
    while time.time() < deadline:
        NSRunLoop.currentRunLoop().runUntilDate_(
            NSDate.dateWithTimeIntervalSinceNow_(0.2))
        elapsed = time.time() - start
        for at in sorted(marks):
            if not marks[at] and elapsed >= at:
                marks[at] = True
                report(item, f"PROBE-A at t+{at}s")
                if at == 12:
                    report(item2, f"PROBE-B at t+{at}s")

    say("done — if you saw PROBE-A / PROBE-B in the menu bar, say so")
    try:
        with open(LOG, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        say(f"written to {LOG}")
    except OSError as exc:
        say(f"could not write log: {exc}")


if __name__ == "__main__":
    main()
