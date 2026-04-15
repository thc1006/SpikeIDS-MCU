"""Autonomous finalization of the GLOBECOM paper after Phase 2 completes.

Steps:
  1. Verify results/qcfs_lsweep.json exists and is well-formed.
  2. Emit tab:lsweep rows (NSL-KDD OA/MF1, UNSW OA/MF1 across L in {2,4,8,16}).
  3. Patch paper/globecom/main.tex in-place, replacing the four placeholder
     "-- & -- & -- & --" rows with real mean$\\pm$std strings.
  4. Update the macros file by re-running scripts/emit_paper_macros.py.
  5. Re-run scripts/run_globecom_stats.py to refresh the Wilcoxon report
     (L-sweep doesn't change it, but we want timestamp consistency).
  6. Recompile the paper (pdflatex + bibtex + pdflatex x2) and log page count.
  7. Emit a finalization report to logs/phase7_finalize_report.md.

Safe to rerun — every step is idempotent.
"""

from __future__ import annotations

import json
import re
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
R = ROOT / "results"
PAPER = ROOT / "paper" / "globecom"
LOGS = ROOT / "logs"
LOGS.mkdir(exist_ok=True)


def fatal(msg: str) -> None:
    print(f"[FATAL] {msg}", file=sys.stderr)
    sys.exit(1)


def agg_cell(ds_block: dict, L: int, metric: str) -> str:
    """Return a 'mean$\\pm$std' string for the given L and metric."""
    key = f"L{L}"
    if key not in ds_block:
        return "--"
    seed_dict = ds_block[key]
    if not seed_dict:
        return "--"
    vals = [float(v[metric]) for v in seed_dict.values() if metric in v]
    if not vals:
        return "--"
    m = statistics.mean(vals)
    s = statistics.stdev(vals) if len(vals) > 1 else 0.0
    return f"{m:.2f}$\\pm${s:.2f}"


def build_lsweep_rows(data: dict) -> list[str]:
    nsl = data.get("nslkdd", {})
    unsw = data.get("unsw", {})
    rows = []
    rows.append("NSL-KDD OA   & "
                + " & ".join(agg_cell(nsl, L, "overall_acc") for L in (2, 4, 8, 16))
                + " \\\\")
    rows.append("NSL-KDD MF1  & "
                + " & ".join(agg_cell(nsl, L, "macro_f1") for L in (2, 4, 8, 16))
                + " \\\\")
    rows.append("UNSW-NB15 OA & "
                + " & ".join(agg_cell(unsw, L, "overall_acc") for L in (2, 4, 8, 16))
                + " \\\\")
    rows.append("UNSW-NB15 MF1& "
                + " & ".join(agg_cell(unsw, L, "macro_f1") for L in (2, 4, 8, 16))
                + " \\\\")
    return rows


def patch_lsweep_table(tex_path: Path, rows: list[str]) -> bool:
    text = tex_path.read_text()
    # Find the block between \midrule (within tab:lsweep) and \bottomrule.
    pattern = re.compile(
        r"(\\label\{tab:lsweep\}.*?\\midrule\s*\n"
        r"\\textbf\{Dataset\} & \$L\{=\}2\$ & \$L\{=\}4\$ & \$L\{=\}8\$ & \$L\{=\}16\$ \\\\\s*\n"
        r"\\midrule\s*\n)"
        r"(?:.*?\n){4}"
        r"(\\bottomrule)",
        re.DOTALL,
    )
    # Simpler: anchor on the placeholder rows directly.
    placeholder_block = (
        "NSL-KDD OA   & -- & -- & -- & -- \\\\\n"
        "NSL-KDD MF1  & -- & -- & -- & -- \\\\\n"
        "UNSW-NB15 OA & -- & -- & -- & -- \\\\\n"
        "UNSW-NB15 MF1& -- & -- & -- & -- \\\\"
    )
    new_block = "\n".join(rows)
    if placeholder_block in text:
        text = text.replace(placeholder_block, new_block)
        tex_path.write_text(text)
        return True
    # Maybe already patched — detect by checking that the first data row
    # differs from the placeholder.
    if rows[0].split("&")[1].strip() != "--":
        # Check if file already contains the new rows.
        if rows[0] in text:
            return False  # already patched
    fatal("Could not locate tab:lsweep placeholder rows in main.tex")
    return False


def run(cmd: list[str], cwd: Path | None = None, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(cmd)}")
    import os
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env)


def merge_cicids_tinycnn() -> None:
    """Fold results/cnn_baseline_cicids.json into cnn_baseline_merged.json.

    The former has a top-level "cicids2017" block; we want emit_paper_macros
    to read a single merged file with nslkdd/unsw/cicids2017 keys.
    Idempotent: if cicids2017 already merged with matching n_seeds, no-op.
    """
    merged = R / "cnn_baseline_merged.json"
    cicids = R / "cnn_baseline_cicids.json"
    if not cicids.exists():
        print("  merge: cnn_baseline_cicids.json not present, skipping")
        return
    if not merged.exists():
        print("  merge: cnn_baseline_merged.json missing, aborting merge")
        return
    m = json.loads(merged.read_text())
    c = json.loads(cicids.read_text())
    cic_block = c.get("cicids2017")
    if not cic_block:
        print("  merge: cicids file has no cicids2017 key, skipping")
        return
    existing = m.get("cicids2017", {})
    if existing and len(existing.get("per_seed", [])) >= len(
        cic_block.get("per_seed", [])
    ):
        print("  merge: cicids2017 already merged, skipping")
        return
    m["cicids2017"] = cic_block
    merged.write_text(json.dumps(m, indent=2))
    print(
        f"  merge: folded cicids2017 "
        f"(n_seeds={len(cic_block.get('per_seed', []))}) into cnn_baseline_merged.json"
    )


def emit_macros() -> None:
    print("[3/6] Regenerating result_macros.tex")
    merge_cicids_tinycnn()
    cmd = [
        sys.executable, "scripts/emit_paper_macros.py",
        "--nslkdd", "results/multiseed_20.json",
        "--unsw", "results/unsw_multiseed_20.json",
        "--cicids", "results/cicids2017_multiseed_experiment.json",
        "--cnn", "results/cnn_baseline_merged.json",
        "--unsw-qcfs", "results/unsw_qcfs_multiseed.json",
        "--cicids-qcfs", "results/cicids_qcfs_multiseed.json",
        "--stats", "results/stats_report_globecom.json",
        "--out", "paper/globecom/result_macros.tex",
    ]
    res = run(cmd, cwd=ROOT)
    if res.returncode != 0:
        print(res.stdout)
        print(res.stderr)
        fatal("emit_paper_macros.py failed")
    print(res.stdout.strip() or "ok")


def refresh_stats() -> None:
    print("[4/6] Refreshing stats report")
    cmd = [sys.executable, "scripts/run_globecom_stats.py"]
    res = run(cmd, cwd=ROOT)
    if res.returncode != 0:
        print(res.stdout)
        print(res.stderr)
        fatal("run_globecom_stats.py failed")


def compile_paper() -> tuple[bool, int]:
    print("[5/6] Compiling paper")
    for cmd in [
        ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "main.tex"],
        ["bibtex", "main"],
        ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "main.tex"],
        ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "main.tex"],
    ]:
        res = run(cmd, cwd=PAPER)
        if res.returncode != 0:
            tail = (res.stdout or "") + "\n" + (res.stderr or "")
            print(tail[-3000:])
            return False, -1
    # Count pages via pdfinfo if available; else use \pageref-like heuristic.
    pdfinfo = run(["pdfinfo", "main.pdf"], cwd=PAPER)
    pages = -1
    if pdfinfo.returncode == 0:
        for line in pdfinfo.stdout.splitlines():
            if line.startswith("Pages:"):
                pages = int(line.split()[1])
                break
    return True, pages


def write_report(ok: bool, pages: int, rows: list[str]) -> Path:
    report = LOGS / "phase7_finalize_report.md"
    lines = [
        "# Phase 7 Finalization Report",
        "",
        f"- Paper compile: **{'OK' if ok else 'FAILED'}**",
        f"- Pages: **{pages}**",
        "",
        "## L-sweep table rows inserted",
        "```",
    ]
    lines.extend(rows)
    lines.append("```")
    report.write_text("\n".join(lines) + "\n")
    return report


def main() -> None:
    print("=== Phase 7 Finalization ===")
    print("[1/6] Loading results/qcfs_lsweep.json")
    lsweep_path = R / "qcfs_lsweep.json"
    if not lsweep_path.exists():
        fatal(f"missing {lsweep_path} — Phase 2 not finished")
    data = json.loads(lsweep_path.read_text())
    rows = build_lsweep_rows(data)
    print("  L-sweep rows:")
    for r in rows:
        print(f"    {r}")

    print("[2/6] Patching tab:lsweep in main.tex")
    patched = patch_lsweep_table(PAPER / "main.tex", rows)
    print(f"  patched={patched}")

    emit_macros()
    refresh_stats()
    ok, pages = compile_paper()
    report = write_report(ok, pages, rows)
    print(f"[6/6] Wrote {report}")
    if not ok:
        sys.exit(2)
    print(f"DONE — pages={pages}")


if __name__ == "__main__":
    main()
