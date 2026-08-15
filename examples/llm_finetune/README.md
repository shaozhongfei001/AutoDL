# LLM Fine-tuning pilot — Qwen2.5-0.5B on alpaca-cleaned

Smallest practical LLM fine-tune for a **6GB GPU** (RTX 3060 Laptop): full
fine-tune of **Qwen2.5-0.5B** (~500M params) on a 500-example subset of
`yahma/alpaca-cleaned`.

## Files
- `config.yaml` — AutoDL loop config (budget, in-run early stop on
  `validation_loss`, loop-level early stop)
- `PROJECT_BRIEF.md` — research goal + search space for the code agent
- `train_ft.py` — the fine-tuning script (AutoDL framework contract compliant)
- `requirements-ft.txt` — runtime deps (already present in anaconda env)

## Run (AutoDL unattended loop)
```bash
# 1. from repo root, load the API key and use the torch interpreter:
eval "$(grep '^export DSEEK_2026_SZF_KEY=' ~/.bashrc)"
export PATH=/home/szf/anaconda3/bin:$PATH
export PYTHONPATH=/home/szf/env/AutoDL

# 2. launch the loop:
nohup .venv/bin/python -m core.loop --project examples/llm_finetune --gpu 0 \
  > examples/llm_finetune/run.log 2>&1 &
```

## Manual smoke test (one round)
```bash
cd examples/llm_finetune
/home/szf/anaconda3/bin/python train_ft.py --epochs 1 --max-examples 20
```

## Key details
- Model + dataset download via `HF_ENDPOINT=https://hf-mirror.com` (huggingface.co
  is unreachable on this network).
- Primary metric **validation_loss** (lower = better); monitor early-stops once
  it plateaus (`direction: lower_better`).
- Every epoch prints `validation_loss=<float>`; the last stdout line is a
  `RESULT {json}` snapshot — both parsed by the framework.
- Active training is timed (`active_train_seconds`) for the budget enforcement.
