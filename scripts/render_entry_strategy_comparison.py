"""Audit fixed comparative research and produce its Korean report and figure."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DAY = 86400000
IDS = ("channel55", "pullback20", "rsi2")
COLORS = {"current_stable": "#a67b4d", "channel55": "#356bb3",
          "pullback20": "#1c8e7d", "rsi2": "#b9568b", "SPY": "#333c4a"}
LABELS = {"current_stable": "Current rules: assumed stable", "channel55": "55-session breakout",
          "pullback20": "20-session pullback", "rsi2": "RSI(2) reversion", "SPY": "SPY price hold"}


def read_csv(p):
    with p.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def percent(x, digits=2):
    return "—" if x is None else f"{100*x:,.{digits}f}%"


def close(a, b, message=""):
    assert math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-7), (message, a, b)


def period_metrics(curve, period):
    selected = [r for r in curve if not r.get("phase") and period["start"] <= r["date"] <= period["end"]]
    first_index = curve.index(selected[0])
    previous = curve[first_index-1]
    start = float(previous["equity"])
    end = float(selected[-1]["equity"])
    years = (float(selected[-1]["at"])-float(previous["at"]))/DAY/365.25
    high, dd = start, 0
    for r in selected:
        high = max(high, float(r["equity"]))
        dd = max(dd, 1-float(r["equity"])/high)
    return {"startEquity": start, "endingEquity": end, "markReturn": end/start-1,
            "cagr": (end/start)**(1/years)-1, "maxDrawdown": dd,
            "sessions": len(selected), "previousEquityAt": float(previous["at"])}


def validate(directory, result):
    prior_dir = ROOT / "research/entry-backtest/2026-10-04"
    prior = json.loads((prior_dir / "results.json").read_text())
    assert result["input"]["sha256"] == prior["input"]["sha256"]
    for relative, expected in result["sourceHashes"].items():
        assert hashlib.sha256((ROOT/relative).read_bytes()).hexdigest() == expected, relative
    reference = read_csv(directory / "SPY-curve.csv")
    reference_dates = [r["date"] for r in reference if not r["phase"]]
    for id, method in result["methods"].items():
        base = id.removesuffix("_stress")
        curve = read_csv(directory / (id+"-curve.csv"))
        trades = read_csv(directory / (id+"-trades.csv"))
        opened = json.loads((directory/(id+"-open.json")).read_text())
        daily = read_csv(directory / (base+"-daily.csv"))
        full, freq = method["full"], method["frequency"]
        assert [r["date"] for r in curve if not r["phase"]] == reference_dates
        assert [r["date"] for r in daily] == reference_dates
        assert len(daily) == freq["sessions"]
        assert sum(int(r["candidates"]) for r in daily) == freq["signals"]
        assert sum(int(r["candidates"]) == 0 for r in daily) == freq["zeroDays"]
        for r in daily:
            top = r["top3"].split("|") if r["top3"] else []
            assert len(top) == min(3, int(r["candidates"]))
            if r["priceRegime"] == "below200":
                assert not top and int(r["candidates"]) == 0
        for h, stats in method["top3"].items():
            assert stats["observations"]+sum(stats["excluded"].values()) == freq["top3Signals"], (id, h)
        assert len(trades) == full["closedTrades"]
        assert len(opened) == full["openPositions"]
        assert len(trades)+len(opened) == full["entries"]
        for t in [*trades, *opened]:
            assert float(t["entryAt"]) > float(t["signalAt"])
            assert float(t["qty"]) > 0 and float(t["qty"]).is_integer()
        for t in trades:
            assert float(t["exitAt"]) >= float(t["entryAt"])
        fees = sum(float(t["entryFee"])+float(t["exitFee"]) for t in trades)+sum(p["entryFee"] for p in opened)
        mark = full["initial"]+sum(float(t["net"]) for t in trades)
        mark += sum(p["qty"]*(p["mark"]-p["entry"])-p["entryFee"] for p in opened)
        close(fees, full["fees"], id+" fees")
        close(mark, full["markEquity"], id+" accounting")
        close(float(curve[-1]["equity"]), mark)
        cost = method["cost"]
        liquidation = mark-sum(p["qty"]*p["mark"]*(1-(1-cost["slip"])*(1-cost["fee"])) for p in opened)
        close(liquidation, full["liquidationEquivalentEquity"])
        symbol_net={}
        for t in trades:
            symbol_net[t["symbol"]]=symbol_net.get(t["symbol"],0)+float(t["net"])
        for t in opened:
            symbol_net[t["symbol"]]=symbol_net.get(t["symbol"],0)+t["qty"]*(t["mark"]*(1-cost["slip"])*(1-cost["fee"])-t["entry"])-t["entryFee"]
        close(sum(symbol_net.values()), liquidation-full["initial"])
        concentration=full["concentration"]
        for q in concentration["topSymbols"]:
            close(q["net"],symbol_net[q["symbol"]])
        if liquidation>full["initial"]:
            close(concentration["topSymbolShareOfNetProfit"],max(symbol_net.values())/(liquidation-full["initial"]))
        high, dd = full["initial"], 0
        for r in curve:
            equity, cash, exposure = (float(r[k]) for k in ("equity", "cash", "exposure"))
            close(equity, cash+exposure, id+" unlevered equity")
            assert cash >= -1e-6
            high = max(high, equity)
            dd = max(dd, 1-equity/high)
            if not r["phase"]:
                assert 0 <= int(r["positions"]) <= 5
                assert 0 <= int(r["maxSectorPositions"]) <= 2
        close(dd, full["maxDrawdown"])
        for key, p in result["periodDefinition"].items():
            actual, expected = method["periods"][key], period_metrics(curve, p)
            for field, value in expected.items():
                close(actual[field], value, id+" "+key+" "+field)
            selected = [r for r in daily if p["start"] <= r["date"] <= p["end"]]
            expected_top = sum(min(3, int(r["candidates"])) for r in selected)
            for h, stats in actual["top3"].items():
                assert stats["observations"]+sum(stats["excluded"].values()) == expected_top, (id, key, h)
        if method["stress"]:
            normal = result["methods"][base]
            assert method["frequency"] == normal["frequency"]
            assert method["top3"] == normal["top3"]  # Diagnostic labels always use normal costs.
            close(cost["fee"], 2*normal["cost"]["fee"])
            close(cost["slip"], 2*normal["cost"]["slip"])
    for status in ("stable", "watch"):
        m = result["controls"]["current_"+status]
        assert m["full"] == prior["scenarios"][status]["portfolio"], "Frozen control must remain unchanged"
        curve = read_csv(prior_dir/(status+"-curve.csv"))
        for key, p in result["periodDefinition"].items():
            for field, value in period_metrics(curve, p).items():
                close(m["periods"][key][field], value)
    ordered = sorted(IDS, key=lambda id: (-result["methods"][id]["periods"]["early"]["cagr"], id))
    assert result["selection"]["selected"] == ordered[0]
    assert not result["selection"]["automaticPromotion"]
    for key, p in result["periodDefinition"].items():
        for field, value in period_metrics(reference, p).items():
            close(result["benchmark"]["periods"][key][field], value)


def render_chart(directory, result):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10})
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.2))
    for id in ("current_stable", *IDS, "SPY"):
        source = ROOT/"research/entry-backtest/2026-10-04/stable-curve.csv" if id == "current_stable" else directory/(id+"-curve.csv")
        curve = read_csv(source)
        rows = [r for r in curve if not r["phase"]]
        axes[0].plot([datetime.fromisoformat(r["date"]) for r in rows],
                     [float(r["equity"])/10000 for r in rows], color=COLORS[id], lw=1.5, label=LABELS[id])
        begin = result["periodDefinition"]["recent"]["start"]
        selected = [r for r in rows if r["date"] >= begin]
        previous = rows[rows.index(selected[0])-1]
        axes[1].plot([datetime.fromisoformat(r["date"]) for r in selected],
                     [float(r["equity"])/float(previous["equity"]) for r in selected], color=COLORS[id], lw=1.5)
    axes[0].set_title("2017-10-02 to 2026-10-02", loc="left", pad=12)
    axes[1].set_title("2023 onward: carried accounts, rebased", loc="left", pad=12)
    axes[0].set_ylabel("Marked equity / initial equity")
    axes[1].set_ylabel("Marked equity / 2022-12-30 equity")
    axes[0].axvline(datetime(2023, 1, 1), color="#7a8798", ls="--", lw=.9, alpha=.7)
    for ax in axes:
        ax.grid(axis="y", color="#dce1e7", lw=.6)
        ax.spines[["top", "right"]].set_visible(False)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    axes[0].xaxis.set_major_locator(mdates.YearLocator(2))
    axes[1].xaxis.set_major_locator(mdates.YearLocator(1))
    axes[0].legend(loc="upper left", fontsize=8.5, frameon=False)
    fig.suptitle("Fixed alternative entry models — exploratory, current-constituent price history", x=.06, ha="left", fontsize=13)
    fig.text(.06, .025, "No dividends. Normal fees + adverse slippage. Displayed curves are marked equity; full-period headline CAGR includes terminal exit costs.", fontsize=8, color="#566275")
    fig.tight_layout(rect=(0, .05, 1, .93))
    fig.savefig(directory/"strategy-comparison.png", dpi=170, bbox_inches="tight")
    plt.close(fig)


def render_report(directory, r):
    normal = {**r["controls"], **{id:r["methods"][id] for id in IDS}, "SPY":r["benchmark"]}
    winner = r["methods"][r["selection"]["selected"]]
    lines = ["# 고정 대체 진입 전략: 과거 비교", "", "세 대체 모델을 계산 전에 고정하고 앞선 현재 규칙 연구와 비교했다. "
             "실시간 매수 판정과 홈페이지는 변경하지 않았다.", "",
             f"동일 가격 버전: **{r['start']}~{r['end']}**, **{r['symbols']}개**, "
             f"**{r['methods']['channel55']['frequency']['sessions']:,}거래일**. "
             "정상 비용은 편도 수수료 0.05%와 불리한 슬리피지 0.05%, 익일 시가 체결이다. "
             "전체 후보 순위로 최대 5개를 보유하며 거래당 위험 1%·종목 비중 20%·동일 업종 2개를 유지했다.", "",
             "## 전체 계좌 성과", "",
             "계좌 성과는 전체 후보를 사용한다. 매일 TOP3만 사는 계좌가 아니다. "
             "아래 전체 CAGR·누적 수익률은 마지막 보유분의 추가 가상 청산 비용까지 반영한다. "
             "낙폭·평균 노출은 일별 종가 평가 기준이다.", "",
             "| 모델 | 연수익률 CAGR | 누적 수익률 | 최대낙폭 | 평균 노출 | 청산 거래 | 청산 승률 |", "|---|---:|---:|---:|---:|---:|---:|"]
    for id,m in normal.items():
        p=m["full"]
        lines.append(f"| {m['name']} | {percent(p['cagr'])} | {percent(p['liquidationEquivalentReturn'])} | "
                     f"{percent(p['maxDrawdown'])} | {percent(p['meanExposure'])} | {p.get('closedTrades','—')} | {percent(p.get('winRate'))} |")
    lines += ["", "현재 규칙 stable/watch는 당시 실제 신용 상태를 복원하지 않은 고정 가정이다. "
              "대체 모델은 당시 SPY 종가의 SMA200 필터를 사용하며 순위·청산도 다르다. "
              "이 차이를 진입 조건 하나의 인과 효과로 해석할 수 없다.", ""]
    concentration=r["methods"]["channel55"]["full"]["concentration"]
    top=concentration["topSymbols"][0]
    lines += [f"돌파 계좌의 손익을 종목별로 확인하면 **{top['symbol']}**의 비용 반영 손익이 "
              f"**${top['net']:,.2f}**, 전체 최종 순이익의 **{percent(concentration['topSymbolShareOfNetProfit'])}**다. "
              "손익 집중도는 첫 결과를 본 뒤 추가한 사후 진단이며 전략·전반 선택 규칙은 바꾸지 않았다. "
              "20% 비중 한도는 진입 시 기준이다. 가격 상승으로 늘어난 비중을 재조정하지 않으므로 "
              "큰 추세의 이익과 위험이 한 종목에 집중될 수 있다.", "",
              "## 시간 분할", "",
              "아래는 같은 연속 계좌의 **종가 평가** 성과다. 보유분을 승계하고 후반 시작 자본은 "
              "2022-12-30 종가 평가액이다. 구간 끝의 추가 가상 청산 비용은 넣지 않는다. "
              "최근 구간도 이미 가격을 본 탐색적 비교이므로 진정한 미관측 검증이 아니다.", "",
              "| 모델 | 2017–2022 CAGR | 2023–2026 CAGR | 후반 SPY 대비 CAGR 차이 | 후반 최대낙폭 |", "|---|---:|---:|---:|---:|"]
    for id,m in normal.items():
        e,l=m["periods"]["early"],m["periods"]["recent"]
        difference=l["cagr"]-r["benchmark"]["periods"]["recent"]["cagr"]
        lines.append(f"| {m['name']} | {percent(e['cagr'])} | {percent(l['cagr'])} | {100*difference:+.2f}%p | {percent(l['maxDrawdown'])} |")
    lines += ["", f"사전에 정한 ‘전반 CAGR 최대’ 규칙으로 선택된 대체 모델은 **{winner['name']}**이다. "
              f"전반 {percent(winner['periods']['early']['cagr'])}, 후반 {percent(winner['periods']['recent']['cagr'])}다. "
              "후반 결과로 모델·임계값을 다시 고르지 않았으며 자동 승격하지 않는다.", "",
              "## 비용 2배", "",
              "순위 신호를 바꾸지 않고 각 대체 계좌에서 수수료·슬리피지를 각각 2배로 높였다. "
              "비용에 따라 수량·비용 손익비·체결 가능한 거래가 달라질 수 있다.", "",
              "| 모델 | 정상 CAGR | 비용 2배 CAGR | 비용 2배 최대낙폭 | 비용 2배 후반 CAGR |", "|---|---:|---:|---:|---:|"]
    for id in IDS:
        a,b=r["methods"][id],r["methods"][id+"_stress"]
        lines.append(f"| {a['name']} | {percent(a['full']['cagr'])} | {percent(b['full']['cagr'])} | "
                     f"{percent(b['full']['maxDrawdown'])} | {percent(b['periods']['recent']['cagr'])} |")
    lines += ["", "## 후보 빈도와 TOP3 진단", "",
              "TOP3 진단은 익일 시가 진입 후 20/63번째 거래일 종가의 고정 기간 수익률이다. "
              "이는 손절·시장 필터 청산을 실행한 계좌 수익률이 아니다. "
              "각 신호의 같은 날짜 SPY와 비교하며 모든 진단은 정상 비용을 사용한다. "
              "일별 신호가 서로 겹치므로 독립 표본의 유의성으로 해석하지 않는다.", "",
              "| 모델 | 후보 0개인 날 | 평균 후보 | 20일 TOP3 SPY 초과수익 | 성숙 표본 | 63일 TOP3 SPY 초과수익 | 성숙 표본 |",
              "|---|---:|---:|---:|---:|---:|---:|"]
    for id,m in normal.items():
        if id=="SPY":continue
        a,b=m["top3"]["20"],m["top3"]["63"]
        lines.append(f"| {m['name']} | {percent(m['frequency']['zeroShare'])} | {m['frequency']['meanCandidates']:.2f} | "
                     f"{100*a['meanExcess']:+.2f}%p | {a['observations']:,} | {100*b['meanExcess']:+.2f}%p | {b['observations']:,} |")
    lines += ["", "미성숙·결측·분할 경계 제외 수와 시간 분할 TOP3 지표는 `results.json`에 모두 남겼다. "
              "두 날짜를 포함한 전 구간이 한 블록 안인 표본만 분할 통계에 사용했다. "
              "후보를 억지로 3개 채우는 모델은 없다.", "",
              "![전체 및 후반 평가 곡선](strategy-comparison.png)", "", "## 연별 종가 평가 수익률", "",
              "| 연도 | 현재 stable 가정 | 55일 돌파 | 20일선 반등 | RSI(2) | SPY 가격 |", "|---|---:|---:|---:|---:|---:|"]
    spy_curve=read_csv(directory/"SPY-curve.csv")
    for year in sorted(r["methods"]["channel55"]["annual"]):
        values=[r["controls"]["current_stable"]["annual"][year]["return"],
                *(r["methods"][id]["annual"][year]["markReturn"] for id in IDS),
                period_metrics(spy_curve,{"start":year+"-01-01","end":year+"-12-31"})["markReturn"]]
        lines.append("| "+year+" | "+" | ".join(percent(v) for v in values)+" |")
    lines += ["", "2017년과 2026년은 부분 연도다. 연별 수익률은 추가 경계 청산 비용을 넣지 않은 종가 평가 기준이다.", "",
              "## 재현·제약", "", "현재 구성 종목·업종을 과거에 사용하므로 생존자 편향이 있다. 상장폐지·역사적 구성 "
              "종목은 포함하지 못했다. 배당은 제외했고 공급자 수정·분할 조정 가격을 사용했다. "
              "실제 과거 신용·펀딩 자료도 복원하지 못했다. 이 결과만으로 현재 매수 TOP을 교체하지 않는다.", "",
              "입력 가격과 기존 대조군을 동봉한 재현 자료에서 실행한다:", "",
              "```bash", "node scripts/test_entry_strategy_comparison.cjs",
              "node scripts/entry_strategy_comparison.cjs",
              "python3 scripts/render_entry_strategy_comparison.py", "```", "",
              "전체 모델 명세는 [PROTOCOL.md](PROTOCOL.md). 코드·대조군·입력 해시와 "
              "CSV 곡선·청산 거래·미청산 포지션은 결과와 함께 보존했다."]
    (directory/"README.md").write_text("\n".join(lines)+"\n",encoding="utf-8")


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--directory",type=Path,default=ROOT/"research/entry-strategy-comparison/2026-10-04")
    p.add_argument("--validate-only",action="store_true")
    args=p.parse_args()
    result=json.loads((args.directory/"results.json").read_text())
    validate(args.directory,result)
    print("PASS: frozen controls, source hashes, candidate counts, next-open fills, risk limits, accounting, split chronology and early-only selection")
    if not args.validate_only:
        render_chart(args.directory,result)
        render_report(args.directory,result)


if __name__=="__main__":
    main()
