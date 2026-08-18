"""环境检查脚本：打印 PyTorch / torchvision 版本与 CUDA 可用性。"""
import torch, torchvision
print("torch", torch.__version__)
print("torchvision", torchvision.__version__)
print("cuda_available", torch.cuda.is_available())
print("gpu_count", torch.cuda.device_count())
