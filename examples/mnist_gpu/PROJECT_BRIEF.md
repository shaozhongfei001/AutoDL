# MNIST GPU — SDD Pilot Study (STUDY-001)

Train a small CNN on MNIST under a **fixed active-train budget** with
**validation used for selection and test reserved for independent acceptance**.
This pilot validates the Experiment Validity Contract (ADR-001) + Protected
Write Boundary (ADR-002/D0) in a real GPU workload.

## Goal
Demonstrate a **fair, auditable candidate experiment** on MNIST that reaches
**>= 97% test accuracy** under the configured budget, using:
- `validation_accuracy` for per-round selection (maximize).
- `test_accuracy` ONLY for final independent acceptance (never fed back).

## Codebase
- Training script: `train.py` (allowlisted, under the protected write boundary).
- Use PyTorch + torchvision (both installed in the project venv). Use GPU 0.
- **MNIST data is ALREADY present locally — DO NOT download or modify it.**

### MANDATORY data-loading constraint (do not violate)
Use this exact root path for both train and test datasets, and set
`download=False`:

```python
from torchvision import datasets, transforms
transform = transforms.Compose([
    transforms.ToTensor(),
    transforms.Normalize((0.1307,), (0.3081,)),
])
train_dataset = datasets.MNIST(
    root="/home/szf/env/AutoDL/examples/mnist_gpu/data",
    train=True,
    download=False,          # data already present, never download
    transform=transform,
)
test_dataset = datasets.MNIST(
    root="/home/szf/env/AutoDL/examples/mnist_gpu/data",
    train=False,
    download=False,
    transform=transform,
)
```

IMPORTANT:
- `root` MUST be `.../mnist_gpu/data` (torchvision appends `MNIST/raw` itself).
- NEVER set `download=True`. NEVER re-download or modify the dataset.
- Do NOT point root at `data/MNIST` or `data/MNIST/raw`.

## Training script requirements (SDD contract compliant)
`train.py` MUST:
- take `--epochs` (default 3), `--batch_size` (default 64) and `--seed`,
- use `device = 'cuda'`,
- **split a 5000-sample validation holdout from the train set with a FIXED
  split seed (20260815)**; validation is for selection only,
- print `Epoch <e>/<n>: loss=... acc=...` each epoch,
- print `validation_accuracy=<value>` and `test_accuracy=<value>` lines,
- print `active_train_seconds=<seconds>` (monotonic training wall-clock),
- save the model to `./model.pt`.

## What to Try (IMPORTANT)
1. Ensure `train.py` satisfies the contract above. If the allowlisted
   `train.py` already does, reuse it.
2. **MUST launch a real GPU training run via the framework's
   `launch_experiment` tool** so the monitor tracks its PID and log file.
   Do NOT skip training or fake the result. Do NOT use `run_shell` for `cd && python`
   (it is blocked; `launch_experiment` runs in the workspace cwd).
3. Let the monitor observe the run; report `validation_accuracy` (selection)
   and `test_accuracy` (acceptance).

## Constraints
- Use GPU 0 only (`CUDA_VISIBLE_DEVICES=0`).
- Budget: `active_train_seconds` <= 300s; hard cap 420s. Keep runs within budget.
- Keep the model small (fits in 6GB easily).
- **Do NOT write to denylisted paths** (data/, .codebuddy/, contracts/, tests/,
  artifacts/, config.yaml, core/…). You may only modify allowlisted files
  (train.py, workspace/).
- **Do NOT run destructive git commands** (reset/clean/checkout/revert/…).

## Current Status
Fresh pilot start for STUDY-001 (SDD governance). No candidate experiment has
run under the new experiment-validity contract yet. The goal is to run the
first budget-constrained candidate and record its validation/test metrics.

## Success Criteria
- A candidate run is launched via `launch_experiment` and monitored (PID captured).
- Run stays within the 300s active-train budget.
- `validation_accuracy` reported for selection and `test_accuracy >= 97%` for
  acceptance.
- No protected/denylisted file was modified (D0 boundary respected).
