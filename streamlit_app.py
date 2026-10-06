"""
Stock Monitor & Company Research
Run:  pip install streamlit yfinance plotly pandas
      streamlit run stock_monitor.py
"""
import json
import os
import pathlib

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

st.set_page_config(page_title="Stock Monitor", page_icon="📈", layout="wide")

DATA_FILE = pathlib.Path("watchlist.json")
DEFAULT = {"tickers": ["AAPL", "MSFT", "NVDA"], "alerts": {}, "mover_pct": 3.0, "seen_news": []}


# ---------- persistence ----------
def load():
    try:
        saved = json.loads(DATA_FILE.read_text())
    except Exception:
        saved = {}
    return {**json.loads(json.dumps(DEFAULT)), **saved}


def save(data):
    DATA_FILE.write_text(json.dumps(data, indent=2))


if "data" not in st.session_state:
    st.session_state.data = load()
data = st.session_state.data


# ---------- data fetching ----------
@st.cache_data(ttl=30)
def get_quote(symbol):
    try:
        fi = yf.Ticker(symbol).fast_info
        price, prev = fi["last_price"], fi["previous_close"]
        return {
            "price": float(price),
            "prev": float(prev),
            "change": float(price - prev),
            "pct": float((price - prev) / prev * 100),
            "volume": fi.get("last_volume"),
            "high": fi.get("year_high"),
            "low": fi.get("year_low"),
        }
    except Exception:
        return None


@st.cache_data(ttl=300)
def get_history(symbol, period, interval):
    return yf.Ticker(symbol).history(period=period, interval=interval)


@st.cache_data(ttl=3600)
def get_info(symbol):
    try:
        return yf.Ticker(symbol).info or {}
    except Exception:
        return {}


@st.cache_data(ttl=3600)
def get_financials(symbol):
    t = yf.Ticker(symbol)
    try:
        return t.income_stmt
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=600)
def get_news(symbol):
    try:
        return yf.Ticker(symbol).news or []
    except Exception:
        return []


def parse_news(n):
    c = n.get("content", n)  # newer yfinance nests under "content"
    url = (c.get("canonicalUrl") or {}).get("url") or c.get("link")
    return {
        "id": n.get("id") or c.get("id") or url,
        "title": c.get("title"),
        "url": url,
        "src": (c.get("provider") or {}).get("displayName") or c.get("publisher", ""),
        "time": c.get("pubDate") or "",
    }


def get_api_key():
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    try:
        return st.secrets["ANTHROPIC_API_KEY"]
    except Exception:
        return None


@st.cache_data(ttl=3600, show_spinner=False)
def ai_summary(symbol, facts, headlines, _api_key):
    import anthropic

    client = anthropic.Anthropic(api_key=_api_key)
    prompt = f"""You are an equity research assistant. Using ONLY the data below, write a
concise brief on {symbol} with these sections:
**What it does** (2 sentences), **Financial snapshot** (3 bullets), **Bull case** (3 bullets),
**Bear case / risks** (3 bullets), **What recent news suggests** (2 sentences).
Be balanced and specific. Note any missing data rather than guessing. This is not investment advice.

COMPANY DATA (JSON):
{facts}

RECENT HEADLINES:
{chr(10).join('- ' + h for h in headlines) or '(none)'}"""
    msg = client.messages.create(
        model="claude-sonnet-5-5",
        max_tokens=900,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


def fmt_num(n):
    if n is None or (isinstance(n, float) and pd.isna(n)):
        return "—"
    for unit, div in (("T", 1e12), ("B", 1e9), ("M", 1e6)):
        if abs(n) >= div:
            return f"{n / div:.2f}{unit}"
    return f"{n:,.2f}"


def fmt_pct(n):
    return "—" if n is None else f"{n * 100:.1f}%"


def fmt(n, digits=2):
    return "—" if n is None else f"{n:.{digits}f}"


# ---------- sidebar ----------
with st.sidebar:
    st.title("📈 Watchlist")
    new = st.text_input("Add ticker", placeholder="e.g. TSLA").strip().upper()
    if st.button("Add", use_container_width=True) and new:
        if new not in data["tickers"]:
            if get_quote(new):
                data["tickers"].append(new)
                save(data)
                st.rerun()
            else:
                st.error(f"Couldn't find {new}")
    remove = st.multiselect("Remove", data["tickers"])
    if st.button("Remove selected", use_container_width=True) and remove:
        data["tickers"] = [t for t in data["tickers"] if t not in remove]
        for t in remove:
            data["alerts"].pop(t, None)
        save(data)
        st.rerun()
    st.divider()
    auto = st.toggle("Auto-refresh", value=False)
    secs = st.slider("Every (seconds)", 15, 300, 60, disabled=not auto)
    if st.button("Refresh now", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.divider()
    new_pct = st.slider("Mover alert threshold (± % today)", 1.0, 15.0, float(data["mover_pct"]), 0.5)
    if new_pct != data["mover_pct"]:
        data["mover_pct"] = new_pct
        save(data)
    st.caption("Data from Yahoo Finance, may be delayed. Not financial advice.")


tab_watch, tab_research = st.tabs(["Watchlist", "Company research"])

# ---------- watchlist tab ----------
with tab_watch:

    def render_watchlist():
        if not data["tickers"]:
            st.info("Add a ticker in the sidebar to get started.")
            return
        rows, triggered = [], []
        for sym in data["tickers"]:
            q = get_quote(sym)
            if not q:
                rows.append({"Ticker": sym, "Price": None})
                continue
            a = data["alerts"].get(sym, {})
            if a.get("above") and q["price"] >= a["above"]:
                triggered.append(f"{sym} is above ${a['above']:.2f} (now ${q['price']:.2f})")
            if a.get("below") and q["price"] <= a["below"]:
                triggered.append(f"{sym} is below ${a['below']:.2f} (now ${q['price']:.2f})")
            if abs(q["pct"]) >= data["mover_pct"]:
                triggered.append(f"{sym} is a big mover: {q['pct']:+.1f}% today (${q['price']:.2f})")
            rows.append(
                {
                    "Ticker": sym,
                    "Price": q["price"],
                    "Change": q["change"],
                    "Change %": q["pct"],
                    "52w Low": q["low"],
                    "52w High": q["high"],
                    "Volume": q["volume"],
                }
            )
        for msg in triggered:
            st.warning(f"🔔 {msg}")

        df = pd.DataFrame(rows)

        def color(v):
            if pd.isna(v):
                return ""
            return "color: #16a34a" if v > 0 else "color: #dc2626" if v < 0 else ""

        styled = (
            df.style.map(color, subset=["Change", "Change %"])
            .format(
                {
                    "Price": "${:,.2f}",
                    "Change": "{:+,.2f}",
                    "Change %": "{:+.2f}%",
                    "52w Low": "${:,.2f}",
                    "52w High": "${:,.2f}",
                    "Volume": "{:,.0f}",
                },
                na_rep="—",
            )
        )
        st.dataframe(styled, use_container_width=True, hide_index=True)

    st.fragment(run_every=secs if auto else None)(render_watchlist)()

    st.subheader("📰 Watchlist news")
    all_news = []
    for sym in data["tickers"]:
        for n in get_news(sym)[:4]:
            item = parse_news(n)
            if item["title"] and item["url"]:
                item["sym"] = sym
                all_news.append(item)
    all_news.sort(key=lambda x: x["time"], reverse=True)
    seen = set(data["seen_news"])
    fresh = [i for i in all_news if i["id"] not in seen]
    if fresh:
        st.info(f"🆕 {len(fresh)} new headlines since you last marked as read")
    for i in all_news[:15]:
        mark = "🆕 " if i["id"] not in seen else ""
        st.markdown(f"- {mark}**{i['sym']}** [{i['title']}]({i['url']}) — *{i['src']}*")
    if fresh and st.button("Mark all as read"):
        data["seen_news"] = list(seen | {i["id"] for i in all_news})[-500:]
        save(data)
        st.rerun()

    st.subheader("Price alerts")
    if data["tickers"]:
        c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
        sym = c1.selectbox("Ticker", data["tickers"], key="alert_sym")
        cur = data["alerts"].get(sym, {})
        above = c2.number_input("Alert above ($)", min_value=0.0, value=float(cur.get("above") or 0), step=1.0)
        below = c3.number_input("Alert below ($)", min_value=0.0, value=float(cur.get("below") or 0), step=1.0)
        c4.write("")
        c4.write("")
        if c4.button("Save"):
            data["alerts"][sym] = {"above": above or None, "below": below or None}
            save(data)
            st.success(f"Alert saved for {sym}")

# ---------- research tab ----------
with tab_research:
    c1, c2 = st.columns([2, 1])
    choice = c1.selectbox("Pick from watchlist", [""] + data["tickers"])
    typed = c2.text_input("…or type any ticker").strip().upper()
    symbol = typed or choice

    if not symbol:
        st.info("Choose or type a ticker to research a company.")
    else:
        info = get_info(symbol)
        if not info:
            st.error(f"No data found for {symbol}.")
        else:
            st.header(f"{info.get('longName', symbol)} ({symbol})")
            st.caption(
                " · ".join(
                    x for x in [info.get("sector"), info.get("industry"), info.get("country")] if x
                )
            )

            # chart
            p1, p2 = st.columns(2)
            period = p1.selectbox("Range", ["1mo", "3mo", "6mo", "1y", "2y", "5y", "max"], index=3)
            kind = p2.radio("Chart", ["Candles", "Line"], horizontal=True)
            interval = "1d" if period not in ("5y", "max") else "1wk"
            hist = get_history(symbol, period, interval)
            if not hist.empty:
                fig = go.Figure()
                if kind == "Candles":
                    fig.add_candlestick(
                        x=hist.index, open=hist["Open"], high=hist["High"],
                        low=hist["Low"], close=hist["Close"], name="Price",
                    )
                else:
                    fig.add_scatter(x=hist.index, y=hist["Close"], name="Close")
                for w in (50, 200):
                    if len(hist) > w:
                        fig.add_scatter(
                            x=hist.index, y=hist["Close"].rolling(w).mean(),
                            name=f"SMA {w}", line=dict(width=1),
                        )
                fig.update_layout(
                    height=480, xaxis_rangeslider_visible=False,
                    margin=dict(l=0, r=0, t=10, b=0),
                )
                st.plotly_chart(fig, use_container_width=True)

            # key metrics
            st.subheader("Key metrics")
            m = st.columns(4)
            metrics = [
                ("Market cap", fmt_num(info.get("marketCap"))),
                ("P/E (trailing)", fmt(info.get("trailingPE"))),
                ("P/E (forward)", fmt(info.get("forwardPE"))),
                ("EPS (TTM)", fmt(info.get("trailingEps"))),
                ("Revenue growth", fmt_pct(info.get("revenueGrowth"))),
                ("Profit margin", fmt_pct(info.get("profitMargins"))),
                ("Return on equity", fmt_pct(info.get("returnOnEquity"))),
                ("Debt / equity", fmt(info.get("debtToEquity"))),
                ("Dividend yield", fmt_pct(info.get("dividendYield") and info["dividendYield"] / 100)),
                ("Beta", fmt(info.get("beta"))),
                ("Free cash flow", fmt_num(info.get("freeCashflow"))),
                ("Employees", f"{info['fullTimeEmployees']:,}" if info.get("fullTimeEmployees") else "—"),
            ]
            for i, (label, val) in enumerate(metrics):
                m[i % 4].metric(label, val)

            # analysts
            st.subheader("Analyst view")
            a = st.columns(4)
            a[0].metric("Consensus", str(info.get("recommendationKey", "—")).replace("_", " ").title())
            a[1].metric("Mean target", fmt(info.get("targetMeanPrice")))
            a[2].metric("Low target", fmt(info.get("targetLowPrice")))
            a[3].metric("High target", fmt(info.get("targetHighPrice")))

            # AI summary
            st.subheader("🤖 AI summary")
            api_key = get_api_key()
            if not api_key:
                st.caption("Set ANTHROPIC_API_KEY (env var or Streamlit secret) to enable AI summaries.")
            elif st.button(f"Generate summary for {symbol}"):
                fields = [
                    "longName", "sector", "industry", "marketCap", "trailingPE", "forwardPE",
                    "trailingEps", "revenueGrowth", "profitMargins", "returnOnEquity",
                    "debtToEquity", "freeCashflow", "dividendYield", "beta",
                    "recommendationKey", "targetMeanPrice", "fiftyTwoWeekLow",
                    "fiftyTwoWeekHigh", "longBusinessSummary",
                ]
                facts = json.dumps({k: info.get(k) for k in fields}, default=str)
                heads = [parse_news(n)["title"] for n in get_news(symbol)[:8]]
                heads = [h for h in heads if h]
                with st.spinner("Writing summary..."):
                    try:
                        st.session_state[f"ai_{symbol}"] = ai_summary(symbol, facts, tuple(heads), api_key)
                    except Exception as e:
                        st.error(f"AI summary failed: {e}")
            if f"ai_{symbol}" in st.session_state:
                st.markdown(st.session_state[f"ai_{symbol}"])
                st.caption("AI-generated from the data above. Not investment advice; verify before acting.")

            # business
            with st.expander("Business summary", expanded=True):
                st.write(info.get("longBusinessSummary", "No description available."))
                if info.get("website"):
                    st.markdown(f"[{info['website']}]({info['website']})")

            # financials
            st.subheader("Income statement (annual)")
            fin = get_financials(symbol)
            if fin is not None and not fin.empty:
                keep = [r for r in ["Total Revenue", "Gross Profit", "Operating Income",
                                    "Net Income", "Diluted EPS"] if r in fin.index]
                tbl = fin.loc[keep].copy()
                tbl.columns = [str(c.year) for c in tbl.columns]
                st.dataframe(tbl.map(fmt_num), use_container_width=True)
                if "Total Revenue" in tbl.index and "Net Income" in tbl.index:
                    chart = fin.loc[["Total Revenue", "Net Income"]].T.sort_index()
                    chart.index = [str(c.year) for c in chart.index]
                    st.bar_chart(chart)
            else:
                st.caption("Financial statements unavailable.")

            # news
            st.subheader("Latest news")
            news = get_news(symbol)[:8]
            if not news:
                st.caption("No news found.")
            for n in news:
                c = n.get("content", n)  # newer yfinance nests under "content"
                title = c.get("title")
                url = (c.get("canonicalUrl") or {}).get("url") or c.get("link")
                src = (c.get("provider") or {}).get("displayName") or c.get("publisher", "")
                if title and url:
                    st.markdown(f"- [{title}]({url}) — *{src}*")
