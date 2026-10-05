"""Audit paired TOP3 outcomes, time splits, block uncertainty and account paths.
Research only; never edits production or forward observation files.
"""
from pathlib import Path
import argparse, csv, gzip, hashlib, io, json, math
from collections import defaultdict
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"research/top3-ranking/2026-10-05"
PERIODS={"full":("2017-10-02","2026-10-02"),
         "early":("2017-10-02","2019-12-31"),
         "middle":("2020-01-01","2022-12-31"),
         "recent":("2023-01-01","2026-10-02")}
NAMES={"baseline":"기존 순위","tie_price_risk":"동점만 가격·위험 보완","price_risk":"가격·위험 우선",
       "volume":"거래량 확인 추가","sector":"업종 상대 강도 추가","combined":"거래량+업종 결합"}
METRICS=["net","excess","gross","avoidance","down","adverse"]
def read_csv(name):
    with gzip.open(OUT/name,"rt",newline="") as f:
        return list(csv.DictReader(f))
def num(v):
    return float(v) if v not in (None,"") else None
def mean(v):
    return float(np.mean(v)) if len(v) else None
def close(a,b):
    assert a is None and b is None or a is not None and b is not None and abs(a-b)<2e-11,(a,b)
def daily(rows):
    bydate=defaultdict(list)
    for r in rows:bydate[r["date"]].append(r)
    return {d:{"count":len(v),**{k:mean([r[k] for r in v]) for k in METRICS}}
            for d,v in sorted(bydate.items())}
def aggregate(rows):
    d=daily(rows)
    if not rows:return {"observations":0,"signalDates":0}
    return {"observations":len(rows),"signalDates":len(d),
            "dateBalancedNet":mean([v["net"] for v in d.values()]),
            "dateBalancedExcess":mean([v["excess"] for v in d.values()]),
            "dateBalancedAvoidance":mean([v["avoidance"] for v in d.values()]),
            "downsidePrecision":mean([v["down"] for v in d.values()]),
            "medianNet":float(np.median([r["net"] for r in rows])),
            "p10Net":float(np.quantile([r["net"] for r in rows],.1)),
            "meanAdverse":mean([v["adverse"] for v in d.values()])}
def block_interval(values,seed=20261005,iterations=2000,block=63):
    x=np.asarray(values,dtype=float);valid=np.isfinite(x)
    if valid.sum()<126:return None
    length=min(block,len(x));blocks=math.ceil(len(x)/length)
    rng=np.random.default_rng(seed)
    starts=rng.integers(0,len(x)-length+1,size=(iterations,blocks))
    sums=np.r_[0.,np.cumsum(np.where(valid,x,0.))]
    counts=np.r_[0,np.cumsum(valid)]
    endpoints=starts+length
    endpoints[:,-1]=starts[:,-1]+len(x)-(blocks-1)*length
    total=(sums[endpoints]-sums[starts]).sum(axis=1)
    count=(counts[endpoints]-counts[starts]).sum(axis=1)
    sample=total[count>0]/count[count>0]
    alpha=.05/10
    return {"blockTradingDays":length,"iterations":iterations,"validDates":int(valid.sum()),
            "meanDelta":float(x[valid].mean()),
            "ci95":[float(q) for q in np.quantile(sample,[.025,.975])],
            "familyAdjustedCI":[float(q) for q in np.quantile(sample,[alpha/2,1-alpha/2])],
            "familySize":10,"seed":seed}
def paired(candidate,baseline,metric,calendar):
    a,b=daily(candidate),daily(baseline)
    common=sorted(d for d in a.keys()&b.keys() if a[d]["count"]==3 and b[d]["count"]==3)
    if not common:return {"pairedDates":0}
    lookup={d:a[d][metric]-b[d][metric] for d in common}
    dates=[d for d in calendar if common[0]<=d<=common[-1]]
    ci=block_interval([lookup.get(d,np.nan) for d in dates])
    return {"pairedDates":len(common),"baseline":mean([b[d][metric] for d in common]),
            "candidate":mean([a[d][metric] for d in common]),"delta":mean(list(lookup.values())),
            "uncertainty":ci,
            "daily":[{"date":d,"delta":lookup.get(d),"candidate":a[d][metric] if d in lookup else None,
                      "baseline":b[d][metric] if d in lookup else None} for d in dates]}
def cost_rows(rows,cost):
    if cost==1:return rows
    fee=.0005*cost;slip=.0005*cost;factor=(1-fee)*(1-slip)/((1+fee)*(1+slip))
    return [{**r,"net":(1+r["gross"])*factor-1,
             "excess":(1+r["gross"])*factor-1-((1+r["benchmark"])/((1-.0005)**2/(1+.0005)**2)*factor-1),
             "avoidance":-r["gross"]*(1-fee)*(1-slip)} for r in rows]
def account_period(rows,report,start,end):
    selected=[r for r in rows if start<=r["date"]<=end]
    if not selected:return None
    first,last=selected[0],selected[-1]
    i=rows.index(first);initial=rows[i-1]["equity"] if i else report["initial"]
    initial_at=rows[i-1]["at"] if i else first["at"]-6.5*3600000
    terminal=report["liquidationEquity"] if end>="2026-10-02" else last["equity"]
    years=(last["at"]-initial_at)/(365.25*86400000)
    high=initial;dd=0
    for r in selected:high=max(high,r["equity"]);dd=max(dd,1-r["equity"]/high)
    return {"start":first["date"],"end":last["date"],"sessions":len(selected),
            "startEquity":initial,"endingEquity":terminal,"cagr":(terminal/initial)**(1/years)-1,
            "maxDrawdown":dd,"meanExposure":mean([r["exposure"]/r["equity"] for r in selected]),
            "basis":"continuous account, positions carried; terminal liquidation costs only at final dataset date"}
def spy_rows():
    meta=json.loads((OUT/"spy-input-manifest.json").read_text())
    assert hashlib.sha256((OUT/"spy-input.csv").read_bytes()).hexdigest()==meta["csvSHA256"]
    with (OUT/"spy-input.csv").open(newline="") as f:
        rows=list(csv.DictReader(f))
    for r in rows:
        for k in ["t","end","open","high","low","close"]:r[k]=float(r[k])
    return [r for r in rows if "2017-10-02"<=r["date"]<="2026-10-02"]
def benchmark_report(rows,cost):
    fee=slip=.0005*cost;first,last=rows[0],rows[-1]
    qty=10000/(first["open"]*(1+fee)*(1+slip))
    terminal=qty*last["close"]*(1-fee)*(1-slip)
    years=(last["end"]-first["t"])/(365.25*86400000)
    high=10000;dd=0
    for r in rows:
        eq=qty*r["close"];high=max(high,eq);dd=max(dd,1-eq/high)
    return {"cagr":(terminal/10000)**(1/years)-1,"maxDrawdown":dd,"terminalEquity":terminal,
            "basis":"SPY price buy-and-hold, initial and terminal transaction costs; no dividends"}
def exposure_controls(curves,spy,report,cost):
    assert [r["date"] for r in curves]==[r["date"] for r in spy]
    first,last=spy[0],spy[-1];years=(last["end"]-first["t"])/(365.25*86400000)
    fee=slip=.0005*cost;weight=report["meanExposure"]
    qty=10000*weight/(first["open"]*(1+fee)*(1+slip));cash=10000*(1-weight)
    terminal=cash+qty*last["close"]*(1-fee)*(1-slip)
    equity=10000;peak=equity;dd=0
    for i,(r,b) in enumerate(zip(curves,spy)):
        prior=curves[i-1] if i else None
        exposure=prior["exposure"]/prior["equity"] if prior else 0.
        reference=spy[i-1]["close"] if i else first["open"]
        equity*=1+exposure*(b["close"]/reference-1)
        peak=max(peak,equity);dd=max(dd,1-equity/peak)
    return {"meanInitialAllocation":weight,"staticSpyCashCagr":(terminal/10000)**(1/years)-1,
            "priorDayExposureSpyCashCagr":(equity/10000)**(1/years)-1,"priorDayExposureDrawdown":dd,
            "basis":"post-hoc diagnostics: static initial allocation set to strategy mean exposure; prior-day exposure uses zero-cost daily rebalancing",
            "limitations":"No claim of selection alpha; issuer beta/sector, stops/exits, execution and omitted rebalance costs also differ"}
def pct(x):
    return "—" if x is None else f"{x*100:.2f}%"
def pp(x):
    return "—" if x is None else f"{x*100:+.2f}%p"
def build(write_outputs=True):
    raw=json.loads((OUT/"raw-results.json").read_text())
    for name,digest in raw["sourceHashes"].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest,"Frozen source differs: "+name
    for name,meta in raw["outputHashes"].items():
        p=OUT/name;assert p.stat().st_size==meta["bytes"];assert hashlib.sha256(p.read_bytes()).hexdigest()==meta["sha256"]
    labels=read_csv("outcomes.csv.gz")
    exclusions=defaultdict(lambda:defaultdict(int));groups=defaultdict(list)
    for r in labels:
        key=(r["status"],r["method"],r["type"],int(r["horizon"]))
        if r["excluded"]:exclusions[key][r["excluded"]]+=1;continue
        for k in METRICS+["benchmark"]:r[k]=num(r[k])
        groups[key].append(r)
    curves=read_csv("curves.csv.gz");curve_groups=defaultdict(list)
    for r in curves:
        for k in ["cost","at","equity","cash","exposure"]:r[k]=num(r[k])
        curve_groups[(r["status"],r["method"],int(r["cost"]))].append(r)
    picks=read_csv("picks.csv.gz");pick_sets=defaultdict(dict);calendar=sorted({r["date"] for r in picks})
    for r in picks:
        key=(r["status"],r["method"],r["type"])
        pick_sets[key].setdefault(r["date"],[]).append(r["symbol"])
    result={"version":raw["version"],"period":raw["period"],"methods":raw["methods"],"periods":{k:list(v) for k,v in PERIODS.items()},
            "datasetSHA256":raw["datasetSHA256"],"rankingAudits":raw["audits"],
            "notes":{"market":"fixed stable/watch, not historical macro observations",
                     "universe":"current 505 constituents/instruments and current sector classification",
                     "sell":"sale next open vs same holding sold horizon close; cash interest zero, no shorts",
                     "precision":"fraction of sell picks whose horizon close is below next-open price, not recall across all falling stocks",
                     "samples":"overlapping observations; paired complete TOP3 dates; 63-trading-day block intervals",
                     "screening":"five alternatives, ten stable primary comparisons; no tuning after results",
                     "promotionApproved":False},"scenarios":{}}
    paired_daily=[]
    for status in ["stable","watch"]:
        result["scenarios"][status]={}
        for method in raw["methods"]:
            out={"label":NAMES[method],"frequency":raw["scenarios"][status][method]["frequency"],
                 "outcomes":{},"paired":{},"accounts":{},"changedDays":{}}
            for side in ["buy","sell"]:
                base=pick_sets[(status,"baseline",side)];current=pick_sets[(status,method,side)]
                out["changedDays"][side]=sum(set(v)!=set(base.get(d,[])) for d,v in current.items())
            for period,(start,end) in PERIODS.items():
                out["outcomes"][period]={};out["paired"][period]={}
                for side in ["buy","sell"]:
                    out["outcomes"][period][side]={};out["paired"][period][side]={}
                    for horizon in [20,63]:
                        key=(status,method,side,horizon)
                        rows=[r for r in groups[key] if start<=r["date"]<=end and r["endDate"]<=end]
                        reference=[r for r in groups[(status,"baseline",side,horizon)] if start<=r["date"]<=end and r["endDate"]<=end]
                        metrics={}
                        for cost in [1,2]:
                            data=cost_rows(rows,cost);metrics[str(cost)]=aggregate(data)
                        out["outcomes"][period][side][str(horizon)]={"costs":metrics}
                        if period=="full":
                            expected=raw["scenarios"][status][method]["outcomes"][side][str(horizon)]
                            for metric in ["dateBalancedNet","dateBalancedExcess","dateBalancedAvoidance","downsidePrecision","medianNet","p10Net","meanAdverse"]:
                                close(metrics["1"].get(metric),expected.get(metric))
                        metric="excess" if side=="buy" else "avoidance"
                        q=paired(rows,reference,metric,calendar)
                        if method!="baseline":
                            for r in q.get("daily",[]):paired_daily.append({"status":status,"method":method,"period":period,"side":side,"horizon":horizon,**r})
                        q.pop("daily",None)
                        if side=="sell":
                            a,b=daily(rows),daily(reference);common=sorted(d for d in a.keys()&b.keys() if a[d]["count"]==b[d]["count"]==3)
                            q["precisionDelta"]=mean([a[d]["down"]-b[d]["down"] for d in common])
                        out["paired"][period][side][str(horizon)]=q
                out["accounts"][period]={}
                for cost in [1,2]:
                    report=next(a for a in raw["scenarios"][status][method]["accounts"] if a["cost"]==cost)
                    q=account_period(curve_groups[(status,method,cost)],report,start,end)
                    if period=="full":
                        close(q["cagr"],report["cagr"])
                        close(q["maxDrawdown"],report["maxDrawdown"])
                        q={**report,**q}
                    out["accounts"][period][str(cost)]=q
            result["scenarios"][status][method]=out
    spy=spy_rows()
    result["benchmark"]={str(cost):benchmark_report(spy,cost) for cost in [1,2]}
    result["postHocExposureDiagnostics"]={}
    for status in ["stable","watch"]:
        result["postHocExposureDiagnostics"][status]={}
        for method in raw["methods"]:
            result["postHocExposureDiagnostics"][status][method]={}
            for cost in [1,2]:
                account=next(a for a in raw["scenarios"][status][method]["accounts"] if a["cost"]==cost)
                result["postHocExposureDiagnostics"][status][method][str(cost)]=exposure_controls(curve_groups[(status,method,cost)],spy,account,cost)
    result["evidenceChecks"]={}
    for method in raw["methods"][1:]:
        s=result["scenarios"]["stable"][method];w=result["scenarios"]["watch"][method]
        base=result["scenarios"]["stable"]["baseline"]
        buy=s["paired"]["full"]["buy"]["63"];sell=s["paired"]["full"]["sell"]["20"]
        checks={
            "buyPrimaryAdjustedIntervalAboveZero":buy.get("uncertainty",{}).get("familyAdjustedCI",[None])[0] is not None and buy["uncertainty"]["familyAdjustedCI"][0]>0,
            "buyRecentDeltaPositive":s["paired"]["recent"]["buy"]["63"].get("delta",0)>0,
            "buyWatchFullAndRecentNonnegative":all(w["paired"][p]["buy"]["63"].get("delta",-1)>=0 for p in ["full","recent"]),
            "buyPositiveFullAndRecentExcess":all(s["outcomes"][p]["buy"]["63"]["costs"]["1"].get("dateBalancedExcess",-1)>0 for p in ["full","recent"]),
            "accountBothCostsCagrNotWorse":all(s["accounts"]["full"][str(c)]["cagr"]>=base["accounts"]["full"][str(c)]["cagr"] for c in [1,2]),
            "accountBothCostsDrawdownNotWorse":all(s["accounts"]["full"][str(c)]["maxDrawdown"]<=base["accounts"]["full"][str(c)]["maxDrawdown"] for c in [1,2]),
            "sellPrimaryAdjustedIntervalAboveZero":sell.get("uncertainty",{}).get("familyAdjustedCI",[None])[0] is not None and sell["uncertainty"]["familyAdjustedCI"][0]>0,
            "sellRecentDeltaAndPrecisionPositive":s["paired"]["recent"]["sell"]["20"].get("delta",-1)>0 and s["paired"]["recent"]["sell"]["20"].get("precisionDelta",-1)>0,
            "sellWatchFullAndRecentNonnegative":all(w["paired"][p]["sell"]["20"].get("delta",-1)>=0 for p in ["full","recent"])
        }
        result["evidenceChecks"][method]=checks
    f=io.StringIO(newline="")
    fields=["status","method","period","side","horizon","date","delta","candidate","baseline"]
    writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(paired_daily)
    data=f.getvalue().encode()
    if write_outputs:(OUT/"paired-daily.csv.gz").write_bytes(gzip.compress(data,mtime=0))
    else:assert gzip.decompress((OUT/"paired-daily.csv.gz").read_bytes())==data,"Paired rows differ"
    result["analysisSourceSHA256"]=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return result
def report(result):
    lines=["# 매수·매도 TOP3 보완 비교 — 2026-10-05","",
           "2017-10-02~2026-10-02, 2,263거래일, 현재 505개 고정 OHLC로 운영 순위와 고정 후보5개를 비교했다.",
           "가격 SHA256은 이전 연구와 동일하다. 기존 55일 진입/보유 규칙과 운영 계좌는 변경하지 않았다.","",
           "## 매수 TOP3: 같은 날짜의 63거래일 SPY 초과수익","",
           "다음 거래일 시가 진입을 가정한 고정기간 관찰이다. **대기 후보를 포함하며 실제 매매 계좌 수익률이 아니다.**",
           "비용은 매수/매도 각각 수수료0.05%와 불리한 슬리피지0.05%. 아래 표는 stable 가정, 날짜별 균등 평균이다.","",
           "| 방식 | 전체 초과수익 | 2020–2022 | 2023년 이후 | 기준선 대비 짝 비교 | 95% 블록 구간 |",
           "| --- | ---: | ---: | ---: | ---: | --- |"]
    for method in result["methods"]:
        r=result["scenarios"]["stable"][method];q=r["paired"]["full"]["buy"]["63"];ci=q.get("uncertainty",{}).get("ci95")
        effect="기준선" if method=="baseline" else pp(q.get("delta"))
        interval="—" if not ci or method=="baseline" else f"{pp(ci[0])} ~ {pp(ci[1])}"
        vals=[r["outcomes"][p]["buy"]["63"]["costs"]["1"].get("dateBalancedExcess") for p in ["full","middle","recent"]]
        lines.append(f"| {NAMES[method]} | {' | '.join(pp(v) for v in vals)} | {effect} | {interval} |")
    lines+=["","## 매도 TOP3: 보유 주식을 팔았을 때와 계속 보유했을 때의 차이","",
            "기존 보유 주식을 신호 다음 시가에 매도한 현금과, 같은 주식을 20번째 종가까지 보유 후 매도한 현금의 차이다.",
            "양수는 매도가 유리, 음수는 팔아서 상승을 놓친 경우다. 공매도 수익이나 전체 하락 종목의 recall이 아니다.","",
            "| 방식 | 전체 매도 효과 | 2023년 이후 효과 | 전체 하락 적중률 | 기준선 대비 짝 비교 | 95% 블록 구간 |",
            "| --- | ---: | ---: | ---: | ---: | --- |"]
    for method in result["methods"]:
        r=result["scenarios"]["stable"][method];v=r["outcomes"]["full"]["sell"]["20"]["costs"]["1"]
        recent=r["outcomes"]["recent"]["sell"]["20"]["costs"]["1"];q=r["paired"]["full"]["sell"]["20"]
        ci=q.get("uncertainty",{}).get("ci95")
        interval="—" if not ci or method=="baseline" else f"{pp(ci[0])} ~ {pp(ci[1])}"
        lines.append(f"| {NAMES[method]} | {pp(v.get('dateBalancedAvoidance'))} | {pp(recent.get('dateBalancedAvoidance'))} | {pct(v.get('downsidePrecision'))} | {'기준선' if method=='baseline' else pp(q.get('delta'))} | {interval} |")
    lines+=["","## 실제 buy만 거래한 보조 계좌","",
            "매일 선정된 매수 TOP3 중 실제 buy 조건을 충족한 종목만 다음 시가에 주문한다. 대기 후보는 거래하지 않는다.",
            "위험1%, 최대5종목·종목20%·동일업종2개·정수주식, 기존 손절/청산 규칙을 동일하게 적용한다.",
            "모든 보유 종목은 holding 판단으로 관리하며, 매도 TOP3 밖이라고 위험 대응을 생략하지 않는다.",
            "이 계좌는 이전 PR33의 ‘전체 buy 주문’ 계좌와 대상이 다르므로 그 CAGR과 직접 대조하지 않는다.","",
            "| 방식 | CAGR | 최대낙폭 | 비용2배 CAGR | 비용2배 낙폭 | 진입 횟수 | 최대 이익 종목 / 이익 비중 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | --- |"]
    for method in result["methods"]:
        r=result["scenarios"]["stable"][method];a=r["accounts"]["full"]["1"];b=r["accounts"]["full"]["2"]
        issuer=a.get("topIssuer",{}).get("symbol","—")
        lines.append(f"| {NAMES[method]} | {pct(a['cagr'])} | {pct(a['maxDrawdown'])} | {pct(b['cagr'])} | {pct(b['maxDrawdown'])} | {a['entries']} | {issuer} / {pct(a.get('topIssuerProfitShare'))} |")
    spy=result["benchmark"]["1"]
    lines.append(f"| SPY 가격 보유 | {pct(spy['cagr'])} | {pct(spy['maxDrawdown'])} | {pct(result['benchmark']['2']['cagr'])} | {pct(result['benchmark']['2']['maxDrawdown'])} | 1 | — |")
    lines+=["","동점 보완 계좌의 수익/낙폭 개선은 유망하지만, 매수63일의 후보 초과수익 차이의 95% 구간은 0을 포함했다.",
            "최근 stable 구간의 후보 평균 차이는 음수이며, watch 가정의 최근 계좌 CAGR도 기준선보다 낮았다.",
            "따라서 후보 선정 우위나 운영 채택을 확증하지 않는다. 거래량/업종을 점수 앞에 두는 이번 고정 방식도 채택하지 않는다.",
            "매도 후보의 평균 매도 효과는 모든 방식에서 음수이며, 개선 후보들의 차이 구간도 0을 포함했다.",
            "매도TOP3는 즉시 매도의 수익성을 보증하지 않는다. 이미 보유한 종목의 손절·위험 대응과 순위 선택 효과를 구분한다.",
            "","## 노출을 맞춘 보조 진단","",
            "결과를 본 뒤 해석을 돕기 위해 추가한 통제이며, 후보/평가 기준을 재튜닝하지 않았다.",
            "평균 노출을 초기 SPY 투자 비중으로 고정한 현금+SPY와, 전날 실제 노출을 추종한 현금+SPY를 따로 비교한다.",
            "평균 노출은 사후 값이다. 전날 노출 추종은 당일/미래 노출을 쓰지 않지만 매일 리밸런싱 비용을 0으로 둔 진단 경로다.",
            "| stable 방식 | 실제 계좌 CAGR | 평균 노출 | 평균 비중 초기 SPY+현금 CAGR | 전날 노출 추종 CAGR |",
            "| --- | ---: | ---: | ---: | ---: |"]
    for method in result["methods"]:
        a=result["scenarios"]["stable"][method]["accounts"]["full"]["1"];d=result["postHocExposureDiagnostics"]["stable"][method]["1"]
        lines.append(f"| {NAMES[method]} | {pct(a['cagr'])} | {pct(a['meanExposure'])} | {pct(d['staticSpyCashCagr'])} | {pct(d['priorDayExposureSpyCashCagr'])} |")
    lines+=["","종목beta/업종·진입/손절/청산·실행 비용의 차이가 함께 남으므로 차이를 순수 종목 선택 alpha로 부르지 않는다.",
            "","![고정 후보의 순위·계좌 비교](comparison.png)","","## 불확실성과 채택 판단","",
            "95% 구간은 종목 관측을 독립으로 세지 않고, 같은 성숙 날짜의 완전한 TOP3 평균을 짝 비교한 63거래일 moving-block bootstrap 2,000회다.",
            "계산은 실제 SPY 거래일 달력에 맞추며 제외 날짜를 0으로 대체하지 않는다.",
            "후보5개 × stable 매수63일/매도20일 주요 비교10개에 대한 Bonferroni 구간도 results.json에 기록한다.",
            "기간별 수익·비용2배·watch 가정·계좌 낙폭·이익 집중도를 함께 보아야 한다.",
            "시간 분할은 이미 알려진 과거를 나눈 사후 감사다. 진정한 미관측 검증으로 주장하지 않는다.","",
            "## 한계","",
            "- 과거 발표 시점 신용 자료가 없어 stable/watch는 고정 조건부 시나리오다.",
            "- 현재 생존 구성과 현재 업종을 과거에 적용했고 상장폐지/당시 구성 변화는 복원하지 못했다.",
            "- 업종 변수는 현재 구성 종목의 당시 63일 동일가중 수익률에서 SPY를 뺀 대리변수이며 자신은 제외했다.",
            "  YSN의 비공개 Sector Gate 공식이나 실제 과거 업종 ETF를 복제한 것이 아니다.",
            "- quote OHLC의 공급자 수정/분할 조정이 가능하다. 배당·세금·환율·현금 이자는 제외했다.",
            "- 이 결과는 단기 순위/후속 가격 검증이며 AI 6개월/1년 가격 예측이나 MAPE의 개선 증거가 아니다.",
            "- 임계값 재튜닝, 생산 순위 변경, 자동 승격, 기존 forward 원장 변경은 포함하지 않았다.","",
            "## 재현과 검증","",
            "같은 가격 번들을 research/history/entry-backtest-2026-10-04/prices.json.gz에 두고 실행한다.","",
            chr(96)*3+"bash","node scripts/test_top3_rankings.cjs",
            "node --max-old-space-size=4096 scripts/backtest_top3_rankings.cjs",
            "python3 scripts/analyze_top3_rankings.py",
            "python3 scripts/analyze_top3_rankings.py --validate-only",chr(96)*3,"",
            "raw-results.json은 운영 선택자와의 순위 감사, 원 규칙 출력과 날짜 캐시 출력의 일치 검사, 계좌 회계 검사를 포함한다.",
            "picks/outcomes/curves/trades 압축 CSV, paired-daily.csv.gz, 입력/코드/출력 SHA256을 보존한다.",
            "날짜 캐시는 검증 결과만 재사용하며 원 지표 공식을 변경하지 않는다.",""]
    return "\n".join(lines)
def plot(result):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    labels=["Current","Tie only","Price/risk","Volume","Sector","Combined"]
    methods=result["methods"];s=result["scenarios"]["stable"];x=np.arange(len(methods));colors=["#93a4b5","#7bb6d1","#f4d06f","#82c7ad","#b2a4e8","#eea89b"]
    fig,axes=plt.subplots(2,2,figsize=(13,8.5),layout="constrained")
    for side,h,metric,title,ax in [
        ("buy","63","dateBalancedExcess","Buy TOP3: 63-day excess over SPY",axes[0,0]),
        ("sell","20","dateBalancedAvoidance","Sell TOP3: 20-day sale vs continued holding",axes[0,1])]:
        full=[s[m]["outcomes"]["full"][side][h]["costs"]["1"][metric]*100 for m in methods]
        recent=[s[m]["outcomes"]["recent"][side][h]["costs"]["1"][metric]*100 for m in methods]
        ax.bar(x-.18,full,.36,color=colors,label="2017-2026");ax.bar(x+.18,recent,.36,color=colors,alpha=.45,hatch="//",label="2023-2026")
        ax.axhline(0,color="#687789",lw=.7);ax.set_xticks(x,labels);ax.set_ylabel("Percentage points");ax.set_title(title);ax.legend(frameon=False)
    for cost,style in [(1,"-"),(2,"--")]:
        axes[1,0].plot(x,[s[m]["accounts"]["full"][str(cost)]["cagr"]*100 for m in methods],style,marker="o",label=f"CAGR, cost {cost}x")
        axes[1,1].plot(x,[s[m]["accounts"]["full"][str(cost)]["maxDrawdown"]*100 for m in methods],style,marker="o",label=f"Drawdown, cost {cost}x")
    axes[1,0].axhline(result["benchmark"]["1"]["cagr"]*100,color="#7f8792",linestyle=":",label="SPY price hold")
    for ax,title in [(axes[1,0],"Only actual buy signals traded"),(axes[1,1],"Account maximum drawdown")]:
        ax.set_xticks(x,labels);ax.set_ylabel("Percent");ax.set_title(title);ax.legend(frameon=False)
    for ax in axes.flat:ax.spines[["top","right"]].set_visible(False);ax.grid(axis="y",alpha=.15);ax.tick_params(axis="x",labelsize=9)
    fig.suptitle("TOP3 ranking comparison | Fixed stable assumption | Same entry/exit rules",fontsize=15)
    fig.savefig(OUT/"comparison.png",dpi=160);plt.close(fig)
def main():
    p=argparse.ArgumentParser();p.add_argument("--validate-only",action="store_true");args=p.parse_args()
    result=build(write_outputs=not args.validate_only)
    if args.validate_only:
        stored=json.loads((OUT/"results.json").read_text())
        assert stored==result,"Analysis differs from stored results"
        assert (OUT/"README.md").read_text()==report(result),"Report differs"
        print(json.dumps({"validated":True,"rankingAudits":result["rankingAudits"],"methods":len(result["methods"])}))
    else:
        (OUT/"results.json").write_text(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False)+"\n")
        (OUT/"README.md").write_text(report(result));plot(result)
        for method in result["methods"]:
            r=result["scenarios"]["stable"][method]
            print(json.dumps({"method":method,"buy63":r["outcomes"]["full"]["buy"]["63"]["costs"]["1"],
                              "sell20":r["outcomes"]["full"]["sell"]["20"]["costs"]["1"],
                              "account":r["accounts"]["full"]["1"]},ensure_ascii=False))
if __name__=="__main__":main()
