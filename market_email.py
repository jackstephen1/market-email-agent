import yfinance as yf
import requests
import smtplib
import os
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import anthropic

WATCHLIST = ["AAPL", "MSFT", "GOOGL", "NVDA", "SPY", "QQQ", "BTC-USD"]

NEWS_API_KEY = os.environ["NEWS_API_KEY"]
FRED_API_KEY = os.environ["FRED_API_KEY"]
ANTHROPIC_KEY = os.environ["ANTHROPIC_API_KEY"]
GMAIL_ADDRESS = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASS = os.environ["GMAIL_APP_PASSWORD"]
RECIPIENT_EMAIL = os.environ["RECIPIENT_EMAIL"]


def get_stock_data(tickers):
    print("Fetching stock data...")
    results = []
    for ticker in tickers:
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="5d")
            hist = hist.dropna()
            if len(hist) >= 2:
                prev_close = float(hist["Close"].iloc[-2])
                curr_close = float(hist["Close"].iloc[-1])
                change_pct = ((curr_close - prev_close) / prev_close) * 100
                results.append({
                    "ticker": ticker,
                    "price": round(curr_close, 2),
                    "change_pct": round(change_pct, 2)
                })
                print("Got " + ticker + ": $" + str(round(curr_close, 2)))
            else:
                print("Not enough history for " + ticker)
        except Exception as e:
            print("Could not fetch " + ticker + ": " + str(e))
    return results


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


def generate_analysis(stock_data, news_headlines, macro_data):
    print("Generating AI analysis...")
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    stocks_text = ""
    if stock_data:
        for s in stock_data:
            sign = "+" if s["change_pct"] > 0 else ""
            stocks_text += s["ticker"] + ": $" + str(s["price"]) + " (" + sign + str(s["change_pct"]) + "%)\n"
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

    prompt = "You are a financial analyst. Based on the data below, return ONLY a valid JSON object. No extra text, no markdown, no code blocks. Just raw JSON.\n\nWATCHLIST:\n" + stocks_text + "\nNEWS:\n" + news_text + "\nMACRO DATA:\n" + macro_text + "\n\nReturn exactly this JSON structure:\n{\"sentiment_score\": <1-10 number>, \"sentiment_label\": \"<Bearish/Neutral/Bullish>\", \"market_summary\": \"<2-3 sentences on overall market mood>\", \"key_insight\": \"<one key thing to watch today>\", \"notable_movers\": \"<2-3 sentences on standout stocks>\", \"macro_context\": \"<2-3 sentences on what economic data suggests>\"}"

    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = message.content[0].text.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    analysis = json.loads(raw)
    print("Analysis generated. Sentiment: " + analysis.get("sentiment_label", "?"))
    return analysis


def build_email_html(stock_data, news_headlines, macro_data, analysis):
    today = datetime.now().strftime("%A, %B %d, %Y")

    sentiment_score = analysis.get("sentiment_score", 5)
    sentiment_label = analysis.get("sentiment_label", "Neutral")
    market_summary = analysis.get("market_summary", "")
    key_insight = analysis.get("key_insight", "")
    notable_movers = analysis.get("notable_movers", "")
    macro_context = analysis.get("macro_context", "")

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
        stock_rows += "<tr style='border-bottom:1px solid #f0f0f0;'><td style='padding:12px;font-weight:700;font-size:15px;color:#1a1a2e;'>" + s["ticker"] + "</td><td style='padding:12px;font-size:15px;color:#333;'>$" + str(s["price"]) + "</td><td style='padding:12px;'><span style='background:" + change_bg + ";color:" + change_color + ";padding:4px 12px;border-radius:20px;font-weight:700;font-size:13px;'>" + arrow + " " + sign + str(s["change_pct"]) + "%</span></td></tr>"

    if not stock_rows:
        stock_rows = "<tr><td colspan='3' style='padding:12px;color:#888;'>No stock data available today.</td></tr>"

    news_items = ""
    for n in news_headlines:
        news_items += "<tr style='border-bottom:1px solid #f5f5f5;'><td style='padding:12px;'><a href='" + n.get("url","#") + "' style='color:#1a1a2e;text-decoration:none;font-size:14px;font-weight:600;'>" + n["title"] + "</a><div style='color:#888;font-size:12px;margin-top:3px;'>" + n["source"] + "</div></td></tr>"

    if not news_items:
        news_items = "<tr><td style='padding:12px;color:#888;'>No news available today.</td></tr>"

    macro_rows = ""
    for k, v in macro_data.items():
        macro_rows += "<tr style='border-bottom:1px solid #f0f0f0;'><td style='padding:10px 12px;color:#555;font-size:14px;'>" + k + "</td><td style='padding:10px 12px;font-weight:700;font-size:14px;color:#1a1a2e;text-align:right;'>" + v + "</td></tr>"

    html = """<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f0f2f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<div style="max-width:600px;margin:0 auto;padding:24px 16px;">

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

  <div style="background:#ffffff;border-radius:16px;padding:24px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,0.08);">
    <div style="font-size:11px;font-weight:700;color:#888;letter-spacing:1px;text-transform:uppercase;margin-bottom:16px;">Top Business News</div>
    <table style="width:100%;border-collapse:collapse;">""" + news_items + """</table>
  </div>

  <div style="background:#ffffff;border-radius:16px;padding:24px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,0.08);">
    <div style="font-size:11px;font-weight:700;color:#888;letter-spacing:1px;text-transform:uppercase;margin-bottom:16px;">Macro Indicators</div>
    <table style="width:100%;border-collapse:collapse;">""" + macro_rows + """</table>
    <p style="margin:16px 0 0;color:#444;font-size:14px;line-height:1.7;">""" + macro_context + """</p>
  </div>

  <div style="text-align:center;color:#aaa;font-size:12px;padding:8px;">Generated by your Daily Market Agent</div>

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
    analysis = generate_analysis(stock_data, news_headlines, macro_data)
    html = build_email_html(stock_data, news_headlines, macro_data, analysis)
    send_email(html)
    print("Done! Check your inbox.")


main()
