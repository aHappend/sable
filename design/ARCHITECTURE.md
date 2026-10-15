# SABLE architecture

Author: Sufeng Guo. This architecture is saved before implementing the RTL.
See SPEC.md for the externally mandatory contract.

## Decomposition and decisions

`sable_endpoint` contains `sable_tx u_tx`, `sable_rx u_rx`, a registered input
demultiplexer, and registered frame-locking output arbitration. TX and RX are
usable independently with exactly the same wire protocol.

Whole-message retention avoids unbounded application replay. Selective repeat,
not stop-and-wait, permits eight different outstanding fragments per stream.
Fixed memories avoid dynamic allocation and shared-memory ownership deadlocks.
Serial header/payload beats use parallel eight-byte CRC updates. RX uses a
single bounded staging frame before committing it to persistent stream slots.
Staging is not a substitute for the eight persistent out-of-order slots.

| Storage | Capacity | Ownership |
|---|---|---|
| TX message words | 4 x 512 x 64 bits | Input first through status handshake AND frame drain |
| TX window metadata | 4 x 8 entries | New frame allocation through ACK/terminal failure |
| TX ACK bitmap | 4 x 16 bits | Whole current message; supports oldest-hole window rule |
| RX staging words | 32 x 64 bits | Current frame parse through commit/drop |
| RX packet slots | 4 x 8 x 32 x 64 bits | CRC-valid commit through ordered copy |
| RX reassembly words | 4 x 512 x 64 bits | Ordered copy through application tail handshake |
| RX ACK FIFO | 32 identities + stream | Accepted packet until ACK serializer takes ownership |
| Completion mailboxes | One per stream | Terminal result through public status handshake |
| Final output registers | One per producer | Load through actual downstream handshake |

Payload memories are not reset; valid and ownership state is reset. Invalid
memory is never advertised. Tail bytes are masked to zero on produced outputs.

## TX stages and simultaneous events

1. Collect application beats, independently per stream. Reserve the full
   message identity range on first beat only after checking its lifetime limit.
2. Commit complete input; on a later edge select a stream in DATA round-robin.
   Select the oldest eligible timeout before a new packet, subject to the
   eight-position window.
3. Serialize three header beats, payload and CRC into the final holding
   register. Serialization changes phase only on actual handshake.
4. Start the slot timer on CRC handshake. Saturating timers become candidates;
   active transmission excludes that identity from another scheduling decision.
5. Parse ACK independently. Validate all four beats including final CRC.
   Matching ACK wins over same-cycle timeout. Advance the oldest hole from
   the message bitmap; out-of-order ACKs alone do not expand the window.
6. Commit exactly one terminal result. Fair status selection loads the final
   holding register; handshake releases application ownership, subject to drain.

One active serializer globally, four independent message owners, eight metadata
positions each. Completion can precede draining a redundant retransmission, but
the memory cannot be overwritten while that frame is active. Failure closes
only the affected stream.

## RX stages and simultaneous events

1. Consume each frame into 24-byte header registers and a 256-byte staging
   memory, validating beat shape and updating CRC only for defined bytes.
2. After CRC handshake, validate session, fields, message identity and window.
   A later commit stage reserves an empty persistent slot, then transfers the
   staging words over bounded cycles. No next staging frame overwrites it.
3. After all staged bytes have durable ownership, publish the slot and enqueue
   ACK. Duplicate accepted/copied identities can regenerate ACK without copy.
4. A fair copy engine selects the next identity for a stream and copies its
   payload words into the corresponding message offset. Publish completion
   only after the final word is committed.
5. A beat-level fair application scheduler loads complete-message words into a
   final holding register. It advances only on the public output handshake.
6. Independent ACK serializer dequeues FIFO entries into its own active frame
   context, computes the protected header CRC, and holds each public beat.

Staging commit and reassembly copy never write the same memory: commit writes
packet slots, copy writes message storage. A slot being copied remains owned
until its final word is committed. A new packet cannot overwrite it.
An ACK enqueue at full occupancy may use space freed by a simultaneous dequeue;
if no space exists only the new ACK is dropped, never accepted packet data.

## Registered flow control and service bounds

Each serial beat uses a load edge and a later handshake edge. Under a ready
opportunity every two cycles, one beat takes at most three cycles after it is
eligible (load plus at most two until handshake). DATA has at most 36 beats,
so standalone serialization takes <=108 cycles plus scheduling. ACK has four
beats. The endpoint adds a registered one-beat shadow stage, without a
combinational data bypass. It does not retire the source beat until the public
link handshake: a CRC stalled in this register must not start a TX timer.
Including this stage, allow four cycles per beat under two-cycle ready service,
or <=144 cycles for DATA and <=16 cycles for ACK, plus frame selection.
A stalled final register is never changed.

RX commit of at most 32 words and ordered copy of at most 32 words are finite.
Input staging can backpressure while committing, but never waits for message
resources: resource rejection is a bounded drop. Copy and application output
do not wait for ACK space; ACK saturation drops only ACK generation.
Round-robin copy serves a persistently copyable stream within four copy
operations, each <=32 words plus control edges. Application arbitration
serves a complete stream within four output-beat opportunities. Status fairness
has the analogous four-opportunity bound. Shared application ready stalls all
currently selected output beats, as any multiplexed ready/valid interface must;
once ready resumes the stream rotation resumes.

ACK and DATA are alternated at frame boundaries; a frame already selected is
locked until its tail. Endpoint output preserves source register stability and
does not count an internal beat twice. Input routing is determined by the first
header beat and remains locked to frame last, including malformed frame drain.
Neither router bases readiness on a DATA transmit-window credit.

The maximum serial DATA frame and <=32-word staging commit are far below the
4096-cycle default timer. At most four DATA contenders and alternating ACK
service bound own scheduling. ACK FIFO holds 32 packets (one full aggregate
window); even saturated, its serializer drains independently, and a retransmit
regenerates a lost ACK. Retry timers exclude serialization and waiting for
arbitration, and start at tail handshake. Conservatively allow 170 cycles for
an ACK service opportunity including one competing maximum DATA frame and
selection bubbles: an enqueued ACK has at most 32 preceding/active entries,
so its service bound is 5610 cycles, plus bounded external delay. This can
exceed one default timeout but is below two; a timeout is not evidence of loss.
Similarly, a maximum message has 512 application beats; four-stream round
robin and three cycles per standalone application beat bound its output drain
by 6144 service cycles plus the allowed initial 512-cycle stall. Timeout
selection cannot itself prevent this independent drain. Two unavailable
events leave two of the four retry opportunities for such transient queue and
consumer delays. Short timeout parameters intentionally need not satisfy the
default successful-delivery envelope. The 200000-cycle per-message acceptance
deadline and the joint default loss/service cases remain measured obligations
for Verifier, not inferred from compilation or these individual stage bounds.

There is no circular wait: TX retention waits only for independent ACK ingress
or terminal timeout; RX staging drops instead of waiting for a full stream;
ACK generation never blocks RX ownership; application completion does not
depend on ACK FIFO drainage; serializers eventually release their frame locks
under the external service assumption. No guarantee is claimed when external
ready remains low forever.

## Synthesis and integration boundary

All core fragmentation, CRC, ACK parsing, retry, reordering and reassembly are
RTL. No software service is required other than establishing a unique session
and obeying ready/valid. Memories are finite word arrays intended for generic
Yosys memory retention. No vendor primitives, clock crossings, physical timing,
network standard compatibility or nonvolatile delivery guarantees are implied.
Verification tools and the eventual technical report are not design inputs.
