#!/usr/bin/env python3
"""Demo training script: simulates a short training run that prints metrics.

Reuses the light_demo objective f(lr) = (lr - 0.25)^2 + 0.01. Sweeps a small
grid of learning rates and prints a `metric=...` line periodically so the
second-by-second watcher has something observable. Pure stdlib, CPU-only.
"""
import argparse
import math
import sys
import time


def objective(lr: float) -> float:
    return (lr - 0.25) ** 2 + 0.01


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lr", type=float, default=0.5)
    parser.add_argument("--steps", type=int, default=30)
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()

    # "training" loop: each step nudges lr toward the optimum and prints a metric.
    lr = args.lr
    for step in range(1, args.steps + 1):
        # Simple gradient-like update toward the true minimum (0.25).
        lr = lr - 0.05 * 2.0 * (lr - 0.25)
        metric = objective(lr)
        print(f"step {step}/{args.steps} | lr={lr:.6f} | metric={metric:.6f}", flush=True)
        time.sleep(args.delay)

    final = objective(lr)
    print(f"metric={final:.6f}", flush=True)
    print("Training complete.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
