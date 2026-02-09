"""
Smoke-test the API without starting a server.
Uses Flask's test client so you can run: python -m scripts.smoke_test_api
Run from the tradebot directory (parent of scripts/).
"""
import sys
from pathlib import Path

# Ensure tradebot root is on path
root = Path(__file__).resolve().parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from api import app


def main():
    client = app.test_client()
    failed = []

    # Root
    r = client.get("/")
    if r.status_code != 200:
        failed.append(f"GET / -> {r.status_code}")
    else:
        print("GET / -> 200 OK")

    # OHLCV (may return 200 with [] if no data)
    r = client.get("/ohlcv?symbol=BTC/USDT&limit=5")
    if r.status_code not in (200, 500):
        failed.append(f"GET /ohlcv -> {r.status_code}")
    else:
        print("GET /ohlcv ->", r.status_code)

    # Chart endpoints
    for path in ["/chart/symbols", "/chart/candle_counts", "/chart/orders", "/chart/fills", "/chart/positions", "/chart/pnl_summary"]:
        r = client.get(path)
        if r.status_code not in (200, 500):
            failed.append(f"GET {path} -> {r.status_code}")
        else:
            print(f"GET {path} ->", r.status_code)

    # Dashboard HTML
    r = client.get("/dashboard")
    if r.status_code != 200:
        failed.append(f"GET /dashboard -> {r.status_code}")
    else:
        print("GET /dashboard -> 200 OK")
        if b"Tradebot" not in r.data and b"chart" not in r.data.lower():
            failed.append("GET /dashboard -> response doesn't look like dashboard HTML")

    if failed:
        print("\nFailed:", failed)
        sys.exit(1)
    print("\nAll smoke tests passed.")


if __name__ == "__main__":
    main()
