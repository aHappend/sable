"""Bounded preparation wrapper that also retains entrypoint/import failures."""
import hashlib
import json
import pathlib
import subprocess
import sys
import time
import uuid

root = pathlib.Path(__file__).resolve().parents[1]
out = root / "evidence/preparation" / ("diagnostic-" + uuid.uuid4().hex[:12])
out.mkdir(parents=True)
argv = sys.argv[1:]
if argv and argv[0] == "--":
    argv = argv[1:]
start = time.time()
source = {}
for pattern in ("rtl/*.sv", "design/*.md", "README.md", "LICENSE", "tests/*"):
    for p in sorted(root.glob(pattern)):
        if p.is_file():
            source[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
tools = {}
for name, flag in (("python3", "--version"), ("iverilog", "-V"), ("vvp", "-V"), ("yosys", "-V")):
    p = subprocess.run([name, flag], capture_output=True, text=True, timeout=5)
    tools[name] = dict(argv=[name, flag], exit_code=p.returncode, stdout=p.stdout, stderr=p.stderr)
timed_out = False
with (out / "stdout.log").open("w") as so, (out / "stderr.log").open("w") as se:
    try:
        p = subprocess.run(argv, cwd=root, stdout=so, stderr=se, timeout=65)
        code = p.returncode
    except subprocess.TimeoutExpired:
        code = None
        timed_out = True
record = dict(argv=argv, cwd=str(root), started_at=start, finished_at=time.time(),
              source_sha256=source, tool_versions=tools, timeout_s=65, timed_out=timed_out,
              exit_code=code, stdout="stdout.log", stderr="stderr.log", acceptance_evidence=False)
(out / "receipt.json").write_text(json.dumps(record, indent=2))
print(str(out.relative_to(root) / "receipt.json"))
print((out / "stdout.log").read_text())
print((out / "stderr.log").read_text())
sys.exit(code if code is not None else 124)
