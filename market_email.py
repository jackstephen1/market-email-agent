import requests
import smtplib
import os
import json
import time
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
import anthropic

WATCHLIST = ["AAPL", "MSFT", "GOOGL", "NVDA", "SPY", "QQQ", "BTC-USD", "ETH-USD", "SLV", "SQQQ", "UVIX"]

NEWS_API_KEY = os.environ["NEWS_API_KEY"]
FRED_API_KEY = os.environ["FRED_API_KEY"]
ANTHROPIC_KEY = os.environ["ANTHROPIC_API_KEY"]
GMAIL_ADDRESS = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASS = os.environ["GMAIL_APP_PASSWORD"]
RECIPIENT_EMAIL = os.environ["RECIPIENT_EMAIL"]
ALPHA_VANTAGE_KEY = os.environ["ALPHA_VANTAGE_KEY"]
FMP_API_KEY = os.environ["FMP_API_KEY"]


def get_sp500_top_movers():
    print("Fetching S&P 500 top movers...")
    try:
        params = {"apikey": FMP_API_KEY}
        g_resp = requests.get("https://financialmodelingprep.com/api/v3/stock_market/gainers", params=params, timeout=10).json()
        l_resp = requests.get("https://financialmodelingprep.com/api/v3/stock_market/losers", params=params, timeout=10).json()
        gainers = g_resp if isinstance(g_resp, list) else []
        losers  = l_resp if isinstance(l_resp, list) else []
        movers = []
        for s in gainers[:10]:
            if isinstance(s, dict) and s.get("symbol") and float(s.get("price", 0) or 0) > 0:
                movers.append({"ticker": s["symbol"], "price": round(float(s["price"]), 2), "change_pct": round(float(s.get("changesPercentage", 0) or 0), 2), "mover_type": "gainer"})
        for s in losers[:10]:
            if isinstance(s, dict) and s.get("symbol") and float(s.get("price", 0) or 0) > 0:
                movers.append({"ticker": s["symbol"], "price": round(float(s["price"]), 2), "change_pct": round(float(s.get("changesPercentage", 0) or 0), 2), "mover_type": "loser"})
        print("Got " + str(len(movers)) + " top movers")
        return movers
    except Exception as e:
        print("Could not fetch top movers: " + str(e))
        return []


def get_sentiment_indicators():
    print("Fetching market sentiment indicators...")
    result = {}

    # Fear & Greed – free, no key
    try:
        fg = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10).json().get("data", [{}])[0]
        fg_value = int(fg.get("value", 50))
        fg_label = fg.get("value_classification", "Neutral")
        result["fear_greed"] = {"value": fg_value, "label": fg_label}
        print("Fear & Greed: " + str(fg_value) + " (" + fg_label + ")")
    except Exception as e:
        print("Fear & Greed failed: " + str(e))
        result["fear_greed"] = {"value": 50, "label": "Neutral"}

    # VIX – stooq CSV (no API key, no rate limit)
    try:
        resp = requests.get("https://stooq.com/q/d/l/?s=%5Evix&i=d",
            headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        lines = [l for l in resp.text.strip().splitlines() if l and not l.startswith("Date")]
        if lines:
            last = lines[-1].split(",")
            vix_value = round(float(last[4]), 2)   # close price
            prev = lines[-2].split(",") if len(lines) >= 2 else last
            prev_close = round(float(prev[4]), 2)
            vix_change = round(((vix_value - prev_close) / prev_close) * 100, 2)
            if vix_value < 15:   vix_label = "Low Volatility"
            elif vix_value < 20: vix_label = "Normal"
            elif vix_value < 30: vix_label = "Elevated Fear"
            else:                vix_label = "Extreme Fear"
            result["vix"] = {"value": vix_value, "change": vix_change, "label": vix_label}
            print("VIX (stooq): " + str(vix_value) + " (" + vix_label + ")")
        else:
            raise Exception("empty response")
    except Exception as e:
        print("VIX stooq failed: " + str(e))
        result["vix"] = {"value": "N/A", "change": 0, "label": "Unavailable"}

    # Put/Call Ratio – stooq CSV
    try:
        resp2 = requests.get("https://stooq.com/q/d/l/?s=%5Epcr&i=d",
            headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        lines2 = [l for l in resp2.text.strip().splitlines() if l and not l.startswith("Date")]
        if lines2:
            last2 = lines2[-1].split(",")
            pc_value = round(float(last2[4]), 2)
            if pc_value < 0.6:   pc_label = "Very Bullish"
            elif pc_value < 0.8: pc_label = "Bullish"
            elif pc_value < 1.0: pc_label = "Neutral"
            elif pc_value < 1.2: pc_label = "Bearish"
            else:                pc_label = "Very Bearish"
            result["put_call"] = {"value": pc_value, "label": pc_label}
            print("Put/Call (stooq): " + str(pc_value) + " (" + pc_label + ")")
        else:
            raise Exception("empty response")
    except Exception as e:
        print("Put/Call stooq failed: " + str(e))
        result["put_call"] = {"value": "N/A", "label": "Unavailable"}

    return result

def get_earnings_data():
    print("Fetching earnings data...")
    import yfinance as yf
    recent   = []
    upcoming = []
    today        = datetime.now().date()
    past_cutoff  = today - timedelta(days=5)
    future_cutoff= today + timedelta(days=7)

    # Broad list of tickers to scan for earnings
    scan = [
        "AAPL","MSFT","GOOGL","NVDA","AMZN","META","TSLA","JPM","BAC","GS",
        "V","MA","UNH","JNJ","XOM","CVX","WMT","HD","NFLX","AMD",
        "INTC","CRM","ORCL","IBM","QCOM","MU","SOFI","AFRM","UPST","COIN",
        "PLTR","RKLB","IONQ","CELH","CAVA","BROS"
    ]

    for ticker in scan:
        try:
            stk = yf.Ticker(ticker)

            # ── Upcoming: check calendar ──
            try:
                cal = stk.calendar          # dict or DataFrame
                if isinstance(cal, dict):
                    dates = cal.get("Earnings Date", [])
                    if not hasattr(dates, "__iter__"): dates = [dates]
                    for d in dates:
                        try:
                            d_date = d.date() if hasattr(d, "date") else d
                            if isinstance(d_date, type(today)) and today <= d_date <= future_cutoff:
                                upcoming.append({
                                    "ticker": ticker,
                                    "date": str(d_date),
                                    "eps_estimate": "N/A",
                                    "time": "TBD"
                                })
                        except:
                            pass
            except:
                pass

            # ── Recent: check earnings_history ──
            try:
                hist = stk.earnings_history
                if hist is not None and hasattr(hist, "iterrows"):
                    for idx, row in hist.iterrows():
                        try:
                            row_date = idx.date() if hasattr(idx, "date") else None
                            if row_date and past_cutoff <= row_date <= today:
                                ea = row.get("epsActual")
                                ee = row.get("epsEstimate")
                                if ea is not None and ee is not None:
                                    ea, ee = float(ea), float(ee)
                                    surp = round(((ea - ee) / abs(ee)) * 100, 1) if ee != 0 else 0
                                    recent.append({
                                        "ticker": ticker,
                                        "date": str(row_date),
                                        "eps_actual":   round(ea, 2),
                                        "eps_estimate": round(ee, 2),
                                        "surprise_pct": surp,
                                        "beat": ea >= ee
                                    })
                        except:
                            pass
            except:
                pass

        except Exception as ex:
            pass

    # Deduplicate upcoming by ticker
    seen_u = set()
    unique_upcoming = []
    for u in sorted(upcoming, key=lambda x: x["date"]):
        if u["ticker"] not in seen_u:
            seen_u.add(u["ticker"])
            unique_upcoming.append(u)

    recent   = sorted(recent,          key=lambda x: abs(x.get("surprise_pct",0)), reverse=True)[:3]
    upcoming = unique_upcoming[:10]
    print("Got " + str(len(recent)) + " recent earnings, " + str(len(upcoming)) + " upcoming")
    return {"recent": recent, "upcoming": upcoming}

def get_broad_news():
    print("Fetching news...")
    headlines = []
    try:
        params = {"category": "business", "language": "en", "country": "us", "pageSize": 10, "apiKey": NEWS_API_KEY}
        articles = requests.get("https://newsapi.org/v2/top-headlines", params=params, timeout=10).json().get("articles", [])
        for a in articles:
            if a.get("title") and "[Removed]" not in a.get("title", ""):
                headlines.append({"title": a["title"], "source": a["source"]["name"], "url": a.get("url", "#")})
    except Exception as e:
        print("Business news failed: " + str(e))
    try:
        params2 = {"language": "en", "country": "us", "pageSize": 10, "apiKey": NEWS_API_KEY}
        articles2 = requests.get("https://newsapi.org/v2/top-headlines", params=params2, timeout=10).json().get("articles", [])
        for a in articles2:
            if a.get("title") and "[Removed]" not in a.get("title", ""):
                title = a["title"]
                if any(word in title.lower() for word in ["war", "sanctions", "fed", "oil", "trade", "tariff", "china", "russia", "iran", "rate", "inflation", "recession", "earnings", "gdp", "jobs"]):
                    headlines.append({"title": title, "source": a["source"]["name"], "url": a.get("url", "#")})
    except Exception as e:
        print("General news failed: " + str(e))
    seen = set()
    unique = []
    for h in headlines:
        if h["title"] not in seen:
            seen.add(h["title"])
            unique.append(h)
    print("Got " + str(len(unique)) + " news articles")
    return unique[:15]


def get_quote_av_stock(ticker):
    try:
        params = {"function": "GLOBAL_QUOTE", "symbol": ticker, "apikey": ALPHA_VANTAGE_KEY}
        quote = requests.get("https://www.alphavantage.co/query", params=params, timeout=10).json().get("Global Quote", {})
        if quote and quote.get("05. price"):
            price = float(quote["05. price"])
            change_pct = float(quote["10. change percent"].replace("%", ""))
            if price > 0:
                print("Got " + ticker + ": $" + str(round(price, 2)))
                return {"ticker": ticker, "price": round(price, 2), "change_pct": round(change_pct, 2), "is_crypto": False}
        print("No data for " + ticker)
        return None
    except Exception as e:
        print("AV stock failed for " + ticker + ": " + str(e))
        return None


def get_quote_crypto(ticker):
    try:
        symbol = ticker.replace("-USD", "").replace("-usd", "")
        url = "https://www.alphavantage.co/query"
        rate = requests.get(url, params={"function": "CURRENCY_EXCHANGE_RATE", "from_currency": symbol, "to_currency": "USD", "apikey": ALPHA_VANTAGE_KEY}, timeout=10).json().get("Realtime Currency Exchange Rate", {})
        if not rate:
            return None
        curr_price = float(rate.get("5. Exchange Rate", 0))
        time.sleep(13)
        ts = requests.get(url, params={"function": "DIGITAL_CURRENCY_DAILY", "symbol": symbol, "market": "USD", "apikey": ALPHA_VANTAGE_KEY}, timeout=10).json().get("Time Series (Digital Currency Daily)", {})
        change_pct = 0.0
        if ts:
            dates = sorted(ts.keys(), reverse=True)
            if len(dates) >= 2:
                prev_entry = ts[dates[1]]
                prev_close = None
                for key in ["4a. close (USD)", "4. close", "4b. close (USD)", "4. close (USD)"]:
                    if key in prev_entry:
                        prev_close = float(prev_entry[key])
                        break
                if prev_close and prev_close > 0:
                    change_pct = ((curr_price - prev_close) / prev_close) * 100
        print("Got " + ticker + ": $" + str(round(curr_price, 2)))
        return {"ticker": ticker, "price": round(curr_price, 2), "change_pct": round(change_pct, 2), "is_crypto": True}
    except Exception as e:
        print("Crypto failed for " + ticker + ": " + str(e))
        return None


def get_stock_data(tickers):
    print("Fetching watchlist quotes...")
    results = []
    for ticker in tickers:
        try:
            if "-USD" in ticker.upper():
                time.sleep(13)
                result = get_quote_crypto(ticker)
            else:
                time.sleep(13)
                result = get_quote_av_stock(ticker)
            if result:
                results.append(result)
        except Exception as e:
            print("Error fetching " + ticker + ": " + str(e))
    print("Got " + str(len(results)) + " of " + str(len(tickers)) + " tickers")
    return results


def get_technicals_av(ticker):
    try:
        url = "https://www.alphavantage.co/query"
        result = {"ticker": ticker}
        time.sleep(13)
        data = requests.get(url, params={"function": "RSI", "symbol": ticker, "interval": "daily", "time_period": 14, "series_type": "close", "apikey": ALPHA_VANTAGE_KEY}, timeout=10).json().get("Technical Analysis: RSI", {})
        if data:
            result["rsi"] = round(float(data[sorted(data.keys(), reverse=True)[0]]["RSI"]), 1)
        time.sleep(13)
        data2 = requests.get(url, params={"function": "SMA", "symbol": ticker, "interval": "daily", "time_period": 50, "series_type": "close", "apikey": ALPHA_VANTAGE_KEY}, timeout=10).json().get("Technical Analysis: SMA", {})
        if data2:
            result["sma50"] = round(float(data2[sorted(data2.keys(), reverse=True)[0]]["SMA"]), 2)
        time.sleep(13)
        data3 = requests.get(url, params={"function": "SMA", "symbol": ticker, "interval": "daily", "time_period": 200, "series_type": "close", "apikey": ALPHA_VANTAGE_KEY}, timeout=10).json().get("Technical Analysis: SMA", {})
        if data3:
            result["sma200"] = round(float(data3[sorted(data3.keys(), reverse=True)[0]]["SMA"]), 2)
        return result if len(result) > 1 else None
    except Exception as e:
        print("Technicals failed for " + ticker + ": " + str(e))
        return None


# Small/mid cap growth universe – rotated daily so we don't always scan the same ones
GROWTH_UNIVERSE = [
    # Fintech
    "SOFI","AFRM","UPST","NU","DAVE","HOOD","LC",
    # AI / Tech infrastructure
    "SOUN","BBAI","IONQ","RKLB","JOBY","ACMR","SMCI",
    # Biotech / Healthcare
    "RXRX","BEAM","CRSP","PACB","ACHR","NVAX","PRCT",
    # Energy / Clean energy
    "CHRD","SM","CIVI","ARRY","FSLR","RUN","PLUG",
    # Defense / Aerospace
    "KTOS","CACI","DRS","AVAV","HII",
    # Emerging consumer
    "CELH","CAVA","BROS","DKNG","CHWY","CVNA",
    # Semiconductors / Hardware
    "MU","MRVL","ON","WOLF","AEIS",
]

def get_swing_trade_data(watchlist_tickers, top_movers):
    import random
    print("Fetching technicals for swing analysis...")

    # Pick 4 random growth stocks to scan today (keeps it fresh each day)
    random.shuffle(GROWTH_UNIVERSE)
    growth_picks = GROWTH_UNIVERSE[:4]

    stock_tickers = [t for t in watchlist_tickers if "-USD" not in t.upper()]
    mover_tickers = [m["ticker"] for m in top_movers[:4] if isinstance(m, dict)]

    seen = set()
    combined = []
    # Priority: growth picks first, then movers, then watchlist
    for t in growth_picks + mover_tickers + stock_tickers:
        if t not in seen:
            combined.append(t)
            seen.add(t)

    technicals = []
    for ticker in combined[:6]:          # scan 6 tickers total
        try:
            print("Getting technicals for " + ticker + "...")
            time.sleep(13)
            quote = get_quote_av_stock(ticker)
            if not quote or quote["price"] == 0:
                continue
            tech = get_technicals_av(ticker)
            if quote and tech:
                technicals.append({**quote, **tech})
                print("  RSI: " + str(tech.get("rsi", "N/A")) + " | SMA50: $" + str(tech.get("sma50", "N/A")))
        except Exception as e:
            print("Could not get technicals for " + ticker + ": " + str(e))
    return technicals


def get_macro_data():
    print("Fetching macro indicators...")
    indicators = {
        "Federal Funds Rate": ("FEDFUNDS", "rate"),
        "Unemployment Rate": ("UNRATE", "unemployment"),
        "10-Year Treasury Yield": ("DGS10", "yield"),
        "US GDP Growth Rate": ("A191RL1Q225SBEA", "gdp")
    }
    results = {}
    for name, (series_id, kind) in indicators.items():
        try:
            # Use limit=10 to get more observations in case recent ones are missing
            params = {"series_id": series_id, "api_key": FRED_API_KEY, "file_type": "json", "sort_order": "desc", "limit": 10}
            obs = requests.get("https://api.stlouisfed.org/fred/series/observations", params=params, timeout=10).json().get("observations", [])
            value = next((o["value"] for o in obs if o.get("value") and o["value"] not in [".", "NA", ""]), "N/A")

            # Generate rating based on indicator type
            if value != "N/A":
                v = float(value)
                if kind == "rate":
                    if v <= 2.5: rating, r_color, r_bg = "Good", "#2e7d32", "#e8f5e9"
                    elif v <= 4.5: rating, r_color, r_bg = "Neutral", "#e65100", "#fff3e0"
                    else: rating, r_color, r_bg = "Restrictive", "#c62828", "#ffebee"
                elif kind == "unemployment":
                    if v <= 4.0: rating, r_color, r_bg = "Strong", "#2e7d32", "#e8f5e9"
                    elif v <= 5.5: rating, r_color, r_bg = "Moderate", "#e65100", "#fff3e0"
                    else: rating, r_color, r_bg = "Weak", "#c62828", "#ffebee"
                elif kind == "yield":
                    if v <= 3.5: rating, r_color, r_bg = "Accommodative", "#2e7d32", "#e8f5e9"
                    elif v <= 4.5: rating, r_color, r_bg = "Neutral", "#e65100", "#fff3e0"
                    else: rating, r_color, r_bg = "Tight", "#c62828", "#ffebee"
                elif kind == "gdp":
                    if v >= 2.5: rating, r_color, r_bg = "Strong", "#2e7d32", "#e8f5e9"
                    elif v >= 1.0: rating, r_color, r_bg = "Moderate", "#e65100", "#fff3e0"
                    else: rating, r_color, r_bg = "Weak", "#c62828", "#ffebee"
                else:
                    rating, r_color, r_bg = "Neutral", "#888", "#f5f5f5"
            else:
                rating, r_color, r_bg = "N/A", "#888", "#f5f5f5"

            results[name] = {"value": value, "rating": rating, "color": r_color, "bg": r_bg}
            print("Got " + name + ": " + value + " (" + rating + ")")
        except Exception as e:
            print("Macro failed for " + name + ": " + str(e))
            results[name] = {"value": "N/A", "rating": "N/A", "color": "#888", "bg": "#f5f5f5"}
    return results


def generate_analysis(stock_data, news_headlines, macro_data, swing_data, top_movers, sentiment_indicators, earnings_data):
    print("Generating AI analysis...")
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    stocks_text = ""
    if stock_data:
        for s in stock_data:
            sign = "+" if s["change_pct"] > 0 else ""
            stocks_text += s["ticker"] + ": $" + str(s["price"]) + " (" + sign + str(s["change_pct"]) + "% today)\n"
    else:
        stocks_text = "Stock data unavailable.\n"

    news_text = "\n".join(["- " + n["title"] for n in news_headlines]) if news_headlines else "No news.\n"
    macro_text = "".join([k + ": " + v["value"] + "\n" for k, v in macro_data.items()])
    movers_text = ""
    if top_movers:
        movers_text += "TOP GAINERS:\n" + "".join([m["ticker"] + ": $" + str(m["price"]) + " (+" + str(m["change_pct"]) + "%)\n" for m in top_movers if m.get("mover_type") == "gainer"][:5])
        movers_text += "TOP LOSERS:\n" + "".join([m["ticker"] + ": $" + str(m["price"]) + " (" + str(m["change_pct"]) + "%)\n" for m in top_movers if m.get("mover_type") == "loser"][:5])
    swing_text = ""
    if swing_data:
        for s in swing_data:
            if s.get("price", 0) > 0:
                swing_text += s["ticker"] + ": current_price=$" + str(s["price"]) + " | RSI=" + str(s.get("rsi", "N/A")) + " | 50SMA=$" + str(s.get("sma50", "N/A")) + " | 200SMA=$" + str(s.get("sma200", "N/A")) + "\n"

    earnings_text = ""
    if earnings_data.get("recent"):
        earnings_text += "RECENT EARNINGS:\n"
        for e in earnings_data["recent"][:5]:
            beat_str = "BEAT" if e.get("beat") else "MISSED"
            earnings_text += e["ticker"] + " " + beat_str + " by " + str(e["surprise_pct"]) + "% (actual: $" + str(e["eps_actual"]) + " vs est: $" + str(e["eps_estimate"]) + ")\n"
    if earnings_data.get("upcoming"):
        earnings_text += "UPCOMING EARNINGS:\n"
        for e in earnings_data["upcoming"][:5]:
            earnings_text += e["ticker"] + " reports on " + e["date"] + "\n"

    fg = sentiment_indicators.get("fear_greed", {})
    vix = sentiment_indicators.get("vix", {})
    pc = sentiment_indicators.get("put_call", {})
    sentiment_text = "Fear & Greed: " + str(fg.get("value", "N/A")) + " (" + fg.get("label", "N/A") + ")\n"
    sentiment_text += "VIX: " + str(vix.get("value", "N/A")) + " (" + vix.get("label", "N/A") + ")\n"
    sentiment_text += "Put/Call: " + str(pc.get("value", "N/A")) + " (" + pc.get("label", "N/A") + ")\n"

    prompt = """You are a financial analyst and swing trader. Return ONLY valid JSON, no extra text or markdown.

CRITICAL RULES:
- Entry zones MUST be within 5% of current_price in technical data. Never invent prices.
- Always specify timeframe on % moves (e.g. 'down 1.31% today')
- Swing trades = 3-10 day holds only
- RSI below 35 = oversold, above 70 = overbought
- SENTIMENT WEIGHTING: Base sentiment_score primarily on actual price action and macro data. Fear & Greed is a secondary indicator only.
- For macro opportunities: connect news events to under-the-radar stocks not yet moved

WATCHLIST:
""" + stocks_text + """
S&P 500 TOP MOVERS:
""" + movers_text + """
SENTIMENT INDICATORS (secondary reference only):
""" + sentiment_text + """
NEWS:
""" + news_text + """
MACRO DATA:
""" + macro_text + """
TECHNICAL DATA (use exact prices for entry zones):
""" + swing_text + """
EARNINGS:
""" + (earnings_text if earnings_text else "No earnings data available.\n") + """

Return this exact JSON:
{
  "sentiment_score": <1-10>,
  "sentiment_label": "<Bearish/Neutral/Bullish>",
  "market_summary": "<2-3 sentences with timeframes on % moves>",
  "key_insight": "<one key thing to watch today>",
  "notable_movers": "<2-3 sentences on watchlist stocks with timeframes>",
  "macro_context": "<2-3 sentences on economic data>",
  "sentiment_commentary": "<2 sentences on VIX and Put/Call positioning. Note if Fear & Greed diverges from price action.>",
  "swing_trades": [
    {
      "ticker": "<symbol>",
      "current_price": <exact price from technical data>,
      "bias": "<Bullish or Bearish>",
      "timeframe": "<e.g. 3-7 days>",
      "entry_zone": "<price range within 5% of current price>",
      "thesis": "<2-3 sentences on the setup>",
      "invalidation": "<price/event that cancels setup>",
      "source": "<Watchlist or S&P 500 Mover>"
    }
  ],
  "macro_opportunities": [
    {
      "theme": "<macro trend e.g. Iran Tensions, Fed Rate Cut, AI Infrastructure>",
      "theme_summary": "<2-3 sentences explaining the opportunity>",
      "plays": [
        {
          "ticker": "<symbol>",
          "company_name": "<full company name>",
          "type": "<Stock or ETF>",
          "why_underrated": "<1-2 sentences on why not priced in yet>",
          "catalyst": "<specific trigger>",
          "timeframe": "<weeks or months>"
        }
      ]
    }
  ]
}

Swing trades: only stocks with valid prices in technical data. 2-4 ideas.
Macro opportunities: 2-3 themes, 2-3 plays each. Focus on under-the-radar names."""

    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = message.content[0].text.strip().replace("```json", "").replace("```", "").strip()
    analysis = json.loads(raw)
    print("Sentiment: " + analysis.get("sentiment_label", "?") + " | Swing: " + str(len(analysis.get("swing_trades", []))) + " | Themes: " + str(len(analysis.get("macro_opportunities", []))))
    return analysis


def build_email_html(stock_data, news_headlines, macro_data, analysis, top_movers, sentiment_indicators, earnings_data):
    today = datetime.now().strftime("%A, %B %d, %Y")
    sentiment_score = analysis.get("sentiment_score", 5)
    sentiment_label = analysis.get("sentiment_label", "Neutral")
    market_summary = analysis.get("market_summary", "")
    key_insight = analysis.get("key_insight", "")
    notable_movers_text = analysis.get("notable_movers", "")
    macro_context = analysis.get("macro_context", "")
    sentiment_commentary = analysis.get("sentiment_commentary", "")
    swing_trades = analysis.get("swing_trades", [])
    macro_opportunities = analysis.get("macro_opportunities", [])

    if sentiment_label == "Bullish":
        sentiment_bg, sentiment_color = "#e8f5e9", "#2e7d32"
    elif sentiment_label == "Bearish":
        sentiment_bg, sentiment_color = "#ffebee", "#c62828"
    else:
        sentiment_bg, sentiment_color = "#fff8e1", "#e65100"

    bar_width = int((sentiment_score / 10) * 100)

    # Watchlist rows
    stock_rows = ""
    for s in stock_data:
        chg = s["change_pct"]
        c_color, c_bg, arrow = ("#2e7d32", "#e8f5e9", "&#9650;") if chg >= 0 else ("#c62828", "#ffebee", "&#9660;")
        sign = "+" if chg > 0 else ""
        label = s["ticker"] + " (Crypto)" if s.get("is_crypto") else s["ticker"]
        stock_rows += "<tr style='border-bottom:1px solid #f0f0f0;'><td style='padding:12px;font-weight:700;font-size:15px;color:#1a1a2e;'>" + label + "</td><td style='padding:12px;font-size:15px;color:#333;'>$" + str(s["price"]) + "</td><td style='padding:12px;'><span style='background:" + c_bg + ";color:" + c_color + ";padding:4px 12px;border-radius:20px;font-weight:700;font-size:13px;'>" + arrow + " " + sign + str(chg) + "%</span></td></tr>"
    if not stock_rows:
        stock_rows = "<tr><td colspan='3' style='padding:12px;color:#888;'>Stock data temporarily unavailable.</td></tr>"

    # S&P movers
    gainer_rows = "".join(["<tr style='border-bottom:1px solid #f0f0f0;'><td style='padding:8px 12px;font-weight:700;font-size:13px;color:#1a1a2e;'>" + m["ticker"] + "</td><td style='padding:8px 12px;font-size:13px;color:#333;'>$" + str(m["price"]) + "</td><td style='padding:8px 12px;'><span style='background:#e8f5e9;color:#2e7d32;padding:3px 8px;border-radius:20px;font-weight:700;font-size:12px;'>&#9650; +" + str(m["change_pct"]) + "%</span></td></tr>" for m in top_movers if m.get("mover_type") == "gainer"][:5])
    loser_rows = "".join(["<tr style='border-bottom:1px solid #f0f0f0;'><td style='padding:8px 12px;font-weight:700;font-size:13px;color:#1a1a2e;'>" + m["ticker"] + "</td><td style='padding:8px 12px;font-size:13px;color:#333;'>$" + str(m["price"]) + "</td><td style='padding:8px 12px;'><span style='background:#ffebee;color:#c62828;padding:3px 8px;border-radius:20px;font-weight:700;font-size:12px;'>&#9660; " + str(m["change_pct"]) + "%</span></td></tr>" for m in top_movers if m.get("mover_type") == "loser"][:5])

    # News
    news_items = "".join(["<tr style='border-bottom:1px solid #f5f5f5;'><td style='padding:12px;'><a href='" + n.get("url","#") + "' style='color:#1a1a2e;text-decoration:none;font-size:14px;font-weight:600;'>" + n["title"] + "</a><div style='color:#888;font-size:12px;margin-top:3px;'>" + n["source"] + "</div></td></tr>" for n in news_headlines])
    if not news_items:
        news_items = "<tr><td style='padding:12px;color:#888;'>No news today.</td></tr>"

    # Macro with ratings
    macro_rows = ""
    for k, v in macro_data.items():
        macro_rows += "<tr style='border-bottom:1px solid #f0f0f0;'><td style='padding:10px 12px;color:#555;font-size:14px;'>" + k + "</td><td style='padding:10px 12px;font-weight:700;font-size:14px;color:#1a1a2e;text-align:center;'>" + v["value"] + "</td><td style='padding:10px 12px;text-align:right;'><span style='background:" + v["bg"] + ";color:" + v["color"] + ";padding:3px 10px;border-radius:20px;font-weight:700;font-size:12px;'>" + v["rating"] + "</span></td></tr>"

    # Sentiment cards
    fg = sentiment_indicators.get("fear_greed", {})
    vix = sentiment_indicators.get("vix", {})
    pc = sentiment_indicators.get("put_call", {})
    fg_value = fg.get("value", 50)
    fg_label = fg.get("label", "Neutral")
    if isinstance(fg_value, int):
        if fg_value <= 25: fg_color, fg_bg = "#c62828", "#ffebee"
        elif fg_value <= 45: fg_color, fg_bg = "#e65100", "#fff3e0"
        elif fg_value <= 55: fg_color, fg_bg = "#888", "#f5f5f5"
        elif fg_value <= 75: fg_color, fg_bg = "#2e7d32", "#e8f5e9"
        else: fg_color, fg_bg = "#1565c0", "#e3f2fd"
        fg_bar = fg_value
    else:
        fg_color, fg_bg, fg_bar = "#888", "#f5f5f5", 50

    vix_value = vix.get("value", "N/A")
    vix_label = vix.get("label", "N/A")
    vix_change = vix.get("change", 0)
    vix_color = "#c62828" if isinstance(vix_value, (int,float)) and vix_value >= 25 else "#e65100" if isinstance(vix_value, (int,float)) and vix_value >= 20 else "#2e7d32"

    pc_value = pc.get("value", "N/A")
    pc_label = pc.get("label", "N/A")
    pc_color = "#c62828" if isinstance(pc_value, (int,float)) and pc_value >= 1.0 else "#2e7d32"

    # Earnings section
    recent_rows = ""
    for e in earnings_data.get("recent", []):
        beat = e.get("beat", True)
        e_color = "#2e7d32" if beat else "#c62828"
        e_bg = "#e8f5e9" if beat else "#ffebee"
        e_label = "BEAT" if beat else "MISS"
        surprise = e.get("surprise_pct", 0)
        sign = "+" if surprise > 0 else ""
        recent_rows += "<tr style='border-bottom:1px solid #f0f0f0;'><td style='padding:10px 12px;font-weight:700;font-size:14px;color:#1a1a2e;'>" + e["ticker"] + "</td><td style='padding:10px 12px;font-size:13px;color:#555;'>" + e["date"] + "</td><td style='padding:10px 12px;font-size:13px;color:#333;'>$" + str(e["eps_actual"]) + " vs $" + str(e["eps_estimate"]) + "</td><td style='padding:10px 12px;'><span style='background:" + e_bg + ";color:" + e_color + ";padding:3px 10px;border-radius:20px;font-weight:700;font-size:12px;'>" + e_label + " " + sign + str(surprise) + "%</span></td></tr>"

    upcoming_rows = ""
    for e in earnings_data.get("upcoming", []):
        time_label = "Pre-Mkt" if e.get("time") == "bmo" else "After Hrs" if e.get("time") == "amc" else e.get("time", "TBD")
        est = "$" + str(e["eps_estimate"]) if e["eps_estimate"] != "N/A" else "N/A"
        upcoming_rows += "<tr style='border-bottom:1px solid #f0f0f0;'><td style='padding:10px 12px;font-weight:700;font-size:14px;color:#1a1a2e;'>" + e["ticker"] + "</td><td style='padding:10px 12px;font-size:13px;color:#555;'>" + e["date"] + "</td><td style='padding:10px 12px;font-size:13px;color:#888;'>" + time_label + "</td><td style='padding:10px 12px;font-size:13px;color:#555;font-weight:600;'>" + est + "</td></tr>"

    earnings_section = ""
    if recent_rows or upcoming_rows:
        recent_block = ""
        if recent_rows:
            recent_block = "<div style='font-size:12px;font-weight:700;color:#333;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:10px;'>Recent Results</div><table style='width:100%;border-collapse:collapse;'><tr style='background:#f8f9fa;'><th style='padding:8px 12px;text-align:left;font-size:11px;color:#999;'>TICKER</th><th style='padding:8px 12px;text-align:left;font-size:11px;color:#999;'>DATE</th><th style='padding:8px 12px;text-align:left;font-size:11px;color:#999;'>EPS</th><th style='padding:8px 12px;text-align:left;font-size:11px;color:#999;'>RESULT</th></tr>" + recent_rows + "</table>"
        upcoming_block = ""
        if upcoming_rows:
            upcoming_block = "<div style='font-size:12px;font-weight:700;color:#333;text-transform:uppercase;letter-spacing:0.5px;margin-top:20px;margin-bottom:10px;'>Upcoming This Week</div><table style='width:100%;border-collapse:collapse;'><tr style='background:#f8f9fa;'><th style='padding:8px 12px;text-align:left;font-size:11px;color:#999;'>TICKER</th><th style='padding:8px 12px;text-align:left;font-size:11px;color:#999;'>DATE</th><th style='padding:8px 12px;text-align:left;font-size:11px;color:#999;'>TIME</th><th style='padding:8px 12px;text-align:left;font-size:11px;color:#999;'>EST EPS</th></tr>" + upcoming_rows + "</table>"
        earnings_section = "<div style='background:#ffffff;border-radius:16px;padding:24px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,0.08);'><div style='font-size:11px;font-weight:700;color:#888;letter-spacing:1px;text-transform:uppercase;margin-bottom:16px;'>Earnings Report</div>" + recent_block + upcoming_block + "</div>"
    else:
        earnings_section = "<div style='background:#ffffff;border-radius:16px;padding:24px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,0.08);'><div style='font-size:11px;font-weight:700;color:#888;letter-spacing:1px;text-transform:uppercase;margin-bottom:12px;'>Earnings Report</div><p style='color:#888;font-size:14px;margin:0;'>No earnings data available today. This section populates on weekdays when companies report.</p></div>"

    # Swing trade cards
    swing_cards = ""
    for trade in swing_trades:
        bias = trade.get("bias", "Bullish")
        b_color, b_bg, b_icon = ("#2e7d32", "#e8f5e9", "&#9650;") if bias == "Bullish" else ("#c62828", "#ffebee", "&#9660;")
        source = trade.get("source", "Watchlist")
        s_color, s_bg = ("#1565c0", "#e3f2fd") if source == "Watchlist" else ("#e65100", "#fff3e0")
        curr = trade.get("current_price", "")
        swing_cards += "<div style='border:1px solid #e8e8e8;border-radius:12px;padding:20px;margin-bottom:12px;'><div style='margin-bottom:12px;'><span style='font-size:18px;font-weight:900;color:#1a1a2e;margin-right:10px;'>" + trade.get("ticker","") + "</span><span style='background:" + b_bg + ";color:" + b_color + ";padding:3px 10px;border-radius:20px;font-weight:700;font-size:12px;margin-right:6px;'>" + b_icon + " " + bias + "</span><span style='background:" + s_bg + ";color:" + s_color + ";padding:3px 10px;border-radius:20px;font-weight:600;font-size:11px;'>" + source + "</span></div><div style='background:#f8f9fa;border-radius:8px;padding:12px;margin-bottom:12px;display:flex;justify-content:space-between;'><div><div style='font-size:11px;font-weight:700;color:#888;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px;'>Entry Zone</div><div style='font-size:15px;font-weight:700;color:#1a1a2e;'>" + trade.get("entry_zone","") + "</div></div><div style='text-align:right;'><div style='font-size:11px;font-weight:700;color:#888;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px;'>Current Price</div><div style='font-size:15px;font-weight:700;color:#555;'>$" + str(curr) + "</div></div></div><div style='font-size:11px;color:#888;margin-bottom:8px;'>Timeframe: <strong>" + trade.get("timeframe","") + "</strong></div><p style='margin:0 0 12px;color:#333;font-size:14px;line-height:1.7;'>" + trade.get("thesis","") + "</p><div style='border-top:1px solid #f0f0f0;padding-top:10px;'><span style='font-size:12px;color:#e65100;font-weight:600;'>Invalidated if: </span><span style='font-size:12px;color:#666;'>" + trade.get("invalidation","") + "</span></div></div>"
    if not swing_cards:
        swing_cards = "<p style='color:#888;font-size:14px;'>No clear swing setups today.</p>"

    # Macro opportunity cards
    macro_opp_cards = ""
    theme_colors = ["#1a237e", "#1b5e20", "#880e4f", "#e65100", "#4a148c"]
    theme_bgs = ["#e8eaf6", "#e8f5e9", "#fce4ec", "#fff3e0", "#f3e5f5"]
    for i, theme_data in enumerate(macro_opportunities):
        color = theme_colors[i % len(theme_colors)]
        bg = theme_bgs[i % len(theme_bgs)]
        plays = theme_data.get("plays", [])
        play_cards = ""
        for play in plays:
            ptype = play.get("type", "Stock")
            type_color = "#1565c0" if ptype == "ETF" else "#2e7d32"
            type_bg = "#e3f2fd" if ptype == "ETF" else "#e8f5e9"
            play_cards += "<div style='border:1px solid #f0f0f0;border-radius:8px;padding:14px;margin-bottom:8px;'><div style='display:flex;align-items:center;gap:8px;margin-bottom:8px;'><span style='font-size:16px;font-weight:900;color:#1a1a2e;'>" + play.get("ticker","") + "</span><span style='font-size:13px;color:#555;'>" + play.get("company_name","") + "</span><span style='background:" + type_bg + ";color:" + type_color + ";padding:2px 8px;border-radius:20px;font-size:11px;font-weight:700;margin-left:auto;'>" + ptype + "</span></div><div style='font-size:13px;color:#444;line-height:1.6;margin-bottom:6px;'><strong>Why now:</strong> " + play.get("why_underrated","") + "</div><div style='font-size:13px;color:#444;line-height:1.6;margin-bottom:6px;'><strong>Catalyst:</strong> " + play.get("catalyst","") + "</div><div style='font-size:12px;color:#888;'>Timeframe: " + play.get("timeframe","") + "</div></div>"
        macro_opp_cards += "<div style='border:2px solid " + bg + ";border-radius:12px;padding:20px;margin-bottom:16px;'><div style='background:" + bg + ";border-radius:8px;padding:10px 14px;margin-bottom:14px;'><div style='font-size:13px;font-weight:800;color:" + color + ";text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;'>&#127919; " + theme_data.get("theme","") + "</div><div style='font-size:14px;color:#333;line-height:1.6;'>" + theme_data.get("theme_summary","") + "</div></div>" + play_cards + "</div>"
    if not macro_opp_cards:
        macro_opp_cards = "<p style='color:#888;font-size:14px;'>No macro themes identified today.</p>"

    movers_section = ""
    if gainer_rows or loser_rows:
        movers_section = "<div style='background:#ffffff;border-radius:16px;padding:24px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,0.08);'><div style='font-size:11px;font-weight:700;color:#888;letter-spacing:1px;text-transform:uppercase;margin-bottom:16px;'>S&P 500 Top Movers Today</div><table style='width:100%;'><tr><td style='width:50%;vertical-align:top;padding-right:8px;'><div style='font-size:12px;font-weight:700;color:#2e7d32;margin-bottom:8px;'>TOP GAINERS</div><table style='width:100%;border-collapse:collapse;'>" + gainer_rows + "</table></td><td style='width:50%;vertical-align:top;padding-left:8px;'><div style='font-size:12px;font-weight:700;color:#c62828;margin-bottom:8px;'>TOP LOSERS</div><table style='width:100%;border-collapse:collapse;'>" + loser_rows + "</table></td></tr></table></div>"

    return """<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f0f2f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<div style="max-width:620px;margin:0 auto;padding:24px 16px;">

  <div style="background:#1a1a2e;border-radius:16px;padding:32px;margin-bottom:16px;text-align:center;">
    <div style="font-size:11px;font-weight:700;color:#a0b4d6;letter-spacing:2px;text-transform:uppercase;margin-bottom:8px;">Daily Market Briefing</div>
    <div style="font-size:26px;font-weight:900;color:#ffffff;">""" + today + """</div>
  </div>

  <div style="background:#ffffff;border-radius:16px;padding:24px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,0.08);">
    <div style="font-size:11px;font-weight:700;color:#888;letter-spacing:1px;text-transform:uppercase;margin-bottom:16px;">Market Sentiment</div>
    <div style="display:flex;align-items:center;margin-bottom:12px;">
      <span style="background:""" + sentiment_bg + """;color:""" + sentiment_color + """;padding:6px 16px;border-radius:20px;font-weight:800;font-size:15px;margin-right:12px;">""" + sentiment_label + """</span>
      <span style="color:#888;font-size:14px;">""" + str(sentiment_score) + """ / 10</span>
    </div>
    <div style="background:#f0f0f0;border-radius:8px;height:10px;margin-bottom:16px;">
      <div style="background:""" + sentiment_color + """;width:""" + str(bar_width) + """%;height:10px;border-radius:8px;"></div>
    </div>
    <p style="margin:0;color:#333;font-size:15px;line-height:1.7;">""" + market_summary + """</p>
  </div>

  <div style="background:#1a1a2e;border-radius:16px;padding:22px;margin-bottom:16px;">
    <div style="font-size:11px;font-weight:700;color:#a0b4d6;letter-spacing:1px;text-transform:uppercase;margin-bottom:10px;">Key Thing To Watch Today</div>
    <div style="color:#ffffff;font-size:15px;line-height:1.7;font-weight:500;">""" + key_insight + """</div>
  </div>

  <div style="background:#ffffff;border-radius:16px;padding:24px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,0.08);">
    <div style="font-size:11px;font-weight:700;color:#888;letter-spacing:1px;text-transform:uppercase;margin-bottom:16px;">Market Sentiment Indicators</div>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:16px;">
      <div style="background:#f8f9fa;border-radius:12px;padding:16px;text-align:center;">
        <div style="font-size:11px;font-weight:700;color:#888;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px;">Fear & Greed</div>
        <div style="font-size:26px;font-weight:900;color:""" + fg_color + """;">""" + str(fg_value) + """</div>
        <div style="background:#f0f0f0;border-radius:4px;height:5px;margin:8px 0;">
          <div style="background:""" + fg_color + """;width:""" + str(fg_bar) + """%;height:5px;border-radius:4px;"></div>
        </div>
        <span style="background:""" + fg_bg + """;color:""" + fg_color + """;padding:3px 8px;border-radius:20px;font-weight:700;font-size:11px;">""" + fg_label + """</span>
      </div>
      <div style="background:#f8f9fa;border-radius:12px;padding:16px;text-align:center;">
        <div style="font-size:11px;font-weight:700;color:#888;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px;">VIX</div>
        <div style="font-size:26px;font-weight:900;color:""" + vix_color + """;">""" + str(vix_value) + """</div>
        <div style="font-size:11px;color:#888;margin:6px 0;">""" + ("+" if isinstance(vix_change,(int,float)) and vix_change > 0 else "") + str(vix_change) + "% today" + """</div>
        <span style="background:#f0f0f0;color:""" + vix_color + """;padding:3px 8px;border-radius:20px;font-weight:700;font-size:11px;">""" + vix_label + """</span>
      </div>
      <div style="background:#f8f9fa;border-radius:12px;padding:16px;text-align:center;">
        <div style="font-size:11px;font-weight:700;color:#888;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px;">Put/Call</div>
        <div style="font-size:26px;font-weight:900;color:""" + pc_color + """;">""" + str(pc_value) + """</div>
        <div style="font-size:11px;color:#888;margin:6px 0;">&gt;1.0 = more puts</div>
        <span style="background:#f0f0f0;color:""" + pc_color + """;padding:3px 8px;border-radius:20px;font-weight:700;font-size:11px;">""" + str(pc_label).split(" ")[0] + """</span>
      </div>
    </div>
    <p style="margin:0;color:#444;font-size:14px;line-height:1.7;">""" + sentiment_commentary + """</p>
  </div>

  <div style="background:#ffffff;border-radius:16px;padding:24px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,0.08);">
    <div style="font-size:11px;font-weight:700;color:#888;letter-spacing:1px;text-transform:uppercase;margin-bottom:16px;">Your Watchlist</div>
    <table style="width:100%;border-collapse:collapse;">
      <tr style="background:#f8f9fa;">
        <th style="padding:10px 12px;text-align:left;font-size:12px;color:#999;font-weight:600;">TICKER</th>
        <th style="padding:10px 12px;text-align:left;font-size:12px;color:#999;font-weight:600;">PRICE</th>
        <th style="padding:10px 12px;text-align:left;font-size:12px;color:#999;font-weight:600;">CHANGE</th>
      </tr>""" + stock_rows + """
    </table>
    <p style="margin:16px 0 0;color:#444;font-size:14px;line-height:1.7;">""" + notable_movers_text + """</p>
  </div>

  """ + movers_section + """

  """ + earnings_section + """

  <div style="background:#ffffff;border-radius:16px;padding:24px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,0.08);">
    <div style="font-size:11px;font-weight:700;color:#888;letter-spacing:1px;text-transform:uppercase;margin-bottom:6px;">Swing Trade Opportunities</div>
    <div style="font-size:12px;color:#aaa;margin-bottom:16px;">Technical setups (3-10 day holds) &mdash; not financial advice</div>
    """ + swing_cards + """
  </div>

  <div style="background:#ffffff;border-radius:16px;padding:24px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,0.08);">
    <div style="font-size:11px;font-weight:700;color:#888;letter-spacing:1px;text-transform:uppercase;margin-bottom:6px;">Macro Opportunity Scan</div>
    <div style="font-size:12px;color:#aaa;margin-bottom:16px;">Under-the-radar plays driven by news &amp; economic trends &mdash; not financial advice</div>
    """ + macro_opp_cards + """
  </div>

  <div style="background:#ffffff;border-radius:16px;padding:24px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,0.08);">
    <div style="font-size:11px;font-weight:700;color:#888;letter-spacing:1px;text-transform:uppercase;margin-bottom:16px;">Top Business News</div>
    <table style="width:100%;border-collapse:collapse;">""" + news_items + """</table>
  </div>

  <div style="background:#ffffff;border-radius:16px;padding:24px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,0.08);">
    <div style="font-size:11px;font-weight:700;color:#888;letter-spacing:1px;text-transform:uppercase;margin-bottom:16px;">Macro Indicators</div>
    <table style="width:100%;border-collapse:collapse;">
      <tr style="background:#f8f9fa;">
        <th style="padding:8px 12px;text-align:left;font-size:11px;color:#999;">INDICATOR</th>
        <th style="padding:8px 12px;text-align:center;font-size:11px;color:#999;">VALUE</th>
        <th style="padding:8px 12px;text-align:right;font-size:11px;color:#999;">RATING</th>
      </tr>""" + macro_rows + """
    </table>
    <p style="margin:16px 0 0;color:#444;font-size:14px;line-height:1.7;">""" + macro_context + """</p>
  </div>

  <div style="text-align:center;color:#aaa;font-size:12px;padding:8px;">Generated by your Daily Market Agent &mdash; Not financial advice</div>
</div>
</body>
</html>"""


def send_email(html_content):
    print("Sending email...")
    today = datetime.now().strftime("%B %d, %Y")
    subject = "Your Daily Market Briefing - " + today
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = RECIPIENT_EMAIL
    msg.attach(MIMEText("Please view this email in an HTML-capable email client.", "plain"))
    msg.attach(MIMEText(html_content, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASS)
        server.sendmail(GMAIL_ADDRESS, RECIPIENT_EMAIL, msg.as_string())
    print("Email sent successfully!")


def main():
    print("Starting Daily Market Agent...")
    stock_data = get_stock_data(WATCHLIST)
    news_headlines = get_broad_news()
    macro_data = get_macro_data()
    top_movers = get_sp500_top_movers()
    sentiment_indicators = get_sentiment_indicators()
    earnings_data = get_earnings_data()
    swing_data = get_swing_trade_data(WATCHLIST, top_movers)
    analysis = generate_analysis(stock_data, news_headlines, macro_data, swing_data, top_movers, sentiment_indicators, earnings_data)
    html = build_email_html(stock_data, news_headlines, macro_data, analysis, top_movers, sentiment_indicators, earnings_data)
    send_email(html)
    print("Done! Check your inbox.")


main()
