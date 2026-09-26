"""Independent bounded offline controls. No ARM compiler, model or hardware.

ELF bytes and tiny files are real. candidate fixtures replace only the fixed
historical receipt hashes/paths; run entry tests use opaque candidate_pins and
fake child processes, not the actual 1024-row evidence or a fake full build.
"""
import importlib.util
import json
from pathlib import Path
import struct

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("independent_sram_build", HERE / "build.py")
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)


def toy_elf():
    raw = bytearray(4096)
    raw[:52] = struct.pack("<16sHHIIIIIHHHHHH", b"\x7fELF\x01\x01\x01" + b"\0" * 9,
                          2, 40, 1, 0x34064101, 52, 0, 0, 52, 32, 4, 40, 0, 0)
    rows = [(1, 256, 0x34064000, 0x34064000, 512, 512, 5, 32),
            (1, 768, 0x34064200, 0x34064200, 16, 128, 6, 32),
            (1, 0, 0x340F0000, 0x340F0000, 0, 0x8000, 6, 32),
            (1, 0, 0x340F8000, 0x340F8000, 0, 512, 6, 32)]
    for i, row in enumerate(rows):
        struct.pack_into("<IIIIIIII", raw, 52 + 32 * i, *row)
    struct.pack_into("<II", raw, 256, 0x340F8000, 0x34064101)
    return raw


def test_valid_elf32_reserved_layout():
    r = b.elf_layout(toy_elf())
    assert r["reserved_pools"] == [[0x34200000, 0x34240000], [0x34240000, 0x34244000]]
    assert [s["memory_bytes"] for s in r["segments"]] == [512, 128, 32768, 512]


@pytest.mark.parametrize("offset,fmt,value", [
    (0, "B", 0), (4, "B", 2), (18, "H", 62), (42, "H", 56),
    (44, "H", 3), (24, "I", 0x34064100), (256, "I", 0x34185000),
    (52 + 12, "I", 0x34064004), (52 + 16, "I", 4096),
    (84 + 8, "I", 0x3423FFF0), (84 + 8, "I", 0x34240000),
    (116 + 20, "I", 0x4000), (148 + 20, "I", 256),
])
def test_bad_elf_layout_rejected(offset, fmt, value):
    raw = toy_elf()
    struct.pack_into("<" + fmt, raw, offset, value)
    if offset == 84 + 8:
        struct.pack_into("<I", raw, offset + 4, value)
    with pytest.raises((RuntimeError, struct.error)):
        b.elf_layout(raw)


def test_mailbox_abi_and_fixed_model():
    a = json.loads((HERE / "ABI.json").read_bytes())
    assert (a["magic"], a["deployment_tag"]) == (0x53364E36, 0x534D3031)
    assert (a["struct_bytes"], a["input_word_offset"], a["output_word_offset"]) == (512, 128, 320)
    assert (a["input_count"], a["output_count"]) == (41, 5)
    assert (a["weights_address"], a["weights_reserved_bytes"], a["weights_file_bytes"]) == (0x34200000, 262144, 145457)
    assert (a["activation_address"], a["activation_reserved_bytes"]) == (0x34240000, 16384)
    main = (HERE / "main.c").read_text()
    assert "22dc7979340c34af613840a8cef70bc07f469ae2143925660cf3312f36475e2d" in main
    assert "cb5b641344e146a9a1b3d439953c9c3b078c706f5fa55eee40b5339ed2cb65ec" in main
    assert "memcpy(output_copy,out[0],20)" in main
    assert "i<5; ++i) g_mailbox.output_words[i]=output_copy[i]" in main


def test_request_checks_and_final_commit_source_contract():
    main = (HERE / "main.c").read_text()
    fn = main.split("static int request_unchanged", 1)[1].split("int main", 1)[0]
    for field in ("request_sequence", "row_id", "platform_ack", "command", "input_count", "input_words"):
        assert "g_mailbox." + field in fn
    assert "i<41" in fn
    assert main.count("if (!request_unchanged(seq,row))") == 2
    assert "g_mailbox.state=S6_DONE; __DMB(); g_mailbox.response_sequence=seq; __DSB();" in main
    assert main.index("while (g_mailbox.platform_ack") < main.index("stai_nsl_qcfs_seed0_init")
    assert "g_mailbox.platform_ack =" not in main


def test_startup_and_full_pool_reservation_source_contract():
    start = (HERE / "startup.c").read_text()
    asm = start.split('void Reset_Handler(void)\n{', 1)[1]
    assert asm.index("cpsid i") < asm.index("msr msp") < asm.index("0xE000ED88") < asm.index("b reset_c")
    assert "0x00F00000" in asm and "dsb\\n isb\\n b reset_c" in asm
    linker = (HERE / "linker.ld").read_text()
    for value in ("0x34200000", "0x34240000", "0x34244000", "262144", "16384"):
        assert value in linker
    assert "0x710" not in linker.lower() and "0x342e" not in linker.lower()
    assert not any("USE_NPU_CACHE" in d for d in b.DEFS)
    assert "-DLL_ATON_SW_FALLBACK=1" in b.DEFS
    assert all(v is False for v in b.LIMITS.values())


def test_pin_rejects_mutate_restore_and_symlink(tmp_path):
    p = tmp_path / "source"; p.write_bytes(b"old")
    held = b.pin(p)
    p.write_bytes(b"new"); p.write_bytes(b"old")
    with pytest.raises(RuntimeError): b.bookend({str(p): held})
    link = tmp_path / "alias"; link.symlink_to(p)
    with pytest.raises(RuntimeError): b.pin(link)


@pytest.fixture
def candidate(tmp_path, monkeypatch):
    review = tmp_path / "review"; review.mkdir()
    vendor = tmp_path / "vendor"; vendor.mkdir()
    failure = vendor / "FAILED.json"; failure.write_bytes(b'{"failed":true}\n')
    translate = {"st_dev":"device", "st_ino":"inode", "st_mode":"mode", "st_nlink":"links",
                 "st_size":"size", "st_mtime_ns":"mtime_ns", "st_ctime_ns":"ctime_ns", "sha256":"sha256"}
    record = {translate[k]: v for k, v in b.pin(failure).items()}
    r = {"saved_descriptor_review_passed":True, "original_wrapper_return_code":1,
         "original_compiler_return_code":0, "original_failure_preserved":True,
         "held_inputs_and_reviewer_sources":{},
         "retained_failure_inventory":{"files":{"FAILED.json":record},"directories":[]}}
    values = {"SAVED_REVIEW_ACTUAL_01.json":r, "SAVED_REVIEW_ACTUAL_01_EXIT.json":{"actual_return_code":0},
              "ACTUAL_01_REVIEW_SNAPSHOT.json":{}}
    hashes = {}
    for n, value in values.items():
        p = review / n; p.write_bytes(b.encoded(value)); hashes[n] = b.pin(p)["sha256"]
    old = tmp_path / "old.json"; old.write_bytes(b.encoded({"input_pins":{}}))
    for name, value in {"REVIEW":review,"VENDOR":vendor,"REVIEW_HASHES":hashes,
                        "OLD_BUILD_RESULT":old,"OLD_BUILD_RESULT_SHA":b.pin(old)["sha256"]}.items():
        monkeypatch.setattr(b, name, value)
    return vendor, review


def test_candidate_original_failure_and_pins(candidate):
    vendor, _ = candidate
    pins = b.candidate_pins()
    assert str(vendor / "FAILED.json") in pins and not (vendor / "RESULT.json").exists()


def test_candidate_extra_empty_directory(candidate):
    vendor, _ = candidate; (vendor / "extra").mkdir()
    with pytest.raises(RuntimeError): b.candidate_pins()


def test_candidate_late_namespace_after_hashes(candidate, monkeypatch):
    vendor, _ = candidate
    original = b.bookend
    def late(pins):
        original(pins)
        (vendor / "late_empty").mkdir(exist_ok=True)
    monkeypatch.setattr(b, "bookend", late)
    with pytest.raises(RuntimeError): b.candidate_pins()


@pytest.fixture
def entry(tmp_path, monkeypatch):
    work = tmp_path / "adapter"; work.mkdir()
    paths = {"HERE":work,"ST":tmp_path/"st","TC":tmp_path/"tc","TP":tmp_path/"tp","GEN":tmp_path/"gen"}
    for key, value in paths.items(): monkeypatch.setattr(b, key, value)
    review = tmp_path / "entry_review"; review.mkdir()
    (review / "SAVED_REVIEW_ACTUAL_01.json").write_bytes(b.encoded({
        "retained_failure_inventory": {"files": {}, "directories": []}}))
    monkeypatch.setattr(b, "REVIEW", review)
    for n in ("build.py","main.c","startup.c","syscalls.c","mailbox.h","linker.ld","README.md","ABI.json"):
        (work/n).write_bytes(b"tiny frozen source\n")
    leaves = [paths["ST"]/"Npu/ll_aton"/(n+".c") for n in
              ("ll_aton","ll_aton_cipher","ll_aton_debug","ll_aton_dbgtrc","ll_aton_lib","ll_aton_lib_sw_operators",
               "ll_aton_runtime","ll_aton_util","ll_sw_float","ll_sw_integer","ll_aton_stai_internal")]
    leaves += [paths["ST"]/"Npu/Devices/STM32N6xx"/(n+".c") for n in ("mcu_cache","npu_cache")]
    leaves += [paths["TP"]/"stm32n6xx-hal-driver/Src"/(n+".c") for n in
               ("stm32n6xx_hal","stm32n6xx_hal_rcc","stm32n6xx_hal_rcc_ex","stm32n6xx_hal_cacheaxi","stm32n6xx_hal_cortex")]
    leaves += [paths["GEN"]/n for n in ("nsl_qcfs_seed0.c","stai_nsl_qcfs_seed0.c")]
    leaves += [paths["ST"]/"Lib/GCC/ARMCortexM55/NetworkRuntime1100_CM55_GCC.a"]
    leaves += [paths["TC"]/"bin"/("arm-none-eabi-"+n) for n in ("gcc","size","readelf","nm","objcopy","objdump")]
    for p in leaves: p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b"fake tool/source, never executed\n")
    monkeypatch.setattr(b, "candidate_pins", lambda: {})
    return work, paths


def test_existing_output_not_adopted(entry):
    work, _ = entry; out=work/"build"; out.mkdir(); (out/"sentinel").write_bytes(b"keep")
    with pytest.raises(RuntimeError): b.run(out)
    assert list(out.iterdir()) == [out/"sentinel"]


def test_failed_child_preserves_raw_exit_and_no_result(entry, monkeypatch):
    work, _ = entry
    class Child:
        pid=123456789
        returncode=23
        def __init__(self, *args, **kwargs):
            kwargs["stdout"].write(b"partial stdout\n"); kwargs["stderr"].write(b"failure stderr\n")
        def wait(self, timeout): return 23
        def poll(self): return 23
    monkeypatch.setattr(b.subprocess, "Popen", Child)
    out=work/"build"
    with pytest.raises(RuntimeError): b.run(out)
    assert json.loads((out/"version.json").read_bytes())["actual_return_code"] == 23
    assert (out/"FAILED.json").is_file() and not (out/"RESULT.json").exists()
    assert (out/"version.stdout").read_bytes() == b"partial stdout\n"


def test_late_parent_rebind_must_not_create_foreign_directory(entry, monkeypatch, tmp_path):
    work, paths=entry; foreign=tmp_path/"foreign"; foreign.mkdir()
    original=b.pin
    def late(path):
        result=original(path)
        if Path(path)==paths["TC"]/"bin/arm-none-eabi-objdump":
            work.rename(tmp_path/"original_adapter"); work.symlink_to(foreign, target_is_directory=True)
        return result
    monkeypatch.setattr(b,"pin",late)
    with pytest.raises(RuntimeError): b.run(work/"build")
    assert list(foreign.iterdir()) == [], "Rejected publication must not create a directory through rebound parent"


def test_original_candidate_source_pin_not_replaced_by_fresh_capture(entry, monkeypatch):
    work, paths = entry
    generated = paths["GEN"] / "nsl_qcfs_seed0.c"
    original = b.pin(generated)
    def held_candidate():
        generated.write_bytes(b"changed after original candidate commitment\n")
        return {str(generated): original}
    monkeypatch.setattr(b, "candidate_pins", held_candidate)
    called = []
    class Child:
        pid=123456789
        returncode=23
        def __init__(self, *args, **kwargs): called.append(True)
        def wait(self, timeout): return 23
        def poll(self): return 23
    monkeypatch.setattr(b.subprocess, "Popen", Child)
    with pytest.raises(RuntimeError): b.run(work/"build")
    assert not called, "Changed original generated input was fresh-adopted and used to start compiler"
