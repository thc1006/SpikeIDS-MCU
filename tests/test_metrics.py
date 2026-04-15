"""
Unit tests for src/metrics.py — shared evaluation module.

Tests cover:
1. Correct output keys and types
2. Known-answer tests with synthetic data
3. Edge cases (y_prob=None, single-sample class)
4. FPR/FNR correctness
5. Regression: macro_acc ≈ balanced_acc (sklearn)
"""

import numpy as np
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from metrics import full_evaluate


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def perfect_data():
    """Perfect classifier: y_pred == y_true."""
    np.random.seed(42)
    n = 200
    num_classes = 4
    class_names = ["A", "B", "C", "D"]
    y_true = np.array([i % num_classes for i in range(n)])
    y_pred = y_true.copy()
    y_prob = np.zeros((n, num_classes))
    y_prob[np.arange(n), y_true] = 1.0
    return y_true, y_pred, y_prob, num_classes, class_names


@pytest.fixture
def imperfect_data():
    """Controlled imperfect classifier for known-answer testing."""
    # 3 classes, 10 samples each = 30 total
    # Class 0: 10 correct
    # Class 1: 8 correct, 2 misclassified as class 0
    # Class 2: 5 correct, 3 misclassified as class 0, 2 as class 1
    y_true = np.array([0]*10 + [1]*10 + [2]*10)
    y_pred = np.array(
        [0]*10 +              # class 0: all correct
        [1]*8 + [0]*2 +       # class 1: 8 right, 2 wrong
        [2]*5 + [0]*3 + [1]*2 # class 2: 5 right, 3+2 wrong
    )
    num_classes = 3
    class_names = ["cat0", "cat1", "cat2"]
    # Build probability with some noise
    y_prob = np.full((30, 3), 0.1)
    for i in range(30):
        y_prob[i, y_pred[i]] = 0.8
    return y_true, y_pred, y_prob, num_classes, class_names


@pytest.fixture
def nslkdd_like():
    """5-class data mimicking NSL-KDD class distribution."""
    np.random.seed(123)
    # Imbalanced: class 0=100, 1=50, 2=20, 3=5, 4=1
    sizes = [100, 50, 20, 5, 1]
    y_true = np.concatenate([np.full(s, i) for i, s in enumerate(sizes)])
    # ~80% accurate overall, minority classes worse
    y_pred = y_true.copy()
    # Flip some predictions
    flip_idx = np.random.choice(len(y_true), size=35, replace=False)
    for idx in flip_idx:
        y_pred[idx] = (y_true[idx] + 1) % 5
    num_classes = 5
    class_names = ["DoS", "Probe", "R2L", "U2R", "normal"]
    # Probabilities
    y_prob = np.random.dirichlet(np.ones(5), size=len(y_true))
    for i in range(len(y_true)):
        y_prob[i, y_pred[i]] += 2.0
    y_prob = y_prob / y_prob.sum(axis=1, keepdims=True)
    return y_true, y_pred, y_prob, num_classes, class_names


# ── Test: Output structure ────────────────────────────────────────────

class TestOutputStructure:
    def test_all_required_keys_present(self, perfect_data):
        result = full_evaluate(*perfect_data)
        required_keys = [
            "overall_acc", "macro_acc", "balanced_acc",
            "macro_precision", "macro_recall", "macro_f1",
            "weighted_precision", "weighted_recall", "weighted_f1",
            "mcc", "roc_auc_macro", "roc_auc_weighted",
            "per_class", "confusion_matrix",
        ]
        for key in required_keys:
            assert key in result, f"Missing key: {key}"

    def test_per_class_keys(self, perfect_data):
        result = full_evaluate(*perfect_data)
        for cls in perfect_data[4]:  # class_names
            assert cls in result["per_class"]
            pc = result["per_class"][cls]
            for key in ["accuracy", "precision", "recall", "f1",
                        "fpr", "fnr", "support"]:
                assert key in pc, f"Missing per_class key: {key} for {cls}"

    def test_types(self, perfect_data):
        result = full_evaluate(*perfect_data)
        for key in ["overall_acc", "macro_acc", "mcc"]:
            assert isinstance(result[key], float)
        assert isinstance(result["confusion_matrix"], list)
        assert isinstance(result["per_class"], dict)
        # support should be int
        for cls in perfect_data[4]:
            assert isinstance(result["per_class"][cls]["support"], int)


# ── Test: Perfect classifier ─────────────────────────────────────────

class TestPerfectClassifier:
    def test_overall_acc_100(self, perfect_data):
        result = full_evaluate(*perfect_data)
        assert result["overall_acc"] == pytest.approx(100.0)

    def test_macro_acc_100(self, perfect_data):
        result = full_evaluate(*perfect_data)
        assert result["macro_acc"] == pytest.approx(100.0)

    def test_mcc_1(self, perfect_data):
        result = full_evaluate(*perfect_data)
        assert result["mcc"] == pytest.approx(1.0)

    def test_all_fpr_zero(self, perfect_data):
        result = full_evaluate(*perfect_data)
        for cls in perfect_data[4]:
            assert result["per_class"][cls]["fpr"] == pytest.approx(0.0)

    def test_all_fnr_zero(self, perfect_data):
        result = full_evaluate(*perfect_data)
        for cls in perfect_data[4]:
            assert result["per_class"][cls]["fnr"] == pytest.approx(0.0)

    def test_roc_auc_1(self, perfect_data):
        result = full_evaluate(*perfect_data)
        assert result["roc_auc_macro"] == pytest.approx(1.0)
        assert result["roc_auc_weighted"] == pytest.approx(1.0)


# ── Test: Known-answer imperfect ──────────────────────────────────────

class TestImperfectClassifier:
    def test_overall_acc(self, imperfect_data):
        result = full_evaluate(*imperfect_data)
        # 10 + 8 + 5 = 23 correct out of 30
        assert result["overall_acc"] == pytest.approx(23.0 / 30.0 * 100, abs=0.01)

    def test_per_class_recall(self, imperfect_data):
        result = full_evaluate(*imperfect_data)
        # class 0: 10/10 = 1.0, class 1: 8/10 = 0.8, class 2: 5/10 = 0.5
        assert result["per_class"]["cat0"]["recall"] == pytest.approx(100.0)
        assert result["per_class"]["cat1"]["recall"] == pytest.approx(80.0)
        assert result["per_class"]["cat2"]["recall"] == pytest.approx(50.0)

    def test_per_class_fnr(self, imperfect_data):
        result = full_evaluate(*imperfect_data)
        # FNR = 1 - recall
        assert result["per_class"]["cat0"]["fnr"] == pytest.approx(0.0)
        assert result["per_class"]["cat1"]["fnr"] == pytest.approx(0.2)
        assert result["per_class"]["cat2"]["fnr"] == pytest.approx(0.5)

    def test_per_class_precision(self, imperfect_data):
        result = full_evaluate(*imperfect_data)
        # class 0 predicted 10+2+3=15 times, 10 correct → P=10/15
        assert result["per_class"]["cat0"]["precision"] == pytest.approx(10.0/15*100, abs=0.1)
        # class 1 predicted 8+2=10 times, 8 correct → P=8/10
        assert result["per_class"]["cat1"]["precision"] == pytest.approx(80.0)
        # class 2 predicted 5 times, 5 correct → P=5/5
        assert result["per_class"]["cat2"]["precision"] == pytest.approx(100.0)

    def test_confusion_matrix_shape(self, imperfect_data):
        result = full_evaluate(*imperfect_data)
        cm = result["confusion_matrix"]
        assert len(cm) == 3
        assert len(cm[0]) == 3

    def test_confusion_matrix_values(self, imperfect_data):
        result = full_evaluate(*imperfect_data)
        cm = result["confusion_matrix"]
        # Row 0 (true=0): all predicted as 0
        assert cm[0] == [10, 0, 0]
        # Row 1 (true=1): 2 as 0, 8 as 1
        assert cm[1] == [2, 8, 0]
        # Row 2 (true=2): 3 as 0, 2 as 1, 5 as 2
        assert cm[2] == [3, 2, 5]

    def test_balanced_acc_equals_macro_acc(self, imperfect_data):
        result = full_evaluate(*imperfect_data)
        # balanced_accuracy_score = mean per-class recall = macro_acc
        assert result["balanced_acc"] == pytest.approx(result["macro_acc"], abs=0.01)

    def test_mcc_range(self, imperfect_data):
        result = full_evaluate(*imperfect_data)
        assert -1.0 <= result["mcc"] <= 1.0
        # Should be positive since we're better than random
        assert result["mcc"] > 0.0


# ── Test: y_prob=None (graceful fallback) ─────────────────────────────

class TestNoProbabilities:
    def test_roc_auc_none_when_no_prob(self, imperfect_data):
        y_true, y_pred, _, num_classes, class_names = imperfect_data
        result = full_evaluate(y_true, y_pred, None, num_classes, class_names)
        assert result["roc_auc_macro"] is None
        assert result["roc_auc_weighted"] is None

    def test_other_metrics_still_work(self, imperfect_data):
        y_true, y_pred, _, num_classes, class_names = imperfect_data
        result = full_evaluate(y_true, y_pred, None, num_classes, class_names)
        assert result["overall_acc"] == pytest.approx(23.0 / 30.0 * 100, abs=0.01)
        assert result["mcc"] is not None


# ── Test: Imbalanced data ─────────────────────────────────────────────

class TestImbalanced:
    def test_single_sample_class(self):
        """Class with only 1 sample in test set."""
        y_true = np.array([0]*50 + [1]*10 + [2])
        y_pred = np.array([0]*50 + [1]*10 + [0])  # class 2 misclassified
        num_classes = 3
        class_names = ["maj", "mid", "rare"]
        result = full_evaluate(y_true, y_pred, None, num_classes, class_names)
        assert result["per_class"]["rare"]["recall"] == pytest.approx(0.0)
        assert result["per_class"]["rare"]["fnr"] == pytest.approx(1.0)
        assert result["per_class"]["rare"]["support"] == 1

    def test_roc_auc_with_imbalanced(self, nslkdd_like):
        result = full_evaluate(*nslkdd_like)
        if result["roc_auc_macro"] is not None:
            assert 0.0 <= result["roc_auc_macro"] <= 1.0
        if result["roc_auc_weighted"] is not None:
            assert 0.0 <= result["roc_auc_weighted"] <= 1.0


# ── Test: FPR correctness ─────────────────────────────────────────────

class TestFPR:
    def test_fpr_known_answer(self, imperfect_data):
        result = full_evaluate(*imperfect_data)
        # Class 0: FP = 2+3 = 5, TN = 10+0+0+2+5 = 17... wait:
        # CM: [[10,0,0],[2,8,0],[3,2,5]]
        # For class 0: TP=10, FP=col0 sum - TP = (10+2+3)-10 = 5
        #              FN=row0 sum - TP = 10-10 = 0
        #              TN = total - TP - FP - FN = 30-10-5-0 = 15
        #              FPR = 5/(5+15) = 0.25
        assert result["per_class"]["cat0"]["fpr"] == pytest.approx(0.25)

        # Class 1: TP=8, FP=col1 sum - TP = (0+8+2)-8 = 2
        #          FN=row1 sum - TP = 10-8 = 2
        #          TN = 30-8-2-2 = 18
        #          FPR = 2/(2+18) = 0.1
        assert result["per_class"]["cat1"]["fpr"] == pytest.approx(0.1)

        # Class 2: TP=5, FP=col2 sum - TP = (0+0+5)-5 = 0
        #          FPR = 0
        assert result["per_class"]["cat2"]["fpr"] == pytest.approx(0.0)


# ── Test: Backward compatibility ──────────────────────────────────────

class TestBackwardCompatibility:
    """Ensure old metric keys are present and match expected computation."""

    def test_old_keys_present(self, nslkdd_like):
        result = full_evaluate(*nslkdd_like)
        old_keys = [
            "overall_acc", "macro_acc", "macro_precision",
            "macro_recall", "macro_f1", "weighted_precision",
            "weighted_recall", "weighted_f1", "per_class",
            "confusion_matrix",
        ]
        for key in old_keys:
            assert key in result

    def test_per_class_old_keys(self, nslkdd_like):
        result = full_evaluate(*nslkdd_like)
        for cls in nslkdd_like[4]:
            pc = result["per_class"][cls]
            for key in ["accuracy", "precision", "recall", "f1", "support"]:
                assert key in pc
