"""Generate the Recall Radar logo (500x500 PNG).

Flat colour, no gradients or fine detail, so it stays legible when RapidAPI
scales it down to a ~32px avatar. The motif is a shield (safety, recalls)
containing radar sweep arcs and a locator dot (detection, monitoring).

    python listing-assets/make_logo.py
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw

SIZE = 500
SUPERSAMPLE = 4  # draw large, downsample once -> clean edges without antialias hacks

NAVY = (14, 32, 56)
WHITE = (255, 255, 255)
AMBER = (255, 176, 32)
OUT = os.path.join(os.path.dirname(__file__), "logo.png")


def shield_polygon(cx: float, cy: float, w: float, h: float) -> list[tuple[float, float]]:
    """A rounded-shoulder shield: flat top, straight sides, tapering to a point."""
    half = w / 2
    top = cy - h / 2
    bottom = cy + h / 2
    shoulder = top + h * 0.16
    waist = top + h * 0.55

    # Flat top. An apex at the centre reads as a notch once downscaled.
    points: list[tuple[float, float]] = [
        (cx - half, top),
        (cx + half, top),
        (cx + half, shoulder),
        (cx + half, waist),
    ]
    # Right side curving in to the tip.
    for i in range(1, 11):
        t = i / 10
        x = cx + half * (1 - t * t * 0.98)
        y = waist + (bottom - waist) * t
        points.append((x, y))
    # Mirror for the left side.
    for i in range(10, 0, -1):
        t = i / 10
        x = cx - half * (1 - t * t * 0.98)
        y = waist + (bottom - waist) * t
        points.append((x, y))
    points += [(cx - half, waist), (cx - half, shoulder)]
    return points


def build() -> Image.Image:
    s = SIZE * SUPERSAMPLE
    img = Image.new("RGB", (s, s), NAVY)
    d = ImageDraw.Draw(img)

    cx = cy = s / 2

    # Shield outline, drawn as a white shield with a navy inset so the mark
    # reads as a bold silhouette rather than a thin outline.
    shield_cy = cy * 1.02
    d.polygon(shield_polygon(cx, shield_cy, s * 0.64, s * 0.76), fill=WHITE)
    d.polygon(shield_polygon(cx, shield_cy, s * 0.64 - s * 0.070, s * 0.76 - s * 0.084), fill=NAVY)

    # Radar sweep: three concentric arcs opening up-right from a locator dot.
    # The arcs' bounding box spans [origin, origin + max_r], so the origin is
    # offset by half the radius to centre the group inside the shield body
    # rather than letting it drift into the right-hand taper.
    # Sits slightly above geometric centre: the shield tapers to a point, so
    # its visual mass is in the upper half and a centred mark looks low.
    max_r = s * 0.315
    origin_x = cx - max_r * 0.48
    origin_y = shield_cy + max_r * 0.40
    stroke = int(s * 0.034)

    for radius_factor in (0.42, 0.71, 1.0):
        r = max_r * radius_factor
        d.arc(
            [origin_x - r, origin_y - r, origin_x + r, origin_y + r],
            start=270, end=356, fill=AMBER, width=stroke,
        )

    # Locator dot at the sweep origin.
    dot = s * 0.044
    d.ellipse([origin_x - dot, origin_y - dot, origin_x + dot, origin_y + dot], fill=AMBER)

    return img.resize((SIZE, SIZE), Image.LANCZOS)


def main() -> None:
    logo = build()
    logo.save(OUT, "PNG", optimize=True)
    print(f"wrote {OUT} ({logo.size[0]}x{logo.size[1]}, mode={logo.mode})")

    # Legibility check: the mark must still read at avatar sizes.
    for px in (128, 64, 32):
        preview = logo.resize((px, px), Image.LANCZOS)
        path = OUT.replace(".png", f"-preview-{px}.png")
        preview.save(path, "PNG")
        print(f"  preview {px:>3}px -> {os.path.basename(path)}")


if __name__ == "__main__":
    main()
