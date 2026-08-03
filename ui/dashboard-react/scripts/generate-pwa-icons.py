from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "assets" / "brand-rose-violet.png"
OUTPUT = ROOT / "assets" / "pwa"


def shell_background(size: int) -> Image.Image:
    image = Image.new("RGB", (size, size), (27, 28, 34))
    pixels = image.load()
    for y in range(size):
        for x in range(size):
            radial_distance = (((x / size - 0.5) ** 2 + (y / size - 0.52) ** 2) ** 0.5)
            radial = max(0.0, 1.0 - radial_distance / 0.63) * 0.18
            diagonal = min(1.0, max(0.0, (x + y) / (size * 2)))
            linear_alpha = 0.10 * (1.0 - diagonal) + 0.02 * diagonal
            linear_color = (
                round(196 * (1.0 - diagonal) + 109 * diagonal),
                round(125 * (1.0 - diagonal) + 53 * diagonal),
                round(255 * (1.0 - diagonal) + 181 * diagonal),
            )
            base = pixels[x, y]
            after_linear = tuple(round(base[i] * (1.0 - linear_alpha) + linear_color[i] * linear_alpha) for i in range(3))
            pixels[x, y] = tuple(round(after_linear[i] * (1.0 - radial) + (196, 125, 255)[i] * radial) for i in range(3))

    return image


def render(size: int, destination: str) -> None:
    source = Image.open(SOURCE).convert("RGBA")
    logo = source.resize((size, size), Image.Resampling.LANCZOS)
    canvas = shell_background(size).convert("RGBA")
    canvas.alpha_composite(logo, (0, 0))
    canvas.convert("RGB").save(OUTPUT / destination, optimize=True)


OUTPUT.mkdir(parents=True, exist_ok=True)
for size, legacy_name, versioned_name in (
    (32, "favicon-32.png", "ayserose-plain-v4-32.png"),
    (180, "apple-touch-icon-180.png", "ayserose-plain-v4-180.png"),
    (192, "icon-192.png", "ayserose-plain-v4-192.png"),
    (512, "icon-512.png", "ayserose-plain-v4-512.png"),
    (512, "icon-maskable-512.png", "ayserose-plain-v4-maskable-512.png"),
):
    render(size, legacy_name)
    render(size, versioned_name)
