# InstaMenuBar

Your Instagram follower count in the macOS menu bar, and your latest posts one
click away — without the Instagram app on your phone.

```
◎ 24.9k        ← the menu bar
```

Clicking it opens a gallery: follower count, deltas for today / 7 days /
30 days, a 30-day sparkline, and your latest 20 posts as image cards with like
and comment counts. Clicking a post opens it on Instagram.

A macOS notification fires whenever the follower count changes.

Built on the official [Instagram API with Instagram Login][api] — no scraping,
no third-party service, no account credentials anywhere. The only thing that
leaves your Mac is an authenticated API call to Meta.

[api]: https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login

---

## How it works

It's a [SwiftBar][swiftbar] plugin: a single Python script that prints text,
which SwiftBar renders as a menu bar item. **Python standard library only** — no
`pip install`, no virtualenv, no AppKit bindings. Thumbnails are resized with
`sips`, which ships with macOS.

[swiftbar]: https://github.com/swiftbar/SwiftBar

```
menu bar item  ──▶  gallery.html  ──▶  instagram.com
     ▲                   ▲
     └── instawatch.30m.py ──▶ graph.instagram.com
                │
                └── ~/.instawatch/{config,history}.json
```

State lives in `~/.instawatch/`. The access token lives in your login Keychain,
never in a file.

## Requirements

- macOS
- [SwiftBar](https://github.com/swiftbar/SwiftBar) (the installer will fetch it
  via Homebrew if it's missing)
- An Instagram **Professional** account (Business or Creator). Personal accounts
  cannot report `followers_count` through the API — you can switch type at
  instagram.com → Settings → Account type and tools.

## Getting a token

One-time, about five minutes. No App Review, no Facebook Page.

1. **Create a Meta app** at <https://developers.facebook.com/apps> → *Create app*.
   Use case: **Other** → app type: **Business**.
2. **Add the Instagram product** → open *API setup with Instagram business login*.
3. **Add the Instagram Tester role.** App Roles → Roles → Add People →
   **Instagram Tester** → your username. This step is easy to miss and causes an
   `Insufficient developer role` error later if you skip it.
4. **Accept the invitation** at
   <https://www.instagram.com/accounts/manage_access/> → *Tester Invites*, while
   logged in as that account.
5. Back in *API setup with Instagram business login* → **Add account**, log in,
   approve → **Generate token**. Copy it; it's shown once.

That's a long-lived token, valid 60 days. InstaMenuBar refreshes it
automatically at ~50 days, so in practice you paste it once.

Only the `instagram_business_basic` scope is needed, and it's granted
immediately while the app is in development mode.

## Install

```bash
git clone https://github.com/josefchl/InstaMenuBar.git
cd InstaMenuBar
./install.sh
```

The installer verifies your token against the API before saving it, stores it in
the Keychain, installs the plugin, and starts SwiftBar. Enable *Launch at Login*
in SwiftBar's preferences to have it come back after a reboot.

Change the refresh interval by renaming the plugin file — `instawatch.30m.py` →
`instawatch.10m.py` for every ten minutes.

## Configuration

`~/.instawatch/config.json`, read on every refresh:

| key | default | meaning |
|---|---|---|
| `title_mode` | `"compact"` | `compact` → `◎ 24.9k`, `count` → `◎ 24 962`, `full` adds today's delta |
| `default_view` | `"gallery"` | `gallery` opens the gallery on click; `menu` shows a dropdown instead |
| `gallery_mode` | `"browser"` | `browser` opens in your browser; `panel` uses SwiftBar's webview (see Notes) |
| `media_limit` | `20` | how many recent posts to show |
| `caption_chars` | `64` | caption truncation in the dropdown |
| `show_thumbnails` | `true` | thumbnails in the dropdown |
| `thumbnail_px` | `64` | source size of dropdown thumbnails |
| `gallery_width` / `gallery_height` | `980` / `760` | panel size in `panel` mode |
| `notify_on_follower_change` | `true` | notify when the count moves |
| `notify_on_new_likes` | `false` | also notify when a post gains likes |

## Files

```
~/.instawatch/config.json     settings
~/.instawatch/history.json    daily follower counts (rolling year) + last-seen likes
~/.instawatch/gallery.html    regenerated on every refresh
~/.instawatch/thumbs/         cached thumbnails, pruned to the current posts
~/.instawatch/instawatch.log  log
```

Token: Keychain, service `instawatch-ig-token`. Read it back with
`security find-generic-password -s instawatch-ig-token -w`.

## Notes and limitations

**Menu images are small and can't be made bigger.** AppKit fits a menu item's
image to the row height, and row height comes from the text. Increasing the font
does not enlarge the image; SwiftBar exposes no parameter for it. That's why the
big view is a page, not a menu.

**`gallery_mode: "panel"` can't open links externally.** SwiftBar's webview is a
bare `WKWebView` with no UI delegate, so `window.open` returns null and
`target="_blank"` has nowhere to go. In panel mode a post click navigates the
panel in place. Browser mode is the default for this reason.

**Likes are sometimes missing.** `like_count` is omitted for media where like
counts are hidden, and isn't available for stories.

**The API exposes no follower identities.** Aggregate counts are all Meta
returns — no list of who followed or unfollowed you, no per-like identity. Any
service claiming otherwise is scraping.

**Rate limits** are around 200 calls per hour, so even a 5-minute interval is
comfortable. The default is 30 minutes.

## Troubleshooting

Run the plugin directly — it prints its output, and errors, to the terminal:

```bash
~/.instawatch/instawatch.30m.py
./instawatch.30m.py --selftest    # render with sample data, no API call
```

| Symptom | Cause |
|---|---|
| `Insufficient developer role` | The Instagram Tester invitation wasn't accepted (step 4 above). |
| `Unsupported get request` | The account is still a personal account, or the token belongs to a different one. |
| Nothing in the menu bar | Check SwiftBar is running (`pgrep -x SwiftBar`). If you use a menu bar manager such as Bartender or Ice, new items are often hidden by default — check its settings. |
| Token expired | Auto-refresh needs the plugin to run at least once every 60 days. If it lapsed, generate a new token and re-run `./install.sh`. |

## Uninstall

```bash
rm "$HOME/Library/Application Support/SwiftBar/Plugins/instawatch.30m.py"
rm -rf ~/.instawatch
security delete-generic-password -s instawatch-ig-token
```

## License

MIT — see [LICENSE](LICENSE).
