# SABLE

**Segmented Acknowledged Buffered Link Engine** is a single-clock,
synthesizable four-stream reliable message transport. Author: Sufeng Guo.
Licensed under MIT; see LICENSE.

## Integration

Top: `sable_endpoint` in `rtl/sable_endpoint.sv`, instantiating `sable_tx u_tx`
and `sable_rx u_rx`. Compile all `rtl/*.sv` as SystemVerilog. No packages,
vendor primitives, external initialization files or software protocol service
are needed. See [the interface specification](design/SPEC.md) for exact ports,
wire format, edge timing and integration obligations, and
[architecture](design/ARCHITECTURE.md) for storage and scheduling.

Four independent streams accept 1..4096-byte messages on a 64-bit ready/valid
interface. Each uses an eight-packet selective-repeat window and <=256-byte
payload fragments. The receiver supports eight out-of-order packets per
stream, CRC-32C, duplicate suppression, ordered complete-message delivery,
and an independent 32-entry ACK FIFO.

Defaults are TIMEOUT_CYCLES=4096, MAX_RETRIES=4, GENERATION_BITS=24. Legal
ranges are respectively 1..65535, 0..15 and 1..24. Capacity is fixed, not
reduced by parameters. Standalone TX has all three parameters; standalone RX
has GENERATION_BITS only.

Drive `rst=1` across at least one rising clock edge with both ends configured
to the same fresh `session_id`. All outputs are zero while rst is high.
Deassert reset, keep the session stable, and start traffic. Never reuse a
session while old frames might exist. A reset of either end cancels both
ends' outstanding application transactions and requires paired reset to a new
session. Consumers must discard any receive message interrupted by reset.

Keep application data and metadata stable while valid is stalled. Tail keep
must be low-contiguous; len is constant per message and first/last describe
each stream independently. A stream cannot begin its next message before its
completion handshake and any redundant transmission drains. Input beats may
interleave streams. RX output also interleaves streams by beat: reconstruct
per stream, not globally. Hold m_status_ready low only when able to retain
the blocked completion at the source.

Status 0 means **ACKED**, not durable across reset and not necessarily consumed
by the peer application. Status 1 means **UNACKNOWLEDGED**, not proof of
non-delivery. It latches tx_failed and requires a new session for that stream.
Identity exhaustion latches session_exhausted before accepting a message that
would reuse identities. Other streams remain independent.

## Source and reproduction boundary

Design sources are `rtl/*.sv`, `design/*.md`, README.md and LICENSE. Independent
verification sources and runnable entrypoints belong to `tests/*`, authored
by Verifier after the design handoff. Generated execution results belong to
`evidence/`, never to RTL inputs. Runtime metadata and private state are not
part of the product and are not required by the hardware.

The admitted verification entrypoints, to be delivered by Verifier, are:

```sh
python3 tests/verify.py behavior --seeds 17 89 203 --max-cycles 200000 --out evidence/behavior
python3 tests/verify.py negative --out evidence/negative
python3 tests/verify.py synthesis --out evidence/synthesis
python3 tests/verify.py reproduce --out evidence/reproduce
```

Dependencies are Python 3, Icarus Verilog (`iverilog`, `vvp`) and Yosys already
installed in the execution environment. These commands are the required
interfaces, not claims that verification files or successful results already
exist at design handoff. Actual tool versions and immutable receipts must
come from the executions; do not substitute expected versions. See
`tests/README.md` when delivered for the requirement/test/evidence index.

| Requirement family | Independent acceptance surface |
|---|---|
| Wire bytes, CRC, framing and identity | Model TX versus RTL RX; RTL TX versus model RX |
| Lengths, windows, reordering and multistream fairness | Directed tests plus seeds 17,89,203 |
| Retry, stalls, failure ambiguity and reset | Directed transaction and liveness monitors |
| Checker sensitivity | Real simulation output/completion corruption negative checks |
| Synthesizable full resources | Default-config generic Yosys hierarchy/check/stat/JSON |
| Self-contained delivery | Fresh project-local source-only reconstruction and rerun |

No functional simulation, synthesis or independent acceptance result is
asserted by this design-stage README. Preparation compilation, if performed,
is advisory only. The shared runtime generates the English Times New Roman
REPORT.md/REPORT.tex/REPORT.pdf only after independent engineering acceptance;
those report files are not prerequisites for verification.

## Trust boundary and limitations

CRC is error detection, not authentication. Correct-content guarantees exclude
undetected collisions. Framing sidebands obey the link contract: finite frames
may be dropped, duplicated, delayed, reordered or corrupted; an infinite
truncated frame is not a recoverable transaction. Finite-loss and service
fairness conditions in SPEC.md are required for successful progress; permanent
loss or backpressure can produce failure or no progress.

This engine is not TCP, RDMA, PCIe, a CPU, an operating system, a physical
network interface, or nonvolatile storage. Generic synthesis is not timing
closure, physical chip signoff, FPGA board validation or measured PPA.
