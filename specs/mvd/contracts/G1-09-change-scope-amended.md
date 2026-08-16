# G1-09a — Change Scope 修订（D-09）

- **策略 ID**：MVD-CHANGE-SCOPE-V2
- **状态**：APPROVED_AS_AMENDED_D09
- **Owner 决定**：`D09=APPROVED_AS_AMENDED_ALLOWLIST_TRAIN_FT_ONLY`
- **生效**：STUDY-MVD-SH-QWEN-001（G1）
- **更新于 UTC**：2026-08-17T04:45:00Z

## 正式决定（Owner）

```text
CHANGE_ALLOWLIST=["train_ft.py"]
MAX_CHANGED_FILES=1
MAX_DIFF_LINES_ADDED_PLUS_DELETED=200
DEPENDENCY_CHANGE_ALLOWED=NO
DEFAULT_REPOSITORY_WRITE_POLICY=DENY
```

## 语义澄清

- `train_ft.py` 是 **allowlist**（允许修改的实验脚本），**不是 protected path**。
- **除 train_ft.py 外，整个仓库默认受保护（DENY）**，包括：

| 路径 | 保护原因 |
|---|---|
| `.git/**` | VCS 完整性 |
| `tests/` 与 final-test 资产 | 测试 oracle 只读 |
| evaluator、dataset 与 split | 数据/评估只读 |
| `specs/mvd/**`、`evidence/mvd/**` | 治理契约只读 |
| `requirements`、lockfile | 依赖锁定 |
| Judge、Committer、policy 和权限配置 | 治理边界 |

## 防绕过

- rename、symlink、submodule、binary replacement **不得绕过**文件数或 diff 限制。
- 文件数限制（MAX_CHANGED_FILES=1）与 diff 限制（MAX_DIFF_LINES_ADDED_PLUS_DELETED=200）同时强制，按两者均不超限判定。

## 依据

Owner 明确：强隔离，不按成本降级（符合 SEC-01 建议）。

## 影响

- 本修订替换原 Study Contract `change_scope` 部分（原 allowlist 含 `workspace/`，现收紧为仅 `train_ft.py`）。
- G1-09 isolation contract 的 change_scope 引用本修订。
