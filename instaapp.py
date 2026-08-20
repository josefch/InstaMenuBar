#!/usr/bin/env python3
"""
InstaMenuBar — self-contained app.

One window, no browser, no SwiftBar, no menu bar item:

  • the gallery renders in the app's own WebKit view
  • Refresh inside the page actually refreshes (custom instawatch:// scheme)
  • clicking a post opens it in your default browser, not in the window
  • the Dock icon shows the follower count
  • auto-refreshes on a timer

Data work is delegated to instawatch.30m.py — same token, same history.json,
same gallery.html. Nothing here talks to the API directly.

    ~/.instawatch/venv/bin/python instaapp.py

Requires: pyobjc-framework-WebKit  (pip install pyobjc-framework-WebKit)
"""

import os
import re
import subprocess
import sys
import traceback
from datetime import datetime

from AppKit import (NSApplication, NSApplicationActivationPolicyRegular,
                    NSBackingStoreBuffered, NSColor, NSFont, NSFontAttributeName,
                    NSForegroundColorAttributeName, NSImage, NSMakeRect,
                    NSMenu, NSMenuItem, NSMutableParagraphStyle,
                    NSParagraphStyleAttributeName, NSTextAlignmentCenter,
                    NSWindow, NSWindowStyleMaskClosable,
                    NSWindowStyleMaskMiniaturizable, NSWindowStyleMaskResizable,
                    NSWindowStyleMaskTitled, NSWorkspace, NSBezierPath)
from Foundation import (NSURL, NSURLRequest, NSMakeSize, NSObject, NSString,
                        NSTimer)
from WebKit import WKWebView, WKWebViewConfiguration

APP_DIR = os.path.expanduser("~/.instawatch")
GALLERY = os.path.join(APP_DIR, "gallery.html")
LOG = os.path.join(APP_DIR, "instaapp.log")

PLUGIN = os.environ.get(
    "INSTAWATCH_PLUGIN",
    os.path.expanduser("~/catalyst/InstaMenuBar/plugins/instawatch.30m.py"))
REFRESH_MINUTES = float(os.environ.get("INSTAWATCH_MINUTES", "30"))

WKNavigationActionPolicyCancel = 0
WKNavigationActionPolicyAllow = 1


def log(msg):
    try:
        os.makedirs(APP_DIR, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")
    except OSError:
        pass


def run_plugin():
    """Run the plugin: refreshes history.json and rewrites gallery.html."""
    if not os.path.exists(PLUGIN):
        log(f"plugin not found: {PLUGIN}")
        return None
    argv = ([PLUGIN] if os.access(PLUGIN, os.X_OK)
            else ["/usr/bin/env", "python3", PLUGIN])
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=180)
        lines = (out.stdout or "").splitlines()
        if not lines:
            log(f"no output (rc={out.returncode}): {out.stderr[:300]}")
            return None
        return lines[0].split("|")[0].strip()
    except Exception as exc:  # noqa: BLE001
        log(f"plugin failed: {exc}")
        return None


def count_from(line):
    if not line:
        return None
    value = re.sub(r"^[^\w\d]*", "", line).strip()
    return value or None


def icon_with_text(text):
    """Draw the count into a Dock-sized icon. None if drawing fails."""
    try:
        size = 256.0
        img = NSImage.alloc().initWithSize_(NSMakeSize(size, size))
        img.lockFocus()
        NSColor.colorWithCalibratedRed_green_blue_alpha_(
            0.086, 0.094, 0.110, 1.0).set()
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(8, 8, size - 16, size - 16), 56, 56).fill()

        style = NSMutableParagraphStyle.alloc().init()
        style.setAlignment_(NSTextAlignmentCenter)
        pts = 96 if len(text) <= 5 else 76
        attrs = {NSFontAttributeName: NSFont.boldSystemFontOfSize_(pts),
                 NSForegroundColorAttributeName: NSColor.whiteColor(),
                 NSParagraphStyleAttributeName: style}
        ns = NSString.stringWithString_(text)
        h = ns.sizeWithAttributes_(attrs).height
        ns.drawInRect_withAttributes_(
            NSMakeRect(0, (size - h) / 2 - 4, size, h), attrs)

        sub = {NSFontAttributeName: NSFont.systemFontOfSize_(28),
               NSForegroundColorAttributeName:
                   NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.55),
               NSParagraphStyleAttributeName: style}
        NSString.stringWithString_("followers").drawInRect_withAttributes_(
            NSMakeRect(0, 44, size, 34), sub)
        img.unlockFocus()
        return img
    except Exception as exc:  # noqa: BLE001
        log(f"icon drawing failed: {exc}")
        return None


class Delegate(NSObject):
    """App delegate, window delegate and WKNavigationDelegate in one."""

    # ---- lifecycle ----------------------------------------------------

    def applicationDidFinishLaunching_(self, _n):
        try:
            self.buildMenu()
            self.buildWindow()
            self.refresh_(None)
            NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                REFRESH_MINUTES * 60.0, self, "refresh:", None, True)
        except Exception:  # noqa: BLE001
            log("startup failed:\n" + traceback.format_exc())

    def applicationShouldHandleReopen_hasVisibleWindows_(self, _app, flag):
        if not flag and getattr(self, "window", None) is not None:
            self.window.makeKeyAndOrderFront_(None)
        return True

    def applicationShouldTerminateAfterLastWindowClosed_(self, _app):
        return False        # closing the window keeps it in the Dock

    # ---- ui -----------------------------------------------------------

    def buildMenu(self):
        """A minimal main menu so ⌘R, ⌘W and ⌘Q behave as expected."""
        main = NSMenu.alloc().init()
        app_item = NSMenuItem.alloc().init()
        main.addItem_(app_item)
        app_menu = NSMenu.alloc().init()

        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Refresh", "refresh:", "r")
        item.setTarget_(self)
        app_menu.addItem_(item)

        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Open on Instagram", "openInstagram:", "i")
        item.setTarget_(self)
        app_menu.addItem_(item)

        app_menu.addItem_(NSMenuItem.separatorItem())
        app_menu.addItem_(
            NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Close Window", "performClose:", "w"))
        app_menu.addItem_(
            NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Quit InstaMenuBar", "terminate:", "q"))
        app_item.setSubmenu_(app_menu)
        NSApplication.sharedApplication().setMainMenu_(main)

    def buildWindow(self):
        rect = NSMakeRect(0, 0, 1000, 780)
        mask = (NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
                | NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskResizable)
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, mask, NSBackingStoreBuffered, False)
        self.window.setTitle_("InstaMenuBar")
        self.window.center()

        config = WKWebViewConfiguration.alloc().init()
        self.web = WKWebView.alloc().initWithFrame_configuration_(rect, config)
        self.web.setNavigationDelegate_(self)
        try:
            self.web.setValue_forKey_(False, "drawsBackground")
        except Exception:  # noqa: BLE001
            pass
        self.window.setContentView_(self.web)
        self.window.makeKeyAndOrderFront_(None)

    def reloadGallery(self):
        if not os.path.exists(GALLERY):
            return
        url = NSURL.fileURLWithPath_(GALLERY)
        try:
            self.web.loadFileURL_allowingReadAccessToURL_(
                url, NSURL.fileURLWithPath_(APP_DIR))
        except Exception:  # noqa: BLE001
            self.web.loadRequest_(NSURLRequest.requestWithURL_(url))

    # ---- navigation ---------------------------------------------------

    def webView_decidePolicyForNavigationAction_decisionHandler_(
            self, _web, action, handler):
        """
        instawatch://refresh  -> re-run the plugin, reload
        http(s)               -> hand to the default browser, don't navigate
        file://               -> allow (that's our own page)
        """
        try:
            url = action.request().URL()
            scheme = (url.scheme() or "").lower()
            if scheme == "instawatch":
                handler(WKNavigationActionPolicyCancel)
                self.refresh_(None)
                return
            if scheme in ("http", "https"):
                handler(WKNavigationActionPolicyCancel)
                NSWorkspace.sharedWorkspace().openURL_(url)
                return
        except Exception:  # noqa: BLE001
            log("navigation policy failed:\n" + traceback.format_exc())
        handler(WKNavigationActionPolicyAllow)

    def webView_didFinishNavigation_(self, _web, _nav):
        log("gallery loaded")

    def webView_didFailNavigation_withError_(self, _web, _nav, error):
        log(f"navigation failed: {error}")

    def webView_didFailProvisionalNavigation_withError_(self, _web, _nav, error):
        log(f"provisional navigation failed: {error}")

    # ---- actions ------------------------------------------------------

    def openInstagram_(self, _sender):
        user = os.environ.get("INSTAWATCH_USER", "")
        if not user:
            try:
                with open(GALLERY, "r", encoding="utf-8") as fh:
                    m = re.search(r"instagram\.com/([A-Za-z0-9._]+)", fh.read())
                user = m.group(1) if m else ""
            except OSError:
                user = ""
        NSWorkspace.sharedWorkspace().openURL_(
            NSURL.URLWithString_(f"https://instagram.com/{user}"))

    def refresh_(self, _sender):
        app = NSApplication.sharedApplication()
        count = count_from(run_plugin())
        if count:
            img = icon_with_text(count)
            if img is not None:
                app.setApplicationIconImage_(img)
                app.dockTile().setBadgeLabel_(None)
            else:
                app.dockTile().setBadgeLabel_(count)
            self.window.setTitle_(f"InstaMenuBar — {count} followers")
            log(f"refreshed: {count}")
        else:
            app.dockTile().setBadgeLabel_("!")
            log("refresh produced no count")
        app.dockTile().display()
        self.reloadGallery()


def main():
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    delegate = Delegate.alloc().init()
    app.setDelegate_(delegate)
    app.activateIgnoringOtherApps_(True)
    app.run()


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001
        log("fatal:\n" + traceback.format_exc())
        raise
