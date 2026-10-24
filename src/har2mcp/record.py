"""`har2mcp record <url>`: capture a HAR with a real Chromium via Playwright."""

from __future__ import annotations

import sys


def record(url: str, output: str, headless: bool = False, wait: float | None = None) -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("record needs Playwright:  pip install 'har2mcp[record]' && playwright install chromium", file=sys.stderr)
        return 2
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx = browser.new_context(record_har_path=output, record_har_content="embed")
        page = ctx.new_page()
        page.goto(url, wait_until="networkidle")
        if wait is not None:
            page.wait_for_timeout(int(wait * 1000))
        else:
            print(f"Recording {url}. Log in and click around, then press Enter here to save {output}.")
            try:
                input()
            except EOFError:
                pass
        ctx.close()
        browser.close()
    print(f"✓ saved {output}. Next:  har2mcp {output}")
    return 0
