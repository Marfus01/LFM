import torch as th
import torch.distributed as dist


def dev():
    """
    Get the device to use for torch.distributed.
    """
    if th.cuda.is_available():
        return th.device("cuda")
    return th.device("cpu")


def get_generator(generator, num_samples=0, seed=0):
    if generator == "dummy":
        return DummyGenerator()
    elif generator == "determ":
        return DeterministicGenerator(num_samples, seed)
    elif generator == "determ-indiv":
        return DeterministicIndividualGenerator(num_samples, seed)
    else:
        raise NotImplementedError


class DummyGenerator:  #pytorch random number generator
    def randn(self, *args, **kwargs):
        return th.randn(*args, **kwargs)

    def randint(self, *args, **kwargs):
        return th.randint(*args, **kwargs)

    def randn_like(self, *args, **kwargs):
        return th.randn_like(*args, **kwargs)


class DeterministicGenerator:
    """
    RNG to deterministically sample num_samples samples that does not depend on batch_size or mpi_machines
    Uses a single rng and samples num_samples sized randomness and subsamples the current indices
    """

    def __init__(self, num_samples, seed=0):
        if dist.is_initialized():
            self.rank = dist.get_rank()
            self.world_size = dist.get_world_size()
        else:
            print("Warning: Distributed not initialised, using single rank")
            self.rank = 0
            self.world_size = 1
        self.num_samples = num_samples
        self.done_samples = 0
        self.seed = seed
        self.rng_cpu = th.Generator()
        if th.cuda.is_available():
            self.rng_cuda = th.Generator(dev())
        self.set_seed(seed)

    def get_global_size_and_indices(self, size):   #分布式 并行计算
        global_size = (self.num_samples, *size[1:]) #计算全局生成尺寸
        indices = th.arange(
            self.done_samples + self.rank, #起始
            self.done_samples + self.world_size * int(size[0]),  #结束
            self.world_size,#步长
        )
        indices = th.clamp(indices, 0, self.num_samples - 1)
        assert len(indices) == size[0], f"rank={self.rank}, ws={self.world_size}, l={len(indices)}, bs={size[0]}"
        return global_size, indices

    def get_generator(self, device):
        return self.rng_cpu if th.device(device).type == "cpu" else self.rng_cuda

    def randn(self, *size, dtype=th.float, device="cpu"):  #正态分布
        global_size, indices = self.get_global_size_and_indices(size)
        generator = self.get_generator(device)
        return th.randn(*global_size, generator=generator, dtype=dtype, device=device)[indices]

    def randint(self, low, high, size, dtype=th.long, device="cpu"):
        global_size, indices = self.get_global_size_and_indices(size)
        generator = self.get_generator(device)
        return th.randint(low, high, generator=generator, size=global_size, dtype=dtype, device=device)[indices]

    def randn_like(self, tensor):
        size, dtype, device = tensor.size(), tensor.dtype, tensor.device
        return self.randn(*size, dtype=dtype, device=device)

    def set_done_samples(self, done_samples):
        self.done_samples = done_samples
        self.set_seed(self.seed)

    def get_seed(self):
        return self.seed

    def set_seed(self, seed):
        self.rng_cpu.manual_seed(seed)
        if th.cuda.is_available():
            self.rng_cuda.manual_seed(seed)


class DeterministicIndividualGenerator:   #单独样本确定性生成器
    """
    RNG to deterministically sample num_samples samples that does not depend on batch_size or mpi_machines
    Uses a separate rng for each sample to reduce memoery usage
    """

    def __init__(self, num_samples, seed=0):
        if dist.is_initialized():
            self.rank = dist.get_rank()
            self.world_size = dist.get_world_size()
        else:
            print("Warning: Distributed not initialised, using single rank")
            self.rank = 0
            self.world_size = 1
        self.num_samples = num_samples
        self.done_samples = 0
        self.seed = seed
        self.rng_cpu = [th.Generator() for _ in range(num_samples)]
        if th.cuda.is_available():
            self.rng_cuda = [th.Generator(dev()) for _ in range(num_samples)]
        self.set_seed(seed)

    def get_size_and_indices(self, size):
        indices = th.arange(
            self.done_samples + self.rank,
            self.done_samples + self.world_size * int(size[0]),
            self.world_size,
        )
        indices = th.clamp(indices, 0, self.num_samples - 1)
        assert len(indices) == size[0], f"rank={self.rank}, ws={self.world_size}, l={len(indices)}, bs={size[0]}"
        return (1, *size[1:]), indices

    def get_generator(self, device):
        return self.rng_cpu if th.device(device).type == "cpu" else self.rng_cuda

    def randn(self, *size, dtype=th.float, device="cpu"):
        size, indices = self.get_size_and_indices(size)
        generator = self.get_generator(device)
        return th.cat(
            [th.randn(*size, generator=generator[i], dtype=dtype, device=device) for i in indices],
            dim=0,
        )

    def randint(self, low, high, size, dtype=th.long, device="cpu"):
        size, indices = self.get_size_and_indices(size)
        generator = self.get_generator(device)
        return th.cat(
            [
                th.randint(
                    low,
                    high,
                    generator=generator[i],
                    size=size,
                    dtype=dtype,
                    device=device,
                )
                for i in indices
            ],
            dim=0,
        )  #逐个生成后合并

    def randn_like(self, tensor):
        size, dtype, device = tensor.size(), tensor.dtype, tensor.device
        return self.randn(*size, dtype=dtype, device=device)

    def set_done_samples(self, done_samples):
        self.done_samples = done_samples

    def get_seed(self):
        return self.seed

    def set_seed(self, seed):
        [rng_cpu.manual_seed(i + self.num_samples * seed) for i, rng_cpu in enumerate(self.rng_cpu)]
        if th.cuda.is_available():
            [rng_cuda.manual_seed(i + self.num_samples * seed) for i, rng_cuda in enumerate(self.rng_cuda)]
