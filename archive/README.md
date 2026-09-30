# Archived and non-authoritative material

The version-5 pipeline documented in `../spikeids_v5/README.md` is the current
workflow. The manuscript under `../paper/globecom/` is still awaiting binding
to the completed neural run, accepted tree/export evidence and paper review;
it is not an accepted v5 manuscript. This archive keeps
superseded material recoverable without leaving dangerous entry points in the
active project layout.

- Planned `pre_v5_non_authoritative/` will contain old ML code, tests, result files, and
  hand-maintained paper values. Some paths have confirmed test-selection or
  preprocessing leakage; other paths are merely based on a different,
  superseded protocol. None may supply version-5 claims.
- Planned `historical_hardware/` will contain board firmware, tooling, and measurements
  that may remain valid in their original microbenchmark scope but are not
  bound to a version-5 checkpoint-to-binary provenance chain.
- Planned `historical_papers/` and `historical_docs/` will preserve prior manuscripts and
  design records. They are historical, not current evidence.
- Planned `v5_nonformal_validation/` will contain version-5 smoke, profile, benchmark, or
  partial-run outputs. They remain useful engineering evidence but are not the
  bundle-bound formal paper run.
- `local_toolchain_installers/` and `local_handoffs/` are workstation-only
  payloads and are intentionally excluded from Git.

The two CIC source ZIPs remain at the repository root because the signed data
source specification and reproducible audit bind those exact relative paths.
They are current provenance inputs, not stale result artifacts.

These categories describe the intended archive, not a claim that the moves
have happened. As of the 2026-09-21 post-run review, this directory has no
`MANIFEST.json`; no archival acceptance should be inferred from this README.
Do not relocate evidence still bound by absolute paths in active consumers.

`MANIFEST.json` is generated at archival time. It records every original and
archived path, byte count, SHA-256 digest, classification, reason, and current
replacement. No material file is deleted by the archival operation.
