"""MNIST GPU 训练脚本（示例 / 候选基线）。

演示如何在 G1 约束下书写训练脚本：固定验证集、定时训练、最后打印结构化
``RESULT {...}`` 供 monitor 解析。注意：本文件是**示例 / 候选**代码，不属于 G1
运行时代码（G1 allowlist 唯一文件是 examples/llm_finetune/train_ft.py）。
"""
import argparse
import time
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, random_split
from torchvision import datasets, transforms

device = 'cuda'


# ============ 模型定义 ============
# MNIST：输入 28x28。
# Conv1 (padding=1, 3x3)：28 -> 28，ReLU，MaxPool2x2：14x14
# Conv2 (padding=1, 3x3)：14 -> 14，ReLU，MaxPool2x2：7x7  -> 64*7*7
class CNN(nn.Module):
    def __init__(self):
        super(CNN, self).__init__()
        self.conv1 = nn.Sequential(
            nn.Conv2d(1, 32, 3, padding=1),
            nn.ReLU(),
            nn.MaxPool2d(2)
        )
        self.conv2 = nn.Sequential(
            nn.Conv2d(32, 64, 3, padding=1),
            nn.ReLU(),
            nn.MaxPool2d(2)
        )
        self.fc1 = nn.Linear(64 * 7 * 7, 128)
        self.fc2 = nn.Linear(128, 10)
        self.relu = nn.ReLU()

    def forward(self, x):
        x = self.conv1(x)   # 14x14
        x = self.conv2(x)   # 7x7
        x = x.view(x.size(0), -1)
        x = self.relu(self.fc1(x))
        x = self.fc2(x)
        return x


def set_seed(seed):
    # 固定随机种子以保证可复现
    import random
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--epochs', type=int, default=8)
    parser.add_argument('--batch_size', type=int, default=64)
    parser.add_argument('--seed', type=int, default=17,
                        help='随机种子；同时驱动验证集 holdout 切分的可复现性')
    parser.add_argument('--dry_run', action='store_true')
    args = parser.parse_args()

    n_epochs = args.epochs
    batch_size = args.batch_size
    set_seed(args.seed)

    # ============ 数据加载 ============
    transform = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize((0.1307,), (0.3081,))
    ])

    train_dataset = datasets.MNIST(
        root='/home/szf/env/AutoDL/examples/mnist_gpu/data',
        train=True,
        download=False,
        transform=transform
    )
    test_dataset = datasets.MNIST(
        root='/home/szf/env/AutoDL/examples/mnist_gpu/data',
        train=False,
        download=False,
        transform=transform
    )

    # ============ 验证集 holdout（仅用于迭代选择）============
    # 固定切分种子 20260815 => 可复现地分出训练集中的 5000 样本验证集。
    # 验证集用于逐轮选择；测试集保留给独立验收。
    SPLIT_SEED = 20260815
    g = torch.Generator().manual_seed(SPLIT_SEED)
    n_val = 5000
    train_sub, val_sub = random_split(
        train_dataset, [len(train_dataset) - n_val, n_val], generator=g
    )

    train_loader = DataLoader(train_sub, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_sub, batch_size=64, shuffle=False)
    test_loader = DataLoader(test_dataset, batch_size=64, shuffle=False)

    # ============ 模型 / 损失 / 优化器 ============
    model = CNN().to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), lr=0.001)

    batches_per_epoch = 2 if args.dry_run else len(train_loader)

    # ============ 评估辅助函数（验证集 holdout，选择用）============
    def evaluate(loader):
        model.eval()
        correct = 0
        total = 0
        running_loss = 0.0
        with torch.no_grad():
            for data, target in loader:
                data, target = data.to(device), target.to(device)
                output = model(data)
                loss = criterion(output, target)
                running_loss += loss.item() * target.size(0)
                _, pred = output.max(1)
                correct += pred.eq(target).sum().item()
                total += target.size(0)
        acc = correct / total
        avg_loss = running_loss / total
        return acc, avg_loss

    # ============ 训练（计时：active_train_seconds）============
    train_start = time.monotonic()
    val_accuracy = 0.0
    val_loss = 0.0
    for epoch in range(1, n_epochs + 1):
        model.train()
        running_loss = 0.0
        correct = 0
        total = 0

        for batch_idx, (data, target) in enumerate(train_loader):
            if batch_idx >= batches_per_epoch:
                break
            data, target = data.to(device), target.to(device)

            optimizer.zero_grad()
            output = model(data)
            loss = criterion(output, target)
            loss.backward()
            optimizer.step()

            running_loss += loss.item()
            _, pred = output.max(1)
            total += target.size(0)
            correct += pred.eq(target).sum().item()

        avg_loss = running_loss / batches_per_epoch
        accuracy = correct / total
        print('Epoch {}/{}: loss={:.4f} acc={:.4f}'.format(epoch, n_epochs, avg_loss, accuracy))
        # 逐 epoch 验证指标（早停契约用）：monitor 解析这个序列来检测平台期，并在
        # 模型收敛时提前终止运行，节省 GPU。
        val_accuracy, val_loss = evaluate(val_loader)[0], evaluate(val_loader)[1]
        print('validation_accuracy={:.4f}'.format(val_accuracy))
    active_train_seconds = time.monotonic() - train_start

    # ============ 评估：测试集（仅独立验收用）============
    test_accuracy, test_loss = evaluate(test_loader)
    print('test_accuracy={:.4f}'.format(test_accuracy))
    print('test_loss={:.4f}'.format(test_loss))

    # ============ 预算 / 指标上报 ============
    print('active_train_seconds={:.2f}'.format(active_train_seconds))
    print('seed={}'.format(args.seed))
    print('epochs={}'.format(n_epochs))
    print('batch_size={}'.format(batch_size))

    # ============ 结构化指标契约（monitor 解析）============
    # 作为最后一行 stdout 打印的单行 JSON；validation_* 驱动逐轮选择，
    # test_* 保留给独立验收。
    import json
    print('RESULT ' + json.dumps({
        'validation_accuracy': round(val_accuracy, 4),
        'validation_loss': round(val_loss, 4),
        'test_accuracy': round(test_accuracy, 4),
        'test_loss': round(test_loss, 4),
    }))

    # ============ 保存模型 ============
    torch.save(model.state_dict(), './model.pt')


if __name__ == '__main__':
    main()
