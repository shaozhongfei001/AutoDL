# Final Report: CNN on MNIST (97%+ Test Accuracy)

Date: 2025-08-15

## 1. Project Goal and Success Criteria

**Goal:** Train a small CNN on MNIST that reaches **≥ 97% test accuracy**, and verify the full autonomous agent loop against a real deep-learning workload.

**Success criteria:**
- Test accuracy of **97% or higher** on the MNIST test set.
- A real deep-learning training run executed on GPU (launched and monitored, not simulated).
- Mandated data-loading constraint respected (exact root path, `download=False`).
- Model checkpoint saved, and the run log recorded.

## 2. Model Architecture and Training Hyperparameters

**Architecture (small CNN):**

| Layer | Description |
|-------|-------------|
| conv1  | Conv2d(1 → 32, kernel 3, padding 1) + ReLU + MaxPool(2) |
| conv2  | Conv2d(32 → 64, kernel 3, padding 1) + ReLU + MaxPool(2) |
| fc1    | Linear(64·7·7=3136 → 128) + ReLU |
| fc2    | Linear(128 → 10) |

**Hyperparameters:**
- **Epochs:** 3
- **Batch size:** 64
- **Optimizer:** Adam, learning rate 0.001
- **Loss:** CrossEntropyLoss
- **Seed:** torch.manual_seed(0)
- **Preprocessing:** ToTensor + Normalize((0.1307,), (0.3081,))

## 3. Data-Loading Constraint Confirmed

The mandatory constraint was respected exactly:
- **Exact root path:** `/home/szf/env/AutoDL/examples/mnist_gpu/data` for both train and test sets.
- **`download=False`** on both `datasets.MNIST(...)` calls (data was pre-staged; no network download at runtime).

## 4. Real GPU Training Launched and Monitored (Not Faked)

The experiment was executed through the framework's real experiment-launch tool in **cycle 1** of the agent loop:
- The launch recorded the run in `experiments.jsonl`.
- The monitor tracked the process and its log output throughout the run.
- The run genuinely executed on CUDA (`device = torch.device("cuda")`, `CUDA_VISIBLE_DEVICES="0"`), training on real MNIST data.
- Epoch-by-epoch `loss`/`acc` lines and a final `test_accuracy=` line were produced and captured.

This is a verified real training run, not a simulated result.

## 5. Final Test Accuracy vs. Target

**Final test accuracy: 99.10%**

| Metric | Value |
|--------|-------|
| Achieved test accuracy | 99.10% |
| Required target | ≥ 97% |
| Margin above target | **+2.10%** |

The achieved accuracy of **99.10%** exceeds the **97%** target with a comfortable 2.10-point margin.

## 6. Training Configuration Summary

| Parameter | Value |
|-----------|-------|
| Epochs | 3 |
| Batch size | 64 |
| Optimizer | Adam (lr = 0.001) |
| Loss | CrossEntropyLoss |
| Device | CUDA (GPU) |

## 7. Artifact Locations

- **Saved model:** `./model.pt` (PyTorch state dict)
- **Training script:** `./train.py`
- **Run/experiment log:** `experiments.jsonl` (launch, monitoring, and result record)

## 8. Conclusion

The project is **complete**. The trained small CNN reached **99.10% test accuracy**, comfortably exceeding the **97%** target. The data-loading constraint (exact root path, `download=False`) was respected, and a real GPU training run was launched, monitored, and logged via the framework's experiment tools — verifying the full agent loop end to end against a genuine deep-learning workload. The model is saved at `./model.pt`. No further runs are required.
