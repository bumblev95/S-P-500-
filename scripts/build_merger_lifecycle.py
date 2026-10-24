"""Audit the frozen outcome layer or export a fully evidenced origin ledger."""

import argparse
import json
from pathlib import Path

from audit_fja_sp500_quarantine import build_audit as quarantine_audit
from build_pit_sp500_inputs import audit_bundle as pit_audit
from pit_sp500_inputs import InputError, PITInputs, canonical, sha256, write_frozen
from research_merger_lifecycle import LifecycleInputs, VERSION

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "research/joint-indicator/merger-lifecycle-v1"
PIT_FOLDER = ROOT / "research/joint-indicator/pit-inputs-v1"
QUARANTINE = ROOT / "research/joint-indicator/pit-quarantine-fja-v1"


def audit(folder=FOLDER):
    folder = Path(folder).resolve()
    manifest = json.loads((folder / "manifest.json").read_text())
    protocol = json.loads((folder / "PROTOCOL.json").read_text())
    if (manifest["version"] != VERSION or protocol["version"] != VERSION
            or protocol.get("researchOnly") is not True
            or protocol.get("modelTrainingAllowed") is not False
            or protocol.get("productionChangesAllowed") is not False):
        raise InputError("Frozen research-only protocol required")
    for scope, parent in (("bundleFiles", folder), ("preservedFiles", ROOT)):
        for relative, digest in manifest[scope].items():
            path = (parent / relative).resolve()
            if not path.is_relative_to(parent) or sha256(path.read_bytes()) != digest:
                raise InputError("Frozen/preserved file changed: " + relative)
    lifecycle = LifecycleInputs.load(folder)
    previous, _ = pit_audit()
    candidate, _ = quarantine_audit()
    for path, report in ((PIT_FOLDER / "coverage-audit.json", previous),
                         (QUARANTINE / "coverage-audit.json", candidate)):
        if path.read_bytes() != canonical(report):
            raise InputError("Earlier audit no longer replays")
    return dict(version=VERSION, researchOnly=True, modelTrainingAllowed=False,
        productionChangesAllowed=False, sourceResearchHead=manifest["sourceResearchHead"],
        lifecycleDatasetHash=lifecycle.dataset_hash, status="blocked_missing_lifecycle_and_origin_evidence",
        originCount=previous["originCount"], readyOriginCount=0,
        originalPITReadyOriginCount=previous["readyOriginCount"],
        originalQuarantineReadyOriginCount=candidate["readyOriginCount"],
        realComputedOutcomeCount=0, normalizedAssetCount=len(lifecycle.assets),
        normalizedActionCount=len(lifecycle.actions), targetQuoteCount=len(lifecycle.data["quotes"]),
        preservedFileCount=len(manifest["preservedFiles"]),
        observedTerms=lifecycle.data["observations"],
        unresolvedPolicy="Observed merger terms are not confirmed complete shareholder wealth or settled contingent rights",
        metricPolicy=protocol["metricPolicy"], cashPolicy=protocol["cashPolicy"],
        requests=[dict(request=r["request"], complete=False, preservedOriginBlockers=r["blockers"],
            blockers=["incomplete_origin_cohort", "missing_permanent_issue_mappings",
                      "missing_complete_action_and_distribution_coverage", "missing_settlement_and_rights_evidence",
                      "missing_exact_horizon_valuations_and_session_timestamps"],
            totalReturnMetricsAllowed=False, originalPriceMetricsAllowed=False)
            for r in previous["requests"]])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, default=FOLDER)
    parser.add_argument("--pit-folder", type=Path, default=PIT_FOLDER)
    parser.add_argument("--origin")
    parser.add_argument("--target-at")
    parser.add_argument("--evaluated-at")
    parser.add_argument("--output", type=Path)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--audit", action="store_true")
    modes.add_argument("--verify", action="store_true")
    modes.add_argument("--export-outcomes", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.export_outcomes:
            if not all((args.origin, args.target_at, args.evaluated_at, args.output)):
                raise InputError("Explicit origin, target session timestamp, evaluation timestamp and output required")
            pit = PITInputs.load(args.pit_folder)
            cohort = pit.snapshot(args.origin)
            lifecycle = LifecycleInputs.load(args.folder)
            ledger = lifecycle.ledger(pit, cohort, args.target_at, args.evaluated_at)
            if not ledger["totalReturnMetricsAllowed"]:
                raise InputError("Incomplete lifecycle evidence; no outcomes exported")
            write_frozen(args.output, ledger)
            print(json.dumps(dict(version=VERSION, retainedPopulation=ledger["retainedPopulation"],
                totalReturnMetricsAllowed=True, originalPriceMetricsAllowed=ledger["originalPriceMetricsAllowed"])))
        else:
            report = audit(args.folder)
            path = args.folder / "coverage-audit.json"
            if args.verify:
                if path.read_bytes() != canonical(report):
                    raise InputError("Frozen lifecycle audit does not replay exactly")
            else:
                write_frozen(path, report)
            print(json.dumps({k: report[k] for k in ("version", "status", "originCount", "readyOriginCount",
                "realComputedOutcomeCount", "preservedFileCount")}))
        return 0
    except (InputError, KeyError, OSError, ValueError) as exc:
        print(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
