#!/usr/bin/env python
"""计算稳定的数据集指纹 + 确定性 split（只读脚本，不修改任何数据）。"""
import hashlib
import json
import os
import sys
from collections import Counter

import pyarrow.ipc as ipc

# 数据集 Arrow 文件的本地路径（Alpaca-Cleaned）。
ARROW_PATH = ("/home/szf/.cache/huggingface/datasets/"
              "yahma___alpaca-cleaned/default/0.0.0/"
              "12567cabf869d7c92e573c7c783905fc160e9639/alpaca-cleaned-train.arrow")

# split 策略标识与划分比例（test 与 validation 各占 10%，其余为 train）。
SPLIT_POLICY = "SPLIT-MVD-V1"
TEST_PCT = 10
VAL_PCT = 10


def bucket_of(i):
    """用行号生成一个 0..99 的确定性分桶，作为 split 的依据。"""
    h = hashlib.sha256(f"row:{i}:split:v1".encode("utf-8")).hexdigest()
    return int(h[:8], 16) % 100


def split_name(i):
    """根据分桶值把行归入 final-test / validation / train 三个集合。"""
    b = bucket_of(i)
    if b < TEST_PCT:
        return "final-test"
    if b < TEST_PCT + VAL_PCT:
        return "validation"
    return "train"


def main():
    # 数据集文件不存在时输出结构化错误并退出。
    if not os.path.exists(ARROW_PATH):
        print(json.dumps({"error": f"not found: {ARROW_PATH}"}))
        sys.exit(1)

    table = ipc.open_stream(ARROW_PATH).read_all()
    cols = table.column_names
    n = table.num_rows

    instruction = table.column("instruction").to_pylist()
    output = table.column("output").to_pylist()
    inp = table.column("input").to_pylist() if "input" in cols else [""] * n

    row_hashes = []
    split_of = []
    for i in range(n):
        # 由 instruction|input|output 拼接出规范化内容并计算行级哈希。
        src = f"{instruction[i]}|{inp[i]}|{output[i]}"
        norm = " ".join(src.split())
        row_hashes.append(hashlib.sha256(norm.encode("utf-8")).hexdigest())
        split_of.append(split_name(i))

    # 全局内容摘要：对所有行哈希排序后取整体 SHA-256。
    global_digest = hashlib.sha256(
        "".join(sorted(row_hashes)).encode("utf-8")).hexdigest()

    splits = Counter(split_of)

    # 各 split 内部的「精确重复内容组」数量（判定数据去重前的暴露度）。
    dup_by_split = {}
    for name in ("final-test", "validation", "train"):
        hashes_in_split = [h for h, s in zip(row_hashes, split_of) if s == name]
        counts = Counter(hashes_in_split)
        dup_by_split[name] = sum(1 for c in counts.values() if c > 1)

    result = {
        "source": "yahma/alpaca-cleaned",
        "revision": "12567cabf869d7c92e573c7c783905fc160e9639",
        "arrow_sha256": "e0b8d2a4fd14442983201e182c15ab2c82175064128920839408ea57dc04015e",
        "total_rows": n,
        "columns": cols,
        "split_policy": SPLIT_POLICY,
        "split_spec": {
            "final-test_pct": TEST_PCT,
            "validation_pct": VAL_PCT,
            "train_pct": 80,
            "method": "deterministic bucket via sha256('row:{i}:split:v1')%100",
        },
        "split_counts": dict(splits),
        "row_content_digest": global_digest,
        "exact_dup_groups_total": sum(1 for c in Counter(row_hashes).values() if c > 1),
        "exact_dup_groups_by_split": dup_by_split,
        "policy_version": "SPLIT-MVD-V1-20260818",
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()