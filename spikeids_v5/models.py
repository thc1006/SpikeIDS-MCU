"""Explicit ANN definitions. QCFS is NOT silently labeled a T=1 spiking network.

shifted_v1 follows putshua/ANN_SNN_QCFS Models/layer.py ANN branch:
  theta * floor(clamp(x/theta,0,1)*L + 0.5) / L
with the original operation order (division by L before multiplication by theta).
legacy_floor_v1 preserves the project's old unshifted expression for diagnostics.
Different formulas are different experiments and cannot resume each other's runs.
"""
from __future__ import annotations
import copy
import math
import torch
from torch import nn
from contracts import require

class FloorSTE(torch.autograd.Function):
    @staticmethod
    def forward(ctx, x):
        return torch.floor(x)
    @staticmethod
    def backward(ctx, gradient):
        return gradient

class QCFS(nn.Module):
    def __init__(self, L=4, init_threshold=1., formula="shifted_v1"):
        super().__init__()
        require(type(L) is int and L >= 1, "QCFS L must be a positive integer")
        require(math.isfinite(init_threshold) and init_threshold > 0, "QCFS threshold must be positive")
        require(formula in ("shifted_v1", "legacy_floor_v1"), "Unknown QCFS formula")
        self.register_buffer("L", torch.tensor(float(L)))
        self.threshold = nn.Parameter(torch.tensor(float(init_threshold)))
        self.formula = formula
        self._levels = float(L)

    def _load_from_state_dict(self, *args, **kwargs):
        super()._load_from_state_dict(*args, **kwargs)
        self._levels = float(self.L.item())  # one synchronization at load, none in forward

    def forward(self, x):
        if self.formula == "shifted_v1":
            z = torch.clamp(x / self.threshold, 0., 1.)
            return (FloorSTE.apply(z * self._levels + .5) / self._levels) * self.threshold
        step = self.threshold / self.L
        return FloorSTE.apply(torch.clamp(x / (step + 1e-8), 0., self._levels)) * step

class FrozenQCFS(nn.Module):
    """Same forward arithmetic, with frozen threshold. No reciprocal substitution."""
    def __init__(self, source: QCFS):
        super().__init__()
        self.register_buffer("threshold", source.threshold.detach().clone())
        self.register_buffer("L", source.L.detach().clone())
        self.formula, self._levels = source.formula, source._levels
    def forward(self, x):
        if self.formula == "shifted_v1":
            return (torch.floor(torch.clamp(x / self.threshold, 0., 1.) * self._levels + .5)
                    / self._levels) * self.threshold
        step = self.threshold / self.L
        return torch.floor(torch.clamp(x / (step + 1e-8), 0., self._levels)) * step

class IDS_MLP(nn.Module):
    def __init__(self, input_dim, hidden=256, num_classes=5):
        super().__init__()
        self.layers = nn.Sequential(
            nn.Linear(input_dim, hidden), nn.BatchNorm1d(hidden), nn.ReLU(),
            nn.Linear(hidden, hidden), nn.BatchNorm1d(hidden), nn.ReLU(),
            nn.Linear(hidden, hidden // 2), nn.BatchNorm1d(hidden // 2), nn.ReLU(),
            nn.Linear(hidden // 2, num_classes))
    def forward(self, x):
        return self.layers(x)

class IDS_MLP_QCFS(nn.Module):
    def __init__(self, input_dim=41, hidden=256, num_classes=5, L=4, formula="shifted_v1"):
        super().__init__()
        self.layers = nn.Sequential(
            nn.Linear(input_dim, hidden), nn.BatchNorm1d(hidden), QCFS(L, formula=formula),
            nn.Linear(hidden, hidden), nn.BatchNorm1d(hidden), QCFS(L, formula=formula),
            nn.Linear(hidden, hidden // 2), nn.BatchNorm1d(hidden // 2), QCFS(L, formula=formula),
            nn.Linear(hidden // 2, num_classes))
    def forward(self, x):
        return self.layers(x)

class TinyCNN_IDS(nn.Module):
    def __init__(self, input_dim, num_classes=5, c1=8, c2=16):
        super().__init__()
        self.input_dim = input_dim
        self.conv1 = nn.Conv2d(1, c1, (1, 3), padding=(0, 1))
        self.relu1 = nn.ReLU()
        self.conv2 = nn.Conv2d(c1, c2, (1, 3), padding=(0, 1))
        self.relu2 = nn.ReLU()
        self.fc = nn.Linear(c2 * input_dim, num_classes)
    def forward(self, x):
        # Contract is always (N,F); do not accept accidentally mis-shaped images.
        x = x.unsqueeze(1).unsqueeze(2)
        return self.fc(self.relu2(self.conv2(self.relu1(self.conv1(x)))).flatten(1))


def build(kind, input_dim, classes, hidden=256, levels=4, formula="shifted_v1"):
    require(input_dim > 0 and classes >= 2 and hidden >= 2, "Invalid model dimensions")
    if kind == "relu": return IDS_MLP(input_dim, hidden, classes)
    if kind == "qcfs": return IDS_MLP_QCFS(input_dim, hidden, classes, levels, formula)
    if kind == "cnn": return TinyCNN_IDS(input_dim, classes)
    raise ValueError(f"Unknown model arm: {kind}")


def fuse_linear_bn(linear: nn.Linear, bn: nn.BatchNorm1d) -> nn.Linear:
    require(not linear.training and not bn.training, "BN folding requires eval mode")
    require(bn.running_mean is not None and bn.running_var is not None, "BN running statistics missing")
    require(linear.out_features == bn.num_features, "BN shape mismatch")
    require(bn.num_batches_tracked is not None and int(bn.num_batches_tracked) > 0,
            "BN has never observed a training batch")
    require(bool(torch.isfinite(bn.running_mean).all() & torch.isfinite(bn.running_var).all()),
            "Non-finite BN statistics")
    require(bool((bn.running_var >= 0).all()), "Negative BN variance")
    # PyTorch 2.10 fuse_linear_bn_weights expects non-None affine parameters.
    # Normalize affine=False explicitly instead of assuming the helper supports it.
    if not bn.affine:
        bn = copy.deepcopy(bn)
        bn.affine = True
        bn.weight = nn.Parameter(torch.ones_like(bn.running_mean), requires_grad=False)
        bn.bias = nn.Parameter(torch.zeros_like(bn.running_mean), requires_grad=False)
    return torch.nn.utils.fuse_linear_bn_eval(linear, bn)


def freeze_for_export(model: nn.Module, fold_bn: bool = False) -> nn.Module:
    require(not model.training, "Export requires eval mode")
    result = copy.deepcopy(model)
    if not hasattr(result, "layers"):
        return result
    layers, out, i = list(result.layers), [], 0
    while i < len(layers):
        layer = layers[i]
        if fold_bn and isinstance(layer, nn.Linear) and i + 1 < len(layers) and isinstance(layers[i + 1], nn.BatchNorm1d):
            out.append(fuse_linear_bn(layer, layers[i + 1])); i += 2
        elif isinstance(layer, QCFS):
            out.append(FrozenQCFS(layer)); i += 1
        else:
            out.append(layer); i += 1
    result.layers = nn.Sequential(*out)
    return result.eval()


@torch.inference_mode()
def simulate_if(model: nn.Module, x: torch.Tensor, T: int) -> torch.Tensor:
    """Explicit IF rate-coded simulation, fresh membrane for EACH input batch.

    One binary spike (amplitude theta) per neuron per step; initial membrane
    theta/2, subtractive reset, constant input each step, readout averaged over T.
    This is an evaluation arm, not an asserted lossless conversion or burst code.
    BN must remain in eval; its bias is applied at each step, as are linear biases.
    """
    require(type(T) is int and T >= 1, "T must be a positive integer")
    require(not model.training and isinstance(model, IDS_MLP_QCFS), "IF simulation needs an eval QCFS MLP")
    require(all(not m.training for m in model.modules()), "A child module remains in training mode")
    membranes = {}
    total = None
    for _ in range(T):
        a = x
        for i, layer in enumerate(model.layers):
            if isinstance(layer, QCFS):
                require(layer.formula == "shifted_v1", "IF conversion defined only for shifted_v1")
                theta = layer.threshold
                require(bool(torch.isfinite(theta).all() & (theta > 0).all()), "Invalid threshold")
                v = membranes.get(i, torch.full_like(a, .5) * theta) + a
                spike = (v >= theta).to(a.dtype) * theta
                membranes[i] = v - spike
                a = spike
            else:
                a = layer(a)
        total = a.clone() if total is None else total + a
    return total / T
