#!/usr/bin/env python3
# <xbar.title>InstaWatch</xbar.title>
# <xbar.version>v2.0</xbar.version>
# <xbar.author>Josef Chladek</xbar.author>
# <xbar.desc>Instagram follower count and latest post engagement.</xbar.desc>
# <xbar.dependencies>python3</xbar.dependencies>
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideLastUpdated>true</swiftbar.hideLastUpdated>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>
"""
InstaWatch as a SwiftBar plugin.

SwiftBar runs this script on the interval in its filename (30m) and renders
whatever it prints. Everything above the first '---' becomes the menu bar
item; everything below becomes the dropdown.

Standard library only — no venv, no rumps, no AppKit. Reads the same token
from the Keychain and keeps the same ~/.instawatch/history.json as before,
so the follower history recorded so far carries over.

Test the output without SwiftBar:   ./instawatch.30m.py
Render sample data:                 ./instawatch.30m.py --selftest
"""

import base64
import json
import os
import re
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

APP_DIR = os.path.expanduser("~/.instawatch")
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
HISTORY_PATH = os.path.join(APP_DIR, "history.json")
LOG_PATH = os.path.join(APP_DIR, "instawatch.log")
THUMB_DIR = os.path.join(APP_DIR, "thumbs")
GALLERY_PATH = os.path.join(APP_DIR, "gallery.html")

GRAPH = "https://graph.instagram.com"
API_VERSION = "v23.0"
KEYCHAIN_SERVICE = "instawatch-ig-token"
NNBSP = " "

DEFAULTS = {
    "media_limit": 20,
    "notify_on_follower_change": True,
    "caption_chars": 64,
    "title_mode": "compact",     # compact | count | full
    "show_thumbnails": True,
    "thumbnail_px": 64,          # source pixels; AppKit still draws these at
                                 # menu-row height — see the gallery for big ones
    "post_font_size": 0,         # 0 = system default. Text size does NOT
                                 # affect thumbnail size; menu images are capped.
    "gallery": True,             # generate gallery.html with full-size images
    "gallery_width": 980,
    "gallery_height": 760,
    # "gallery" = clicking the menu bar item opens the gallery directly.
    # "menu"    = the classic dropdown; the gallery is then a row inside it.
    "default_view": "gallery",
    # "browser" opens the gallery in Safari — links inside it then open normally.
    # "panel" uses SwiftBar's built-in webview: prettier and floating, but it
    # has no way to hand a URL to the browser, so post clicks navigate in place.
    "gallery_mode": "browser",
}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def log(msg):
    try:
        os.makedirs(APP_DIR, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")
    except OSError:
        pass


def load_json(path, fallback):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return dict(fallback)


def save_json(path, data):
    try:
        os.makedirs(APP_DIR, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
        os.chmod(path, 0o600)
    except OSError as exc:
        log(f"could not save {path}: {exc}")


def fmt(n):
    try:
        return f"{int(n):,}".replace(",", NNBSP)
    except (TypeError, ValueError):
        return "—"


def fmt_compact(n):
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "—"
    if n < 10_000:
        return fmt(n)
    if n < 1_000_000:
        return f"{int(n / 100) / 10:.1f}k".replace(".0k", "k")
    return f"{int(n / 100_000) / 10:.1f}M".replace(".0M", "M")


def signed(n):
    return f"+{n}" if n > 0 else str(n)


def notify(title, message):
    script = (f"display notification {json.dumps(message)} "
              f"with title {json.dumps(title)}")
    subprocess.run(["osascript", "-e", script], check=False,
                   capture_output=True, timeout=10)


def esc(text):
    """SwiftBar treats '|' as the start of parameters, and newlines as rows."""
    return str(text).replace("|", "¦").replace("\n", " ").strip()


# --------------------------------------------------------------------------
# thumbnails
# --------------------------------------------------------------------------

def thumbnail_b64(post, px):
    """
    Small square PNG for the post, base64-encoded for SwiftBar's `image=`.

    Resized with sips, which ships with macOS — no Pillow, no pip. Results
    are cached per media id, so a given post is only ever fetched once and
    subsequent refreshes cost nothing.
    """
    media_id = re.sub(r"[^A-Za-z0-9_-]", "", str(post.get("id", "")))
    if not media_id:
        return None

    cache = os.path.join(THUMB_DIR, f"{media_id}-{px}.b64")
    try:
        with open(cache, "r", encoding="ascii") as fh:
            return fh.read().strip() or None
    except OSError:
        pass

    # Videos and reels expose a still separately; images use media_url.
    url = post.get("thumbnail_url") or post.get("media_url")
    if not url:
        return None

    os.makedirs(THUMB_DIR, exist_ok=True)
    raw = os.path.join(THUMB_DIR, f".{media_id}.src")
    png = os.path.join(THUMB_DIR, f".{media_id}.png")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "InstaWatch/2.0"})
        with urllib.request.urlopen(req, timeout=15,
                                    context=ssl.create_default_context()) as resp:
            data = resp.read(4_000_000)
        with open(raw, "wb") as fh:
            fh.write(data)

        # -Z fits the longest edge; -c pads to an exact square so rows align.
        subprocess.run(
            ["sips", "-s", "format", "png", "-Z", str(px),
             "-c", str(px), str(px), raw, "--out", png],
            capture_output=True, timeout=20, check=True,
        )
        with open(png, "rb") as fh:
            encoded = base64.b64encode(fh.read()).decode("ascii")

        with open(cache, "w", encoding="ascii") as fh:
            fh.write(encoded)
        return encoded
    except Exception as exc:  # noqa: BLE001
        log(f"thumbnail for {media_id} failed: {exc}")
        return None
    finally:
        for path in (raw, png):
            try:
                os.remove(path)
            except OSError:
                pass


def prune_thumbs(media, px):
    """
    Keep only thumbnails for posts currently shown, at the current size.
    Changing thumbnail_px makes every cached file stale, so drop those too.
    """
    keep = {f"{re.sub(r'[^A-Za-z0-9_-]', '', str(p.get('id', '')))}-{px}.b64"
            for p in media}
    try:
        for name in os.listdir(THUMB_DIR):
            if name.endswith(".b64") and name not in keep:
                os.remove(os.path.join(THUMB_DIR, name))
    except OSError:
        pass


# --------------------------------------------------------------------------
# token + api
# --------------------------------------------------------------------------

class ApiError(Exception):
    pass


def get_token():
    out = subprocess.run(
        ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
        capture_output=True, text=True, timeout=20,
    )
    if out.returncode == 0 and out.stdout.strip():
        return out.stdout.strip()
    return load_json(CONFIG_PATH, {}).get("access_token", "")


def store_token(token):
    subprocess.run(
        ["security", "add-generic-password", "-U", "-s", KEYCHAIN_SERVICE,
         "-a", os.environ.get("USER", "instawatch"), "-w", token],
        capture_output=True, text=True, timeout=20, check=False,
    )


def api_get(path, token, **params):
    params["access_token"] = token
    url = f"{GRAPH}/{API_VERSION}/{path.lstrip('/')}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "InstaWatch/2.0"})
    try:
        with urllib.request.urlopen(req, timeout=25,
                                    context=ssl.create_default_context()) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            msg = json.loads(body)["error"]["message"]
        except Exception:  # noqa: BLE001
            msg = body[:180] or str(exc)
        raise ApiError(msg) from exc
    except Exception as exc:  # noqa: BLE001
        raise ApiError(str(exc)) from exc


def maybe_refresh_token(token, history):
    """Long-lived tokens last 60 days; roll at 50 so it never lapses."""
    last = history.get("token_refreshed")
    if last:
        try:
            if (date.today() - date.fromisoformat(last)).days < 50:
                return token
        except ValueError:
            pass
    try:
        url = (f"{GRAPH}/refresh_access_token?"
               + urllib.parse.urlencode({"grant_type": "ig_refresh_token",
                                         "access_token": token}))
        req = urllib.request.Request(url, headers={"User-Agent": "InstaWatch/2.0"})
        with urllib.request.urlopen(req, timeout=25,
                                    context=ssl.create_default_context()) as resp:
            new = json.loads(resp.read().decode("utf-8")).get("access_token")
        if new:
            store_token(new)
            history["token_refreshed"] = date.today().isoformat()
            log("token refreshed, good for another 60 days")
            return new
    except Exception as exc:  # noqa: BLE001
        log(f"token refresh failed (not fatal yet): {exc}")
    return token


# --------------------------------------------------------------------------
# history
# --------------------------------------------------------------------------

def delta_today(history):
    f = history.get("followers", {})
    today, yday = date.today().isoformat(), (date.today() - timedelta(days=1)).isoformat()
    if today in f and yday in f:
        return f[today] - f[yday]
    return 0


def delta_over(history, days):
    f = history.get("followers", {})
    today = date.today().isoformat()
    if today not in f:
        return None
    target = (date.today() - timedelta(days=days)).isoformat()
    past = [k for k in sorted(f) if k <= target]
    return f[today] - f[past[-1]] if past else None


def record(history, profile, media, config):
    followers = profile.get("followers_count")
    if isinstance(followers, int):
        f = history.setdefault("followers", {})
        today = date.today().isoformat()
        previous = f.get(today)
        f[today] = followers
        for old in sorted(f)[:-370]:
            f.pop(old, None)
        if (config.get("notify_on_follower_change")
                and isinstance(previous, int) and previous != followers):
            notify("Instagram",
                   f"{signed(followers - previous)} followers → {fmt(followers)}")

    history["media"] = {
        p["id"]: {"like_count": p.get("like_count"),
                  "comments_count": p.get("comments_count")}
        for p in media
    }
    save_json(HISTORY_PATH, history)


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def post_line(post, previous, caption_chars, thumb=None, font_size=0):
    caption = re.sub(r"\s+", " ", (post.get("caption") or "")).strip()
    if len(caption) > caption_chars:
        caption = caption[: caption_chars - 1].rstrip() + "…"
    if not caption:
        caption = post.get("media_type", "post").replace("_", " ").lower()

    likes = post.get("like_count")
    bump = ""
    prev = previous.get(post["id"], {}).get("like_count")
    if isinstance(prev, int) and isinstance(likes, int) and likes > prev:
        bump = f" ▲{likes - prev}"

    when = ""
    if post.get("timestamp"):
        try:
            dt = datetime.fromisoformat(post["timestamp"].replace("+0000", "+00:00"))
            days = (datetime.now(timezone.utc) - dt).days
            when = "today" if days == 0 else (f"{days}d" if days < 30
                                              else dt.strftime("%b %Y"))
        except ValueError:
            pass

    label = (f"♥ {fmt(likes)}{bump}   ✎ {fmt(post.get('comments_count'))}"
             f"   {esc(caption)}")
    if when:
        label += f"  ({when})"

    params = []
    if post.get("permalink"):
        params.append(f"href={post['permalink']}")
    if font_size:
        params.append(f"size={int(font_size)}")
    if thumb:
        params.append(f"image={thumb}")
    return f"{label}{' | ' + ' '.join(params) if params else ''}"


def render(profile, media, history, config, previous_media):
    out = []
    followers = profile.get("followers_count")
    mode = config.get("title_mode", "compact")
    d = delta_today(history)

    if mode == "count":
        core = fmt(followers)
    elif mode == "full":
        arrow = f" ▲{d}" if d > 0 else (f" ▼{abs(d)}" if d < 0 else "")
        core = f"{fmt(followers)}{arrow}"
    else:
        core = fmt_compact(followers)

    # Build the gallery first: the menu bar line itself may point at it.
    gallery_path = (write_gallery(profile, media, history, previous_media)
                    if config.get("gallery", True) else None)

    if gallery_path and config.get("default_view", "gallery") == "gallery":
        # webview on the title line means clicking the menu bar item opens the
        # gallery straight away instead of dropping a menu down.
        out.append(f"◎ {core} | {gallery_params(config, gallery_path)}")
    else:
        out.append(f"◎ {core}")

    # Everything below still renders if the webview is unavailable.
    out.append("---")
    line = f"{fmt(followers)} followers"
    if d:
        line += f"   ({signed(d)} today)"
    out.append(f"{line} | size=14")

    d7 = delta_over(history, 7)
    if d7 is not None:
        out.append(f"{signed(d7)} over 7 days | color=#888888")
    d30 = delta_over(history, 30)
    if d30 is not None:
        out.append(f"{signed(d30)} over 30 days | color=#888888")

    out.append(f"{fmt(profile.get('media_count'))} posts  ·  following "
               f"{fmt(profile.get('follows_count'))} | color=#888888")

    if gallery_path:
        out.append(f"Gallery — big thumbnails | {gallery_params(config, gallery_path)}")

    uname = profile.get("username", "")
    if uname:
        out.append(f"Open @{uname} | href=https://instagram.com/{uname}")

    if media:
        out.append("---")
        out.append("Latest posts | color=#888888")
        px = int(config.get("thumbnail_px", 32))
        want_thumbs = bool(config.get("show_thumbnails", True))
        font_size = int(config.get("post_font_size", 0) or 0)
        for post in media:
            thumb = thumbnail_b64(post, px) if want_thumbs else None
            out.append(post_line(post, previous_media,
                                 config.get("caption_chars", 46), thumb, font_size))
        if want_thumbs:
            prune_thumbs(media, px)

    out.append("---")
    out.append(f"Updated {datetime.now():%H:%M} | color=#888888")
    out.append("Refresh now | refresh=true")

    f = history.get("followers", {})
    if len(f) > 1:
        out.append("History")
        prev = None
        for day in sorted(f)[-14:]:
            diff = "" if prev is None else f"   ({signed(f[day] - prev)})"
            out.append(f"--{day}    {fmt(f[day])}{diff} | font=Menlo")
            prev = f[day]
    return out


ln = chr(10)

# Palette: dark chart surface, single-hue (blue) sparkline, reserved status
# colors for the delta. Validated against this surface — the green/red pair
# fails CVD separation on its own, which is why the delta always carries an
# arrow and a sign, and why up and down never appear at the same time.
GALLERY_CSS = """
:root {
  color-scheme: dark;
  --surface: #16181c; --card: #1e2126; --line: #2c2e35;
  --ink: #ffffff; --ink-2: #c3c2b7; --muted: #898781;
  --series: #3987e5; --good: #0ca30c; --bad: #d03b3b;
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 20px 22px 28px; background: var(--surface); color: var(--ink);
  font: 13px/1.45 system-ui, -apple-system, "SF Pro Text", sans-serif;
  -webkit-font-smoothing: antialiased;
}
a { color: inherit; text-decoration: none; }

/* ---- stat tile ---- */
.tile {
  display: flex; align-items: center; gap: 26px; flex-wrap: wrap;
  padding: 14px 18px; margin-bottom: 20px;
  background: var(--card); border: 1px solid var(--line); border-radius: 12px;
}
.who { font-size: 13px; color: var(--muted); margin-bottom: 2px; }
.hero { font-size: 30px; font-weight: 600; letter-spacing: -0.02em; line-height: 1.05; }
.hero small { font-size: 12px; font-weight: 400; color: var(--muted); margin-left: 6px; }
.deltas { display: flex; gap: 16px; font-size: 12px; align-items: baseline; }
.delta { font-weight: 600; }
.delta.up { color: var(--good); } .delta.down { color: var(--bad); }
.delta span { color: var(--muted); font-weight: 400; margin-left: 4px; }
.spark { position: relative; margin-left: auto; }
.spark svg { display: block; }
.tip {
  position: absolute; pointer-events: none; opacity: 0; transform: translate(-50%, -100%);
  background: #0d0d0d; border: 1px solid var(--line); border-radius: 6px;
  padding: 4px 7px; font-size: 11px; white-space: nowrap; transition: opacity .1s;
  font-variant-numeric: tabular-nums;
}
.acts { display: flex; gap: 8px; }
.acts a {
  padding: 5px 11px; border: 1px solid var(--line); border-radius: 7px;
  font-size: 12px; color: var(--ink-2); background: #1a1d21;
}
.acts a:hover { border-color: #4a515c; color: var(--ink); }

details.table { margin: -8px 0 20px; }
details.table summary { cursor: pointer; color: var(--muted); font-size: 12px; }
details.table table {
  margin-top: 8px; border-collapse: collapse; font-size: 12px;
  font-variant-numeric: tabular-nums;
}
details.table td { padding: 2px 18px 2px 0; color: var(--ink-2); }
details.table td.d { color: var(--muted); }

/* ---- grid ---- */
.grid { display: grid; gap: 15px; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); }
a.card {
  display: flex; flex-direction: column; background: var(--card);
  border: 1px solid var(--line); border-radius: 10px; overflow: hidden;
  transition: border-color .12s ease, transform .12s ease;
}
a.card:hover { border-color: #4a515c; transform: translateY(-2px); }
.thumb { position: relative; width: 100%; aspect-ratio: 1/1; background: #24272d; }
.thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.badge {
  position: absolute; top: 7px; right: 7px; padding: 2px 6px; border-radius: 5px;
  background: rgba(0,0,0,.62); font-size: 10px; backdrop-filter: blur(3px);
}
.body { padding: 9px 11px 11px; display: flex; flex-direction: column; gap: 6px; }
.caption {
  font-size: 12px; line-height: 1.35; color: var(--ink-2); min-height: 2.7em;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.stats { display: flex; gap: 12px; font-size: 11.5px; color: var(--muted); }
.stats b { font-weight: 600; color: var(--ink-2); }
.bump { color: var(--good); font-weight: 600; }
.when { margin-left: auto; }
footer { margin-top: 22px; color: var(--muted); font-size: 11px; }
"""

GALLERY_JS = """
// Open posts in a new browser tab. In Safari window.open works; inside
// SwiftBar's webview it returns null (no window delegate), so fall back to
// navigating in place rather than leaving the click doing nothing at all.
document.addEventListener('click', function (e) {
  var a = e.target.closest('a[data-external]');
  if (!a) return;
  var url = a.getAttribute('href');
  e.preventDefault();
  var w = null;
  try { w = window.open(url, '_blank'); } catch (err) { w = null; }
  if (!w) { window.location.href = url; }
});
// Sparkline hover
(function () {
  var box = document.querySelector('.spark'); if (!box) return;
  var tip = box.querySelector('.tip'), cross = box.querySelector('.cross');
  box.querySelectorAll('rect[data-v]').forEach(function (r) {
    r.addEventListener('mouseenter', function () {
      tip.textContent = r.dataset.d + '  ' + r.dataset.v + (r.dataset.c ? '  ' + r.dataset.c : '');
      tip.style.opacity = 1;
      // Clamp inside the panel so edge points don't render half off-screen.
      var half = tip.offsetWidth / 2, w = box.offsetWidth;
      var x = Math.min(Math.max(parseFloat(r.dataset.x), half), w - half);
      tip.style.left = x + 'px';
      tip.style.top = Math.max(tip.offsetHeight, parseFloat(r.dataset.y) - 6) + 'px';
      if (cross) { cross.setAttribute('x1', r.dataset.x); cross.setAttribute('x2', r.dataset.x);
                   cross.style.opacity = 1; }
    });
  });
  box.addEventListener('mouseleave', function () {
    tip.style.opacity = 0; if (cross) cross.style.opacity = 0;
  });
})();
"""


def sparkline_svg(history, days=30):
    """
    Single-series trend for the stat tile: one hue, 2px line, soft area,
    one 8px endpoint marker with a surface ring. No axes, no per-point labels
    — the hero number carries the value; hover carries the detail.
    """
    f = history.get("followers", {})
    keys = sorted(f)[-days:]
    if len(keys) < 2:
        return ""

    values = [f[k] for k in keys]
    w, hgt, pad = 240, 46, 6
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    n = len(values)

    def px(i):
        return pad + i * (w - 2 * pad) / (n - 1)

    def py(v):
        if hi == lo:
            return hgt / 2
        return hgt - pad - (v - lo) / span * (hgt - 2 * pad)

    pts = [(px(i), py(v)) for i, v in enumerate(values)]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = (f"{pts[0][0]:.1f},{hgt - pad:.1f} " + line +
            f" {pts[-1][0]:.1f},{hgt - pad:.1f}")

    hits = []
    step = (w - 2 * pad) / (n - 1)
    for i, (x, y) in enumerate(pts):
        prev = values[i - 1] if i else None
        change = f"({signed(values[i] - prev)})" if prev is not None else ""
        try:
            label = datetime.strptime(keys[i], "%Y-%m-%d").strftime("%d %b")
        except ValueError:
            label = keys[i]
        hits.append(
            f'<rect x="{max(0, x - step / 2):.1f}" y="0" width="{step:.1f}" '
            f'height="{hgt}" fill="transparent" data-v="{fmt(values[i])}" '
            f'data-d="{label}" data-c="{change}" data-x="{x:.1f}" data-y="{y:.1f}"/>')

    ex, ey = pts[-1]
    return f"""<svg width="{w}" height="{hgt}" viewBox="0 0 {w} {hgt}" role="img"
     aria-label="Follower count, last {n} days">
  <polygon points="{area}" fill="var(--series)" opacity="0.13"/>
  <polyline points="{line}" fill="none" stroke="var(--series)" stroke-width="2"
            stroke-linejoin="round" stroke-linecap="round"/>
  <line class="cross" x1="0" y1="0" x2="0" y2="{hgt}" stroke="var(--muted)"
        stroke-width="1" opacity="0" style="transition:opacity .1s"/>
  <circle cx="{ex:.1f}" cy="{ey:.1f}" r="4" fill="var(--series)"
          stroke="var(--surface)" stroke-width="2"/>
  {''.join(hits)}
</svg>"""


def history_table(history, days=14):
    f = history.get("followers", {})
    keys = sorted(f)[-days:]
    if len(keys) < 2:
        return ""
    rows, prev = [], None
    for k in reversed(keys):
        diff = ""
        if prev is not None:
            diff = signed(f[prev] - f[k])
        rows.append(f"<tr><td>{k}</td><td>{fmt(f[k])}</td>"
                    f'<td class="d">{diff}</td></tr>')
        prev = k
    # rows were built newest-first, so the diff belongs to the row above it
    return ('<details class="table"><summary>Show numbers</summary>'
            f'<table>{"".join(rows)}</table></details>')


def gallery_html(profile, media, history, previous, plugin_name="instawatch"):
    """A real page — the one place thumbnails can be as large as we like."""
    def h(text):
        return (str(text).replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))

    uname = profile.get("username", "")
    followers = profile.get("followers_count")

    deltas = []
    for label, value in (("today", delta_today(history)),
                         ("7 days", delta_over(history, 7)),
                         ("30 days", delta_over(history, 30))):
        if value is None:
            continue
        arrow = "▲" if value > 0 else ("▼" if value < 0 else "·")
        cls = "up" if value > 0 else ("down" if value < 0 else "")
        deltas.append(f'<div class="delta {cls}">{arrow} {signed(value)}'
                      f'<span>{label}</span></div>')

    cards = []
    for post in media:
        src = post.get("thumbnail_url") or post.get("media_url") or ""
        caption = re.sub(r"\s+", " ", (post.get("caption") or "")).strip()
        if not caption:
            caption = post.get("media_type", "post").replace("_", " ").lower()

        likes, comments = post.get("like_count"), post.get("comments_count")
        prev = previous.get(post["id"], {}).get("like_count")
        bump = ""
        if isinstance(prev, int) and isinstance(likes, int) and likes > prev:
            bump = f' <span class="bump">▲{likes - prev}</span>'

        when = ""
        if post.get("timestamp"):
            try:
                dt = datetime.fromisoformat(post["timestamp"].replace("+0000", "+00:00"))
                ago = (datetime.now(timezone.utc) - dt).days
                when = ("today" if ago == 0 else
                        f"{ago}d" if ago < 30 else dt.strftime("%b %Y"))
            except ValueError:
                pass

        kind = post.get("media_type", "")
        badge = ('<span class="badge">▶</span>' if kind == "VIDEO"
                 else '<span class="badge">❐</span>' if kind == "CAROUSEL_ALBUM"
                 else "")

        cards.append(f"""    <a class="card" data-external href="{h(post.get('permalink', '#'))}">
      <div class="thumb">{f'<img src="{h(src)}" loading="lazy" alt="">' if src else ''}{badge}</div>
      <div class="body">
        <div class="caption">{h(caption)}</div>
        <div class="stats"><span>♥ <b>{fmt(likes)}</b>{bump}</span>
          <span>✎ <b>{fmt(comments)}</b></span><span class="when">{h(when)}</span></div>
      </div>
    </a>""")

    spark = sparkline_svg(history)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>@{h(uname)}</title>
<style>{GALLERY_CSS}</style></head>
<body>
  <div class="tile">
    <div>
      <div class="who">@{h(uname)}</div>
      <div class="hero">{fmt(followers)}<small>followers</small></div>
    </div>
    <div class="deltas">{''.join(deltas)}</div>
    <div class="acts">
      <a href="swiftbar://refreshplugin?name={h(plugin_name)}">Refresh</a>
      <a data-external href="https://instagram.com/{h(uname)}">Instagram</a>
    </div>
    {f'<div class="spark">{spark}<div class="tip"></div></div>' if spark else ''}
  </div>
  {history_table(history)}
  <div class="grid">
{ln.join(cards)}
  </div>
  <footer>{fmt(profile.get('media_count'))} posts · following
    {fmt(profile.get('follows_count'))} — updated {datetime.now():%d %b %Y, %H:%M}.
    Clicking a post opens it in your browser.</footer>
  <script>{GALLERY_JS}</script>
</body></html>
"""


def plugin_name():
    """SwiftBar identifies a plugin by the part of the filename before the dot."""
    try:
        return os.path.basename(__file__).split(".")[0] or "instawatch"
    except NameError:
        return "instawatch"


def write_gallery(profile, media, history, previous):
    try:
        with open(GALLERY_PATH, "w", encoding="utf-8") as fh:
            fh.write(gallery_html(profile, media, history, previous, plugin_name()))
        return GALLERY_PATH
    except OSError as exc:
        log(f"gallery write failed: {exc}")
        return None


def gallery_params(config, path):
    """
    In browser mode this is a plain href, which SwiftBar hands to the system —
    the page opens in Safari and every link inside it behaves like a link.
    In panel mode we add the webview flags instead.
    """
    href = f"href=file://{urllib.parse.quote(path)}"
    if config.get("gallery_mode", "browser") == "panel":
        return (f"{href} webview=true "
                f"webvieww={int(config.get('gallery_width', 980))} "
                f"webviewh={int(config.get('gallery_height', 760))}")
    return href


def render_error(message):
    return [
        "◎ ⚠︎",
        "---",
        f"{esc(message)} | color=#cc4400 length=60",
        "---",
        "Retry | refresh=true",
        f"Open log | href=file://{LOG_PATH}",
    ]


# --------------------------------------------------------------------------

SAMPLE = (
    {"username": "josefchladek", "followers_count": 24962,
     "follows_count": 312, "media_count": 1987},
    [{"id": "a", "caption": "Daido Moriyama — Farewell Photography, 1972\nreissue",
      "media_type": "IMAGE", "permalink": "https://instagram.com/p/aaa",
      "timestamp": "2026-08-17T09:00:00+0000", "like_count": 214, "comments_count": 9},
     {"id": "b", "caption": "", "media_type": "CAROUSEL_ALBUM",
      "permalink": "https://instagram.com/p/bbb",
      "timestamp": "2026-07-02T09:00:00+0000", "like_count": 88, "comments_count": 3}],
)


def main():
    config = {**DEFAULTS, **load_json(CONFIG_PATH, {})}
    history = load_json(HISTORY_PATH, {"followers": {}, "media": {}})
    previous_media = dict(history.get("media", {}))

    if "--selftest" in sys.argv:
        profile, media = SAMPLE
        today = date.today()
        history["followers"] = {
            (today - timedelta(days=i)).isoformat(): 24962 - i * 11 for i in range(31)
        }
        print("\n".join(render(profile, media, history, config, {})))
        return

    try:
        token = get_token()
        if not token:
            print("\n".join(render_error(
                "No access token in Keychain — run: security add-generic-password "
                "-U -s instawatch-ig-token -a $USER -w <token>")))
            return

        token = maybe_refresh_token(token, history)
        profile = api_get("me", token,
                          fields="user_id,username,account_type,followers_count,"
                                 "follows_count,media_count")
        media = api_get("me/media", token,
                        fields="id,caption,media_type,permalink,timestamp,"
                               "like_count,comments_count,media_url,thumbnail_url",
                        limit=int(config.get("media_limit", 8))).get("data", [])

        record(history, profile, media, config)
        print("\n".join(render(profile, media, history, config, previous_media)))

    except ApiError as exc:
        log(f"API error: {exc}")
        print("\n".join(render_error(str(exc))))
    except Exception as exc:  # noqa: BLE001
        log(f"unexpected: {type(exc).__name__}: {exc}")
        print("\n".join(render_error(f"{type(exc).__name__}: {exc}")))


if __name__ == "__main__":
    main()
