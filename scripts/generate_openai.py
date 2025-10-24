#!/usr/bin/env python3
import os, json, argparse, pathlib, textwrap
from datetime import datetime

# Minimal OpenAI image generation using REST to avoid SDK dependency surprise
# Requires: environment variable OPENAI_API_KEY

import base64
import urllib.request

DEFAULT_MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1")


def request_openai_image(prompt: str, size: str = "1024x1024") -> bytes:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")

    data = json.dumps({
        "model": DEFAULT_MODEL,
        "prompt": prompt,
        "size": size,
        "response_format": "b64_json"
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.openai.com/v1/images/generations",
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
        b64 = payload["data"][0]["b64_json"]
        return base64.b64decode(b64)


def load_brief() -> dict:
    brief_path = pathlib.Path("brand/brief.yaml")
    if not brief_path.exists():
        return {}
    return brief_path.read_text()


def assemble_color_keywords(brief_text: str) -> str:
    # crude pull from yaml text to avoid pyyaml dependency
    lines = [ln.strip() for ln in brief_text.splitlines()]
    colors = []
    capture = False
    for ln in lines:
        if ln.startswith("color_palette:"):
            capture = True
            continue
        if capture and ln and not ln.startswith("#"):
            if ln.startswith("typography:") or ln.startswith("logo:"):
                break
            if ln.startswith("-"):
                colors.append(ln.lstrip("- ").split()[0])
    if not colors:
        return "deep teal, cyan, navy, warm sand, coral"
    return ", ".join(colors[:5])


def read_prompt_templates() -> list[str]:
    pdir = pathlib.Path("prompts/openai")
    if not pdir.exists():
        return []
    prompts = []
    for p in sorted(pdir.glob("*.txt")):
        prompts.append(p.read_text())
    return prompts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="assets/out", help="Output directory")
    parser.add_argument("--size", default="1024x1024", help="Image size WxH")
    parser.add_argument("--count", type=int, default=8, help="Number of concepts")
    parser.add_argument("--brand-name", default=None, help="Override brand name")
    args = parser.parse_args()

    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    brief_text = load_brief() or ""
    brand_name = args.brand_name or "Sealab Studios"
    color_keywords = assemble_color_keywords(brief_text)
    templates = read_prompt_templates()
    if not templates:
        templates = [
            "Design a flat, vector-like minimal ocean-tech symbol for {brand_name}. No text. Use {color_keywords}. 1:1 centered composition.",
        ]

    generated = 0
    idx = 0
    now = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    for template in templates:
        if generated >= args.count:
            break
        prompt = template.format(brand_name=brand_name, color_keywords=color_keywords)
        try:
            img_bytes = request_openai_image(prompt, size=args.size)
        except Exception as e:
            print(f"ERROR: generation failed: {e}")
            break
        fname = out_dir / f"logo_{now}_{idx:02d}.png"
        with open(fname, "wb") as f:
            f.write(img_bytes)
        meta = {
            "prompt": prompt,
            "model": DEFAULT_MODEL,
            "size": args.size,
            "brand": brand_name,
        }
        with open(out_dir / f"logo_{now}_{idx:02d}.json", "w") as jf:
            json.dump(meta, jf, indent=2)
        print(f"wrote {fname}")
        generated += 1
        idx += 1
        if generated < args.count and len(templates) == 1:
            # vary with lightweight chaos
            templates.append(prompt + " -- add variation focusing on negative space rings")


if __name__ == "__main__":
    main()
