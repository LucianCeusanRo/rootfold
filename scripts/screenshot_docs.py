#!/usr/bin/env python3
"""Capture the Swagger UI at /api/docs into docs/screenshots/swagger.png."""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000/api/docs"
OUT = Path(__file__).resolve().parents[1] / "docs" / "screenshots" / "swagger.png"
OUT.parent.mkdir(parents=True, exist_ok=True)


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(URL, wait_until="networkidle", timeout=30_000)
        # Wait for Swagger UI to render the API title.
        page.wait_for_selector("text=Rootfold", timeout=15_000)
        page.screenshot(path=str(OUT), full_page=True)
        browser.close()
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
