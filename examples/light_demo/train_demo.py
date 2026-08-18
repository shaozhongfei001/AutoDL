#!/usr/bin/env python3
"""演示训练脚本：模拟一段短时训练并打印指标。

复用 light_demo 的目标函数 f(lr) = (lr - 0.25)^2 + 0.01。对一组较小的学习率做
网格扫描，并周期性地打印 ``metric=...`` 行，让逐秒观察的 watcher 有可见的输出。
纯标准库、仅 CPU。
"""
import argparse
import math
import sys
import time


def objective(lr: float) -> float:
    # 目标函数：以 0.25 为最小值点
    return (lr - 0.25) ** 2 + 0.01


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lr", type=float, default=0.5)
    parser.add_argument("--steps", type=int, default=30)
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()

    # “训练”循环：每一步把 lr 朝真实最优点（0.25）推动，并打印一条指标。
    lr = args.lr
    for step in range(1, args.steps + 1):
        # 类似梯度的更新，朝真实最小值（0.25）靠近
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
