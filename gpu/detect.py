"""
AutoResearcher GPU 检测与管理

提供一组基础 GPU 工具：检测可用 GPU、查询 GPU 状态、判断某张 GPU 是否空闲、
为实验挑选可用的 GPU。
"""

import subprocess
import json
import logging
from typing import Optional

logger = logging.getLogger("autoresearcher.gpu")


def detect_gpus() -> list[int]:
    """通过 ``nvidia-smi -L`` 检测所有可用 GPU。

    返回：
        GPU 索引列表，例如 [0, 1, 2, 3]；检测失败则返回空列表。
    """
    try:
        result = subprocess.run(
            ["nvidia-smi", "-L"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
            return list(range(len(lines)))
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    logger.warning("nvidia-smi 未找到或执行失败，未检测到 GPU。")
    return []


def gpu_status() -> list[dict]:
    """获取 GPU 的详细信息。

    返回：
        字典列表，每个含 gpu_id、name、memory_used、memory_total、
        utilization、temperature。
    """
    try:
        result = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=index,name,memory.used,memory.total,utilization.gpu,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return []

        gpus = []
        for line in result.stdout.strip().split("\n"):
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 6:
                gpus.append({
                    "gpu_id": int(parts[0]),
                    "name": parts[1],
                    "memory_used_mb": int(parts[2]),
                    "memory_total_mb": int(parts[3]),
                    "utilization_pct": int(parts[4]),
                    "temperature_c": int(parts[5]),
                })

        return gpus

    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []


def is_gpu_available(gpu_id: int, memory_threshold_mb: int = 1000) -> bool:
    """判断某张 GPU 是否空闲（显存占用低于阈值）。

    参数：
        gpu_id: 要检查的 GPU 索引
        memory_threshold_mb: 已用显存低于此值才视为空闲

    返回：
        该 GPU 看起来空闲则为 True
    """
    statuses = gpu_status()
    for gpu in statuses:
        if gpu["gpu_id"] == gpu_id:
            return gpu["memory_used_mb"] < memory_threshold_mb
    return False


def get_usable_gpus(reserve_last: bool = True) -> list[int]:
    """获取可用于实验的 GPU 列表。

    参数：
        reserve_last: 若为 True，则排除最后一张 GPU（用于保活），见 gpu/keeper.py

    返回：
        可用于实验的 GPU 索引列表
    """
    gpus = detect_gpus()
    if not gpus:
        return []
    if reserve_last and len(gpus) > 1:
        return gpus[:-1]
    return gpus


def get_free_gpus(reserve_last: bool = True, memory_threshold_mb: int = 1000) -> list[int]:
    """获取既可用、当前又空闲的 GPU 列表。

    参数：
        reserve_last: 排除最后一张 GPU
        memory_threshold_mb: “空闲” 的显存阈值

    返回：
        空闲 GPU 索引列表
    """
    usable = get_usable_gpus(reserve_last=reserve_last)
    return [g for g in usable if is_gpu_available(g, memory_threshold_mb)]


def print_gpu_summary():
    """打印一份人类可读的 GPU 概览。"""
    statuses = gpu_status()
    if not statuses:
        print("未检测到 GPU。")
        return

    print(f"{'GPU':>4} {'Name':<25} {'Memory':>15} {'Util':>6} {'Temp':>6}")
    print("-" * 60)
    for gpu in statuses:
        mem = f"{gpu['memory_used_mb']}MB/{gpu['memory_total_mb']}MB"
        print(
            f"{gpu['gpu_id']:>4} {gpu['name']:<25} {mem:>15} "
            f"{gpu['utilization_pct']:>5}% {gpu['temperature_c']:>4}°C"
        )

    usable = get_usable_gpus()
    free = get_free_gpus()
    print(f"\n可用: {usable} | 空闲: {free}")


if __name__ == "__main__":
    print_gpu_summary()
