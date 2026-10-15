#!/usr/bin/env python3
"""SABLE admitted verification entrypoints; all evidence is append-only."""
import argparse
import json
import pathlib
import shutil
import sys
import time
import traceback

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from retain import ROOT, command, fresh, inventory, versions
from scenarios import run_transport


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
    try:
        if args.operation in ("probe", "negative-child"):
            if args.case:
                import directed
                cases = {"window": directed.window, "ack": directed.ack_integrity,
                         "rx": directed.rx_integrity, "mailbox": directed.mailbox,
                         "resources": directed.reverse_and_fifo, "timers": directed.timers,
                         "ambiguity": directed.ambiguity, "resets": directed.resets,
                         "rx-wrap": directed.rx_wrap, "parameters": directed.parameters}
                results.append(cases[args.case](out / "run"))
            else:
                results.append(run_transport(out / "run", args.seeds[0], args.mode,
                                             args.max_cycles, smoke=not args.full, mutant=args.mutant))
        elif args.operation == "behavior":
            for seed in args.seeds:
                for mode in (0, 1, 2):
                    results.append(run_transport(out / f"seed{seed}-mode{mode}", seed, mode, args.max_cycles))
            from directed import directed
            results.extend(directed(out, args.max_cycles))
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
                    "--out", "evidence/synthesis"], timeout=65, cwd=clean)
            results.append(dict(outcome="passed", copied_sources=source))
    except Exception:
        code = 1
        record["failure"] = traceback.format_exc()
        print(record["failure"], file=sys.stderr)
        (out / "stderr.log").write_text(record["failure"])
    finally:
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
