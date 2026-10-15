#!/usr/bin/env python3
"""SABLE admitted verification entrypoints; all evidence is append-only."""
import argparse
import json
import pathlib
import shutil
import sys
import time
import traceback

sys.dont_write_bytecode = True
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from retain import ROOT, command, fresh, inventory, versions
from scenarios import run_transport


def seeded_runs(out, seed, max_cycles):
    return [run_transport(out / f"seed{seed}-mode{mode}", seed, mode, max_cycles)
            for mode in (0, 1, 2)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("behavior", "negative", "synthesis", "reproduce", "probe", "negative-child"))
    parser.add_argument("--seeds", nargs="+", type=int, default=[17, 89, 203])
    parser.add_argument("--max-cycles", type=int, default=200000)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--mode", type=int, default=2)
    parser.add_argument("--mutant", choices=("data", "status"))
    parser.add_argument("--repair-of")
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--case")
    args = parser.parse_args()
    out = fresh(args.out.resolve(), args.operation)
    source = inventory()
    start = time.time()
    record = dict(argv=[sys.executable, *sys.argv], cwd=str(ROOT), source_sha256=source,
                  tool_versions=versions(), started_at=start, repair_of=args.repair_of,
                  timeout_s=110, timed_out=False, stdout="stdout.log", stderr="stderr.log",
                  acceptance_evidence=False, cost="unavailable")
    code = 0
    results = []
    planned = []
    try:
        if args.operation in ("probe", "negative-child"):
            if args.case:
                import directed
                cases = {"window": directed.window, "ack": directed.ack_integrity,
                         "rx": directed.rx_integrity, "mailbox": directed.mailbox,
                         "resources": directed.reverse_and_fifo, "timers": directed.timers,
                         "ambiguity": directed.ambiguity, "resets": directed.resets,
                         "rx-wrap": directed.rx_wrap, "parameters": directed.parameters,
                         "wrap": lambda p: directed.wrap(p, 24, 260),
                         "exhaust": lambda p: directed.wrap(p, 1, 512),
                         "atomic-exhaust": lambda p: directed.wrap(p, 1, 504, 4096),
                         "fairness": directed.receive_fairness}
                results.append(cases[args.case](out / "run"))
            else:
                results.append(run_transport(out / "run", args.seeds[0], args.mode,
                                             args.max_cycles, smoke=not args.full, mutant=args.mutant))
        elif args.operation == "behavior":
            planned = [f"seed{seed}-mode{mode}" for seed in args.seeds for mode in (0, 1, 2)]
            planned += ["window", "ack-integrity", "rx-integrity", "mailbox", "receive-fairness",
                        "rx-resources/reverse", "rx-resources/fifo", "timers/coincident",
                        "timers/in_retransmit", "timers/public_crc_stall", "timers/exhaust",
                        "ambiguity", "resets/mode0", "resets/mode1", "resets/mode2",
                        "wrap-default", "identity-exhaustion", "atomic-identity-exhaustion",
                        "rx-wrap", "parameters"]
            from concurrent.futures import ProcessPoolExecutor
            with ProcessPoolExecutor(max_workers=3) as pool:
                jobs = [pool.submit(seeded_runs, out, seed, args.max_cycles) for seed in args.seeds]
                for job in jobs:
                    results.extend(job.result())
            from directed import directed
            results.extend(directed(out, args.max_cycles))
            for name in planned:
                assert (out / name / "coverage.json").is_file(), ("MISSING_REQUIRED_RUN", name)
        elif args.operation == "synthesis":
            from synthesis import synthesis
            results.append(synthesis(out))
        elif args.operation == "negative":
            for mutant, marker in (("data", "BYTE_MISMATCH"), ("status", "STATUS_MISMATCH")):
                child = out / mutant
                child.mkdir()
                argv = ["python3", "tests/verify.py", "negative-child", "--mode", "2",
                        "--mutant", mutant, "--out", str(child)]
                import subprocess
                with (child / "stdout.log").open("w") as so, (child / "stderr.log").open("w") as se:
                    p = subprocess.run(argv, cwd=ROOT, stdout=so, stderr=se, timeout=45)
                text = (child / "stderr.log").read_text()
                assert p.returncode != 0 and marker in text, ("NEGATIVE_NOT_DETECTED", mutant, p.returncode, text)
                injections = list(child.glob("negative-child-*/run/injection.json"))
                assert len(injections) == 1, ("missing actual handshake injection", mutant)
                results.append(dict(mutant=mutant, exit_code=p.returncode, mismatch=marker,
                                    injection=str(injections[0].relative_to(out))))
        elif args.operation == "reproduce":
            clean = out / "source"
            clean.mkdir()
            for name in source:
                target = clean / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / name, target)
            assert inventory(clean) == source
            command(out, "clean-smoke", ["python3", "tests/verify.py", "probe",
                    "--mode", "2", "--out", "evidence/smoke"], timeout=45, cwd=clean)
            command(out, "clean-synthesis", ["python3", "tests/verify.py", "synthesis",
                    "--out", "evidence/synthesis"], timeout=105, cwd=clean)
            results.append(dict(outcome="passed", copied_sources=source))
    except Exception:
        code = 1
        record["failure"] = traceback.format_exc()
        print(record["failure"], file=sys.stderr)
        (out / "stderr.log").write_text(record["failure"])
    finally:
        ledger = []
        for name in planned:
            coverage = out / name / "coverage.json"
            receipt = out / name / "simulation.receipt.json"
            if coverage.exists():
                quantity = json.loads(coverage.read_text())
                state = quantity["outcome"]
            else:
                quantity = None
                state = "failed" if receipt.exists() else "not_completed_or_not_executed"
            ledger.append(dict(run=name, state=state, measured=quantity,
                               coverage=str(coverage.relative_to(out)),
                               receipt=str(receipt.relative_to(out)) if receipt.exists() else None))
        (out / "ledger.json").write_text(json.dumps(ledger, indent=2))
        record.update(finished_at=time.time(), exit_code=code, results=results)
        (out / "receipt.json").write_text(json.dumps(record, indent=2))
        if not (out / "stderr.log").exists():
            (out / "stderr.log").write_text("")
        summary = f"{args.operation}: {'PASS' if code == 0 else 'FAIL'}; receipt={out.relative_to(ROOT)}/receipt.json\n"
        (out / "stdout.log").write_text(summary)
        (out / "RESULTS.md").write_text(
            "# Verification execution\n\n" + summary + "\n" +
            "This is executed self-check evidence, not independent engineering acceptance. "
            "Actual source identifiers, commands, versions, exits and run counts are in receipt.json. "
            "Tool/call billing is unavailable. No physical signoff is claimed.\n")
        print(summary, end="")
    return code


if __name__ == "__main__":
    sys.exit(main())
