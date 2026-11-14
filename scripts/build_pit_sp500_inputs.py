"""Validate/audit/export the frozen PIT boundary. No model or service imports."""

import argparse
import json
from pathlib import Path

from pit_sp500_inputs import InputBlocked, InputError, PITInputs, VERSION, canonical, sha256, write_frozen

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "research/joint-indicator/pit-inputs-v1"


def verify_manifest(folder, root=ROOT):
    folder, root = Path(folder).resolve(), Path(root).resolve()
    manifest = json.loads((folder / "manifest.json").read_text())
    if manifest.get("version") != VERSION or not manifest.get("researchOnly"):
        raise InputError("Research-only manifest required")
    for name, expected in manifest["bundleFiles"].items():
        path = (folder / name).resolve()
        if not path.is_relative_to(folder) or sha256(path.read_bytes()) != expected:
            raise InputError("Frozen bundle hash mismatch: " + name)
    for name, expected in manifest["preservedFiles"].items():
        path = (root / name).resolve()
        if not path.is_relative_to(root) or sha256(path.read_bytes()) != expected:
            raise InputError("Preserved prior research changed: " + name)
    protocol = json.loads((folder / "PROTOCOL.json").read_text())
    if (protocol.get("version") != VERSION or protocol.get("researchOnly") is not True
            or protocol.get("modelTrainingAllowed") is not False
            or protocol.get("productionChangesAllowed") is not False):
        raise InputError("Input-only protocol required")
    return manifest, protocol


def audit_bundle(folder=FOLDER, root=ROOT):
    folder = Path(folder)
    manifest, protocol = verify_manifest(folder, root)
    inputs = PITInputs.load(folder)
    requests = json.loads((folder / "origins.json").read_text())
    if requests.get("sourceResearchHead") != manifest["sourceResearchHead"]:
        raise InputError("Origin/source research head mismatch")
    if requests.get("cutoffConvention") != "America/New_York session open; knownAt strictly earlier":
        raise InputError("Origin cutoff convention mismatch")
    dates = sorted({r["origin"] for r in requests["requests"]})
    snapshots = {d: inputs.snapshot(d, require_complete=False) for d in dates}
    reports = []
    for request in requests["requests"]:
        snapshot = snapshots[request["origin"]]
        reports.append(dict(request=request, complete=snapshot["complete"],
                            blockers=snapshot["blockers"], observedSecurityCount=snapshot["securityCount"],
                            cohortHash=snapshot["cohortHash"]))
    complete = all(s["complete"] for s in snapshots.values()) and bool(snapshots)
    report = dict(version=VERSION, registeredAt=protocol["registeredAt"], researchOnly=True,
                  sourceResearchHead=manifest["sourceResearchHead"],
                  datasetHash=inputs.dataset_hash, manifestHash=sha256((folder / "manifest.json").read_bytes()),
                  status="input_boundary_ready" if complete else "blocked_missing_historical_data",
                  modelTrainingAllowed=False, productionChangesAllowed=False,
                  originCount=len(dates), readyOriginCount=sum(s["complete"] for s in snapshots.values()),
                  requestCount=len(reports), fullHistoricalCoverage=complete,
                  blockers=sorted({b for s in snapshots.values() for b in s["blockers"]}),
                  sourceSummary=dict(sources=len(inputs.sources), securities=len(inputs.securities),
                                     events=len(inputs.events), baselines=len(inputs.data["baselines"]),
                                     prices=len(inputs.data["prices"]), outcomes=len(inputs.data["outcomes"]),
                                     completeCoverageAttestations=sum(c["completeness"] == "complete" for c in inputs.data["coverage"])),
                  quarantine=inputs.data.get("quarantine", []), requests=reports,
                  nextInputRequirements=protocol["requiredHistoricalInputs"])
    return report, snapshots


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, default=FOLDER)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--audit", action="store_true", help="Freeze explicit blocked/ready coverage report")
    mode.add_argument("--verify", action="store_true", help="Verify sources, prior results and exact audit replay")
    mode.add_argument("--export-cohorts", action="store_true", help="Fail closed unless ALL origin inputs are complete")
    args = parser.parse_args()
    try:
        report, snapshots = audit_bundle(args.folder)
        if args.verify:
            path = args.folder / "coverage-audit.json"
            if path.read_bytes() != canonical(report):
                raise InputError("Frozen coverage audit does not replay exactly")
        elif args.audit:
            write_frozen(args.folder / "coverage-audit.json", report)
        else:
            if not report["fullHistoricalCoverage"]:
                raise InputBlocked(report)
            write_frozen(args.folder / "origin-cohorts.json", dict(version=VERSION, researchOnly=True,
                         inputDatasetHash=report["datasetHash"], snapshots=snapshots))
        print(json.dumps({k: report[k] for k in ("version", "status", "originCount", "readyOriginCount",
                                                "modelTrainingAllowed", "productionChangesAllowed")}, ensure_ascii=False))
        return 0
    except (InputError, KeyError, OSError, ValueError) as exc:
        print(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
