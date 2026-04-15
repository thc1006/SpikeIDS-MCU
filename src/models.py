"""
Shared model definitions for all SNN-IDS experiments.

Extracted from 12+ files to eliminate duplication.
"""

import torch
import torch.nn as nn


# ── Standard ReLU MLP ────────────────────────────────────────────────

class IDS_MLP(nn.Module):
    """Standard IDS MLP: Linear→BN→ReLU × 3 + Linear output.

    Architecture: input_dim → hidden → hidden → hidden//2 → num_classes
    """
    def __init__(self, input_dim, hidden=256, num_classes=5):
        super().__init__()
        self.layers = nn.Sequential(
            nn.Linear(input_dim, hidden),
            nn.BatchNorm1d(hidden),
            nn.ReLU(),
            nn.Linear(hidden, hidden),
            nn.BatchNorm1d(hidden),
            nn.ReLU(),
            nn.Linear(hidden, hidden // 2),
            nn.BatchNorm1d(hidden // 2),
            nn.ReLU(),
            nn.Linear(hidden // 2, num_classes),
        )

    def forward(self, x):
        return self.layers(x)


class IDS_MLP_Fused(nn.Module):
    """BN-fused IDS MLP for ONNX export (no BatchNorm layers)."""
    def __init__(self, input_dim, hidden=256, num_classes=5):
        super().__init__()
        self.fc1 = nn.Linear(input_dim, hidden)
        self.relu1 = nn.ReLU()
        self.fc2 = nn.Linear(hidden, hidden)
        self.relu2 = nn.ReLU()
        self.fc3 = nn.Linear(hidden, hidden // 2)
        self.relu3 = nn.ReLU()
        self.fc4 = nn.Linear(hidden // 2, num_classes)

    def forward(self, x):
        x = self.relu1(self.fc1(x))
        x = self.relu2(self.fc2(x))
        x = self.relu3(self.fc3(x))
        return self.fc4(x)


# ── Flexible MLP (for baseline experiments) ──────────────────────────

class FlexMLP(nn.Module):
    """Flexible MLP with configurable hidden layers."""
    def __init__(self, input_dim, hidden_layers, num_classes):
        super().__init__()
        layers = []
        prev_dim = input_dim
        for h in hidden_layers:
            layers.append(nn.Linear(prev_dim, h))
            layers.append(nn.BatchNorm1d(h))
            layers.append(nn.ReLU())
            prev_dim = h
        layers.append(nn.Linear(prev_dim, num_classes))
        self.layers = nn.Sequential(*layers)
        self.n_params = sum(p.numel() for p in self.parameters())

    def forward(self, x):
        return self.layers(x)


class FusedFlexMLP(nn.Module):
    """Fused (no BN) version of FlexMLP for ONNX export."""
    def __init__(self, input_dim, hidden_layers, num_classes):
        super().__init__()
        layers = []
        prev_dim = input_dim
        for h in hidden_layers:
            layers.append(nn.Linear(prev_dim, h))
            layers.append(nn.ReLU())
            prev_dim = h
        layers.append(nn.Linear(prev_dim, num_classes))
        self.layers = nn.Sequential(*layers)

    def forward(self, x):
        return self.layers(x)


# ── Tiny Conv2D-based CNN (GLOBECOM Phase 5 baseline) ────────────────

class TinyCNN_IDS(nn.Module):
    """Conv2D (1×K) baseline for tabular IDS features.

    Neural-ART only has confirmed support for Conv2D (not Conv1D). We treat
    the tabular features as a 1-channel "image" of shape (1, 1, input_dim)
    and apply Conv2D kernels of height 1 (so they run along the feature axis
    only). Kernel widths are kept within Neural-ART's stride-1 limit of 6.

    Op set used:  Conv2D, ReLU, Gemm (Linear), Flatten, Reshape.
    Param budget: < 30K for 41 input features, 5 classes.
    """

    def __init__(self, input_dim: int, num_classes: int = 5,
                 c1: int = 8, c2: int = 16):
        super().__init__()
        self.input_dim = int(input_dim)
        # kernel (height=1, width=3) stays within Neural-ART limits.
        self.conv1 = nn.Conv2d(1, c1, kernel_size=(1, 3), padding=(0, 1))
        self.relu1 = nn.ReLU()
        self.conv2 = nn.Conv2d(c1, c2, kernel_size=(1, 3), padding=(0, 1))
        self.relu2 = nn.ReLU()
        self.fc = nn.Linear(c2 * self.input_dim, num_classes)

    def forward(self, x):
        # x: (B, F) → (B, 1, 1, F)
        if x.dim() == 2:
            x = x.unsqueeze(1).unsqueeze(2)
        x = self.relu1(self.conv1(x))
        x = self.relu2(self.conv2(x))
        x = x.flatten(1)
        return self.fc(x)


# ── QCFS (Quantization-Clip-Floor-Shift) ─────────────────────────────

class FloorSTE(torch.autograd.Function):
    """Floor with Straight-Through Estimator gradient."""
    @staticmethod
    def forward(ctx, x):
        return torch.floor(x)

    @staticmethod
    def backward(ctx, grad_output):
        return grad_output


class QCFS(nn.Module):
    """Quantization-Clip-Floor-Shift activation.

    QCFS(x) = floor( clip(x / step, 0, L) ) * step

    At T=1: equivalent to uniform INT quantization with L levels.
    The threshold (and thus step) is learnable.
    """
    def __init__(self, L=8, init_threshold=1.0):
        super().__init__()
        self.register_buffer("L", torch.tensor(float(L)))
        self.threshold = nn.Parameter(torch.tensor(float(init_threshold)))

    def forward(self, x):
        step = self.threshold / self.L
        x_scaled = x / (step + 1e-8)
        x_clipped = torch.clamp(x_scaled, 0.0, self.L.item())
        x_floored = FloorSTE.apply(x_clipped)
        return x_floored * step

    def extra_repr(self):
        return f"L={self.L}, threshold={self.threshold.item():.4f}"


class QCFSFrozen(nn.Module):
    """QCFS with frozen (constant) threshold for clean ONNX export."""
    def __init__(self, step, L):
        super().__init__()
        self.register_buffer("step_val", torch.tensor(float(step)))
        self.register_buffer("L_val", torch.tensor(float(L)))
        self.register_buffer("inv_step", torch.tensor(1.0 / (step + 1e-8)))

    def forward(self, x):
        x_scaled = x * self.inv_step
        x_clipped = torch.clamp(x_scaled, 0.0, self.L_val)
        x_floored = torch.floor(x_clipped)
        return x_floored * self.step_val


class IDS_MLP_QCFS(nn.Module):
    """IDS MLP with QCFS activation instead of ReLU."""
    def __init__(self, input_dim=41, hidden=256, num_classes=5, L=8):
        super().__init__()
        self.layers = nn.Sequential(
            nn.Linear(input_dim, hidden),
            nn.BatchNorm1d(hidden),
            QCFS(L=L),
            nn.Linear(hidden, hidden),
            nn.BatchNorm1d(hidden),
            QCFS(L=L),
            nn.Linear(hidden, hidden // 2),
            nn.BatchNorm1d(hidden // 2),
            QCFS(L=L),
            nn.Linear(hidden // 2, num_classes),
        )

    def forward(self, x):
        return self.layers(x)


class IDS_MLP_QCFS_Frozen(nn.Module):
    """Export-only model with frozen QCFS and fused BatchNorm."""
    def __init__(self, layers_list):
        super().__init__()
        self.layers = nn.Sequential(*layers_list)

    def forward(self, x):
        return self.layers(x)


# ── BN Fusion Utilities ──────────────────────────────────────────────

def fuse_bn(linear, bn):
    """Fuse BatchNorm into Linear layer, return (weight, bias) tensors."""
    w = linear.weight.data
    b = linear.bias.data if linear.bias is not None else torch.zeros(w.shape[0])
    mean = bn.running_mean
    var = bn.running_var
    gamma = bn.weight.data
    beta = bn.bias.data
    eps = bn.eps
    std = torch.sqrt(var + eps)
    fused_w = w * (gamma / std).unsqueeze(1)
    fused_b = (b - mean) * gamma / std + beta
    return fused_w, fused_b


def fuse_bn_to_linear(linear, bn):
    """Fuse BatchNorm into Linear layer, return new nn.Linear module."""
    fused_w, fused_b = fuse_bn(linear, bn)
    new_linear = nn.Linear(linear.in_features, linear.out_features)
    new_linear.weight.data = fused_w
    new_linear.bias.data = fused_b
    return new_linear


def fuse_bn_model(model):
    """Fuse all BatchNorm layers in a Sequential model in-place."""
    layers = list(model.layers)
    fused = []
    i = 0
    while i < len(layers):
        if (i + 1 < len(layers)
                and isinstance(layers[i], nn.Linear)
                and isinstance(layers[i + 1], nn.BatchNorm1d)):
            fused.append(fuse_bn_to_linear(layers[i], layers[i + 1]))
            i += 2
        else:
            fused.append(layers[i])
            i += 1
    model.layers = nn.Sequential(*fused)
    return model
