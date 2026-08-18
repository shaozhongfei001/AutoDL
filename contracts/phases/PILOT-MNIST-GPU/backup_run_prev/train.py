"""MNIST GPU 训练脚本（PILOT 备份，legacy 版本）。

两卷积层 CNN，固定 5000 样本验证集（切分种子 20260815），训练后打印
``validation_accuracy`` / ``test_accuracy`` / ``active_train_seconds`` 供监控解析。
历史存档代码。
"""
import argparse
import os
import time

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, Subset, random_split

from torchvision import datasets, transforms


os.environ["CUDA_VISIBLE_DEVICES"] = "0"


class CNN(nn.Module):
    """两卷积 + 两全连接的 CNN。"""
    def __init__(self):
        super(CNN, self).__init__()
        self.conv1 = nn.Conv2d(1, 32, 3, padding=1)
        self.conv2 = nn.Conv2d(32, 64, 3, padding=1)
        self.fc1 = nn.Linear(64 * 7 * 7, 128)
        self.fc2 = nn.Linear(128, 10)

    def forward(self, x):
        x = F.relu(self.conv1(x))
        x = F.max_pool2d(x, 2)
        x = F.relu(self.conv2(x))
        x = F.max_pool2d(x, 2)
        x = x.view(x.size(0), -1)
        x = F.relu(self.fc1(x))
        x = self.fc2(x)
        return x


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch_size", type=int, default=64)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    # 固定 5000 样本验证集与切分种子
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
        root="/home/szf/env/AutoDL/examples/mnist_gpu/data", train=True,
        download=False, transform=transform)
    test_dataset = datasets.MNIST(
        root="/home/szf/env/AutoDL/examples/mnist_gpu/data", train=False,
        download=False, transform=transform)

    # 从训练集切出固定 5000 样本验证集（seed 20260815）
    gen = torch.Generator().manual_seed(VALIDATION_SEED)
    train_subset, val_subset = random_split(
        train_dataset, [len(train_dataset) - VALIDATION_SIZE, VALIDATION_SIZE],
        generator=gen)

    train_loader = DataLoader(train_subset, batch_size=args.batch_size,
                              shuffle=True, num_workers=0)
    val_loader = DataLoader(val_subset, batch_size=args.batch_size,
                            shuffle=False, num_workers=0)
    test_loader = DataLoader(test_dataset, batch_size=args.batch_size,
                             shuffle=False, num_workers=0)

    model = CNN().to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)

    train_start = time.time()

    for epoch in range(1, args.epochs + 1):
        model.train()
        running_loss = 0.0
        correct = 0
        total = 0
        for images, labels in train_loader:
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
        avg_loss = running_loss / total
        train_acc = correct / total
        print("Epoch {}/{}: loss={:.4f} acc={:.4f}".format(
            epoch, args.epochs, avg_loss, train_acc))

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

    # 测试集精度
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

    print("active_train_seconds={:.2f}".format(train_seconds))

    torch.save(model.state_dict(), "./model.pt")


if __name__ == "__main__":
    main()
