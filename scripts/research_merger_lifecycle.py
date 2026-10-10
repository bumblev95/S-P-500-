"""Research-only shareholder wealth accounting after corporate actions.

Separate outcome layer: never selects a cohort, splices tickers, trains a model,
or treats a successor's price as the extinguished security's price target.
Gross USD wealth; paid cash stays idle, no interest or dividend reinvestment.
"""

from __future__ import annotations

import copy
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path

from pit_sp500_inputs import (InputError, InputBlocked, PITInputs, VERSION as PIT_VERSION,
    assert_evaluation_population, canonical, finite, sha256, timestamp)

VERSION = "shareholder-lifecycle-v1"
DOMAINS = {"corporate_actions", "distributions", "terminal_status", "identity"}


def number(value, positive=False):
    if not finite(value) or positive and value <= 0:
        raise InputError("Finite nonnegative amount (positive where required) expected")
    return Decimal(str(value))


class LifecycleInputs:
    def __init__(self, data, folder=None, *, allow_synthetic=False):
        self.data = copy.deepcopy(data)
        if (data.get("version") != VERSION or data.get("schemaVersion") != 1
                or data.get("researchOnly") is not True or data.get("policyId") != VERSION):
            raise InputError("Research-only lifecycle schema required")
        # Reuse the frozen source/payload clock boundary; no provider shortcuts.
        carrier = dict(schemaVersion=1, version=PIT_VERSION, sources=data["sources"],
            securities=[], baselines=[], events=[], coverage=[], prices=[], outcomes=[])
        self.evidence = PITInputs(carrier, folder, allow_synthetic=allow_synthetic)
        self.assets = self._unique(data["assets"], "securityId")
        self.actions = self._unique(data["actions"], "actionId")
        self._unique(data["coverage"], "coverageId")
        self._validate()
        self.dataset_hash = sha256(canonical(self.data))

    @classmethod
    def load(cls, folder):
        folder = Path(folder)
        return cls(json.loads((folder / "lifecycle-inputs.json").read_text()), folder)

    @staticmethod
    def _unique(rows, key):
        result = {}
        for row in rows:
            value = row.get(key)
            if not isinstance(value, str) or not value or value in result:
                raise InputError("Missing/duplicate " + key)
            result[value] = row
        return result

    def _record(self, row):
        source = self.evidence._source(row)
        if not row.get("evidenceLocator"):
            raise InputError("Original row/notice locator required")
        return source

    def _validate(self):
        permanent = set()
        for asset in self.assets.values():
            self._record(asset)
            if asset.get("kind") not in {"equity", "right"}:
                raise InputError("Unsupported asset type")
            if asset.get("verified") is True:
                key = asset.get("permanentId", {})
                if (key.get("scheme") not in {"PERMNO", "GVKEY_IID", "provider_issue_id"}
                        or not key.get("value") or not key.get("provider")
                        or not asset.get("identityEvidence")):
                    raise InputError("Permanent issue identity evidence required; ticker/CIK insufficient")
                identity = (key["provider"], key["scheme"], key["value"])
                if identity in permanent:
                    raise InputError("Duplicate permanent issue mapping")
                permanent.add(identity)
        for action in self.actions.values():
            self._record(action)
            if (action.get("securityId") not in self.assets or not action.get("eventKey")
                    or action.get("kind") not in {"distribution", "split", "exchange", "zero_recovery"}
                    or action.get("status") not in {"completed", "announced", "unresolved", "cancelled"}):
                raise InputError("Invalid lifecycle action")
            if action["status"] == "cancelled" and (not action.get("cancellationEvidence")
                    or timestamp(action["knownAt"]) < timestamp(action["cancelledAt"])):
                raise InputError("Cancelled action requires dated cancellation evidence")
            if action["status"] == "completed":
                if (not action.get("settlementEvidence") or action.get("termsVerified") is not True
                        or timestamp(action["settledAt"]) < timestamp(action["effectiveAt"])
                        or timestamp(action["knownAt"]) < timestamp(action["settledAt"])):
                    raise InputError("Completed action requires observed settlement and clocks")
                if action.get("entitlementConvention") != "effective_at_per_unit_verified":
                    raise InputError("Exact per-unit entitlement/fractional treatment required")
            if action["kind"] == "split":
                number(action.get("ratio"), positive=True)
                if action.get("deliveries"):
                    raise InputError("Split cannot also deliver consideration")
            else:
                for leg in action.get("deliveries", []):
                    number(leg.get("perUnit"), positive=True)
                    if leg.get("kind") == "cash":
                        if leg.get("currency") != "USD":
                            raise InputError("USD only; no implicit FX conversion")
                    elif leg.get("kind") == "asset":
                        if leg.get("securityId") not in self.assets:
                            raise InputError("Unknown delivered security/right identity")
                        if leg["securityId"] == action["securityId"]:
                            raise InputError("Self delivery requires an explicit split instead")
                    else:
                        raise InputError("Unknown consideration leg")
                if action["kind"] == "zero_recovery":
                    if action.get("deliveries") or action.get("zeroRecoveryConfirmed") is not True:
                        raise InputError("Zero requires confirmed cancellation with no residual rights")
                elif not action.get("deliveries"):
                    raise InputError("Consideration cannot be empty or guessed zero")
            if action.get("supersedes"):
                old = self.actions.get(action["supersedes"])
                compatible_kind = old is not None and (old["kind"] == action["kind"]
                    or {old["kind"], action["kind"]} <= {"exchange", "zero_recovery"})
                if (old is None or not compatible_kind
                        or any(old[k] != action[k] for k in ("eventKey", "securityId", "effectiveAt"))
                        or timestamp(old["knownAt"]) >= timestamp(action["knownAt"])):
                    raise InputError("Invalid lifecycle correction chain")
        quote_keys = set()
        for quote in self.data["quotes"]:
            self._record(quote)
            number(quote.get("close"))
            if (quote.get("securityId") not in self.assets or quote.get("basis") != "unadjusted"
                    or quote.get("currency") != "USD"
                    or timestamp(quote["knownAt"]) < timestamp(quote["effectiveAt"])):
                raise InputError("Unadjusted, dated USD quote required; no double counting actions")
            key = (quote["securityId"], timestamp(quote["effectiveAt"]), timestamp(quote["knownAt"]))
            if key in quote_keys:
                raise InputError("Duplicate quote vintage")
            quote_keys.add(key)
        for row in self.data["coverage"]:
            source = self._record(row)
            if (row.get("securityId") not in self.assets or row.get("completeness") not in {"complete", "partial"}
                    or not row.get("domains") or not set(row["domains"]) <= DOMAINS
                    or not row.get("coverageEvidence")
                    or timestamp(row["from"]) >= timestamp(row["throughExclusive"])
                    or timestamp(row["throughExclusive"]) > timestamp(source["retrievedAt"])):
                raise InputError("Invalid full-lifecycle coverage")
            if row["completeness"] == "complete" and source["temporalQuality"] not in {"certified_point_in_time", "synthetic"}:
                raise InputError("Dated notices cannot certify complete lifecycle coverage")
        for observation in self.data.get("observations", []):
            self._record(observation)
            if observation.get("allowedUse") != "diagnostic_only":
                raise InputError("Unnormalized observations must remain diagnostic only")

    def visible_actions(self, asof, through=None):
        rows = [r for r in self.actions.values() if timestamp(r["knownAt"]) < asof]
        superseded = {r["supersedes"] for r in rows if r.get("supersedes")}
        rows = [r for r in rows if r["actionId"] not in superseded]
        if through is not None:
            rows = [r for r in rows if timestamp(r["effectiveAt"]) <= through]
        keys = [(r["securityId"], timestamp(r["effectiveAt"])) for r in rows]
        if len(keys) != len(set(keys)):
            raise InputError("Ambiguous simultaneous actions; supply evidenced combined consideration")
        event_keys = [r["eventKey"] for r in rows]
        if len(event_keys) != len(set(event_keys)):
            raise InputError("Conflicting action versions need explicit supersession")
        return sorted(rows, key=lambda r: (timestamp(r["effectiveAt"]), r["actionId"]))

    def _identity(self, sid, start, asof):
        asset = self.assets.get(sid)
        return (asset is not None and asset.get("verified") is True
                and timestamp(asset["effectiveAt"]) <= start and timestamp(asset["knownAt"]) < asof)

    def _coverage(self, sid, start, end, asof):
        missing = []
        for domain in sorted(DOMAINS):
            intervals = sorted((timestamp(c["from"]), timestamp(c["throughExclusive"]))
                for c in self.data["coverage"] if c["securityId"] == sid and c["completeness"] == "complete"
                and domain in c["domains"] and timestamp(c["knownAt"]) < asof)
            cursor = start
            for left, right in intervals:
                if left <= cursor < right:
                    cursor = right
            if cursor <= end:
                missing.append("missing_" + domain + "_coverage:" + sid)
        return missing

    def _quote(self, sid, at, asof):
        rows = [q for q in self.data["quotes"] if q["securityId"] == sid
                and timestamp(q["effectiveAt"]) == at and timestamp(q["knownAt"]) < asof]
        return max(rows, key=lambda q: timestamp(q["knownAt"])) if rows else None

    def _follow(self, pit, member, cohort, target, asof, actions):
        sid = member["securityId"]
        result = dict(securityId=sid, origin=cohort["origin"], targetAt=target.isoformat(),
            originSymbol=member["symbol"], status="blocked_lifecycle_evidence", blockers=[],
            totalReturnFactor=None, totalWealthUSD=None, priceFactor=None,
            priceTargetStatus="missing_evidence", cashReceivedUSD=0.0, positions=[], trace=[], unsettledReceivables=[])
        if asof <= target:
            return dict(result, status="pending_outcome", blockers=["target_not_mature"])
        past = pit.past_prices(sid, cohort["origin"])
        if not past:
            return dict(result, blockers=["missing_entry_quote"])
        entry = past[-1]
        if entry["basis"] != "unadjusted" or entry.get("currency") != "USD" or not finite(entry["close"]) or entry["close"] <= 0:
            return dict(result, blockers=["positive_unadjusted_USD_entry_quote_required"])
        start, denominator = timestamp(entry["effectiveAt"]), number(entry["close"], positive=True)
        result["entryQuote"] = dict(sourceId=entry["sourceId"], effectiveAt=entry["effectiveAt"], knownAt=entry["knownAt"], close=entry["close"])
        blockers = []
        if not self._identity(sid, start, timestamp(cohort["cutoff"])):
            blockers.append("missing_origin_permanent_identity:" + sid)
        relevant = [a for a in actions if start < timestamp(a["effectiveAt"]) <= target]
        # No arbitrary ID sorting of same-time A->B->C handoffs.
        for when in {timestamp(a["effectiveAt"]) for a in relevant if a["status"] != "cancelled"}:
            group = [a for a in relevant if timestamp(a["effectiveAt"]) == when and a["status"] != "cancelled"]
            from_ids = {a["securityId"] for a in group}
            to_ids = {l["securityId"] for a in group for l in a.get("deliveries", []) if l["kind"] == "asset"}
            if from_ids & to_ids:
                raise InputError("Same-time dependent actions require evidenced ordering")
        positions, opened, segments = {sid: Decimal(1)}, {sid: start}, []
        cash, original_extinguished, extinguished = Decimal(0), False, set()
        action_ids, quote_refs = [], []
        for action in relevant:
            asset_id, at = action["securityId"], timestamp(action["effectiveAt"])
            if action["status"] == "cancelled":
                continue
            if asset_id in extinguished:
                raise InputError("Later action on an extinguished issue: normalize residual rights or correct termination")
            if asset_id not in positions:
                continue
            units = positions[asset_id]
            action_ids.append(action["actionId"])
            if action["status"] != "completed" or timestamp(action["settledAt"]) > target:
                blockers.append("unsettled_action:" + action["actionId"])
                # Do not invent deliveries from a proposal or a post-horizon payment.
                if action["status"] == "completed":
                    result["unsettledReceivables"].append(dict(actionId=action["actionId"],
                        securityId=asset_id, units=str(units), deliveries=action.get("deliveries", []),
                        settledAt=action["settledAt"], targetValueUSD=None))
                    if action["kind"] in {"exchange", "zero_recovery"}:
                        segments.append((asset_id, opened.pop(asset_id), at))
                        positions.pop(asset_id)
                        extinguished.add(asset_id)
                        original_extinguished = original_extinguished or asset_id == sid
                continue
            result["trace"].append(dict(actionId=action["actionId"], sourceId=action["sourceId"],
                evidenceLocator=action["evidenceLocator"], securityId=asset_id, kind=action["kind"],
                effectiveAt=action["effectiveAt"], settledAt=action["settledAt"], unitsBefore=str(units),
                deliveries=action.get("deliveries", []), ratio=action.get("ratio")))
            if action["kind"] == "split":
                positions[asset_id] *= number(action["ratio"], positive=True)
                continue
            if action["kind"] in {"exchange", "zero_recovery"}:
                segments.append((asset_id, opened.pop(asset_id), at))
                positions.pop(asset_id)
                extinguished.add(asset_id)
                if asset_id == sid:
                    original_extinguished = True
            for leg in action.get("deliveries", []):
                amount = units * number(leg["perUnit"], positive=True)
                if leg["kind"] == "cash":
                    cash += amount
                else:
                    delivered = leg["securityId"]
                    if delivered in extinguished:
                        raise InputError("Extinguished permanent security cannot be resurrected")
                    positions[delivered] = positions.get(delivered, Decimal(0)) + amount
                    opened.setdefault(delivered, at)
        segments.extend((asset_id, opened[asset_id], target) for asset_id in positions)
        for asset_id, left, right in segments:
            if not self._identity(asset_id, left, asof):
                blockers.append("missing_permanent_identity:" + asset_id)
            blockers.extend(self._coverage(asset_id, left, right, asof))
        # Seed notices remain binding until a NEW PIT bundle supplies an evidenced correction.
        for event in pit.visible_events(asof, "delisting"):
            if any(event["securityId"] == held and left < timestamp(event["effectiveAt"]) <= right
                   for held, left, right in segments):
                if event["value"]["settlementStatus"] == "unresolved":
                    blockers.append("unresolved_PIT_terminal_event:" + event["eventId"])
                if not any(a.get("pitEventId") == event["eventId"] and a["securityId"] == event["securityId"]
                           and a["actionId"] in action_ids
                           and a["kind"] in {"exchange", "zero_recovery"} for a in relevant):
                    blockers.append("missing_terminal_handoff:" + event["eventId"])
        wealth, original_value = cash, None
        for asset_id, units in sorted(positions.items()):
            asset = self.assets.get(asset_id)
            quote = self._quote(asset_id, target, asof)
            if asset is not None and asset["kind"] == "right":
                blockers.append("unresolved_contingent_right:" + asset_id)
                quote = None  # Neither a maximum payout nor an assumed zero is a price.
            if quote is None:
                blockers.append("missing_exact_target_valuation:" + asset_id)
            else:
                value = units * number(quote["close"])
                wealth += value
                quote_refs.append(dict(securityId=asset_id, sourceId=quote["sourceId"],
                    evidenceLocator=quote["evidenceLocator"], knownAt=quote["knownAt"], effectiveAt=quote["effectiveAt"]))
                if asset_id == sid:
                    original_value = value
            result["positions"].append(dict(securityId=asset_id, units=str(units),
                closeUSD=quote["close"] if quote else None))
        result.update(blockers=sorted(set(blockers)), cashReceivedUSD=float(cash), quoteProvenance=quote_refs,
            priceTargetStatus="not_applicable_extinguished" if original_extinguished else "missing_evidence")
        if not blockers:
            result.update(status="ready", totalWealthUSD=float(wealth), totalReturnFactor=float(wealth / denominator))
            if not original_extinguished and original_value is not None:
                result.update(priceFactor=float(original_value / denominator), priceTargetStatus="ready")
        return result

    def ledger(self, pit, cohort, target_at, evaluated_at):
        verified = pit.snapshot(cohort["origin"])
        if canonical(cohort) != canonical(verified):
            raise InputError("Lifecycle requires the unchanged complete frozen origin cohort")
        target, asof = timestamp(target_at), timestamp(evaluated_at)
        if target <= timestamp(cohort["cutoff"]):
            raise InputError("Target must follow origin; explicit exchange-session timestamp required")
        actions = self.visible_actions(asof, through=target)
        rows = [self._follow(pit, member, cohort, target, asof, actions) for member in cohort["members"]]
        assert_evaluation_population(cohort, rows)
        ready = bool(rows) and all(r["status"] == "ready" for r in rows)
        price_ready = ready and all(r["priceTargetStatus"] == "ready" for r in rows)
        synthetic = any(s["temporalQuality"] == "synthetic"
                        for s in [*pit.sources.values(), *self.evidence.sources.values()])
        result = dict(version=VERSION, researchOnly=True, modelTrainingAllowed=False,
            productionChangesAllowed=False, cohortHash=cohort["cohortHash"], lifecycleDatasetHash=self.dataset_hash,
            evidenceMode="synthetic_fixture" if synthetic else "verified_source_payloads",
            realResearchEligible=ready and not synthetic,
            origin=cohort["origin"], targetAt=target.isoformat(), evaluatedAt=asof.isoformat(),
            originPopulation=len(cohort["members"]), retainedPopulation=len(rows), rows=rows,
            totalReturnMetricsAllowed=ready, originalPriceMetricsAllowed=price_ready,
            statuses=dict(sorted(Counter(r["status"] for r in rows).items())),
            cashPolicy="USD paid cash held at zero yield through target; gross, no reinvestment/fees/taxes",
            pricePolicy="Original issue only, split-adjusted per initial unit; no successor-price substitution")
        result["ledgerHash"] = sha256(canonical(result))
        return result

    def evaluate(self, pit, cohort, target_at, evaluated_at, forecasts):
        """Optional metrics require two explicit forecast targets; never relabel old predictions."""
        ledger = self.ledger(pit, cohort, target_at, evaluated_at)
        if (forecasts.get("cohortHash") != cohort["cohortHash"] or forecasts.get("origin") != cohort["origin"]
                or timestamp(forecasts["targetAt"]) != timestamp(target_at)):
            raise InputError("Forecast population/target mismatch")
        predictions = forecasts["rows"]
        assert_evaluation_population(cohort, predictions)
        by_id = {r["securityId"]: r for r in predictions}
        for row in predictions:
            for field in ("predictedTotalReturnFactor", "predictedOriginalPriceFactor"):
                if row.get(field) is not None:
                    number(row[field])
        metrics = dict(totalReturnMAEPercentagePoints=None, upRecall=None, downRecall=None,
            originalPriceMAPEPercent=None, totalReturnStatus="blocked_incomplete_lifecycle",
            originalPriceStatus="blocked_missing_or_nonexistent_original_price")
        rows = ledger["rows"]
        if ledger["totalReturnMetricsAllowed"]:
            if all(by_id[r["securityId"]].get("predictedTotalReturnFactor") is not None for r in rows):
                pairs = [(by_id[r["securityId"]]["predictedTotalReturnFactor"], r["totalReturnFactor"]) for r in rows]
                metrics.update(totalReturnStatus="ready", totalReturnMAEPercentagePoints=
                    100 * sum(abs(p-a) for p,a in pairs) / len(pairs))
                for name, check in (("upRecall", lambda x:x>1),("downRecall",lambda x:x<1)):
                    subset = [(p,a) for p,a in pairs if check(a)]
                    metrics[name] = sum(check(p) for p,a in subset)/len(subset) if subset else None
            else:
                metrics["totalReturnStatus"] = "missing_explicit_total_return_forecast"
        if ledger["originalPriceMetricsAllowed"]:
            if any(r["priceFactor"] == 0 for r in rows):
                metrics["originalPriceStatus"] = "undefined_MAPE_zero_price"
            elif all(by_id[r["securityId"]].get("predictedOriginalPriceFactor") is not None for r in rows):
                metrics.update(originalPriceStatus="ready", originalPriceMAPEPercent=100 * sum(
                    abs(by_id[r["securityId"]]["predictedOriginalPriceFactor"] / r["priceFactor"] - 1)
                    for r in rows)/len(rows))
            else:
                metrics["originalPriceStatus"] = "missing_explicit_original_price_forecast"
        return dict(ledger=ledger, metrics=metrics, metricPopulation=len(rows),
            policy="All origin rows retained; no survivor-only metric and no price-to-total-return forecast conversion")
