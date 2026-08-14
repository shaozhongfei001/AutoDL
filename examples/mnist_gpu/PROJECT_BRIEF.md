# MNIST GPU Experiment

Train a small CNN on MNIST to a target test accuracy, running REAL GPU
training with PyTorch. This verifies the full agent loop against an actual
deep-learning workload and exercises the default experiment monitor.

## Goal
Train a small convolutional network on MNIST to reach **97%+ test accuracy**.

## Codebase
- Training script: `train.py` (to be created by the agent).
- Use PyTorch + torchvision (both installed in the project venv). Use GPU 0.
- **MNIST data is ALREADY present locally — DO NOT download it.**

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

## Training script requirements
`train.py` MUST:
- take `--epochs` (default 3) and `--batch_size` (default 64),
- use `device = 'cuda'` (CUDA is available),
- print `Epoch <e>/<n>: loss=... acc=...` each epoch,
- print a final `test_accuracy=<value>` line to stdout,
- save the model to `./model.pt`.

## What to Try (IMPORTANT)
1. Create `train.py` per the spec above (simple 2-conv CNN, Adam or SGD,
   cross-entropy loss).
2. **MUST launch a real GPU training run** (`python train.py --epochs 3`) via the
   framework's experiment-launch tool so the monitor tracks its PID and log file.
   Do NOT skip training or fake the result.
3. Let the monitor observe the run, then report the final test accuracy.

## Constraints
- Use GPU 0 only (`CUDA_VISIBLE_DEVICES=0`).
- Max 3 epochs per run.
- Keep the model small (fits in 6GB easily).
- Every run must be a real launched subprocess that prints `test_accuracy=...`.

## Current Status
No experiments run yet. Starting from scratch.

## Success Criteria
- A run reaches test accuracy >= 97%.
- Training is actually launched on GPU and monitored (not skipped).
