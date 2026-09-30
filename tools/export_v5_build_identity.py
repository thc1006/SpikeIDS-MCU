#!/usr/bin/env python3
"""Read-only distribution/runtime version identities for the export continuation.

Distribution metadata and imported module versions are different fields. Neither
is normalized or substituted for the other. This binds selected installed Python
files, not every binary in a wheel and not a cryptographic publisher identity.
No checkpoint loading, model execution, package installation or file writes occur.
"""
from __future__ import annotations

import ast
import csv
from email.parser import BytesParser
import hashlib
import importlib
import importlib.metadata
import io
import os
from pathlib import Path
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "spikeids_v5")]
from contracts import json_bytes, require

SELF = Path(__file__).resolve()
PACKAGES = ("numpy", "torch", "onnx", "onnxruntime")
KIND = "spikeids_v5_export_build_identity"
SCOPE = "selected_installed_python_files_and_exact_distribution_runtime_versions"
NOT_ASSERTED = ["complete_wheel_or_binary_integrity", "publisher_authenticity",
                "historical_module_memory_integrity", "numerical_export_parity"]
STAT_KEYS = {"device", "inode", "mode", "links", "bytes", "mtime_ns", "ctime_ns"}


def source_paths() -> list[Path]:
    return sorted([SELF, ROOT / "spikeids_v5/contracts.py"])


def _equal(left, right):
    return json_bytes(left) == json_bytes(right)


def _canonical(value: str | Path) -> Path:
    path = Path(value)
    require(path.is_absolute() and ".." not in path.parts and path == path.resolve() and
            not path.is_symlink() and not any(p.is_symlink() for p in path.parents),
            f"Noncanonical installed-package path: {path}")
    return path


def _stat(status):
    return {"device": status.st_dev, "inode": status.st_ino, "mode": status.st_mode,
            "links": status.st_nlink, "bytes": status.st_size,
            "mtime_ns": status.st_mtime_ns, "ctime_ns": status.st_ctime_ns}


def _read_file(path: Path) -> tuple[bytes, dict]:
    """Hash and parse the same stable FD, allowing recorded uv package hardlinks."""
    path = _canonical(path)
    before = _stat(path.lstat())
    require(stat.S_ISREG(before["mode"]) and before["links"] >= 1,
            f"Installed-package evidence is not a regular file: {path}")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        require(_stat(os.fstat(fd)) == before, f"Package changed while opening: {path}")
        chunks = []
        while block := os.read(fd, 1024 * 1024):
            chunks.append(block)
        require(_stat(os.fstat(fd)) == before, f"Package changed while reading: {path}")
    finally:
        os.close(fd)
    require(_stat(path.lstat()) == before, f"Package pathname changed while reading: {path}")
    payload = b"".join(chunks)
    return payload, {**before, "sha256": hashlib.sha256(payload).hexdigest()}


def _end_stats(pins):
    for name, pin in pins.items():
        path = _canonical(name)
        require(_equal(_stat(path.lstat()), {key: pin[key] for key in STAT_KEYS}),
                f"Installed package changed at identity endpoint: {path}")


def _runtime_text(value, field):
    # torch.__version__ is a str subclass (TorchVersion); preserve its full text.
    require(isinstance(value, str) and bool(value), f"Invalid runtime text: {field}")
    return str(value)


def _literal_assignments(payload: bytes, path: Path, names: set[str]) -> dict:
    """Read only explicit version constants, without executing installed sources."""
    values = {}
    for node in ast.parse(payload, filename=str(path)).body:
        targets = (node.targets if isinstance(node, ast.Assign) else
                   [node.target] if isinstance(node, ast.AnnAssign) else [])
        for target in targets:
            if isinstance(target, ast.Name) and target.id in names:
                require(target.id not in values, f"Ambiguous version constant in {path}")
                try:
                    values[target.id] = ast.literal_eval(node.value)
                except (ValueError, TypeError) as exc:
                    raise ValueError(f"Nonliteral version constant {target.id} in {path}") from exc
    require(set(values) == names, f"Missing literal version constants in {path}")
    return values


def _module_file(module, expected: Path | None = None) -> Path:
    require(isinstance(getattr(module, "__file__", None), str), "Missing loaded module file")
    path = _canonical(module.__file__)
    require(getattr(getattr(module, "__spec__", None), "origin", None) == str(path),
            f"Loaded module file/spec origin disagree: {path}")
    if expected is not None:
        require(path == expected, f"Loaded version module belongs elsewhere: {path}")
    return path


def _end_runtime(packages):
    for name, item in packages.items():
        module = importlib.import_module(name)
        _module_file(module, Path(item["module_file"]))
        require(_runtime_text(getattr(module, "__version__", None), name) == item["module_version"] and
                importlib.metadata.version(name) == item["distribution_version"],
                f"Runtime version changed at identity endpoint: {name}")
        if name != "onnxruntime":
            version_module = importlib.import_module(name + ".version")
            _module_file(version_module, Path(item["version_file"]))
            key = "__version__" if name == "torch" else "version"
            require(_runtime_text(getattr(version_module, key, None), name + ".version") ==
                    item["module_version"], f"Version submodule changed at endpoint: {name}")
        if name == "torch":
            require(_equal({key: getattr(version_module, key, None)
                            for key in ("cuda", "git_version")}, item["torch_build"]),
                    "Torch CUDA/git changed at identity endpoint")


def _capture_package(name: str, pins: dict) -> dict:
    module = importlib.import_module(name)
    module_file = _module_file(module)
    distribution = importlib.metadata.distribution(name)
    root = _canonical(distribution.locate_file(""))
    require(root.is_dir() and module_file == root / name / "__init__.py",
            f"Loaded {name} is not the selected distribution's package")
    files = distribution.files
    require(files is not None, f"Distribution file ownership is unavailable: {name}")
    entries = [str(entry) for entry in files]
    require(len(entries) == len(set(entries)), f"Duplicate distribution file ownership: {name}")
    metadata_entries = [entry for entry in entries
                        if len(Path(entry).parts) == 2 and
                        Path(entry).parent.name.endswith(".dist-info") and
                        Path(entry).name == "METADATA"]
    require(len(metadata_entries) == 1, f"Ambiguous METADATA ownership: {name}")
    metadata_file = _canonical(distribution.locate_file(metadata_entries[0]))
    require(metadata_file.parent.parent == root, f"METADATA is outside distribution root: {name}")
    record_file = metadata_file.with_name("RECORD")
    version_file = root / name / ("__init__.py" if name == "onnxruntime" else "version.py")
    owned = (module_file, version_file, metadata_file, record_file)
    payloads = {}
    for path in dict.fromkeys(owned):
        relative = str(path.relative_to(root))
        require(relative in entries and
                _canonical(distribution.locate_file(relative)) == path,
                f"Selected installed file lacks distribution ownership: {path}")
        payload, snapshot = _read_file(path)
        require(str(path) not in pins or _equal(pins[str(path)], snapshot),
                f"Package evidence changed between reads: {path}")
        pins[str(path)] = snapshot
        payloads[path] = payload
    # Pin the same-FD RECORD that establishes membership; do not claim to verify
    # every RECORD hash or every installed library in the distribution.
    rows = list(csv.reader(io.StringIO(payloads[record_file].decode("utf-8"))))
    require(all(len(row) == 3 for row in rows), f"Malformed installed RECORD: {name}")
    record_entries = [row[0] for row in rows]
    require(len(record_entries) == len(set(record_entries)) and
            set(record_entries) == set(entries), f"Distribution ownership changed: {name}")
    metadata = BytesParser().parsebytes(payloads[metadata_file])
    require(metadata.get_all("Name") == [name] and
            len(metadata.get_all("Version", [])) == 1,
            f"Wrong or ambiguous distribution METADATA: {name}")
    distribution_version = metadata["Version"]
    require(type(distribution_version) is str and distribution_version and
            distribution.version == distribution_version and
            importlib.metadata.version(name) == distribution_version,
            f"Distribution version API/METADATA mismatch: {name}")
    module_version = _runtime_text(getattr(module, "__version__", None), name)
    names = ({"__version__", "cuda", "git_version"} if name == "torch" else
             {"__version__"} if name == "onnxruntime" else {"version"})
    literals = _literal_assignments(payloads[version_file], version_file, names)
    version_key = "__version__" if name in ("torch", "onnxruntime") else "version"
    require(type(literals[version_key]) is str and literals[version_key] == module_version,
            f"Loaded module version differs from installed source: {name}")
    result = {"distribution_version": distribution_version, "module_version": module_version,
              "distribution_root": str(root), "module_file": str(module_file),
              "version_file": str(version_file), "metadata_file": str(metadata_file),
              "record_file": str(record_file)}
    if name != "onnxruntime":
        version_module = importlib.import_module(name + ".version")
        _module_file(version_module, version_file)
        require(_runtime_text(getattr(version_module, version_key, None), name + ".version") ==
                module_version, f"Loaded version submodule disagrees: {name}")
    if name == "torch":
        cuda = getattr(version_module, "cuda", None)
        git_version = getattr(version_module, "git_version", None)
        require((cuda is None or type(cuda) is str and bool(cuda)) and
                type(git_version) is str and bool(git_version) and
                _equal({"cuda": cuda, "git_version": git_version},
                       {key: literals[key] for key in ("cuda", "git_version")}),
                "Torch CUDA/git runtime differs from installed version source")
        result["torch_build"] = {"cuda": cuda, "git_version": git_version}
    return result


def capture_build_identity() -> dict:
    """Capture complete version strings and narrowly scoped file evidence, read-only."""
    pins = {}
    packages = {name: _capture_package(name, pins) for name in PACKAGES}
    _end_runtime(packages)
    _end_stats(pins)
    result = {"schema": 1, "kind": KIND, "scope": SCOPE,
              "packages": packages, "files": pins, "not_asserted": NOT_ASSERTED.copy()}
    _validate_shape(result)
    return result


def _validate_shape(identity):
    require(type(identity) is dict and set(identity) ==
            {"schema", "kind", "scope", "packages", "files", "not_asserted"} and
            type(identity["schema"]) is int and identity["schema"] == 1 and
            identity["kind"] == KIND and identity["scope"] == SCOPE and
            _equal(identity["not_asserted"], NOT_ASSERTED), "Malformed export build identity")
    packages, pins = identity["packages"], identity["files"]
    require(type(packages) is dict and set(packages) == set(PACKAGES) and type(pins) is dict,
            "Incomplete build identity package inventory")
    files = set()
    for name in PACKAGES:
        item = packages[name]
        keys = {"distribution_version", "module_version", "distribution_root", "module_file",
                "version_file", "metadata_file", "record_file"}
        require(type(item) is dict and set(item) == (keys | {"torch_build"} if name == "torch" else keys)
                and all(type(item[key]) is str and item[key] for key in keys),
                f"Malformed build identity package: {name}")
        root = _canonical(item["distribution_root"])
        require(item["module_file"] == str(root / name / "__init__.py") and
                item["version_file"] == str(root / name /
                    ("__init__.py" if name == "onnxruntime" else "version.py")),
                f"Wrong build identity package paths: {name}")
        metadata = _canonical(item["metadata_file"])
        require(metadata.parent.parent == root and metadata.parent.name.endswith(".dist-info") and
                metadata.name == "METADATA" and item["record_file"] == str(metadata.with_name("RECORD")),
                f"Wrong build identity metadata paths: {name}")
        for key in ("module_file", "version_file", "metadata_file", "record_file"):
            files.add(str(_canonical(item[key])))
        if name == "torch":
            build = item["torch_build"]
            require(type(build) is dict and set(build) == {"cuda", "git_version"} and
                    (build["cuda"] is None or type(build["cuda"]) is str and bool(build["cuda"])) and
                    type(build["git_version"]) is str and bool(build["git_version"]),
                    "Malformed Torch build identity")
    require(set(pins) == files, "Build identity selected-file inventory is incomplete")
    for path, snapshot in pins.items():
        require(type(snapshot) is dict and set(snapshot) == STAT_KEYS | {"sha256"} and
                all(type(snapshot[key]) is int and snapshot[key] >= 0 for key in STAT_KEYS) and
                stat.S_ISREG(snapshot["mode"]) and snapshot["links"] >= 1 and
                type(snapshot["sha256"]) is str and len(snapshot["sha256"]) == 64 and
                all(char in "0123456789abcdef" for char in snapshot["sha256"]),
                f"Malformed installed-file snapshot: {path}")


def identity_files(expected: dict) -> list[Path]:
    _validate_shape(expected)
    return sorted(Path(path) for path in expected["files"])


def validate_build_identity(expected: dict) -> dict:
    """Re-capture and exactly compare every recorded field; return fresh file pins."""
    _validate_shape(expected)
    actual = capture_build_identity()
    require(_equal(actual, expected), "Installed export build identity changed")
    _end_runtime(actual["packages"])
    _end_stats(actual["files"])
    return actual["files"]


def validate_distribution_versions(packages: dict, expected: dict) -> None:
    """Bind genuine distribution provenance separately; no module-version substitution."""
    _validate_shape(expected)
    require(type(packages) is dict and set(packages) == set(PACKAGES) and
            all(type(packages[name]) is str and
                packages[name] == expected["packages"][name]["distribution_version"]
                for name in PACKAGES), "Export distribution-version provenance differs")


def validate_policy_versions(policy: dict, expected: dict, *, provenance_packages=None) -> None:
    """Check raw exporter policy fields against MODULE versions (never normalize).

    This field-role check does not replace validate_build_identity's live check.
    Consumers must use both at their input/output boundaries.
    """
    _validate_shape(expected)
    require(type(policy) is dict and all(type(policy.get(name)) is str and
            policy[name] == expected["packages"][name]["module_version"]
            for name in ("torch", "onnx", "onnxruntime")),
            "Export policy module-version identity differs")
    if "numpy" in policy:
        require(type(policy["numpy"]) is str and
                policy["numpy"] == expected["packages"]["numpy"]["module_version"],
                "Export policy numpy module-version identity differs")
    if provenance_packages is not None:
        validate_distribution_versions(provenance_packages, expected)
