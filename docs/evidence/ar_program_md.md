# Evidence: autoresearch program.md 核心协议
# Source: /home/szf/env/autoresearch/program.md
# Supports: 建议B(git回退闭环)、建议C(simplicity)、NEVER STOP

## 单文件修改约束（建议D 证据）
**What you CAN do:**
- Modify `train.py` — this is the only file you edit. Everything is fair game: model architecture, optimizer, hyperparameters, training loop, batch size, model size, etc.

**What you CANNOT do:**
- Modify `prepare.py`. It is read-only. It contains the fixed evaluation, data loading, tokenizer, and training constants (time budget, sequence length, etc).
- Install new packages or add dependencies.
- Modify the evaluation harness. The `evaluate_bpb` function in `prepare.py` is the ground truth metric.

## Simplicity criterion（建议C 证据）
**Simplicity criterion**: All else being equal, simpler is better. A small improvement that adds ugly complexity is not worth it. Conversely, removing something and getting equal or better results is a great outcome — that's a simplification win. When evaluating whether to keep a change, weigh the complexity cost against the improvement magnitude. A 0.001 val_bpb improvement that adds 20 lines of hacky code? Probably not worth it. A 0.001 val_bpb improvement from deleting code? Definitely keep. An improvement of ~0 but much simpler code? Keep.

## Git 驱动的实验闭环（建议B 证据）
The experiment loop (LOOP FOREVER):
1. Look at the git state: the current branch/commit we're on
2. Tune `train.py` with an experimental idea by directly hacking the code.
3. git commit
4. Run the experiment: `uv run train.py > run.log 2>&1`
5. Read out the results: `grep "^val_bpb:\|^peak_vram_mb:" run.log`
6. If the grep output is empty, the run crashed...
7. Record the results in the tsv (do not commit the results.tsv file)
8. If val_bpb improved (lower), you "advance" the branch, keeping the git commit
9. If val_bpb is equal or worse, you git reset back to where you started

The idea is that you are a completely autonomous researcher trying things out. If they work, keep. If they don't, discard. And you're advancing the branch so that you can iterate.

## NEVER STOP（建议E 参考）
**NEVER STOP**: Once the experiment loop has begun, do NOT pause to ask the human if you should continue... You are autonomous. If you run out of ideas, think harder... The loop runs until the human interrupts you, period.

As an example use case, a user might leave you running while they sleep. If each experiment takes you ~5 minutes then you can run approx 12/hour, for a total of about 100 over the duration of the average human sleep.
