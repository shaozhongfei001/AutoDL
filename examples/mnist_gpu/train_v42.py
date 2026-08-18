"""MNIST GPU 训练脚本（v42 变体）。

一个稍深的 CNN，在固定 5000 样本验证集上做逐轮选择，并在独立的测试集上报告
最终精度。打印 ``active_train_seconds=...`` 与 ``validation_accuracy=...`` /
``test_accuracy=...`` 供 monitor 解析。纯标准训练，无 early-stop / 结构化 RESULT
输出（旧式日志格式）。
"""
import argparse
import os
import time

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, Subset, random_split

from torchvision import datasets, transforms


# 固定使用 GPU 0
os.environ["CUDA_VISIBLE_DEVICES"] = "0"


class Net(nn.Module):
    """一个三卷积 + 两全连接的 CNN。"""
    def __init__(self, hidden_dim=128):
        super(Net, self).__init__()
        self.conv1 = nn.Conv2d(1, hidden_dim, kernel_size=5, padding=2)
        self.bn1 = nn.BatchNorm2d(hidden_dim)
        self.conv2 = nn.Conv2d(hidden_dim, hidden_dim, kernel_size=5, padding=2)
        self.conv3 = nn.Conv2d(hidden_dim, hidden_dim, kernel_size=5, padding=2)
        self.bn3 = nn.BatchNorm2d(hidden_dim)
        self.drop1 = nn.Dropout2d(p=0.25)
        self.drop_fc = nn.Dropout(p=0.4)
        self.pool = nn.MaxPool2d(2)
        self.fc1 = nn.Linear(hidden_dim * 3 * 3, 64)
        self.fc2 = nn.Linear(64, 10)
        self.relu = nn.ReLU()
        self.silu = nn.SiLU()

    def forward(self, x):
        x = self.pool(self.relu(self.bn1(self.conv1(x))))
        x = self.drop1(x)
        x = self.pool(self.silu(self.conv2(x)))
        x = self.pool(self.relu(self.bn3(self.conv3(x))))
        x = x.view(x.size(0), -1)
        x = self.drop_fc(self.relu(self.fc1(x)))
        x = self.fc2(x)
        return x


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch_size", type=int, default=64)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--dry_run", action="store_true")
    args = parser.parse_args()

    # 从训练集中切出固定的 5000 样本验证集（种子 20260815）
    VALIDATION_SIZE = 5000
    VALIDATION_SEED = 20260815

    torch.manual_seed(args.seed)

    device = torch.device("cuda")
    torch.cuda.set_device(0)

    transform = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize((0.1307,), (0.3081,)),
    ])
    train_dataset = datasets.MNIST(
        # 复用本地已下载的数据，避免重复下载
        root="/home/szf/env/AutoDL/examples/mnist_gpu/data", train=True,
        download=False, transform=transform)
    test_dataset = datasets.MNIST(
        root="/home/szf/env/AutoDL/examples/mnist_gpu/data", train=False,
        download=False, transform=transform)

    # 用固定种子的 Generator 从训练集分出 5000 样本验证集
    gen = torch.Generator().manual_seed(VALIDATION_SEED)
    train_subset, val_subset = random_split(
        train_dataset, [len(train_dataset) - VALIDATION_SIZE, VALIDATION_SIZE],
        generator=gen)

    # dry_run 模式下只跑极少步数以便快速验证流程
    max_epochs = 1 if args.dry_run else args.epochs
    max_batches = 2 if args.dry_run else None

    train_loader = DataLoader(train_subset, batch_size=args.batch_size,
                              shuffle=True, num_workers=0)
    val_loader = DataLoader(val_subset, batch_size=args.batch_size,
                            shuffle=False, num_workers=0)
    test_loader = DataLoader(test_dataset, batch_size=args.batch_size,
                             shuffle=False, num_workers=0)

    model = Net().to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)

    train_start = time.time()

    # 训练循环（每 epoch 统计平均 loss 与训练精度）
    for epoch in range(1, max_epochs + 1):
        model.train()
        running_loss = 0.0
        correct = 0
        total = 0
        for b_i, (images, labels) in enumerate(train_loader):
            if max_batches is not None and b_i >= max_batches:
                break
            images = images.to(device)
            labels = labels.to(device)
            optimizer.zero_grad()
            outputs = model(images)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()
            running_loss += loss.item() * images.size(0)
            _, predicted = torch.max(outputs, 1)
            total += labels.size(0)
            correct += (predicted == labels).sum().item()
        avg_loss = running_loss / max(total, 1)
        train_acc = correct / max(total, 1)
        print("Epoch {}/{}: loss={:.4f} acc={:.4f}".format(
            epoch, max_epochs, avg_loss, train_acc))

    train_seconds = time.time() - train_start

    # 验证集精度
    model.eval()
    correct = 0
    total = 0
    with torch.no_grad():
        for images, labels in val_loader:
            images = images.to(device)
            labels = labels.to(device)
            outputs = model(images)
            _, predicted = torch.max(outputs, 1)
            total += labels.size(0)
            correct += (predicted == labels).sum().item()
    val_acc = correct / total
    print("validation_accuracy={:.4f}".format(val_acc))

    # 测试集精度（独立验收用）
    correct = 0
    total = 0
    with torch.no_grad():
        for images, labels in test_loader:
            images = images.to(device)
            labels = labels.to(device)
            outputs = model(images)
            _, predicted = torch.max(outputs, 1)
            total += labels.size(0)
            correct += (predicted == labels).sum().item()
    test_acc = correct / total
    print("test_accuracy={:.4f}".format(test_acc))

    # 打印训练活跃秒数（供预算契约统计）
    print("active_train_seconds={:.2f}".format(train_seconds))

    torch.save(model.state_dict(), "./model.pt")


if __name__ == "__main__":
    main()
