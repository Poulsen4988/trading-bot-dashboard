"""
Eneste sted at definere C25-watchlisten.
Importeres af news.py, nasdaq_news.py og scripts/fetch_prices.py.

uic:    Saxo Bank UIC-kode. None = ikke opsat endnu.
nasdaq: Søgenøgle (lowercase) til match mod Nasdaq Copenhagen-feedets
        company-felt i nasdaq_news.py. None = ingen dansk meddelelseskilde.
"""

C25 = [
    {"yf": "NOVO-B.CO",   "saxo": "NOVOb:xcse",    "uic": 15629, "name": "Novo Nordisk B",          "nasdaq": "novo nordisk"},
    {"yf": "MAERSK-B.CO", "saxo": "MAERSKb:xcse",  "uic": 6041,  "name": "A.P. Møller-Mærsk B",     "nasdaq": "mærsk"},
    {"yf": "MAERSK-A.CO", "saxo": "MAERSKa:xcse",  "uic": None,  "name": "A.P. Møller-Mærsk A",     "nasdaq": "mærsk"},
    {"yf": "DSV.CO",      "saxo": "DSV:xcse",      "uic": 3955,  "name": "DSV",                     "nasdaq": "dsv a/s"},
    {"yf": "ORSTED.CO",   "saxo": "ORSTED:xcse",   "uic": None,  "name": "Ørsted",                  "nasdaq": "ørsted"},
    {"yf": "CARL-B.CO",   "saxo": "CARLb:xcse",    "uic": None,  "name": "Carlsberg B",             "nasdaq": "carlsberg a/s"},
    {"yf": "PNDORA.CO",   "saxo": "PNDORA:xcse",   "uic": None,  "name": "Pandora",                 "nasdaq": "pandora a/s"},
    {"yf": "TRYG.CO",     "saxo": "TRYG:xcse",     "uic": None,  "name": "Tryg",                    "nasdaq": "tryg a/s"},
    {"yf": "COLO-B.CO",   "saxo": "COLOb:xcse",    "uic": None,  "name": "Coloplast B",             "nasdaq": "coloplast a/s"},
    {"yf": "GMAB.CO",     "saxo": "GMAB:xcse",     "uic": None,  "name": "Genmab",                  "nasdaq": "genmab"},
    {"yf": "GN.CO",       "saxo": "GN:xcse",       "uic": None,  "name": "GN Store Nord",           "nasdaq": "gn store nord"},
    {"yf": "DEMANT.CO",   "saxo": "DEMANT:xcse",   "uic": None,  "name": "Demant",                  "nasdaq": "demant a/s"},
    {"yf": "RBREW.CO",    "saxo": "RBREW:xcse",    "uic": None,  "name": "Royal Unibrew",           "nasdaq": "unibrew"},
    {"yf": "NDA-DK.CO",   "saxo": "NDA-DK:xcse",   "uic": None,  "name": "Nordea Bank",             "nasdaq": None},
    {"yf": "DANSKE.CO",   "saxo": "DANSKE:xcse",   "uic": None,  "name": "Danske Bank",             "nasdaq": "danske bank a/s"},
    {"yf": "FLS.CO",      "saxo": "FLS:xcse",      "uic": None,  "name": "FLSmidth",                "nasdaq": "flsmidth"},
    {"yf": "VWS.CO",      "saxo": "VWS:xcse",      "uic": None,  "name": "Vestas Wind Systems",     "nasdaq": "vestas"},
    {"yf": "AMBU-B.CO",   "saxo": "AMBUb:xcse",    "uic": None,  "name": "Ambu B",                  "nasdaq": "ambu a/s"},
    {"yf": "NSIS-B.CO",   "saxo": "NSISb:xcse",    "uic": None,  "name": "Novonesis B",             "nasdaq": "novonesis"},
    {"yf": "ROCK-B.CO",   "saxo": "ROCKb:xcse",    "uic": None,  "name": "Rockwool B",              "nasdaq": "rockwool a/s"},
    {"yf": "BAVA.CO",     "saxo": "BAVA:xcse",     "uic": None,  "name": "Bavarian Nordic",         "nasdaq": "bavarian nordic"},
    {"yf": "JYSK.CO",     "saxo": "JYSK:xcse",     "uic": None,  "name": "Jyske Bank",              "nasdaq": "jyske bank a/s"},
    {"yf": "ISS.CO",      "saxo": "ISS:xcse",      "uic": None,  "name": "ISS",                     "nasdaq": "iss a/s"},
    {"yf": "ALSYDB.CO",   "saxo": "SYDB:xcse",     "uic": None,  "name": "Sydbank",                 "nasdaq": "sydbank"},
    {"yf": "NNIT.CO",     "saxo": "NNIT:xcse",     "uic": None,  "name": "NNIT",                    "nasdaq": "nnit a/s"},
]

# Bagudkompatibel liste til eksisterende kode — kun aktier med kendte UICs
WATCHLIST = [
    {"symbol": s["saxo"], "name": s["name"], "uic": s["uic"]}
    for s in C25 if s["uic"] is not None
]

# Simple (yf_ticker, name) tuples used by screener.py
STOCKS = [(s["yf"], s["name"]) for s in C25]
