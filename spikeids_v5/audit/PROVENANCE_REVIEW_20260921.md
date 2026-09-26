# Adversarial provenance review — 2026-09-21

This review is a gate for the final version-5 run. It distinguishes the exact
local model inputs from upstream provenance statements; a correct local hash
does not excuse an incorrect upstream hash.

## Primary-source cross-checks

- The [UNB NSL-KDD page](https://www.unb.ca/cic/datasets/nsl.html) names
  `KDDTrain+.TXT` and `KDDTest+.TXT`, describes the label and difficulty
  columns, and now states that the download is no longer available. The local
  source contract therefore binds the two mirrored files by their actual
  SHA-256 rather than implying a current UNB download.
- The [UNSW-NB15 project page](https://research.unsw.edu.au/projects/unsw-nb15-dataset)
  explicitly identifies `UNSW_NB15_training-set.csv` as 175,341 rows and
  `UNSW_NB15_testing-set.csv` as 82,332 rows. The audit verifies those roles by
  content and schema, not file size.
- The [CICIDS2017 page](https://www.unb.ca/cic/datasets/ids-2017.html) identifies
  `GeneratedLabelledFlows.zip` and `MachineLearningCSV.zip` and documents the
  five capture days and attacks. The model input is the eight CSV members of
  `MachineLearningCSV.zip`; `GeneratedLabelledFlows.zip` is supporting
  provenance only.
- The [IoT-23 project page](https://www.stratosphereips.org/datasets-iot23)
  describes 20 malware and 3 benign captures and the original detailed labels.
  The formal row benchmark uses a third-party preprocessed Hugging Face
  derivative, not the original 8.7/20 GB release, and retains that limitation.

The NSL mirror was independently read through the GitHub API at commit
`27bbbdf5c5cccf9970b8b6037a0f19dc09c5a0a9`; both returned byte counts and
SHA-256 values equal the local files. The UNSW mirror was independently listed
through the Hugging Face API at revision
`3eb02c4a0a29866b7abcb5ef77c45cf4fcc8f6b0`; its `test.csv` is the official
175,341-row training content and its `train.csv` is the official 82,332-row
testing content, with exact local byte/SHA-256 matches. The source specs now
name official publishers separately from these pinned mirrors.

## IoT-23 pinned-revision correction

The source is pinned to Hugging Face dataset
`19kmunz/iot-23-preprocessed-allcolumns` revision
`04de595b618478668d5974a861a9f4f7305814b1`. `hf datasets info` and
`hf datasets list -R` at that exact revision reported the following LFS
objects; hashing the three local Hub cache blobs independently produced the
same values and byte sizes.

| Shard | Bytes | LFS SHA-256 |
|---|---:|---|
| `train-00000-of-00003-47134d3a10206e3c.parquet` | 91,377,382 | `6e34d6e6b20e55b096315bd0b5873dd61a98c8a1b64b6d10da158569cc5018b5` |
| `train-00001-of-00003-7fb0937ba34dd762.parquet` | 94,804,621 | `8f3e5fd699213d31f6ea21f3406c5b046a83c724fd4953233191aef51e8c6283` |
| `train-00002-of-00003-78be3fca5c692525.parquet` | 88,036,992 | `e227f605a0e10e22c5cc8d8783ee81ca779a25834c293b43de4aa69255630b45` |

The earlier local source spec contained three different strings in the
`lfs_sha256` fields. The formal-r1 local model input itself was still exactly
bound as `data/iot23/iot23_combined.parquet`, 208,124,338 bytes, SHA-256
`8b40d893d47127fa7ac3cafd59b745f1100c403202cad5de0177fb0ebc4c2050`,
with 6,046,623 audited rows. Thus the discovery is an upstream-provenance
metadata error, not evidence that the training bytes changed.

As an additional independent check, the pinned Hugging Face dataset was loaded
from the local revision cache and compared in bounded 65,536-row batches with
the complete local Parquet: all 6,046,623 rows and 21 columns had identical
values, order, and missing-value positions. The comparison allowed Arrow dtype
representation differences only: the local pandas reserialization uses
`large_string`, and nullable `orig_bytes`/`resp_bytes` are represented as
float64 rather than nullable int64. No value coercion difference was accepted.

Nevertheless, the source spec participates in the prepared-cache fingerprint.
The r1 cache and training plan are therefore demoted to non-formal validation
evidence. The corrected source spec, a fresh passed data audit, a fresh cache,
and a new frozen training plan are required for the final paper artifacts. No
old plan or checkpoint is relabelled after the fact.

## CICIDS2017 mirror revision correction

The earlier source spec named `c01dsnap/CIC-IDS2017` without identifying the
host and contained an invalid full revision string. The repository is a
Hugging Face dataset, not a GitHub repository. Hub metadata resolves the pinned
complete revision to `4e9edfa727f800b6f595bc2ee7420527156562b2`.
`hf datasets list -R` at that revision reports the same eight filenames, byte
sizes, and LFS SHA-256 values already recorded for the local CSVs. The source
spec now names the host and valid revision explicitly. As with the IoT fix,
the local CSV hashes did not change, but no cache created from the inaccurate
provenance spec is promoted to the final formal run.
