<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="brand/logo-dark.svg">
    <img src="brand/logo.svg" width="420" alt="Vulcan">
  </picture>
  <h1>SABLE · 多流分段确认与缓冲可靠传输引擎</h1>
  <p><strong>可综合 4 流滑动窗口可靠消息传输 SystemVerilog 硬件核 · CRC-32C 帧完整性校验 · 乱序重组与选择性重传</strong></p>
  <p>
    <img src="https://img.shields.io/badge/Language-SystemVerilog_2012-0f766e?style=flat-square" alt="SV2012">
    <img src="https://img.shields.io/badge/RTL_规模-3_模块_%C2%B7_979_行-0f766e?style=flat-square" alt="RTL">
    <img src="https://img.shields.io/badge/验证签核-10_套测试_%2B_Yosys_综合通过-1d4ed8?style=flat-square" alt="Verification">
    <img src="https://img.shields.io/badge/Author-Sufeng_Guo_(MSRA)-334155?style=flat-square" alt="Author">
    <img src="https://img.shields.io/badge/License-MIT-64748b?style=flat-square" alt="License">
  </p>
  <p>
    <a href="https://ahappend.github.io/vulcan/">项目主页</a> ·
    <a href="https://github.com/aHappend/vulcan-showcase">Vulcan 芯片总览</a> ·
    <a href="https://github.com/aHappend/anvil-q">Anvil-Q (大模型)</a> ·
    <a href="https://github.com/aHappend/anvil-e">Anvil-E (多模态向量)</a> ·
    <a href="https://github.com/aHappend/billet-t">Billet-T (频谱变换)</a> ·
    <a href="https://github.com/aHappend/billet-f">Billet-F (数字滤波)</a> ·
    <a href="https://github.com/aHappend/rivet-a">Rivet-A (认证加密)</a> ·
    <a href="https://github.com/aHappend/rivet-h">Rivet-H (杂凑认证)</a> ·
    <a href="REPORT.pdf"><strong>工程签核报告 (PDF)</strong></a> ·
    <a href="README.md"><strong>English</strong></a>
  </p>
</div>

---

**SABLE**（*Segmented Acknowledged Buffered Link Engine*）是由 **Vulcan** 架构设计、RTL 实现并完成综合与故障注入验证的单时钟多流可靠消息传输硬件引擎，支持 4 独立数据流并发分段、每流 8 槽滑动发送窗口、CRC-32C 硬件校验、接收端 8 槽乱序重排重组及重传耗尽确定性恢复。

## 工程签核交付物总览

| 签核维度 | 已验证工程交付物 |
| :--- | :--- |
| **可综合 RTL 源码 (`rtl/*.sv`)** | **3 个核心模块 · 979 行** ([`sable_endpoint.sv`](rtl/sable_endpoint.sv)、[`sable_tx.sv`](rtl/sable_tx.sv)、[`sable_rx.sv`](rtl/sable_rx.sv)) |
| **架构与协议规范 (`design/`)** | [`design/ARCHITECTURE.md`](design/ARCHITECTURE.md) · [`design/SPEC.md`](design/SPEC.md) |
| **自检仿真与故障注入验证 (`tests/`)** | **10 套独立验证集**（协议黄金参考模型、TX/RX 独立单测、丢包/乱序/篡改/反压链路模型、多随机种子与负向变异检测） |
| **逻辑综合签核** | 通过 `yosys` 综合检查（`hierarchy -check; proc; opt; check -assert; stat`），`0` 锁存器推断 |
| **正式工程报告 (`REPORT.pdf`)** | [**`REPORT.pdf`**](REPORT.pdf) · [`REPORT.md`](REPORT.md) |

## 系统微架构与协议规格

| 子系统维度 | 协议规范要求 | 硬件微架构实现 |
| :--- | :--- | :--- |
| **1. 多流数据通路接口** | 单时钟域，64 位 `ready`/`valid` 接口，**4 条独立并发流**，消息长度 **1–4096 B**，最大帧载荷 **256 B**，支持非对齐尾字节 | 每流独立消息分段器、尾拍字节掩码（`keep`）对齐与工作保持型公平轮询仲裁 |
| **2. 滑动发送窗口** | **每流 8 个未确认在途包**（`window_depth = 8`），全流水并发发送（不退化为停等协议） | 每流 8 槽选择性重传记分板、重传载荷缓存与独立超时重传计时器 |
| **3. CRC-32C 完整性保护** | **CRC-32C**（Castagnoli `0x1EDC6F41`）保护流 ID、序列号、消息边界、有效载荷与 ACK 控制帧 | 可综合硬件 CRC-32C 生成/校验器，通过标准校验向量 `"123456789" -> 0xE3069283` 验证 |
| **4. 接收端乱序缓存与重组** | **每流 8 槽乱序接收缓存**、重复包抑制、完整消息重组与按流保序交付 | 每流位图与重组缓冲器，配备独立解耦 ACK FIFO 防止发送窗口满时死锁 |
| **5. 重传上限与边界恢复** | 有限深度队列背压、序列号回绕隔离、超时与 ACK 同拍优先级裁决及 `UNACKNOWLEDGED` 显式上报 | 代际隔离状态机，重传耗尽时精确上报 `UNACKNOWLEDGED` 状态，零误报交付 |

## 可综合 RTL 模块清单

| 模块文件 | 代码行数 | 硬件功能描述 |
| :--- | :--- | :--- |
| [`rtl/sable_endpoint.sv`](rtl/sable_endpoint.sv) | `147` 行 | 顶层全双工传输端点，集成 TX 分段发送、RX 乱序重组与物理链路复用仲裁 |
| [`rtl/sable_tx.sv`](rtl/sable_tx.sv) | `427` 行 | 4 流消息分段、8 槽滑动窗口记分板、超时重传引擎与 CRC-32C 帧封装 |
| [`rtl/sable_rx.sv`](rtl/sable_rx.sv) | `405` 行 | CRC-32C 帧校验、8 槽乱序重组缓冲、重复帧过滤与解耦 ACK 帧生成 |

---
<p align="center"><sub>作者：<strong>Sufeng Guo</strong> · 微软亚洲研究院 (Microsoft Research Asia) · <a href="mailto:sufeng_guo@smail.nju.edu.cn">sufeng_guo@smail.nju.edu.cn</a> · <a href="LICENSE">MIT License</a></sub></p>
