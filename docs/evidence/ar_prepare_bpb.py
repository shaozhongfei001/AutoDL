# Evidence: autoresearch BPB 归一化指标
# Source: /home/szf/env/autoresearch/prepare.py:340-365
# Supports: 建议A - 指标归一化可比性（当前项目较弱）

# Evaluation (DO NOT CHANGE — this is the fixed metric)
@torch.no_grad()
def evaluate_bpb(model, tokenizer, batch_size):
    """
    Bits per byte (BPB): vocab size-independent evaluation metric.
    Sums per-token cross-entropy (in nats), sums target byte lengths,
    then converts nats/byte to bits/byte. Special tokens (byte length 0)
    are excluded from both sums.
    Uses fixed MAX_SEQ_LEN so results are comparable across configs.
    """
    token_bytes = get_token_bytes(device="cuda")
    val_loader = make_dataloader(tokenizer, batch_size, MAX_SEQ_LEN, "val")
    steps = EVAL_TOKENS // (batch_size * MAX_SEQ_LEN)
    total_nats = 0.0
    total_bytes = 0
    for _ in range(steps):
        x, y, _ = next(val_loader)
        loss_flat = model(x, y, reduction='none').view(-1)
        y_flat = y.view(-1)
        nbytes = token_bytes[y_flat]
        mask = nbytes > 0
        total_nats += (loss_flat * mask).sum().item()
        total_bytes += nbytes.sum().item()
    return total_nats / (math.log(2) * total_bytes)

# 结论：BPB 按 token 字节长度归一化，与 vocab size 无关，
# 使不同 vocab 大小、不同架构的模型可公平比较（"可搜索"的前提）。
