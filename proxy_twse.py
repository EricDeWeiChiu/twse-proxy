# proxy_twse.py
import os
import time
from datetime import datetime

import requests
from flask import Flask, jsonify, request

app = Flask(__name__)

# ---- 基本設定 ----

MIS_TWSE_URL = (
    "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
    "?ex_ch=t00.tw|o00.tw&json=1&delay=0&_={ts}"
)

MIS_HEADERS = {
    "Referer": "https://mis.twse.com.tw/stock/index.jsp",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/javascript,*/*;q=0.01",
}

# 簡單快取，避免 proxy 自己打太兇
CACHE = {"ts": 0, "data": None}
CACHE_TTL = 5  # 秒

# 簡單保護用的 token（可選）
PROXY_TOKEN = os.environ.get("TWSE_PROXY_TOKEN", "my-secret-token")


def fetch_from_mis() -> dict:
    """實際呼叫 mis.twse，解析加權 t00 / 櫃買 o00"""

    url = MIS_TWSE_URL.format(ts=int(time.time() * 1000))
    resp = requests.get(url, headers=MIS_HEADERS, timeout=5)
    resp.raise_for_status()

    text = resp.text.strip()
    if not text:
        # mis.twse 可能封鎖或回空，直接回 raw 給客戶端看
        return {"taiex": None, "otc": None, "raw": "", "error": "empty_response"}

    data = resp.json()
    msg_array = data.get("msgArray", [])

    taiex_raw = None
    otc_raw = None
    for item in msg_array:
        if item.get("c") == "t00":
            taiex_raw = item
        elif item.get("c") == "o00":
            otc_raw = item

    def parse_item(raw):
        if not raw:
            return None

        def f(v, d=0.0):
            try:
                return float(v)
            except Exception:
                return d

        price = f(raw.get("z"))
        prev = f(raw.get("y"))
        change = price - prev if prev else 0.0
        percent = (change / prev * 100) if prev else 0.0

        volume = f(raw.get("v"))
        tlong = raw.get("tlong")

        if tlong:
            dt = datetime.fromtimestamp(int(tlong) / 1000)
            tstr = dt.strftime("%Y-%m-%d %H:%M:%S")
        else:
            t = raw.get("t", "")
            d = raw.get("d", "")
            tstr = f"{d} {t}".strip()

        return {
            "symbol": raw.get("c"),
            "name": raw.get("n"),
            "price": price,
            "change": change,
            "percent": percent,
            "volume": volume,
            "time": tstr,
        }

    return {
        "taiex": parse_item(taiex_raw),
        "otc": parse_item(otc_raw),
    }


@app.get("/twse/realtime")
def twse_realtime():
    """
    Proxy 端點：
      GET /twse/realtime?token=你的token

    回傳格式：
    {
      "taiex": { price, change, percent, volume, time, ... },
      "otc":   { ... },
      "from": "mis.twse.com.tw"
    }
    """
    token = request.args.get("token")
    if PROXY_TOKEN and token != PROXY_TOKEN:
        return jsonify({"error": "unauthorized"}), 401

    # 快取
    now = time.time()
    if CACHE["data"] is not None and now - CACHE["ts"] <= CACHE_TTL:
        return jsonify(CACHE["data"])

    try:
        data = fetch_from_mis()
        data["from"] = "mis.twse.com.tw"
        CACHE["ts"] = now
        CACHE["data"] = data
        return jsonify(data)
    except Exception as e:
        print("proxy twse_realtime error:", e)
        return jsonify({"taiex": None, "otc": None, "error": str(e)}), 500


if __name__ == "__main__":
    # 本機測試：python proxy_twse.py
    app.run(host="0.0.0.0", port=8000, debug=True)