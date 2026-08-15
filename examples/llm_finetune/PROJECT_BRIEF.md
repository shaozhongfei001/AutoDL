# LLM Fine-tuning Pilot — Qwen2.5-0.5B on alpaca-cleaned

## Goal
Fine-tune the smallest practical LLM — **Qwen2.5-0.5B** (~500M params) — on an
instruction-following subset of **alpaca-cleaned** to teach it to follow
instructions. This is a multi-round, GPU-bound, unattended search over
fine-tuning hyper-parameters.

## Why this model (smallest on our 6GB GPU)
- RTX 3060 Laptop with **6GB VRAM**. Qwen2.5-0.5B full fine-tune fits in
  ~2.5-3GB VRAM, leaving headroom.
- transformers 4.41.2 ships native `Qwen2ForCausalLM` support (no upgrade needed).
- ~500M params is large enough to be a real LLM fine-tune yet small enough to
  iterate on a laptop GPU.

## Environment prerequisites
- **Model download**: huggingface.co is unreachable from this network; the
  training script MUST set `HF_ENDPOINT=https://hf-mirror.com` (verified
  reachable) before calling `AutoModelForCausalLM.from_pretrained`.
- **Dataset**: `yahma/alpaca-cleaned` (52k instruction/response pairs) is
  reachable via the same mirror. The script sub-samples a fixed 500 examples
  for a tight budget (fingerprint `alpaca-cleaned-subset-500`).
- **Runtime**: use `/home/szf/anaconda3/bin/python` (has torch 2.3 + transformers).
  Note: plain `python` in launch_experiment resolves to a torch-less interpreter;
  pass the absolute anaconda python path.

## What the code agent varies per round (search space)
1. `--lr` learning rate (e.g. 1e-4 … 1e-5)
2. `--epochs` (2–4)
3. `--max_len` (256–512)
4. `--batch_size` (4–8)
5. optimizer / warmup ratio (adamw_torch, warmup 0–10%)
6. (optional) loss masking vs causal-lm default

## Metric / success signal
- **Primary: validation_loss** (lower is better). The monitor early-stops a run
  once val-loss plateaus (`direction: lower_better`).
- Secondary: train_loss trend (overfit check).
- The machine-judgment loop (M2) promotes a candidate only if it beats the
  champion val-loss by more than `min_effect_size` (0.05) while not overfitting.

## Training-script contract (REQUIRED by the framework)
- Print `validation_loss=<float>` EVERY epoch (the monitor parses this for the
  in-run early stop).
- Print a single `RESULT {<json>}` as the LAST stdout line:
  `RESULT {"validation_loss": ..., "train_loss": ..., "test_loss": ...}`
- Time your active training loop; the monitor enforces the active-seconds budget.
- Save the fine-tuned adapter/model so the round is comparable.

## Convergence policy
- The loop auto-converges (no manual killing) when 3 consecutive candidates are
  DISCARDed within the noise band, or when the leader launches no experiment for
  3 rounds.
