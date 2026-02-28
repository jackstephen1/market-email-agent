import yfinance as yf
import requests
import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import anthropic

WATCHLIST = [“AAPL”, “MSFT”, “GOOGL”, “NVDA”, “SPY”, “QQQ”, “BTC-USD”]

NEWS_API_KEY = os.environ[“NEWS_API_KEY”]
FRED_API_KEY = os.environ[“FRED_API_KEY”]
ANTHROPIC_KEY = os.environ[“ANTHROPIC_API_KEY”]
GMAIL_ADDRESS = os.environ[“GMAIL_ADDRESS”]
GMAIL_APP_PASS = os.environ[“GMAIL_APP_PASSWORD”]
RECIPIENT_EMAIL = os.environ[“RECIPIENT_EMAIL”]

def get_stock_data(tickers):
print(“Fetching stock data…”)
results = []
for ticker in tickers:
try:
stock = yf.Ticker(ticker)
hist = stock.history(period=“2d”)
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
print(“Could not fetch “ + ticker + “: “ + str(e))
return results

def get_financial_news():
print(“Fetching financial news…”)
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
headlines = []
for a in articles:
if a.get(“title”):
headlines.append(”- “ + a[“title”] + “ (” + a[“source”][“name”] + “)”)
return headlines[:10]
except Exception as e:
print(“Could not fetch news: “ + str(e))
return [“Could not fetch news today.”]

def get_macro_data():
print(“Fetching macro indicators…”)
indicators = {
“Federal Funds Rate”: “FEDFUNDS”,
“CPI Inflation”: “CPIAUCSL”,
“Unemployment Rate”: “UNRATE”,
“10-Year Treasury Yield”: “DGS10”,
“US GDP Growth Rate”: “A191RL1Q225SBEA”
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
“limit”: 1
}
response = requests.get(base_url, params=params)
data = response.json()
value = data[“observations”][0][“value”]
results[name] = value
except Exception as e:
print(“Could not fetch “ + name + “: “ + str(e))
results[name] = “N/A”
return results

def generate_analysis(stock_data, news_headlines, macro_data):
print(“Generating AI analysis…”)
client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

```
stocks_text = ""
for s in stock_data:
    sign = "+" if s["change_pct"] > 0 else ""
    stocks_text += "  " + s["ticker"] + ": $" + str(s["price"]) + " (" + sign + str(s["change_pct"]) + "%)\n"

news_text = "\n".join(news_headlines)
macro_text = ""
for k, v in macro_data.items():
    macro_text += "  " + k + ": " + v + "\n"

prompt = "You are a financial analyst writing a daily morning briefing email. Be concise and use plain English. Format your response as HTML using h2, p, and ul tags.\n\nWATCHLIST:\n" + stocks_text + "\nNEWS:\n" + news_text + "\nMACRO DATA:\n" + macro_text + "\nWrite a briefing covering: overall market mood, notable movers, key news, macro context, and one thing to watch today. Keep it under 400 words."

message = client.messages.create(
    model="claude-opus-4-6",
    max_tokens=1024,
    messages=[{"role": "user", "content": prompt}]
)
return message.content[0].text
```

def send_email(html_content):
print(“Sending email…”)
today = datetime.now().strftime(”%B %d, %Y”)
subject = “Your Daily Market Briefing - “ + today

```
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
```

def main():
print(“Starting Daily Market Agent…”)
stock_data = get_stock_data(WATCHLIST)
news_headlines = get_financial_news()
macro_data = get_macro_data()
analysis_html = generate_analysis(stock_data, news_headlines, macro_data)
send_email(analysis_html)
print(“Done! Check your inbox.”)

main()
