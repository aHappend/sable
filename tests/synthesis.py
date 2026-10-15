"""Full-capacity generic synthesis and structural checks, not physical signoff."""
import collections
import json

from retain import ROOT, command


def synthesis(out):
    script = out / "synthesize.ys"
    design = out / "endpoint.json"
    script.write_text(
        "read_verilog -sv " + " ".join(str(p.relative_to(ROOT)) for p in sorted(ROOT.glob("rtl/*.sv"))) + "\n"
        "hierarchy -check -top sable_endpoint\n"
        "synth -top sable_endpoint -run begin:fine\n"
        "check -assert\nstat\n"
        f"write_json {design}\n")
    command(out, "yosys", ["yosys", "-Q", "-T", "-s", script], timeout=60)
    netlist = json.loads(design.read_text())
    modules = netlist["modules"]
    assert "sable_endpoint" in modules
    top = modules["sable_endpoint"]
    for name in ("u_tx", "u_rx"):
        assert name in top["cells"], ("missing hierarchy", name)
        cell = top["cells"][name]
        assert cell["type"] in modules
        original = modules[cell["type"]].get("attributes", {}).get("hdlname", cell["type"]).lstrip("\\")
        assert original.split()[0] == ("sable_tx" if name == "u_tx" else "sable_rx"), original
        assert sum(isinstance(bit, int) for bits in cell["connections"].values() for bit in bits) > 100
    counts = collections.Counter()
    memory = collections.Counter()
    for module_name, module in modules.items():
        assert int(module.get("attributes", {}).get("blackbox", "0"), 2) == 0, ("blackbox", module_name)
        for cell in module.get("cells", {}).values():
            kind = cell["type"]
            counts[kind] += 1
            assert "latch" not in kind.lower(), ("latch", module_name, kind)
            assert kind.startswith("$") or kind in modules, ("unknown cell", kind)
            if kind in ("$mem_v2", "$mem"):
                params = cell["parameters"]
                memory[module_name] += int(params["WIDTH"], 2) * int(params["SIZE"], 2)
    tx = top["cells"]["u_tx"]["type"]
    rx = top["cells"]["u_rx"]["type"]
    assert memory[tx] >= 4 * 512 * 64, ("TX storage missing", memory)
    assert memory[rx] >= (4 * 512 + 4 * 8 * 32) * 64, ("RX storage missing", memory)
    assert sum(n for k, n in counts.items() if "dff" in k.lower()) > 20, ("empty state shell", counts)
    for port in top["ports"].values():
        if port["direction"] == "output":
            assert any(isinstance(bit, int) for bit in port["bits"]), ("constant output", port)
    result = dict(outcome="passed", cell_counts=dict(counts), memory_bits=dict(memory),
                  memories_mapped=False, configuration="default full four-stream eight-window 4096-byte endpoint",
                  limits="generic synthesis only; no technology area/timing or physical signoff")
    (out / "structure.json").write_text(json.dumps(result, indent=2))
    return result
