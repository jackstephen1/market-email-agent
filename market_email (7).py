import requests
import smtplib
import os
import json
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
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
        url = "https://financialmodelingprep.com/api/v3/stock_market/gainers"
        params = {"apikey": FMP_API_KEY}
        response = requests.get(url, params=params, timeout=10)
        gainers = response.json()[:10]

        url2 = "https://financialmodelingprep.com/api/v3/stock_market/losers"
        response2 = requests.get(url2, params=params, timeout=10)
        losers = response2.json()[:10]

        movers = []
        for s in gainers:
            if s.get("symbol") and s.get("price"):
                movers.append({
                    "ticker": s["symbol"],
                    "price": round(float(s["price"]), 2),
                    "change_pct": round(float(s.get("changesPercentage", 0)), 2),
                    "is_crypto": False,
                    "mover_type": "gainer"
                })
        for s in losers:
            if s.get("symbol") and s.get("price"):
                movers.append({
                    "ticker": s["symbol"],
                    "price": round(float(s["price"]), 2),
                    "change_pct": round(float(s.get("changesPercentage", 0)), 2),
                    "is_crypto": False,
                    "mover_type": "loser"
                })

        print("Got " + str(len(movers)) + " top movers")
        return movers
    except Exception as e:
        print("Could not fetch top movers: " + str(e))
        return []


def get_quote_fmp(ticker):
    try:
        url = "https://financialmodelingprep.com/api/v3/quote-short/" + ticker
        params = {"apikey": FMP_API_KEY}
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        if data and len(data) > 0:
            q = data[0]
            return {
                "ticker": ticker,
                "price": round(float(q.get("price", 0)), 2),
                "change_pct": round(float(q.get("changesPercentage", 0)), 2),
                "is_crypto": False
            }
    except Exception as e:
        print("FMP quote failed for " + ticker + ": " + str(e))
    return None


def get_quote_crypto(ticker):
    try:
        symbol = ticker.replace("-USD", "").replace("-usd", "")
        url = "https://www.alphavantage.co/query"
        params = {
            "function": "CURRENCY_EXCHANGE_RATE",
            "from_currency": symbol,
            "to_currency": "USD",
            "apikey": ALPHA_VANTAGE_KEY
        }
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        rate = data.get("Realtime Currency Exchange Rate", {})
        if rate:
            curr_price = float(rate.get("5. Exchange Rate", 0))
            time.sleep(12)
            params2 = {
                "function": "DIGITAL_CURRENCY_DAILY",
                "symbol": symbol,
                "market": "USD",
                "apikey": ALPHA_VANTAGE_KEY
            }
            response2 = requests.get(url, params=params2, timeout=10)
            data2 = response2.json()
            ts = data2.get("Time Series (Digital Currency Daily)", {})
            if ts:
                dates = sorted(ts.keys(), reverse=True)
                prev_close = float(ts[dates[1]]["4a. close (USD)"])
                change_pct = ((curr_price - prev_close) / prev_close) * 100
            else:
                change_pct = 0.0
            return {"ticker": ticker, "price": round(curr_price, 2), "change_pct": round(change_pct, 2), "is_crypto": True}
    except Exception as e:
        print("Crypto quote failed for " + ticker + ": " + str(e))
    return None


def get_stock_data(tickers):
    print("Fetching watchlist quotes...")
    results = []
    for ticker in tickers:
        try:
            if "-USD" in ticker.upper():
                time.sleep(12)
                result = get_quote_crypto(ticker)
            else:
                result = get_quote_fmp(ticker)
                time.sleep(1)
            if result:
                results.append(result)
                print("Got " + ticker + ": $" + str(result["price"]))
            else:
                print("No data for " + ticker)
        except Exception as e:
            print("Could not fetch " + ticker + ": " + str(e))
    print("Got " + str(len(results)) + " of " + str(len(tickers)) + " tickers")
    return results


def get_technicals_fmp(ticker):
    try:
        result = {"ticker": ticker}

        # Get RSI
        url = "https://financialmodelingprep.com/api/v3/technical_indicator/daily/" + ticker
        params = {"period": 14, "type": "rsi", "apikey": FMP_API_KEY}
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        if data and len(data) > 0:
            result["rsi"] = round(float(data[0].get("rsi", 0)), 1)
        time.sleep(1)

        # Get SMA 50
        params2 = {"period": 50, "type": "sma", "apikey": FMP_API_KEY}
        r2 = requests.get(url, params=params2, timeout=10)
        data2 = r2.json()
        if data2 and len(data2) > 0:
            result["sma50"] = round(float(data2[0].get("sma", 0)), 2)
        time.sleep(1)

        # Get SMA 200
        params3 = {"period": 200, "type": "sma", "apikey": FMP_API_KEY}
        r3 = requests.get(url, params=params3, timeout=10)
        data3 = r3.json()
        if data3 and len(data3) > 0:
            result["sma200"] = round(float(data3[0].get("sma", 0)), 2)

        return result if len(result) > 1 else None
    except Exception as e:
        print("Technicals failed for " + ticker + ": " + str(e))
        return None


def get_swing_trade_data(watchlist_tickers, top_movers):
    print("Fetching technicals for swing trade analysis...")

    # Combine watchlist stocks + top movers, deduplicated, no crypto
    stock_tickers = [t for t in watchlist_tickers if "-USD" not in t.upper()]
    mover_tickers = [m["ticker"] for m in top_movers[:10]]

    combined = []
    seen = set()
    for t in stock_tickers + mover_tickers:
        if t not in seen:
            combined.append(t)
            seen.add(t)

    # Scan top 12 to stay within API limits
    scan_list = combined[:12]
    technicals = []

    for ticker in scan_list:
        try:
            print("Getting technicals for " + ticker + "...")
            quote = get_quote_fmp(ticker)
            time.sleep(1)
            tech = get_technicals_fmp(ticker)
            time.sleep(1)
            if quote and tech:
                combined_data = {**quote, **tech}
                technicals.append(combined_data)
                print("  RSI: " + str(tech.get("rsi", "N/A")) + " | SMA50: $" + str(tech.get("sma50", "N/A")))
        except Exception as e:
            print("Could not get technicals for " + ticker + ": " + str(e))

    return technicals


def get_financial_news():
    print("Fetching financial news...")
    url = "https://newsapi.org/v2/top-headlines"
    params = {
        "category": "business",
        "language": "en",
        "country": "us",
        "pageSize": 8,
        "apiKey": NEWS_API_KEY
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        articles = response.json().get("articles", [])
        headlines = []
        for a in articles:
            if a.get("title") and "[Removed]" not in a.get("title", ""):
                headlines.append({
                    "title": a["title"],
                    "source": a["source"]["name"],
                    "url": a.get("url", "#")
                })
        print("Got " + str(len(headlines)) + " news articles")
        return headlines[:8]
    except Exception as e:
        print("Could not fetch news: " + str(e))
        return []


def get_macro_data():
    print("Fetching macro indicators...")
    indicators = {
        "Federal Funds Rate": "FEDFUNDS",
        "Unemployment Rate": "UNRATE",
        "10-Year Treasury Yield": "DGS10",
        "US GDP Growth Rate": "A191RL1Q225SBEA"
    }
    results = {}
    base_url = "https://api.stlouisfed.org/fred/series/observations"
    for name, series_id in indicators.items():
        try:
            params = {
                "series_id": series_id,
                "api_key": FRED_API_KEY,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 3
            }
            response = requests.get(base_url, params=params, timeout=10)
            data = response.json()
            obs = data.get("observations", [])
            value = "N/A"
            for o in obs:
                if o.get("value") and o["value"] != ".":
                    value = o["value"]
                    break
            results[name] = value
            print("Got " + name + ": " + value)
        except Exception as e:
            print("Could not fetch " + name + ": " + str(e))
            results[name] = "N/A"
    return results


def generate_analysis(stock_data, news_headlines, macro_data, swing_data, top_movers):
    print("Generating AI analysis...")
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    stocks_text = ""
    if stock_data:
        for s in stock_data:
            sign = "+" if s["change_pct"] > 0 else ""
            stocks_text += s["ticker"] + ": $" + str(s["price"]) + " (" + sign + str(s["change_pct"]) + "% today)\n"
    else:
        stocks_text = "Stock data unavailable today.\n"

    news_text = ""
    if news_headlines:
        for n in news_headlines:
            news_text += "- " + n["title"] + "\n"
    else:
        news_text = "No news available.\n"

    macro_text = ""
    for k, v in macro_data.items():
        macro_text += k + ": " + v + "\n"

    movers_text = ""
    if top_movers:
        gainers = [m for m in top_movers if m.get("mover_type") == "gainer"][:5]
        losers = [m for m in top_movers if m.get("mover_type") == "loser"][:5]
        movers_text += "TOP GAINERS TODAY:\n"
        for m in gainers:
            movers_text += m["ticker"] + ": $" + str(m["price"]) + " (+" + str(m["change_pct"]) + "%)\n"
        movers_text += "TOP LOSERS TODAY:\n"
        for m in losers:
            movers_text += m["ticker"] + ": $" + str(m["price"]) + " (" + str(m["change_pct"]) + "%)\n"

    swing_text = ""
    if swing_data:
        for s in swing_data:
            swing_text += s["ticker"] + ": price=$" + str(s.get("price", "N/A"))
            swing_text += " | RSI=" + str(s.get("rsi", "N/A"))
            swing_text += " | 50SMA=$" + str(s.get("sma50", "N/A"))
            swing_text += " | 200SMA=$" + str(s.get("sma200", "N/A")) + "\n"

    prompt = """You are a financial analyst and swing trader. Based on the data below, return ONLY a valid JSON object. No extra text, no markdown, no code blocks. Just raw JSON.

IMPORTANT RULES:
- Always specify timeframe on any percentage move (e.g. 'down 1.31% today', 'up 2.5% this week')
- Swing trade setups are for weekly timeframes (3-10 day holds), NOT day trades
- RSI below 35 = oversold (potential buy), RSI above 70 = overbought (potential short/sell)
- Price above SMA50 and SMA200 = bullish trend, below = bearish trend
- Consider top movers as potential setups - big losers can be bounce candidates, big gainers may have momentum
- Be specific about entry zones, reasoning, and what would invalidate the setup

WATCHLIST:
""" + stocks_text + """
S&P 500 TOP MOVERS TODAY:
""" + movers_text + """
NEWS:
""" + news_text + """
MACRO DATA:
""" + macro_text + """
TECHNICAL DATA:
""" + swing_text + """

Return exactly this JSON:
{
  "sentiment_score": <1-10>,
  "sentiment_label": "<Bearish/Neutral/Bullish>",
  "market_summary": "<2-3 sentences on overall market mood with timeframes on any % moves>",
  "key_insight": "<one key thing to watch today>",
  "notable_movers": "<2-3 sentences on standout watchlist stocks with timeframes>",
  "macro_context": "<2-3 sentences on what economic data suggests>",
  "swing_trades": [
    {
      "ticker": "<ticker symbol>",
      "bias": "<Bullish or Bearish>",
      "timeframe": "<e.g. 3-7 days>",
      "entry_zone": "<price range to consider entering>",
      "thesis": "<2-3 sentences explaining the setup and why>",
      "invalidation": "<what price or event would cancel this setup>",
      "source": "<Watchlist or S&P 500 Mover or Opportunity>"
    }
  ]
}

Provide 3-5 swing trade ideas. Prioritize the most compelling setups from the watchlist, S&P 500 movers, and any other opportunities you identify from the news and macro context."""

    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = message.content[0].text.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    analysis = json.loads(raw)
    print("Analysis generated. Sentiment: " + analysis.get("sentiment_label", "?"))
    print("Swing trades found: " + str(len(analysis.get("swing_trades", []))))
    return analysis


def build_email_html(stock_data, news_headlines, macro_data, analysis, top_movers):
    today = datetime.now().strftime("%A, %B %d, %Y")

    sentiment_score = analysis.get("sentiment_score", 5)
    sentiment_label = analysis.get("sentiment_label", "Neutral")
    market_summary = analysis.get("market_summary", "")
    key_insight = analysis.get("key_insight", "")
    notable_movers = analysis.get("notable_movers", "")
    macro_context = analysis.get("macro_context", "")
    swing_trades = analysis.get("swing_trades", [])

    if sentiment_label == "Bullish":
        sentiment_bg = "#e8f5e9"
        sentiment_color = "#2e7d32"
    elif sentiment_label == "Bearish":
        sentiment_bg = "#ffebee"
        sentiment_color = "#c62828"
    else:
        sentiment_bg = "#fff8e1"
        sentiment_color = "#e65100"

    bar_width = int((sentiment_score / 10) * 100)

    stock_rows = ""
    for s in stock_data:
        if s["change_pct"] >= 0:
            change_color = "#2e7d32"
            change_bg = "#e8f5e9"
            arrow = "&#9650;"
        else:
            change_color = "#c62828"
            change_bg = "#ffebee"
            arrow = "&#9660;"
        sign = "+" if s["change_pct"] > 0 else ""
        label = s["ticker"] + " (Crypto)" if s.get("is_crypto") else s["ticker"]
        stock_rows += "<tr style='border-bottom:1px solid #f0f0f0;'><td style='padding:12px;font-weight:700;font-size:15px;color:#1a1a2e;'>" + label + "</td><td style='padding:12px;font-size:15px;color:#333;'>$" + str(s["price"]) + "</td><td style='padding:12px;'><span style='background:" + change_bg + ";color:" + change_color + ";padding:4px 12px;border-radius:20px;font-weight:700;font-size:13px;'>" + arrow + " " + sign + str(s["change_pct"]) + "%</span></td></tr>"

    if not stock_rows:
        stock_rows = "<tr><td colspan='3' style='padding:12px;color:#888;'>Stock data temporarily unavailable.</td></tr>"

    # Top movers section
    gainer_rows = ""
    loser_rows = ""
    for m in [x for x in top_movers if x.get("mover_type") == "gainer"][:5]:
        sign = "+" if m["change_pct"] > 0 else ""
        gainer_rows += "<tr style='border-bottom:1px solid #f0f0f0;'><td style='padding:8px 12px;font-weight:700;font-size:14px;color:#1a1a2e;'>" + m["ticker"] + "</td><td style='padding:8px 12px;font-size:14px;color:#333;'>$" + str(m["price"]) + "</td><td style='padding:8px 12px;'><span style='background:#e8f5e9;color:#2e7d32;padding:3px 10px;border-radius:20px;font-weight:700;font-size:12px;'>&#9650; " + sign + str(m["change_pct"]) + "%</span></td></tr>"

    for m in [x for x in top_movers if x.get("mover_type") == "loser"][:5]:
        loser_rows += "<tr style='border-bottom:1px solid #f0f0f0;'><td style='padding:8px 12px;font-weight:700;font-size:14px;color:#1a1a2e;'>" + m["ticker"] + "</td><td style='padding:8px 12px;font-size:14px;color:#333;'>$" + str(m["price"]) + "</td><td style='padding:8px 12px;'><span style='background:#ffebee;color:#c62828;padding:3px 10px;border-radius:20px;font-weight:700;font-size:12px;'>&#9660; " + str(m["change_pct"]) + "%</span></td></tr>"

    news_items = ""
    for n in news_headlines:
        news_items += "<tr style='border-bottom:1px solid #f5f5f5;'><td style='padding:12px;'><a href='" + n.get("url","#") + "' style='color:#1a1a2e;text-decoration:none;font-size:14px;font-weight:600;'>" + n["title"] + "</a><div style='color:#888;font-size:12px;margin-top:3px;'>" + n["source"] + "</div></td></tr>"

    if not news_items:
        news_items = "<tr><td style='padding:12px;color:#888;'>No news available today.</td></tr>"

    macro_rows = ""
    for k, v in macro_data.items():
        macro_rows += "<tr style='border-bottom:1px solid #f0f0f0;'><td style='padding:10px 12px;color:#555;font-size:14px;'>" + k + "</td><td style='padding:10px 12px;font-weight:700;font-size:14px;color:#1a1a2e;text-align:right;'>" + v + "</td></tr>"

    swing_cards = ""
    for trade in swing_trades:
        bias = trade.get("bias", "Bullish")
        if bias == "Bullish":
            bias_color = "#2e7d32"
            bias_bg = "#e8f5e9"
            bias_icon = "&#9650;"
        else:
            bias_color = "#c62828"
            bias_bg = "#ffebee"
            bias_icon = "&#9660;"

        source = trade.get("source", "Watchlist")
        if source == "Watchlist":
            source_color = "#1565c0"
            source_bg = "#e3f2fd"
        elif "Mover" in source:
            source_color = "#e65100"
            source_bg = "#fff3e0"
        else:
            source_color = "#6a1b9a"
            source_bg = "#f3e5f5"

        swing_cards += "<div style='border:1px solid #e8e8e8;border-radius:12px;padding:20px;margin-bottom:12px;'><div style='margin-bottom:12px;'><span style='font-size:18px;font-weight:900;color:#1a1a2e;margin-right:10px;'>" + trade.get("ticker","") + "</span><span style='background:" + bias_bg + ";color:" + bias_color + ";padding:3px 10px;border-radius:20px;font-weight:700;font-size:12px;margin-right:6px;'>" + bias_icon + " " + bias + "</span><span style='background:" + source_bg + ";color:" + source_color + ";padding:3px 10px;border-radius:20px;font-weight:600;font-size:11px;margin-right:6px;'>" + source + "</span><span style='color:#888;font-size:12px;font-weight:600;'>" + trade.get("timeframe","") + "</span></div><div style='background:#f8f9fa;border-radius:8px;padding:12px;margin-bottom:12px;'><div style='font-size:11px;font-weight:700;color:#888;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px;'>Entry Zone</div><div style='font-size:15px;font-weight:700;color:#1a1a2e;'>" + trade.get("entry_zone","") + "</div></div><p style='margin:0 0 12px;color:#333;font-size:14px;line-height:1.7;'>" + trade.get("thesis","") + "</p><div style='border-top:1px solid #f0f0f0;padding-top:10px;'><span style='font-size:12px;color:#e65100;font-weight:600;'>Invalidated if: </span><span style='font-size:12px;color:#666;'>" + trade.get("invalidation","") + "</span></div></div>"

    if not swing_cards:
        swing_cards = "<p style='color:#888;font-size:14px;'>No clear swing setups identified today.</p>"

    movers_section = ""
    if gainer_rows or loser_rows:
        movers_section = """
  <div style="background:#ffffff;border-radius:16px;padding:24px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,0.08);">
    <div style="font-size:11px;font-weight:700;color:#888;letter-spacing:1px;text-transform:uppercase;margin-bottom:16px;">S&P 500 Top Movers Today</div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
      <div>
        <div style="font-size:12px;font-weight:700;color:#2e7d32;margin-bottom:8px;">TOP GAINERS</div>
        <table style="width:100%;border-collapse:collapse;">""" + gainer_rows + """</table>
      </div>
      <div>
        <div style="font-size:12px;font-weight:700;color:#c62828;margin-bottom:8px;">TOP LOSERS</div>
        <table style="width:100%;border-collapse:collapse;">""" + loser_rows + """</table>
      </div>
    </div>
  </div>"""

    html = """<!DOCTYPE html>
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
    <div style="font-size:11px;font-weight:700;color:#888;letter-spacing:1px;text-transform:uppercase;margin-bottom:16px;">Your Watchlist</div>
    <table style="width:100%;border-collapse:collapse;">
      <tr style="background:#f8f9fa;">
        <th style="padding:10px 12px;text-align:left;font-size:12px;color:#999;font-weight:600;">TICKER</th>
        <th style="padding:10px 12px;text-align:left;font-size:12px;color:#999;font-weight:600;">PRICE</th>
        <th style="padding:10px 12px;text-align:left;font-size:12px;color:#999;font-weight:600;">CHANGE</th>
      </tr>
      """ + stock_rows + """
    </table>
    <p style="margin:16px 0 0;color:#444;font-size:14px;line-height:1.7;">""" + notable_movers + """</p>
  </div>

  """ + movers_section + """

  <div style="background:#ffffff;border-radius:16px;padding:24px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,0.08);">
    <div style="font-size:11px;font-weight:700;color:#888;letter-spacing:1px;text-transform:uppercase;margin-bottom:6px;">Swing Trade Opportunities</div>
    <div style="font-size:12px;color:#aaa;margin-bottom:16px;">Weekly timeframe (3-10 day holds) &mdash; not financial advice</div>
    """ + swing_cards + """
  </div>

  <div style="background:#ffffff;border-radius:16px;padding:24px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,0.08);">
    <div style="font-size:11px;font-weight:700;color:#888;letter-spacing:1px;text-transform:uppercase;margin-bottom:16px;">Top Business News</div>
    <table style="width:100%;border-collapse:collapse;">""" + news_items + """</table>
  </div>

  <div style="background:#ffffff;border-radius:16px;padding:24px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,0.08);">
    <div style="font-size:11px;font-weight:700;color:#888;letter-spacing:1px;text-transform:uppercase;margin-bottom:16px;">Macro Indicators</div>
    <table style="width:100%;border-collapse:collapse;">""" + macro_rows + """</table>
    <p style="margin:16px 0 0;color:#444;font-size:14px;line-height:1.7;">""" + macro_context + """</p>
  </div>

  <div style="text-align:center;color:#aaa;font-size:12px;padding:8px;">Generated by your Daily Market Agent &mdash; Not financial advice</div>

</div>
</body>
</html>"""

    return html


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
    news_headlines = get_financial_news()
    macro_data = get_macro_data()
    top_movers = get_sp500_top_movers()
    swing_data = get_swing_trade_data(WATCHLIST, top_movers)
    analysis = generate_analysis(stock_data, news_headlines, macro_data, swing_data, top_movers)
    html = build_email_html(stock_data, news_headlines, macro_data, analysis, top_movers)
    send_email(html)
    print("Done! Check your inbox.")


main()
