"""Predeclared stock experiments: dated financial changes and OOS calibration."""
from collections import Counter
from datetime import date
import math
import os
os.environ.setdefault('OMP_NUM_THREADS', '2')
import numpy as np
from sklearn.linear_model import LogisticRegression

DYNAMIC_FIELDS = ['annualGrowthAcceleration', 'annualNetMarginChange',
                  'annualCashflowMarginChange', 'annualLeverageChange',
                  'cashflowLessProfitMargin', 'quarterGrowthAcceleration',
                  'quarterNetMarginChange']
EXPERIMENTS = ('independentReturn', 'secDynamics')
LABELS = (-1, 0, 1)


def financial_changes(annual, quarterly, day):
    """Compare distinct fiscal periods using only versions published before day.

    Annual restatements of the same period are not a new growth observation.
    Historical valuation needs vintage shares/prices and is deliberately absent.
    """
    def pair(rows, max_age, min_gap, max_gap):
        available = [r for r in rows if r['availableDate'] < day and r['periodEnd'] < day]
        if not available:
            return None, None
        latest = max(available, key=lambda r: (r['periodEnd'], r['availableDate']))
        if (date.fromisoformat(day) - date.fromisoformat(latest['periodEnd'])).days > max_age:
            return None, None
        prior = [r for r in available if min_gap <=
                 (date.fromisoformat(latest['periodEnd']) - date.fromisoformat(r['periodEnd'])).days <= max_gap]
        return latest, max(prior, key=lambda r: (r['periodEnd'], r['availableDate'])) if prior else None

    def delta(a, b, field, other=None):
        x = (a or {}).get(field); y = (b or {}).get(other or field)
        return float(x-y) if all(isinstance(v, (int, float)) and math.isfinite(v) for v in (x, y)) else float('nan')

    a, b = pair(annual, 550, 330, 400)
    q, p = pair(quarterly, 200, 60, 120)
    values = [delta(a, b, field) for field in ('revenueGrowth', 'netMargin', 'cashflowMargin', 'liabilitiesToAssets')]
    values += [delta(a, a, 'cashflowMargin', 'netMargin'),
               delta(q, p, 'quarterRevenueGrowth'), delta(q, p, 'quarterNetMargin')]
    through = max((r['availableDate'] for r in (a, b, q, p) if r), default=None)
    return values, through


def calibrate_direction(raw, previous, name, origin):
    """Logistic recalibration on already realized, out-of-sample raw scores.

    The decision is fixed argmax (no holdout threshold search). Each historical
    date has equal total weight. Insufficient calibration stays visibly raw.
    """
    prior = [r for r in previous if r['targetDate'] < origin and r.get(name+'Scores')]
    dates = sorted({r['origin'] for r in prior})[-8:]
    prior = [r for r in prior if r['origin'] in dates]
    y = [1 if r['y'] > 1.02 else -1 if r['y'] < .98 else 0 for r in prior]
    counts = Counter(y)
    status = dict(calibrated=False, dates=len(dates), n=len(prior),
                  targetThrough=max((r['targetDate'] for r in prior), default=None),
                  method='fixed argmax; raw scores, insufficient realized calibration')
    probability = np.asarray(raw, dtype=float)
    if len(dates) >= 3 and all(counts[label] >= 20 for label in LABELS):
        x = np.log(np.clip([r[name+'Scores']['raw'] for r in prior], 1e-6, 1.))
        sizes = Counter(r['origin'] for r in prior)
        weights = [len(prior)/(len(dates)*sizes[r['origin']]) for r in prior]
        model = LogisticRegression(C=1., max_iter=300, random_state=23)
        model.fit(x, y, sample_weight=weights)
        calibrated = model.predict_proba(np.log(np.clip(probability, 1e-6, 1.)))
        probability = calibrated[:, [list(model.classes_).index(label) for label in LABELS]]
        status.update(calibrated=True, method='date-weighted OOS logistic calibration; fixed argmax')
    details = [dict(raw=[float(v) for v in r], down=float(p[0]), flat=float(p[1]), up=float(p[2]),
                    chosen=LABELS[int(np.argmax(p))], **status) for r, p in zip(raw, probability)]
    return details
