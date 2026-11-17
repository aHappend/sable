# SABLE — Reliable multistream message-transport RTL

[English](README.md) · [简体中文](README.zh-CN.md) · [Repository guide / 文件导航](REPOSITORY_GUIDE.md)

Documentation updated: 2026-11-17. This page describes a repository snapshot, not a live job dashboard.

## Overview

**SABLE** publishes chip RTL, technical reports and verification artifacts. Segmented Acknowledged Buffered Link Engine: CRC-32C framing, sliding send windows, out-of-order receive reassembly and bounded retry handling.

The chip project is public; Vulcan itself remains private and closed-source. Future public releases must be limited to chip technology and public reproducibility materials, excluding Vulcan internal architecture and operating materials. This refresh organizes documentation only; it is not a comprehensive disclosure audit of historical material and does not claim that the existing repository tree has undergone such clearance.

## Scope and evidence

Use the [exact-directory result index](REPOSITORY_GUIDE.md). Functional simulation, synthesis, standalone/virtual-pin timing, board-bridge probing, workload readback and system-software execution are different evidence scopes. A pass at one scope does not establish another. Existing historical results are retained; this documentation refresh neither upgrades nor invalidates them.

Read timing, utilization and performance values from their specific records and applicability conditions; results from differently located copies are not merged. This page makes no fleet-wide claim of physical-board completion, full-model inference, physical Linux boot or measured power/energy efficiency.

## Repository guide

The [repository guide](REPOSITORY_GUIDE.md) lists existing source, constraints, tests, reports and result paths. Hyphenated, underscored and `chips/` directories can be different publication copies; none is silently designated authoritative, moved or deleted.

Start reproduction from the selected chip’s public specification, test instructions and scripts. Tool, input and board requirements belong to that directory. Chip experiments were not rerun as part of this documentation update.

## Executive Engineering Signoff Summary

| Signoff Dimension | Verified Deliverable |
| --- | --- |
| **Synthesizable RTL (`rtl/*.sv`)** | **3 modules · 979 lines** ([`sable_endpoint.sv`](rtl/sable_endpoint.sv), [`sable_tx.sv`](rtl/sable_tx.sv), [`sable_rx.sv`](rtl/sable_rx.sv)) |
| **Architecture & Protocol Spec (`design/`)** | [`design/ARCHITECTURE.md`](design/ARCHITECTURE.md) · [`design/SPEC.md`](design/SPEC.md) |
| **Verification & Fault-Injection Suite (`tests/`)** | **10 self-checking suites** (protocol oracle, standalone TX/RX, lossy/reordered/corrupted link, multi-seed regression, error sensitivity) |
| **Synthesis Signoff** | Passed `yosys` generic synthesis (`hierarchy -check; proc; opt; check -assert; stat`) with `0` inferred latches |
| **Engineering Report (`REPORT.pdf`)** | [**`REPORT.pdf`**](REPORT.pdf) · [`REPORT.md`](REPORT.md) |

The listed suite count and generic-synthesis outcome are the retained report’s results, not tests rerun for this documentation update; see [test instructions](tests/README.md) and [technical report](REPORT.md).

## System Architecture & Protocol Specification

| Subsystem / Dimension | Specification Contract | Hardware Realization |
| --- | --- | --- |
| **1. Multi-Stream Datapath** | Single clock, 64-bit `ready`/`valid` interface, **4 independent streams**, message length **1–4096 B**, max frame payload **256 B**, non-aligned tail handling | Per-stream ingress segmentation, byte-enable (`keep`) tail qualification, and work-conserving round-robin stream arbitration |
| **2. Sliding Send Window** | **8 unacknowledged packets per stream** (`window_depth = 8`), concurrent in-flight packets without stop-and-wait degradation | Per-stream 8-slot selective-repeat scoreboard, retry payload buffers, and independent per-stream retransmission timers |
| **3. CRC-32C Integrity** | **CRC-32C** (Castagnoli `0x1EDC6F41`, `init=0xFFFFFFFF`, `refin=true`, `refout=true`, `xorout=0xFFFFFFFF`) across header, payload, and ACK frames | Synthesizable CRC-32C generator/checker verified against standard check vector `"123456789" -> 0xE3069283` |
| **4. Out-of-Order Reassembly** | **8-slot out-of-order buffer per stream**, duplicate suppression, complete-message reassembly, and in-order per-stream retirement | Per-stream bitmap & reassembly buffer with decoupled ACK FIFO to prevent TX-full deadlock |
| **5. Retry Exhaustion & Reset** | Finite queues/buffers, sequence wrap-around isolation, simultaneous timeout+ACK priority, and explicit `UNACKNOWLEDGED` reporting | Generation-isolated state machines and deterministic `UNACKNOWLEDGED` completion reporting without false delivery claims |

## Delivered RTL Module Inventory

| Module File | Lines | Hardware Role |
| --- | --- | --- |
| [`rtl/sable_endpoint.sv`](rtl/sable_endpoint.sv) | `147` LOC | Top-level full-duplex endpoint integrating TX segmentation, RX reassembly, and link arbitration |
| [`rtl/sable_tx.sv`](rtl/sable_tx.sv) | `427` LOC | 4-stream segmentation, 8-slot sliding window, retransmission timers, and CRC-32C frame generator |
| [`rtl/sable_rx.sv`](rtl/sable_rx.sv) | `405` LOC | CRC-32C frame verifier, 8-slot out-of-order reassembly buffer, duplicate filter, and ACK generator |

## Related projects

- AI / embeddings: [Anvil-Q](https://github.com/aHappend/anvil-q), [Anvil-E](https://github.com/aHappend/anvil-e), [Anvil-QN](https://github.com/aHappend/anvil-qn), [Anvil-EN](https://github.com/aHappend/anvil-en), [Anvil-D](https://github.com/aHappend/anvil-d).
- Systems: [Hammer-V](https://github.com/aHappend/hammer-v), [Furnace-X](https://github.com/aHappend/furnace-x).
- DSP / vision: [Billet-F](https://github.com/aHappend/billet-f), [Billet-T](https://github.com/aHappend/billet-t), [Swage-S](https://github.com/aHappend/swage-s).
- Data / security / graphics: [Bellows-L](https://github.com/aHappend/bellows-l), [Bellows-N](https://github.com/aHappend/bellows-n), [Rivet-A](https://github.com/aHappend/rivet-a), [Rivet-H](https://github.com/aHappend/rivet-h), [Crucible-G](https://github.com/aHappend/crucible-g), [SABLE](https://github.com/aHappend/sable).
- [Public fleet catalog](https://github.com/aHappend/vulcan-showcase). Related independent research: [ACE-2](https://github.com/aHappend/ace-2), [ACE-3](https://github.com/aHappend/ace-3); these retain their own provenance and acceptance boundaries.
- DSpark is a research direction, not a published chip delivery in this repository; no implementation or repository link is asserted here.
