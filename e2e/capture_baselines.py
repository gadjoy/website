"""Capture the visual baselines (`make baselines`).

Separate from the test run on purpose: regenerating baselines is an explicit
act, never a side effect of a failing comparison. A gate that rewrites its own
expectation when it fails is not a gate.
"""
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def main() -> int:
    from playwright.sync_api import sync_playwright
    import conftest as C
    from test_screenshots import fingerprint, shoot

    C.BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    for stale in C.BASELINE_DIR.glob("*.png"):
        stale.unlink()

    # Reuse the session fixtures by driving them directly.
    port = C.free_port()
    import subprocess, tempfile, functools, http.server, threading
    out = Path(tempfile.mkdtemp(prefix="gadjoy-baseline-"))
    build = subprocess.run(
        ["hugo", "--destination", str(out), "--baseURL", f"http://127.0.0.1:{port}/"],
        cwd=C.REPO_ROOT, capture_output=True, text=True)
    if build.returncode != 0:
        print(build.stderr[-2000:], file=sys.stderr)
        return 1

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(out))
    handler.func.log_message = lambda *a, **k: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for page_name in sorted(C.PAGES):
                for vp in sorted(C.VIEWPORTS):
                    dest = C.BASELINE_DIR / f"{page_name}-{vp}.png"
                    shoot(browser, f"http://127.0.0.1:{port}", page_name, vp, dest)
                    print(f"  captured {dest.name}")
            (C.BASELINE_DIR / "fingerprint.json").write_text(
                json.dumps(fingerprint(browser), indent=2) + "\n")
            browser.close()
    finally:
        srv.shutdown()

    print(f"\nBaselines in {C.BASELINE_DIR}. REVIEW THE IMAGES before committing — "
          f"they become the definition of correct.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
