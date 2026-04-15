"""
Shared data loading for SNN-IDS.
Provides consistent preprocessing pipelines for NSL-KDD and UNSW-NB15.
All functions return numpy arrays; consumers convert to torch as needed.
"""

import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.preprocessing import LabelEncoder, StandardScaler
from config import COL_NAMES, ATTACK_MAP, NSL_CLASS_NAMES


# ── NSL-KDD ────────────────────────────────────────────────────────────


def load_nslkdd_raw(data_dir):
    """Load raw NSL-KDD DataFrames with label mapping applied.

    Returns:
        (train_df, test_df) with labels mapped and difficulty dropped.
    """
    train_df = pd.read_csv(data_dir / "KDDTrain+.txt", header=None, names=COL_NAMES)
    test_df = pd.read_csv(data_dir / "KDDTest+.txt", header=None, names=COL_NAMES)
    for df in [train_df, test_df]:
        df.drop(columns=["difficulty"], inplace=True)
        df["label"] = df["label"].map(ATTACK_MAP).fillna("unknown")
        df.drop(df[df["label"] == "unknown"].index, inplace=True)
    return train_df, test_df


def preprocess_nslkdd(train_df, test_df):
    """Preprocess NSL-KDD DataFrames into scaled numpy arrays.

    Applies: categorical encoding -> label encoding -> StandardScaler.

    Returns:
        (X_train, y_train, X_test, y_test, scaler, label_enc)
        X arrays are float32, y arrays are int64.
    """
    cat_cols = ["protocol_type", "service", "flag"]
    for col in cat_cols:
        le = LabelEncoder()
        combined = pd.concat([train_df[col], test_df[col]])
        le.fit(combined)
        train_df[col] = le.transform(train_df[col])
        test_df[col] = le.transform(test_df[col])

    label_enc = LabelEncoder()
    label_enc.fit(NSL_CLASS_NAMES)
    y_train = label_enc.transform(train_df["label"])
    y_test = label_enc.transform(test_df["label"])

    X_train = train_df.drop(columns=["label"]).values.astype(np.float32)
    X_test = test_df.drop(columns=["label"]).values.astype(np.float32)

    scaler = StandardScaler()
    X_train = scaler.fit_transform(X_train)
    X_test = scaler.transform(X_test)

    return X_train, y_train, X_test, y_test, scaler, label_enc


def load_nslkdd(data_dir):
    """Load and preprocess NSL-KDD in one step.

    Returns:
        (X_train, y_train, X_test, y_test, scaler, label_enc)
    """
    train_df, test_df = load_nslkdd_raw(data_dir)
    return preprocess_nslkdd(train_df, test_df)


# ── UNSW-NB15 ──────────────────────────────────────────────────────────


def load_unsw_raw(data_dir):
    """Load raw UNSW-NB15 parquet files.

    Returns:
        (train_df, test_df) with id column dropped.
    """
    train_df = pd.read_parquet(data_dir / "UNSW_NB15_training-set.parquet")
    test_df = pd.read_parquet(data_dir / "UNSW_NB15_testing-set.parquet")
    for col in ["id"]:
        if col in train_df.columns:
            train_df = train_df.drop(columns=[col])
            test_df = test_df.drop(columns=[col])
    return train_df, test_df


def preprocess_unsw(train_df, test_df):
    """Preprocess UNSW-NB15 DataFrames into scaled numpy arrays.

    Applies: label extraction -> categorical encoding -> NaN handling -> StandardScaler.

    Returns:
        (X_train, y_train, X_test, y_test, scaler, label_enc, feature_names)
        X arrays are float32, y arrays are int64.
    """
    train_labels_raw = train_df["attack_cat"].astype(str).str.strip()
    test_labels_raw = test_df["attack_cat"].astype(str).str.strip()
    train_df = train_df.drop(columns=["attack_cat", "label"])
    test_df = test_df.drop(columns=["attack_cat", "label"])

    cat_cols = train_df.select_dtypes(include=["object", "category"]).columns.tolist()
    for col in cat_cols:
        le = LabelEncoder()
        combined = pd.concat([train_df[col].astype(str), test_df[col].astype(str)])
        le.fit(combined)
        train_df[col] = le.transform(train_df[col].astype(str))
        test_df[col] = le.transform(test_df[col].astype(str))

    all_classes = sorted(set(train_labels_raw.unique()) | set(test_labels_raw.unique()))
    label_enc = LabelEncoder()
    label_enc.fit(all_classes)
    y_train = label_enc.transform(train_labels_raw)
    y_test = label_enc.transform(test_labels_raw)

    feature_names = list(train_df.columns)

    X_train = train_df.values.astype(np.float32)
    X_test = test_df.values.astype(np.float32)
    X_train = np.nan_to_num(X_train, nan=0.0, posinf=1e6, neginf=-1e6)
    X_test = np.nan_to_num(X_test, nan=0.0, posinf=1e6, neginf=-1e6)

    scaler = StandardScaler()
    X_train = scaler.fit_transform(X_train)
    X_test = scaler.transform(X_test)

    return X_train, y_train, X_test, y_test, scaler, label_enc, feature_names


def load_unsw(data_dir):
    """Load and preprocess UNSW-NB15 in one step.

    Returns:
        (X_train, y_train, X_test, y_test, scaler, label_enc, feature_names)
    """
    train_df, test_df = load_unsw_raw(data_dir)
    return preprocess_unsw(train_df, test_df)
