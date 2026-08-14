import argparse
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader
from torchvision import datasets, transforms

device = 'cuda'


# ============ Model Definition ============
# MNIST: 28x28 input.
# Conv1 (padding=1, 3x3): 28 -> 28, ReLU, MaxPool2x2: 14x14
# Conv2 (padding=1, 3x3): 14 -> 14, ReLU, MaxPool2x2: 7x7  -> 64*7*7
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--epochs', type=int, default=3)
    parser.add_argument('--batch_size', type=int, default=64)
    parser.add_argument('--dry_run', action='store_true')
    args = parser.parse_args()

    n_epochs = args.epochs
    batch_size = args.batch_size

    # ============ Data Loading ============
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

    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
    test_loader = DataLoader(test_dataset, batch_size=64)

    # ============ Model / Loss / Optimizer ============
    model = CNN().to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), lr=0.001)

    batches_per_epoch = 2 if args.dry_run else len(train_loader)

    # ============ Training ============
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

    # ============ Evaluation ============
    model.eval()
    test_correct = 0
    test_total = 0
    with torch.no_grad():
        for data, target in test_loader:
            data, target = data.to(device), target.to(device)
            output = model(data)
            _, pred = output.max(1)
            test_correct += pred.eq(target).sum().item()
            test_total += target.size(0)

    test_accuracy = test_correct / test_total
    print('test_accuracy={:.4f}'.format(test_accuracy))

    # ============ Save model ============
    torch.save(model.state_dict(), './model.pt')


if __name__ == '__main__':
    main()
