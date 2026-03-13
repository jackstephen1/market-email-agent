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
        params = {"apikey": FMP_API_KEY}
        gainers = requests.get("https://financialmodelingprep.com/api/v3/stock_market/gainers", params=params, timeout=10).json()[:10]
        losers = requests.get("https://financialmodelingprep.com/api/v3/stock_market/losers", params=params, timeout=10).json()[:10]
        movers = []
        for s in gainers:
            if s.get("symbol") and s.get("price") and float(s.get("price", 0)) > 0:
                movers.append({"ticker": s["symbol"], "price": round(float(s["price"]), 2), "change_pct": round(float(s.get("changesPercentage", 0)), 2), "mover_type": "gainer"})
        for s in losers:
            if s.get("symbol") and s.get("price") and float(s.get("price", 0)) > 0:
                movers.append({"ticker": s["symbol"], "price": round(float(s["price"]), 2), "change_pct": round(float(s.get("changesPercentage", 0)), 2), "mover_type": "loser"})
        print("Got " + str(len(movers)) + " top movers")
        return movers
    except Exception as e:
        print("Could not fetch top movers: " + str(e))
        return []


def get_quote_fmp(ticker):
    try:
        # Use the batch quote endpoint which works on free tier
        url = "https://financialmodelingprep.com/api/v3/quote/" + ticker
        params = {"apikey": FMP_API_KEY}
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        if data and isinstance(data, list) and len(data) > 0:
            q = data[0]
            price = float(q.get("price", 0))
            change_pct = float(q.get("changesPercentage", 0))
            if price > 0:
                print("Got " + ticker + ": $" + str(round(price, 2)))
                return {"ticker": ticker, "price": round(price, 2), "change_pct": round(change_pct, 2), "is_crypto": False}
        print("FMP returned no valid data for " + ticker)
        return None
    except Exception as e:
        print("FMP quote failed for " + ticker + ": " + str(e))
        return None


def get_quote_crypto(ticker):
    try:
        symbol = ticker.replace("-USD", "").replace("-usd", "")
        url = "https://www.alphavantage.co/query"
        # Get current price
        params = {"function": "CURRENCY_EXCHANGE_RATE", "from_currency": symbol, "to_currency": "USD", "apikey": ALPHA_VANTAGE_KEY}
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        rate = data.get("Realtime Currency Exchange Rate", {})
        if not rate:
            print("No exchange rate data for " + ticker)
            return None
        curr_price = float(rate.get("5. Exchange Rate", 0))

        # Get previous close for % change
        time.sleep(12)
        params2 = {"function": "DIGITAL_CURRENCY_DAILY", "symbol": symbol, "market": "USD", "apikey": ALPHA_VANTAGE_KEY}
        response2 = requests.get(url, params=params2, timeout=10)
        data2 = response2.json()
        ts = data2.get("Time Series (Digital Currency Daily)", {})
        change_pct = 0.0
        if ts:
            dates = sorted(ts.keys(), reverse=True)
            if len(dates) >= 2:
                # Try multiple possible key formats for previous close
                prev_entry = ts[dates[1]]
                prev_close = None
                for key in ["4a. close (USD)", "4. close", "4b. close (USD)"]:
                    if key in prev_entry:
                        prev_close = float(prev_entry[key])
                        break
                if prev_close and prev_close > 0:
                    change_pct = ((curr_price - prev_close) / prev_close) * 100

        print("Got " + ticker + ": $" + str(round(curr_price, 2)))
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
                time.sleep(1)
                result = get_quote_fmp(ticker)
            if result:
                results.append(result)
            else:
                print("No data for " + ticker)
        except Exception as e:
            print("Could not fetch " + ticker + ": " + str(e))
    print("Got " + str(len(results)) + " of " + str(len(tickers)) + " tickers")
    return results


def get_technicals_fmp(ticker):
    try:
        result = {"ticker": ticker}
        url = "https://financialmodelingprep.com/api/v3/technical_indicator/daily/" + ticker

        time.sleep(1)
        r = requests.get(url, params={"period": 14, "type": "rsi", "apikey": FMP_API_KEY}, timeout=10)
        data = r.json()
        if data and isinstance(data, list) and len(data) > 0:
            result["rsi"] = round(float(data[0].get("rsi", 0)), 1)

        time.sleep(1)
        r2 = requests.get(url, params={"period": 50, "type": "sma", "apikey": FMP_API_KEY}, timeout=10)
        data2 = r2.json()
        if data2 and isinstance(data2, list) and len(data2) > 0:
            result["sma50"] = round(float(data2[0].get("sma", 0)), 2)

        time.sleep(1)
        r3 = requests.get(url, params={"period": 200, "type": "sma", "apikey": FMP_API_KEY}, timeout=10)
        data3 = r3.json()
        if data3 and isinstance(data3, list) and len(data3) > 0:
            result["sma200"] = round(float(data3[0].get("sma", 0)), 2)

        return result if len(result) > 1 else None
    except Exception as e:
        print("Technicals failed for " + ticker + ": " + str(e))
        return None


def get_swing_trade_data(watchlist_tickers, top_movers):
    print("Fetching technicals for swing trade analysis...")
    stock_tickers = [t for t in watchlist_tickers if "-USD" not in t.upper()]
    mover_tickers = [m["ticker"] for m in top_movers[:8]]
    seen = set()
    combined = []
    for t in stock_tickers + mover_tickers:
        if t not in seen:
            combined.append(t)
            seen.add(t)

    technicals = []
    for ticker in combined[:10]:
        try:
            print("Getting technicals for " + ticker + "...")
            time.sleep(1)
            quote = get_quote_fmp(ticker)
            if not quote or quote["price"] == 0:
                print("Skipping " + ticker + " - no valid price")
                continue
            tech = get_technicals_fmp(ticker)
            if quote and tech:
                combined_data = {**quote, **tech}
                technicals.append(combined_data)
                print("  Price: $" + str(quote["price"]) + " | RSI: " + str(tech.get("rsi", "N/A")) + " | SMA50: $" + str(tech.get("sma50", "N/A")))
        except Exception as e:
            print("Could not get technicals for " + ticker + ": " + str(e))

    return technicals


def get_financial_news():
    print("Fetching financial news...")
    url = "https://newsapi.org/v2/top-headlines"
    params = {"category": "business", "language": "en", "country": "us", "pageSize": 8, "apiKey": NEWS_API_KEY}
    try:
        response = requests.get(url, params=params, timeout=10)
        articles = response.json().get("articles", [])
        headlines = []
        for a in articles:
            if a.get("title") and "[Removed]" not in a.get("title", ""):
                headlines.append({"title": a["title"], "source": a["source"]["name"], "url": a.get("url", "#")})
        print("Got " + str(len(headlines)) + " news articles")
        return headlines[:8]
    except Exception as e:
        print("Could not fetch news: " + str(e))
        return []


def get_macro_data():
    print("Fetching macro indicators...")
    indicators = {"Federal Funds Rate": "FEDFUNDS", "Unemployment Rate": "UNRATE", "10-Year Treasury Yield": "DGS10", "US GDP Growth Rate": "A191RL1Q225SBEA"}
    results = {}
    for name, series_id in indicators.items():
        try:
            params = {"series_id": series_id, "api_key": FRED_API_KEY, "file_type": "json", "sort_order": "desc", "limit": 3}
            response = requests.get("https://api.stlouisfed.org/fred/series/observations", params=params, timeout=10)
            obs = response.json().get("observations", [])
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

    news_text = "\n".join(["- " + n["title"] for n in news_headlines]) if news_headlines else "No news available.\n"

    macro_text = ""
    for k, v in macro_data.items():
        macro_text += k + ": " + v + "\n"

    movers_text = ""
    if top_movers:
        movers_text += "TOP GAINERS:\n"
        for m in [x for x in top_movers if x.get("mover_type") == "gainer"][:5]:
            movers_text += m["ticker"] + ": $" + str(m["price"]) + " (+" + str(m["change_pct"]) + "%)\n"
        movers_text += "TOP LOSERS:\n"
        for m in [x for x in top_movers if x.get("mover_type") == "loser"][:5]:
            movers_text += m["ticker"] + ": $" + str(m["price"]) + " (" + str(m["change_pct"]) + "%)\n"

    swing_text = ""
    if swing_data:
        for s in swing_data:
            if s.get("price", 0) > 0:
                swing_text += s["ticker"] + ": current_price=$" + str(s.get("price")) + " | RSI=" + str(s.get("rsi", "N/A")) + " | 50SMA=$" + str(s.get("sma50", "N/A")) + " | 200SMA=$" + str(s.get("sma200", "N/A")) + "\n"

    prompt = """You are a financial analyst and swing trader. Return ONLY a valid JSON object, no extra text, no markdown.

CRITICAL RULES:
- Entry zones MUST be based on the current_price provided in the technical data. Do not invent prices.
- Always specify timeframe on % moves (e.g. 'down 1.31% today')
- Swing trades are 3-10 day holds, not day trades
- RSI below 35 = oversold, above 70 = overbought
- Only recommend a stock if you have its current price in the data below

WATCHLIST:
""" + stocks_text + """
S&P 500 TOP MOVERS:
""" + movers_text + """
NEWS:
""" + news_text + """
MACRO:
""" + macro_text + """
TECHNICAL DATA (use these exact prices for entry zones):
""" + swing_text + """

Return this exact JSON:
{
  "sentiment_score": <1-10>,
  "sentiment_label": "<Bearish/Neutral/Bullish>",
  "market_summary": "<2-3 sentences on market mood with timeframes on % moves>",
  "key_insight": "<one key thing to watch today>",
  "notable_movers": "<2-3 sentences on standout watchlist stocks with timeframes>",
  "macro_context": "<2-3 sentences on economic data>",
  "swing_trades": [
    {
      "ticker": "<symbol>",
      "current_price": <exact price from technical data>,
      "bias": "<Bullish or Bearish>",
      "timeframe": "<e.g. 3-7 days>",
      "entry_zone": "<price range close to current price>",
      "thesis": "<2-3 sentences explaining the setup>",
      "invalidation": "<price or event that cancels setup>",
      "source": "<Watchlist or S&P 500 Mover or Opportunity>"
    }
  ]
}

Provide 3-5 swing trade ideas using ONLY stocks that appear in the technical data with valid prices."""

    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = message.content[0].text.strip().replace("```json", "").replace("```", "").strip()
    analysis = json.loads(raw)
    print("Sentiment: " + analysis.get("sentiment_label", "?") + " | Swing trades: " + str(len(analysis.get("swing_trades", []))))
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
        sentiment_bg, sentiment_color = "#e8f5e9", "#2e7d32"
    elif sentiment_label == "Bearish":
        sentiment_bg, sentiment_color = "#ffebee", "#c62828"
    else:
        sentiment_bg, sentiment_color = "#fff8e1", "#e65100"

    bar_width = int((sentiment_score / 10) * 100)

    stock_rows = ""
    for s in stock_data:
        chg = s["change_pct"]
        c_color, c_bg, arrow = ("#2e7d32", "#e8f5e9", "&#9650;") if chg >= 0 else ("#c62828", "#ffebee", "&#9660;")
        sign = "+" if chg > 0 else ""
        label = s["ticker"] + " (Crypto)" if s.get("is_crypto") else s["ticker"]
        stock_rows += "<tr style='border-bottom:1px solid #f0f0f0;'><td style='padding:12px;font-weight:700;font-size:15px;color:#1a1a2e;'>" + label + "</td><td style='padding:12px;font-size:15px;color:#333;'>$" + str(s["price"]) + "</td><td style='padding:12px;'><span style='background:" + c_bg + ";color:" + c_color + ";padding:4px 12px;border-radius:20px;font-weight:700;font-size:13px;'>" + arrow + " " + sign + str(chg) + "%</span></td></tr>"

    if not stock_rows:
        stock_rows = "<tr><td colspan='3' style='padding:12px;color:#888;'>Stock data temporarily unavailable.</td></tr>"

    gainer_rows = ""
    loser_rows = ""
    for m in [x for x in top_movers if x.get("mover_type") == "gainer"][:5]:
        sign = "+" if m["change_pct"] > 0 else ""
        gainer_rows += "<tr style='border-bottom:1px solid #f0f0f0;'><td style='padding:8px 12px;font-weight:700;font-size:14px;color:#1a1a2e;'>" + m["ticker"] + "</td><td style='padding:8px 12px;font-size:13px;color:#333;'>$" + str(m["price"]) + "</td><td style='padding:8px 12px;'><span style='background:#e8f5e9;color:#2e7d32;padding:3px 8px;border-radius:20px;font-weight:700;font-size:12px;'>&#9650; " + sign + str(m["change_pct"]) + "%</span></td></tr>"
    for m in [x for x in top_movers if x.get("mover_type") == "loser"][:5]:
        loser_rows += "<tr style='border-bottom:1px solid #f0f0f0;'><td style='padding:8px 12px;font-weight:700;font-size:14px;color:#1a1a2e;'>" + m["ticker"] + "</td><td style='padding:8px 12px;font-size:13px;color:#333;'>$" + str(m["price"]) + "</td><td style='padding:8px 12px;'><span style='background:#ffebee;color:#c62828;padding:3px 8px;border-radius:20px;font-weight:700;font-size:12px;'>&#9660; " + str(m["change_pct"]) + "%</span></td></tr>"

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
        b_color, b_bg, b_icon = ("#2e7d32", "#e8f5e9", "&#9650;") if bias == "Bullish" else ("#c62828", "#ffebee", "&#9660;")
        source = trade.get("source", "Watchlist")
        if source == "Watchlist":
            s_color, s_bg = "#1565c0", "#e3f2fd"
        elif "Mover" in source:
            s_color, s_bg = "#e65100", "#fff3e0"
        else:
            s_color, s_bg = "#6a1b9a", "#f3e5f5"

        current_price = trade.get("current_price", "")
        price_display = " &mdash; Current: $" + str(current_price) if current_price else ""

        swing_cards += "<div style='border:1px solid #e8e8e8;border-radius:12px;padding:20px;margin-bottom:12px;'><div style='margin-bottom:12px;'><span style='font-size:18px;font-weight:900;color:#1a1a2e;margin-right:10px;'>" + trade.get("ticker","") + "</span><span style='background:" + b_bg + ";color:" + b_color + ";padding:3px 10px;border-radius:20px;font-weight:700;font-size:12px;margin-right:6px;'>" + b_icon + " " + bias + "</span><span style='background:" + s_bg + ";color:" + s_color + ";padding:3px 10px;border-radius:20px;font-weight:600;font-size:11px;'>" + source + "</span></div><div style='background:#f8f9fa;border-radius:8px;padding:12px;margin-bottom:12px;display:flex;justify-content:space-between;align-items:center;'><div><div style='font-size:11px;font-weight:700;color:#888;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px;'>Entry Zone</div><div style='font-size:15px;font-weight:700;color:#1a1a2e;'>" + trade.get("entry_zone","") + "</div></div><div style='text-align:right;'><div style='font-size:11px;font-weight:700;color:#888;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px;'>Timeframe</div><div style='font-size:14px;font-weight:600;color:#555;'>" + trade.get("timeframe","") + "</div></div></div>" + ("<div style='font-size:12px;color:#888;margin-bottom:8px;'>Current price" + price_display + "</div>" if price_display else "") + "<p style='margin:0 0 12px;color:#333;font-size:14px;line-height:1.7;'>" + trade.get("thesis","") + "</p><div style='border-top:1px solid #f0f0f0;padding-top:10px;'><span style='font-size:12px;color:#e65100;font-weight:600;'>Invalidated if: </span><span style='font-size:12px;color:#666;'>" + trade.get("invalidation","") + "</span></div></div>"

    if not swing_cards:
        swing_cards = "<p style='color:#888;font-size:14px;'>No clear swing setups identified today.</p>"

    movers_section = ""
    if gainer_rows or loser_rows:
        movers_section = "<div style='background:#ffffff;border-radius:16px;padding:24px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,0.08);'><div style='font-size:11px;font-weight:700;color:#888;letter-spacing:1px;text-transform:uppercase;margin-bottom:16px;'>S&P 500 Top Movers Today</div><table style='width:100%;border-collapse:collapse;'><tr><td style='width:50%;vertical-align:top;padding-right:8px;'><div style='font-size:12px;font-weight:700;color:#2e7d32;margin-bottom:8px;'>TOP GAINERS</div><table style='width:100%;border-collapse:collapse;'>" + gainer_rows + "</table></td><td style='width:50%;vertical-align:top;padding-left:8px;'><div style='font-size:12px;font-weight:700;color:#c62828;margin-bottom:8px;'>TOP LOSERS</div><table style='width:100%;border-collapse:collapse;'>" + loser_rows + "</table></td></tr></table></div>"

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
      </tr>""" + stock_rows + """
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
