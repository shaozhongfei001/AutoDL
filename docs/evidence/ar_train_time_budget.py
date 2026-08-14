# Evidence: autoresearch 固定时间预算机制
# Source: /home/szf/env/autoresearch/train.py:513-604
# Supports: 建议A - 固定时间预算归一化（P0 缺失项）

# 训练按"时长"而非 epoch 停止。所有调度基于 progress = total_training_time / TIME_BUDGET。
print(f"Time budget: {TIME_BUDGET}s")   # TIME_BUDGET = 300 (from prepare.py)

# Schedules (all based on progress = training_time / TIME_BUDGET)
def get_lr_multiplier(progress):
    if progress < WARMUP_RATIO:
        return progress / WARMUP_RATIO if WARMUP_RATIO > 0 else 1.0
    elif progress < 1.0 - WARMDOWN_RATIO:
        return 1.0
    else:
        cooldown = (1.0 - progress) / WARMDOWN_RATIO
        return cooldown * 1.0 + (1 - cooldown) * FINAL_LR_FRAC

# 训练主循环
while True:
    torch.cuda.synchronize()
    t0 = time.time()
    for micro_step in range(grad_accum_steps):
        with autocast_ctx:
            loss = model(x, y)
        train_loss = loss.detach()
        loss = loss / grad_accum_steps
        loss.backward()
        x, y, epoch = next(train_loader)

    # Progress and schedules (core: time-based normalization)
    progress = min(total_training_time / TIME_BUDGET, 1.0)
    lrm = get_lr_multiplier(progress)
    ...
    optimizer.step()
    model.zero_grad(set_to_none=True)
    ...
    if step > 10:
        total_training_time += dt
    ...
    # Time's up — stop after warmup steps, NOT after N epochs
    if step > 10 and total_training_time >= TIME_BUDGET:
        break

# 结论：无论 agent 如何改架构/优化器/超参，每个实验都在完全相同的
# TIME_BUDGET（5分钟）计算预算下完成，使 val_bpb 可公平比较。
