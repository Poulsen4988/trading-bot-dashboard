import os,sys,json
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
res={"python":sys.version.split()[0]}
for m in ["yfinance","pandas","numpy","ta","requests"]:
    try:
        mod=__import__(m); res[m]=getattr(mod,"__version__","ok")
    except Exception as e: res[m]="MISSING:"+e.__class__.__name__
try: res["ls_root"]=sorted([x for x in os.listdir(".")])[:50]
except Exception as e: res["ls_root"]=str(e)
import github_store
github_store.put_json("us/_envcheck.json",res,"env check")
print(json.dumps(res))
