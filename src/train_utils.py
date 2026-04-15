"""
Shared training utilities for all SNN-IDS experiments.

Extracted from 7+ files to eliminate duplication.
"""

import numpy as np
import torch


def set_seed(seed):
    """Set random seed for reproducibility across all backends."""
    torch.manual_seed(seed)
    np.random.seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False


def compute_class_weights(labels, num_classes):
    """Compute inverse-frequency class weights for imbalanced classification.

    Args:
        labels: torch.Tensor of integer class labels
        num_classes: total number of classes

    Returns:
        torch.Tensor of shape (num_classes,) with normalized weights
    """
    counts = np.bincount(labels.numpy(), minlength=num_classes).astype(np.float32)
    counts = np.maximum(counts, 1.0)
    weights = 1.0 / counts
    weights = weights / weights.sum() * num_classes
    return torch.tensor(weights, dtype=torch.float32)
