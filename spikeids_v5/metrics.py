"""Validated fixed-label classification metrics; percentage/fraction units are explicit."""
from __future__ import annotations
import numpy as np
from sklearn.metrics import roc_auc_score
from contracts import require

PERCENT_METRICS = ("overall_acc", "macro_acc", "balanced_acc", "macro_precision", "macro_recall", "macro_f1",
                   "weighted_precision", "weighted_recall", "weighted_f1")
SCALARS = (*PERCENT_METRICS, "mcc", "roc_auc_macro", "roc_auc_weighted")


def full_evaluate(y_true, y_pred, y_prob, num_classes, class_names):
    require(type(num_classes) is int and num_classes >= 2, "At least two classes required")
    require(len(class_names) == num_classes and len(set(class_names)) == num_classes and
            all(isinstance(c, str) for c in class_names), "Unique class names in probability-column order required")
    y, pred = np.asarray(y_true), np.asarray(y_pred)
    require(y.ndim == pred.ndim == 1 and len(y) > 0 and y.shape == pred.shape, "Invalid label shapes")
    require(y.dtype.kind in "iu" and pred.dtype.kind in "iu", "Labels must be integer IDs, not floats")
    require(((y >= 0) & (y < num_classes)).all() and ((pred >= 0) & (pred < num_classes)).all(), "Label out of range")
    y, pred = y.astype(np.int64, copy=False), pred.astype(np.int64, copy=False)
    cm = np.bincount(num_classes*y + pred, minlength=num_classes**2).reshape(num_classes, num_classes)
    support, predicted, tp = cm.sum(1), cm.sum(0), cm.diagonal()
    precision = np.divide(tp, predicted, out=np.zeros(num_classes, dtype=float), where=predicted > 0)
    recall = np.divide(tp, support, out=np.zeros(num_classes, dtype=float), where=support > 0)
    denominator = support + predicted
    f1 = np.divide(2*tp, denominator, out=np.zeros(num_classes, dtype=float), where=denominator > 0)
    n = len(y); correct = int(tp.sum())
    # Generalized multiclass MCC from the confusion matrix. Cast before dot products.
    sf, pf = support.astype(float), predicted.astype(float)
    denom = np.sqrt(max(0., n*n - np.dot(sf, sf)) * max(0., n*n - np.dot(pf, pf)))
    mcc = float((correct*n - np.dot(sf, pf))/denom) if denom else 0.
    result = {
        "overall_acc": 100.*correct/n,
        "macro_acc": float(recall.mean()*100), "macro_recall": float(recall.mean()*100),
        "balanced_acc": float(recall[support > 0].mean()*100),
        "macro_precision": float(precision.mean()*100), "macro_f1": float(f1.mean()*100),
        "weighted_precision": float(np.dot(precision, support)/n*100),
        "weighted_recall": float(np.dot(recall, support)/n*100),
        "weighted_f1": float(np.dot(f1, support)/n*100), "mcc": mcc,
        "roc_auc_macro": None, "roc_auc_weighted": None, "auc_status": "not_requested",
        "confusion_matrix": cm.tolist(), "per_class": {},
        "metric_semantics": {"macro_denominator": "all declared classes; undefined P/R/F1 use zero",
                             "balanced_acc_denominator": "classes present in ground truth",
                             "per_class_accuracy": "legacy alias of recall, NOT one-vs-rest accuracy",
                             "p_r_f1_accuracy_unit": "percent", "fpr_fnr_auc_unit": "fraction",
                             "auc_method": "binary positive class index 1; multiclass one-vs-rest"}}
    for i, name in enumerate(class_names):
        neg = n - support[i]
        result["per_class"][name] = {
            "accuracy": float(recall[i]*100), "precision": float(precision[i]*100),
            "recall": float(recall[i]*100), "f1": float(f1[i]*100), "support": int(support[i]),
            "fpr": float((predicted[i]-tp[i])/neg) if neg else None,
            "fnr": float((support[i]-tp[i])/support[i]) if support[i] else None,
            "recall_defined": bool(support[i]), "precision_defined": bool(predicted[i])}
    if y_prob is not None:
        prob = np.asarray(y_prob)
        require(prob.shape == (n, num_classes) and prob.dtype.kind == 'f', "Expected floating probability matrix (N,C)")
        require(np.isfinite(prob).all() and (prob >= 0).all() and (prob <= 1).all(), "Invalid probability values")
        require(np.allclose(prob.sum(1), 1., atol=1e-6, rtol=1e-5), "Probability rows must sum to one")
        if (support == 0).any():
            result["auc_status"] = "undefined_missing_declared_class"
        elif num_classes == 2:
            auc = float(roc_auc_score(y, prob[:, 1]))
            result.update(roc_auc_macro=auc, roc_auc_weighted=auc, auc_status="defined_binary")
        else:
            # Invalid probabilities were rejected above; do not swallow unexpected library errors.
            result.update(roc_auc_macro=float(roc_auc_score(y, prob, multi_class="ovr", average="macro", labels=list(range(num_classes)))),
                          roc_auc_weighted=float(roc_auc_score(y, prob, multi_class="ovr", average="weighted", labels=list(range(num_classes)))),
                          auc_status="defined_multiclass_ovr")
    return result


def summary(values):
    valid = [float(v) for v in values if v is not None]
    require(all(np.isfinite(v) for v in valid), "Non-finite metric aggregate")
    return {"mean": float(np.mean(valid)) if valid else None,
            "std": float(np.std(valid, ddof=1)) if len(valid) > 1 else None,
            "n_valid": len(valid), "n_total": len(values), "values": values}


def aggregate(rows, classes):
    require(rows and len({r["seed"] for r in rows}) == len(rows), "Duplicate/empty seed aggregation")
    result = {key: summary([r[key] for r in rows]) for key in SCALARS}
    result["per_class"] = {c: {key: summary([r["per_class"][c][key] for r in rows])
                              for key in ("accuracy", "precision", "recall", "f1", "fpr", "fnr")}
                           for c in classes}
    cm = np.asarray([r["confusion_matrix"] for r in rows], dtype=float)
    result.update(confusion_matrix_mean=cm.mean(0).tolist(),
                  confusion_matrix_std=cm.std(0, ddof=1).tolist() if len(rows) > 1 else None)
    return result
