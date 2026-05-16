import yfinance as yf, json
t = yf.Ticker("DSV.CO")
print(json.dumps(t.news[0] if t.news else {}, indent=2, ensure_ascii=False))
