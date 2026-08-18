# G1-02 环境选择报告

- **Evidence ID**：G1-02
- **Owner**：TECH_LEAD（ARCH-01）推荐，HUMAN_OWNER 最终决定
- **Gate**：G1_CONTRACT_BASELINE_PREPARATION
- **Study**：STUDY-MVD-SH-QWEN-001
- **Generated at UTC**：2026-08-17T03:40:00Z
- **相关证据**：`specs/mvd/runtime/G1-01-canonical-runtime-manifest.yaml`

## 1. 双环境对照证据（机器事实，2026-08-17 实查）

| 维度 | anaconda base (ENV-ANACONDA-BASE) | .venv (ENV-VENV) |
|---|---|---|
| Python 解释器 | `/home/szf/anaconda3/bin/python` | `/home/szf/env/AutoDL/.venv/bin/python` |
| Python 版本 | 3.11.7 | 3.10.12 |
| pydantic | 2.13.4 | 2.13.4 |
| **torch** | **2.3.0+cu121 (cuda 12.1)** | **2.5.0+cu124 (cuda 12.4)** |
| **torchvision** | **0.18.0+cu121** | **0.20.0+cu124** |
| **loguru** | **❌ 未安装** | **0.7.3 ✅** |
| **pyright** | **1.1.409 ✅**（仅类型检查工具） | ❌ 不存在 |
| 288 测试 | 无法运行（缺 loguru） | **288 passed in 1.59s** |

## 2. 判定依据

依据 **项目兼容性 → 288 测试 → 可复现性** 三层，**不按版本新旧** 决定：

### 2.1 项目兼容性（决定性）
- **loguru 硬依赖**：项目 `core/logging_setup.py` 硬依赖 loguru。anaconda base **未安装 loguru**，导入即失败，项目无法运行。`.venv` 有 loguru 0.7.3。
- **G0 基线一致**：G0 基线（EVD-G0-012 更正后 + STUDY-001 契约）记录 `torch 2.5.0+cu124, torchvision 0.20.0+cu124`，与 `.venv` 完全一致；anaconda base 是 `2.3.0+cu121/0.18.0+cu121`，不一致。

### 2.2 288 测试
- `.venv`：**288 passed in 1.59s**（2026-08-17 实测）。
- anaconda base：**无法运行**（缺 loguru）。

### 2.3 可复现性
- `.venv` 是历史 288 测试、试点（C1-C9）、基线采集一直使用的环境，证据链连续。
- anaconda base 从未作为项目运行环境，缺依赖、版本不一致。

## 3. 环境标记

| 环境 | GATE_EVIDENCE_AUTHORITY | SUPPORTED_FOR_MVD_BUILD |
|---|---|---|
| anaconda base (3.11.7) | **NO** | **NO** |
| **.venv (3.10.12)** | **YES（推荐 canonical）** | **YES** |

> 被淘汰环境（anaconda base）已标记：`GATE_EVIDENCE_AUTHORITY=NO`、`SUPPORTED_FOR_MVD_BUILD=NO`。

## 4. 推荐结论

**推荐 canonical runtime = `.venv`（/home/szf/env/AutoDL/.venv/bin/python, Python 3.10.12）**

- 唯一完整可运行环境：loguru 齐全、torch/cuda 与 G0 基线一致、288 测试全部通过。
- pydantic 2.13.4、pyright 1.1.409 双环境就绪（pyright 作为独立类型检查工具从 anaconda base 调用，不注入 runtime）。

## 5. 需 Owner 决策

- 最终 canonical runtime 选择确认（本报告推荐 .venv）。
- 若 Owner 要求 anaconda base 作为 canonical，则需补装 loguru 并重跑 288 测试、重建 torch 2.5.0+cu124 基线——不建议。

## 6. 遗留提示（供 G1 冻结）

- **双环境差异**：anaconda base(3.11.7) 与 .venv(3.10.12) Python 版本不同，但本项目运行不依赖 Python 3.11 特性，.venv 3.10.12 满足全部要求。
- **pyright**：作为静态工具，其所在环境不影响 runtime 一致性，但 V3.0 F1 strict contracts 阶段需在 G1 明确 pyright 调用约定（从 base 调用，版本锁 1.1.409）。
