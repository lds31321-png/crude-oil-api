import os
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import uvicorn

app = FastAPI(title="OVX & WTI Analyzer", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def fetch_ticker(symbol: str, period: str) -> dict:
    ticker = yf.Ticker(symbol)
    hist = ticker.history(period=period)

    if hist.empty:
        return {"symbol": symbol, "error": "No data available"}

    hist.index = hist.index.tz_localize(None) if hist.index.tzinfo else hist.index

    latest = hist.iloc[-1]
    prev = hist.iloc[-2] if len(hist) > 1 else latest
    change = float(latest["Close"] - prev["Close"])
    change_pct = float(change / prev["Close"] * 100) if prev["Close"] != 0 else 0.0

    return {
        "symbol": symbol,
        "latest_close": round(float(latest["Close"]), 4),
        "previous_close": round(float(prev["Close"]), 4),
        "change": round(change, 4),
        "change_pct": round(change_pct, 4),
        "high": round(float(hist["High"].max()), 4),
        "low": round(float(hist["Low"].min()), 4),
        "mean": round(float(hist["Close"].mean()), 4),
        "std": round(float(hist["Close"].std()), 4),
        "data_points": len(hist),
        "start_date": hist.index[0].strftime("%Y-%m-%d"),
        "end_date": hist.index[-1].strftime("%Y-%m-%d"),
        "history": [
            {
                "date": idx.strftime("%Y-%m-%d"),
                "open": round(float(row["Open"]), 4),
                "high": round(float(row["High"]), 4),
                "low": round(float(row["Low"]), 4),
                "close": round(float(row["Close"]), 4),
                "volume": int(row["Volume"]),
            }
            for idx, row in hist.iterrows()
        ],
    }


@app.get("/")
def root():
    return {
        "service": "OVX & WTI Analyzer",
        "endpoints": {
            "/analyze": "OVX와 WTI 데이터 분석 (GET)",
            "/analyze?period=3mo": "기간 지정 가능 (1mo, 3mo, 6mo, 1y, 2y, 5y)",
        },
    }


@app.get("/analyze")
def analyze(
    period: str = Query(default="3mo", description="데이터 기간 (1mo, 3mo, 6mo, 1y, 2y, 5y)"),
    include_history: bool = Query(default=True, description="일별 가격 히스토리 포함 여부"),
):
    ovx = fetch_ticker("^OVX", period)
    wti = fetch_ticker("CL=F", period)

    correlation = None
    signal = None

    if "error" not in ovx and "error" not in wti:
        ovx_ticker = yf.Ticker("^OVX")
        wti_ticker = yf.Ticker("CL=F")
        ovx_hist = ovx_ticker.history(period=period)["Close"]
        wti_hist = wti_ticker.history(period=period)["Close"]

        ovx_hist.index = ovx_hist.index.tz_localize(None) if ovx_hist.index.tzinfo else ovx_hist.index
        wti_hist.index = wti_hist.index.tz_localize(None) if wti_hist.index.tzinfo else wti_hist.index

        combined = pd.DataFrame({"OVX": ovx_hist, "WTI": wti_hist}).dropna()
        if len(combined) > 1:
            correlation = round(float(combined["OVX"].corr(combined["WTI"])), 4)

        ovx_val = ovx["latest_close"]
        wti_chg = wti["change_pct"]

        if ovx_val > 45:
            volatility_level = "매우 높음"
        elif ovx_val > 35:
            volatility_level = "높음"
        elif ovx_val > 25:
            volatility_level = "보통"
        else:
            volatility_level = "낮음"

        if ovx_val > 40 and wti_chg < -1:
            signal = "⚠️ 고변동성 + WTI 하락: 원유 시장 불안 신호"
        elif ovx_val < 25 and wti_chg > 1:
            signal = "✅ 저변동성 + WTI 상승: 원유 시장 안정적 상승"
        elif ovx_val > 35:
            signal = "🔶 변동성 주의 구간: 리스크 관리 필요"
        else:
            signal = "🔵 시장 안정: 특이 신호 없음"

    else:
        volatility_level = None

    result = {
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "period": period,
        "ovx": ovx if include_history else {k: v for k, v in ovx.items() if k != "history"},
        "wti": wti if include_history else {k: v for k, v in wti.items() if k != "history"},
        "analysis": {
            "ovx_wti_correlation": correlation,
            "ovx_volatility_level": volatility_level,
            "signal": signal,
        },
    }

    return result


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), reload=False)
