import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import yfinance as yf
import numpy as np
import pandas as pd
from datetime import datetime
import uvicorn

app = FastAPI()
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

# ── 종목 설정 ──────────────────────────────────────────
ASSETS = {
    "원유": {
        "ticker": "CL=F",
        "vol_ticker": "^OVX",
        "name": "WTI 원유",
        "unit": "$",
        "emoji": "🛢",
    },
    "S&P": {
        "ticker": "ES=F",
        "vol_ticker": "^VIX",
        "name": "S&P500",
        "unit": "$",
        "emoji": "📈",
    },
    "sp": {
        "ticker": "ES=F",
        "vol_ticker": "^VIX",
        "name": "S&P500",
        "unit": "$",
        "emoji": "📈",
    },
    "골드": {
        "ticker": "GC=F",
        "vol_ticker": "^GVZ",
        "name": "골드",
        "unit": "$",
        "emoji": "🥇",
    },
    "금": {
        "ticker": "GC=F",
        "vol_ticker": "^GVZ",
        "name": "골드",
        "unit": "$",
        "emoji": "🥇",
    },
    "천연가스": {
        "ticker": "NG=F",
        "vol_ticker": "^OVX",
        "name": "천연가스",
        "unit": "$",
        "emoji": "⛽",
    },
    "대두": {
        "ticker": "ZS=F",
        "vol_ticker": "^OVX",
        "name": "대두",
        "unit": "$",
        "emoji": "🫘",
    },
    "호주달러": {
        "ticker": "AUDUSD=X",
        "vol_ticker": "^OVX",
        "name": "AUD/USD",
        "unit": "",
        "emoji": "🇦🇺",
    },
    "aud": {
        "ticker": "AUDUSD=X",
        "vol_ticker": "^OVX",
        "name": "AUD/USD",
        "unit": "",
        "emoji": "🇦🇺",
    },
    "국채": {
        "ticker": "ZN=F",
        "vol_ticker": "^MOVE",
        "name": "10년 국채",
        "unit": "$",
        "emoji": "📊",
    },
    "10년": {
        "ticker": "ZN=F",
        "vol_ticker": "^MOVE",
        "name": "10년 국채",
        "unit": "$",
        "emoji": "📊",
    },
}


def find_asset(asset_str: str):
    """입력 문자열에서 자산 찾기"""
    s = asset_str.strip().lower()
    for key, val in ASSETS.items():
        if key in s:
            return key, val
    return "원유", ASSETS["원유"]  # 기본값


def calc_hv(prices, window=30):
    log_ret = np.log(prices / prices.shift(1)).dropna()
    return round(float(log_ret.rolling(window).std().iloc[-1] * np.sqrt(252) * 100), 2)


def calc_iv_rank(series):
    cur = float(series.iloc[-1])
    lo, hi = float(series.min()), float(series.max())
    ivr = round((cur - lo) / (hi - lo) * 100, 1) if hi != lo else 50.0
    pct = round((series < cur).sum() / len(series) * 100, 1)
    return ivr, pct


def get_direction(series):
    slope = np.polyfit(range(5), series.iloc[-5:].values, 1)[0]
    return "상승" if slope > 0.2 else ("하락" if slope < -0.2 else "횡보")


def get_cp_ratio(ticker):
    try:
        t = yf.Ticker(ticker)
        exps = t.options
        if not exps:
            return 1.0
        chain = t.option_chain(exps[0])
        cv = chain.calls["volume"].fillna(0).sum()
        pv = chain.puts["volume"].fillna(0).sum()
        return round(float(cv / pv), 2) if pv > 0 else 1.0
    except:
        return 1.0


def ovx_5points(df, asset_name):
    """역사적 5개 포인트"""
    if hasattr(df.index, "tz") and df.index.tz is not None:
        df = df.copy()
        df.index = df.index.tz_localize(None)
    points = [
        ("21Q4", "2021-11-15"),
        ("22Q2", "2022-05-10"),
        ("22Q4", "2022-11-15"),
        ("23Q2", "2023-05-10"),
    ]
    result = []
    for label, date in points:
        try:
            ts = pd.Timestamp(date)
            idx = min(df.index.searchsorted(ts), len(df) - 1)
            val = round(float(df["Close"].iloc[idx]), 1)
        except:
            val = 0.0
        result.append({"label": label, "value": val})
    result.append({"label": "현재", "value": round(float(df["Close"].iloc[-1]), 1)})
    return result


def calc_score(iv_rank, iv_pct, hv_premium, ratio, direction, cp, option_type, ret5):
    s = iv_rank * 0.30 + iv_pct * 0.25
    s += min(max(hv_premium * 1.5, 0), 100) * 0.20
    s += min(max((ratio - 1.0) / 0.8 * 100, 0), 100) * 0.15
    if option_type == "콜":
        if ret5 > 5:
            s += 15
        elif ret5 > 2:
            s += 8
        elif ret5 < -2:
            s -= 8
        if cp > 1.5:
            s += 10
        elif cp > 1.2:
            s += 5
        elif cp < 0.8:
            s -= 10
        if direction == "상승":
            s += 5
    else:
        if ret5 < -5:
            s += 15
        elif ret5 < -2:
            s += 8
        elif ret5 > 2:
            s -= 8
        if cp < 0.7:
            s += 10
        elif cp < 0.85:
            s += 5
        elif cp > 1.3:
            s -= 10
        if direction == "하락":
            s += 5
    return int(min(max(round(s), 0), 100))


def calc_factors(iv_pct, hv_premium, vol_cur, cp, iv_rank, option_type, ret5):
    month = datetime.now().month
    geo_risk = min(int(vol_cur * 0.85), 100)
    supply_unc = min(int(iv_pct * 0.9), 100)
    if month in [5, 6, 7, 8]:
        seasonal = 75
    elif month in [11, 12, 1, 2]:
        seasonal = 70
    else:
        seasonal = 55
    dollar = min(int(iv_rank * 0.72), 100)
    if option_type == "콜":
        spec = min(int(cp * 50), 100)
        if ret5 > 3:
            spec = min(spec + 15, 100)
    else:
        spec = min(int((2.0 - min(cp, 2.0)) * 50), 100)
        if ret5 < -3:
            spec = min(spec + 15, 100)
    return [
        {"name": "지정학 리스크", "pct": geo_risk},
        {"name": "공급 불확실성", "pct": supply_unc},
        {"name": "계절적 수요", "pct": seasonal},
        {"name": "달러 강세", "pct": dollar},
        {"name": "투기 포지션", "pct": spec},
    ]


@app.get("/analyze")
async def analyze(option_type: str = "콜", asset: str = "원유"):
    try:
        # 자산 찾기
        asset_key, asset_info = find_asset(asset)
        ticker = asset_info["ticker"]
        vol_ticker = asset_info["vol_ticker"]
        asset_name = asset_info["name"]
        emoji = asset_info["emoji"]

        # 변동성 지수 데이터
        vol_df = yf.Ticker(vol_ticker).history(period="5y")
        vol_1y = vol_df["Close"].iloc[-252:]
        vol_cur = round(float(vol_df["Close"].iloc[-1]), 2)

        # 기초자산 데이터
        price_df = yf.Ticker(ticker).history(period="1y")
        price_cur = round(float(price_df["Close"].iloc[-1]), 2)
        ret5 = (
            round(
                (price_df["Close"].iloc[-1] / price_df["Close"].iloc[-6] - 1) * 100, 2
            )
            if len(price_df) > 6
            else 0.0
        )
        ret20 = (
            round(
                (price_df["Close"].iloc[-1] / price_df["Close"].iloc[-22] - 1) * 100, 2
            )
            if len(price_df) > 22
            else 0.0
        )

        hv = calc_hv(price_df["Close"])
        iv_rank, iv_pct = calc_iv_rank(vol_1y)
        direction = get_direction(vol_1y)
        hv_premium = round(vol_cur - hv, 2)
        ratio = round(vol_cur / hv, 2) if hv > 0 else 1.0
        cp = get_cp_ratio(ticker)

        score = calc_score(
            iv_rank, iv_pct, hv_premium, ratio, direction, cp, option_type, ret5
        )
        verdict = "고평가" if score >= 70 else ("적정" if score >= 40 else "저평가")
        opt_label = (
            f"{option_type}(Call)" if option_type == "콜" else f"{option_type}(Put)"
        )
        factors = calc_factors(
            iv_pct, hv_premium, vol_cur, cp, iv_rank, option_type, ret5
        )

        if option_type == "콜":
            comm = [
                f"현재 {asset_name} 가격은 {asset_info['unit']}{price_cur}이며 5일 수익률 {ret5:+.2f}%, 변동성 지수는 {vol_cur}입니다.",
                f"내재변동성(IV) {vol_cur}이 역사적 변동성(HV) {hv} 대비 {hv_premium}포인트 프리미엄으로 거래되고 있습니다. {'상승' if ret5 > 0 else '하락'} 추세에서 콜 옵션 수요가 {'증가' if ret5 > 2 else '보통'}하고 있습니다.",
                f"IV Rank {iv_rank}, IV 백분위 {iv_pct}%로 {verdict} 수준입니다. 콜/풋 비율 {cp}로 {'콜 수요 우세' if cp > 1 else '풋 수요 우세'}한 상황이며 콜 프리미엄 고평가 점수는 {score}점입니다.",
            ]
        else:
            comm = [
                f"현재 {asset_name} 가격은 {asset_info['unit']}{price_cur}이며 5일 수익률 {ret5:+.2f}%, 변동성 지수는 {vol_cur}입니다.",
                f"내재변동성(IV) {vol_cur}이 역사적 변동성(HV) {hv} 대비 {hv_premium}포인트 프리미엄으로 거래되고 있습니다. {'하락' if ret5 < 0 else '상승'} 추세에서 풋 옵션 수요가 {'증가' if ret5 < -2 else '보통'}하고 있습니다.",
                f"IV Rank {iv_rank}, IV 백분위 {iv_pct}%로 {verdict} 수준입니다. 콜/풋 비율 {cp}로 {'풋 수요 우세' if cp < 1 else '콜 수요 우세'}한 상황이며 풋 프리미엄 고평가 점수는 {score}점입니다.",
            ]

        return {
            "score": score,
            "verdict": verdict,
            "option_type": opt_label,
            "asset_name": asset_name,
            "emoji": emoji,
            "price": price_cur,
            "price_unit": asset_info["unit"],
            "ret5": ret5,
            "ret20": ret20,
            "vol_current": vol_cur,
            "vol_ticker": vol_ticker,
            "iv_rank": iv_rank,
            "iv_percentile": f"{iv_pct}%",
            "iv_direction": direction,
            "hv": hv,
            "hv_discount": hv_premium,
            "iv_hv_ratio": ratio,
            "call_put_ratio": cp,
            "factors": factors,
            "ovx_history": ovx_5points(vol_df, asset_name),
            "alert_message": f"현재 {asset_name} {option_type} 옵션 IV({vol_cur})가 HV({hv})보다 {hv_premium}포인트 높습니다. {option_type} 프리미엄 고평가 점수 {score}점으로 {verdict} 구간입니다.",
            "commentary_title": f"{asset_name} {option_type}옵션 {verdict} 분석",
            "commentary": comm,
            "data_source": "Yahoo Finance — 약 15~20분 지연 데이터",
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M KST"),
        }
    except Exception as e:
        return {"error": str(e)}


if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def root():
    if os.path.exists("static/index.html"):
        return FileResponse("static/index.html")
    return {"status": "ok"}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
