# D-01 torch 版本差异闭合记录（透明更正，不覆盖原证据）

- **Closure ID**：D01-CLOSURE-20260817-001
- **Owner**：TECH_LEAD（ARCH-01）+ SEC-01
- **Gate**：G1_CONTRACT_BASELINE（REMEDIATION）
- **生成时间 UTC**：2026-08-17T04:30:00Z
- **依据**：OWNER_DECISION=PARTIAL_APPROVAL_G1_DECISION_PACK_WITH_TARGETED_REMEDIATION（D01=APPROVED_WITH_DEPENDENCY_BASELINE_CORRECTION）

## 1. 差异声明（透明更正）

Owner 指出 G0 汇报 torch 2.3.0 与 G1 声明 .venv 为 torch 2.5.0+cu124 且"与 G0 基线一致"存在矛盾。经独立核验，**该矛盾源于 G0 证据 EVD-G0-012 记录偏差**，现追加透明更正记录，不覆盖原证据。

```
DEPENDENCY_BASELINE_DISCREPANCY=OPEN->CORRECTED
G0_REPORTED_TORCH=2.3.0
G1_OBSERVED_TORCH=2.5.0+cu124
CANONICAL_RUNTIME=.venv/python3.10.12
DISCREPANCY_ROOT_CAUSE=G0_EVD-G0-012 将 anaconda base 的 torch 2.3.0 误记为"运行时"事实
TRUTH=项目运行环境始终为 .venv (torch 2.5.0+cu124)，anaconda base 从未作为项目运行环境
```

### 1.1 差异根因

- EVD-G0-012 的 `facts.torch = "2.3.0+cu121"` 并附 note "Runtime is anaconda python 3.11.7 with torch 2.3.0+cu121"。
- 该记录**错误**：anaconda base（torch 2.3.0）从未运行过项目。288 测试、试点 C1-C9、基线采集全部在 .venv（torch 2.5.0+cu124）执行。
- G0 已确认 .venv=3.10.12（012 facts），但 torch 字段误引用了 anaconda base 值。

### 1.2 依赖漂移判定

- `requirements.txt` **不含 torch**（无版本声明），SHA256=`8c390592...`。
- 安装环境 .venv 实际 torch = **2.5.0+cu124**。
- 因 requirements 未声明 torch 版本，**不构成依赖漂移**（requirements 未约束该包）；但属于"requirements 未锁定 runtime 关键依赖"的覆盖缺口，须在 G1 补 lockfile。
- **纠正**：cannot宣称"requirements 可复现 torch"；必须依赖 full freeze lockfile（见 §4）。

## 2. Canonical 环境完整证据（2026-08-17 实查）

| 证据 | 值 |
|---|---|
| Python 可执行 realpath | `/usr/bin/python3.10`（.venv symlink 目标） |
| 解释器 | `/home/szf/env/AutoDL/.venv/bin/python` |
| `python -V` | Python 3.10.12 |
| torch（pip show） | 2.5.0+cu124 |
| torch `__version__` | 2.5.0+cu124 |
| torch `version.cuda` | 12.4 |
| torchvision | 0.20.0+cu124 |
| pydantic（pip show） | 2.13.4 |
| loguru（pip show） | 0.7.3 |
| requirements.txt SHA256 | `8c390592e17a5589bc80be465a43fdff850e975bb667de698bb5e3e0eb78c943` |
| full freeze SHA256 | `ade58b5661416172832f0de5bbd13fefa4e36171c374775ae1d938bd6ced7893` |
| 288 测试 | 288 passed（2.52s / 1.50s 两次） |
| 测试报告 SHA256 | `d94a0247f3b84c743804f217bfbc5c1227e5d32d669aa9604acc976b60a3dba2` |
| canonical 环境判定 | GATE_EVIDENCE_AUTHORITY=YES, SUPPORTED_FOR_MVD_BUILD=YES |

## 3. full freeze（canonical 环境，SHA256=`ade58b56...`）

完整 freeze 见 `specs/mvd/runtime/D01-canonical-freeze.txt`（随本记录归档）。
关键项：`torch==2.5.0+cu124`、`torchvision==0.20.0+cu124`、`pydantic==2.13.4`、`loguru==0.7.3`、`numpy==2.2.6`、`pytest==9.1.1`。

## 4. lockfile 覆盖缺口与整改

- **缺口**：requirements.txt 未声明 torch/torchvision/pydantic/loguru 具体版本，无法从 requirements 复现 runtime。
- **整改**：以 `D01-canonical-freeze.txt` 作为 canonical lockfile 权威（冻结 torch 2.5.0+cu124）。G1 批准后，该 freeze 作为依赖锁基线；requirements.txt 可补充锁定但不改变 freeze 权威性。

## 5. 更正影响

- G0 核心结论不受影响（288 测试、隔离、试点停止均与 torch 字段值无关）。
- EVD-G0-012 的 torch 字段标注为偏差，本记录为透明更正。
- anaconda base 仍标记：GATE_EVIDENCE_AUTHORITY=NO, SUPPORTED_FOR_MVD_BUILD=NO（缺 loguru）。

## 6. 关联 SHA

- 治理分支 HEAD（提交本记录前）：`f1f35652848c1b0ee4c5f0a1c8cce7d0fd2b03e6`
- main base commit：`83e41c13e1032b02548d445dd3234ae127d03311`
- requirements.txt：`8c390592e17a5589bc80be465a43fdff850e975bb667de698bb5e3e0eb78c943`
- full freeze：`ade58b5661416172832f0de5bbd13fefa4e36171c374775ae1d938bd6ced7893`
- 288 测试报告：`d94a0247f3b84c743804f217bfbc5c1227e5d32d669aa9604acc976b60a3dba2`
