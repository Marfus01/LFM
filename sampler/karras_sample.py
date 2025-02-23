import numpy as np
import torch as th

from .random_util import get_generator


def karras_sample(
    model,
    x_T,
    steps,
    clip_denoised=True,
    progress=False,
    callback=None,
    model_kwargs=None,
    device=None,
    sigma_min=0.002,
    sigma_max=80,  # higher for highres?
    sampler="heun",
    s_churn=0.0,
    s_tmin=0.0,
    s_tmax=float("inf"),
    s_noise=1.0,
    generator=None,
    classifier=None,
    cond_func=None,
):
    if generator is None:
        generator = get_generator("dummy")

    sigmas = th.linspace(sigma_max, sigma_min, steps, device=device)
    #定义采样区间
    sample_fn = {
        "heun": sample_heun,
        "euler": sample_euler,
    }[sampler]

    if sampler in ["heun"]:
        sampler_args = dict(s_churn=s_churn, s_tmin=s_tmin, s_tmax=s_tmax, s_noise=s_noise)
    else:
        sampler_args = {}
    #heun euler 两种采样方法
    def denoiser(x_t, sigma):
        if model_kwargs.get("cfg_scale", 1.0) > 1.0:
            denoised = model.forward_with_cfg(sigma, x_t, **model_kwargs)
        else:
            denoised = model(sigma, x_t, **model_kwargs)
        if clip_denoised:
            denoised = denoised.clamp(-1, 1)
        return denoised
    #denoiser函数，输入x_t和sigma，计算去噪结果
    def cls_denoiser(x_t, sigma):
        vec = model(sigma, x_t)
        cond_vec = cond_func(classifier, x_t, 1.0 - sigma, **model_kwargs)
        return vec + cond_vec
    #是否使用分类器
    if classifier is not None:
        x_0 = sample_fn(
            cls_denoiser,
            x_T,
            sigmas,
            generator,
            progress=progress,
            callback=callback,
            **sampler_args,
        )
    else:
        x_0 = sample_fn(
            denoiser,
            x_T,
            sigmas,
            generator,
            progress=progress,
            callback=callback,
            **sampler_args,
        )
    return x_0


def to_d(x, sigma, denoised):
    """Converts a denoiser output to a Karras ODE derivative."""
    # return (x - denoised) / append_dims(sigma, x.ndim)
    return x  # identity for flow matching


@th.no_grad()
def sample_euler(
    denoiser,
    x, #当前状态
    sigmas, #随机数生成序列
    generator,
    progress=False,
    callback=None,
):
    """Implements Algorithm 2 (Heun steps) from Karras et al. (2022)."""
    s_in = x.new_ones([x.shape[0]])
    indices = range(len(sigmas) - 1)
    if progress:
        from tqdm.auto import tqdm

        indices = tqdm(indices)

    for i in indices:
        sigma = sigmas[i]
        denoised = denoiser(x, sigma * s_in)  #去噪
        # d = to_d(x, sigma, denoised)
        d = denoised
        if callback is not None:
            callback(
                {
                    "x": x,
                    "i": i,
                    "sigma": sigmas[i],
                    "denoised": denoised,
                }
            )
        dt = sigmas[i + 1] - sigma
        x = x + d * dt
    return x


@th.no_grad()
def sample_heun(
    distiller,
    x,
    sigmas,
    generator,
    progress=False,
    callback=None,
    steps=40,
    s_churn=0.0,
    s_tmin=0.0,
    s_tmax=float("inf"),
    s_noise=1.0,
):
    s_in = x.new_ones([x.shape[0]])
    t_steps = sigmas

    x_next = x
    for i, (t_cur, t_next) in enumerate(zip(t_steps[:-1], t_steps[1:])):  # 0, ..., N-1
        x_cur = x_next

        # Increase noise temporarily.  加入临时噪声
        gamma = min(s_churn / steps, np.sqrt(2) - 1) if s_tmin <= t_cur <= s_tmax else 0
        t_hat = th.as_tensor(t_cur + gamma * t_cur)
        x_hat = x_cur + (t_hat**2 - t_cur**2).sqrt() * s_noise * generator.randn_like(x_cur)

        # Euler step.
        denoised = distiller(x_hat, t_hat * s_in)
        # d_cur = (x_hat - denoised) / t_hat
        d_cur = denoised

        x_next = x_hat + (t_next - t_hat) * d_cur

        # Apply 2nd order correction.   二阶修正
        if i < steps - 1:
            denoised = distiller(x_next, t_next * s_in)
            # d_prime = (x_next - denoised) / t_next
            d_prime = denoised
            x_next = x_hat + (t_next - t_hat) * (0.5 * d_cur + 0.5 * d_prime)  #再次去噪求平均

    return x_next
