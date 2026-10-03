import requests, smtplib, os, json, time, random
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
import anthropic

WATCHLIST = ["AAPL","MSFT","GOOGL","NVDA","SPY","QQQ","BTC-USD","ETH-USD","SLV","SQQQ","UVIX"]

GROWTH_UNIVERSE = [
    "SOFI","AFRM","UPST","NU","HOOD","SOUN","BBAI","IONQ","RKLB","JOBY",
    "RXRX","BEAM","CRSP","NVAX","CHRD","SM","FSLR","RUN","PLUG","KTOS",
    "AVAV","CELH","CAVA","BROS","DKNG","CHWY","CVNA","MU","MRVL","AEIS",
]

NEWS_API_KEY     = os.environ["NEWS_API_KEY"]
FRED_API_KEY     = os.environ["FRED_API_KEY"]
ANTHROPIC_KEY    = os.environ["ANTHROPIC_API_KEY"]
GMAIL_ADDRESS    = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASS   = os.environ["GMAIL_APP_PASSWORD"]
RECIPIENT_EMAIL  = os.environ["RECIPIENT_EMAIL"]
AV_KEY           = os.environ["ALPHA_VANTAGE_KEY"]
FMP_KEY          = os.environ["FMP_API_KEY"]

AV_URL = "https://www.alphavantage.co/query"

def av(params, label=""):
    time.sleep(13)
    try:
        return requests.get(AV_URL, params={**params, "apikey": AV_KEY}, timeout=12).json()
    except Exception as e:
        print(label + " failed: " + str(e))
        return {}

def get_sp500_top_movers():
    print("Fetching top movers...")
    movers = []
    try:
        for kind in ["gainers","losers"]:
            data = requests.get("https://financialmodelingprep.com/api/v3/stock_market/"+kind, params={"apikey":FMP_KEY}, timeout=10).json()
            if not isinstance(data, list): continue
            for s in data[:10]:
                if not isinstance(s, dict): continue
                try:
                    p = float(s.get("price") or 0)
                    c = float(s.get("changesPercentage") or 0)
                    sym = s.get("symbol","")
                    if sym and p > 0:
                        movers.append({"ticker":sym,"price":round(p,2),"change_pct":round(c,2),"mover_type":"gainer" if kind=="gainers" else "loser"})
                except: pass
        print("Got " + str(len(movers)) + " movers")
    except Exception as e:
        print("Movers failed: " + str(e))
    return movers


def get_sentiment_indicators():
    print("Fetching sentiment...")
    result = {}
    try:
        fg = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10).json().get("data",[{}])[0]
        result["fear_greed"] = {"value": int(fg.get("value",50)), "label": fg.get("value_classification","Neutral")}
        print("F&G: " + str(result["fear_greed"]["value"]))
    except Exception as e:
        print("F&G failed: " + str(e))
        result["fear_greed"] = {"value":50,"label":"Neutral"}
    try:
        vv, vc = None
        lbl = "Low Volatility" if vv<15 else "Normal" if vv<20 else "Elevated Fear" if vv<30 else "Extreme Fear"
        result["vix"] = {"value":vv,"change":vc,"label":lbl}
        print("VIX: " + str(vv))
    except Exception as e:
        print("VIX failed: " + str(e))
        result["vix"] = {"value":"N/A","change":0,"label":"Unavailable"}
    try:
        pv, _ = None
        lbl = "Very Bullish" if pv<0.6 else "Bullish" if pv<0.8 else "Neutral" if pv<1.0 else "Bearish" if pv<1.2 else "Very Bearish"
        result["put_call"] = {"value":pv,"label":lbl}
        print("P/C: " + str(pv))
    except Exception as e:
        print("P/C failed: " + str(e))
        result["put_call"] = {"value":"N/A","label":"Unavailable"}
    return result

# Major companies to always check for earnings — the ones people actually care about
EARNINGS_WATCHLIST = [
    # Mega cap tech
    "AAPL","MSFT","GOOGL","GOOG","AMZN","META","NVDA","TSLA","NFLX","AMD",
    # Semiconductors
    "MU","INTC","QCOM","AVGO","TSM","AMAT","LRCX","KLAC","MRVL","ARM",
    # Financials
    "JPM","BAC","GS","MS","WFC","C","BLK","V","MA","AXP",
    # Consumer / Retail
    "WMT","HD","NKE","COST","TGT","MCD","SBUX","LOW","TJX","AMZN",
    # Healthcare / Pharma
    "UNH","JNJ","LLY","ABBV","PFE","MRK","CVS","ABT","BMY","GILD",
    # Energy
    "XOM","CVX","COP","SLB","EOG","PSX","VLO","OXY",
    # Industrial / Defense
    "BA","CAT","GE","HON","LMT","RTX","NOC","GD","AVAV",
    # Growth / Tech
    "CRM","ORCL","NOW","SNOW","PLTR","COIN","SOFI","UBER","LYFT","ABNB",
    "SHOP","SQ","PYPL","TWLO","ZM","DDOG","NET","CRWD","PANW","OKTA",
    # Other major names
    "DIS","CMCSA","VZ","T","TMUS","PG","KO","PEP","PM","MO",
]

def get_earnings_data():
    print("Fetching earnings...")
    import csv, io, yfinance as yf
    recent, upcoming = [], []
    today  = datetime.now().date()
    past   = today - timedelta(days=7)
    future = today + timedelta(days=7)

    # ── Step 1: Check major companies via yfinance (most reliable for big names)
    print("Checking major earnings watchlist via yfinance...")
    for ticker in EARNINGS_WATCHLIST:
        try:
            stk = yf.Ticker(ticker)
            # Upcoming
            try:
                cal = stk.calendar
                if isinstance(cal, dict):
                    dates = cal.get("Earnings Date", [])
                    if not hasattr(dates, "__iter__") or isinstance(dates, str):
                        dates = [dates]
                    for d in list(dates):
                        try:
                            dd = d.date() if hasattr(d, "date") else d
                            if isinstance(dd, type(today)) and today <= dd <= future:
                                upcoming.append({
                                    "ticker": ticker,
                                    "date": str(dd),
                                    "eps_estimate": "N/A",
                                    "time": "TBD"
                                })
                        except: pass
            except: pass
            # Recent
            try:
                hist = stk.earnings_history
                if hist is not None and hasattr(hist, "iterrows"):
                    for idx, row in hist.iterrows():
                        try:
                            rd = idx.date() if hasattr(idx, "date") else None
                            if rd and past <= rd <= today:
                                ea = row.get("epsActual"); ee = row.get("epsEstimate")
                                if ea is not None and ee is not None:
                                    ea, ee = float(ea), float(ee)
                                    surp = round(((ea-ee)/abs(ee))*100,1) if ee!=0 else 0
                                    recent.append({
                                        "ticker": ticker,
                                        "date": str(rd),
                                        "eps_actual": round(ea,2),
                                        "eps_estimate": round(ee,2),
                                        "surprise_pct": surp,
                                        "beat": ea >= ee
                                    })
                        except: pass
            except: pass
        except: pass

    # ── Step 2: Supplement with AV calendar for anything we missed ─────────────
    try:
        resp = requests.get(
            "https://www.alphavantage.co/query",
            params={"function":"EARNINGS_CALENDAR","horizon":"1month","apikey":AV_KEY},
            timeout=15
        )
        text = resp.text.strip()
        if text and (resp.headers.get("Content-Type","").startswith("text/csv") or text.startswith("symbol")):
            reader = csv.DictReader(io.StringIO(text))
            existing_upcoming = set(u["ticker"] for u in upcoming)
            for row in reader:
                try:
                    sym = row.get("symbol","").strip()
                    rep_date = row.get("reportDate","").strip()
                    est = row.get("estimate","").strip()
                    if not sym or not rep_date: continue
                    # Only add if it's a recognizable company (in our watchlist)
                    # or if it appears in the top of AV results and isn't already tracked
                    rd = datetime.strptime(rep_date, "%Y-%m-%d").date()
                    if today <= rd <= future and sym in EARNINGS_WATCHLIST and sym not in existing_upcoming:
                        upcoming.append({
                            "ticker": sym,
                            "date": str(rd),
                            "eps_estimate": round(float(est),2) if est else "N/A",
                            "time": "TBD"
                        })
                        existing_upcoming.add(sym)
                except: pass
    except Exception as e:
        print("AV calendar supplement failed: " + str(e))

    # Deduplicate and sort
    seen_u = set(); uniq_up = []
    for u in sorted(upcoming, key=lambda x: x["date"]):
        if u["ticker"] not in seen_u:
            seen_u.add(u["ticker"]); uniq_up.append(u)

    recent = sorted(recent, key=lambda x: abs(x.get("surprise_pct",0)), reverse=True)[:5]
    upcoming = uniq_up[:10]
    print("Earnings: " + str(len(recent)) + " recent, " + str(len(upcoming)) + " upcoming")
    return {"recent": recent, "upcoming": upcoming}

def get_broad_news():
    print("Fetching news...")
    headlines=[]
    try:
        arts=requests.get("https://newsapi.org/v2/top-headlines",params={"category":"business","language":"en","country":"us","pageSize":10,"apiKey":NEWS_API_KEY},timeout=10).json().get("articles",[])
        for a in arts:
            if a.get("title") and "[Removed]" not in a.get("title",""):
                headlines.append({"title":a["title"],"source":a["source"]["name"],"url":a.get("url","#")})
    except: pass
    seen=set(); uniq=[]
    for h in headlines:
        if h["title"] not in seen:
            seen.add(h["title"]); uniq.append(h)
    print("Got " + str(len(uniq)) + " articles")
    return uniq[:15]

def get_quote_stock(ticker):
    data = av({"function":"GLOBAL_QUOTE","symbol":ticker}, ticker)
    q = data.get("Global Quote",{})
    if q and q.get("05. price"):
        p=float(q["05. price"]); c=float(q["10. change percent"].replace("%",""))
        if p>0:
            print("Got " + ticker + ": $" + str(round(p,2)))
            return {"ticker":ticker,"price":round(p,2),"change_pct":round(c,2),"is_crypto":False}
    return None

def get_quote_crypto(ticker):
    symbol=ticker.replace("-USD","")
    data=av({"function":"CURRENCY_EXCHANGE_RATE","from_currency":symbol,"to_currency":"USD"},ticker)
    rate=data.get("Realtime Currency Exchange Rate",{})
    if not rate: return None
    curr=float(rate.get("5. Exchange Rate",0))
    data2=av({"function":"DIGITAL_CURRENCY_DAILY","symbol":symbol,"market":"USD"},ticker)
    ts=data2.get("Time Series (Digital Currency Daily)",{})
    chg=0.0
    if ts:
        dates=sorted(ts.keys(),reverse=True)
        if len(dates)>=2:
            pe=ts[dates[1]]
            prev=next((float(pe[k]) for k in ["4a. close (USD)","4. close","4b. close (USD)","4. close (USD)"] if k in pe),None)
            if prev and prev>0: chg=((curr-prev)/prev)*100
    print("Got " + ticker + ": $" + str(round(curr,2)))
    return {"ticker":ticker,"price":round(curr,2),"change_pct":round(chg,2),"is_crypto":True}

def get_stock_data(tickers):
    print("Fetching watchlist...")
    results=[]
    for t in tickers:
        try:
            r=get_quote_crypto(t) if "-USD" in t.upper() else get_quote_stock(t)
            if r: results.append(r)
        except Exception as e:
            print(t + " failed: " + str(e))
    print("Got " + str(len(results)) + "/" + str(len(tickers)))
    return results

def get_technicals(ticker):
    result={"ticker":ticker}
    for fn,period,key,rkey in [("RSI",14,"Technical Analysis: RSI","RSI"),("SMA",50,"Technical Analysis: SMA","SMA"),("SMA",200,"Technical Analysis: SMA","SMA")]:
        data=av({"function":fn,"symbol":ticker,"interval":"daily","time_period":period,"series_type":"close"},ticker)
        series=data.get(key,{})
        if series:
            latest=sorted(series.keys(),reverse=True)[0]
            val=series[latest].get(rkey)
            if val:
                if fn=="RSI": result["rsi"]=round(float(val),1)
                elif period==50: result["sma50"]=round(float(val),2)
                else: result["sma200"]=round(float(val),2)
    # Volume — fetch daily time series to get today vs 20-day avg
    try:
        data=av({"function":"TIME_SERIES_DAILY","symbol":ticker,"outputsize":"compact"},ticker)
        ts=data.get("Time Series (Daily)",{})
        if ts:
            dates=sorted(ts.keys(),reverse=True)
            today_vol=float(ts[dates[0]].get("5. volume",0))
            avg_vols=[float(ts[d].get("5. volume",0)) for d in dates[1:21] if ts[d].get("5. volume")]
            if avg_vols and today_vol>0:
                avg_vol=sum(avg_vols)/len(avg_vols)
                vol_ratio=round(today_vol/avg_vol,1) if avg_vol>0 else None
                result["volume_today"]=int(today_vol)
                result["volume_avg20"]=int(avg_vol)
                result["volume_ratio"]=vol_ratio
                print("  Volume: " + str(vol_ratio) + "x avg")
    except Exception as e:
        print("Volume fetch failed for " + ticker + ": " + str(e))
    return result if len(result)>1 else None


def get_sector_data():
    """Fetch daily % change for all 11 sector ETFs."""
    print("Fetching sector rotation data...")
    sectors = {
        "XLK":  "Technology",
        "XLF":  "Financials",
        "XLE":  "Energy",
        "XLV":  "Healthcare",
        "XLY":  "Consumer Disc.",
        "XLI":  "Industrials",
    }
    results = []
    for etf, name in sectors.items():
        try:
            data = av({"function":"GLOBAL_QUOTE","symbol":etf}, etf)
            q = data.get("Global Quote",{})
            if q and q.get("05. price"):
                chg = round(float(q["10. change percent"].replace("%","")), 2)
                results.append({"etf":etf,"name":name,"change_pct":chg})
        except Exception as e:
            print("Sector " + etf + " failed: " + str(e))
    # Sort strongest to weakest
    results = sorted(results, key=lambda x: x["change_pct"], reverse=True)
    print("Got " + str(len(results)) + " sectors")
    return results


def is_quality_stock(ticker, price, change_pct):
    """Filter out garbage — penny stocks, extreme movers likely to be meme/news spikes."""
    if price < 5:
        return False, "price under $5"
    if price > 5000:
        return False, "price over $5000 (likely Berkshire/NVR type)"
    if abs(change_pct) > 50:
        return False, "move over 50% likely news spike or halt"
    # Skip obvious penny/OTC patterns
    if len(ticker) > 5:
        return False, "ticker too long (likely OTC)"
    return True, "ok"



def get_finviz_candidates():
    """
    Scrape Finviz screener directly via URL — more reliable than the library.
    Returns a deduplicated list of tickers from 3 screens.
    """
    print("Running Finviz screeners...")
    from bs4 import BeautifulSoup
    candidates = {}

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Referer": "https://finviz.com/",
    }

    screens = [
        # Screen 1: Oversold + above 200 SMA (bounce setups)
        ("Oversold+Uptrend", "https://finviz.com/screener.ashx?v=111&f=rsi_os30,sma200_pa,sh_avgvol_o500,sh_price_o5&o=rsi"),
        # Screen 2: Near 52-week high with strong volume (breakouts)
        ("Breakout", "https://finviz.com/screener.ashx?v=111&f=sh_avgvol_o300,sh_price_o5,ta_highlow52w_nh&o=-relativevolume"),
        # Screen 3: Up on the week, RSI not overbought, small/mid cap
        ("Weekly Momentum", "https://finviz.com/screener.ashx?v=111&f=cap_smallover,sh_avgvol_o200,sh_price_o5,ta_rsi_nos70,geo_usa&o=-perf1w"),
    ]

    for screen_name, url in screens:
        try:
            time.sleep(2)  # be polite
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code != 200:
                print("  Screen " + screen_name + " HTTP " + str(resp.status_code))
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            # Finviz ticker cells have class "screener-link-primary"
            tickers = [a.text.strip() for a in soup.find_all("a", class_="screener-link-primary")]
            tickers = [t for t in tickers if t and len(t) <= 5][:10]
            for ticker in tickers:
                if ticker not in candidates:
                    candidates[ticker] = screen_name
            print("  Screen " + screen_name + ": " + str(len(tickers)) + " tickers — " + str(tickers[:5]))
        except Exception as e:
            print("  Screen " + screen_name + " failed: " + str(e))

    result = [{"ticker": t, "screen": s} for t, s in candidates.items()]
    print("Finviz total candidates: " + str(len(result)) + " — " + str([r["ticker"] for r in result]))
    return result

def get_scan_universe(watchlist, growth_universe, top_movers, spy_change, finviz_candidates=[]):
    """
    Build a dynamic scan universe from:
    1. Top S&P movers (filtered for quality) — always fresh, market-driven
    2. A few growth universe picks — your conviction names
    3. Watchlist stocks — always included

    Also calculates relative strength vs SPY for context.
    """
    print("Building scan universe from top movers + growth picks...")

    results = []
    seen = set()

    # ── Layer 0: Finviz screener results (pre-screened, highest quality) ────────
    for item in finviz_candidates:
        ticker = item.get("ticker","")
        if not ticker or ticker in seen: continue
        seen.add(ticker)
        results.append({
            "ticker":     ticker,
            "price":      0,
            "change_pct": 0,
            "vol_ratio":  None,
            "rel_str":    0,
            "unusual":    False,
            "source":     "Finviz: " + item.get("screen","Screen")
        })

    # ── Layer 1: Top movers (filtered for quality) ────────────────────────────
    mover_tickers = []
    for m in top_movers:
        if not isinstance(m, dict): continue
        ticker = m.get("ticker","")
        price  = float(m.get("price", 0) or 0)
        chg    = float(m.get("change_pct", 0) or 0)
        ok, reason = is_quality_stock(ticker, price, chg)
        if ok and ticker not in seen:
            mover_tickers.append(ticker)
            seen.add(ticker)
            rel_str = round(chg - spy_change, 2)
            results.append({
                "ticker":     ticker,
                "price":      price,
                "change_pct": chg,
                "vol_ratio":  None,   # will fetch below if quota allows
                "rel_str":    rel_str,
                "unusual":    False,
                "source":     "Top Mover"
            })
    print("  Quality movers: " + str(len(mover_tickers)) + " of " + str(len(top_movers)) + " passed filter")

    # ── Layer 2: 3 random growth universe picks ───────────────────────────────
    growth_picks = random.sample(
        [t for t in growth_universe if t not in seen],
        min(3, len([t for t in growth_universe if t not in seen]))
    )
    for ticker in growth_picks:
        seen.add(ticker)
        results.append({
            "ticker":     ticker,
            "price":      0,
            "change_pct": 0,
            "vol_ratio":  None,
            "rel_str":    0,
            "unusual":    False,
            "source":     "Growth Universe"
        })

    # ── Layer 3: Watchlist stocks (non-crypto) ────────────────────────────────
    for ticker in watchlist:
        if "-USD" not in ticker.upper() and ticker not in seen:
            seen.add(ticker)
            results.append({
                "ticker":     ticker,
                "price":      0,
                "change_pct": 0,
                "vol_ratio":  None,
                "rel_str":    0,
                "unusual":    False,
                "source":     "Watchlist"
            })

    print("Total scan universe: " + str(len(results)) + " tickers")
    return results

def get_swing_data(watchlist, movers, scan_universe=[]):
    print("Fetching technicals...")

    # Priority order: top movers first, then growth picks, then watchlist
    ordered = (
        [x["ticker"] for x in scan_universe if x.get("source") == "Top Mover"] +
        [x["ticker"] for x in scan_universe if x.get("source") == "Growth Universe"] +
        [x["ticker"] for x in scan_universe if x.get("source") == "Watchlist"]
    )
    # Deduplicate preserving order
    seen = set(); combined = []
    for t in ordered:
        if t not in seen: combined.append(t); seen.add(t)

    results = []
    for ticker in combined[:6]:   # 6 deep scans max to stay within API quota
        try:
            print("Technicals: " + ticker)
            q = get_quote_stock(ticker)
            if not q or q["price"] == 0:
                # Try to use price from scan universe if AV fails
                su = next((x for x in scan_universe if x["ticker"]==ticker), {})
                if su.get("price", 0) > 0:
                    q = {"ticker": ticker, "price": su["price"], "change_pct": su["change_pct"], "is_crypto": False}
                else:
                    continue
            tech = get_technicals(ticker)
            if tech:
                su_data = next((x for x in scan_universe if x["ticker"]==ticker), {})
                combined_data = {**q, **tech}
                combined_data["rel_str"]     = su_data.get("rel_str", 0)
                combined_data["scan_source"] = su_data.get("source", "")
                if su_data.get("vol_ratio"):
                    combined_data["volume_ratio"] = su_data["vol_ratio"]
                results.append(combined_data)
                src = su_data.get("source","")
                print("  RSI:" + str(tech.get("rsi","N/A")) + " SMA50:$" + str(tech.get("sma50","N/A")) + " [" + src + "]")
                combined_data["scan_source"] = src
        except Exception as e:
            print(ticker + " tech failed: " + str(e))
    return results

def get_fred_value(series_id):
    """Fetch latest non-null value from FRED."""
    try:
        obs = requests.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params={"series_id": series_id, "api_key": FRED_API_KEY,
                    "file_type": "json", "sort_order": "desc", "limit": 10},
            timeout=10
        ).json().get("observations", [])
        return next((o["value"] for o in obs if o.get("value") and o["value"] not in [".", "NA", ""]), None)
    except:
        return None


def get_aaii_sentiment():
    """
    Scrape AAII weekly sentiment survey — % Bullish / Bearish / Neutral.
    Published every Thursday at aaii.com/sentimentsurvey/sent_results
    """
    try:
        from bs4 import BeautifulSoup
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = requests.get("https://www.aaii.com/sentimentsurvey/sent_results", headers=headers, timeout=12)
        soup = BeautifulSoup(resp.text, "html.parser")
        # AAII table has percentages in the first data row
        tables = soup.find_all("table")
        for table in tables:
            rows = table.find_all("tr")
            for row in rows:
                cells = [td.get_text(strip=True) for td in row.find_all("td")]
                # Look for a row with % values
                if len(cells) >= 3:
                    try:
                        bull = float(cells[0].replace("%",""))
                        neut = float(cells[1].replace("%",""))
                        bear = float(cells[2].replace("%",""))
                        if 0 < bull < 100 and 0 < bear < 100:
                            spread = round(bull - bear, 1)
                            if bull >= 45:
                                rating, rc, rb = "Bullish", "#00863a", "#e6f9ec"
                            elif bear >= 45:
                                rating, rc, rb = "Bearish", "#cc3d00", "#fff0eb"
                            else:
                                rating, rc, rb = "Neutral", "#996300", "#fff8e6"
                            result = {
                                "bullish": round(bull, 1),
                                "bearish": round(bear, 1),
                                "neutral": round(neut, 1),
                                "spread":  spread,
                                "rating":  rating,
                                "color":   rc,
                                "bg":      rb
                            }
                            print("AAII: Bull " + str(bull) + "% Bear " + str(bear) + "% (" + rating + ")")
                            return result
                    except:
                        continue
    except Exception as e:
        print("AAII failed: " + str(e))
    return None


def get_macro_data():
    print("Fetching macro...")
    indicators = {
        "Federal Funds Rate": ("FEDFUNDS", "rate"),
        "Unemployment Rate":  ("UNRATE",   "unemp"),
        "10-Year Treasury":   ("DGS10",    "yield"),
        "2-Year Treasury":    ("DGS2",     "yield2"),
        "GDP Growth Rate":    ("A191RL1Q225SBEA", "gdp"),
    }
    results = {}
    for name, (sid, kind) in indicators.items():
        try:
            val = get_fred_value(sid)
            if val:
                v = float(val)
                if kind == "rate":
                    if v <= 2.5:   rat, rc, rb = "Good",          "#00863a", "#e6f9ec"
                    elif v <= 4.5: rat, rc, rb = "Neutral",        "#996300", "#fff8e6"
                    else:          rat, rc, rb = "Restrictive",    "#cc3d00", "#fff0eb"
                elif kind in ("yield", "yield2"):
                    if v <= 3.5:   rat, rc, rb = "Accommodative", "#00863a", "#e6f9ec"
                    elif v <= 4.5: rat, rc, rb = "Neutral",        "#996300", "#fff8e6"
                    else:          rat, rc, rb = "Tight",          "#cc3d00", "#fff0eb"
                elif kind == "unemp":
                    if v <= 4.0:   rat, rc, rb = "Strong",         "#00863a", "#e6f9ec"
                    elif v <= 5.5: rat, rc, rb = "Moderate",       "#996300", "#fff8e6"
                    else:          rat, rc, rb = "Weak",            "#cc3d00", "#fff0eb"
                else:
                    if v >= 2.5:   rat, rc, rb = "Strong",         "#00863a", "#e6f9ec"
                    elif v >= 1.0: rat, rc, rb = "Moderate",       "#996300", "#fff8e6"
                    else:          rat, rc, rb = "Weak",            "#cc3d00", "#fff0eb"
                results[name] = {"value": val, "rating": rat, "color": rc, "bg": rb}
                print("Got " + name + ": " + val + " (" + rat + ")")
            else:
                results[name] = {"value": "N/A", "rating": "N/A", "color": "#888", "bg": "#f5f5f5"}
        except Exception as e:
            print(name + " failed: " + str(e))
            results[name] = {"value": "N/A", "rating": "N/A", "color": "#888", "bg": "#f5f5f5"}

    # ── Yield Curve Spread (10yr - 2yr) ──────────────────────────────────────
    try:
        t10 = results.get("10-Year Treasury", {}).get("value")
        t2  = results.get("2-Year Treasury",  {}).get("value")
        if t10 and t2 and t10 != "N/A" and t2 != "N/A":
            spread = round(float(t10) - float(t2), 2)
            if spread >= 0.5:   srat, src, srb = "Normal",   "#00863a", "#e6f9ec"
            elif spread >= 0:   srat, src, srb = "Flat",     "#996300", "#fff8e6"
            else:               srat, src, srb = "Inverted", "#cc3d00", "#fff0eb"
            results["Yield Curve (10-2)"] = {
                "value":  str(spread) + "%",
                "rating": srat,
                "color":  src,
                "bg":     srb
            }
            print("Yield Curve: " + str(spread) + "% (" + srat + ")")
    except Exception as e:
        print("Yield curve calc failed: " + str(e))

    # ── AAII Sentiment Survey ─────────────────────────────────────────────────
    aaii = get_aaii_sentiment()
    results["__aaii__"] = aaii   # stored separately for custom HTML rendering

    return results

def generate_analysis(stocks, news, macro, swing, movers, sentiment, earnings, sectors=[], scan_universe=[]):
    print("Generating analysis...")
    client=anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    stocks_t="".join([s["ticker"]+": $"+str(s["price"])+" ("+("+" if s["change_pct"]>0 else "")+str(s["change_pct"])+"% today)\n" for s in stocks]) or "Unavailable.\n"
    news_t="\n".join(["- "+n["title"] for n in news]) or "No news.\n"
    macro_t = ""
    aaii = macro.get("__aaii__")
    for k, v in macro.items():
        if k == "__aaii__": continue
        macro_t += k + ": " + v["value"] + "\n"
    if aaii:
        macro_t += "AAII Sentiment: Bull " + str(aaii.get("bullish","N/A")) + "% Bear " + str(aaii.get("bearish","N/A")) + "% Spread=" + str(aaii.get("spread","N/A")) + "% (" + aaii.get("rating","N/A") + ")\n"
    mov_t=""
    if movers:
        mov_t+="GAINERS:\n"+"".join([m["ticker"]+": $"+str(m["price"])+" (+"+str(m["change_pct"])+"%)\n" for m in movers if m.get("mover_type")=="gainer"][:5])
        mov_t+="LOSERS:\n"+"".join([m["ticker"]+": $"+str(m["price"])+" ("+str(m["change_pct"])+"%)\n" for m in movers if m.get("mover_type")=="loser"][:5])
    swing_t=""
    for s in swing:
        if s.get("price",0)>0:
            line=s["ticker"]+": price=$"+str(s["price"])+" RSI="+str(s.get("rsi","N/A"))+" 50SMA=$"+str(s.get("sma50","N/A"))+" 200SMA=$"+str(s.get("sma200","N/A"))
            if s.get("volume_ratio"): line+=" volume="+str(s["volume_ratio"])+"x_avg_20day"
            if s.get("rel_str"): line+=" rel_strength_vs_SPY="+str(s["rel_str"])+"%"
            if s.get("scan_source"): line+=" ["+str(s["scan_source"])+"]"
            swing_t+=line+"\n"
    fg=sentiment.get("fear_greed",{}); vix=sentiment.get("vix",{}); pc=sentiment.get("put_call",{})
    sent_t="F&G: "+str(fg.get("value","N/A"))+" ("+fg.get("label","N/A")+")\nVIX: "+str(vix.get("value","N/A"))+" ("+vix.get("label","N/A")+")\nP/C: "+str(pc.get("value","N/A"))+" ("+pc.get("label","N/A")+")\n"
    earn_t=""
    if earnings.get("recent"):
        earn_t+="RECENT:\n"+"".join([e["ticker"]+" "+("BEAT" if e["beat"] else "MISS")+" "+("+" if e["surprise_pct"]>0 else "")+str(e["surprise_pct"])+"% ($"+str(e["eps_actual"])+" vs $"+str(e["eps_estimate"])+" est)\n" for e in earnings["recent"]])
    if earnings.get("upcoming"):
        earn_t+="UPCOMING:\n"+"".join([e["ticker"]+" reports "+e["date"]+"\n" for e in earnings["upcoming"]])
    rules = (
        "You are a financial analyst. Return ONLY valid JSON, no markdown.\n\n"
        "RULES:\n"
        "- Always include timeframe on percent moves (e.g. down 1.2% today)\n"
        "- Swing trades are 3-10 day holds only\n"
        "- Entry zones must be within 5% of current_price\n"
        "- RSI<35 oversold, RSI>70 overbought\n"
        "- NEVER recommend the same ticker twice — one bias per stock, pick the stronger conviction side\n"
        "- Only recommend 2-3 swing trades total, high conviction only — fewer but better setups\n"
        "- Base sentiment score on price action first; Fear & Greed is secondary\n"
        "- Macro opportunities: under-the-radar stocks not yet moved on news themes\n"
        "- price_target: specific realistic number. Bullish = above entry, Bearish = below entry\n"
        "- invalidation_price: specific number where setup is cancelled\n"
        "- entry_midpoint: the exact midpoint number of the entry_zone range\n"
        "- risk_reward: string like '2.4:1'. Bullish R/R = (target-entry)/(entry-invalidation). Bearish = (entry-target)/(invalidation-entry). Round to 1 decimal\n"
        "- volume_signal: if volume data shows ratio>=1.5 write 'High volume Xx avg'. Otherwise 'Normal volume'. If no data 'Volume N/A'\n"
        "- prioritize swing trade setups in sectors showing strength today\n"
        "- flag unusual volume tickers first - they have the highest conviction\n"
        "- mention relative strength vs SPY in thesis when relevant\n"
    )
    schema = (
        "Return this exact JSON:\n"
        "{\n"
        '  "sentiment_score": <1-10>,\n'
        '  "sentiment_label": "<Bearish/Neutral/Bullish>",\n'
        '  "market_summary": "<2-3 sentences with timeframes on % moves>",\n'
        '  "key_insight": "<one thing to watch today>",\n'
        '  "notable_movers": "<2-3 sentences on watchlist with timeframes>",\n'
        '  "macro_context": "<2-3 sentences on economic data>",\n'
        '  "sentiment_commentary": "<2 sentences on what Fear & Greed suggests about market positioning>",\n'
        '  "swing_trades": [\n'
        '    {\n'
        '      "ticker": "",\n'
        '      "current_price": 0,\n'
        '      "bias": "Bullish",\n'
        '      "timeframe": "",\n'
        '      "entry_zone": "",\n'
        '      "entry_midpoint": 0,\n'
        '      "price_target": 0,\n'
        '      "invalidation_price": 0,\n'
        '      "risk_reward": "",\n'
        '      "volume_signal": "",\n'
        '      "thesis": "",\n'
        '      "invalidation": "",\n'
        '      "source": ""\n'
        '    }\n'
        '  ],\n'
        '  "macro_opportunities": [\n'
        '    {\n'
        '      "theme": "",\n'
        '      "theme_summary": "",\n'
        '      "plays": [\n'
        '        {\n'
        '          "ticker": "",\n'
        '          "company_name": "",\n'
        '          "type": "Stock",\n'
        '          "why_underrated": "",\n'
        '          "catalyst": "",\n'
        '          "timeframe": ""\n'
        '        }\n'
        '      ]\n'
        '    }\n'
        '  ]\n'
        "}\n\n"
        "Swing trades: 2-3 high conviction ideas only. Each ticker appears ONCE maximum. No duplicate tickers with opposite biases.\n"
        "Macro opportunities: 2-3 themes from news/macro, 2-3 plays each, focus on under-the-radar names."
    )
    # Sector rotation text
    sector_t = ""
    if sectors:
        top3    = sectors[:3]
        bottom3 = sectors[-3:]
        sector_t += "LEADING SECTORS TODAY:\n"
        for s in top3:
            sector_t += s["etf"] + " (" + s["name"] + "): " + ("+" if s["change_pct"]>0 else "") + str(s["change_pct"]) + "%\n"
        sector_t += "LAGGING SECTORS TODAY:\n"
        for s in bottom3:
            sector_t += s["etf"] + " (" + s["name"] + "): " + str(s["change_pct"]) + "%\n"

    # Scan universe context for Claude
    uv_t = ""
    top_mover_picks = [x for x in scan_universe if x.get("source") == "Top Mover"]
    if top_mover_picks:
        uv_t = "TODAY\'S TOP MOVERS IN SCAN (quality filtered):\n"
        for x in top_mover_picks[:8]:
            rs = x.get("rel_str", 0)
            rs_str = ("outperforming" if rs>0 else "underperforming") + " SPY by " + str(abs(rs)) + "%"
            sign = "+" if x["change_pct"] > 0 else ""
            uv_t += x["ticker"] + ": " + sign + str(x["change_pct"]) + "% today | " + rs_str + " [" + x.get("source","") + "]\n"

    data_sections = (
        "WATCHLIST:\n" + stocks_t +
        "\nMOVERS:\n" + mov_t +
        "\nSECTOR ROTATION:\n" + (sector_t or "No sector data.\n") +
        "\nTOP MOVERS & SCAN UNIVERSE:\n" + (uv_t or "No mover data today.\n") +
        "\nSENTIMENT (secondary):\n" + sent_t +
        "\nNEWS:\n" + news_t +
        "\nMACRO:\n" + macro_t +
        "\nTECHNICALS (base entry zones on these prices):\n" + swing_t +
        "\nEARNINGS:\n" + (earn_t or "No earnings data.\n")
    )
    prompt = rules + data_sections + "\n" + schema
    msg=client.messages.create(model="claude-opus-4-6",max_tokens=3000,messages=[{"role":"user","content":prompt}])
    raw=msg.content[0].text.strip().replace("```json","").replace("```","").strip()
    result=json.loads(raw)

    # Deduplicate swing trades — one ticker, one direction only
    seen_tickers = set()
    clean_trades = []
    for trade in result.get("swing_trades", []):
        ticker = trade.get("ticker","")
        if ticker and ticker not in seen_tickers:
            seen_tickers.add(ticker)
            clean_trades.append(trade)
        elif ticker in seen_tickers:
            print("Removed duplicate swing trade: " + ticker)
    result["swing_trades"] = clean_trades[:3]  # max 3

    print("Sentiment: "+result.get("sentiment_label","?")+" | Swing: "+str(len(result.get("swing_trades",[])))+" | Themes: "+str(len(result.get("macro_opportunities",[]))))
    return result

def row(content):
    return "<div style='border-bottom:0.5px solid #f0f0f0;'>"+content+"</div>"

def pill(text, color, bg):
    return "<span style='background:"+bg+";color:"+color+";padding:2px 10px;border-radius:20px;font-size:12px;font-weight:500;'>"+text+"</span>"

def build_email(stocks, news, macro, analysis, movers, sentiment, earnings, portfolio_html="", sectors=[]):
    today = datetime.now().strftime("%A, %B %d, %Y")
    sl=analysis.get("sentiment_label","Neutral"); ss=analysis.get("sentiment_score",5)
    slc={"Bullish":("#00863a","#e6f9ec"),"Bearish":("#cc3d00","#fff0eb")}.get(sl,("#996300","#fff8e6"))

    fg=sentiment.get("fear_greed",{})
    fgv=fg.get("value",50); fgl=fg.get("label","Neutral")
    fgc="#00863a" if fgv>=55 else "#cc3d00" if fgv<=35 else "#996300"
    fgb="#e6f9ec" if fgv>=55 else "#fff0eb" if fgv<=35 else "#fff8e6"

    # watchlist
    wl=""
    for s in stocks:
        chg=s["change_pct"]; sign="+" if chg>0 else ""
        rc="#00863a" if chg>=0 else "#cc3d00"; rb="#e6f9ec" if chg>=0 else "#fff0eb"
        lbl=s["ticker"]+" (Crypto)" if s.get("is_crypto") else s["ticker"]
        wl+="<div style='display:flex;justify-content:space-between;align-items:center;padding:10px 0;border-bottom:0.5px solid #f0f0f0;'>"
        wl+="<div><div style='font-size:15px;font-weight:500;color:#111;'>"+lbl+"</div><div style='font-size:12px;color:#888;'>$"+str(s["price"])+"</div></div>"
        wl+=pill(sign+str(chg)+"%",rc,rb)+"</div>"
    if not wl: wl="<div style='padding:12px 0;color:#888;'>Data temporarily unavailable.</div>"

    # movers
    gr=""
    for m in [x for x in movers if x.get("mover_type")=="gainer"][:5]:
        gr+="<div style='display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:0.5px solid #f0f0f0;'>"
        gr+="<span style='font-size:14px;font-weight:500;color:#111;'>"+m["ticker"]+"</span>"
        gr+="<span style='font-size:13px;color:#888;'>$"+str(m["price"])+"</span>"
        gr+=pill("+"+str(m["change_pct"])+"%","#00863a","#e6f9ec")+"</div>"
    lr=""
    for m in [x for x in movers if x.get("mover_type")=="loser"][:5]:
        lr+="<div style='display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:0.5px solid #f0f0f0;'>"
        lr+="<span style='font-size:14px;font-weight:500;color:#111;'>"+m["ticker"]+"</span>"
        lr+="<span style='font-size:13px;color:#888;'>$"+str(m["price"])+"</span>"
        lr+=pill(str(m["change_pct"])+"%","#cc3d00","#fff0eb")+"</div>"

    # news
    ni=""
    for n in news:
        ni+="<div style='padding:10px 0;border-bottom:0.5px solid #f0f0f0;'>"
        ni+="<a href='"+n.get("url","#")+"' style='color:#111;text-decoration:none;font-size:14px;font-weight:500;line-height:1.5;'>"+n["title"]+"</a>"
        ni+="<div style='color:#888;font-size:12px;margin-top:3px;'>"+n["source"]+"</div></div>"
    if not ni: ni="<div style='padding:12px 0;color:#888;'>No news today.</div>"

    # macro
    mr=""
    for k,v in macro.items():
        mr+="<div style='display:flex;justify-content:space-between;align-items:center;padding:10px 0;border-bottom:0.5px solid #f0f0f0;'>"
        mr+="<span style='font-size:14px;color:#333;'>"+k+"</span>"
        mr+="<div style='display:flex;align-items:center;gap:8px;'>"
        mr+="<span style='font-size:14px;font-weight:500;color:#111;'>"+v["value"]+"</span>"
        mr+=pill(v["rating"],v["color"],v["bg"])+"</div></div>"

    # earnings
    rr=""
    for e in earnings.get("recent",[]):
        beat=e.get("beat",False); ec="#00863a" if beat else "#cc3d00"; eb="#e6f9ec" if beat else "#fff0eb"
        sign="+" if e["surprise_pct"]>0 else ""
        rr+="<div style='display:flex;justify-content:space-between;align-items:center;padding:9px 0;border-bottom:0.5px solid #f0f0f0;'>"
        rr+="<span style='font-size:14px;font-weight:500;color:#111;'>"+e["ticker"]+"</span>"
        rr+="<span style='font-size:13px;color:#555;'>$"+str(e["eps_actual"])+" vs $"+str(e["eps_estimate"])+"</span>"
        rr+=pill(("Beat" if beat else "Miss")+" "+sign+str(e["surprise_pct"])+"%",ec,eb)+"</div>"
    ur=""
    for e in earnings.get("upcoming",[]):
        est="$"+str(e["eps_estimate"])+" est" if e["eps_estimate"]!="N/A" else "Est N/A"
        ur+="<div style='display:flex;justify-content:space-between;align-items:center;padding:9px 0;border-bottom:0.5px solid #f0f0f0;'>"
        ur+="<span style='font-size:14px;font-weight:500;color:#111;'>"+e["ticker"]+"</span>"
        ur+="<span style='font-size:13px;color:#888;'>"+e["date"]+"</span>"
        ur+="<span style='font-size:13px;color:#555;'>"+est+"</span></div>"

    # swing cards
    sc=""
    for t in analysis.get("swing_trades",[]):
        bias=t.get("bias","Bullish")
        bc="#00863a" if bias=="Bullish" else "#cc3d00"; bb="#e6f9ec" if bias=="Bullish" else "#fff0eb"
        src=t.get("source","Watchlist")
        scc="#185fa5" if src=="Watchlist" else "#996300"; scb="#e3f2fd" if src=="Watchlist" else "#fff3e0"
        sc+="<div style='border:0.5px solid #e8e8e8;border-radius:12px;padding:18px;margin-bottom:10px;'>"
        sc+="<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;'>"
        sc+="<div style='display:flex;align-items:center;gap:8px;'>"
        sc+="<span style='font-size:17px;font-weight:500;color:#111;'>"+t.get("ticker","")+"</span>"
        sc+=pill(("▲ " if bias=="Bullish" else "▼ ")+bias,bc,bb)
        sc+=pill(src,scc,scb)+"</div>"
        sc+="<span style='font-size:12px;color:#888;'>"+t.get("timeframe","")+"</span></div>"
        sc+="<div style='display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px;'>"
        sc+="<div style='background:#f7f7f7;border-radius:8px;padding:10px;'><div style='font-size:11px;color:#888;margin-bottom:3px;'>Entry zone</div><div style='font-size:15px;font-weight:500;color:#111;'>"+t.get("entry_zone","")+"</div></div>"
        sc+="<div style='background:#f7f7f7;border-radius:8px;padding:10px;'><div style='font-size:11px;color:#888;margin-bottom:3px;'>Current price</div><div style='font-size:15px;font-weight:500;color:#111;'>$"+str(t.get("current_price",""))+"</div></div></div>"
        sc+="<div style='display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px;'>"
        sc+="<div style='background:#f7f7f7;border-radius:8px;padding:10px;'><div style='font-size:11px;color:#888;margin-bottom:3px;'>Risk/Reward</div><div style='font-size:15px;font-weight:500;color:#111;'>"+t.get("risk_reward","N/A")+"</div></div>"
        vol_sig=t.get("volume_signal","")
        vol_color="#00863a" if "High volume" in vol_sig else "#888"
        sc+="<div style='background:#f7f7f7;border-radius:8px;padding:10px;'><div style='font-size:11px;color:#888;margin-bottom:3px;'>Volume</div><div style='font-size:13px;font-weight:500;color:"+vol_color+";'>"+vol_sig+"</div></div></div>"
        sc+="<div style='font-size:13px;color:#444;line-height:1.6;margin-bottom:10px;'>"+t.get("thesis","")+"</div>"
        sc+="<div style='border-top:0.5px solid #f0f0f0;padding-top:8px;font-size:12px;'><span style='color:#FF5000;font-weight:500;'>Invalidated if </span><span style='color:#666;'>"+t.get("invalidation","")+"</span></div></div>"
    if not sc: sc="<div style='font-size:14px;color:#888;'>No clear setups today.</div>"

    # macro opps
    mo=""
    tcolors=[("#1a237e","#e8eaf6"),("#1b5e20","#e8f5e9"),("#880e4f","#fce4ec"),("#e65100","#fff3e0")]
    for i,td in enumerate(analysis.get("macro_opportunities",[])):
        tc,tbg=tcolors[i%len(tcolors)]
        mo+="<div style='border:0.5px solid #e8e8e8;border-radius:12px;padding:18px;margin-bottom:12px;'>"
        mo+="<div style='background:"+tbg+";border-radius:8px;padding:10px 14px;margin-bottom:12px;'>"
        mo+="<div style='font-size:12px;font-weight:500;color:"+tc+";text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;'>"+td.get("theme","")+"</div>"
        mo+="<div style='font-size:13px;color:#333;line-height:1.6;'>"+td.get("theme_summary","")+"</div></div>"
        for p in td.get("plays",[]):
            pt=p.get("type","Stock"); ptc="#185fa5" if pt=="ETF" else "#00863a"; ptb="#e3f2fd" if pt=="ETF" else "#e6f9ec"
            mo+="<div style='border:0.5px solid #f0f0f0;border-radius:8px;padding:12px;margin-bottom:8px;'>"
            mo+="<div style='display:flex;align-items:center;gap:8px;margin-bottom:6px;'>"
            mo+="<span style='font-size:15px;font-weight:500;color:#111;'>"+p.get("ticker","")+"</span>"
            mo+="<span style='font-size:13px;color:#555;'>"+p.get("company_name","")+"</span>"
            mo+=pill(pt,ptc,ptb)+"</div>"
            mo+="<div style='font-size:13px;color:#444;margin-bottom:4px;'><b>Why now:</b> "+p.get("why_underrated","")+"</div>"
            mo+="<div style='font-size:13px;color:#444;margin-bottom:4px;'><b>Catalyst:</b> "+p.get("catalyst","")+"</div>"
            mo+="<div style='font-size:12px;color:#888;'>Timeframe: "+p.get("timeframe","")+"</div></div>"
        mo+="</div>"
    if not mo: mo="<div style='font-size:14px;color:#888;'>No macro themes today.</div>"

    card = lambda title,body: "<div style='background:#fff;border-radius:16px;padding:20px 24px;margin-bottom:12px;border:0.5px solid #e8e8e8;'><div style='font-size:12px;color:#888;text-transform:uppercase;letter-spacing:1px;margin-bottom:16px;'>"+title+"</div>"+body+"</div>"
    sub = lambda txt: "<p style='margin:14px 0 0;color:#555;font-size:13px;line-height:1.6;border-top:0.5px solid #f0f0f0;padding-top:12px;'>"+txt+"</p>"

    movers_sec=""
    if gr or lr:
        movers_sec=card("S&P 500 top movers","<div style='display:grid;grid-template-columns:1fr 1fr;gap:16px;'><div><div style='font-size:12px;font-weight:500;color:#00863a;margin-bottom:8px;'>Top gainers</div>"+gr+"</div><div><div style='font-size:12px;font-weight:500;color:#cc3d00;margin-bottom:8px;'>Top losers</div>"+lr+"</div></div>")

    earn_sec=""
    hr=earnings.get("recent",[]); hu=earnings.get("upcoming",[])
    if hr or hu:
        inner=""
        if hr: inner+="<div style='font-size:12px;font-weight:500;color:#333;margin-bottom:8px;'>Recent results</div>"+rr+"<div style='height:16px;'></div>"
        if hu: inner+="<div style='font-size:12px;font-weight:500;color:#333;margin-bottom:8px;'>Upcoming this week</div>"+ur
        earn_sec=card("Earnings",inner)

    html = "<!DOCTYPE html><html><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width,initial-scale=1'></head>"
    html += "<body style='margin:0;padding:0;background:#f4f4f4;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;'>"
    html += "<div style='max-width:620px;margin:0 auto;padding:20px 16px;'>"
    html += "<div style='background:#000;border-radius:16px;padding:28px 24px 22px;margin-bottom:12px;display:flex;justify-content:space-between;align-items:flex-start;'>"
    html += "<div><div style='font-size:11px;font-weight:500;color:#888;letter-spacing:2px;text-transform:uppercase;margin-bottom:6px;'>Market Briefing</div>"
    html += "<div style='font-size:22px;font-weight:500;color:#fff;'>"+today+"</div></div>"
    html += "<div style='text-align:right;'><div style='font-size:11px;color:#888;margin-bottom:5px;'>Overall</div>"
    html += pill(sl+" "+str(ss)+"/10",slc[0],slc[1])+"</div></div>"
    html += card("Market summary","<p style='margin:0;color:#222;font-size:15px;line-height:1.7;'>"+analysis.get("market_summary","")+"</p>")
    html += "<div style='background:#000;border-radius:16px;padding:18px 24px;margin-bottom:12px;display:flex;gap:14px;align-items:flex-start;'>"
    html += "<div style='font-size:20px;color:#FFD700;margin-top:2px;'>&#9889;</div>"
    html += "<div><div style='font-size:11px;color:#888;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px;'>Key thing to watch</div>"
    html += "<div style='font-size:14px;color:#fff;line-height:1.6;'>"+analysis.get("key_insight","")+"</div></div></div>"
    fgbar = str(fgv) if isinstance(fgv, int) else "50"
    html += "<div style='background:#fff;border-radius:16px;padding:20px 24px;margin-bottom:12px;border:0.5px solid #e8e8e8;'>"
    html += "<div style='font-size:12px;color:#888;text-transform:uppercase;letter-spacing:1px;margin-bottom:16px;'>Market Sentiment</div>"
    html += "<div style='display:flex;align-items:center;gap:20px;margin-bottom:14px;'>"
    html += "<div style='text-align:center;'><div style='font-size:11px;color:#888;margin-bottom:4px;'>Fear & Greed</div>"
    html += "<div style='font-size:36px;font-weight:600;color:"+fgc+";'>"+str(fgv)+"</div>"
    html += "<span style='background:"+fgb+";color:"+fgc+";padding:3px 12px;border-radius:20px;font-size:12px;font-weight:500;'>"+fgl+"</span></div>"
    html += "<div style='flex:1;'><div style='background:#f0f0f0;border-radius:6px;height:8px;margin-bottom:8px;'>"
    html += "<div style='background:"+fgc+";width:"+fgbar+"%;height:8px;border-radius:6px;'></div></div>"
    html += "<div style='display:flex;justify-content:space-between;font-size:10px;color:#bbb;'><span>Extreme Fear</span><span>Neutral</span><span>Extreme Greed</span></div></div></div>"
    html += "<p style='margin:0;color:#444;font-size:13px;line-height:1.6;border-top:0.5px solid #f0f0f0;padding-top:12px;'>"+analysis.get("sentiment_commentary","")+"</p></div>"
    html += card("Your watchlist", wl+sub(analysis.get("notable_movers","")))
    html += movers_sec
    html += earn_sec
    if portfolio_html:
        html += card("Paper Portfolio", portfolio_html)
    html += card("Swing trade setups","<div style='font-size:12px;color:#bbb;margin-bottom:16px;'>3-10 day holds - not financial advice</div>"+sc)
    html += card("Macro opportunity scan","<div style='font-size:12px;color:#bbb;margin-bottom:16px;'>Under-the-radar plays - not financial advice</div>"+mo)
    html += card("Top business news",ni)
    # Sector rotation card
    if sectors:
        sec_html = "<div style='display:flex;flex-direction:column;gap:0;'>"
        for s in sectors:
            chg = s["change_pct"]
            sc = "#00863a" if chg > 0 else "#cc3d00"
            sb = "#e6f9ec" if chg > 0 else "#fff0eb"
            sign = "+" if chg > 0 else ""
            bar_w = min(100, int(abs(chg) * 10))
            sec_html += "<div style='display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:0.5px solid #f0f0f0;'>"
            sec_html += "<span style='font-size:13px;color:#333;'>" + s["etf"] + " <span style='color:#888;font-size:12px;'>"+s["name"]+"</span></span>"
            sec_html += "<span style='background:"+sb+";color:"+sc+";padding:2px 10px;border-radius:20px;font-size:12px;font-weight:500;'>"+sign+str(chg)+"%</span></div>"
        sec_html += "</div>"
        html += card("Sector Rotation", sec_html)
    html += card("Macro indicators", mr + aaii_html + sub(analysis.get("macro_context","")))
    html += "<div style='text-align:center;color:#bbb;font-size:11px;padding:8px;'>Generated by your market agent - Not financial advice</div>"
    html += "</div></body></html>"
    return html

def send_email(html):
    print("Sending...")
    today=datetime.now().strftime("%B %d, %Y")
    msg=MIMEMultipart("alternative")
    msg["Subject"]="Market Briefing - "+today
    msg["From"]=GMAIL_ADDRESS; msg["To"]=RECIPIENT_EMAIL
    msg.attach(MIMEText("View in HTML email client.","plain"))
    msg.attach(MIMEText(html,"html"))
    with smtplib.SMTP_SSL("smtp.gmail.com",465) as s:
        s.login(GMAIL_ADDRESS,GMAIL_APP_PASS)
        s.sendmail(GMAIL_ADDRESS,RECIPIENT_EMAIL,msg.as_string())
    print("Sent!")


PORTFOLIO_FILE = "portfolio.json"

def load_portfolio():
    if os.path.exists(PORTFOLIO_FILE):
        try:
            with open(PORTFOLIO_FILE, "r") as f:
                return json.load(f)
        except:
            pass
    return {
        "start_date": datetime.now().strftime("%Y-%m-%d"),
        "open_positions": [],
        "closed_trades": [],
        "total_trades": 0,
        "wins": 0,
        "losses": 0,
        "total_pnl_pct": 0.0
    }

def save_portfolio(portfolio):
    with open(PORTFOLIO_FILE, "w") as f:
        json.dump(portfolio, f, indent=2)
    print("Portfolio saved.")


def get_price_fast(ticker):
    """
    Fast price lookup using FMP — no rate limit delay.
    Used for portfolio position checks where speed matters.
    Falls back to yfinance if FMP fails.
    """
    # Try FMP first (no delay needed)
    try:
        resp = requests.get(
            "https://financialmodelingprep.com/api/v3/quote-short/" + ticker,
            params={"apikey": FMP_KEY},
            timeout=8
        )
        data = resp.json()
        if isinstance(data, list) and len(data) > 0:
            price = float(data[0].get("price", 0) or 0)
            if price > 0:
                return round(price, 2)
    except Exception as e:
        pass

    # Fallback: yfinance (no API quota)
    try:
        import yfinance as yf
        hist = yf.Ticker(ticker).history(period="2d")
        if not hist.empty:
            return round(float(hist["Close"].iloc[-1]), 2)
    except:
        pass

    return None

def update_portfolio(portfolio, swing_trades, current_prices):
    today        = datetime.now().strftime("%Y-%m-%d")
    closed_today = []
    still_open   = []
    MAX_HOLD_DAYS = 10

    for pos in portfolio.get("open_positions", []):
        ticker     = pos["ticker"]
        current    = current_prices.get(ticker)
        bias       = pos.get("bias", "Bullish")
        target     = float(pos.get("price_target", 0) or 0)
        stop       = float(pos.get("invalidation_price", 0) or 0)
        entry      = float(pos.get("entry_price", current or 0) or 0)
        entry_date = pos.get("entry_date", today)
        try:
            days_held = (datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(entry_date, "%Y-%m-%d")).days
        except:
            days_held = 0

        closed = False
        result = None

        if current is None:
            # Use fast FMP/yfinance fetch — no AV rate limit delay
            price = get_price_fast(ticker)
            if price and price > 0:
                current = price
                current_prices[ticker] = current
                print("  " + ticker + ": fast fetch $" + str(current))

        if current is None:
            if days_held >= MAX_HOLD_DAYS:
                print("  " + ticker + ": no price, expired day " + str(days_held))
                result = {"outcome": "NEUTRAL", "exit_price": entry, "pnl_pct": 0, "exit_date": today, "reason": "10-day expiry (price unavailable)"}
                closed = True
            else:
                print("  " + ticker + ": no price day " + str(days_held) + " keeping open")
                still_open.append(pos)
                continue

        if current is not None:
            print("  Checking " + ticker + ": $" + str(current) + " target=$" + str(target) + " stop=$" + str(stop) + " day=" + str(days_held))

        if bias == "Bullish":
            if target and current is not None and current >= target:
                pnl = round(((current - entry) / entry) * 100, 2) if entry else 0
                result = {"outcome": "WIN", "exit_price": current, "pnl_pct": pnl, "exit_date": today, "reason": "Target hit"}
                closed = True
                print("  " + ticker + " TARGET HIT WIN " + str(pnl) + "%")
            elif stop and current is not None and current <= stop:
                pnl = round(((current - entry) / entry) * 100, 2) if entry else 0
                result = {"outcome": "LOSS", "exit_price": current, "pnl_pct": pnl, "exit_date": today, "reason": "Stop hit"}
                closed = True
                print("  " + ticker + " STOP HIT LOSS " + str(pnl) + "%")
            elif days_held >= MAX_HOLD_DAYS:
                pnl = round(((current - entry) / entry) * 100, 2) if current and entry else 0
                outcome = "WIN" if pnl > 0 else "LOSS" if pnl < 0 else "NEUTRAL"
                result = {"outcome": outcome, "exit_price": current or entry, "pnl_pct": pnl, "exit_date": today, "reason": "10-day expiry"}
                closed = True
                print("  " + ticker + " EXPIRED " + outcome + " " + str(pnl) + "%")
        else:
            if target and current is not None and current <= target:
                pnl = round(((entry - current) / entry) * 100, 2) if entry else 0
                result = {"outcome": "WIN", "exit_price": current, "pnl_pct": pnl, "exit_date": today, "reason": "Target hit"}
                closed = True
                print("  " + ticker + " TARGET HIT WIN " + str(pnl) + "%")
            elif stop and current is not None and current >= stop:
                pnl = round(((entry - current) / entry) * 100, 2) if entry else 0
                result = {"outcome": "LOSS", "exit_price": current, "pnl_pct": pnl, "exit_date": today, "reason": "Stop hit"}
                closed = True
                print("  " + ticker + " STOP HIT LOSS " + str(pnl) + "%")
            elif days_held >= MAX_HOLD_DAYS:
                pnl = round(((entry - current) / entry) * 100, 2) if current and entry else 0
                outcome = "WIN" if pnl > 0 else "LOSS" if pnl < 0 else "NEUTRAL"
                result = {"outcome": outcome, "exit_price": current or entry, "pnl_pct": pnl, "exit_date": today, "reason": "10-day expiry"}
                closed = True
                print("  " + ticker + " EXPIRED " + outcome + " " + str(pnl) + "%")

        if closed and result:
            closed_trade = {**pos, **result, "days_held": days_held}
            portfolio["closed_trades"].append(closed_trade)
            portfolio["total_trades"] = portfolio.get("total_trades", 0) + 1
            if result["outcome"] == "WIN":
                portfolio["wins"] = portfolio.get("wins", 0) + 1
            elif result["outcome"] == "LOSS":
                portfolio["losses"] = portfolio.get("losses", 0) + 1
            portfolio["total_pnl_pct"] = round(portfolio.get("total_pnl_pct", 0.0) + result["pnl_pct"], 2)
            closed_today.append(closed_trade)
        elif not closed:
            still_open.append(pos)

    portfolio["open_positions"] = still_open

    MAX_POSITIONS = 12
    existing_tickers     = set(p["ticker"] for p in portfolio["open_positions"])
    closed_today_tickers = set(c["ticker"] for c in closed_today)
    blocked = existing_tickers | closed_today_tickers

    for trade in swing_trades:
        if len(portfolio["open_positions"]) >= MAX_POSITIONS:
            print("Max " + str(MAX_POSITIONS) + " positions reached")
            break
        ticker = trade.get("ticker", "")
        if not ticker or ticker in blocked:
            if ticker in closed_today_tickers:
                print("Skipping " + ticker + " closed today")
            continue
        midpoint = float(trade.get("entry_midpoint", 0) or 0)
        if not midpoint:
            try:
                zone = trade.get("entry_zone", "")
                nums = []
                for x in zone.replace("-", " ").split():
                    try: nums.append(float(x.replace("$","").replace(",","").strip()))
                    except: pass
                midpoint = round(sum(nums)/len(nums), 2) if nums else float(trade.get("current_price", 0) or 0)
            except:
                midpoint = float(trade.get("current_price", 0) or 0)
        if midpoint <= 0:
            continue
        new_pos = {
            "ticker":             ticker,
            "entry_date":         today,
            "entry_price":        midpoint,
            "price_target":       float(trade.get("price_target", 0) or 0),
            "invalidation_price": float(trade.get("invalidation_price", 0) or 0),
            "bias":               trade.get("bias", "Bullish"),
            "thesis":             trade.get("thesis", ""),
            "source":             trade.get("source", ""),
        }
        portfolio["open_positions"].append(new_pos)
        blocked.add(ticker)
        print("Opened: " + ticker + " @ $" + str(midpoint) + " target=$" + str(new_pos["price_target"]) + " stop=$" + str(new_pos["invalidation_price"]))

    return portfolio, closed_today

def build_portfolio_section(portfolio, closed_today):
    open_pos  = portfolio.get("open_positions", [])
    closed_all= portfolio.get("closed_trades", [])
    total     = portfolio.get("total_trades", 0)
    wins      = portfolio.get("wins", 0)
    losses    = portfolio.get("losses", 0)
    total_pnl = portfolio.get("total_pnl_pct", 0.0)
    start     = portfolio.get("start_date","")
    win_rate  = round((wins/total)*100) if total>0 else 0

    # Stats bar
    pnl_color = "#00863a" if total_pnl >= 0 else "#cc3d00"
    pnl_bg    = "#e6f9ec" if total_pnl >= 0 else "#fff0eb"
    pnl_sign  = "+" if total_pnl >= 0 else ""

    stats = "<div style='display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:10px;margin-bottom:16px;'>"
    def stat_card(label, value, vc="#111", vb="transparent"):
        return "<div style='background:#f7f7f7;border-radius:8px;padding:10px 12px;'><div style='font-size:11px;color:#888;margin-bottom:4px;'>"+label+"</div><div style='font-size:16px;font-weight:500;color:"+vc+";background:"+vb+";'>"+value+"</div></div>"
    stats += stat_card("Total trades", str(total))
    stats += stat_card("Win rate", str(win_rate)+"%", "#00863a" if win_rate>=55 else "#cc3d00")
    stats += stat_card("Wins / Losses", str(wins)+" / "+str(losses))
    stats += stat_card("Total P&L", pnl_sign+str(total_pnl)+"%", pnl_color)
    stats += "</div>"

    # Open positions — sorted newest first
    op_html = ""
    open_pos_sorted = sorted(open_pos, key=lambda x: x.get("entry_date",""), reverse=True)
    if open_pos_sorted:
        op_html += "<div style='font-size:12px;font-weight:500;color:#333;margin-bottom:8px;'>Open positions ("+str(len(open_pos_sorted))+")</div>"
        for p in open_pos_sorted:
            bias = p.get("bias","Bullish")
            bc = "#00863a" if bias=="Bullish" else "#cc3d00"
            bb = "#e6f9ec" if bias=="Bullish" else "#fff0eb"
            ep = p.get("entry_price",0); pt = p.get("price_target",0); ip = p.get("invalidation_price",0)
            op_html += "<div style='display:flex;justify-content:space-between;align-items:center;padding:9px 0;border-bottom:0.5px solid #f0f0f0;'>"
            op_html += "<div><span style='font-size:14px;font-weight:500;color:#111;'>"+p["ticker"]+"</span>"
            op_html += "<span style='background:"+bb+";color:"+bc+";padding:1px 7px;border-radius:20px;font-size:11px;font-weight:500;margin-left:6px;'>"+bias+"</span></div>"
            op_html += "<div style='font-size:12px;color:#888;text-align:right;'>"
            op_html += "Entry $"+str(ep)+" &middot; Target $"+str(pt)+" &middot; Stop $"+str(ip)
            op_html += "<div style='font-size:11px;color:#bbb;'>Since "+p.get("entry_date","")+"</div></div></div>"
    if not open_pos_sorted:
        op_html += "<div style='font-size:13px;color:#888;margin-bottom:12px;'>No open positions.</div>"

    # Recently closed
    rc_html = ""
    recent_closed = (closed_today + [c for c in reversed(closed_all) if c not in closed_today])[:5]
    if recent_closed:
        rc_html += "<div style='font-size:12px;font-weight:500;color:#333;margin-top:16px;margin-bottom:8px;'>Recently closed</div>"
        for c in recent_closed:
            outcome = c.get("outcome","")
            pnl = c.get("pnl_pct",0); sign="+" if pnl>=0 else ""
            oc="#00863a" if outcome=="WIN" else "#cc3d00"; ob="#e6f9ec" if outcome=="WIN" else "#fff0eb"
            rc_html += "<div style='display:flex;justify-content:space-between;align-items:center;padding:9px 0;border-bottom:0.5px solid #f0f0f0;'>"
            rc_html += "<span style='font-size:14px;font-weight:500;color:#111;'>"+c.get("ticker","")+"</span>"
            rc_html += "<span style='font-size:12px;color:#888;'>"+c.get("reason","")+" on "+c.get("exit_date","")+"</span>"
            rc_html += "<span style='background:"+ob+";color:"+oc+";padding:2px 10px;border-radius:20px;font-size:12px;font-weight:500;'>"+sign+str(pnl)+"%</span></div>"

    disclaimer = "<div style='font-size:11px;color:#bbb;margin-top:12px;'>Paper portfolio started "+start+". Simulated trades, not real money. Past performance does not guarantee future results.</div>"

    if total == 0 and not open_pos:
        body = "<div style='font-size:14px;color:#888;'>Portfolio tracking starts today. New trades from today's swing setups will be tracked here going forward.</div>"
    else:
        body = stats + op_html + rc_html + disclaimer

    return body

def main():
    print("Starting...")
    stocks  = get_stock_data(WATCHLIST)
    news    = get_broad_news()
    macro   = get_macro_data()
    movers  = get_sp500_top_movers()
    sent    = get_sentiment_indicators()
    earn    = get_earnings_data()
    sectors = get_sector_data()
    # Get SPY change for relative strength calculation
    spy_change       = next((s["change_pct"] for s in stocks if s["ticker"]=="SPY"), 0)
    finviz_candidates= get_finviz_candidates()
    scan_universe    = get_scan_universe(WATCHLIST, GROWTH_UNIVERSE, movers, spy_change, finviz_candidates)
    swing       = get_swing_data(WATCHLIST, movers, scan_universe)
    analysis    = generate_analysis(stocks,news,macro,swing,movers,sent,earn,sectors,scan_universe)

    # Portfolio tracking
    portfolio = load_portfolio()

    # Step 1: Build current prices dict
    current_prices = {s["ticker"]: s["price"] for s in stocks}
    for sw in swing:
        if sw.get("ticker") and sw.get("price"):
            current_prices[sw["ticker"]] = sw["price"]

    # Step 2: Fetch prices for ALL open positions (critical for non-watchlist stocks)
    open_tickers = [p["ticker"] for p in portfolio.get("open_positions", [])]
    missing = [t for t in open_tickers if t not in current_prices]
    if missing:
        print("Fetching prices for " + str(len(missing)) + " open positions: " + str(missing))
        for ticker in missing:
            price = get_price_fast(ticker)
            if price and price > 0:
                current_prices[ticker] = price
                print("  Got " + ticker + ": $" + str(price))
            else:
                print("  No price for " + ticker)

    # Step 3: Evaluate open positions FIRST (check targets/stops/expiry)
    # This must happen before adding new trades so closures reduce position count
    portfolio, closed_today = update_portfolio(portfolio, analysis.get("swing_trades",[]), current_prices)
    save_portfolio(portfolio)
    portfolio_html = build_portfolio_section(portfolio, closed_today)

    html    = build_email(stocks,news,macro,analysis,movers,sent,earn,portfolio_html,sectors)
    send_email(html)
    print("Done!")

main()
