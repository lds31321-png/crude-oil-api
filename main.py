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
    """OVX 역사적 5개 포인트 - 타임존 문제 수정"""
    # 타임존 제거
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
            # 해당 날짜에 가장 가까운 인덱스 찾기
            idx = df.index.searchsorted(ts)
            idx = min(idx, len(df) - 1)
            val = round(float(df["Close"].iloc[idx]), 1)
        except Exception:
            val = 0.0
        result.append({"label": label, "value": val})
    result.append({"label": "현재", "value": round(float(df["Close"].iloc[-1]), 1)})
    return result


def calc_score(
    iv_rank, iv_pct, hv_premium, ratio, direction, cp, option_type, wti_ret5
):
    """
    고평가 점수 계산 (매도자 관점)
    - 기본 점수: IV가 높을수록, HV 대비 프리미엄이 클수록 고평가
    - 콜 조정: WTI 상승 + CP비율 높을수록 콜 고평가
    - 풋 조정: WTI 하락 + CP비율 낮을수록 풋 고평가
    """
    # 기본 고평가 점수 (IV vs HV 관점)
    s = iv_rank * 0.30 + iv_pct * 0.25
    s += min(max(hv_premium * 1.5, 0), 100) * 0.20
    s += min(max((ratio - 1.0) / 0.8 * 100, 0), 100) * 0.15

    if option_type == "콜":
        # 콜: WTI 상승 중일수록 콜 수요 증가 → 콜 프리미엄 고평가
        if wti_ret5 > 5:
            s += 15  # WTI 강한 상승 → 콜 고평가
        elif wti_ret5 > 2:
            s += 8
        elif wti_ret5 < -2:
            s -= 8
        # CP비율 높을수록 콜 수요 강세 → 콜 고평가
        if cp > 1.5:
            s += 10
        elif cp > 1.2:
            s += 5
        elif cp < 0.8:
            s -= 10
        # IV 상승 중이면 콜 프리미엄 더 비싸짐
        if direction == "상승":
            s += 5

    else:  # 풋
        # 풋: WTI 하락 중일수록 풋 수요 증가 → 풋 프리미엄 고평가
        if wti_ret5 < -5:
            s += 15  # WTI 강한 하락 → 풋 고평가
        elif wti_ret5 < -2:
            s += 8
        elif wti_ret5 > 2:
            s -= 8
        # CP비율 낮을수록 풋 수요 강세 → 풋 고평가
        if cp < 0.7:
            s += 10
        elif cp < 0.85:
            s += 5
        elif cp > 1.3:
            s -= 10
        if direction == "하락":
            s += 5

    return int(min(max(round(s), 0), 100))


def calc_factors(iv_pct, hv_premium, ovx_cur, cp, iv_rank, option_type, wti_ret5):
    """거시경제 요인 포함 고평가 요인 계산"""
    month = datetime.now().month

    # 지정학 리스크: OVX 수준 기반
    geo_risk = min(int(ovx_cur * 0.85), 100)

    # 공급 불확실성: IV 백분위 기반
    supply_unc = min(int(iv_pct * 0.9), 100)

    # 계절적 수요: 드라이빙 시즌(5~8월), 겨난(11~2월) 높음
    if month in [5, 6, 7, 8]:
        seasonal = 75
    elif month in [11, 12, 1, 2]:
        seasonal = 70
    else:
        seasonal = 55

    # 달러 강세 압력: IVR 기반
    dollar = min(int(iv_rank * 0.72), 100)

    # 투기 포지션: 옵션 종류별 CP비율 반영
    if option_type == "콜":
        spec = min(int(cp * 50), 100)
        # WTI 상승 시 투기 콜 포지션 증가
        if wti_ret5 > 3:
            spec = min(spec + 15, 100)
    else:
        spec = min(int((2.0 - min(cp, 2.0)) * 50), 100)
        if wti_ret5 < -3:
            spec = min(spec + 15, 100)

    return [
        {"name": "지정학 리스크", "pct": geo_risk},
        {"name": "공급 불확실성", "pct": supply_unc},
        {"name": "계절적 수요", "pct": seasonal},
        {"name": "달러 강세", "pct": dollar},
        {"name": "투기 포지션", "pct": spec},
    ]


@app.get("/analyze")
async def analyze(option_type: str = "콜"):
    try:
        ovx_df = yf.Ticker("^OVX").history(period="5y")
        ovx_1y = ovx_df["Close"].iloc[-252:]
        ovx_cur = round(float(ovx_df["Close"].iloc[-1]), 2)

        wti_df = yf.Ticker("CL=F").history(period="1y")
        wti_cur = round(float(wti_df["Close"].iloc[-1]), 2)

        # WTI 5일/20일 수익률
        wti_ret5 = (
            round((wti_df["Close"].iloc[-1] / wti_df["Close"].iloc[-6] - 1) * 100, 2)
            if len(wti_df) > 6
            else 0.0
        )
        wti_ret20 = (
            round((wti_df["Close"].iloc[-1] / wti_df["Close"].iloc[-22] - 1) * 100, 2)
            if len(wti_df) > 22
            else 0.0
        )

        hv = calc_hv(wti_df["Close"])
        iv_rank, iv_pct = calc_iv_rank(ovx_1y)
        direction = get_direction(ovx_1y)
        hv_premium = round(ovx_cur - hv, 2)
        ratio = round(ovx_cur / hv, 2) if hv > 0 else 1.0
        cp = get_cp_ratio()

        score = calc_score(
            iv_rank, iv_pct, hv_premium, ratio, direction, cp, option_type, wti_ret5
        )
        verdict = "고평가" if score >= 70 else ("적정" if score >= 40 else "저평가")
        opt_label = (
            f"{option_type}(Call)" if option_type == "콜" else f"{option_type}(Put)"
        )
        factors = calc_factors(
            iv_pct, hv_premium, ovx_cur, cp, iv_rank, option_type, wti_ret5
        )

        # 콜/풋별 분석 코멘터리
        if option_type == "콜":
            comm = [
                f"현재 WTI 원유 선물 가격은 ${wti_cur}이며 5일 수익률 {wti_ret5:+.2f}%, OVX(원유 변동성 지수)는 {ovx_cur}입니다.",
                f"내재변동성(IV) {ovx_cur}이 역사적 변동성(HV) {hv} 대비 {hv_premium}포인트 프리미엄으로 거래되고 있습니다. WTI {'상승' if wti_ret5 > 0 else '하락'} 추세에서 콜 옵션 수요가 {'증가' if wti_ret5 > 2 else '보통'}하고 있습니다.",
                f"IV Rank {iv_rank}, IV 백분위 {iv_pct}%로 {verdict} 수준입니다. 콜/풋 비율 {cp}로 {'콜 수요 우세' if cp > 1 else '풋 수요 우세'}한 상황이며 콜 프리미엄 고평가 점수는 {score}점입니다.",
            ]
        else:
            comm = [
                f"현재 WTI 원유 선물 가격은 ${wti_cur}이며 5일 수익률 {wti_ret5:+.2f}%, OVX(원유 변동성 지수)는 {ovx_cur}입니다.",
                f"내재변동성(IV) {ovx_cur}이 역사적 변동성(HV) {hv} 대비 {hv_premium}포인트 프리미엄으로 거래되고 있습니다. WTI {'하락' if wti_ret5 < 0 else '상승'} 추세에서 풋 옵션 수요가 {'증가' if wti_ret5 < -2 else '보통'}하고 있습니다.",
                f"IV Rank {iv_rank}, IV 백분위 {iv_pct}%로 {verdict} 수준입니다. 콜/풋 비율 {cp}로 {'풋 수요 우세' if cp < 1 else '콜 수요 우세'}한 상황이며 풋 프리미엄 고평가 점수는 {score}점입니다.",
            ]

        return {
            "score": score,
            "verdict": verdict,
            "option_type": opt_label,
            "wti_price": wti_cur,
            "wti_ret5": wti_ret5,
            "wti_ret20": wti_ret20,
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
            "alert_message": f"현재 원유 {option_type} 옵션 IV({ovx_cur})가 HV({hv})보다 {hv_premium}포인트 높습니다. WTI 5일 수익률 {wti_ret5:+.2f}% 반영 시 {option_type} 프리미엄 고평가 점수 {score}점으로 {verdict} 구간입니다.",
            "commentary_title": f"원유 {option_type}옵션 {verdict} 분석",
            "commentary": comm,
            "data_source": "Yahoo Finance — 약 15분 지연 데이터",
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
