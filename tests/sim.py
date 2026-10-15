"""Interactive public-pin simulation and transaction monitors."""
import collections
import json
import pathlib
import select
import subprocess
import sys
import time

from model import decode
from retain import ROOT, command

INPUT_WIDTHS = (1, 64, 8, 1, 1, 2, 13, 1, 1, 1, 1, 64, 8, 1, 1)
OUTPUT_NAMES = ("ir", "mv", "md", "mk", "mf", "ml", "ms", "mn", "sv", "ss", "sc",
                "fail", "exhaust", "tv", "td", "tk", "tf", "tl", "rr")
OUTPUT_WIDTHS = (1, 1, 64, 8, 1, 1, 2, 13, 1, 2, 2, 4, 4, 1, 64, 8, 1, 1, 1)


def pack(values):
    total = 0
    for value, width in zip(values, INPUT_WIDTHS):
        assert 0 <= value < 1 << width, (value, width)
        total = (total << width) | value
    return total


def unpack(value):
    result = {}
    for name, width in reversed(tuple(zip(OUTPUT_NAMES, OUTPUT_WIDTHS))):
        result[name] = value & ((1 << width) - 1)
        value >>= width
    assert value == 0
    return result


def vector(app=None, incoming=None, mr=1, sr=1, lr=1):
    return [int(app is not None), *(app or (0, 0, 0, 0, 0, 0)), mr, sr, lr,
            int(incoming is not None), *(incoming or (0, 0, 0, 0))]


class Sim:
    def __init__(self, out, mode=2, timeout=4096, retries=4, generation=24, mutant=None):
        self.out = pathlib.Path(out)
        self.out.mkdir(parents=True)
        self.config = dict(mode=mode, timeout=timeout, retries=retries, generation=generation)
        self.argv = ["vvp", str(self.out / "sim.vvp")]
        command(self.out, "compile", ["iverilog", "-g2012", "-Wall", "-s", "bridge",
                "-Pbridge.MODE=" + str(mode), "-Pbridge.TIMEOUT_CYCLES=" + str(timeout),
                "-Pbridge.MAX_RETRIES=" + str(retries),
                "-Pbridge.GENERATION_BITS=" + str(generation),
                "-o", self.out / "sim.vvp", "tests/bridge.sv",
                *sorted(str(p.relative_to(ROOT)) for p in ROOT.glob("rtl/*.sv"))])
        self.start = time.time()
        self.err = (self.out / "simulation.stderr").open("w")
        self.raw = (self.out / "simulation.stdout").open("w")
        self.inputs = (self.out / "vectors.txt").open("w")
        self.p = subprocess.Popen(self.argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=self.err, text=True, bufsize=1, cwd=ROOT)
        self.cycle = 0
        self.session = 0x1234abcd
        self.stall = {}
        self.frames = [[], []]
        self.history = []
        self.mutant = mutant
        self.mutated = False
        self.comparisons = collections.Counter()
        self.input_hold = {}
        self.application_progress = {}
        self.application_complete = {}
        try:
            self.reset()
        except Exception:
            self.close()
            raise

    def step(self, a=None, b=None, rst=0):
        a = a or vector()
        b = b or vector()
        line = f"{rst:x} {self.session:x} {pack(a):x} {pack(b):x}\n"
        self.inputs.write(line)
        self.p.stdin.write(line)
        self.p.stdin.flush()
        if not select.select([self.p.stdout], [], [], 10)[0]:
            self.p.terminate()
            raise RuntimeError("SIMULATION_RESPONSE_TIMEOUT")
        line = self.p.stdout.readline()
        self.raw.write(line)
        assert line.startswith("OBS "), ("simulation stopped", line, self.cycle)
        fields = line.split()
        assert len(fields) == 3 and not any(c in fields[1] + fields[2] for c in "xXzZ")
        observations = [unpack(int(v, 16)) for v in fields[1:]]
        self.cycle += 1
        if rst:
            assert not any(any(o.values()) for o in observations), ("reset", observations)
            self.stall.clear()
            self.input_hold.clear()
            self.application_progress.clear()
            self.application_complete.clear()
            self.frames = [[], []]
            return observations, []
        emitted = []
        for node, (o, drive) in enumerate(zip(observations, (a, b))):
            self.comparisons["pin_cycles"] += 1
            for channel, valid, ready, values in (
                ("application", drive[0], o["ir"], tuple(drive[1:7])),
                ("incoming", drive[10], o["rr"], tuple(drive[11:]))):
                key = node, channel
                if key in self.input_hold:
                    assert valid and values == self.input_hold[key], ("STIMULUS_STALL_VIOLATION", key, values, self.input_hold[key])
                if valid and not ready:
                    self.input_hold[key] = values
                else:
                    self.input_hold.pop(key, None)
            if drive[0] and o["ir"]:
                _, data, keep, first, last, stream, length = drive[:7]
                assert 1 <= length <= 4096, ("ILLEGAL_APPLICATION_LENGTH", length)
                pos, previous_length = self.application_progress.get((node, stream), (0, length))
                count = min(8, length - pos)
                assert (previous_length, keep, first, last) == (
                    length, (1 << count) - 1, int(pos == 0), int(pos + count == length)), (
                    "ILLEGAL_APPLICATION_SHAPE", node, stream, pos, drive[:7])
                if last:
                    self.application_progress.pop((node, stream), None)
                    self.application_complete[node, stream] = self.cycle
                else:
                    self.application_progress[node, stream] = pos + count, length
                self.comparisons["application_input_contract"] += 1
            for channel, valid, ready, names in (
                ("link", o["tv"], drive[9], ("td", "tk", "tf", "tl")),
                ("message", o["mv"], drive[7], ("md", "mk", "mf", "ml", "ms", "mn")),
                ("status", o["sv"], drive[8], ("ss", "sc"))):
                val = tuple(o[k] for k in names)
                key = node, channel
                if key in self.stall:
                    assert valid and val == self.stall[key], ("STALL_UNSTABLE", self.cycle, key, val, self.stall[key])
                if valid and not ready:
                    self.stall[key] = val
                    self.comparisons["stall_cycles"] += 1
                else:
                    self.stall.pop(key, None)
            if o["tv"] and drive[9]:
                beat = tuple(o[k] for k in ("td", "tk", "tf", "tl"))
                assert bool(beat[2]) == (not self.frames[node]), ("frame first", self.cycle, beat)
                if beat[2] and ((beat[0] >> 24) & 255) == 0:
                    stream = (beat[0] >> 32) & 3
                    assert (node, stream) in self.application_complete
                    assert self.cycle >= self.application_complete[node, stream] + 2, (
                        "REGISTERED_TX_LATENCY", self.cycle, self.application_complete[node, stream])
                self.frames[node].append(beat)
                if beat[-1]:
                    words = self.frames[node]
                    decoded = decode(words)
                    emitted.append((node, words, decoded))
                    self.history.append((self.cycle, node, decoded))
                    self.frames[node] = []
                    self.comparisons["frames"] += 1
            if self.mutant == "data" and not self.mutated and o["mv"] and drive[7]:
                original = o["md"]
                o["md"] ^= 1
                self.mutated = True
                (self.out / "injection.json").write_text(json.dumps(
                    dict(kind="actual_application_handshake", cycle=self.cycle, node=node,
                         original=original, corrupted=o["md"]), indent=2))
            if self.mutant == "status" and not self.mutated and o["sv"] and drive[8]:
                original = o["sc"]
                o["sc"] ^= 1
                self.mutated = True
                (self.out / "injection.json").write_text(json.dumps(
                    dict(kind="actual_status_handshake", cycle=self.cycle, node=node,
                         original=original, corrupted=o["sc"]), indent=2))
        return observations, emitted

    def reset(self):
        self.step(rst=1)
        self.step(rst=1)
        self.step()

    def close(self):
        self.p.stdin.close()
        rest = self.p.stdout.read()
        self.raw.write(rest)
        code = self.p.wait(timeout=5)
        self.raw.close()
        self.inputs.close()
        self.err.close()
        record = dict(argv=self.argv, cwd=str(ROOT), config=self.config, started_at=self.start,
                      finished_at=time.time(), exit_code=code, timed_out=False, cycles=self.cycle,
                      stdout="simulation.stdout", stderr="simulation.stderr", vectors="vectors.txt",
                      comparisons=dict(self.comparisons))
        (self.out / "simulation.receipt.json").write_text(json.dumps(record, indent=2))
        if sys.exc_info()[0] is None:
            assert code == 0, ("vvp exit", code)
