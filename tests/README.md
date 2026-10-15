# SABLE independent verification

The oracle is a public-pin transaction oracle, authored after the RTL handoff.
It does not read hierarchical DUT state, force signals, implement product
protocol operations for the RTL, or compare two identical endpoints without
independent byte/packet expectations. `model.py` specifies wire bytes and
CRC-32C; `scenarios.py` compares actual fragments, messages, statuses, identities
and ordering. `bridge.sv` is only a clocked pin transactor. The real DUT does
fragmentation, CRC, retransmission, window management, ACKs and reassembly.

## Reproduction

Run from the delivered project root with already-installed Python 3,
Icarus Verilog (`iverilog`, `vvp`) and Yosys. No pip packages, private runtime
files, external source repositories, setup steps or downloaded tools are used.

```sh
python3 tests/verify.py behavior --seeds 17 89 203 --max-cycles 200000 --out evidence/behavior
python3 tests/verify.py negative --out evidence/negative
python3 tests/verify.py synthesis --out evidence/synthesis
python3 tests/verify.py reproduce --out evidence/reproduce
```

Each invocation creates a new UUID-suffixed attempt under `--out`, never
overwriting previous evidence. `receipt.json` records actual argv/cwd, SHA-256
of every selected source, actual tool version stdout/stderr, epoch start/end
times, exit, timeout, result scope and unavailable billing cost. Child command
receipts retain exact compiler/Yosys invocations and raw logs. Simulator
receipts bind the configuration and seed to `vectors.txt`, raw pre-edge
`simulation.stdout` and `simulation.stderr`. The native simulator trace can
also be replayed with `vvp <attempt>/sim.vvp < <attempt>/vectors.txt`.
`coverage.json`, `fault_decisions.json`, `ledger.json` and `RESULTS.md` provide
measured quantities and paths; the ledger includes failed/not-completed runs
rather than dropping them from the denominator. A nonzero exit is a failure,
unless explicitly expected and independently recognized by the negative parent.

The behavior command runs three independent seeded jobs, each executing TX,
RX, then paired endpoints; it then executes all directed cases. Parallelism
does not change seeds, sources, thresholds, resources or comparisons. Each seed
covers every listed length across the streams, with both 1 and 4096 bytes on
**every** stream. The shorter `probe` operation is advisory and never substitutes
for the admitted behavior command.

`reproduce` copies only nonempty `rtl/*.sv`, `design/*.md`, `README.md`,
`LICENSE`, and regular files in flat `tests/*` to a fresh project-local
`source/`. It verifies the copied hashes, then runs the unchanged paired-endpoint
smoke oracle (1, 9, 257 and 4096 bytes on all four streams) and full-capacity
generic synthesis from that new cwd. No evidence, binaries, caches, metadata,
final product report or absolute original-project import paths are copied.

## Timing, fairness and error checking

Inputs settle before clock edges; `OBS` is sampled before the active edge and
before nonblocking updates. Public pins are checked for X/Z on both clock edges,
including Active-region sampling. Reset starts asserted at time zero, with
settled public-zero checks before the first edge and explicit reset clocks.
An extra timing step separates the falling edge from subsequent input changes,
avoiding an Active-region reset-monitor race.

Accepted application input is checked for legal length, per-stream first/last,
constant length and contiguous keep. Both driven input channels and all public
producer outputs are monitored for valid/payload stability across stalls.
New DATA cannot appear before the committed application tail plus two cycles.
Application delivery requires all necessary independently CRC-valid input
fragments and the specified registered-output separation. ACK identity and
registered separation are checked against actual CRC-valid DATA arrival.

In seeded success traffic, ready opportunities are every two cycles, application
source gaps are bounded, receive startup blocking is 512 cycles, and randomized
extra frame delays are 1..64 cycles. Loss/corruption is restricted to identities
below 16: at most one unavailable DATA attempt and one unavailable ACK attempt
per identity. Later identities still exercise duplicates, delays and reordering.
This finite campaign is not an exhaustive fault proof. Wire queues retain
complete frames; a stalled beat never changes. Counts distinguish scheduled
overtaking from **observed** decreasing identities, and observed reordering is
mandatory. The original 200000-cycle deadline is enforced as a conservative
whole-experiment cap as well as a completion obligation, not an unbounded wait.
After settlement, remaining duplicate frames are delivered and drained, with
further message/status output rejected.

The per-stream TX monitor tracks actual emitted identities minus actual
CRC-valid ACKs, rejecting a ninth outstanding packet and advancement beyond the
oldest unacknowledged hole. Model RX compares each fragment byte and metadata;
model TX checks received complete-message bytes and emitted protected ACKs.
Seeded mandatory fault categories must have nonzero counts; zero comparisons,
unsettled transactions and missing directed witnesses are failures.

## Requirement-to-test/evidence index

Paths below are relative to a behavior attempt unless otherwise specified.

| Requirement | Executable witness | Evidence |
|---|---|---|
| Four streams, full length matrix, non-beat tails and partial fragments | `traffic`, all seeds/modes | `seed*-mode*/coverage.json` |
| Independent TX, RX and end-to-end byte checking | `run_transport`, `MessageOracle`, `decode` | Simulator traces, byte/fragment/status counts |
| DATA/ACK loss, duplicate, reorder, header/payload/CRC corruption, delay | `fault_packet`, `rx_enqueue` | Fault decisions, actual invalid frames, observed reorder |
| Input, link, message and status backpressure | `Sim.step` stability/contract monitors | Per-cycle transcript and simulator comparison counts |
| Eight packets per stream, aggregate 32, no stop-and-wait, oldest hole and fairness | `window` with ACKs frozen | `window/coverage.json` |
| Standard CRC-32C vector and protected ACK semantics | `ack_integrity` | `ack-integrity/coverage.json` |
| DATA integrity and finite malformed-frame rejection | `rx_integrity` | `rx-integrity/coverage.json` |
| Eight reverse-order retained RX slots; missing oldest and future ninth | `reverse_and_fifo` | `rx-resources/reverse/coverage.json` |
| Full ACK FIFO, drops without data loss, duplicate re-ACK recovery | `reverse_and_fifo` | `rx-resources/fifo/coverage.json` |
| Complete-message ownership, blocked stream and other-stream progress | `receive_fairness` | `receive-fairness/coverage.json` |
| ACK generation with full DATA TX window; resource-rejected DATA drains before a following valid ACK | `endpoint_ack_independence` | `endpoint-ack-independence/coverage.json` |
| Four completion mailboxes retain statuses under blocking | `mailbox` | `mailbox/coverage.json` |
| ACK at timeout threshold; ACK during held retransmission; memory retained through drain | `timers` | `timers/*/coverage.json` |
| Timer starts only on actual public CRC handshake | `timers` | `timers/public_crc_stall/coverage.json` |
| Exactly five sends for four retries; failure closes only affected stream | `timers` | `timers/exhaust/coverage.json` |
| UNACKNOWLEDGED despite actual receiver delivery | `ambiguity`, paired RTL, zero retries | `ambiguity/coverage.json` |
| Partial input/frame, pending ACK/output/status reset; stale sessions and fragments | `resets` on TX/RX/endpoint | `resets/mode*/coverage.json` |
| Sequence 255->0, late old ACK and DATA | `wrap`, `rx_wrap` with default generation | `wrap-default/`, `rx-wrap/` |
| Complete identity never reused; whole-message allocation checked atomically | `wrap`, generation=1, 512 and 504 packets | `identity-exhaustion/`, `atomic-identity-exhaustion/` |
| Eight legal parameter tuples and six explicit illegal rejections | `parameters` | `parameters/coverage.json` and individual receipts |
| Oracle detects actual wrong bytes and actual wrong status | `negative` parent and `negative-child` through normal simulation/checker | Negative receipts, injection JSON and explicit expected/actual mismatch |
| Full default-capacity generic synthesis, real TX/RX hierarchy, memory/state, no latches/blackboxes | `synthesis.py` | Yosys logs/receipt, `endpoint.json`, `structure.json` |
| Source-only fresh-cwd simulation and synthesis | `reproduce` | Copied manifest and both clean command receipts |

The standard CRC vector is also checked against the actual RTL DATA frame
carrying ASCII `123456789`: the independently calculated affine header
contribution is removed from the observed public CRC, and the recovered payload
CRC must equal literal `e3069283`. ACK CRCs cover all 24 header bytes.
Directed bit flips cover magic/type, stream, flags, lengths, session, sequence,
generation, offsets, reserved fields, payload and CRC. Malformed frames with
recomputed valid CRC also test structure independently of checksum rejection.

## Synthesis scope and retained diagnostics

The installed Yosys uses an exclusive `-run` end label. The script therefore
uses `synth -top sable_endpoint -noshare -run begin:fine`: this **executes**
the complete coarse synthesis, including `proc`, optimization and
`memory -nomap`, without the fine memory-mapping/technology passes. Disabling
optional SAT-based resource sharing avoids a combinatorial search over many
window-memory read conditions; it does not reduce the hardware configuration.
`check -assert`, cell/state/memory checks, and JSON export remain mandatory.
No latch, blackbox, constant-output shell or missing TX/RX instance is accepted.
This is not physical signoff, measured silicon PPA, or technology mapping.

Preparation is advisory and source-version-specific, not independent acceptance.
Original failures remain at:

- `evidence/preparation/diagnostic-f328f07a27bb/receipt.json`: safe-path import
  failure; repaired by explicitly binding the delivered tests directory.
- `evidence/preparation/probe-20261015T102225Z-fe01a25d/receipt.json`: interactive
  scanner timeout; repaired by removing trailing blocking whitespace.
- `evidence/preparation/probe-20261015T102250Z-daf56a5a/receipt.json`: driver
  incorrectly re-offered an already accepted single-beat message; repaired by
  retaining the completion obligation before selecting another input beat.
- `evidence/preparation/synthesis-20261015T102420Z-a5253c92/receipt.json`:
  exclusive end label left processes unsynthesized.
- `evidence/preparation/synthesis-20261015T102452Z-b8604824/receipt.json`:
  optional SAT sharing timed out. The repaired full-capacity run is
  `evidence/preparation/synthesis-20261015T102847Z-d8acfe96/receipt.json`.
- `evidence/preparation/diagnostic-022647ad7636/receipt.json`: overly long
  preparation campaign hit its 65-second wrapper limit; never counted as pass.
- `evidence/preparation/probe-20261015T102847Z-01b02aec/receipt.json` and
  `evidence/preparation/probe-20261015T102847Z-d2e3b308/receipt.json`: missing
  parent evidence directories; repaired with recursive parent creation for
  new attempt directories, without overwriting prior attempts.
- `evidence/preparation/probe-20261015T102939Z-3f0bbea7/receipt.json`:
  reset observation raced input changes on the same falling-edge timestep.
  The separated-edge repair is retained at
  `evidence/preparation/probe-20261015T103034Z-777db14c/receipt.json`.

The negative child failures are intentional **real comparator failures**, not
RTL edits: `negative-child-20261015T103309Z-4fde7d72/receipt.json` records the
actual byte 213 versus expected 212; `negative-child-20261015T103458Z-d95d8130/receipt.json`
records actual completion 1 versus expected 0, under `evidence/preparation/`.
Each includes an actual-handshake `run/injection.json`. The admitted negative
parent must independently recognize both failures and their evidence.

Only compile, executed self-checks and independently accepted delivery are
distinct levels of evidence. The shared runtime executes admitted checks and
owns independent acceptance. Final REPORT.md/REPORT.tex/REPORT.pdf are generated
only afterward and are deliberately absent from verification selectors and
existence assertions. Known limits are the specified finite faults, unique
paired sessions, no CRC collisions, and no physical/network compatibility claims.
