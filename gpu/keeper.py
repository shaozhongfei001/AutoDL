"""
AutoResearcher GPU 保活脚本

通过维持最低的 GPU 活跃度，防止云 GPU 实例被回收。许多云平台
（例如阿里云 PAI-DSW）会在 GPU 长时间空闲（通常 3 小时）后回收实例。

这是开源基础版：它在指定的 GPU 上常驻一个很小的张量，以触发平台认为
“有活跃使用” 的判定，从而避免实例被释放。
"""

import signal
import sys
import time
import logging

logger = logging.getLogger("autoresearcher.gpu.keeper")


class GPUKeeper:
    """面向云实例的最小 GPU 保活器。

    在目标 GPU 上分配一个小张量，并周期性地做一个微小运算来登记活跃度。
    """

    def __init__(self, gpu_id: int):
        self.gpu_id = gpu_id
        self._running = True
        self._tensor = None

        # 注册优雅关闭信号处理器
        signal.signal(signal.SIGTERM, self._shutdown)
        signal.signal(signal.SIGINT, self._shutdown)

    def start(self, interval: int = 300):
        """启动保活循环。

        参数：
            interval: 两次活跃心跳之间的间隔秒数（默认 5 分钟）
        """
        try:
            import torch
        except ImportError:
            logger.error("未安装 PyTorch，无法运行 GPU 保活。")
            return

        if not torch.cuda.is_available():
            logger.error("CUDA 不可用。")
            return

        device = torch.device(f"cuda:{self.gpu_id}")
        logger.info(f"GPU 保活器在 GPU {self.gpu_id} 上启动")

        # 分配一个极小张量（4KB）
        self._tensor = torch.zeros(1024, device=device, dtype=torch.float32)

        while self._running:
            # 最小活跃操作：原地加 1 再清零
            self._tensor.add_(1.0)
            self._tensor.zero_()
            time.sleep(interval)

        # 收尾清理
        del self._tensor
        torch.cuda.empty_cache()
        logger.info("GPU 保活器已停止。")

    def _shutdown(self, signum, frame):
        logger.info(f"收到信号 {signum}，正在关闭保活器。")
        self._running = False


def main():
    import argparse
    parser = argparse.ArgumentParser(description="GPU 保活守护进程")
    parser.add_argument("--gpu", type=int, required=True, help="要保活的 GPU ID")
    parser.add_argument("--interval", type=int, default=300, help="心跳间隔（秒）")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [GPU-Keeper] %(message)s")
    keeper = GPUKeeper(gpu_id=args.gpu)
    keeper.start(interval=args.interval)


if __name__ == "__main__":
    main()
