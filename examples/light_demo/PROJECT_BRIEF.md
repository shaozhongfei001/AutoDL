# Light Demo: Parameter Search on a Toy Objective

Smoke-test the full agent loop THINK → EXECUTE → MONITOR → REFLECT,
with an emphasis on exercising the **default experiment monitor**
(`poll_interval` is configured, and the agent MUST launch a training
process that outlives it so the monitor's polling loop is observed).

## Goal
Find the learning rate `lr` that minimizes `f(lr) = (lr - 0.25)^2 + 0.01`
on the interval [0.01, 1.0]. The true minimum is at `lr = 0.25`.

## Codebase
- Training script: `train.py` (to be created by the agent).
- Pure Python + stdlib only (no PyTorch, no numpy).
- `train.py` takes `--lr` and `--steps`, and MUST:
  - print a `step <n>/<total> | metric=<v>` line on each step,
  - print a final `metric=<v>` line on stdout,
  - sleep ~1s between steps so a run with `--steps 60` lasts ~60s.

## What to Try (IMPORTANT)
1. Create `train.py` implementing the above, using only the standard library.
2. **MUST launch a real training run that lasts LONGER than the monitor's
   poll interval** (e.g. `python train.py --lr 0.5 --steps 60`), using the
   framework's experiment-launch tool so the monitor can track its PID and
   log file. Do NOT just compute the answer analytically and skip training.
3. Let the monitor observe the run to completion, then report the final
   metric and any decision for the next cycle.

## Constraints
- No external packages. Pure Python 3.10+.
- Every run must print `metric=...` lines and be a real subprocess.
- Max 5 runs per cycle.
- Do not write outside this project directory.

## Current Status
No experiments run yet. Starting from scratch.

## Success Criteria
- A run reaches `f(lr) < 0.001` (lr close to 0.25).
- A training process is actually launched and monitored (not skipped).
