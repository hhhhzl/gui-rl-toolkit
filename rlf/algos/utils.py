"""
Includes clipping utilies, wrapping utilies, common RL algorithm components.
"""

from typing import Dict, List, Optional, Tuple

import gym.spaces as spaces
import numpy as np
import torch
import torch.nn.functional as F
from torch import autograd
from torch import nn as nn


def clip(
    ac: torch.Tensor, lower_lim: torch.Tensor, upper_lim: torch.Tensor
) -> torch.Tensor:
    """
    Per-dimension clip
    """
    if isinstance(ac, torch.Tensor):
        return torch.max(torch.min(ac, upper_lim), lower_lim)
    else:
        return np.maximum(np.minimum(ac, upper_lim), lower_lim)


def get_joint_limits(
    limits_per_joint: List[Dict[str, float]],
    lower_lim: float,
    upper_lim: float,
    device=None,
    take_count: Optional[int] = None,
) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    if take_count is not None:
        use_limits_per_joint = limits_per_joint[:take_count]
    else:
        use_limits_per_joint = limits_per_joint

    inf_joints = torch.tensor(
        [joint["lower"] == 0.0 for joint in use_limits_per_joint],
        device=device,
    )

    joint_limits_min = torch.tensor(
        [
            joint["lower"] if joint["lower"] != 0.0 else lower_lim
            for joint in use_limits_per_joint
        ],
        device=device,
    )
    joint_limits_max = torch.tensor(
        [
            joint["upper"] if joint["upper"] != 0.0 else upper_lim
            for joint in use_limits_per_joint
        ],
        device=device,
    )
    return joint_limits_min, joint_limits_max, inf_joints


def wrap_joints(
    js: torch.Tensor, lower_lim: float, upper_lim: float, wrap_mask
) -> torch.Tensor:
    res = js.clone()
    lower = torch.tensor(lower_lim)
    upper = torch.tensor(upper_lim)

    mask = (js > upper) | (js == lower)
    res *= ~mask
    res += mask * (
        lower + torch.abs(js + upper) % (torch.abs(lower) + torch.abs(upper))
    )

    mask = (js < lower) | (js == upper)
    res *= ~mask
    res += mask * (
        upper - torch.abs(js - lower) % (torch.abs(lower) + torch.abs(upper))
    )

    res = (lower * (res == upper)) + ((res != upper) * js)
    return ((~wrap_mask) * js) + (wrap_mask * res)


def linear_lr_schedule(cur_update, total_updates, initial_lr, opt):
    lr = initial_lr - (initial_lr * (cur_update / float(total_updates)))
    for param_group in opt.param_groups:
        param_group["lr"] = lr


def td_loss(target, policy, cur_states, cur_actions, add_info={}, cont_actions=False):
    """
    Computes the mean squared error between the Q values for the current states
    and the target q values.
    """
    if cont_actions:
        inputs = torch.cat([cur_states, cur_actions], dim=-1)
        cur_q_vals = policy.get_value(inputs, **add_info)
    else:
        cur_q_vals = policy(cur_states, **add_info).gather(1, cur_actions)
    loss = F.mse_loss(cur_q_vals.view(-1), target.view(-1))
    return loss


def soft_update(model, model_target, tau):
    """
    Copy data from `model` to `model_target` with a decay specified by tau. A
    tau value closer to 0 means less of the model will be copied to the target
    model. A tau of 1 is the same as `hard_update`.
    """
    for param, target_param in zip(model.parameters(), model_target.parameters()):
        # target_param.detach()
        target_param.data.copy_((tau * param.data) + ((1.0 - tau) * target_param.data))


def hard_update(model, model_target):
    """
    Copy all data from `model` to `model_target`
    """
    model_target.load_state_dict(model.state_dict())


def reparam_sample(dist):
    """
    A general method for updating either a categorical or normal distribution.
    In the case of a Categorical distribution, the logits are just returned
    """
    if isinstance(dist, torch.distributions.Normal):
        return dist.rsample()
    elif isinstance(dist, torch.distributions.Categorical):
        return dist.logits
    else:
        raise ValueError("Unrecognized distribution")


def compute_ac_loss(pred_actions, true_actions, ac_space):
    if isinstance(pred_actions, torch.distributions.Distribution):
        pred_actions = reparam_sample(pred_actions)

    if isinstance(ac_space, spaces.Discrete):
        loss = F.cross_entropy(pred_actions, true_actions.view(-1).long())
    else:
        loss = F.mse_loss(pred_actions, true_actions)
    return loss


# Adapted from https://github.com/Khrylx/PyTorch-RL/blob/f44b4444c9db5c1562c5d0bc04080c319ba9141a/utils/torch.py#L26
def set_flat_params_to(params, flat_params):
    prev_ind = 0
    for param in params:
        flat_size = int(np.prod(list(param.size())))
        param.data.copy_(
            flat_params[prev_ind : prev_ind + flat_size].view(param.size())
        )
        prev_ind += flat_size


# Adapted from https://github.com/Khrylx/PyTorch-RL/blob/f44b4444c9db5c1562c5d0bc04080c319ba9141a/utils/torch.py#L17
def get_flat_params_from(params):
    return torch.cat([param.view(-1) for param in params])


def wass_grad_pen(
    expert_state, expert_action, policy_state, policy_action, use_actions, disc_fn
):
    num_dims = len(expert_state.shape) - 1
    alpha = torch.rand(expert_state.size(0), 1)
    alpha_state = (
        alpha.view(-1, *[1 for _ in range(num_dims)])
        .expand_as(expert_state)
        .to(expert_state.device)
    )
    mixup_data_state = alpha_state * expert_state + (1 - alpha_state) * policy_state
    mixup_data_state.requires_grad = True
    inputs = [mixup_data_state]

    if use_actions:
        alpha_action = alpha.expand_as(expert_action).to(expert_action.device)
        mixup_data_action = (
            alpha_action * expert_action + (1 - alpha_action) * policy_action
        )
        mixup_data_action.requires_grad = True
        inputs.append(mixup_data_action)
    else:
        mixup_data_action = []

    disc = disc_fn(mixup_data_state, mixup_data_action)
    ones = torch.ones(disc.size()).to(disc.device)

    grad = autograd.grad(
        outputs=disc,
        inputs=inputs,
        grad_outputs=ones,
        create_graph=True,
        retain_graph=True,
        only_inputs=True,
    )[0]

    grad_pen = (grad.norm(2, dim=1) - 1).pow(2).mean()
    return grad_pen


def wass_distance(p_dist, q_dist, eps=1e-8, n_iters=5):
    """
    Approximate the Wasserstein distance between two distributions using the Sinkhorn algorithm.

    Parameters:
        p_dist (torch.Tensor): The first distribution.
        q_dist (torch.Tensor): The second distribution.
        eps (float): A small positive value to stabilize the computation.
        n_iters (int): Number of iterations for Sinkhorn algorithm.

    Returns:
        torch.Tensor: Approximated Wasserstein distance between p_dist and q_dist.
    """
    n_points = p_dist.shape[0]
    # Initializing the scaling factors for the two distributions
    u = torch.ones(n_points, device=p_dist.device) / n_points
    v = torch.ones(n_points, device=p_dist.device) / n_points

    # Sinkhorn iterations
    for i in range(n_iters):
        v = q_dist / (torch.sum(p_dist * u, dim=1, keepdim=True) + eps)
        u = 1.0 / (torch.sum(p_dist * v, dim=1, keepdim=True) + eps)

    # Compute the optimal transport matrix and the Wasserstein distance
    transport_matrix = u * (p_dist * v.t())
    wass_distance_val = torch.sum(transport_matrix * q_dist, dim=1, keepdim=True)

    return wass_distance_val


class RunningMeanAndVar(nn.Module):
    """
    Adapted from https://github.com/facebookresearch/habitat-lab/blob/bc85d0961cef3b4a08bc9263869606109fb6ff0a/habitat_baselines/rl/ddppo/policy/running_mean_and_var.py#L13
    """

    def __init__(self, state_dim: int) -> None:
        super().__init__()
        self.register_buffer("_mean", torch.zeros(1, state_dim))
        self.register_buffer("_var", torch.zeros(1, state_dim))
        self.register_buffer("_count", torch.zeros(()))
        self._mean: torch.Tensor = self._mean
        self._var: torch.Tensor = self._var
        self._count: torch.Tensor = self._count

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if self.training:
            n = x.size(0)
            # We will need to do reductions (mean) over the channel dimension,
            # so moving channels to the first dimension and then flattening
            # will make those faster.  Further, it makes things more numerically stable
            # for fp16 since it is done in a single reduction call instead of
            # multiple
            x_channels_first = x.transpose(1, 0).contiguous().view(x.size(1), -1)
            new_mean = x_channels_first.mean(-1, keepdim=True)
            new_count = torch.full_like(self._count, n)

            new_var = (x_channels_first - new_mean).pow(2).mean(dim=-1, keepdim=True)

            new_mean = new_mean.view(1, -1)
            new_var = new_var.view(1, -1)

            m_a = self._var * (self._count)
            m_b = new_var * (new_count)
            M2 = (
                m_a
                + m_b
                + (new_mean - self._mean).pow(2)
                * self._count
                * new_count
                / (self._count + new_count)
            )

            self._var = M2 / (self._count + new_count)
            self._mean = (self._count * self._mean + new_count * new_mean) / (
                self._count + new_count
            )

            self._count += new_count

        inv_stdev = torch.rsqrt(torch.max(self._var, torch.full_like(self._var, 1e-2)))
        # This is the same as
        # (x - self._mean) * inv_stdev but is faster since it can
        # make use of addcmul and is more numerically stable in fp16
        return torch.addcmul(-self._mean * inv_stdev, x, inv_stdev)


class MeanAndVar(nn.Module):
    def __init__(self, mean, var):
        super().__init__()
        state_dim = mean.shape[0]
        self.register_buffer("mean", torch.zeros(1, state_dim))
        self.register_buffer("var", torch.zeros(1, state_dim))
        self.set_mean_var(mean, var)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        inv_stdev = torch.rsqrt(torch.max(self.var, torch.full_like(self.var, 1e-2)))
        # This is the same as
        # (x - self._mean) * inv_stdev but is faster since it can
        # make use of addcmul and is more numerically stable in fp16
        return torch.addcmul(-self.mean * inv_stdev, x, inv_stdev)

    def set_mean_var(self, mean, var):
        self.mean = mean
        self.var = var
