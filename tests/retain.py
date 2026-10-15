"""Append-only project-local command evidence, also used for bounded probes."""
import datetime
import hashlib
import json
import pathlib
import subprocess
import time
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[1]
SELECTORS = ("rtl/*.sv", "design/*.md", "README.md", "LICENSE", "tests/*")


def inventory(root=ROOT):
    result = {}
    for pattern in SELECTORS:
        paths = sorted(p for p in root.glob(pattern) if p.is_file())
        if not paths:
            raise RuntimeError("empty required selector: " + pattern)
        for p in paths:
            result[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return result


def fresh(root, label):
    root = pathlib.Path(root)
    root.mkdir(parents=True, exist_ok=True)
    out = root / (label + "-" + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
    out.mkdir()
    return out


def versions():
    result = {}
    for name, argv in (("python3", ["python3", "--version"]),
                       ("iverilog", ["iverilog", "-V"]),
                       ("vvp", ["vvp", "-V"]), ("yosys", ["yosys", "-V"])):
        p = subprocess.run(argv, capture_output=True, text=True, timeout=10)
        result[name] = {"argv": argv, "exit_code": p.returncode,
                        "stdout": p.stdout, "stderr": p.stderr}
    return result


def command(out, name, argv, timeout=45, cwd=ROOT, allow_failure=False):
    start = time.time()
    stdout = out / (name + ".stdout")
    stderr = out / (name + ".stderr")
    timed_out = False
    with stdout.open("w") as so, stderr.open("w") as se:
        try:
            p = subprocess.run([str(x) for x in argv], cwd=cwd, stdout=so, stderr=se, timeout=timeout)
            code = p.returncode
        except subprocess.TimeoutExpired:
            code = None
            timed_out = True
    record = dict(argv=[str(x) for x in argv], cwd=str(cwd), started_at=start,
                  finished_at=time.time(), timeout_s=timeout, timed_out=timed_out,
                  exit_code=code, stdout=str(stdout.relative_to(out)),
                  stderr=str(stderr.relative_to(out)))
    (out / (name + ".receipt.json")).write_text(json.dumps(record, indent=2))
    if timed_out or (code != 0 and not allow_failure):
        raise RuntimeError(f"{name}: exit={code} timeout={timed_out}; see {out}")
    return record
