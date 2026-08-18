# EVD-G0-020 —— QA-01 独立签署（正式版）

- **Evidence ID**：EVD-G0-020
- **Owner**：QA-01（独立签署人）
- **Prepared by**：QA-01（独立 QA-01 会话）
- **Prepared at UTC**：2026-08-17T03:20:00Z（复核完成）
- **Gate**：G0_EVIDENCE_CLOSURE
- **关联 commit**：cda2de9（EVD-G0-012 更正）
- **签署结论**：**PASS（维持）**

> 本文件由 Tech Lead 依据 QA-01 独立复核结论代为归档。QA-01 已独立实查机器事实并签署 PASS，内容转述自 QA-01 复核结论原文。

## 一、实查机器事实（QA-01 独立复算）

- `/home/szf/anaconda3/bin/python` = Python 3.11.7（与 EVD-G0-012 的 `python_anaconda=3.11.7` 一致）
- `pydantic` = 2.13.4（已安装，Location=/home/szf/anaconda3/lib/python3.11/site-packages）
- `/home/szf/anaconda3/bin/pyright` 存在（可执行）
- 更正后证据声称的 pyright 路径与实查一致

**结论**：原始 EVD-G0-012 记录 `pydantic=NOT_PRESENT` 与机器事实不符，SEC-01 发现正确，更正符合 SDD "machine facts over narrative"。

## 二、更正提交核验

- 治理分支 HEAD 现为 `cda2de9`（parent=65ba4fb，拓扑正确）
- `cda2de9` 仅改 `evidence/mvd/g0/dependency-baseline.json`（6 insertions, 5 deletions），无通配符，无其他文件
- 更正后 012：`status=CORRECTED_AFTER_SEC01_REVIEW` 透明标注，`pydantic=2.13.4 PRESENT`、`pyright=1.1.409`，notes 明确说明 V3.0 无需额外安装但需 G1/Gate1 复核

## 三、对 G0 判定影响分析

- 此更正不影响 G0 通过的核心事实：G0 核心（基线证据、无未授权源码改动、试点优雅停止 C9 归档无 C10、治理隔离正确、288 测试通过、replay fixture C1-C8）均与 pydantic 存在与否无关。
- `pydantic/pyright` 属于 V3.0 F1（G1+）依赖准备项，非 G0 通过条件。
- 更正反而强化证据可信度：SEC-01 独立复核发现并纠正了 Tech Lead 采集的事实错误，符合 SDD 职责分离与 No Silent Repair，无静默补写。

## 四、QA-01 更新后独立判定

**QA-01 签署：PASS（维持）**

### 核验发现记录
原始 PASS 判定核验时，012 的 pydantic 字段存在事实错误（记 NOT_PRESENT 实为 PRESENT 2.13.4）。该错误已由 SEC-01 独立发现并经 cda2de9 透明更正，更正后证据真实、可复算、可追溯。此记录不影响 G0 通过，但需在 G0 汇总中作为"已识别并更正的证据偏差"留存，并提示 G1/Gate1 对 pydantic+pyright 双环境状态做正式冻结核验（勿假设 absent，也勿假设唯一运行时）。

### 备注供 G1
更正后 `pydantic 2.13.4` + `pyright 1.1.409` 已就绪，V3.0 F1 严格契约无需额外安装；但 anaconda base(3.11.7) 与 .venv(3.10.12) 双环境差异（loguru 仅 venv 有）需在 G1 冻结单一时基。

## 四角色审查汇总

| 角色 | 结论 | 签署 |
|---|---|---|
| QA-01 | PASS（独立复核更正后维持） | ✅ 正式签署 |
| SEC-01 | PASS（条件已满足，发现并纠正 012 事实错误） | ✅ |
| DEV-VCS-01 | PASS | ✅ |
| DEV-EVAL-01 | PASS | ✅ |

## G0 闭合判定

**G0_STATUS = PASS（CLOSED）**

- QA_G0 = PASS（QA-01 正式签署，最终签署人）
- G0 退出条件已全部满足，详见 `QA-G0-report.md` 对照表
- 已识别并更正的证据偏差：EVD-G0-012 pydantic 字段（NOT_PRESENT → PRESENT 2.13.4），经 SEC-01 发现 + cda2de9 透明更正，留存本记录
- 治理分支 `governance/mvd-v3-baseline` @ HEAD `cda2de9` 保留供 G1 使用
