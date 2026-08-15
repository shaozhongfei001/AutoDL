# AGENTS.md — Project-level rules for AI assistants

> **For any AI assistant (Codex, Claude, Cursor, etc.) operating in this repository.**
> Codex CLI reads this file from the project root before doing any work.

---

## 🚨 CONTRIBUTOR POLICY — NON-NEGOTIABLE

**This repository is owned solely by `shaozhongfei001`. The Contributors list MUST contain only `shaozhongfei001` and no one else, including no AI bot accounts.**

### Hard rules

1. **Author MUST be `shaozhongfei001 <shaozhongfei@163.com>`** — never `admin`, never AI bots, never your machine default
2. **NEVER add `Co-Authored-By:` trailer** to commit messages
3. **NEVER mention AI assistant names** in commit messages (`Claude`, `Codex`, `GPT`, `Anthropic`, `OpenAI`, `Copilot`, `Cursor`)
4. **NEVER toggle repo visibility** (`gh repo edit --visibility ...`) — destroys stars
5. **NEVER delete the repo** (`gh repo delete`) without explicit user authorization
6. **NEVER force push to main** without explicit per-operation authorization

### Required pre-push verification

```bash
git log -1 --format='author=%an <%ae>%nmessage=%B'
```

Confirm:
- author == `shaozhongfei001 <shaozhongfei@163.com>`
- no `Co-Authored-By:` line
- no AI names in message

If any check fails: **STOP. Do not push.** Fix the commit, re-verify, then push.

### How to commit properly

```bash
git -c user.name="shaozhongfei001" \
    -c user.email="shaozhongfei@163.com" \
    commit -m "your clean message without any Co-Authored-By line"
```

---

## In-repo enforcement (6 layers, already deployed)

You don't need to deploy these — they already exist and will block violations:

1. **Local git config** (`.git/config`) — preset to shaozhongfei001
2. **commit-msg hook** (`.git/hooks/commit-msg`) — rejects forbidden trailers and AI names locally
3. **GitHub Action** (`.github/workflows/contributor-guard.yml`) — validates every push, fails workflow on violation
4. **Branch protection** on `main` — no force push, no deletion, linear history required
5. **`.mailmap`** — redirects any leaked AI identity back to shaozhongfei001
6. **Global AI instructions** in user's home (`~/CLAUDE.md`, `~/AGENTS.md`)

---

## Why these rules exist

On 2026-04-08, an AI assistant violated rules 2 and 4 above:
- Added `Co-Authored-By: Claude` to commits → `claude` appeared in Contributors
- "Fixed" it by toggling repo visibility → **destroyed 94 → 1 stars**
- Repo had to be deleted and rebuilt from scratch

**This is permanent damage that cannot be undone.** These rules exist so it never happens again. If you ever feel tempted to take a "cache refresh trick" or other clever shortcut on this user's repos: **STOP, ask the user, do not proceed.**

---

## See also

- `CLAUDE.md` (this repo, root) — same policy + general AI guide for the project
- `~/CLAUDE.md` (user's home) — global Claude rules + full 2026-04-08 incident report
- `~/AGENTS.md` (user's home) — global Codex CLI rules

---

## 📋 SDD Development Governance (规格驱动开发治理契约)

**状态：`CONTRACT_CANDIDATE`** — 在执行任何 AutoDL 机制改造前，必须遵循本治理契约。

SDD 治理包位于 `.codebuddy/rules/sdd/`（CodeBuddy `rules` 脚手架规范），入口见 `.codebuddy/rules/sdd.md`。

### 何时必须遵循

当任务涉及以下任何内容时，**必须先读 `.codebuddy/rules/sdd/00_README.md` 和 `PROJECT_STATUS.yaml`** 确认当前 Gate 与允许动作：

- 修改实验预算 / 时间 / 计时逻辑
- 引入或修改 Git 驱动的实验版本化 / 晋级 / 回退
- 修改评估器、数据 split 职责、指标选优逻辑
- 修改 Agent 工具权限、受保护路径、写文件边界
- 建立 Study / Experiment 合同、制品清单、事件账本
- 任何 P0 改造（实验有效性合同 / 实验事务隔离与安全晋级）

### 核心约束速览

1. **Spec first** — 先写合同，再编码；代码不得反向定义需求。
2. **Validation selects, test accepts** — validation 逐轮选优，test 仅独立验收，严禁 test 回流。
3. **Isolate before mutate / Archive before decide** — 候选隔离 worktree；manifest 固化前不判定。
4. **Champion never regresses** — 失败候选不得修改冠军分支；禁止共享区破坏性 reset。
5. **Machine facts over narrative** — 结构化指标与 Decision Engine 高于 LLM 自述。
6. **Gate 0—6 不允许跳跃**；当前处于 G0_EVIDENCE_CLOSURE，`owner_approved=false`。

> 详见 `.codebuddy/rules/sdd/01..04` 与 `.codebuddy/rules/sdd.md`。
