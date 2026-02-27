“””
Daily Market Email Agent
Fetches stock data, news, and economic indicators, then uses Claude to
generate a smart analysis and sends it to your email every morning.
“””

import yfinance as yf
import requests
import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import anthropic

# ============================================================

# YOUR WATCHLIST — Edit this list with your own stocks/ETFs

# ============================================================

WATCHLIST = [“AAPL”, “MSFT”, “GOOGL”, “NVDA”, “SPY”, “QQQ”, “BTC-USD”]

# ============================================================

# API KEYS — These are loaded from environment variables

# (You’ll set these up in GitHub Secrets — instructions below)

# ============================================================

NEWS_API_KEY    = os.environ[“NEWS_API_KEY”]
FRED_API_KEY    = os.environ[“FRED_API_KEY”]
ANTHROPIC_KEY   = os.environ[“ANTHROPIC_API_KEY”]
GMAIL_ADDRESS   = os.environ[“GMAIL_ADDRESS”]
GMAIL_APP_PASS  = os.environ[“GMAIL_APP_PASSWORD”]
RECIPIENT_EMAIL = os.environ[“RECIPIENT_EMAIL”]  # Can be same as GMAIL_ADDRESS

# ============================================================

# STEP 1: Fetch stock data for your watchlist

# ============================================================

def get_stock_data(tickers):
print(“📈 Fetching stock data…”)
results = []
for ticker in tickers:
try:
stock = yf.Ticker(ticker)
hist = stock.history(period=“2d”)  # Get last 2 days to calculate change
if len(hist) >= 2:
prev_close = hist[“Close”].iloc[-2]
curr_close = hist[“Close”].iloc[-1]
change_pct = ((curr_close - prev_close) / prev_close) * 100
results.append({
“ticker”: ticker,
“price”: round(curr_close, 2),
“change_pct”: round(change_pct, 2)
})
except Exception as e:
print(f”  Warning: Could not fetch {ticker}: {e}”)
return results

# ============================================================

# STEP 2: Fetch top financial news headlines

# ============================================================

def get_financial_news():
print(“📰 Fetching financial news…”)
url = “https://newsapi.org/v2/top-headlines”
params = {
“category”: “business”,
“language”: “en”,
“pageSize”: 10,
“apiKey”: NEWS_API_KEY
}
try:
response = requests.get(url, params=params)
articles = response.json().get(“articles”, [])
headlines = [f”- {a[‘title’]} ({a[‘source’][‘name’]})” for a in articles if a.get(“title”)]
return headlines[:10]
except Exception as e:
print(f”  Warning: Could not fetch news: {e}”)
return [“Could not fetch news today.”]

# ============================================================

# STEP 3: Fetch macro/economic indicators from FRED

# ============================================================

def get_macro_data():
print(“🏦 Fetching macro indicators…”)
# These are FRED series IDs for key economic indicators
indicators = {
“Federal Funds Rate”: “FEDFUNDS”,
“CPI Inflation (YoY)”: “CPIAUCSL”,
“Unemployment Rate”: “UNRATE”,
“10-Year Treasury Yield”: “DGS10”,
“US GDP Growth Rate”: “A191RL1Q225SBEA”,
}
results = {}
base_url = “https://api.stlouisfed.org/fred/series/observations”
for name, series_id in indicators.items():
try:
params = {
“series_id”: series_id,
“api_key”: FRED_API_KEY,
“file_type”: “json”,
“sort_order”: “desc”,
“limit”: 1  # Just the most recent value
}
response = requests.get(base_url, params=params)
data = response.json()
value = data[“observations”][0][“value”]
results[name] = value
except Exception as e:
print(f”  Warning: Could not fetch {name}: {e}”)
results[name] = “N/A”
return results

# ============================================================

# STEP 4: Use Claude to generate a smart analysis

# ============================================================

def generate_analysis(stock_data, news_headlines, macro_data):
print(“🤖 Generating AI analysis with Claude…”)
client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

```
# Format the data into a prompt for Claude
stocks_text = "\n".join([
    f"  {s['ticker']}: ${s['price']} ({'+' if s['change_pct'] > 0 else ''}{s['change_pct']}%)"
    for s in stock_data
])
news_text = "\n".join(news_headlines)
macro_text = "\n".join([f"  {k}: {v}" for k, v in macro_data.items()])

prompt = f"""You are a financial analyst writing a daily morning briefing email. 
```

Be concise, insightful, and use plain English (not too technical).
Format your response as a clean, readable email body in HTML.

Here is today’s data:

WATCHLIST PERFORMANCE:
{stocks_text}

TOP FINANCIAL NEWS:
{news_text}

MACRO ECONOMIC INDICATORS (latest available):
{macro_text}

Please write a daily briefing that includes:

1. A short overall market mood/summary (2-3 sentences)
1. Notable movers in the watchlist and why they might be moving
1. Key news stories to be aware of
1. Macro context — what the economic indicators suggest
1. One key thing to watch today

Keep it under 400 words. Write in HTML with simple formatting (use <h2>, <p>, <ul> tags).
Start directly with the content, no subject line needed.”””

```
message = client.messages.create(
    model="claude-opus-4-6",
    max_tokens=1024,
    messages=[{"role": "user", "content": prompt}]
)
return message.content[0].text
```

# ============================================================

# STEP 5: Send the email via Gmail

# ============================================================

def send_email(html_content):
print(“📧 Sending email…”)
today = datetime.now().strftime(”%B %d, %Y”)
subject = f”📊 Your Daily Market Briefing — {today}”

```
# Build the email
msg = MIMEMultipart("alternative")
msg["Subject"] = subject
msg["From"] = GMAIL_ADDRESS
msg["To"] = RECIPIENT_EMAIL

# Plain text fallback + HTML version
plain_text = "Please view this email in an HTML-capable email client."
msg.attach(MIMEText(plain_text, "plain"))
msg.attach(MIMEText(html_content, "html"))

# Send via Gmail SMTP
with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
    server.login(GMAIL_ADDRESS, GMAIL_APP_PASS)
    server.sendmail(GMAIL_ADDRESS, RECIPIENT_EMAIL, msg.as_string())

print("✅ Email sent successfully!")
```

# ============================================================

# MAIN — Run everything in order

# ============================================================

def main():
print(f”\n🚀 Starting Daily Market Agent — {datetime.now().strftime(’%Y-%m-%d %H:%M’)}\n”)

```
# Gather all data
stock_data     = get_stock_data(WATCHLIST)
news_headlines = get_financial_news()
macro_data     = get_macro_data()

# Generate AI analysis
analysis_html  = generate_analysis(stock_data, news_headlines, macro_data)

# Send the email
send_email(analysis_html)

print("\n✅ Done! Check your inbox.\n")
```

if **name** == “**main**”:
main()
