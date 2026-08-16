# LLM Fine-tuning Pilot — Qwen2.5-0.5B on alpaca-cleaned

## Goal
Fine-tune the smallest practical LLM — **Qwen2.5-0.5B** (~500M params) — on an
instruction-following subset of **alpaca-cleaned** to teach it to follow
instructions. This is a **multi-round, GPU-bound, unattended search over
fine-tuning hyper-parameters**, driven by machine judgment (validation_loss for
selection).

## Why this model (smallest on our 6GB GPU)
- RTX 3060 Laptop, **6GB VRAM**. Qwen2.5-0.5B full fine-tune fits in ~2.5-3GB
  (batch_size=1, max_len=128). transformers 4.41.2 ships native `Qwen2ForCausalLM`.
- ~500M params: real LLM fine-tune yet small enough to iterate on a laptop GPU.

## Baseline script (MANDATORY — modify THIS file, do NOT create a new one)
- The baseline fine-tuning script is **`train_ft.py`**, already present in the
  **workspace** (the write boundary). **Modify it in place per round. Do NOT
  create new training files, do NOT point it at paths outside the workspace.**
- Use the torch-enabled interpreter **`/home/szf/anaconda3/bin/python`** (plain
  `python` in launch_experiment resolves to a torch-less interpreter).

## Environment prerequisites (already handled inside train_ft.py)
- Model + dataset download uses `HF_ENDPOINT=https://hf-mirror.com` (huggingface.co
  unreachable). train_ft.py sets this itself — do NOT remove it.
- Model: `Qwen/Qwen2.5-0.5B`. Dataset: `yahma/alpaca-cleaned`, sub-sampled to a
  fixed count via `--max-examples` (fingerprint `alpaca-cleaned-subset-20000`).

## Search space (vary ONE hyper-parameter family per round)
1. `--lr` (1e-5 … 1e-4)
2. `--epochs` (2–4) — watch for overfit (train_loss drops while val rises)
3. `--max-len` (128–256) — keep small; VRAM is tight
4. `--batch-size` (1–2) — keep small; batch_size=4, len=256 OOMs on 6GB
5. optimizer / warmup-ratio / gradient accumulation

## Metric / success signal
- **Primary: validation_loss (lower is better).** The framework's in-run early
  stop reads per-epoch `validation_loss` (`direction: lower_better`).
- Watch for **overfitting**: if `train_loss` keeps dropping but `validation_loss`
  rises across epochs, that candidate is bad (DISCARD).
- The machine-judgment loop promotes a candidate only if its validation_loss
  beats the champion by more than the noise band while not overfitting.

## Training-script contract (REQUIRED by the framework — keep it intact)
- Print `validation_loss=<float>` EVERY epoch (monitor parses for early stop).
- Print a single `RESULT {<json>}` as the LAST stdout line:
  `RESULT {"validation_loss": ..., "train_loss": ..., "test_loss": ...}`
- Time the active training loop (`active_train_seconds`) for budget enforcement.
- **Run via `launch_experiment`** (the monitor tracks PID + log file), NOT
  `run_shell`. Example: `launch_experiment(command="/home/szf/anaconda3/bin/python train_ft.py --epochs 3 --lr 1e-4", log_file="logs/exp_001.log")`.
- Save the fine-tuned model under the workspace (e.g. `model_ft/`).

## What to do per round
1. Ensure `train_ft.py` satisfies the contract above; start from it as champion.
2. **Evolve ONE hyper-parameter** (lr/epochs/max-len/batch-size). Do not change
   the model id, dataset, or config schema.
3. **MUST launch a real GPU fine-tune via `launch_experiment`** — do NOT skip
   training or fake the result.
4. Let the monitor observe the run; report `validation_loss` (selection).
5. Machine judgment decides KEEP / DISCARD; then propose a NEW hyper-parameter
   combo for the next round — keep improving the champion, no repeats.

## Constraints
- Use GPU 0 (`CUDA_VISIBLE_DEVICES=0`). Budget: `active_train_seconds` <= 7500s;
  hard cap 9000s. Keep each run within budget.
- **Do NOT write to denylisted paths** (data/, .codebuddy/, contracts/, tests/,
  artifacts/, config.yaml, core/…). Only modify `train_ft.py` and workspace files.
- **Do NOT run destructive git commands** (reset/clean/checkout/revert/…).
- **Do NOT repeat the same hyper-parameter combo** (hypothesis de-dup is on).

## Current Status
Multi-round automatic fine-tuning search on Qwen2.5-0.5B under a fixed active-train
budget, driven by machine judgment (validation_loss for selection). The initial
champion is the baseline `train_ft.py`. Run as many rounds as budget/cycles allow,
promoting only machine-verified improvements (lower validation_loss).

## Success Criteria
- At least 2-3 distinct hyper-parameter variants run across rounds (no repeats).
- Each run launched via `launch_experiment` and monitored (PID captured).
- Each run stays within budget; no CUDA OOM; no fake/skipped training.
- Machine judgment promotes real improvements (validation_loss decrease above
  noise) and discards worse/overfit/crashed runs.
- Final champion shows lower validation_loss than the baseline, without overfit.
- No protected/denylisted file was modified (D0 boundary respected).
