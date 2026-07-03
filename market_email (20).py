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

def parse_stooq(symbol):
    resp = requests.get("https://stooq.com/q/d/l/?s="+symbol+"&i=d", headers={"User-Agent":"Mozilla/5.0"}, timeout=12)
    rows = [l.strip() for l in resp.text.strip().splitlines() if l.strip() and not l.lower().startswith("date") and "," in l]
    if len(rows) < 2:
        raise Exception("only " + str(len(rows)) + " data rows")
    last = rows[-1].split(",")
    prev = rows[-2].split(",")
    close = round(float(last[4]), 2)
    prev_close = round(float(prev[4]), 2)
    chg = round((close - prev_close) / prev_close * 100, 2)
    return close, chg

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
        vv, vc = parse_stooq("%5Evix")
        lbl = "Low Volatility" if vv<15 else "Normal" if vv<20 else "Elevated Fear" if vv<30 else "Extreme Fear"
        result["vix"] = {"value":vv,"change":vc,"label":lbl}
        print("VIX: " + str(vv))
    except Exception as e:
        print("VIX failed: " + str(e))
        result["vix"] = {"value":"N/A","change":0,"label":"Unavailable"}
    try:
        pv, _ = parse_stooq("%5Epcr")
        lbl = "Very Bullish" if pv<0.6 else "Bullish" if pv<0.8 else "Neutral" if pv<1.0 else "Bearish" if pv<1.2 else "Very Bearish"
        result["put_call"] = {"value":pv,"label":lbl}
        print("P/C: " + str(pv))
    except Exception as e:
        print("P/C failed: " + str(e))
        result["put_call"] = {"value":"N/A","label":"Unavailable"}
    return result

def get_earnings_data():
    print("Fetching earnings...")
    import yfinance as yf
    recent, upcoming = [], []
    today = datetime.now().date()
    past = today - timedelta(days=7)
    future = today + timedelta(days=7)
    scan = ["AAPL","MSFT","GOOGL","NVDA","AMZN","META","TSLA","JPM","BAC","GS","V","MA","UNH","JNJ","XOM","WMT","HD","NFLX","AMD","CRM","QCOM","MU","SOFI","COIN","PLTR","CELH","CAVA"]
    for ticker in scan:
        try:
            stk = yf.Ticker(ticker)
            try:
                cal = stk.calendar
                if isinstance(cal, dict):
                    dates = cal.get("Earnings Date",[])
                    if not hasattr(dates,"__iter__") or isinstance(dates,str): dates=[dates]
                    for d in list(dates):
                        try:
                            dd = d.date() if hasattr(d,"date") else d
                            if isinstance(dd, type(today)) and today<=dd<=future:
                                upcoming.append({"ticker":ticker,"date":str(dd),"eps_estimate":"N/A","time":"TBD"})
                        except: pass
            except: pass
            try:
                hist = stk.earnings_history
                if hist is not None and hasattr(hist,"iterrows"):
                    for idx, row in hist.iterrows():
                        try:
                            rd = idx.date() if hasattr(idx,"date") else None
                            if rd and past<=rd<=today:
                                ea=row.get("epsActual"); ee=row.get("epsEstimate")
                                if ea is not None and ee is not None:
                                    ea,ee=float(ea),float(ee)
                                    surp=round(((ea-ee)/abs(ee))*100,1) if ee!=0 else 0
                                    recent.append({"ticker":ticker,"date":str(rd),"eps_actual":round(ea,2),"eps_estimate":round(ee,2),"surprise_pct":surp,"beat":ea>=ee})
                                    print("  Earnings: " + ticker + " " + ("+"+str(surp) if surp>0 else str(surp)) + "%")
                        except: pass
            except: pass
        except: pass
    seen=set(); uniq_up=[]
    for u in sorted(upcoming,key=lambda x:x["date"]):
        if u["ticker"] not in seen:
            seen.add(u["ticker"]); uniq_up.append(u)
    recent=sorted(recent,key=lambda x:abs(x.get("surprise_pct",0)),reverse=True)[:3]
    upcoming=uniq_up[:8]
    print("Earnings: " + str(len(recent)) + " recent, " + str(len(upcoming)) + " upcoming")
    return {"recent":recent,"upcoming":upcoming}

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
    return result if len(result)>1 else None

def get_swing_data(watchlist, movers):
    print("Fetching technicals...")
    picks=random.sample(GROWTH_UNIVERSE,min(4,len(GROWTH_UNIVERSE)))
    wl=[t for t in watchlist if "-USD" not in t.upper()]
    mv=[m["ticker"] for m in movers[:4] if isinstance(m,dict)]
    seen=set(); combined=[]
    for t in picks+mv+wl:
        if t not in seen: combined.append(t); seen.add(t)
    results=[]
    for ticker in combined[:6]:
        try:
            print("Technicals: " + ticker)
            q=get_quote_stock(ticker)
            if not q or q["price"]==0: continue
            tech=get_technicals(ticker)
            if q and tech:
                results.append({**q,**tech})
                print("  RSI:" + str(tech.get("rsi","N/A")) + " SMA50:$" + str(tech.get("sma50","N/A")))
        except Exception as e:
            print(ticker + " tech failed: " + str(e))
    return results

def get_macro_data():
    print("Fetching macro...")
    indicators={"Federal Funds Rate":("FEDFUNDS","rate"),"Unemployment Rate":("UNRATE","unemp"),"10-Year Treasury":("DGS10","yield"),"GDP Growth Rate":("A191RL1Q225SBEA","gdp")}
    results={}
    for name,(sid,kind) in indicators.items():
        try:
            obs=requests.get("https://api.stlouisfed.org/fred/series/observations",params={"series_id":sid,"api_key":FRED_API_KEY,"file_type":"json","sort_order":"desc","limit":10},timeout=10).json().get("observations",[])
            val=next((o["value"] for o in obs if o.get("value") and o["value"] not in [".","NA",""]),None)
            if val:
                v=float(val)
                if kind=="rate":
                    if v<=2.5: rat,rc,rb="Good","#00863a","#e6f9ec"
                    elif v<=4.5: rat,rc,rb="Neutral","#996300","#fff8e6"
                    else: rat,rc,rb="Restrictive","#cc3d00","#fff0eb"
                elif kind=="unemp":
                    if v<=4.0: rat,rc,rb="Strong","#00863a","#e6f9ec"
                    elif v<=5.5: rat,rc,rb="Moderate","#996300","#fff8e6"
                    else: rat,rc,rb="Weak","#cc3d00","#fff0eb"
                elif kind=="yield":
                    if v<=3.5: rat,rc,rb="Accommodative","#00863a","#e6f9ec"
                    elif v<=4.5: rat,rc,rb="Neutral","#996300","#fff8e6"
                    else: rat,rc,rb="Tight","#cc3d00","#fff0eb"
                else:
                    if v>=2.5: rat,rc,rb="Strong","#00863a","#e6f9ec"
                    elif v>=1.0: rat,rc,rb="Moderate","#996300","#fff8e6"
                    else: rat,rc,rb="Weak","#cc3d00","#fff0eb"
                results[name]={"value":val,"rating":rat,"color":rc,"bg":rb}
                print("Got " + name + ": " + val)
            else:
                results[name]={"value":"N/A","rating":"N/A","color":"#888","bg":"#f5f5f5"}
        except Exception as e:
            print(name + " failed: " + str(e))
            results[name]={"value":"N/A","rating":"N/A","color":"#888","bg":"#f5f5f5"}
    return results

def generate_analysis(stocks, news, macro, swing, movers, sentiment, earnings):
    print("Generating analysis...")
    client=anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    stocks_t="".join([s["ticker"]+": $"+str(s["price"])+" ("+("+" if s["change_pct"]>0 else "")+str(s["change_pct"])+"% today)\n" for s in stocks]) or "Unavailable.\n"
    news_t="\n".join(["- "+n["title"] for n in news]) or "No news.\n"
    macro_t="".join([k+": "+v["value"]+"\n" for k,v in macro.items()])
    mov_t=""
    if movers:
        mov_t+="GAINERS:\n"+"".join([m["ticker"]+": $"+str(m["price"])+" (+"+str(m["change_pct"])+"%)\n" for m in movers if m.get("mover_type")=="gainer"][:5])
        mov_t+="LOSERS:\n"+"".join([m["ticker"]+": $"+str(m["price"])+" ("+str(m["change_pct"])+"%)\n" for m in movers if m.get("mover_type")=="loser"][:5])
    swing_t="".join([s["ticker"]+": price=$"+str(s["price"])+" RSI="+str(s.get("rsi","N/A"))+" 50SMA=$"+str(s.get("sma50","N/A"))+" 200SMA=$"+str(s.get("sma200","N/A"))+"\n" for s in swing if s.get("price",0)>0])
    fg=sentiment.get("fear_greed",{}); vix=sentiment.get("vix",{}); pc=sentiment.get("put_call",{})
    sent_t="F&G: "+str(fg.get("value","N/A"))+" ("+fg.get("label","N/A")+")\nVIX: "+str(vix.get("value","N/A"))+" ("+vix.get("label","N/A")+")\nP/C: "+str(pc.get("value","N/A"))+" ("+pc.get("label","N/A")+")\n"
    earn_t=""
    if earnings.get("recent"):
        earn_t+="RECENT:\n"+"".join([e["ticker"]+" "+("BEAT" if e["beat"] else "MISS")+" "+("+" if e["surprise_pct"]>0 else "")+str(e["surprise_pct"])+"% ($"+str(e["eps_actual"])+" vs $"+str(e["eps_estimate"])+" est)\n" for e in earnings["recent"]])
    if earnings.get("upcoming"):
        earn_t+="UPCOMING:\n"+"".join([e["ticker"]+" reports "+e["date"]+"\n" for e in earnings["upcoming"]])
    prompt = "You are a financial analyst. Return ONLY valid JSON, no markdown.\n\nRULES:\n- Always include timeframe on percent moves (e.g. down 1.2% today)\n- Swing trades 3-10 day holds, entry zones within 5% of current_price\n- RSI<35 oversold RSI>70 overbought\n- Base sentiment on price action first, Fear & Greed is secondary\n- Macro opportunities: under-the-radar stocks not yet moved on news themes- price_target must be a specific realistic price (not a range). Bullish target above entry, bearish below.- invalidation_price must be a specific number, the exact price that would invalidate the setup.\n\nWATCHLIST: "+stocks_t+"\nMOVERS: "+mov_t+"\nSENTIMENT: "+sent_t+"\nNEWS: "+news_t+"\nMACRO: "+macro_t+"\nTECHNICALS: "+swing_t+"\nEARNINGS: "+(earn_t or "No data.")+"\n\nReturn:\n{\"sentiment_score\":<1-10>,\"sentiment_label\":\"<Bearish/Neutral/Bullish>\",\"market_summary\":\"<2-3 sentences>\",\"key_insight\":\"<one thing to watch>\",\"notable_movers\":\"<2-3 sentences>\",\"macro_context\":\"<2-3 sentences>\",\"sentiment_commentary\":\"<2 sentences on VIX and Put/Call>\",\"swing_trades\":[{\"ticker\":\"\",\"current_price\":0,\"bias\":\"Bullish\",\"timeframe\":\"\",\"entry_zone\":\"\",\"thesis\":\"\",\"invalidation\":\"\",\"source\":\"\"}],\"macro_opportunities\":[{\"theme\":\"\",\"theme_summary\":\"\",\"plays\":[{\"ticker\":\"\",\"company_name\":\"\",\"type\":\"Stock\",\"why_underrated\":\"\",\"catalyst\":\"\",\"timeframe\":\"\"}]}]}\n\nSwing: 2-4 trades from technicals only. Macro: 2-3 themes, 2-3 plays each."
    msg=client.messages.create(model="claude-opus-4-6",max_tokens=3000,messages=[{"role":"user","content":prompt}])
    raw=msg.content[0].text.strip().replace("```json","").replace("```","").strip()
    result=json.loads(raw)
    print("Sentiment: "+result.get("sentiment_label","?")+" | Swing: "+str(len(result.get("swing_trades",[])))+" | Themes: "+str(len(result.get("macro_opportunities",[]))))
    return result

def row(content):
    return "<div style='border-bottom:0.5px solid #f0f0f0;'>"+content+"</div>"

def pill(text, color, bg):
    return "<span style='background:"+bg+";color:"+color+";padding:2px 10px;border-radius:20px;font-size:12px;font-weight:500;'>"+text+"</span>"

def build_email(stocks, news, macro, analysis, movers, sentiment, earnings, portfolio_html=""):
    today = datetime.now().strftime("%A, %B %d, %Y")
    sl=analysis.get("sentiment_label","Neutral"); ss=analysis.get("sentiment_score",5)
    slc={"Bullish":("#00863a","#e6f9ec"),"Bearish":("#cc3d00","#fff0eb")}.get(sl,("#996300","#fff8e6"))

    fg=sentiment.get("fear_greed",{}); vix=sentiment.get("vix",{}); pc=sentiment.get("put_call",{})
    fgv=fg.get("value",50); fgl=fg.get("label","Neutral")
    fgc="#00863a" if fgv>=55 else "#cc3d00" if fgv<=35 else "#996300"
    fgb="#e6f9ec" if fgv>=55 else "#fff0eb" if fgv<=35 else "#fff8e6"
    vv=vix.get("value","N/A"); vc=vix.get("change",0); vl=vix.get("label","N/A")
    vxc="#cc3d00" if isinstance(vv,(int,float)) and vv>=25 else "#996300" if isinstance(vv,(int,float)) and vv>=20 else "#00863a"
    pv=pc.get("value","N/A"); pl=pc.get("label","N/A")
    pcc="#cc3d00" if isinstance(pv,(int,float)) and pv>=1.0 else "#00863a"

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

    fgbar=str(fgv) if isinstance(fgv,int) else "50"
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
    html += "<div style='background:#fff;border-radius:16px;padding:20px 24px;margin-bottom:12px;border:0.5px solid #e8e8e8;'>"
    html += "<div style='font-size:12px;color:#888;text-transform:uppercase;letter-spacing:1px;margin-bottom:16px;'>Sentiment indicators</div>"
    html += "<div style='display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;margin-bottom:14px;'>"
    html += "<div><div style='font-size:11px;color:#888;margin-bottom:4px;'>Fear & greed</div><div style='font-size:24px;font-weight:500;color:"+fgc+";'>"+str(fgv)+"</div><div style='background:#f0f0f0;border-radius:4px;height:4px;margin:6px 0;'><div style='background:"+fgc+";width:"+fgbar+"%;height:4px;border-radius:4px;'></div></div><div style='font-size:11px;color:"+fgc+";'>"+fgl+"</div></div>"
    html += "<div><div style='font-size:11px;color:#888;margin-bottom:4px;'>VIX</div><div style='font-size:24px;font-weight:500;color:"+vxc+";'>"+str(vv)+"</div><div style='font-size:11px;color:#888;margin:6px 0;'>"+("+" if isinstance(vc,(int,float)) and vc>0 else "")+str(vc)+"% today</div><div style='font-size:11px;color:"+vxc+";'>"+vl+"</div></div>"
    html += "<div><div style='font-size:11px;color:#888;margin-bottom:4px;'>Put/call</div><div style='font-size:24px;font-weight:500;color:"+pcc+";'>"+str(pv)+"</div><div style='font-size:11px;color:#888;margin:6px 0;'>&gt;1.0 = more puts</div><div style='font-size:11px;color:"+pcc+";'>"+pl+"</div></div></div>"
    html += "<p style='margin:0;color:#444;font-size:13px;line-height:1.6;border-top:0.5px solid #f0f0f0;padding-top:12px;'>"+analysis.get("sentiment_commentary","")+"</p></div>"
    html += card("Your watchlist", wl+sub(analysis.get("notable_movers","")))
    html += movers_sec
    html += earn_sec
    if portfolio_html:
        html += card("Paper Portfolio", portfolio_html)
    html += card("Swing trade setups","<div style='font-size:12px;color:#bbb;margin-bottom:16px;'>3-10 day holds - not financial advice</div>"+sc)
    html += card("Macro opportunity scan","<div style='font-size:12px;color:#bbb;margin-bottom:16px;'>Under-the-radar plays - not financial advice</div>"+mo)
    html += card("Top business news",ni)
    html += card("Macro indicators",mr+sub(analysis.get("macro_context","")))
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

def update_portfolio(portfolio, swing_trades, current_prices):
    today = datetime.now().strftime("%Y-%m-%d")
    closed_today = []

    # Check open positions against today's prices
    still_open = []
    for pos in portfolio.get("open_positions", []):
        ticker = pos["ticker"]
        current = current_prices.get(ticker)
        if current is None:
            still_open.append(pos)
            continue

        bias = pos.get("bias", "Bullish")
        target = pos.get("price_target", 0)
        inval  = pos.get("invalidation_price", 0)
        entry  = pos.get("entry_price", current)
        closed = False
        result = None

        if bias == "Bullish":
            if target and current >= target:
                pnl = round(((current - entry) / entry) * 100, 2)
                result = {"outcome": "WIN", "exit_price": current, "pnl_pct": pnl, "exit_date": today, "reason": "Target hit"}
                closed = True
            elif inval and current <= inval:
                pnl = round(((current - entry) / entry) * 100, 2)
                result = {"outcome": "LOSS", "exit_price": current, "pnl_pct": pnl, "exit_date": today, "reason": "Invalidated"}
                closed = True
        else:  # Bearish
            if target and current <= target:
                pnl = round(((entry - current) / entry) * 100, 2)
                result = {"outcome": "WIN", "exit_price": current, "pnl_pct": pnl, "exit_date": today, "reason": "Target hit"}
                closed = True
            elif inval and current >= inval:
                pnl = round(((entry - current) / entry) * 100, 2)
                result = {"outcome": "LOSS", "exit_price": current, "pnl_pct": pnl, "exit_date": today, "reason": "Invalidated"}
                closed = True

        if closed and result:
            closed_trade = {**pos, **result}
            portfolio["closed_trades"].append(closed_trade)
            portfolio["total_trades"] += 1
            if result["outcome"] == "WIN":
                portfolio["wins"] += 1
            else:
                portfolio["losses"] += 1
            portfolio["total_pnl_pct"] = round(portfolio.get("total_pnl_pct", 0) + result["pnl_pct"], 2)
            closed_today.append(closed_trade)
            print("Closed " + ticker + ": " + result["outcome"] + " " + str(result["pnl_pct"]) + "%")
        else:
            still_open.append(pos)

    portfolio["open_positions"] = still_open

    # Add new trades from today's recommendations
    existing_tickers = [p["ticker"] for p in portfolio["open_positions"]]
    for trade in swing_trades:
        ticker = trade.get("ticker","")
        if not ticker or ticker in existing_tickers:
            continue
        midpoint = trade.get("entry_midpoint", 0)
        if not midpoint:
            try:
                zone = trade.get("entry_zone","")
                nums = [float(x.replace("$","").strip()) for x in zone.replace("-"," ").split() if x.replace(".","").replace("$","").replace("-","").isdigit() or any(c.isdigit() for c in x)]
                midpoint = round(sum(nums)/len(nums), 2) if nums else trade.get("current_price", 0)
            except:
                midpoint = trade.get("current_price", 0)
        if midpoint <= 0:
            continue
        new_pos = {
            "ticker":           ticker,
            "entry_date":       today,
            "entry_price":      midpoint,
            "price_target":     trade.get("price_target", 0),
            "invalidation_price": trade.get("invalidation_price", 0),
            "bias":             trade.get("bias","Bullish"),
            "thesis":           trade.get("thesis",""),
            "source":           trade.get("source",""),
        }
        portfolio["open_positions"].append(new_pos)
        print("Opened position: " + ticker + " @ $" + str(midpoint))

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

    # Open positions
    op_html = ""
    if open_pos:
        op_html += "<div style='font-size:12px;font-weight:500;color:#333;margin-bottom:8px;'>Open positions ("+str(len(open_pos))+")</div>"
        for p in open_pos:
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
    else:
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
    swing   = get_swing_data(WATCHLIST, movers)
    analysis= generate_analysis(stocks,news,macro,swing,movers,sent,earn)

    # Portfolio tracking
    portfolio = load_portfolio()
    current_prices = {s["ticker"]: s["price"] for s in stocks}
    # Also add any swing trade tickers that were fetched
    for sw in swing:
        if sw.get("ticker") and sw.get("price"):
            current_prices[sw["ticker"]] = sw["price"]
    portfolio, closed_today = update_portfolio(portfolio, analysis.get("swing_trades",[]), current_prices)
    save_portfolio(portfolio)
    portfolio_html = build_portfolio_section(portfolio, closed_today)

    html    = build_email(stocks,news,macro,analysis,movers,sent,earn,portfolio_html)
    send_email(html)
    print("Done!")

main()
