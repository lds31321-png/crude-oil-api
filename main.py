import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import numpy as np
import pandas as pd
from datetime import datetime
import uvicorn

app = FastAPI()
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


def calc_hv(prices, window=30):
    log_ret = np.log(prices / prices.shift(1)).dropna()
    return round(float(log_ret.rolling(window).std().iloc[-1] * np.sqrt(252) * 100), 2)


def calc_iv_rank(series):
    cur = float(series.iloc[-1])
    iv_rank = round(
        (cur - float(series.min())) / (float(series.max()) - float(series.min())) * 100,
        1,
    )
    iv_pct = round((series < cur).sum() / len(series) * 100, 1)
    return iv_rank, iv_pct


def get_direction(series):
    slope = np.polyfit(range(5), series.iloc[-5:].values, 1)[0]
    return "상승" if slope > 0.2 else ("하락" if slope < -0.2 else "횡보")


def get_cp_ratio():
    try:
        t = yf.Ticker("CL=F")
        exps = t.options
        if not exps:
            return 1.0
        chain = t.option_chain(exps[0])
        cv = chain.calls["volume"].fillna(0).sum()
        pv = chain.puts["volume"].fillna(0).sum()
        return round(float(cv / pv), 2) if pv > 0 else 1.0
    except:
        return 1.0


def ovx_5points(df):
    points = [
        ("21Q4", "2021-11-01"),
        ("22Q2", "2022-05-01"),
        ("22Q4", "2022-11-01"),
        ("23Q2", "2023-05-01"),
    ]
    result = []
    for label, date in points:
        try:
            idx = df.index.searchsorted(pd.Timestamp(date, tz="America/New_York"))
            val = round(float(df["Close"].iloc[min(idx, len(df) - 1)]), 1)
        except:
            val = 0.0
        result.append({"label": label, "value": val})
    result.append({"label": "현재", "value": round(float(df["Close"].iloc[-1]), 1)})
    return result


def calc_score(iv_rank, iv_pct, hv_premium, ratio, direction):
    s = iv_rank * 0.30 + iv_pct * 0.25 + min(max(hv_premium * 2, 0), 100) * 0.20
    s += min(max((ratio - 1.0) / 0.8 * 100, 0), 100) * 0.15
    if direction == "상승":
        s += 10
    elif direction == "하락":
        s -= 5
    return int(min(max(round(s), 0), 100))


@app.get("/analyze")
async def analyze(option_type: str = "콜"):
    try:
        ovx_df = yf.Ticker("^OVX").history(period="2y")
        ovx_1y = ovx_df["Close"].iloc[-252:]
        ovx_cur = round(float(ovx_df["Close"].iloc[-1]), 2)
        wti_df = yf.Ticker("CL=F").history(period="1y")
        wti_cur = round(float(wti_df["Close"].iloc[-1]), 2)
        hv = calc_hv(wti_df["Close"])
        iv_rank, iv_pct = calc_iv_rank(ovx_1y)
        direction = get_direction(ovx_1y)
        hv_premium = round(ovx_cur - hv, 2)
        ratio = round(ovx_cur / hv, 2) if hv > 0 else 1.0
        cp = get_cp_ratio()
        score = calc_score(iv_rank, iv_pct, hv_premium, ratio, direction)
        verdict = "고평가" if score >= 70 else ("적정" if score >= 40 else "저평가")
        opt_label = (
            f"{option_type}(Call)" if option_type == "콜" else f"{option_type}(Put)"
        )
        factors = [
            {"name": "IV 퍼센타일", "pct": int(iv_pct)},
            {"name": "IV/HV 프리미엄", "pct": min(int(hv_premium * 3), 100)},
            {"name": "시장 불안도", "pct": min(int(ovx_cur * 1.2), 100)},
            {"name": "콜수요 집중", "pct": min(int(cp * 40), 100)},
            {"name": "변동성 순위", "pct": min(int(iv_rank * 0.8), 100)},
        ]
        return {
            "score": score,
            "verdict": verdict,
            "option_type": opt_label,
            "wti_price": wti_cur,
            "ovx_current": ovx_cur,
            "iv_rank": iv_rank,
            "iv_percentile": f"{iv_pct}%",
            "iv_direction": direction,
            "hv": hv,
            "hv_discount": hv_premium,
            "iv_hv_ratio": ratio,
            "call_put_ratio": cp,
            "factors": factors,
            "ovx_history": ovx_5points(ovx_df),
            "alert_message": f"현재 원유 {option_type} 옵션 IV({ovx_cur})가 HV({hv})보다 {hv_premium}포인트 높습니다. 종합 고평가 점수 {score}점으로 {verdict} 구간입니다.",
            "commentary_title": f"원유 {option_type}옵션 {verdict} 분석",
            "commentary": [
                f"현재 WTI 원유 선물 가격은 ${wti_cur}이며 OVX(원유 변동성 지수)는 {ovx_cur}입니다.",
                f"내재변동성(IV) {ovx_cur}이 역사적 변동성(HV) {hv} 대비 {hv_premium}포인트 프리미엄으로 거래되고 있습니다.",
                f"IV Rank {iv_rank}, IV 백분위 {iv_pct}%로 {verdict} 수준이며 콜/풋 비율은 {cp}입니다.",
            ],
            "data_source": "Yahoo Finance — 약 15분 지연 데이터",
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M KST"),
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/")
async def root():
    return {"status": "ok"}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
