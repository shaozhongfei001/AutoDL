# ADR-MVD-001 — Strict Pydantic v2 / pyright / JSON Schema / Versioning

- **ADR ID**：ADR-MVD-001
- **主题**：strict schema 与版本化
- **Owner**：ARCH-01
- **状态**：DRAFT_FOR_G1_REVIEW
- **生效版本**：study-contract/v1（G1）
- **关联 Gate**：G1（合同基线）→ G4（F1 strict contracts）
- **日期**：2026-08-17

## 决策

使用 **Pydantic v2** 作为运行时严格 schema 校验框架，结合 **pyright strict** 静态类型检查与 **JSON Schema** 合同导出。所有合同/指标/产物 schema 采用显式版本化（如 `study-contract/v1`、`artifact-manifest/v1`、`mvd-ledger/v1`）。

- Pydantic v2（已确认 2.13.4，双环境就绪）
- pyright 1.1.409（静态类型检查，strict 模式）
- JSON Schema 作为跨工具机器可读合同载体
- schema 版本号固化在 contract/schema 字段中

## 替代方案

| 替代 | 否决理由 |
|---|---|
| 仅运行时 assert / 手写校验 | 无声明式 schema，无法机器导出 JSON Schema 供独立验证 |
| dataclasses 无校验 | 无类型级强制，无法达到 strict contracts 要求 |
| mypy 代替 pyright | pyright 更贴近 Pylance/VS Code 生态，且 1.1.409 已就绪 |

## 风险

- Pydantic v2 与 Pydantic v1 有 API 差异；本项目从 v2 起步无迁移成本。
- pyright strict 可能对现有宽松代码产生大量告警；需在 F1 阶段逐个消解。
- JSON Schema 与 Pydantic model 需要双向一致维护，否则 drift。

## 回滚

- 若 pyright strict 阻塞交付，可临时降级为 `pyright basic`（记录为例外）并提交 QA 评审，不静默放宽。
- Pydantic v2 若出现不兼容，回退依赖锁文件（G1-01 full dependency lock）到上一可用版本。

## Owner 与生效

- Owner：ARCH-01
- 生效条件：G1 Study Contract 批准时生效，V3.0 F1（G4 输入）落实代码。
