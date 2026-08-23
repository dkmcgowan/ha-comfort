"""Generate the Home Assistant brand images from the Comfort app's artwork.

Home Assistant 2026.3 and newer serve brand images out of the integration
itself, from a `brand/` folder, so an integration no longer has to be
accepted into the home-assistant/brands repository to have an icon. Without
these files the integration shows a blank placeholder everywhere.

Source artwork is the app's own launcher icon and wordmark, taken from the
decompiled APK's resources. The launcher icon is an Android adaptive icon,
which means a separate background and foreground layer that have to be
composited before anything looks right.

The wordmark is white with a transparent background, which would vanish
against Home Assistant's light theme, so the app's own navy is baked in
behind it.

Usage:

    python scripts/make_brand_assets.py <path to decompiled res directory>

Requires Pillow, which is a development-only dependency; the integration
itself has no requirements.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

try:
    from PIL import Image
except ImportError:  # pragma: no cover - developer tooling only
    sys.exit("This script needs Pillow: pip install pillow")

OUT = pathlib.Path(__file__).parent.parent / "custom_components" / "kumo_cloud" / "brand"


def build_icon(res: pathlib.Path) -> Image.Image:
    """Composite the adaptive launcher icon into a single square image."""
    background = Image.open(res / "mipmap-xxxhdpi" / "ic_launcher_background.png").convert("RGBA")
    foreground = Image.open(res / "mipmap-xxxhdpi" / "ic_launcher_foreground.png").convert("RGBA")
    return Image.alpha_composite(background, foreground)


def build_logo(res: pathlib.Path, icon: Image.Image) -> Image.Image:
    """Put the white wordmark on the icon's own background color."""
    logo = Image.open(res / "drawable-xxhdpi" / "images_comfortapplogo.png").convert("RGBA")
    # Sample the icon's corner rather than hardcoding a navy that might drift
    # if the app is re-skinned.
    backdrop_color = icon.getpixel((4, 4))
    padding = 24
    canvas = Image.new(
        "RGBA",
        (logo.width + padding * 2, logo.height + padding * 2),
        backdrop_color,
    )
    canvas.alpha_composite(logo, (padding, padding))
    return canvas


def fit(image: Image.Image, box: tuple[int, int]) -> Image.Image:
    """Scale to fit inside box, preserving aspect ratio.

    Unlike `Image.thumbnail` this scales up as well as down, so the @2x file
    really is twice the size of the 1x one. The wordmark source is smaller
    than 2x, so that step is a mild upscale.
    """
    ratio = min(box[0] / image.width, box[1] / image.height)
    size = (max(1, round(image.width * ratio)), max(1, round(image.height * ratio)))
    return image.resize(size, Image.LANCZOS)


def main() -> int:
    """Write the four brand files."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "res",
        type=pathlib.Path,
        nargs="?",
        default=pathlib.Path.home() / "kumocloud-decompiled/app/src/main/res",
    )
    args = parser.parse_args()

    if not args.res.is_dir():
        sys.exit(f"not a directory: {args.res}")

    OUT.mkdir(parents=True, exist_ok=True)

    icon = build_icon(args.res)
    # Home Assistant wants exactly 256 and 512 square.
    icon.resize((256, 256), Image.LANCZOS).save(OUT / "icon.png")
    icon.resize((512, 512), Image.LANCZOS).save(OUT / "icon@2x.png")

    logo = build_logo(args.res, icon)
    fit(logo, (512, 256)).save(OUT / "logo.png")
    fit(logo, (1024, 512)).save(OUT / "logo@2x.png")

    for path in sorted(OUT.glob("*.png")):
        with Image.open(path) as written:
            print(f"  {written.size[0]:>4}x{written.size[1]:<4} {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
