Logo design with 3rd‑party image tools

This repo sets you up to generate clean, minimal, ocean‑tech logo marks for `Sealab Studios` (or your brand) using external tools such as OpenAI Images, Midjourney, Stable Diffusion (ComfyUI), Leonardo, and Ideogram. It includes:

- `brand/brief.yaml`: brand brief (name, tone, colors, motifs)
- `prompts/*`: curated provider‑specific prompts/templates
- `scripts/generate_openai.py`: generate concepts via OpenAI Images
- `scripts/resize_exports.py`: export PNG/WebP in multiple sizes
- `assets/out/`: output folder for images and metadata

Quick start

1) Install Python deps (for resizing and OpenAI path)

```bash
pip3 install -r requirements.txt
```

2) OpenAI route (if you have a key)

```bash
export OPENAI_API_KEY=...  # your key
# optional: export OPENAI_IMAGE_MODEL=gpt-image-1
python3 scripts/generate_openai.py --count 8 --size 1024x1024 --brand-name "Sealab Studios"
# outputs PNG+JSON to assets/out
```

3) Midjourney route

- Open `prompts/midjourney/minimal_symbol.txt`
- Paste it after `/imagine` in Discord. Suggested flags are already included: `--ar 1:1 --v 6 --style raw --chaos 15`.
- Upscale the best options and download.

4) Stable Diffusion (ComfyUI) route

- See `prompts/stable-diffusion/comfyui_workflow.md` for sampler/CFG/negative prompts.
- Use SDXL or SD1.5 with a vector‑style LoRA. Output at 1024×1024.

5) Leonardo and Ideogram

- Use the text prompts in `prompts/leonardo/prompt.txt` and `prompts/ideogram/prompt.txt` as your base.

6) Resize exports (PNG + WebP)

- For a single image:

```bash
python3 scripts/resize_exports.py assets/out/logo_YYYYMMDDTHHMMSSZ_00.png
```

- For all PNGs in the folder:

```bash
for f in assets/out/*.png; do python3 scripts/resize_exports.py "$f"; done
```

What makes these prompts work

- Mark‑only symbols (no text), flat/vector‑like, strong negative space
- Ocean‑tech motifs: sonar rings, wave interference, bathymetry lines, nautilus spiral, geometric "S" monogram
- High‑contrast, centered 1:1 compositions, solid backgrounds, no gradients/shadows

Customize the brand

- Edit `brand/brief.yaml` to change name, tone, colors, and motifs. The OpenAI generator lightly derives color keywords from this file. You can also directly tweak the prompt templates in `prompts/*`.

Outputs

- Concepts are written to `assets/out/` as `logo_<timestamp>_<idx>.png` plus a matching `.json` recording the prompt and image settings.
