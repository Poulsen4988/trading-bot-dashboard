"""
Udfører en handel via Saxo Bank API.
Brug: python trade.py <BUY|SELL> <UIC> <ANTAL>
Eksempel: python trade.py BUY 4913 10
"""
import json
import sys

import saxo_client as saxo


def place_order(account_key, client_key, buy_sell, uic, amount):
    order = {
        "AccountKey": account_key,
        "Amount": amount,
        "AssetType": "Stock",
        "BuySell": buy_sell,
        "OrderType": "Market",
        "Uic": uic,
        "ManualOrder": False,
    }
    result = saxo.post("/trade/v2/orders", order)
    return result


def get_account_keys():
    data = saxo.get("/port/v1/accounts/me")
    acc = data.get("Data", [{}])[0]
    return acc.get("AccountKey"), acc.get("ClientKey")


def main():
    if len(sys.argv) != 4:
        print("Brug: python trade.py <BUY|SELL> <UIC> <ANTAL>")
        sys.exit(1)

    buy_sell = sys.argv[1].upper()
    uic = int(sys.argv[2])
    amount = int(sys.argv[3])

    if buy_sell not in ("BUY", "SELL"):
        print("Fejl: første argument skal være BUY eller SELL")
        sys.exit(1)

    account_key, client_key = get_account_keys()
    result = place_order(account_key, client_key, buy_sell, uic, amount)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
