"""Validate research output accounting and render its dated Korean report/chart."""
import argparse
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_csv(p):
    with p.open(newline="") as f:
        return list(csv.DictReader(f))


def percent(x, digits=2):
    return "—" if x is None else f"{x * 100:,.{digits}f}%"


def validate(directory, result, sources):
    assert result["input"]["sha256"] == sources["datasetSHA256"]
    for relative, expected in result["sourceHashes"].items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected, relative
    for status, s in result["scenarios"].items():
        daily = read_csv(directory / (status + "-daily.csv"))
        curve = read_csv(directory / (status + "-curve.csv"))
        trades = read_csv(directory / (status + "-trades.csv"))
        opened = json.loads((directory / (status + "-open.json")).read_text())
        freq, account = s["frequency"], s["portfolio"]
        assert len(daily) == freq["sessions"]
        assert sum(int(r["buy"]) for r in daily) == freq["totalSignalObservations"]
        assert sum(int(r["buy"]) == 0 for r in daily) == freq["zeroDays"]
        assert sum(freq[k] for k in ("zeroDays", "oneDays", "twoDays", "threeOrMoreDays")) == len(daily)
        top_total = sum(min(int(r["buy"]), 3) for r in daily)
        waiting_total = 0
        for r in daily:
            if int(r["buy"]):
                assert not r["waiting"]
            else:
                waiting = r["waiting"].split("|") if r["waiting"] else []
                assert len(waiting) <= 3
                assert all(q.rsplit(":", 1)[1] in ("breakout", "pullback", "riskwait") for q in waiting)
                waiting_total += len(waiting)
        for group, expected in (("allBuyOutcomes", freq["totalSignalObservations"]),
                                ("top3Outcomes", top_total), ("waitingTop3Outcomes", waiting_total)):
            for metrics in s[group].values():
                assert metrics["observations"] + sum(metrics["excluded"].values()) == expected
        assert len(trades) == account["closedTrades"]
        assert len(opened) == account["openPositions"]
        for t in trades:
            assert float(t["entryAt"]) > float(t["signalAt"])
            assert float(t["qty"]).is_integer() and float(t["qty"]) > 0
        fees = sum(float(t["entryFee"]) + float(t["exitFee"]) for t in trades) + sum(p["entryFee"] for p in opened)
        equity = account["initial"] + sum(float(t["net"]) for t in trades)
        equity += sum(p["qty"] * (p["mark"] - p["entry"]) - p["entryFee"] for p in opened)
        assert abs(fees - account["fees"]) < 1e-6
        assert abs(equity - account["markEquity"]) < 1e-6
        assert abs(float(curve[-1]["equity"]) - equity) < 1e-6
    audit = result.get("latestSnapshotAudit")
    if audit:
        assert audit["compared"] == audit["publishedSymbols"] == result["symbols"]
        assert not audit["mismatches"], audit["mismatches"]


def render_chart(directory, result, input_dir):
    import gzip
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from collect_entry_backtest import normalize
    payload = json.loads(gzip.decompress((input_dir / "raw/SPY.json.gz").read_bytes()))
    spy, _ = normalize(payload, "SPY", result["end"])
    spy = [r for r in spy if r["date"] >= result["start"]]
    cfg = result["costRisk"]
    qty = 10000 / (spy[0]["open"] * (1 + cfg["slip"]) * (1 + cfg["fee"]))
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10})
    fig, axes = plt.subplots(2, 1, figsize=(12, 7.4), sharex=True, gridspec_kw={"height_ratios": [2, 1]})
    colors = {"stable": "#ba7424", "watch": "#2377ab"}
    for status in ("stable", "watch"):
        curve = read_csv(directory / (status + "-curve.csv"))
        dates = [datetime.fromisoformat(r["date"]) for r in curve]
        axes[0].plot(dates, [float(r["equity"]) / 10000 for r in curve], color=colors[status], lw=1.6,
                     label=status + " scenario (all buy candidates)")
        daily = read_csv(directory / (status + "-daily.csv"))
        values = [int(r["buy"]) for r in daily]
        rolling = [sum(values[max(0, i - 20):i + 1]) / min(i + 1, 21) for i in range(len(values))]
        axes[1].plot([datetime.fromisoformat(r["date"]) for r in daily], rolling, color=colors[status], lw=1.5,
                     label=status + ": 21-session average")
    axes[0].plot([datetime.fromisoformat(r["date"]) for r in spy], [qty * r["close"] / 10000 for r in spy],
                 color="#3a4353", lw=1.5, label="SPY price buy-and-hold")
    for ax in axes:
        ax.grid(axis="y", color="#dce1e7", linewidth=.6)
        ax.spines[["top", "right"]].set_visible(False)
        ax.legend(loc="upper left", fontsize=9, frameon=False)
        for year in (2020, 2022):
            ax.axvspan(datetime(year, 1, 1), datetime(year + 1, 1, 1), color="#728198", alpha=.08)
    axes[0].set_ylabel("Marked equity / initial $10,000")
    axes[0].set_title("Frozen entry-context-v1: retrospective, conditional market scenarios", loc="left", fontsize=13, pad=13)
    axes[1].set_ylabel("Buy candidates / session")
    axes[1].xaxis.set_major_locator(mdates.YearLocator())
    axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    axes[1].set_xlim(datetime.fromisoformat(result["start"]), datetime.fromisoformat(result["end"]))
    fig.text(.07, .035, "Current home universe (503 stocks + SPY/SOXX); survivorship bias; no historical credit reconstruction.\n"
             "Next-open fills, 0.05% fee + 0.05% adverse slippage per side. Dividends excluded; open holdings marked.",
             fontsize=9, color="#4d5767")
    fig.subplots_adjust(left=.08, right=.98, top=.92, bottom=.14, hspace=.14)
    fig.savefig(directory / "equity-and-signals.png", dpi=170)
    plt.close(fig)


def write_report(directory, r, sources):
    scenarios = r["scenarios"]
    stable, watch = scenarios["stable"], scenarios["watch"]
    audit = r.get("latestSnapshotAudit", {})
    lines = ["# 매수 TOP 조건 과거 검증 — 2026-10-04", "",
        f"현행 조건을 바꾸지 않고 **{r['start']}–{r['end']}, {stable['frequency']['sessions']:,}거래일, "
        f"현재 홈 대상 {r['symbols']}개**를 검증했다. 매수 후보가 0개였던 날은 stable 가정에서 "
        f"**{percent(stable['frequency']['zeroShare'])}**, watch 가정에서 **{percent(watch['frequency']['zeroShare'])}**였다.", "",
        "이것은 가격 조건의 **조건부·탐색적** 백테스트다. 당시 시장 위험 피드를 재구성한 전체 서비스의 과거 실적은 아니다. "
        "현재 구성 종목만 사용하므로 생존 편향이 있으며, 과거 규칙 설계 후 시행한 연구라 미관측 검증도 아니다.", "",
        f"고정 실행 모형의 계좌 CAGR은 stable **{percent(stable['portfolio']['cagr'])}**, "
        f"watch **{percent(watch['portfolio']['cagr'])}**로 SPY 가격 보유 "
        f"**{percent(stable['portfolio']['benchmark']['cagr'])}**보다 낮았다. "
        "매수 TOP 3의 20·63일 표본 평균 초과수익도 두 가정 모두 음수였다. "
        "매수 0개 자체는 오류의 증거가 아니지만, 이번 실험에서 현행 조합의 성과 우위는 확인되지 않았다.", "",
        "## 매수 TOP은 얼마나 자주 비었나", "",
        "| 지표 | 항상 stable 가정 | 항상 watch 가정 |", "| --- | ---: | ---: |"]
    for label, key in (("후보 0개 거래일", "zeroDays"), ("후보 1개 거래일", "oneDays"),
                       ("후보 2개 거래일", "twoDays"), ("후보 3개 이상 거래일", "threeOrMoreDays")):
        lines.append(f"| {label} | {stable['frequency'][key]:,} | {watch['frequency'][key]:,} |")
    lines += [f"| 하루 평균 buy 수 | {stable['frequency']['meanBuyCount']:.2f} | {watch['frequency']['meanBuyCount']:.2f} |",
              f"| 반복 포함 신호 관측 | {stable['frequency']['totalSignalObservations']:,} | {watch['frequency']['totalSignalObservations']:,} |",
              f"| 비매수→매수 신호 시작 횟수 | {stable['frequency']['buyEpisodes']:,} | {watch['frequency']['buyEpisodes']:,} |", "",
              "동일 종목의 연속 신호는 별도 날짜로 센다. 신호 시작 횟수도 계좌 거래 수나 독립 표본 수를 뜻하지 않는다.", "",
              "| 연도 | 거래일 | stable 0개 일수 | watch 0개 일수 | stable 하루 평균 buy | watch 하루 평균 buy |",
              "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for year, a in stable["frequency"]["annual"].items():
        b = watch["frequency"]["annual"][year]
        lines.append(f"| {year} | {a['sessions']} | {a['zero']} | {b['zero']} | "
                     f"{a['totalSignals']/a['sessions']:.2f} | {b['totalSignals']/b['sessions']:.2f} |")
    lines += ["", "2017년은 10월부터, 2026년은 10월 2일까지다.", "", "## 현재 빈 매수 목록의 재현", ""]
    if audit:
        lines += [f"고정한 홈 원본(가격 생성 {audit['priceGeneratedAt']}, 시장 생성 {audit['marketGeneratedAt']})과 "
                  f"다운로드 이력으로 다시 계산한 **{audit['compared']}개 판정·점수가 모두 일치**했다. "
                  f"실제 해당 시장 피드의 상태는 `{audit['market']}`이고 `buy={audit['counts'].get('buy',0)}`다.", "",
                  "```json", json.dumps(audit["counts"], ensure_ascii=False, sort_keys=True), "```", ""]
    lines += ["빈 매수 목록은 과거에도 관측되는 규칙 결과다. 빈도만으로 55일/8% 기준의 최적성이나 수익성을 판단할 수는 없다.", "",
              "## 매수 TOP 3의 후속 가격 성과", "",
              "매일 기존 점수·ticker 순서로 최대 3개를 선택했다. 다음 실제 거래일 시가 진입 후 "
              "20·63번째 보유 거래일 종가 청산에 양쪽 비용을 반영했다. 동일 날짜·기간 SPY와 비교한다. "
              "**손절 실행·복리 계좌 성과가 아닌 고정기간 관찰 통계**다.", "",
              "| 가정 / 보유기간 | 성숙 관측 | 평균 순수익률 | 중앙값 | 수익 양수 비율 | 동기간 SPY 평균 | 평균 초과수익 | 평균 최저가 변동 |",
              "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for status, s in scenarios.items():
        for h, m in s["top3Outcomes"].items():
            lines.append(f"| {status} / {h}일 | {m['observations']:,} | {percent(m['meanNet'])} | {percent(m['medianNet'])} | "
                         f"{percent(m['winRate'])} | {percent(m['meanBenchmark'])} | {percent(m['meanExcess'])}p | {percent(m['meanAdverse'])} |")
    lines += ["", "초과수익은 퍼센트포인트다. 최저가 변동은 진입 시가 대비 비용 전의 보유기간 최저 저가이며 계좌 최대낙폭이 아니다. "
              "미성숙·결측 제외 수, 날짜별 균등 가중 평균, 하위 10%와 전체 buy 결과는 `results.json`에 있다. "
              "중첩 기간·같은 날짜 종목의 상관 때문에 위 표본 수를 독립적인 성공 횟수로 보지 않는다.", "",
              "## 기존 실행 규칙을 적용한 가상 계좌", "",
              "각 가정은 $10,000으로 시작하며 **TOP 3으로 제한하지 않고 전체 buy를 점수순으로 주문**한다. "
              "거래당 계좌 위험 1%, 최대 5종목, 진입 비중 최대 20%, 동일 현재 업종 최대 2개, 정수 주식·현금 계좌다. "
              "양쪽 수수료와 불리한 슬리피지는 각각 0.05%. 다음 시가 체결, 0.5변동폭 초과 갭 취소, "
              "같은 봉에서는 손절 우선. 돌파는 목표가 없이 추적 손절, 눌림목은 신호 전 55일 고점을 목표로 한다. "
              "보유 reduce와 손절 상향은 다음 봉부터 적용한다. 자세한 규칙은 [PROTOCOL.md](PROTOCOL.md)에 고정했다.", "",
              "| 지표 | stable 가정 | watch 가정 | SPY 가격 보유 |", "| --- | ---: | ---: | ---: |"]
    a, b = stable["portfolio"], watch["portfolio"]
    spy = a["benchmark"]
    lines += [f"| 종료 청산 비용 포함 총수익률 | {percent(a['liquidationEquivalentReturn'])} | {percent(b['liquidationEquivalentReturn'])} | {percent(spy['netReturn'])} |",
              f"| CAGR | {percent(a['cagr'])} | {percent(b['cagr'])} | {percent(spy['cagr'])} |",
              f"| 일별 종가 최대낙폭 | {percent(a['maxDrawdown'])} | {percent(b['maxDrawdown'])} | {percent(spy['maxDrawdown'])} |",
              f"| 평균 투자 노출 | {percent(a['meanExposure'])} | {percent(b['meanExposure'])} | 약 100% |",
              f"| 진입 / 청산 거래 | {a['entries']} / {a['closedTrades']} | {b['entries']} / {b['closedTrades']} | 1 / 1 |",
              f"| 청산 거래 순이익 승률 | {percent(a['winRate'])} | {percent(b['winRate'])} | — |",
              f"| 종료 시 보유 포지션 | {a['openPositions']} | {b['openPositions']} | — |", "",
              "종료 청산 비용은 미청산 포지션을 마지막 종가로 매도한다고 가정한 비용까지 차감했다. "
              "청산 거래 수·승률에는 이 가상 마지막 매도를 넣지 않는다. 그래프·연별 성적은 실제 가상 운용의 종가 평가액이다. "
              "최대낙폭은 일별 종가 기준이며 장중 최대 손실과 다르다.", "",
              "![조건부 계좌와 신호 빈도](equity-and-signals.png)", "",
              "| 연도 | stable 계좌 | watch 계좌 | SPY 가격 보유 | stable 연중 최대낙폭 | watch 연중 최대낙폭 |",
              "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for year, y in a["annual"].items():
        z = b["annual"][year]
        lines.append(f"| {year} | {percent(y['return'])} | {percent(z['return'])} | {percent(y['benchmarkReturn'])} | "
                     f"{percent(y['maxDrawdown'])} | {percent(z['maxDrawdown'])} |")
    lines += ["", "## 매수가 0개일 때의 진입 대기 TOP 3", "",
              "기존 whitelist인 breakout·pullback·riskwait만, 실제 buy가 0개인 날짜에서 관찰했다. "
              "서로 다른 날짜 집합이므로 매수 TOP과의 수익률 차이는 조건 완화의 인과적 효과가 아니다. "
              "대기 상태를 매수 추천으로 승격하지 않는다.", "",
              "| 가정 / 보유기간 | 성숙 관측 | 평균 순수익률 | 동기간 SPY | 평균 초과수익 |",
              "| --- | ---: | ---: | ---: | ---: |"]
    for status, s in scenarios.items():
        for h, m in s["waitingTop3Outcomes"].items():
            lines.append(f"| {status} / {h}일 | {m['observations']:,} | {percent(m['meanNet'])} | "
                         f"{percent(m['meanBenchmark'])} | {percent(m['meanExcess'])}p |")
    rejected = {k: v["rejectedDates"] for k, v in sources["sources"].items() if v.get("rejectedDates")}
    lines += ["", "## 데이터·검증 범위와 한계", "",
              f"- 수집 {sources['collectedStocks']}/{sources['expectedStocks']}개, 유효 OHLC "
              f"{sum(v['rows'] for v in sources['sources'].values()):,}개. 공급자 접근/속도 차단·수집 실패 없음. "
              f"유효하지 않은 봉 {json.dumps(rejected,ensure_ascii=False)}은 보간하지 않았다.",
              f"- 보유 중 가격 결측으로 실행·평가가 동결된 종목-거래일: stable {a['missingHeldSessions']}, watch {b['missingHeldSessions']}.",
              "- 현재 구성·현재 업종을 과거에 적용했다. 당시 S&P 500 구성 변화·상장폐지·과거 업종은 재현하지 못했다.",
              "- 과거 발표 시점의 NFCI·STLFSI4·DRTSCILM·FUNDING 피드를 확보하지 않았다. "
              "최신 수정된 FRED 관측을 과거의 알려진 정보로 대체하지 않았다. "
              "[FRED 실시간 기간 설명](https://fred.stlouisfed.org/docs/api/fred/realtime_period.html)에 따르면 "
              "현재 알려진 과거값과 당시 알려진 값은 구분해야 한다.",
              "- Yahoo quote OHLC를 같은 기준으로 사용했고 AdjClose와 섞지 않았다. "
              "공급자의 수정·분할 조정이 가능하며 당시 원 시세·주식 수·기업행위를 완전히 복원한 계좌는 아니다. "
              "배당·세금·환율은 양쪽 모두 제외했다.",
              "- 변동폭·55일/20일 수준·지표는 신호 날짜까지의 봉만 사용한다. 미래 봉 수정 불변성, "
              "익일 체결, 손절 우선·갭·정수 주식, 위험/unknown/stale 시장 차단, "
              "데이터 검증·성숙 라벨과 현행 ticker 동률 순서를 테스트했다.",
              "- 각 CSV의 신호 수와 성숙/제외 수, 거래·종료 포지션·비용·평가액의 회계 일치를 추가 확인했다.",
              "- 임계값을 탐색·최적화하지 않았고 생산 매수 조건·홈 순위·forward 관측 원장을 변경하지 않았다.", "",
              "## 재현", "", "```bash", "python scripts/collect_entry_backtest.py",
              "node --max-old-space-size=4096 scripts/backtest_entry_rules.cjs",
              "node scripts/test_entry_backtest.cjs", "python -m unittest discover -s scripts -p test_entry_backtest.py",
              "python scripts/render_entry_backtest.py", "```", "",
              "보존된 `prices.json.gz`를 `research/history/entry-backtest-2026-10-04/`에 놓으면 "
              "재다운로드 없이 동일 가격 입력으로 실행할 수 있다. `sources.json`의 원본 해시·수집일과 "
              "`results.json`의 규칙/입력 해시를 대조한다. 재다운로드 해시가 달라지면 동일 가격 버전의 재현이 아니다.", "",
              "그림 재생성에는 matplotlib이 필요하다. `--validate-only` 검증은 Python 표준 라이브러리만 사용한다. "
              "현재 원본과의 일치에는 동봉한 고정 forecasts/market snapshot을 사용한다.", "",
              f"정규화 가격 SHA-256: `{r['input']['sha256']}`", "",
              f"고정 규칙 SHA-256: `{r['sourceHashes']['scripts/entry-study-v1/technical-guide.cjs']}`", ""]
    (directory / "README.md").write_text("\n".join(lines))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--directory", type=Path, default=ROOT / "research/entry-backtest/2026-10-04")
    p.add_argument("--input-dir", type=Path, default=ROOT / "research/history/entry-backtest-2026-10-04")
    p.add_argument("--validate-only", action="store_true", help="Check committed results without downloading prices or plotting")
    args = p.parse_args()
    result = json.loads((args.directory / "results.json").read_text())
    sources = json.loads((args.directory / "sources.json").read_text())
    validate(args.directory, result, sources)
    if not args.validate_only:
        render_chart(args.directory, result, args.input_dir)
        write_report(args.directory, result, sources)
    print("PASS: signal totals, matured/excluded labels, next-open trades, fees, terminal equity and current snapshot parity")


if __name__ == "__main__":
    main()
