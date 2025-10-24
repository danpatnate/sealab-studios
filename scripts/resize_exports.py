#!/usr/bin/env python3
import argparse, pathlib, subprocess, sys
from typing import List

# Uses pillow if available; otherwise falls back to imagemagick `convert` if present.

SIZES = [2048, 1024, 512, 256, 128]


def pillow_available() -> bool:
    try:
        import PIL  # type: ignore
        return True
    except Exception:
        return False


def resize_with_pillow(src: pathlib.Path, out_dir: pathlib.Path, sizes: List[int]) -> None:
    from PIL import Image  # type: ignore
    img = Image.open(src)
    for size in sizes:
        im = img.copy()
        im = im.convert("RGBA")
        im = im.resize((size, size), Image.LANCZOS)
        out = out_dir / f"{src.stem}_{size}.png"
        im.save(out, format="PNG")
        webp = out_dir / f"{src.stem}_{size}.webp"
        im.save(webp, format="WEBP", quality=92, method=6)
        print(f"wrote {out}")
        print(f"wrote {webp}")


def has_convert() -> bool:
    from shutil import which
    return which("convert") is not None


def resize_with_convert(src: pathlib.Path, out_dir: pathlib.Path, sizes: List[int]) -> None:
    for size in sizes:
        out = out_dir / f"{src.stem}_{size}.png"
        cmd = ["convert", str(src), "-resize", f"{size}x{size}", str(out)]
        subprocess.check_call(cmd)
        print(f"wrote {out}")
        webp = out_dir / f"{src.stem}_{size}.webp"
        cmd2 = ["convert", str(out), "-quality", "92", str(webp)]
        subprocess.check_call(cmd2)
        print(f"wrote {webp}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="Path to source PNG")
    parser.add_argument("--out", default="assets/out", help="Output directory")
    parser.add_argument("--sizes", default=",".join(map(str, SIZES)), help="Comma-separated sizes")
    args = parser.parse_args()

    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    sizes = [int(s) for s in args.sizes.split(",") if s]
    src = pathlib.Path(args.input)
    if not src.exists():
        print(f"ERROR: input not found: {src}", file=sys.stderr)
        sys.exit(1)

    if pillow_available():
        resize_with_pillow(src, out_dir, sizes)
    elif has_convert():
        resize_with_convert(src, out_dir, sizes)
    else:
        print("ERROR: neither pillow nor imagemagick convert is available. Install pillow: pip install pillow", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
