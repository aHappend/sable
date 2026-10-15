<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="brand/logo-dark.svg">
    <img src="brand/logo.svg" width="480" alt="Vulcan">
  </picture>
</p>

<h1 align="center">SABLE · 多流分片确认可靠消息传输引擎</h1>

<p align="center">
  可综合 SystemVerilog 多流可靠传输引擎 RTL 设计，展示真实硬件工程成果。
  <br>
  <a href="https://ahappend.github.io/vulcan/">访问官网</a>
  · <a href="https://github.com/aHappend/vulcan-showcase">Vulcan 作品集</a>
  · <a href="README.md">English</a>
  · <a href="OBJECTIVE.md">原始任务规格书</a>
  · <a href="design/">架构与协议规格</a>
  · <a href="rtl/">RTL 源码</a> · <a href="REPORT.pdf">正式技术报告 (PDF)</a>
  · <a href="brand/">品牌素材</a>
</p>

**SABLE**（*Segmented Acknowledged Buffered Link Engine*，分片确认缓冲链路引擎）是一个单时钟、可综合的四流可靠消息传输引擎，由 **Vulcan 0.8** 在 1:1 同题双盲硬件工程对比实验（`aHappend/sable`）中从空白工作区全自主完成规格制定、微架构划分、SystemVerilog RTL 实现、独立协议参考模型验证与通用综合交付。

## 工程实时进展与交付物总览

| 指标项 | 当前状态 / 数值 |
| --- | --- |
| **自主研发引擎** | **Vulcan 0.8**（后端模型 `gpt-6.1-sol`，全自治 `no_operator_assumption` 闭环） |
| **当前工程进度** | 当前阶段：`completed`（第 3 步）— 已发布正式报告 (`REPORT.pdf`) |
| **可综合 RTL 模块（`rtl/*.sv`）** | **3 个模块 / 共 979 行** |
| **架构与协议文档（`design/*.md`）** | **2 份文档**（[`design/ARCHITECTURE.md`](design/ARCHITECTURE.md), [`design/SPEC.md`](design/SPEC.md)） |
| **验证与参考模型套件（`tests/*`）** | **10 个文件** |
| **产品技术白皮书（`REPORT.pdf`）** | [**已发布 (`REPORT.pdf`)**](REPORT.pdf) |
| **最近同步时间** | `2026-10-15 21:13:37 UTC+8` |

## 系统架构与六大核心规格映射

| 子系统 / 维度 | 题目规格要求 | 硬件工程实现要点 |
| --- | --- | --- |
| **一、基本功能与多流接口** | 单时钟设计、64 位 `ready`/`valid` 数据接口、支持 **4 条独立消息流**；每条消息 **1～4096 字节**；每包有效载荷最多 **256 字节**（不含包头与 CRC）；正确处理非整拍尾部与非满长尾分片 | 4 流独立消息分片器、尾拍字节掩码（`keep`）对齐、每流独立状态维护与跨流公平轮询仲裁 |
| **二、每流 8 包滑动发送窗口** | 每条流支持深度为 **8 个未确认数据包** 的发送窗口，允许多个数据包同时在途，绝不退化为停等协议 | 每流 8 槽位选择性重传（Selective Repeat）发送窗口、重传载荷缓存与独立超时重传计数器 |
| **三、CRC-32C 端到端完整性保护** | 采用 **CRC-32C**（标准向量 `"123456789" -> 0xE3069283`），完整保护流标识、序号、分片边界、数据载荷与确认（ACK）语义，防止损坏 ACK 错误推进窗口 | 可综合 CRC-32C 硬件编解码逻辑，同时覆盖数据帧与确认/控制帧 |
| **四、乱序缓存与消息有序重组** | 接收端完成完整性校验、**每流 8 包乱序缓存**、重复包抑制、消息重组与同流有序交付 | 接收端每流乱序重排槽位、独立 32 项 ACK 发送队列（确保数据发送窗口满时确认通路不死锁） |
| **五、有限资源边界与回绕/复位隔离** | 有限队列背压处理、单流等待不阻塞其他就绪流、序号回绕旧包隔离、超时与确认同拍处理、重试耗尽报告“未获确认（`UNACKNOWLEDGED`）”及传输中复位恢复 | 会话/代际（`session_id`）旧包隔离机制、重试耗尽精确状态上报（绝不伪报成功） |
| **六、独立参考模型验证与 Yosys 综合** | 基于外部协议行为的独立参考模型；分别验证 TX、RX 与端到端故障注入（丢包、重复、乱序、损坏、延迟、背压）；≥3 个固定随机种子回归 + 负向检错敏感度验证 + Yosys 通用综合 | `iverilog -g2012` / `vvp` 自检回归 + 受控错误注入负向测试 + `yosys` 综合签核 |

## 已交付 RTL 模块清单

| 模块文件 | 代码规模 | 功能说明 |
| --- | --- | --- |
| [`rtl/sable_endpoint.sv`](rtl/sable_endpoint.sv) | `147` 行（`6026` B） | 可综合 SystemVerilog RTL 核心模块 |
| [`rtl/sable_rx.sv`](rtl/sable_rx.sv) | `405` 行（`16565` B） | 可综合 SystemVerilog RTL 核心模块 |
| [`rtl/sable_tx.sv`](rtl/sable_tx.sv) | `427` 行（`17420` B） | 可综合 SystemVerilog RTL 核心模块 |

## 仓库目录结构

```text
.
├── OBJECTIVE.md         # SABLE 1:1 双盲对比实验完整原始任务书
├── design/              # 接口与协议规范 (SPEC.md) 及微架构设计文档 (ARCHITECTURE.md)
├── rtl/                 # 可综合 SystemVerilog RTL 模块 (sable_endpoint.sv, sable_tx.sv, sable_rx.sv 等)
├── tests/               # 独立协议参考模型、链路故障注入器与自检测试套件
├── brand/               # 展示仓库品牌视觉素材
└── REPORT.pdf           # 独立审阅产品技术白皮书（验证通过后生成）
```

## 架构师自主编写的集成与验证技术说明（原文附录）

完整独立技术说明文件：[`DESIGN_README.md`](DESIGN_README.md)

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

## 许可

公开的代码、文档与视觉素材采用 [MIT License](LICENSE)。
