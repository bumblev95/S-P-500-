"""Run the byte-pinned legacy estimators, without their build/publish functions.

This file runs in its own process so imports resolve to the five frozen modules
in this directory, never to newer production modules in scripts/.
"""
import gzip
import json
import math
import sys
from pathlib import Path

import numpy as np
import build_environment_research as v5
import build_forecasts as trend


def generate(bundle):
    origin = bundle['origin']
    histories = bundle['histories']
    members = bundle['members']
    if any(not rows or rows[-1]['date'] != origin or
           any(r['date'] > origin for r in rows) for rows in histories.values()):
        raise ValueError('History must end at origin, without future target inputs')
    context = {}
    for symbol in v5.PROXIES:
        values = v5.features(histories[symbol])
        context[symbol] = dict(features=values, dates=np.array(sorted(values)))
    universe = {s: histories[s] for s in sorted(members)
                if s in histories and len(histories[s]) >= 200}
    # v5's 21-session profile consumes z, not the SEC/earnings w fields.
    # CIK deduplication, Friday training origins and targetDate < origin are
    # retained exactly; no other horizon or historical candidate is evaluated.
    data, latest = v5.records(universe, context, 21, 'stocks', {
        'symbolCIKs': {s: v['cik'] for s, v in members.items()}})
    train = [r for r in data if r['targetDate'] < origin]
    current = [latest[s] for s in sorted(latest) if latest[s]['origin'] == origin]
    if len(train) < 300 or not current:
        raise ValueError('Insufficient legacy v5 training/current rows')
    model = v5.fit_horizon(train, 21)
    predictions, scores = model.predict(current)
    v5_rows = []
    for row, ratio, score in zip(current, predictions, scores):
        point = row['anchor'] * float(ratio)
        if not math.isfinite(point) or point <= 0 or row['contextThrough'] >= origin:
            raise ValueError('Invalid legacy point or future context')
        v5_rows.append(dict(model=v5.MODEL, assetClass='stocks', symbol=row['symbol'],
                            asOf=origin, horizon='21', anchor=row['anchor'],
                            horizonModel=point, horizonDirectionScores=score))
    trend_rows = []
    for row in bundle['priceRows']:
        if row['date'] != origin:
            raise ValueError('Trend input is not the fixed origin snapshot')
        prediction = trend.predict(row, 21)
        if prediction:
            trend_rows.append({k: v for k, v in dict(
                model=trend.MODEL, symbol=row['symbol'], asOf=origin,
                **prediction).items() if k in trend.FIELDS})
    return dict(v5=v5_rows, trend=trend_rows,
                trainingRows=len(train), trainingOrigins=len({r['origin'] for r in train}),
                trainTargetThrough=max(r['targetDate'] for r in train),
                contextThrough=max(r['contextThrough'] for r in current),
                profile=v5.HORIZON_PROFILES[21],
                missingV5=sorted(set(members) - {r['symbol'] for r in v5_rows}))


if __name__ == '__main__':
    bundle = json.loads(gzip.decompress(Path(sys.argv[1]).read_bytes()))
    result = generate(bundle)
    Path(sys.argv[2]).write_text(json.dumps(result, allow_nan=False, sort_keys=True) + '\n')
