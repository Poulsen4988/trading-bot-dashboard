"""
Eneste sted at definere C25-watchlisten.
Importeres af screener.py, research.py, news.py og scripts/fetch_prices.py.

uic: Saxo Bank UIC-kode. None = ikke opsat endnu (kan researches men ikke handles).
"""

C25 = [
    {"yf": "NOVO-B.CO",   "saxo": "NOVOb:xcse",   "uic": 15629, "name": "Novo Nordisk B"},
    {"yf": "MAERSK-B.CO", "saxo": "MAERSKb:xcse",  "uic": 6041,  "name": "A.P. Møller-Mærsk B"},
    {"yf": "MAERSK-A.CO", "saxo": "MAERSKa:xcse",  "uic": None,  "name": "A.P. Møller-Mærsk A"},
    {"yf": "DSV.CO",      "saxo": "DSV:xcse",       "uic": 3955,  "name": "DSV"},
    {"yf": "ORSTED.CO",   "saxo": "ORSTED:xcse",    "uic": None,  "name": "Ørsted"},
    {"yf": "CARL-B.CO",   "saxo": "CARLb:xcse",     "uic": None,  "name": "Carlsberg B"},
    {"yf": "PNDORA.CO",   "saxo": "PNDORA:xcse",    "uic": None,  "name": "Pandora"},
    {"yf": "TRYG.CO",     "saxo": "TRYG:xcse",      "uic": None,  "name": "Tryg"},
    {"yf": "COLO-B.CO",   "saxo": "COLOb:xcse",     "uic": None,  "name": "Coloplast B"},
    {"yf": "GMAB.CO",     "saxo": "GMAB:xcse",      "uic": None,  "name": "Genmab"},
    {"yf": "GN.CO",       "saxo": "GN:xcse",        "uic": None,  "name": "GN Store Nord"},
    {"yf": "DEMANT.CO",   "saxo": "DEMANT:xcse",    "uic": None,  "name": "Demant"},
    {"yf": "RBREW.CO",    "saxo": "RBREW:xcse",     "uic": None,  "name": "Royal Unibrew"},
    {"yf": "NDA-DK.CO",   "saxo": "NDA-DK:xcse",    "uic": None,  "name": "Nordea Bank"},
    {"yf": "FLS.CO",      "saxo": "FLS:xcse",       "uic": None,  "name": "FLSmidth"},
    {"yf": "VWS.CO",      "saxo": "VWS:xcse",       "uic": None,  "name": "Vestas Wind Systems"},
    {"yf": "AMBU-B.CO",   "saxo": "AMBUb:xcse",     "uic": None,  "name": "Ambu B"},
    {"yf": "NSIS-B.CO",   "saxo": "NSISb:xcse",     "uic": None,  "name": "Novonesis B"},
    {"yf": "ROCK-B.CO",   "saxo": "ROCKb:xcse",     "uic": None,  "name": "Rockwool B"},
    {"yf": "BAVA.CO",     "saxo": "BAVA:xcse",      "uic": None,  "name": "Bavarian Nordic"},
    {"yf": "JYSK.CO",     "saxo": "JYSK:xcse",      "uic": None,  "name": "Jyske Bank"},
    {"yf": "ISS.CO",      "saxo": "ISS:xcse",       "uic": None,  "name": "ISS"},
    {"yf": "SYDB.CO",     "saxo": "SYDB:xcse",      "uic": None,  "name": "Sydbank"},
    {"yf": "NNIT.CO",     "saxo": "NNIT:xcse",      "uic": None,  "name": "NNIT"},
    {"yf": "CHR.CO",      "saxo": "CHR:xcse",       "uic": None,  "name": "Chr. Hansen"},
]

# Bagudkompatibel liste til eksisterende kode — kun aktier med kendte UICs
WATCHLIST = [
    {"symbol": s["saxo"], "name": s["name"], "uic": s["uic"]}
    for s in C25 if s["uic"] is not None
]

# Simple (yf_ticker, name) tuples used by screener.py
STOCKS = [(s["yf"], s["name"]) for s in C25]
