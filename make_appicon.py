#!/usr/bin/env python3
"""
Generate InstaMenuBar.icns — the icon macOS shows when the app is NOT running.

While running, the app draws the live follower count into its Dock tile. Quit
it and macOS falls back to the bundle's icon file; without one you get a blank
grey placeholder. This is that file.

Drawn at 4x and downsampled so the strokes stay clean at every size.
"""

import io

from PIL import Image, ImageDraw

S = 1024
SS = 4                      # supersample factor
BG = (22, 24, 28, 255)      # matches the gallery surface
FG = (255, 255, 255, 255)


def squircle(draw, box, radius, fill):
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def build():
    n = S * SS
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # macOS app icons sit in a rounded square inset from the canvas edge.
    inset = int(n * 0.10)
    squircle(d, (inset, inset, n - inset, n - inset),
             radius=int(n * 0.185), fill=BG)

    # Camera glyph, same language as the menu bar icon.
    cx = cy = n / 2
    body = n * 0.235                      # half-width of the camera body
    stroke = int(n * 0.030)
    d.rounded_rectangle((cx - body, cy - body, cx + body, cy + body),
                        radius=int(n * 0.085), outline=FG, width=stroke)

    lens = n * 0.108
    d.ellipse((cx - lens, cy - lens, cx + lens, cy + lens),
              outline=FG, width=stroke)

    flash = n * 0.028
    fx, fy = cx + body * 0.60, cy - body * 0.60
    d.ellipse((fx - flash, fy - flash, fx + flash, fy + flash), fill=FG)

    return img.resize((S, S), Image.LANCZOS)


def main():
    master = build()
    master.save("InstaMenuBar.png")
    # Pillow writes .icns directly; it needs the standard size ladder.
    sizes = [(16, 16), (32, 32), (64, 64), (128, 128), (256, 256), (512, 512),
             (1024, 1024)]
    master.save("InstaMenuBar.icns", format="ICNS", sizes=sizes)
    print("wrote InstaMenuBar.png and InstaMenuBar.icns")


if __name__ == "__main__":
    main()
