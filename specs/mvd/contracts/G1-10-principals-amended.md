# G1-10a — Principals 修订（D-10）

- **策略 ID**：MVD-PRINCIPALS-V2
- **状态**：APPROVED_AS_AMENDED_D10
- **Owner 决定**：`D10=APPROVED_AS_AMENDED_SEPARATE_SERVICE_PRINCIPALS`
- **生效**：STUDY-MVD-SH-QWEN-001（G1）
- **更新于 UTC**：2026-08-17T04:50:00Z

## 正式决定（Owner）

四个独立 service principals：

```text
ITERATIVE_PRINCIPAL=svc-mvd-iterative-v1
FINAL_EVAL_PRINCIPAL=svc-mvd-final-eval-v1
COMMITTER_PRINCIPAL=svc-mvd-committer-v1
QA_PRINCIPAL=qa-01-readonly-review
```

> **QA-01 不兼任 final-eval 运行主体**。QA-01 是独立审查角色，不承担运行时生产职责，只读证据并签署报告。

## 各 principal 权限边界

| principal | test read | decision write | champion write | iterative memory write | 职责 |
|---|---|---|---|---|---|
| svc-mvd-iterative-v1 | **否** | 否 | 否 | 是（仅自身 memory） | 逐轮选优，生成 candidate |
| svc-mvd-final-eval-v1 | **是** | 否 | 否 | 否 | 独立 final-eval 运行，产出 test 指标 |
| svc-mvd-committer-v1 | 否（无 raw metric/test read） | 是（仅接收已签名 FinalDecision） | 是 | 否 | 仅按已签名 FinalDecision 提交 |
| qa-01-readonly-review | 只读证据 | 否 | 否 | 否 | 只读证据，独立签署 QA 报告 |

权限规则：
- iterative：无 test read、无 decision write、无 champion write。
- final-eval：有 test read，但无 iterative memory / decision / champion write。
- committer：无 raw metric/test read，只接收已签名 FinalDecision。
- QA-01：只读证据并签署报告，不承担运行时生产职责。

## G2 映射要求

G2 必须把这些逻辑 principal 映射到**可执行的 OS/service identity 和 ACL**。

## 影响

- 本修订替换原方案（原把 QA-01 当作 final-eval principal，不批准）。
- 更新 G1-09 isolation contract 的 principals 段。
