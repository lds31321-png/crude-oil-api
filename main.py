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

app = FastAPI(title="원유 옵션 고평가 분석 API")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


def clean_tz(series):
    if hasattr(series.index, "tz") and series.index.tz is not None:
        series.index = series.index.tz_localize(None)
    return series


def calc_hv(prices, window=21):
    log_ret = np.log(prices / prices.shift(1)).dropna()
    hv = log_ret.rolling(window).std().iloc[-1] * np.sqrt(252) * 100
    return round(float(hv), 2)


def calc_ivr_pct(series):
    cur = float(series.iloc[-1])
    lo, hi = float(series.min()), float(series.max())
    ivr = round((cur - lo) / (hi - lo) * 100, 1) if hi != lo else 50.0
    pct = round(float((series < cur).sum()) / len(series) * 100, 1)
    return ivr, pct


def get_iv_direction(series):
    slope = np.polyfit(range(10), series.iloc[-10:].values, 1)[0]
    if slope > 0.3:
        return "상승", round(float(slope), 3)
    elif slope < -0.3:
        return "하락", round(float(slope), 3)
    return "횡보", round(float(slope), 3)


def calc_wti_momentum(prices):
    r5  = (prices.iloc[-1] / prices.iloc[-6]  - 1) * 100 if len(prices) > 6  else 0.0
    r20 = (prices.iloc[-1] / prices.iloc[-22] - 1) * 100 if len(prices) > 22 else 0.0
    return round(float(r5), 2), round(float(r20), 2)


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


def calc_overval_score(option_type, iv_rank, iv_pct, hv_premium, hv_iv_ratio,
                       iv_direction, cp_ratio):
    """
    매도자 관점 옵션 고평가 점수 (0~100)
    콜: C/P 비율 높을수록 고평가 / 풋: C/P 비율 낮을수록 고평가
    """
    s  = iv_rank * 0.25
    s += iv_pct  * 0.22
    s += max(0.0, min(100.0, hv_premium * 2.0 + 50.0)) * 0.18
    s += max(0.0, min(100.0, (1.0 - hv_iv_ratio) * 100.0 + 50.0)) * 0.15
    # C/P 비율 컴포넌트 — 콜/풋 방향 반대
    if option_type == "콜":
        cp_score = min(100.0, max(0.0, (cp_ratio - 0.5) / 1.5 * 100.0))
    else:
        cp_score = min(100.0, max(0.0, (1.5 - cp_ratio) / 1.0 * 100.0))
    s += cp_score * 0.20
    if   iv_direction == "상승": s += 10.0
    elif iv_direction == "하락": s -= 10.0
    return int(min(max(round(s), 0), 100))


def seasonal_demand():
    m = datetime.now().month
    table = {1:65, 2:60, 3:45, 4:40, 5:55, 6:70, 7:75, 8:70, 9:50, 10:45, 11:60, 12:65}
    return table.get(m, 50)


def build_overval_factors(ovx_cur, ovx_52w_lo, hv, iv_rank, wti_ret20, cp_ratio):
    """
    5가지 고평가 요인 점수 (0~100)
    """
    # 1. 지정학리스크: OVX가 52주 저점 대비 얼마나 높은가
    geo = int(min(100, max(0, (ovx_cur / max(ovx_52w_lo, 1) - 1) * 160 + 20)))

    # 2. 공급불확실성: 역사적 변동성(HV)이 높을수록 공급 불확실
    supply = int(min(100, max(0, hv * 2.5)))

    # 3. 계절수요: 월별 계절성
    seasonal = seasonal_demand()

    # 4. 달러강세: WTI 20일 하락 = 달러 강세 신호 (역방향)
    dollar = int(min(100, max(0, 50 - wti_ret20 * 2.5)))

    # 5. 투기포지션: IV 순위 + C/P 비율 기반
    cp_factor = min(cp_ratio, 2.5) * 18 if cp_ratio > 0 else 18
    spec = int(min(100, max(0, iv_rank * 0.55 + cp_factor)))

    return [
        {"name": "지정학리스크",   "pct": geo},
        {"name": "공급불확실성",   "pct": supply},
        {"name": "계절수요",       "pct": seasonal},
        {"name": "달러강세",       "pct": dollar},
        {"name": "투기포지션",     "pct": spec},
    ]


def get_ovx_history(df, days=90):
    hist = clean_tz(df["Close"].copy()).tail(days)
    return [
        {"date": str(idx)[:10], "value": round(float(v), 2)}
        for idx, v in hist.items()
    ]


def build_commentary(option_type, iv_rank, iv_pct, iv_direction, hv_premium,
                     hv_iv_ratio, wti_cur, ovx_cur, hv, cp_ratio, score):
    verdict = (
        "고평가" if score >= 70 else
        "적정"   if score >= 40 else
        "저평가"
    )
    opt_kor = "콜(Call)" if option_type == "콜" else "풋(Put)"
    opt_kr  = "콜" if option_type == "콜" else "풋"

    lines = [
        f"현재 WTI 원유 선물가는 <b style='color:#f0a050'>${wti_cur}</b>이며, "
        f"OVX 원유 변동성 지수는 <b style='color:#f0a050'>{ovx_cur}</b>입니다.",
    ]

    # IV 수준 해석
    if iv_rank >= 70:
        lines.append(
            f"IV Rank <b>{iv_rank}</b>로 <b style='color:#ff4a32'>1년 중 상위권</b>입니다. "
            f"역사적으로 높은 구간에서 {opt_kr} 옵션 프리미엄이 <b>고평가</b>되고 있습니다."
        )
    elif iv_rank >= 40:
        lines.append(
            f"IV Rank <b>{iv_rank}</b>로 중간 수준입니다. "
            f"{opt_kr} 옵션 프리미엄은 <b>적정</b> 구간에 있습니다."
        )
    else:
        lines.append(
            f"IV Rank <b>{iv_rank}</b>로 <b style='color:#2ec470'>1년 중 하위권</b>입니다. "
            f"{opt_kr} 옵션 프리미엄은 <b>저평가</b>되어 있습니다."
        )

    # IV 방향 해석
    if iv_direction == "상승":
        lines.append(
            f"IV가 <b style='color:#ff4a32'>상승 추세</b>입니다. "
            f"프리미엄이 계속 오르고 있어 {opt_kr} 매도 진입 타이밍을 신중히 검토해야 합니다."
        )
    elif iv_direction == "하락":
        lines.append(
            f"IV가 <b style='color:#2ec470'>하락 추세</b>입니다. "
            f"프리미엄이 낮아지고 있어 {opt_kr} 매도 시 수취 프리미엄이 감소할 수 있습니다."
        )
    else:
        lines.append(
            f"IV가 <b>횡보</b> 중입니다. 프리미엄 수준이 안정적으로 유지되고 있습니다."
        )

    # HV 프리미엄 해석
    if hv_premium > 5:
        lines.append(
            f"내재변동성(IV {ovx_cur})이 역사적변동성(HV {hv})보다 "
            f"<b style='color:#ff4a32'>+{hv_premium}pt 높습니다.</b> "
            f"시장이 실제 움직임 이상으로 불안을 반영하여 프리미엄이 비쌉니다."
        )
    elif hv_premium < 0:
        lines.append(
            f"내재변동성(IV {ovx_cur})이 역사적변동성(HV {hv})보다 "
            f"<b style='color:#2ec470'>{hv_premium}pt 낮습니다.</b> "
            f"시장이 과거 움직임보다 낮은 변동성을 예상하여 프리미엄이 저렴합니다."
        )
    else:
        lines.append(
            f"내재변동성(IV {ovx_cur})이 역사적변동성(HV {hv}) 대비 "
            f"{hv_premium}pt로 <b>적정 수준</b>에 있습니다."
        )

    # 종합 결론
    lines.append(
        f"C/P 비율 {cp_ratio} · HV/IV 배율 {round(hv/ovx_cur, 3) if ovx_cur > 0 else 'N/A'} 기준 "
        f"{opt_kor} 고평가 점수 <b style='color:#e07020'>{score}점</b>으로 "
        f"<b>{verdict}</b> 구간입니다. "
        + (f"옵션 <b>매도 전략</b>이 프리미엄 측면에서 유리한 환경입니다."
           if score >= 70 else
           f"옵션 프리미엄은 공정 가치에 근접해 있습니다."
           if score >= 40 else
           f"옵션 <b>매수 전략</b>이 저렴한 프리미엄 측면에서 유리한 환경입니다.")
    )
    return lines


@app.get("/analyze")
async def analyze(option_type: str = Query(default="콜", description="콜 또는 풋")):
    try:
        ovx_df   = yf.Ticker("^OVX").history(period="2y")
        wti_df   = yf.Ticker("CL=F").history(period="1y")

        ovx_close = clean_tz(ovx_df["Close"].copy())
        wti_close = clean_tz(wti_df["Close"].copy())

        ovx_1y    = ovx_close.iloc[-252:]
        ovx_cur   = round(float(ovx_close.iloc[-1]), 2)
        wti_cur   = round(float(wti_close.iloc[-1]), 2)

        hv             = calc_hv(wti_close)
        iv_rank, iv_pct = calc_ivr_pct(ovx_1y)
        iv_direction, _ = get_iv_direction(ovx_1y)
        hv_premium     = round(ovx_cur - hv, 2)
        hv_iv_ratio    = round(hv / ovx_cur, 3) if ovx_cur > 0 else 1.0
        wti_ret5, wti_ret20 = calc_wti_momentum(wti_close)
        cp             = get_cp_ratio()

        ovx_52w_hi = round(float(ovx_1y.max()), 2)
        ovx_52w_lo = round(float(ovx_1y.min()), 2)

        score   = calc_overval_score(iv_rank, iv_pct, hv_premium, hv_iv_ratio, iv_direction)
        verdict = (
            "고평가" if score >= 70 else
            "적정"   if score >= 40 else
            "저평가"
        )

        factors    = build_overval_factors(ovx_cur, ovx_52w_lo, hv, iv_rank, wti_ret20, cp)
        ovx_hist   = get_ovx_history(ovx_df, days=90)
        commentary = build_commentary(
            option_type, iv_rank, iv_pct, iv_direction, hv_premium,
            hv_iv_ratio, wti_cur, ovx_cur, hv, cp, score
        )

        return {
            "score":          score,
            "verdict":        verdict,
            "option_type":    option_type,
            "wti_price":      wti_cur,
            "wti_ret5":       wti_ret5,
            "wti_ret20":      wti_ret20,
            "ovx_current":    ovx_cur,
            "ovx_52w_hi":     ovx_52w_hi,
            "ovx_52w_lo":     ovx_52w_lo,
            "iv_rank":        iv_rank,
            "iv_percentile":  iv_pct,
            "iv_direction":   iv_direction,
            "hv":             hv,
            "hv_premium":     hv_premium,
            "hv_iv_ratio":    hv_iv_ratio,
            "call_put_ratio": cp,
            "factors":        factors,
            "ovx_history":    ovx_hist,
            "commentary":     commentary,
            "data_source":    "Yahoo Finance (약 15분 지연)",
            "updated_at":     datetime.now().strftime("%Y-%m-%d %H:%M KST"),
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
    return {"status": "ok"}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
