"""
Background alerts: big movers, price alerts and fresh news -> push notification.

Reads watchlist.json (same file the app uses), sends to ntfy.sh if NTFY_TOPIC is set
(install the free ntfy app on your phone and subscribe to your topic), else prints.

Run locally:   python alerts_job.py
Run on a schedule: see .github/workflows/alerts.yml
"""
import datetime as dt
import json
import os
import pathlib

import requests
import yfinance as yf

WATCH = pathlib.Path("watchlist.json")
STATE = pathlib.Path("alerts_state.json")
TOPIC = os.environ.get("NTFY_TOPIC")


def notify(title, body):
    print(f"[{title}]\n{body}\n")
    if TOPIC:
        try:
            requests.post(
                f"https://ntfy.sh/{TOPIC}",
                data=body.encode("utf-8"),
                headers={"Title": title},
                timeout=15,
            )
        except Exception as e:
            print("ntfy failed:", e)


def parse_news(n):
    c = n.get("content", n)
    url = (c.get("canonicalUrl") or {}).get("url") or c.get("link")
    return n.get("id") or c.get("id") or url, c.get("title"), url


def main():
    cfg = json.loads(WATCH.read_text()) if WATCH.exists() else {}
    tickers = cfg.get("tickers", ["AAPL", "MSFT", "NVDA"])
    threshold = float(cfg.get("mover_pct", 3.0))
    alerts = cfg.get("alerts", {})

    today = dt.date.today().isoformat()
    first_run = not STATE.exists()
    state = json.loads(STATE.read_text()) if not first_run else {}
    if state.get("date") != today:
        state["date"] = today
        state["fired"] = []  # per-day dedupe for price/mover alerts
    state.setdefault("news", [])

    lines = []
    for sym in tickers:
        try:
            fi = yf.Ticker(sym).fast_info
            price, prev = float(fi["last_price"]), float(fi["previous_close"])
        except Exception:
            continue
        pct = (price - prev) / prev * 100

        def fire(key, msg):
            if key not in state["fired"]:
                state["fired"].append(key)
                lines.append(msg)

        if abs(pct) >= threshold:
            fire(f"{sym}:mover", f"{sym} {pct:+.1f}% today (${price:.2f})")
        a = alerts.get(sym, {})
        if a.get("above") and price >= a["above"]:
            fire(f"{sym}:above", f"{sym} crossed above ${a['above']:.2f} (now ${price:.2f})")
        if a.get("below") and price <= a["below"]:
            fire(f"{sym}:below", f"{sym} fell below ${a['below']:.2f} (now ${price:.2f})")

    if lines:
        notify("Stock movers & price alerts", "\n".join(lines))

    # news: alert on headlines not seen before (first run just records them)
    new_items = []
    for sym in tickers:
        try:
            for n in (yf.Ticker(sym).news or [])[:5]:
                nid, title, url = parse_news(n)
                if nid and title and nid not in state["news"]:
                    state["news"].append(nid)
                    new_items.append(f"{sym}: {title}\n{url}")
        except Exception:
            continue
    state["news"] = state["news"][-1000:]
    if new_items and not first_run:
        notify(f"{len(new_items)} new headlines", "\n\n".join(new_items[:10]))

    STATE.write_text(json.dumps(state, indent=2))


if __name__ == "__main__":
    main()
