# SpikeIDS version 5：可稽核的四資料集訓練與論文數值管線

本套件是對 2026-09-20 上傳的十個檔案及所追查核心依賴的**新版本重構**。目標硬體為 16 GB RAM、Intel 第 14 代 Core i5、RTX 4060 Ti 16 GB。原始檔、既有結果與正在進行的訓練不會被它修改；請把整個資料夾放進原專案，而不是把這裡的 `models.py` 直接覆蓋原專案的全部模型定義。

**這不是「所有輸入、所有平台、所有未來執行皆正確」的證明。**已執行的測試、未執行的 CUDA／Parquet／ONNX／真實資料／板端驗證，分開記錄在 `audit/TEST_REPORT.json`。CPU 合成資料的準確率不是論文結果。

2026-09-22 08:25 最新狀態：本機完整模型／證據副本phase已限定驗收。
copy56178／fa81b2與獨立全目的端SHA驗證37711／55edf8均實際退出0；
root保留性441728與獨立交接988fcb也退出0。4177 payload files、
18819342389 bytes及原440 checkpoints／440 predictions／84 trees保持一致。
新決策：[LOCAL_COPY_PHASE_ACCEPTANCE.json](../results/v5_evidence_copy_review_20260922_1srUIm/LOCAL_COPY_PHASE_ACCEPTANCE.json)，
細節：[copy phase](../results/v5_evidence_copy_review_20260922_1srUIm/STATUS.md)。
原退出收據內的false驗收旗標保留歷史狀態，不回寫。無已知限定契約blocker，
但不是绝對無bug證明；不代表異地／可移植raw+runtime、投稿、release或硬體驗收。
17 export negatives不變；原來源、副本與auditor皆HOLD，沒有背景自動重試／
刷板／發布。以下07:56及更早均為歷史狀態，不得據此重啟已完成phase。

2026-09-22 07:56 歷史狀態：完整副本session56178實際退出0，保存4177檔、
18819342389 bytes（含440 checkpoints／440 predictions／84 trees）；原檔未搬移。
唯讀預檢58671、獨立啟動核對40cdd3與root事後stat／namespace核對7a26f1均退出0。
**獨立目的端全SHA後審查尚未完成，因此copy phase尚未驗收。**新auditor正在
修正合成反例並覆核，未跑真postreview。副本與原來源HOLD，不重跑成功copy。
新導航：[copy phase](../results/v5_evidence_copy_review_20260922_1srUIm/STATUS.md)。
不是異地備份、完整可移植runtime、release、投稿或硬體驗收；17 negatives不變。

2026-09-22 07:08 歷史狀態：有界「論文產物」驗收器session17280實際退出0，
root postcheck72646亦退出0，4111份原證據承諾保持一致。candidate03內容、
真實PDF四次build/replay、獨立保留性與兩個agent的9頁圖像審查皆已通過；
17個export negatives不變。獨立actual postreview76589也實際退出0；正在建置
新的完整模型／結果copy-only保存工具並對抗審查，尚未執行真正副本。
這不是venue／publication／release／硬體驗收。
最新連結見
[phase index](../results/v5_paper_continued_review_20260922_sQdjK1/STATUS.md)。
舊package/archive不相容此mixed-origin證據鏈，不能直接執行或搬動held路徑。

2026-09-22 05:36 歷史狀態：真實PDF owner session68301退出1，尚未驗收。
四次TeX build已產生一致PDF/text，但adapter在monitor關閉後呼叫舊callback，
觸發closed-file ValueError。既有fake monitor測試漏掉此生命週期問題；正在
additive v2補修與獨立攻擊覆核，通過才用新namespace重跑。失敗輸出全保留，
`ROOT_PDF_ACTUAL_01_FAILED_EXIT.json`／`ROOT_PDF_ACTUAL_01_FAILURE_REVIEW.md`
位於下述review root。3335原input stat退出後一致，未重訓或改統計；不把
可讀PDF誤當phase通過。論文／release／硬體未驗收，詳細限制見handoff。

2026-09-22 05:04 歷史狀態：真實唯讀論文候選稿已產生，renderer session55545
及退出後檢查50461均實際退出0。新稿位於
`results/v5_paper_continued_review_20260922_sQdjK1/candidate_actual_01/paper/`；
該review root的 `ROOT_RENDER_ACTUAL_EXIT.json` 綁定來源、manifest與真實退出。
3318份held ordinary inputs／50來源／8候選檔與保留namespace通過退出後核對。
22作者／57独立lifecycle／36独立科學／3範本整合測試皆通過，先前11個實證
草稿漏洞已修、失敗紀錄保留。原論文／模型／統計未改，尚未TeX/PDF／論文驗收。
目前進行實際內容獨立覆核與PDF failure-retention adapter審查，通過才建置PDF。
硬體／NPU／延遲能耗／release仍未驗收；不要重啟或搬移已pin的既有成果。

2026-09-22 03:43–04:26 歷史狀態：明示的神經 export continuation 已完成全部22項分類，
owner session 98042 實際退出0；FP32 4/11、QDQ 1/11通過，17個negatives保留。
尚未完成後 phase 驗收，不能宣稱全面 INT8／NPU／部署通過。
此前已通過來源綁定的901回歸／370攻擊整合／1真實遙測測試並freeze。
原3項不重匯出，只執行剩餘19項；原數值negatives與工程失敗均保留。
服務 `spikeids-v5-export-cont-20260922-r6-recovery1.service` 受單一 16 GiB／
禁用 swap cgroup 限制。全部 pinned 來源／review／資料／模型不得更改；
03:54 正式 lifecycle 稽核已通過，外層 session 8544 與稽核 child 均實際退出0；
核對3,185份檔案承諾及39次worker執行。04:02全部22項真實數值重播亦通過，
outer session59443／child均實際退出0，93.429秒；原17項negative保留。
這是同一validator的fresh replay，不是第三套獨立算法。04:26 export證據phase
正式驗收完成（publisher session78173退出0，3314份held evidence）；驗收檔是
`results/v5_export_continuation_postreview_20260922_mw1Fyh/acceptance_actual_01/EXPORT_POSTRUN_ACCEPTANCE.json`。
負結果仍為負結果。現在開發新版唯讀論文consumer，尚未寫真候選稿；論文、
板端/NPU/延遲能耗及release尚未放行，不可重啟既有成功或失敗audits。
詳見 handoff 開頭。

2026-09-22 02:40 歷史狀態：神經匯出在第 3 項遭遇 distribution/module
version 欄位混用，已實際退出 1、保留失敗，不可重啟原 plan。前兩項真實
FP32 parity negatives 也保留；剩 19 項尚未執行。正在建置另經審查的明示
接續器，尚未簽核／啟動；不能把開發中的程式或「worker 退出 0」當作驗收。
原 440 neural fits／84 tree fits 已驗收，不受此匯出 consumer 缺陷改寫。
詳情與不可修改的 evidence boundaries 見 `CODEX_HANDOFF.md` 開頭。

2026-09-21 23:52 歷史更新：r6-recovery1 的 440 fits、evaluation、統計與獨立程式
驗證已於 16:19 完成，原始結果在 `results/v5_run_20260921_r6_recovery1/`。
完成後 lifecycle／science 覆核通過；新 tree adapter／controller 的具體缺陷
修復並通過獨立覆核、901 項回歸與 151 項主線攻擊測試（皆實際退出 0）。
固定 84-fit CPU tree baseline 於 23:39 完成、實際退出 0，並於 23:52 通過
完成後科學／資源覆核及驗收。神經 exports、paper、release、硬體仍未放行。
最新狀態以 `CODEX_HANDOFF.md` 開頭為準。
歷史測試報告與 r1/r2/r3/r4 cache/run 仍非本輪正式證據，不可混用。

本輪 tree 驗收紀錄（唯讀，不啟動／重試；服務已結束）：

```shell
jq '{passed, accepted_at, scope, not_accepted}' results/v5_postrun_review_20260921_BtSToy/TREE_PHASE_ACCEPTANCE.json
jq '{observed_return_code, invocation_id}' results/v5_postrun_review_20260921_BtSToy/TREE_OWNER_EXIT_OBSERVATION.json
```

工作目錄 `results/v5_tree_continuation_20260921_r6_1`；模型與結果目錄
`results/v5_tree_20260921_r6_1`。全部 84 模型已另外做完整 test 數值重播，
2,333 舊輸入未變；519 筆資源樣本重播通過。下一階段仍須獨立前置審查，
不自動發布論文或硬體主張。服務被 systemd 回收為 not-found 不代表本輪失敗；
實際退出證據見上方 owner receipt，勿重啟同一 plan。
不要改動 plan 綁定的來源、測試、review、資料及舊神經產物。

## 背景接續的歷史啟動紀錄（2026-09-21 09:02；已於 16:19 完成）

`spikeids-v5-research-20260921-r6-recovery1.service` 已啟動，使用
`tools/continue_v5_research.py` 的明確 recovery plan，保留原 SIGBUS 失敗，
改用 repo 外 NVMe 暫存從頭驗收原兩份 cache。通過後自動執行 60＋66 次
fit-only 選型、正式 440 fits、一次 evaluation、統計與獨立驗證；失敗即停，
沒有自動 retry／reboot resume，也不代表 tree／匯出／論文／硬體已完成。
最終實作完整回歸為 859 PASS；來源、測試、限制見 `CODEX_HANDOFF.md`。
不可在它執行期間照抄下方範例，另啟相同輸出或修改 pinned inputs。

唯讀狀態指令（不是驗收指令，不會啟動訓練）：

```shell
systemctl --user status spikeids-v5-research-20260921-r6-recovery1.service --no-pager
jq -c 'select(has("phase"))' results/v5_research_continuation_20260921_r6_recovery1/continuation.log
TMPDIR=/var/tmp/spikeids-v5-recovery-runtime-20260921-u0aXsd uv run --no-sync --python .venv/bin/python python tools/continue_v5_research.py status --plan results/v5_research_continuation_20260921_r6_recovery1/plan.json
```

## 1. 修正的不是同一份舊結果

本版必須重新產生實驗結果，原因包括：exact-input-group-disjoint unique-pattern 協定、fit-only 類別編碼與 scaler、sqrt-inverse class weights、fixed-final-epoch checkpoint、修正 QCFS shift，以及固定統計檢定家族。不能把新結果寫回舊表格卻稱只是效能優化。

QCFS 的兩個模式明確分開：

- `shifted_v1`：依原作者 ANN 分支的運算順序，`floor(clamp(x/θ,0,1)*L+0.5)/L*θ`，是**量化 ANN**。
- `legacy_floor_v1`：保留專案舊的 `floor(clamp(x/(θ/L+1e-8),0,L))*θ/L`，只供另立協定的診斷；不能把舊 checkpoint 偷換成新公式。

L=4 的量化 ANN 具有五個輸出值，包括零。標準單步、每神經元最多一個 spike 的 IF 模型只有零或閾值幅度，並不普遍等於上述五值 ANN。`snn_analysis.py` 實際模擬時間、膜電位、reset 與讀出，再量測差異；它不宣稱「有 floor 就是 T=1 SNN」。

## 2. 建議的目錄與環境

```text
SpikeIDS-MCU/
├── .venv/
├── data/
├── src/                    # 原專案，保留不動
├── scripts/                # 原專案，保留不動
└── spikeids_v5/             # 本套件全部檔案放在這裡
```

以下指令從原專案根目錄執行。採用你的既有 `uv` 環境，不自動升級 PyTorch 或替換 CUDA build：

```shell
uv run --no-sync python -c "import torch; print(torch.__version__); print(torch.version.cuda); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NO CUDA')"
```

正式 GPU 執行必須看到 CUDA 可用和正確顯示卡。缺套件時在**指定的本機環境**使用 `uv pip`，不要把本交付 CPU 測試環境的 torch build 複製過去。執行依賴是 torch、numpy、pandas、scipy、scikit-learn；Parquet 需要 pyarrow；ONNX/QDQ 輸出需要 onnx、onnxruntime；測試另外需要 pytest、statsmodels。

本次正式 resource gate 要求 Linux cgroup v2；本機以 systemd user scope 啟動。原生 Windows 或其他未驗證環境不能沿用這份硬體驗收結論；可攜鎖定分支仍不等於已通過正式流程。

## 3. 原始資料規格與前處理

NSL 使用 `data/KDDTrain+.txt`、`data/KDDTest+.txt`；43 欄原始檔，包含 41 features、label、difficulty。UNSW 使用 `UNSW_NB15_training-set.parquet`／`testing-set.parquet`，或對應 CSV；依檔案角色分割，不依「哪個檔比較大」偷偷交換。

CICIDS 正式來源使用八個固定命名、逐檔 pin 的原始 MachineLearningCSV；Parquet 無法證明 physical duplicate-column identity，因此此路徑不接受 CIC Parquet。IoT 使用 `data/iot23/iot23_combined.parquet` 或同名 CSV。資料應仍有原始 categorical tokens，不能拿已經全資料擬合編碼的輸出假裝 raw。其他路徑可用 `--source-spec-dir`，其中每個資料集一份 JSON：

```json
{
  "dataset": "unsw",
  "provenance_note": "說明下載來源、版本、是否已做上游轉換，以及仍待確認的部分",
  "files": [
    {"path": "UNSW_NB15_training-set.parquet", "role": "train", "bytes": 123, "sha256": "REPLACE_WITH_REAL_SHA256"},
    {"path": "UNSW_NB15_testing-set.parquet", "role": "test", "bytes": 456, "sha256": "REPLACE_WITH_REAL_SHA256"}
  ]
}
```

CIC／IoT 的角色為 `combined`；上方僅示意欄位，不是可用 source spec。正式流程使用 `audit/source_specs/` 內逐檔 pin 的真實大小與 SHA-256；缺 shard 或未知 label 均停止。

```shell
uv run --no-sync python spikeids_v5/audit_data.py --data-dir data --source-spec-dir spikeids_v5/audit/source_specs --output-dir results/v5_corrected_audit
uv run --no-sync python spikeids_v5/suite.py prepare --data-dir data --source-spec-dir spikeids_v5/audit/source_specs --raw-audit results/v5_corrected_audit/data_audit.json --cache-root results/v5_corrected_cache_a
uv run --no-sync python spikeids_v5/suite.py prepare --data-dir data --source-spec-dir spikeids_v5/audit/source_specs --raw-audit results/v5_corrected_audit/data_audit.json --cache-root results/v5_corrected_cache_b
uv run --no-sync python tools/verify_v5_data.py --raw-audit results/v5_corrected_audit/data_audit.json --iot-provenance spikeids_v5/audit/iot23_provenance.json --cache-root-a results/v5_corrected_cache_a --cache-root-b results/v5_corrected_cache_b --output results/v5_corrected_audit/data_acceptance.json
```

上述是另立全新流程的範例目錄，不是重跑目前 r6-recovery1 的指令；該輪 real-data acceptance 已通過並保留完整證據。raw audit 成功本身不等於 data acceptance 成功。準備先建立 immutable raw identity、依 exact X grouping 分割，再迭代合併 final-FP32 collision components；只在 raw-unique fit population 擬合 vocabulary/scaler，固定點後以 final unique `(X,label)` 作訓練與評估 population。這兩個 population 不可混稱，詳細算法見 `audit/DATA_PROTOCOL_GROUP_DISJOINT_20260921.md`。預設 chunksize=65536，納入指紋。載入已驗證 cache 使用私有 ndarray，避免 mmap 後檔案改動改變訓練張量。

NSL／UNSW 保留官方 train/test 角色；training 內以 exact-X groups 切 validation，與 training component 重疊的 official-test patterns 排除並保留完整 accounting。CIC／IoT 目標為約 64/16/20，group constraints 下不保證精確比例。所有模型與 seeds 共用同一 cache；class weights 只由 final model-fit labels 計算。

CIC 保留固定 schema 中的常數欄位，不使用全資料的變異數決定特徵集合，因此不保證仍是舊表格的「69 維」。欄位數與順序以產生的 metadata 為準。不再依 test 的負值範圍決定是否 clipping。非 NSL 的已宣告 NaN／Inf／缺值轉零，未知數字文字直接報错；此政策會改變部分舊結果，已列入指紋。

CIC 原始實體欄位中的重複 `Fwd Header Length` 必須逐列相同，才移除第二份；另排除 destination port，現行 schema 對應 76 個 inputs，最後仍須核對 accepted metadata。CIC 的十五類結果只作 fixed-pattern descriptive benchmark；稀有類別的實際 fit/validation/test supports 必須完整揭露，不能用 dry simulation 數字代替本輪資料驗收。增加 training seeds 只增加 optimization variability 的觀測，不增加稀有攻擊樣本；不宣稱可靠 Heartbleed、SQL-injection 或 Infiltration 偵測。固定分割缺任何宣告類別就停止，不挑另一個 fold 或事後合併類別。

IoT 保留原專案五群映射以便比較，但 metadata 明確註記歷史 `C&C` 群包含 `Attack`、`FileDownload` 等項，不能稱為純 C&C ground truth。上游預處理是否已洩漏，不能靠重新 scaler 就洗掉。

**Exact model-input disjointness 不等於 capture/device/time holdout。**本協定估計 unique labelled patterns 的表現，不是 traffic-frequency accuracy，也不建立未見装置／場景／未來時間泛化。`upstream_preprocessing_verified` 仍為 false；上游已做的探索或轉換無法靠重新 scaler 消除。

## 4. 效能配置：量測，而不是相信 workers=2 或固定倍率

每一個訓練 job 仍是隔離的 GPU 程序；suite 可把互不依賴的 dataset/model jobs 做有界並行，worker 數會凍結在 plan，且必須先以獨立重跑的 training/scientific digest 驗收。預設使用 FP32、關閉 AMP/TF32、嚴格 deterministic algorithms。每個 epoch 產生一次固定 CPU RNG permutation、一次重排 GPU resident arrays，batch 使用連續 slices；validation logits 預配置，沒有逐 class `.item()` 同步。QCFS 固定 L 不在 forward 每次取回 CPU。

預設保守 optimizer 為 `single`。本次正式配置的選擇使用已獨立審查的
`tools/qualify_v5_performance.py`，**必須先有四資料集雙 cache acceptance**：

```shell
systemd-run --user --scope --unit=spikeids-v5-profiles -p MemoryMax=16G -p MemorySwapMax=0 uv run --no-sync python tools/qualify_v5_performance.py profiles --cache-root results/v5_corrected_cache_a --raw-audit results/v5_corrected_audit/data_audit.json --data-acceptance results/v5_corrected_audit/data_acceptance.json --work-dir results/v5_profiles
systemd-run --user --scope --unit=spikeids-v5-workers -p MemoryMax=16G -p MemorySwapMax=0 uv run --no-sync python tools/qualify_v5_performance.py workers --profile-qualification results/v5_profiles --work-dir results/v5_workers
uv run --no-sync python tools/qualify_v5_performance.py verify --work-dir results/v5_workers
```

Profiles 固定 single／foreach／fused × 1／4 threads，CIC 的 ReLU/QCFS/CNN
與 IoT 的 ReLU/QCFS，各 seed 0、10 epochs、兩次獨立重跑且反向候選順序，
共 60 fits；同 profile 完整 training digest 必須一致。Workers 固定 1／4／8，
全部 11 jobs 各做 primary/replica，共 66 fits，跨 worker 候選亦須 digest
相同。全程 fit-only，不開 test，按完整事件與 raw resource telemetry 核對的
wall time 排名；不依 accuracy 選擇。任何 candidate subprocess、重現或資源
失敗都使**整次 qualification 失敗**，不排除失敗候選後改選剩餘者。
Worker runtime 必須與所選 parent profile 的環境完全相同。

舊 `benchmark_profiles.py` 可留作獨立工程診斷；其報告缺少本次完整固定矩陣
與 resource/event 驗收，不能代替上述 qualification。工具測試通過也不代表
已測得這台機器在新資料協定上的最佳配置。

短 benchmark 的最快候選不等於所有 seeds／80 epochs 或所有資料集的最佳。GPU 溫度、時脈、其他程式與作業系統排程仍影響時間；時間值不列入科學結果的逐位一致 hash。原 README 的「4–5 小時」「固定 5–15% 開銷」「workers=2 飽和」不作保證。2026-09-20 舊 workload 的 4/6/8-worker smoke 及其時間、RSS、digest 比較僅屬歷史工程記錄，不是新資料協定的 profile 驗收，也不能據此決定本次正式 worker 數。新 accepted caches 的 optimizer、threads、workers 必須依速度、獨立重現與資源證據重新評估後凍結，不按 validation/test 分數挑設定。

正式 workload 使用 fresh cgroup v2 scope：MemoryMax=16G、MemorySwapMax=0，另有 14 GiB process-tree RSS 與 GPU 取樣限制；記錄 kernel memory peak/OOM 和 raw telemetry，已知異常不得進下一階段。這不等於在實體 16 GB 整機上驗收，也不證明取樣間不存在 GPU 峰值。GPU resident 模式保留 2 GiB reserve；不足就停止，不自動更改 batch、precision 或訓練預算。

每次測試保存 logits/probabilities 的磁碟成本約為 `n_test × (8 × class_count + 16)` bytes，再乘模型數、seeds 和兩次驗證；這尚未包含 checkpoint/cache。四資料集、20 seeds 的完整證據可能佔多 GB，請先按實際 metadata 預留磁碟。不要為省空間把 float32 logits 改成 float16 卻保留相同協定名稱。

## 5. 凍結正式實驗，之後不改 code／資料／版本

以下 `fused / 4 threads / 8 workers` 只是**須由新協定本機 benchmark 驗收後**才能採用的示例，不表示這個組合已通過本輪 profile；正式 freeze 前應替換成實際驗收的配置。預設保守候選是 single／1 worker。

```shell
uv run --no-sync python spikeids_v5/suite.py freeze --cache-root results/v5_corrected_cache_a --raw-audit results/v5_corrected_audit/data_audit.json --data-acceptance results/v5_corrected_audit/data_acceptance.json --run-dir results/v5_run --device cuda --optimizer fused --threads 4 --workers 8
systemd-run --user --scope --unit=spikeids-v5-formal -p MemoryMax=16G -p MemorySwapMax=0 uv run --no-sync python spikeids_v5/suite.py run --run-dir results/v5_run
```

固定規格為 20 seeds、11 組 dataset×model：四個資料集各 ReLU/QCFS，加上 NSL、UNSW、CIC 的 TinyCNN。IoT 是 40 epochs、batch1024，其餘 80 epochs、batch512。使用 fixed-final-epoch checkpoint，validation 每十個 epoch 與最後一次僅作診斷，不選模型。BatchNorm 的 singleton tail 合併上一批，不丟樣本。上述 optimizer/workers 須以新協定重新 benchmark，不能把旧結果當新協定驗收。

全域順序是 **所有11組先 fit → 另一套獨立初始化/訓練完整重跑 → 所有對照一致 → 才對 test 評估兩份模型 → logits/機率/預測/metrics 一致**。正式 20 seeds 是 220 次模型訓練，雙重驗證合計 440 次，這是明確的驗收成本，沒有把只重讀同一 checkpoint 當成重訓。

低階 fit 支援 exact-identity resume；所有 protocol/source/data/environment 必須相同。正式 resource acceptance 目前要求完整一次 `run` 或各一次 fit/verify/evaluate 的成功 traces，失敗／中斷 trace 不可刪除後宣稱乾淨成功。正式 test exposure 不可重設。checkpoint 每十個 epochs／validation／最後保存；不能改 epochs 後沿用舊 optimizer/cosine state。

正式結果是 `results/v5_run/results/`；`replicas/` 是核對組。若途中失敗，所有下游統計／finalize 都停止。不得看完 test 後從兩份選較高分者。`verification_fit.json` 與 `verification_evaluate.json` 必須成功，且它們的 hashes 必須仍對得上實際 checkpoint、predictions 和 plan。

### 接線 smoke test

```shell
uv run --no-sync python spikeids_v5/suite.py freeze --cache-root results/v5_corrected_cache_a --raw-audit results/v5_corrected_audit/data_audit.json --data-acceptance results/v5_corrected_audit/data_acceptance.json --run-dir results/v5_smoke --device cuda --optimizer fused --threads 4 --workers 8 --seeds 0 1 --smoke-epochs 2 --bounded-memory
systemd-run --user --scope --unit=spikeids-v5-smoke -p MemoryMax=16G -p MemorySwapMax=0 uv run --no-sync python spikeids_v5/suite.py run --run-dir results/v5_smoke
```

smoke 協定明確標為 `smoke_only`，不能通過 20-seed 論文 finalization。驗收看控制流程與結果重現，不要求 OA≈78 或 macro-F1≈58。

## 6. 統計與論文輸出

**2026-09-21 post-run review 警告：下列為歷史範例，不可直接對已完成的
r6-recovery1 run 重跑。**原 stats/equivalence/finalize CLI 會重寫已綁定
SHA/stat 的統計產物。paper phase 必須先完成只讀已驗統計的 consumer
修正與審查；目前尚未放行。即使新 bytes 相同也不能替換原驗收檔案。

```shell
uv run --no-sync python spikeids_v5/run_globecom_stats.py --run-dir results/v5_run
uv run --no-sync python spikeids_v5/run_v4_equivalence.py --run-dir results/v5_run
uv run --no-sync python tools/run_v5_exports.py --run-dir results/v5_run --output-root results/v5_export --paper-dir paper/globecom
uv run --no-sync python spikeids_v5/finalize_all_det.py --run-dir results/v5_run --tree-run-dir results/v5_tree_run --export-root results/v5_export --paper-dir paper/globecom
```

同一份結果會先從保存的 test labels/predictions/probabilities 重算 metrics、比對 checkpoint、核對實際 seed ID 與 split/preprocessor identity，而不是信任 aggregate。列數相同不等於樣本相同；相同 epochs 不等於相同 FLOPs／容量／硬體耗能。

所有差值統一 **ReLU − comparator，percentage points**。difference 檢定家族為七種比較×OA/MF1＝14；equivalence 家族為四資料集×OA/MF1＝8。兩個家族各自做 Holm；這是兩個預先區分的研究問題，**不是對兩者合併22個主張宣稱一次總體 FWER=0.05**。需要合併家族時，必須在凍結前設計另一協定，不能看完結果才切換。

TOST 使用 `(1−2α)` 的個別 t interval，並以 `max(p_lower,p_upper)` 作為 IUT p 值；Holm 後的決策不等於每個原始90% CI都是 simultaneous CI。δ 預設1pp在本次 freeze 記錄，不冒稱它已在舊投稿中預先註冊。`delta_min_infimum` 是未校正的敏感度診斷，嚴格大於該界線才通過，不是拿來看完資料改 margin 的工具。

signed-rank 對 ties/zeros 使用整數動態規劃的 conditional sign-flip 分布，差值的小數12位取捨規則固定。它的 exact 指條件分布的計算，不代表獨立性、對稱性等前提已被證明。參數式 TOST 與 signed-rank TOST 並非同一 estimand，不依 Shapiro p 值自動換主檢定。零觀察變異回報參數式推論未定義，不把非零常數差值的 d_z 寫成零或把數值退化冒充無限信心。

Signed-rank difference 的 estimand 是 symmetric paired-difference location／pseudomedian；mean difference 只是描述量，不能把該 p 值稱為平均差的檢定。Primary paired-t TOST 檢定 mean paired difference；另外八項 signed-rank TOST 是 location robustness family，獨立 Holm 調整。八項 primary／robustness adjusted p、decisions 與 discordance 必須全數報告，不依結果選擇是否揭露；三個 family 不合稱一次總體 FWER 保證。

`stats_tests.py` 另外提供正態差值假設下、對樣本變異分布做 deterministic quadrature 的 power 與 bounded/bisection required-n。它不是 distribution-free power，也不是 observed power 證明。預設報告不自動用看過的差值選下一批 seeds。

**顯著差異可以和 frozen sensitivity margin 內的 numerical equivalence 並存；difference 不顯著也不等於等價。**δ 是本輪凍結的數值敏感度界線，不是已有獨立證據支持的 practical-importance threshold。刪除原 README 預先指定的「IoT一定QCFS較好」「所有四個都等價」結論，依新的報告描述。

### 安全的 LaTeX 接線

finalize 只產生 `result_macros_v5.tex` 與 provenance，不覆寫 `main.tex` 或舊手工 macro。正式 export matrix 另產生 `export_macros_v5.tex` 與 provenance；兩者都必須由正文以 literal `\\input` 納入。Codex 必須把相關引用改成 `vFive...` 新 macro，不能只追加新 macro 又讓正文繼續吃舊檔。

```shell
uv run --no-sync python spikeids_v5/check_paper_consistency.py --run-dir results/v5_run --tree-run-dir results/v5_tree_run --export-root results/v5_export --paper-dir paper/globecom --strict
uv run --no-sync python spikeids_v5/finalize_all_det.py --run-dir results/v5_run --tree-run-dir results/v5_tree_run --export-root results/v5_export --paper-dir paper/globecom --build --build-output results/v5_paper_build
```

任何來源缺失、macro缺失、hash不符、檢查失敗都停止；shell使用 `set -euo pipefail`，沒有吞掉失敗的 `|| echo`。僅在 strict 檢查通過後才允許 `latexmk`。小 p 值不顯示成「0.000」。per-class recall 本來就是百分比，不再乘100。

checker 的範圍是受管理的數值來源與保守的文字模式掃描，不能證明整篇自然語言、理論、所有輔助表格或能耗主張正確。報告明確寫 `natural_language_scientific_claims_proven: false`。沒有稿件完整內容與板端實驗，不能宣稱整篇論文已通過。

本輪 `main.tex` 的方法文字同步不是 paper acceptance：精確 frozen protocol block 仍須等已驗證 neural/tree/export plans 與 accepted metadata 齊備後產生，不能預先假造；正式 result/export macros、完整統計、strict checker 與雙 build/replay 證據也不能由這次文字修正代替。

舊格式消費者需要 view 時，可在這個**新 run namespace**使用 `assemble_nsl_legacy.py`／`assemble_cnn_legacy.py --run-dir ...`；產物在 `legacy/`，保留來源指紋，沒有把舊 JSON 改名洗成新證據。

## 7. L-sweep、轉換、匯出與板端

L-sweep、IF temporal simulation 與 frozen-ANN layerwise 分析均為 optional separate diagnostics，不在本文正式 440 neural fits＋84 tree fits＋22 neural export attempts 矩陣內，也不表示已完成本文 ablations。兩個 reference datasets 的 RF ONNX 驗證另行保留，是兩個額外 export artifacts，不是額外 fits。

舊 README 與 L-sweep 程式的 L集合互相矛盾，因此新程式要求明確指定 `--levels`：

```shell
uv run --no-sync python spikeids_v5/experiment_qcfs_lsweep.py --dataset nslkdd --cache results/v5_cache/nslkdd --work-dir results/v5_lsweep --levels 1 2 4 8 16 --stage fit
uv run --no-sync python spikeids_v5/experiment_qcfs_lsweep.py --dataset nslkdd --cache results/v5_cache/nslkdd --work-dir results/v5_lsweep --levels 1 2 4 8 16 --stage evaluate
```

每個 L 都用同一份fit-only cache、80epochs、固定seeds，先全部fit兩次並核對，才評估test。這仍是次要診斷，不自動使舊 L=4 選擇成為事前決策。

實際 IF 模擬與新的 checkpoint-bound frozen-ANN layerwise 檢查：

```shell
uv run --no-sync python spikeids_v5/snn_analysis.py --run-dir results/v5_run --dataset nslkdd --output results/v5_run/if_validation.json
uv run --no-sync python spikeids_v5/layerwise_analysis.py --run-dir results/v5_run --dataset unsw --model qcfs --output results/v5_run/frozen_layerwise.json
```

這裡的 layerwise 是 ANN→frozen ANN，不是完整 INT8中間張量或SNN等價證明；不會用其結果冒充舊圖。

FP32 ONNX／QDQ：

```shell
uv run --no-sync python tools/run_v5_exports.py --run-dir results/v5_run --output-root results/v5_export --paper-dir paper/globecom
```

正式 export runner 在第一次 attempt 前凍結 22-attempt plan，並在 neural run 登記唯一 export namespace；須先有真實 prior-exposure disclosure，詳見 `EXPORT_PROTOCOL.md`。全部閾值、validation sampling、fit-only calibration 與 QDQ recipe 均固定，不能看結果再調整。低階 exporter 不代替這個正式 gate。數值失敗必須精確重現；OOM、signal、storage error 不能算 QDQ 科學失敗。

原 quantize_qcfs 把 `quant_format` 誤設成 `QuantType.QInt8`；新路徑是 `QuantFormat.QDQ`，type另設QInt8。部分 linear/conv量化的QDQ圖不等於「全INT8」「全部NPU」；算子清單不能代替 vendor mapping report。輸出每次使用新資料夾，不再讓不同資料集共用 `ids_qcfs_L4.onnx` 而覆蓋彼此。

原 N6 kernel 有代表性固定量化參數與人工bias，不能把該微基準直接視為新訓練模型的部署。`deployment_gate.py` 是**離線證據核對器**，不會刷板、halt MCU、改時脈。它要求實際binary、編譯報告、clock原始依據、timing log、相同input vectors及board logits。即使文件一致，也明確不冒稱已做物理量測真實性 attestation；未提供電流/電壓量測就不稱能耗已測。

## 8. 給 Codex 的接手入口

先讀 `CODEX_HANDOFF.md`，再讀 `audit/REVIEW.md` 和實際測試報告。不要執行原 README 的 `train_fast` 範例；不要改正在執行中的 `experiment_multiseed(1).py` 來破壞其 resume。需要修改本套件來源時先停止啟動新的job，另建新版本/run目錄；不改已凍結的來源hash讓它勉強續跑。

在套件目錄執行測試：

```shell
uv run --no-sync python -m pytest tests -q
```

`tests` 使用明確標註的合成資料，不能把測試通過理解成原始資料、GPU、板端、或全論文結果已通過。
`audit/TEST_REPORT.json` 是原始交付的歷史紀錄，不是目前候選版本的驗收。
最新狀態以 `CODEX_HANDOFF.md`、`audit/ADVERSARIAL_REVIEW_20260921.md` 所連結
的 source-bound 測試、失敗紀錄與實際資料／資源 gates 為準。
