# SABLE interface and behavioral specification

Segmented Acknowledged Buffered Link Engine. Author: Sufeng Guo.
This is the design contract saved before RTL implementation. The admitted work
order remains authoritative; implementation choices below do not reduce it.

## Public interfaces

`sable_endpoint` instantiates `sable_tx u_tx` and `sable_rx u_rx`. All ports are
unsigned. One rising-edge clock `clk`, synchronous active-high `rst`, and
32-bit `session_id` are common to all three modules. Configuration is sampled
on reset and must remain stable while running.

| Interface | Producer signals | Consumer signal |
|---|---|---|
| Application TX | `s_msg_valid,data[63:0],keep[7:0],first,last,stream[1:0],len[12:0]` | `s_msg_ready` |
| Application RX | `m_msg_valid,data[63:0],keep[7:0],first,last,stream[1:0],len[12:0]` | `m_msg_ready` |
| Completion | `m_status_valid,stream[1:0],code[1:0]` | `m_status_ready` |
| Endpoint link TX | `link_tx_valid,data[63:0],keep[7:0],first,last` | `link_tx_ready` |
| Endpoint link RX | `link_rx_valid,data[63:0],keep[7:0],first,last` | `link_rx_ready` |

Names in a table row share its prefix. TX exposes DATA as `m_data_*` and
receives ACK as `s_ack_*`; RX receives DATA as `s_data_*` and emits ACK as
`m_ack_*`. Link-shaped interfaces have 64-bit data, 8-bit keep and no stream/len
sidebands. `tx_failed[3:0]` and `session_exhausted[3:0]` are sticky TX indicators.
Parameters on TX and endpoint are `TIMEOUT_CYCLES=4096` (1..65535),
`MAX_RETRIES=4` (0..15), `GENERATION_BITS=24` (1..24); RX has
`GENERATION_BITS=24`. Illegal parameters are explicitly rejected, not clamped.

Four independent streams each accept one outstanding message of 1..4096 bytes.
Application beats may interleave streams. Within each stream len is constant,
first marks byte zero, last marks the final beat, non-tail keep is ff and tail
keep is contiguous from bit zero. The source must obey these input contracts;
malformed application traffic is an integration error, not a supported message.
The next same-stream message may start only after the preceding completion
handshake and any already started DATA frame drains. A source holding a
non-ready stream at the multiplexed application input causes its own blocking.
RX emits complete messages only, possibly interleaving streams by beat.

## Cycle and degenerate-boundary table

| Situation | Required edge behavior |
|---|---|
| Pre-edge valid and ready | Exactly one transfer, except on a reset edge |
| Pre-edge valid and not ready | Hold data and all metadata through the eventual handshake |
| Pre-edge valid zero | Do not advance any input collection counter |
| rst high | Mask every public output, including ready and data, to zero; reset wins |
| First edge after reset | Empty state; only actual inputs create transactions |
| Internal state commit at edge k | Earliest dependent final output load k+1; earliest handshake k+2 |
| Length 1..8 | first and last coincide on application beat; DATA still has separate header/CRC |
| Length not divisible by eight | Tail keep selects only valid bytes; CRC never shares this beat |
| Length 257..4096 | Last fragment can be partial; all other fragments are 256 bytes |
| Fixed window/FIFO capacity | Four streams, eight slots/stream and 32 ACK entries, not configurable |
| Non-power-of-two work | Explicit byte/fragment counts, never a message-length wrap mask |
| ACK plus timeout | Valid matching ACK wins; no failure for that acknowledged entry |
| ACK during retransmission | Retire identity, drain already started frame without reviving entry |
| ACK FIFO enqueue plus dequeue | Both complete; occupancy unchanged; no overwrite |
| Reset plus any operation | Cancel operation and all partially visible transactions |
| Completion stall | Hold final output; retain stream ownership until status handshake |

Every producer has a final holding register. Store-and-forward scheduling is
multi-cycle, not combinational forwarding or a fixed message latency guarantee.

## Canonical wire format

Each frame is three full header beats, DATA payload beats (none for ACK), and
one separate CRC beat. Bytes travel low lane first; all multibyte fields are
little-endian.

| Header byte(s) | Meaning |
|---|---|
| 0,1,2 | 53,42,01 hexadecimal |
| 3 | 00 DATA, 01 ACK |
| 4 | stream 0..3, upper bits zero |
| 5 | bit0 SOM, bit1 EOM, other bits zero |
| 6..7 | payload byte length |
| 8..11 | session_id |
| 12 | sequence |
| 13..15 | generation |
| 16..17 | message length |
| 18..19 | message byte offset |
| 20..23 | zero |

Identity is the unsigned 32-bit concatenation `{generation,sequence}`. Each
stream starts at zero and allocates consecutive identities, across messages.
DATA offset is a multiple of 256, payload is `min(256,len-offset)`, SOM iff
offset=0, EOM iff offset+payload=len. ACK preserves only stream, session and
identity; all other header fields are zero.

Header keep is ff; only header beat zero has first. Payload keep is contiguous
low ones. Only CRC has last; CRC keep is 0f, high data bits are zero. Reject
bad constants, reserved bits, length relations, frame shape, session, generation
range and CRC without changing delivery/window state or issuing positive ACK.
Finite malformed frames drain. A first beat resynchronizes parsing after reset;
continuation beats with no recognized first are discarded.

CRC-32C/Castagnoli: polynomial 1edc6f41, reflected update 82f63b78, initial
ffffffff, reflected input/output, xorout ffffffff. Process bytes in wire order,
each byte bit zero first. Cover all 24 header bytes and valid payload bytes,
not CRC or padding. Put the result little-endian in low 32 bits of its own
beat. ASCII `123456789` has standard result e3069283. CRC protects ACK meaning,
not merely payload. It is not authentication and undetected CRC collisions are
excluded from the correctness guarantee.

## Reliability, ownership and failure

TX stores each complete message before fragmenting. Eight selective-repeat
entries per stream restrict new identities to distance <=7 from the oldest
unacknowledged identity. Non-contiguous ACKs cannot open a ninth position.
Timers start on actual CRC-beat handshake; becoming overdue does not consume a
retry. Only an actual retransmission start consumes one of MAX_RETRIES.
DATA scheduling is whole-frame round-robin across streams, oldest overdue
within a stream before new DATA. Each persistently eligible stream is served
within four DATA arbitration opportunities.

Only a structurally valid, CRC-protected ACK matching a previously transmitted
active identity can acknowledge it. All fragments acknowledged produces exactly
one status ACKED=0. Exhausting retries and timing out again produces exactly one
UNACKNOWLEDGED=1 and closes that stream until session reset. This status says
neither that delivery happened nor that it did not happen. A completion mailbox
per stream plus fair final output arbitration prevents overwriting statuses.

RX holds eight out-of-order packets per stream and a full 4096-byte reassembly
buffer. It accepts only identities within seven positions of next-to-copy,
consistent with the current message base and length. Any fragment can establish
the message, including a non-SOM fragment. It copies in identity order, suppresses
duplicate delivery, and ACKs only packets with retained ownership. Duplicates of
retained or already copied packets can be ACKed again. A full message is retained
until application tail handshake. Previous-message duplicates can be re-ACKed
using monotonic committed identity history; next-message traffic cannot displace
an unconsumed current message. Resource-limited and too-far future frames drain
and are dropped, without ACK. A separate 32-entry ACK FIFO may drop a new ACK
when full; its corresponding accepted DATA stays owned and retransmissions
regenerate ACKs.

Endpoint link arbitration alternates whole DATA and ACK frames when both are
available. Neither can monopolize the link; ACKs never consume a DATA slot.
Input demultiplexing drains DATA even when reassembly cannot accept it, so a
following ACK cannot be permanently blocked by a full DATA window.

## Sessions and fault envelope

Both ends reset together to the same fresh session. Reset cancels input,
in-flight windows, statuses, reassembly, ACK queues and partial outputs. The
application discards any cross-reset partial receive. Never reuse a session
while old frames can remain. Single-end reset requires upgrading to a paired
new-session reset. Old-session frames cannot ACK or deliver current traffic.

Sequence 255 wraps to zero while generation increments. Unused generation
bits must be zero. Complete identity never wraps: before accepting a message,
TX checks room for all fragments and latches session_exhausted if insufficient.
GENERATION_BITS=1 shortens lifetime to 512 packets without reducing resources.

Faults include finite whole-frame loss, duplication, reordering, delay and bit
corruption; framing sidebands remain canonical for ordinary fault injection.
A never-ending missing-last frame is outside the recoverable link contract.
No guarantee is made under permanent loss/backpressure or CRC collision.
For the default bounded-fair success regime: ready opportunity at least every
two cycles, input next beat within four, receive blocking at most 512 cycles
then two-cycle service, link extra delay <=64 cycles, at most two unavailable
DATA/ACK events per identity, and finite duplication/reordering. The admitted
completion and delivery deadline is 200000 cycles from complete input.

## Required independent acceptance

Verifier owns `tests/*`, independent TX/RX oracles and endpoint scoreboards,
all functional simulation, negative checks and actual default-config Yosys
synthesis. Required seeds are 17,89,203; all run TX, RX and endpoint traffic.
Coverage includes the full admitted length matrix, 32 outstanding identities,
frozen ACK eight-not-nine window proof, reverse-order RX slots, CRC-protected
critical fields, malformed finite frames, duplicate/old/future ACKs, FIFO and
mailbox saturation, stalls, timeouts/ACK coincidence, retransmission ACKs,
retry exhaustion despite delivery, reset phases, sequence wrap with old frames,
identity exhaustion, eight legal parameter tuples and illegal rejection.
Negative checks must corrupt an actual output handshake and a real completion
through the ordinary comparison entry, preserving nonzero mismatch evidence.
No passing verification or independent acceptance is claimed by this document.
