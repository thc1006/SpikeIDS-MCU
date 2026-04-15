"""
Shared evaluation metrics for all SNN-IDS experiments.

Provides a single full_evaluate() function used by:
- experiment_multiseed.py (NSL-KDD, ReLU + QCFS)
- experiment_unsw.py (UNSW-NB15, ReLU)
- tree_baseline.py (RF + XGBoost)
- experiment_baselines.py (LogReg + small MLPs)
- experiment_focal.py (focal loss ablation)
- experiment_cicids.py (CICIDS2017)
"""

import numpy as np
from sklearn.metrics import (
    confusion_matrix,
    precision_recall_fscore_support,
    balanced_accuracy_score,
    matthews_corrcoef,
    roc_auc_score,
)


def full_evaluate(y_true, y_pred, y_prob, num_classes, class_names):
    """
    Compute all metrics from predictions + probabilities.

    Args:
        y_true: ground truth labels, shape (N,), int array
        y_pred: predicted labels, shape (N,), int array
        y_prob: predicted probabilities, shape (N, C), float array or None
                (if None, ROC-AUC will be None)
        num_classes: number of classes (int)
        class_names: list of class name strings, length == num_classes

    Returns:
        dict with all metrics (values are Python floats/ints/lists)
    """
    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)
    labels = list(range(num_classes))

    # Confusion matrix
    cm = confusion_matrix(y_true, y_pred, labels=labels)

    # Per-class precision, recall, F1, support
    precision, recall, f1, support = precision_recall_fscore_support(
        y_true, y_pred, labels=labels, zero_division=0
    )

    # Per-class accuracy
    row_sums = np.maximum(cm.sum(axis=1), 1)
    per_class_acc = cm.diagonal() / row_sums

    # Overall accuracy
    overall_acc = cm.diagonal().sum() / cm.sum() * 100

    # Macro accuracy (= balanced accuracy)
    macro_acc = per_class_acc.mean() * 100

    # Macro P/R/F1
    macro_precision = precision.mean() * 100
    macro_recall = recall.mean() * 100
    macro_f1 = f1.mean() * 100

    # Weighted P/R/F1
    w_precision, w_recall, w_f1, _ = precision_recall_fscore_support(
        y_true, y_pred, average='weighted', zero_division=0
    )

    # Balanced accuracy (sklearn) — should match macro_acc
    balanced_acc = balanced_accuracy_score(y_true, y_pred) * 100

    # MCC (multi-class)
    mcc = matthews_corrcoef(y_true, y_pred)

    # Per-class FPR and FNR from confusion matrix
    per_class_fpr = np.zeros(num_classes)
    per_class_fnr = np.zeros(num_classes)
    for i in range(num_classes):
        tp = cm[i, i]
        fn = cm[i, :].sum() - tp
        fp = cm[:, i].sum() - tp
        tn = cm.sum() - tp - fn - fp
        per_class_fpr[i] = fp / max(fp + tn, 1)
        per_class_fnr[i] = 1.0 - recall[i]  # FNR = 1 - TPR

    # ROC-AUC (OVR)
    roc_auc_macro = None
    roc_auc_weighted = None
    if y_prob is not None:
        y_prob = np.asarray(y_prob)
        try:
            val = float(roc_auc_score(
                y_true, y_prob, multi_class='ovr', average='macro', labels=labels
            ))
            roc_auc_macro = None if np.isnan(val) else val
        except (ValueError, IndexError):
            roc_auc_macro = None
        try:
            val = float(roc_auc_score(
                y_true, y_prob, multi_class='ovr', average='weighted', labels=labels
            ))
            roc_auc_weighted = None if np.isnan(val) else val
        except (ValueError, IndexError):
            roc_auc_weighted = None

    # Build result dict
    result = {
        "overall_acc": float(overall_acc),
        "macro_acc": float(macro_acc),
        "balanced_acc": float(balanced_acc),
        "macro_precision": float(macro_precision),
        "macro_recall": float(macro_recall),
        "macro_f1": float(macro_f1),
        "weighted_precision": float(w_precision * 100),
        "weighted_recall": float(w_recall * 100),
        "weighted_f1": float(w_f1 * 100),
        "mcc": float(mcc),
        "roc_auc_macro": roc_auc_macro,
        "roc_auc_weighted": roc_auc_weighted,
        "per_class": {
            class_names[i]: {
                "accuracy": float(per_class_acc[i] * 100),
                "precision": float(precision[i] * 100),
                "recall": float(recall[i] * 100),
                "f1": float(f1[i] * 100),
                "fpr": float(per_class_fpr[i]),
                "fnr": float(per_class_fnr[i]),
                "support": int(support[i]),
            }
            for i in range(num_classes)
        },
        "confusion_matrix": cm.tolist(),
    }

    return result
