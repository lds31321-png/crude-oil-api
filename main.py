import os
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import yfinance as yf
import numpy as np
import pandas as pd
from datetime import datetime
import uvicorn

app = FastAPI(title="원유 옵션 분석 API")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


def clean_index(series):
    if series.index.tzinfo is not None:
        series.index = series.index.tz_localize(None)
    return series


def calc_hv(prices, window=21):
    log_ret = np.log(prices / prices.shift(1)).dropna()
    hv = log_ret.rolling(window).std().iloc[-1] * np.sqrt(252) * 100
    return round(float(hv), 2)


def calc_ivr_and_pct(series):
    cur = float(series.iloc[-1])
    lo, hi = float(series.min()), float(series.max())
    ivr = round((cur - lo) / (hi - lo) * 100, 1) if hi != lo else 50.0
    pct = round((series < cur).sum() / len(series) * 100, 1)
    return ivr, pct


def get_iv_direction(series):
    slope = np.polyfit(range(10), series.iloc[-10:].values, 1)[0]
    if slope > 0.3:
        return "상승", round(float(slope), 2)
    elif slope < -0.3:
        return "하락", round(float(slope), 2)
    return "횡보", round(float(slope), 2)


def calc_wti_momentum(prices):
    if len(prices) < 22:
        return 0.0, 0.0
    ret5 = (prices.iloc[-1] / prices.iloc[-6] - 1) * 100
    ret20 = (prices.iloc[-1] / prices.iloc[-22] - 1) * 100
    return round(float(ret5), 2), round(float(ret20), 2)


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
    except Exception:
        return 1.0


def calc_score(option_type, iv_rank, iv_pct, hv_premium, hv_iv_ratio,
               iv_direction, wti_ret5, cp_ratio):
    if option_type == "콜":
        s = (100 - iv_rank) * 0.25
        s += (100 - iv_pct) * 0.20
        s += max(0, min(100, 50 - hv_premium * 1.5)) * 0.20
        s += max(0, min(100, 50 + wti_ret5 * 5)) * 0.20
        s += (15 if iv_direction == "하락" else (-10 if iv_direction == "상승" else 0))
        s += max(0, min(15, (cp_ratio - 0.8) * 20))
    else:
        s = iv_rank * 0.25
        s += iv_pct * 0.20
        s += max(0, min(100, 50 + hv_premium * 1.5)) * 0.20
        s += max(0, min(100, 50 - wti_ret5 * 5)) * 0.20
        s += (15 if iv_direction == "상승" else (-10 if iv_direction == "하락" else 0))
        s += max(0, min(15, (1 / cp_ratio - 0.8) * 20)) if cp_ratio > 0 else 0
    return int(min(max(round(s), 0), 100))


def build_factors(option_type, iv_rank, iv_pct, hv_premium, wti_ret5, ovx_cur, cp_ratio):
    if option_type == "콜":
        return [
            {"name": "IV 저평가 지수",  "pct": int(min(max(100 - iv_rank, 0), 100))},
            {"name": "IV 백분위 역방향", "pct": int(min(max(100 - iv_pct, 0), 100))},
            {"name": "HV 대비 저가",    "pct": int(min(max(50 - hv_premium * 1.5, 0), 100))},
            {"name": "WTI 상승 모멘텀", "pct": int(min(max(50 + wti_ret5 * 5, 0), 100))},
            {"name": "콜 수요 압력",    "pct": int(min(max(cp_ratio * 40, 0), 100))},
        ]
    else:
        return [
            {"name": "IV 고평가 지수",  "pct": int(min(max(iv_rank, 0), 100))},
            {"name": "IV 백분위",       "pct": int(min(max(iv_pct, 0), 100))},
            {"name": "HV 대비 프리미엄","pct": int(min(max(50 + hv_premium * 1.5, 0), 100))},
            {"name": "WTI 하락 모멘텀", "pct": int(min(max(50 - wti_ret5 * 5, 0), 100))},
            {"name": "풋 수요 압력",    "pct": int(min(max((1/cp_ratio if cp_ratio>0 else 1)*40, 0), 100))},
        ]


def get_ovx_history(df, days=90):
    hist = clean_index(df["Close"].copy()).tail(days)
    result = []
    for idx, val in hist.items():
        date = str(idx)[:10]
        result.append({"date": date, "value": round(float(val), 2)})
    return result


def build_commentary(option_type, iv_rank, iv_pct, iv_direction, hv_premium,
                     hv_iv_ratio, wti_cur, ovx_cur, hv, cp_ratio, score):
    verdict = "매우 유리" if score >= 70 else ("유리" if score >= 55 else ("보통" if score >= 40 else ("불리" if score >= 25 else "매우 불리")))
    opt_label = "콜(Call)" if option_type == "콜" else "풋(Put)"

    lines = [
        f"현재 WTI 원유 선물가는 <b style='color:#f0a050'>${wti_cur}</b>이며, "
        f"OVX 원유 변동성 지수는 <b style='color:#f0a050'>{ovx_cur}</b>입니다.",
    ]

    if option_type == "콜":
        if iv_rank < 30:
            lines.append(f"IV Rank {iv_rank}로 낮은 구간입니다. 역사적 저점 수준의 <b>저렴한 옵션 프리미엄</b>으로 콜 매수가 유리합니다.")
        elif iv_rank < 60:
            lines.append(f"IV Rank {iv_rank}으로 중간 수준입니다. 콜 매수 시 변동성 확대 여부를 확인하세요.")
        else:
            lines.append(f"IV Rank {iv_rank}로 높은 구간입니다. 콜 옵션 프리미엄이 비싸 매수 시 불리한 환경입니다.")
        if iv_direction == "하락":
            lines.append(f"IV가 <b style='color:#30c070'>하락 추세</b>입니다. 베가 리스크가 줄어들어 콜 매수에 유리합니다.")
        elif iv_direction == "상승":
            lines.append(f"IV가 <b style='color:#ff4a30'>상승 추세</b>입니다. 프리미엄 비용이 증가할 수 있어 주의가 필요합니다.")
        if hv_premium < 0:
            lines.append(f"현재 IV({ovx_cur})가 HV({hv})보다 낮아 옵션이 <b style='color:#30c070'>공정가 이하</b>에 거래되고 있습니다.")
        else:
            lines.append(f"IV({ovx_cur})가 HV({hv})보다 {hv_premium}pt 높아 옵션이 <b style='color:#ff4a30'>고평가</b> 상태입니다.")
    else:
        if iv_rank > 70:
            lines.append(f"IV Rank {iv_rank}로 높은 변동성 구간입니다. 풋 옵션이 비싸지만 <b>시장 불안이 반영된 환경</b>입니다.")
        elif iv_rank > 40:
            lines.append(f"IV Rank {iv_rank}으로 중간 수준입니다. 적정 가격의 풋 옵션 매수 구간입니다.")
        else:
            lines.append(f"IV Rank {iv_rank}로 낮은 구간입니다. 풋 옵션 프리미엄이 저렴하나 변동성 확대 촉매가 필요합니다.")
        if iv_direction == "상승":
            lines.append(f"IV가 <b style='color:#ff4a30'>상승 추세</b>입니다. 풋 매수 방향과 일치하여 베가 이익을 기대할 수 있습니다.")
        elif iv_direction == "하락":
            lines.append(f"IV가 <b style='color:#30c070'>하락 추세</b>입니다. 베가 손실 리스크가 있어 풋 매수 타이밍을 재고하세요.")
        if hv_premium > 5:
            lines.append(f"IV({ovx_cur})가 HV({hv})보다 {hv_premium}pt 높아 시장이 <b>추가 하락 리스크를 반영</b>하고 있습니다.")
        else:
            lines.append(f"HV 대비 프리미엄이 낮아 풋 옵션이 상대적으로 저렴합니다.")

    lines.append(
        f"콜/풋 비율 {cp_ratio} · HV/IV 배율 {round(hv/ovx_cur,2) if ovx_cur>0 else 'N/A'} 기준으로 "
        f"{opt_label} 매수 적합도 점수는 <b style='color:#e07020'>{score}점</b>으로 <b>{verdict}</b> 구간입니다."
    )
    return lines


@app.get("/analyze")
async def analyze(option_type: str = Query(default="콜", description="옵션 종류: 콜 또는 풋")):
    try:
        ovx_df = yf.Ticker("^OVX").history(period="2y")
        wti_df = yf.Ticker("CL=F").history(period="1y")

        ovx_close = clean_index(ovx_df["Close"].copy())
        wti_close = clean_index(wti_df["Close"].copy())

        ovx_1y = ovx_close.iloc[-252:]
        ovx_cur = round(float(ovx_close.iloc[-1]), 2)
        wti_cur = round(float(wti_close.iloc[-1]), 2)

        hv = calc_hv(wti_close)
        iv_rank, iv_pct = calc_ivr_and_pct(ovx_1y)
        iv_direction, iv_slope = get_iv_direction(ovx_1y)
        hv_premium = round(ovx_cur - hv, 2)
        hv_iv_ratio = round(hv / ovx_cur, 3) if ovx_cur > 0 else 1.0
        wti_ret5, wti_ret20 = calc_wti_momentum(wti_close)
        cp = get_cp_ratio()

        score = calc_score(option_type, iv_rank, iv_pct, hv_premium,
                           hv_iv_ratio, iv_direction, wti_ret5, cp)
        verdict = (
            "매우 유리" if score >= 70 else
            "유리"     if score >= 55 else
            "보통"     if score >= 40 else
            "불리"     if score >= 25 else
            "매우 불리"
        )
        opt_label = f"{option_type}(Call)" if option_type == "콜" else f"{option_type}(Put)"

        factors = build_factors(option_type, iv_rank, iv_pct, hv_premium,
                                wti_ret5, ovx_cur, cp)
        ovx_history = get_ovx_history(ovx_df, days=90)
        commentary = build_commentary(
            option_type, iv_rank, iv_pct, iv_direction, hv_premium,
            hv_iv_ratio, wti_cur, ovx_cur, hv, cp, score
        )

        ovx_52w_hi = round(float(ovx_1y.max()), 2)
        ovx_52w_lo = round(float(ovx_1y.min()), 2)

        return {
            "score": score,
            "verdict": verdict,
            "option_type": opt_label,
            "option_type_raw": option_type,
            "wti_price": wti_cur,
            "wti_ret5": wti_ret5,
            "wti_ret20": wti_ret20,
            "ovx_current": ovx_cur,
            "ovx_52w_hi": ovx_52w_hi,
            "ovx_52w_lo": ovx_52w_lo,
            "iv_rank": iv_rank,
            "iv_percentile": iv_pct,
            "iv_direction": iv_direction,
            "iv_slope": iv_slope,
            "hv": hv,
            "hv_premium": hv_premium,
            "hv_iv_ratio": hv_iv_ratio,
            "call_put_ratio": cp,
            "factors": factors,
            "ovx_history": ovx_history,
            "commentary": commentary,
            "data_source": "Yahoo Finance (약 15분 지연)",
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M KST"),
        }
    except Exception as e:
        import traceback
        return {"error": str(e), "detail": traceback.format_exc()}


if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static_assets")


@app.get("/")
async def root():
    if os.path.exists("static/index.html"):
        return FileResponse("static/index.html")
    return {"status": "ok", "endpoints": ["/analyze"]}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
