# SABLE — 可靠多流消息传输 RTL

[English](README.md) · [简体中文](README.zh-CN.md) · [Repository guide / 文件导航](REPOSITORY_GUIDE.md)

文档更新：2026-11-17。本页对应仓库快照，不是实时作业看板。

## 概览

**SABLE**：可靠多流消息传输 RTL。下方保留芯片技术与报告入口；具体实现范围以所链接目录、规范、测试和结果原件为准。

芯片项目公开；Vulcan 本身保持私有、闭源。今后公开发布仅限芯片技术与公开复现资料，不得包含 Vulcan 内部架构或运作资料。本次更新仅整理文档，并非对全部历史材料进行全面披露审查，也不声称既有仓库树已完成此类清查。

## 范围与证据

按实际目录核对[公开结果索引](REPOSITORY_GUIDE.md)。功能仿真、综合、独立 IP／虚拟引脚时序、板卡桥接探测、工作负载数值读回和系统软件执行是不同层级；一种通过不能替代另一种。现有历史结果保留，不因本次文档更新自动升级或作废。

时钟、资源与性能指标必须读取对应目录的原始记录和适用条件；同名副本不合并为一个数值。此处不宣称全系完成上板、完整模型推理、Linux 实机启动或功耗／能效测量。

## 文件导航

[文件与证据导航](REPOSITORY_GUIDE.md)列出真实存在的源码、约束、测试、报告及结果路径。连字符、下划线和 `chips/` 目录可能是不同发布副本，不自动指定某份为权威，也不移动或删除原件。

公开复现从对应芯片的规范、测试说明和脚本开始；所需工具、输入和板卡条件以该目录为准。文档更新没有重新执行芯片实验。

## 工程签核交付物总览

| 签核维度 | 已验证工程交付物 |
| --- | --- |
| **可综合 RTL 源码 (`rtl/*.sv`)** | **3 个核心模块 · 979 行** ([`sable_endpoint.sv`](rtl/sable_endpoint.sv)、[`sable_tx.sv`](rtl/sable_tx.sv)、[`sable_rx.sv`](rtl/sable_rx.sv)) |
| **架构与协议规范 (`design/`)** | [`design/ARCHITECTURE.md`](design/ARCHITECTURE.md) · [`design/SPEC.md`](design/SPEC.md) |
| **自检仿真与故障注入验证 (`tests/`)** | **10 套独立验证集**（协议黄金参考模型、TX/RX 独立单测、丢包/乱序/篡改/反压链路模型、多随机种子与负向变异检测） |
| **逻辑综合签核** | 通过 `yosys` 综合检查（`hierarchy -check; proc; opt; check -assert; stat`），`0` 锁存器推断 |
| **正式工程报告 (`REPORT.pdf`)** | [**`REPORT.pdf`**](REPORT.pdf) · [`REPORT.md`](REPORT.md) |

测试套件数量与通用综合结果来自已有报告，并非本次文档更新重新执行；参见[测试说明](tests/README.md)和[技术报告](REPORT.md)。

## 系统微架构与协议规格

| 子系统维度 | 协议规范要求 | 硬件微架构实现 |
| --- | --- | --- |
| **1. 多流数据通路接口** | 单时钟域，64 位 `ready`/`valid` 接口，**4 条独立并发流**，消息长度 **1–4096 B**，最大帧载荷 **256 B**，支持非对齐尾字节 | 每流独立消息分段器、尾拍字节掩码（`keep`）对齐与工作保持型公平轮询仲裁 |
| **2. 滑动发送窗口** | **每流 8 个未确认在途包**（`window_depth = 8`），全流水并发发送（不退化为停等协议） | 每流 8 槽选择性重传记分板、重传载荷缓存与独立超时重传计时器 |
| **3. CRC-32C 完整性保护** | **CRC-32C**（Castagnoli `0x1EDC6F41`）保护流 ID、序列号、消息边界、有效载荷与 ACK 控制帧 | 可综合硬件 CRC-32C 生成/校验器，通过标准校验向量 `"123456789" -> 0xE3069283` 验证 |
| **4. 接收端乱序缓存与重组** | **每流 8 槽乱序接收缓存**、重复包抑制、完整消息重组与按流保序交付 | 每流位图与重组缓冲器，配备独立解耦 ACK FIFO 防止发送窗口满时死锁 |
| **5. 重传上限与边界恢复** | 有限深度队列背压、序列号回绕隔离、超时与 ACK 同拍优先级裁决及 `UNACKNOWLEDGED` 显式上报 | 代际隔离状态机，重传耗尽时精确上报 `UNACKNOWLEDGED` 状态，零误报交付 |

## 可综合 RTL 模块清单

| 模块文件 | 代码行数 | 硬件功能描述 |
| --- | --- | --- |
| [`rtl/sable_endpoint.sv`](rtl/sable_endpoint.sv) | `147` 行 | 顶层全双工传输端点，集成 TX 分段发送、RX 乱序重组与物理链路复用仲裁 |
| [`rtl/sable_tx.sv`](rtl/sable_tx.sv) | `427` 行 | 4 流消息分段、8 槽滑动窗口记分板、超时重传引擎与 CRC-32C 帧封装 |
| [`rtl/sable_rx.sv`](rtl/sable_rx.sv) | `405` 行 | CRC-32C 帧校验、8 槽乱序重组缓冲、重复帧过滤与解耦 ACK 帧生成 |

---
<p align="center"><sub>作者：<strong>Sufeng Guo</strong> · 微软亚洲研究院 (Microsoft Research Asia) · <a href="mailto:sufeng_guo@smail.nju.edu.cn">sufeng_guo@smail.nju.edu.cn</a> · <a href="LICENSE">MIT License</a></sub></p>

## 关联项目

- AI / embeddings: [Anvil-Q](https://github.com/aHappend/anvil-q), [Anvil-E](https://github.com/aHappend/anvil-e), [Anvil-QN](https://github.com/aHappend/anvil-qn), [Anvil-EN](https://github.com/aHappend/anvil-en), [Anvil-D](https://github.com/aHappend/anvil-d).
- Systems: [Hammer-V](https://github.com/aHappend/hammer-v), [Furnace-X](https://github.com/aHappend/furnace-x).
- DSP / vision: [Billet-F](https://github.com/aHappend/billet-f), [Billet-T](https://github.com/aHappend/billet-t), [Swage-S](https://github.com/aHappend/swage-s).
- Data / security / graphics: [Bellows-L](https://github.com/aHappend/bellows-l), [Bellows-N](https://github.com/aHappend/bellows-n), [Rivet-A](https://github.com/aHappend/rivet-a), [Rivet-H](https://github.com/aHappend/rivet-h), [Crucible-G](https://github.com/aHappend/crucible-g), [SABLE](https://github.com/aHappend/sable).
- [Public fleet catalog](https://github.com/aHappend/vulcan-showcase). Related independent research: [ACE-2](https://github.com/aHappend/ace-2), [ACE-3](https://github.com/aHappend/ace-3); these retain their own provenance and acceptance boundaries.
- DSpark 是研究方向，不代表本仓库已交付对应芯片；此处不虚构实现或仓库链接。
