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
            hist = stock.history(period="2d")
            if len(hist) >= 2:
                prev_close = hist["Close"].iloc[-2]
                curr_close = hist["Close"].iloc[-1]
                change_pct = ((curr_close - prev_close) / prev_close) * 100
                results.append({
                    "ticker": ticker,
                    "price": round(curr_close, 2),
                    "change_pct": round(change_pct, 2)
                })
        except Exception as e:
            print("Could not fetch " + ticker + ": " + str(e))
    return results


def get_financial_news():
    print("Fetching financial news...")
    url = "https://newsapi.org/v2/top-headlines"
    params = {
        "category": "business",
        "language": "en",
        "pageSize": 8,
        "apiKey": NEWS_API_KEY
    }
    try:
        response = requests.get(url, params=params)
        articles = response.json().get("articles", [])
        headlines = []
        for a in articles:
            if a.get("title"):
                headlines.append({
                    "title": a["title"],
                    "source": a["source"]["name"],
                    "url": a.get("url", "#")
                })
        return headlines[:8]
    except Exception as e:
        print("Could not fetch news: " + str(e))
        return []


def get_macro_data():
    print("Fetching macro indicators...")
    indicators = {
        "Federal Funds Rate": "FEDFUNDS",
        "CPI Inflation": "CPIAUCSL",
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
                "limit": 1
            }
            response = requests.get(base_url, params=params)
            data = response.json()
            value = data["observations"][0]["value"]
            results[name] = value
        except Exception as e:
            print("Could not fetch " + name + ": " + str(e))
            results[name] = "N/A"
    return results


def generate_analysis(stock_data, news_headlines, macro_data):
    print("Generating AI analysis...")
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    stocks_text = ""
    for s in stock_data:
        sign = "+" if s["change_pct"] > 0 else ""
        stocks_text += s["ticker"] + ": $" + str(s["price"]) + " (" + sign + str(s["change_pct"]) + "%)\n"

    news_text = ""
    for n in news_headlines:
        news_text += "- " + n["title"] + "\n"

    macro_text = ""
    for k, v in macro_data.items():
        macro_text += k + ": " + v + "\n"

    prompt = """You are a financial analyst. Based on the data below, return ONLY a valid JSON object with no extra text, no markdown, no code blocks.

WATCHLIST:
""" + stocks_text + """
NEWS:
""" + news_text + """
MACRO DATA:
""" + macro_text + """

Return this exact JSON structure:
{
  "sentiment_score": <number from 1-10 where 1=very bearish, 10=very bullish>,
  "sentiment_label": "<Bearish / Neutral / Bullish>",
  "sentiment_color": "<#d32f2f for bearish / #f57c00 for neutral / #2e7d32 for bullish>",
  "market_summary": "<2-3 sentence overall market mood>",
  "key_insight": "<one bold insight or thing to watch today>",
  "notable_movers": "<2-3 sentences about standout stocks from the watchlist>",
  "macro_context": "<2-3 sentences on what the economic data suggests>"
}"""

    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = message.content[0].text.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    analysis = json.loads(raw)
    return analysis


def build_email_html(stock_data, news_headlines, macro_data, analysis):
    today = datetime.now().strftime("%A, %B %d, %Y")

    sentiment_score = analysis.get("sentiment_score", 5)
    sentiment_label = analysis.get("sentiment_label", "Neutral")
    sentiment_color = analysis.get("sentiment_color", "#f57c00")
    market_summary = analysis.get("market_summary", "")
    key_insight = analysis.get("key_insight", "")
    notable_movers = analysis.get("notable_movers", "")
    macro_context = analysis.get("macro_context", "")

    bar_width = int((sentiment_score / 10) * 100)

    stock_rows = ""
    for s in stock_data:
        if s["change_pct"] >= 0:
            color = "#2e7d32"
            bg = "#e8f5e9"
            arrow = "▲"
        else:
            color = "#c62828"
            bg = "#ffebee"
            arrow = "▼"
        stock_rows += """
        <tr style="border-bottom: 1px solid #f0f0f0;">
            <td style="padding: 10px 12px; font-weight: 700; font-size: 15px;">{ticker}</td>
            <td style="padding: 10px 12px; font-size: 15px;">${price}</td>
            <td style="padding: 10px 12px;">
                <span style="background:{bg}; color:{color}; padding: 4px 10px; border-radius: 20px; font-weight: 700; font-size: 13px;">
                    {arrow} {change}%
                </span>
            </td>
        </tr>""".format(
            ticker=s["ticker"],
            price=s["price"],
            bg=bg,
            color=color,
            arrow=arrow,
            change=("{:+.2f}".format(s["change_pct"]))
        )

    news_items = ""
    for n in news_headlines:
        news_items += """
        <tr style="border-bottom: 1px solid #f5f5f5;">
            <td style="padding: 10px 12px;">
                <a href="{url}" style="color: #1a1a2e; text-decoration: none; font-size: 14px; font-weight: 500;">{title}</a>
                <span style="display: block; color: #999; font-size: 12px; margin-top: 2px;">{source}</span>
            </td>
        </tr>""".format(
            url=n.get("url", "#"),
            title=n["title"],
            source=n["source"]
        )

    macro_rows = ""
    for k, v in macro_data.items():
        macro_rows += """
        <tr style="border-bottom: 1px solid #f0f0f0;">
            <td style="padding: 8px 12px; color: #555; font-size: 14px;">{key}</td>
            <td style="padding: 8px 12px; font-weight: 700; font-size: 14px; text-align: right;">{val}</td>
        </tr>""".format(key=k, val=v)

    html = """
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0; padding:0; background:#f4f6f9; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">

  <div style="max-width: 620px; margin: 0 auto; padding: 20px;">

    <!-- HEADER -->
    <div style="background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%); border-radius: 16px; padding: 30px; margin-bottom: 16px; text-align: center;">
      <div style="font-size: 28px; font-weight: 900; color: #ffffff; letter-spacing: -0.5px;">
        Market Briefing
      </div>
      <div style="color: #a0b4d6; font-size: 14px; margin-top: 6px;">{today}</div>
    </div>

    <!-- SENTIMENT SCORE -->
    <div style="background: #ffffff; border-radius: 16px; padding: 24px; margin-bottom: 16px; box-shadow: 0 2px 8px rgba(0,0,0,0.06);">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
        <span style="font-size: 13px; font-weight: 700; color: #888; text-transform: uppercase; letter-spacing: 1px;">Market Sentiment</span>
        <span style="background: {sentiment_color}; color: white; padding: 4px 14px; border-radius: 20px; font-weight: 800; font-size: 14px;">{sentiment_label}</span>
      </div>
      <div style="background: #f0f0f0; border-radius: 10px; height: 14px; overflow: hidden; margin-bottom: 10px;">
        <div style="background: linear-gradient(90deg, #d32f2f, #f57c00, #2e7d32); width: {bar_width}%; height: 100%; border-radius: 10px;"></div>
      </div>
      <div style="display: flex; justify-content: space-between; font-size: 11px; color: #aaa;">
        <span>Bearish</span><span>Neutral</span><span>Bullish</span>
      </div>
      <p style="margin: 16px 0 0; color: #333; font-size: 15px; line-height: 1.6;">{market_summary}</p>
    </div>

    <!-- KEY INSIGHT -->
    <div style="background: linear-gradient(135deg, #0f3460, #1a1a2e); border-radius: 16px; padding: 20px; margin-bottom: 16px;">
      <div style="font-size: 12px; font-weight: 700; color: #a0b4d6; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px;">Key Thing To Watch Today</div>
      <div style="color: #ffffff; font-size: 15px; line-height: 1.6; font-weight: 500;">{key_insight}</div>
    </div>

    <!-- STOCK TABLE -->
    <div style="background: #ffffff; border-radius: 16px; padding: 24px; margin-bottom: 16px; box-shadow: 0 2px 8px rgba(0,0,0,0.06);">
      <div style="font-size: 13px; font-weight: 700; color: #888; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 16px;">Your Watchlist</div>
      <table style="width: 100%; border-collapse: collapse;">
        <tr style="background: #f8f9fa; border-radius: 8px;">
          <th style="padding: 8px 12px; text-align: left; font-size: 12px; color: #999; font-weight: 600;">TICKER</th>
          <th style="padding: 8px 12px; text-align: left; font-size: 12px; color: #999; font-weight: 600;">PRICE</th>
          <th style="padding: 8px 12px; text-align: left; font-size: 12px; color: #999; font-weight: 600;">CHANGE</th>
        </tr>
        {stock_rows}
      </table>
      <p style="margin: 16px 0 0; color: #555; font-size: 14px; line-height: 1.6;">{notable_movers}</p>
    </div>

    <!-- NEWS -->
    <div style="background: #ffffff; border-radius: 16px; padding: 24px; margin-bottom: 16px; box-shadow: 0 2px 8px rgba(0,0,0,0.06);">
      <div style="font-size: 13px; font-weight: 700; color: #888; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 16px;">Top Business News</div>
      <table style="width: 100%; border-collapse: collapse;">
        {news_items}
      </table>
    </div>

    <!-- MACRO -->
    <div style="background: #ffffff; border-radius: 16px; padding: 24px; margin-bottom: 16px; box-shadow: 0 2px 8px rgba(0,0,0,0.06);">
      <div style="font-size: 13px; font-weight: 700; color: #888; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 16px;">Macro Indicators</div>
      <table style="width: 100%; border-collapse: collapse;">
        {macro_rows}
      </table>
      <p style="margin: 16px 0 0; color: #555; font-size: 14px; line-height: 1.6;">{macro_context}</p>
    </div>

    <!-- FOOTER -->
    <div style="text-align: center; color: #aaa; font-size: 12px; padding: 10px;">
      Generated by your Daily Market Agent
    </div>

  </div>
</body>
</html>""".format(
        today=today,
        sentiment_color=sentiment_color,
        sentiment_label=sentiment_label,
        bar_width=bar_width,
        market_summary=market_summary,
        key_insight=key_insight,
        stock_rows=stock_rows,
        notable_movers=notable_movers,
        news_items=news_items,
        macro_rows=macro_rows,
        macro_context=macro_context
    )

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
