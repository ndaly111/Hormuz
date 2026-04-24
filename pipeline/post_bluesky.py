"""
Posts the daily Hormuz transit chart + caption to Bluesky.

Reuses the existing /today page's share-image generator (today.js
`generateShareImage()`) and caption builder (`buildTweetText()`) so the
post matches the on-site share kit byte-for-byte — no duplicate design
logic to drift.

Flow:
  1. Start a local HTTP server over the site/ directory
  2. Launch headless chromium, load today.html, wait for init
  3. Extract the generated PNG (data URL) and caption text
  4. Post to Bluesky via atproto with image embed + clickable URL

Env:
  BLUESKY_HANDLE         default: hormuz-traffic.bsky.social
  BLUESKY_APP_PASSWORD   required unless --dry-run (from GitHub secret)
  SHARE_RANGE_KEY        default: d30   (one of d7/d30/closure/war/all)

CLI flags:
  --dry-run    render image + log caption, skip the actual Bluesky post.
               Writes PNG to pipeline/_latest_share.png for local preview.
"""
from __future__ import annotations

import argparse
import base64
import os
import socket
import sys
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SITE_DIR = ROOT / "site"

HANDLE = os.environ.get("BLUESKY_HANDLE", "hormuz-traffic.bsky.social")
APP_PASSWORD = os.environ.get("BLUESKY_APP_PASSWORD")
RANGE_KEY = os.environ.get("SHARE_RANGE_KEY", "war")
SITE_URL = "https://hormuz-traffic.com"
SITE_LABEL = "hormuz-traffic.com"


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _QuietHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(SITE_DIR), **kwargs)

    def log_message(self, *_args, **_kwargs):
        pass


def _start_server() -> tuple[HTTPServer, int]:
    port = _pick_free_port()
    srv = HTTPServer(("127.0.0.1", port), _QuietHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, port


def capture_share_assets(port: int) -> tuple[bytes, str]:
    """Return (png_bytes, caption) from a live render of today.html."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": 1400, "height": 1000})
        page = context.new_page()
        page.goto(f"http://127.0.0.1:{port}/today.html", wait_until="networkidle")

        # Select requested range before image generation. today.js init()
        # defaults to d30, so we always click the requested range button
        # unless it happens to equal d30.
        if RANGE_KEY != "d30":
            page.evaluate(f"""(async () => {{
              document.querySelectorAll('.share-range-buttons .range-btn')
                .forEach(b => b.classList.remove('active'));
              const btn = document.querySelector(
                `.share-range-buttons .range-btn[data-range='{RANGE_KEY}']`);
              if (btn) {{ btn.classList.add('active'); btn.click(); }}
            }})()""")

        # Wait for share image to be ready
        page.wait_for_function(
            "document.getElementById('shareImage') && "
            "document.getElementById('shareImage').src && "
            "document.getElementById('shareImage').src.startsWith('data:image/png')",
            timeout=30000,
        )

        data_url = page.evaluate("() => document.getElementById('shareImage').src")
        caption = page.evaluate("() => document.getElementById('tweetText').value")
        browser.close()

    png_bytes = base64.b64decode(data_url.split(",", 1)[1])
    return png_bytes, caption.strip()


def post(png_bytes: bytes, caption: str) -> str:
    if not APP_PASSWORD:
        raise RuntimeError("BLUESKY_APP_PASSWORD not set")

    # Lazy import so --dry-run works without atproto installed
    from atproto import Client, client_utils, models

    client = Client()
    client.login(HANDLE, APP_PASSWORD)

    blob = client.upload_blob(png_bytes)

    tb = client_utils.TextBuilder()
    tb.text(caption)
    tb.text("\n\n")
    tb.link(SITE_LABEL, SITE_URL)

    alt = "Hormuz Strait daily vessel transit chart. Source: IMF PortWatch."
    response = client.send_post(
        text=tb,
        embed=models.AppBskyEmbedImages.Main(
            images=[models.AppBskyEmbedImages.Image(alt=alt, image=blob.blob)]
        ),
    )
    return response.uri


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Render + log caption, skip Bluesky post")
    args = parser.parse_args()

    if not args.dry_run and not APP_PASSWORD:
        print("ERROR: BLUESKY_APP_PASSWORD env var not set", file=sys.stderr)
        return 2

    srv, port = _start_server()
    try:
        print(f"Local server on :{port}, rendering today.html (range={RANGE_KEY})")
        png, caption = capture_share_assets(port)
        print(f"  PNG: {len(png):,} bytes   Caption: {caption!r}")

        if args.dry_run:
            out = ROOT / "pipeline" / "_latest_share.png"
            out.write_bytes(png)
            print(f"DRY RUN — PNG saved to {out}, not posting.")
            return 0

        uri = post(png, caption)
        print(f"Posted to Bluesky: {uri}")
        return 0
    finally:
        srv.shutdown()


if __name__ == "__main__":
    sys.exit(main())
