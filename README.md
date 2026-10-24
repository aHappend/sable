<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="brand/logo-dark.svg">
    <img src="brand/logo.svg" width="420" alt="Vulcan">
  </picture>
  <h1>SABLE · Segmented Acknowledged Buffered Link Engine</h1>
  <p><strong>Synthesizable 4-Stream Sliding-Window Reliable Message Transport Engine in SystemVerilog · CRC-32C Integrity · Out-of-Order Reassembly</strong></p>
  <p>
    <img src="https://img.shields.io/badge/Language-SystemVerilog_2012-0f766e?style=flat-square" alt="SV2012">
    <img src="https://img.shields.io/badge/RTL_Footprint-3_Modules_%C2%B7_979_LOC-0f766e?style=flat-square" alt="RTL">
    <img src="https://img.shields.io/badge/Verification-10_Suites_%2B_Yosys_Passed-1d4ed8?style=flat-square" alt="Verification">
    <img src="https://img.shields.io/badge/Author-Sufeng_Guo_(MSRA)-334155?style=flat-square" alt="Author">
    <img src="https://img.shields.io/badge/License-MIT-64748b?style=flat-square" alt="License">
  </p>
  <p>
    <a href="https://ahappend.github.io/vulcan/">Website</a> ·
    <a href="https://github.com/aHappend/vulcan-showcase">Vulcan Showcase</a> ·
    <a href="https://github.com/aHappend/anvil-q">Anvil-Q (LLM)</a> ·
    <a href="https://github.com/aHappend/anvil-e">Anvil-E (Embedding)</a> ·
    <a href="https://github.com/aHappend/billet-t">Billet-T (FFT/DSP)</a> ·
    <a href="https://github.com/aHappend/billet-f">Billet-F (FIR/IIR)</a> ·
    <a href="https://github.com/aHappend/rivet-a">Rivet-A (AES-GCM)</a> ·
    <a href="https://github.com/aHappend/rivet-h">Rivet-H (SHA/HMAC)</a> ·
    <a href="REPORT.pdf"><strong>Engineering Report (PDF)</strong></a> ·
    <a href="README.zh-CN.md"><strong>中文文档</strong></a>
  </p>
</div>

---

**SABLE** (*Segmented Acknowledged Buffered Link Engine*) is a synthesizable single-clock multi-stream reliable message transport engine in SystemVerilog, architected, implemented, and verified by **Vulcan** with full CRC-32C framing, per-stream 8-slot sliding send windows, out-of-order receiver reassembly, and bounded retry exhaustion recovery.

## Executive Engineering Signoff Summary

| Signoff Dimension | Verified Deliverable |
| :--- | :--- |
| **Synthesizable RTL (`rtl/*.sv`)** | **3 modules · 979 lines** ([`sable_endpoint.sv`](rtl/sable_endpoint.sv), [`sable_tx.sv`](rtl/sable_tx.sv), [`sable_rx.sv`](rtl/sable_rx.sv)) |
| **Architecture & Protocol Spec (`design/`)** | [`design/ARCHITECTURE.md`](design/ARCHITECTURE.md) · [`design/SPEC.md`](design/SPEC.md) |
| **Verification & Fault-Injection Suite (`tests/`)** | **10 self-checking suites** (protocol oracle, standalone TX/RX, lossy/reordered/corrupted link, multi-seed regression, error sensitivity) |
| **Synthesis Signoff** | Passed `yosys` generic synthesis (`hierarchy -check; proc; opt; check -assert; stat`) with `0` inferred latches |
| **Engineering Report (`REPORT.pdf`)** | [**`REPORT.pdf`**](REPORT.pdf) · [`REPORT.md`](REPORT.md) |

## System Architecture & Protocol Specification

| Subsystem / Dimension | Specification Contract | Hardware Realization |
| :--- | :--- | :--- |
| **1. Multi-Stream Datapath** | Single clock, 64-bit `ready`/`valid` interface, **4 independent streams**, message length **1–4096 B**, max frame payload **256 B**, non-aligned tail handling | Per-stream ingress segmentation, byte-enable (`keep`) tail qualification, and work-conserving round-robin stream arbitration |
| **2. Sliding Send Window** | **8 unacknowledged packets per stream** (`window_depth = 8`), concurrent in-flight packets without stop-and-wait degradation | Per-stream 8-slot selective-repeat scoreboard, retry payload buffers, and independent per-stream retransmission timers |
| **3. CRC-32C Integrity** | **CRC-32C** (Castagnoli `0x1EDC6F41`, `init=0xFFFFFFFF`, `refin=true`, `refout=true`, `xorout=0xFFFFFFFF`) across header, payload, and ACK frames | Synthesizable CRC-32C generator/checker verified against standard check vector `"123456789" -> 0xE3069283` |
| **4. Out-of-Order Reassembly** | **8-slot out-of-order buffer per stream**, duplicate suppression, complete-message reassembly, and in-order per-stream retirement | Per-stream bitmap & reassembly buffer with decoupled ACK FIFO to prevent TX-full deadlock |
| **5. Retry Exhaustion & Reset** | Finite queues/buffers, sequence wrap-around isolation, simultaneous timeout+ACK priority, and explicit `UNACKNOWLEDGED` reporting | Generation-isolated state machines and deterministic `UNACKNOWLEDGED` completion reporting without false delivery claims |

## Delivered RTL Module Inventory

| Module File | Lines | Hardware Role |
| :--- | :--- | :--- |
| [`rtl/sable_endpoint.sv`](rtl/sable_endpoint.sv) | `147` LOC | Top-level full-duplex endpoint integrating TX segmentation, RX reassembly, and link arbitration |
| [`rtl/sable_tx.sv`](rtl/sable_tx.sv) | `427` LOC | 4-stream segmentation, 8-slot sliding window, retransmission timers, and CRC-32C frame generator |
| [`rtl/sable_rx.sv`](rtl/sable_rx.sv) | `405` LOC | CRC-32C frame verifier, 8-slot out-of-order reassembly buffer, duplicate filter, and ACK generator |

---
<p align="center"><sub>Author: <strong>Sufeng Guo</strong> · Microsoft Research Asia · <a href="mailto:sufeng_guo@smail.nju.edu.cn">sufeng_guo@smail.nju.edu.cn</a> · <a href="LICENSE">MIT License</a></sub></p>
