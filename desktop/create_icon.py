"""Generate the Relay desktop icon without external source artwork."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


def create(path: Path) -> None:
    sizes = (16, 24, 32, 48, 64, 128, 256)
    images = []
    for size in sizes:
        image = Image.new("RGBA", (size, size), (13, 20, 32, 255))
        draw = ImageDraw.Draw(image)
        pad = max(1, size // 12)
        draw.rounded_rectangle(
            (pad, pad, size - pad, size - pad),
            radius=max(3, size // 6),
            fill=(107, 167, 243, 255),
        )
        inset = max(2, size // 4)
        line = max(1, size // 16)
        for row in range(3):
            top = inset + row * max(3, size // 7)
            right = size - inset - (size // 10 if row == 2 else 0)
            draw.rounded_rectangle(
                (inset, top, right, top + line),
                radius=max(1, line // 2),
                fill=(13, 20, 32, 255),
            )
        images.append(image)
    path.parent.mkdir(parents=True, exist_ok=True)
    images[-1].save(path, format="ICO", sizes=[(size, size) for size in sizes], append_images=images[:-1])
    images[-1].save(path.with_suffix(".png"), format="PNG")


if __name__ == "__main__":
    create(Path(__file__).resolve().with_name("relay.ico"))
