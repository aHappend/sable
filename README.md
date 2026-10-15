<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="brand/logo-dark.svg">
    <img src="brand/logo.svg" width="420" alt="SABLE">
  </picture>
</p>

<h1 align="center">SABLE · Segmented Acknowledged Buffered Link Engine</h1>

<p align="center">
  Synthesizable Multi-Stream Reliable Message Transport Engine in SystemVerilog
  <br>
  Engineered autonomously by <b>Vulcan 0.8</b> · Public Open-Source Repository
</p>

---

## Overview

**SABLE** (*Segmented Acknowledged Buffered Link Engine*) is a synthesizable single-clock multi-stream reliable message transport engine featuring a 64-bit `ready`/`valid` data interface, 4 independent streams, 8-packet sliding send window per stream, 1–4096B message segmentation into $\le 256$B payload frames, CRC-32C header + payload + ACK integrity protection, out-of-order reassembly, duplicate suppression, sequence wrap-around isolation, in-flight reset recovery, and bounded retry exhaustion reporting.

- **Current RTL Modules (`rtl/*.sv`)**: `0` files (`0` lines)
- **Product Report (`REPORT.pdf`)**: `In Progress`
- **Last Synced**: `2026-10-15 18:02:30 UTC+8`

See [`OBJECTIVE.md`](OBJECTIVE.md) for the complete specification.
