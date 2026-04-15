"""Unit tests for FocalLoss — gamma=0 must equal weighted CE."""

import torch
import torch.nn as nn
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from experiment_focal import FocalLoss


class TestFocalLoss:
    def test_gamma0_equals_unweighted_ce(self):
        """gamma=0 with uniform alpha should match unweighted CE (mean reduction)."""
        torch.manual_seed(42)
        alpha = torch.ones(3)
        logits = torch.randn(16, 3)
        targets = torch.randint(0, 3, (16,))

        focal = FocalLoss(alpha=alpha, gamma=0.0)
        ce = nn.CrossEntropyLoss(reduction='mean')

        focal_loss = focal(logits, targets)
        ce_loss = ce(logits, targets)

        assert focal_loss.item() == pytest.approx(ce_loss.item(), rel=1e-4)

    def test_gamma_positive_reduces_moderately_easy_loss(self):
        """With gamma>0, moderately confident predictions have lower loss."""
        alpha = torch.ones(3)
        # Moderately easy: correct but not extreme
        logits = torch.tensor([[2.0, -1.0, -1.0]])
        targets = torch.tensor([0])

        focal_g0 = FocalLoss(alpha=alpha, gamma=0.0)
        focal_g2 = FocalLoss(alpha=alpha, gamma=2.0)

        loss_g0 = focal_g0(logits, targets).item()
        loss_g2 = focal_g2(logits, targets).item()

        # Both should be positive, gamma=2 should be smaller
        assert loss_g0 > 0
        assert loss_g2 < loss_g0

    def test_hard_sample_less_suppressed(self):
        """Hard samples should be less suppressed than easy ones."""
        alpha = torch.ones(3)
        logits_easy = torch.tensor([[5.0, -5.0, -5.0]])
        logits_hard = torch.tensor([[0.5, 0.3, 0.2]])
        targets = torch.tensor([0])

        focal = FocalLoss(alpha=alpha, gamma=2.0)

        loss_easy = focal(logits_easy, targets).item()
        loss_hard = focal(logits_hard, targets).item()

        # Hard sample should have higher focal loss
        assert loss_hard > loss_easy

    def test_gradient_flows(self):
        """Ensure gradients flow through focal loss."""
        alpha = torch.tensor([1.0, 1.0])
        logits = torch.randn(8, 2, requires_grad=True)
        targets = torch.randint(0, 2, (8,))

        focal = FocalLoss(alpha=alpha, gamma=2.0)
        loss = focal(logits, targets)
        loss.backward()

        assert logits.grad is not None
        assert logits.grad.shape == logits.shape
