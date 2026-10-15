"""Smoke test for a running CoreYield: the frontend (Firebase Hosting) and the API (Cloud Run).

Read-only: it never records a decision. The one POST it sends has no engineer name, which the
decision rules must refuse (HTTP 400). --chat also asks the agents one question (calls Gemini,
a few cents). Exit code 0 only if every check passes.

Run:  python scripts/smoke_test.py --frontend https://coreyield.web.app \\
                                   --api https://coreyield-XXXX.asia-south1.run.app [--chat]
      python scripts/smoke_test.py --frontend http://localhost:8080      (one server for both)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request


def fetch(url: str, body: dict | None = None, timeout: float = 30) -> tuple[int, str, float]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"} if data else {})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace"), time.monotonic() - t0
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), time.monotonic() - t0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--frontend", required=True, help="where the page is served (Firebase Hosting URL)")
    ap.add_argument("--api", help="Cloud Run URL; defaults to the frontend (API reached through its rewrite)")
    ap.add_argument("--chat", action="store_true", help="also ask the agents one question (calls Gemini)")
    a = ap.parse_args()
    fe, api = a.frontend.rstrip("/"), (a.api or a.frontend).rstrip("/")
    results: list[tuple[bool, str, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((bool(ok), name, detail))

    s, page, t = fetch(fe + "/")
    check("frontend page", s == 200 and 'class="brand-name">CoreYield<' in page and "DEMO DATA" in page, f"{s} in {t:.2f}s")
    for asset in ("/static/app.js", "/static/styles.css"):
        s, _, t = fetch(fe + asset)
        check(f"frontend {asset}", s == 200, f"{s} in {t:.2f}s")

    bases = [("api", api)] + ([("api via frontend rewrite", fe)] if fe != api else [])
    for label, base in bases:
        s, body, t = fetch(base + "/health")
        check(f"{label}: /health", s == 200 and json.loads(body).get("ok") is True, f"{s} in {t:.2f}s")
        s, body, t = fetch(base + "/api/month")
        m = json.loads(body) if s == 200 else {}
        mo = m.get("month", {})
        check(f"{label}: /api/month", s == 200 and len(m.get("vehicles", [])) == 12 and "gap_closed_pct" in mo,
              f"{s} in {t:.2f}s; gap closed {mo.get('gap_closed_pct')}%, blocked {mo.get('blocked_before_dismantling')}")

    for path, test in (("/api/vehicles/V05", lambda d: d.get("vehicle_id") == "V05" and d["value"]["offer"] > 0),
                       ("/api/rules", lambda d: len(d.get("rules", [])) == 20),
                       ("/api/inbox", lambda d: "reviews" in d and "recent" in d),
                       ("/api/decisions", lambda d: "count" in d)):
        s, body, t = fetch(api + path)
        try:
            ok = s == 200 and test(json.loads(body))
        except (ValueError, KeyError, TypeError):
            ok = False
        check(path, ok, f"{s} in {t:.2f}s")

    s, body, _ = fetch(api + "/api/decisions", {"engineer": "", "kind": "sign_off", "vehicle_id": "V01", "action": "sign"})
    check("a decision without a name is refused (nothing written)", s == 400, f"{s}")

    if a.chat:
        s, body, t = fetch(fe + "/api/chat", {"question": "Why is the starter on V05 waiting for an engineer?"}, timeout=90)
        d = json.loads(body) if body.startswith("{") else {}
        check("agents answer through the frontend (Gemini)", s == 200 and "STR-03" in d.get("answer", "")
              and d.get("ungrounded") == [], f"{s} in {t:.1f}s; tools {d.get('tools')}; ungrounded {d.get('ungrounded')}")

    width = max(len(n) for _, n, _ in results)
    for ok, name, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<{width}}  {detail}")
    failed = sum(not ok for ok, _, _ in results)
    print(f"\n{len(results) - failed}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
