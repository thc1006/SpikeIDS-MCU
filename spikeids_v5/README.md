# SpikeIDS version 5：可稽核的四資料集訓練與論文數值管線

本套件是對 2026-09-20 上傳的十個檔案及所追查核心依賴的**新版本重構**。目標硬體為 16 GB RAM、Intel 第 14 代 Core i5、RTX 4060 Ti 16 GB。原始檔、既有結果與正在進行的訓練不會被它修改；請把整個資料夾放進原專案，而不是把這裡的 `models.py` 直接覆蓋原專案的全部模型定義。

**這不是「所有輸入、所有平台、所有未來執行皆正確」的證明。**已執行的測試、未執行的 CUDA／Parquet／ONNX／真實資料／板端驗證，分開記錄在 `audit/TEST_REPORT.json`。CPU 合成資料的準確率不是論文結果。

## 1. 修正的不是同一份舊結果

本版必須重新產生實驗結果，原因包括：fit-only 類別編碼、fit-only scaler、固定 validation 選模型、修正 QCFS 的 shift，以及固定統計檢定家族。不能把新結果寫回舊表格卻稱只是效能優化。

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

Shell 輔助檔適用 Linux／WSL；原生 Windows 直接使用所有 Python 指令。Windows 特有鎖定與 CUDA 分支若未在測試報告中列為已執行，就不能說已通過。

## 3. 原始資料規格與前處理

NSL 使用 `data/KDDTrain+.txt`、`data/KDDTest+.txt`；43 欄原始檔，包含 41 features、label、difficulty。UNSW 使用 `UNSW_NB15_training-set.parquet`／`testing-set.parquet`，或對應 CSV；依檔案角色分割，不依「哪個檔比較大」偷偷交換。

CICIDS 使用 `data/cicids2017/cicids2017_combined.parquet` 或同名 CSV，否則要求八個固定命名的原始 CSV 全數存在。IoT 使用 `data/iot23/iot23_combined.parquet` 或同名 CSV。資料應仍有原始 categorical tokens，不能拿已經全資料擬合編碼的輸出假裝 raw。其他路徑可用 `--source-spec-dir`，其中每個資料集一份 JSON：

```json
{
  "dataset": "unsw",
  "provenance_note": "說明下載來源、版本、是否已做上游轉換，以及仍待確認的部分",
  "files": [
    {"path": "UNSW_NB15_training-set.parquet", "role": "train"},
    {"path": "UNSW_NB15_testing-set.parquet", "role": "test"}
  ]
}
```

CIC／IoT 的角色為 `combined`；所有來源都會保存實際檔案 SHA-256。沒有自動下載、略過缺 shard、默默刪除未知 label 或不明文字欄位的路徑。

```shell
uv run --no-sync python spikeids_v5/suite.py prepare --data-dir data --cache-root results/v5_cache
```

準備流程如下：先分塊讀取 labels，建立固定 train／validation／test row IDs；僅用 fit rows 收集 category vocabulary；再僅用 fit rows 做固定順序的 incremental StandardScaler；最後以 float32、int64 memory-mapped arrays 保存各 split。預設 chunksize=65536，它也是前處理指紋的一部分，不可悄悄更改。

官方 NSL／UNSW training 另保留 **20% validation，split seed=20260920**；這是沿用上一版 hardened runner 的選擇，而不是 README 中另一套 15%／12345。CIC／IoT 先使用固定 80/20 stratified row split（seed=42），再從 training 切出 validation。所有模型和 seeds 共用同一份準備好的 cache。類別權重只由 fit labels 計算。

CIC 保留固定 schema 中的常數欄位，不使用全資料的變異數決定特徵集合，因此不保證仍是舊表格的「69 維」。欄位數與順序以產生的 metadata 為準。不再依 test 的負值範圍決定是否 clipping。非 NSL 的已宣告 NaN／Inf／缺值轉零，未知數字文字直接報错；此政策會改變部分舊結果，已列入指紋。

IoT 保留原專案五群映射以便比較，但 metadata 明確註記歷史 `C&C` 群包含 `Attack`、`FileDownload` 等項，不能稱為純 C&C ground truth。上游預處理是否已洩漏，不能靠重新 scaler 就洗掉。

**非常重要：移除 encoder/scaler/test-selection 洩漏，並不自動排除 duplicate、flow、capture、device 或 time-group 洩漏。**這個 row-split benchmark 不應被寫成「未見過裝置／場景／未來時間」的泛化實驗。metadata 明確保留 `duplicate_or_group_leakage_excluded: false` 和 `upstream_preprocessing_verified: false`。要做那些更強主張，必須拿到可靠的 group IDs、另立分組/時間協定，不能從縮減表格臆造 group。

## 4. 效能配置：量測，而不是相信 workers=2 或固定倍率

主訓練一次只有一個 GPU 訓練程序，避免兩份 CUDA context／資料／模型互相競爭。預設使用 FP32、關閉 AMP/TF32、嚴格 deterministic algorithms。每個 epoch 產生一次固定 CPU RNG permutation、一次重排 GPU resident arrays，batch 使用連續 slices；validation logits 預配置，沒有逐 class `.item()` 同步。QCFS 固定 L 不在 forward 每次取回 CPU。

預設保守 optimizer 為 `single`。不要因為「fused」這個名稱就宣稱一定最快或一定不確定，應量測：

```shell
uv run --no-sync python spikeids_v5/benchmark_profiles.py --dataset nslkdd --cache results/v5_cache/nslkdd --device cuda --work-dir results/v5_benchmark_nsl
```

候選為 single:1、single:4、foreach:4、fused:4。每個候選跑兩次，第二輪反向安排候選順序；先檢查同候選權重、optimizer、scheduler、RNG、history 的一致性，再按端到端 wall time 排名，不按 validation/test 準確率挑設定。可在 CICIDS 上加 `--models relu qcfs cnn` 量測另一類負載。CPU 也可明確比較 `--device cpu`。

短 benchmark 的最快候選不等於所有 seeds／80 epochs 或所有資料集的最佳。GPU 溫度、時脈、其他程式與作業系統排程仍影響時間；時間值不列入科學結果的逐位一致 hash。原 README 的「4–5 小時」「固定 5–15% 開銷」「workers=2 飽和」不作保證。

系統 RAM 用 memory mapping 和固定 chunks 控制暫存規模，不以 16 GB RAM 作為可保證的硬上限。GPU resident 模式會先估資料、重排副本與 2 GiB reserve；顯存不足就停止，不自動更改 batch。可另立 `--data-placement cpu` 的執行配置，但 suite 預設 GPU 常駐，不能執行中偷偷切換。

每次測試保存 logits/probabilities 的磁碟成本約為 `n_test × (8 × class_count + 16)` bytes，再乘模型數、seeds 和兩次驗證；這尚未包含 checkpoint/cache。四資料集、20 seeds 的完整證據可能佔多 GB，請先按實際 metadata 預留磁碟。不要為省空間把 float32 logits 改成 float16 卻保留相同協定名稱。

## 5. 凍結正式實驗，之後不改 code／資料／版本

以下 `fused / 4 threads` 只是**已由本機 benchmark 驗收後**的示例；沒有量測前可使用預設 single。

```shell
uv run --no-sync python spikeids_v5/suite.py freeze --cache-root results/v5_cache --run-dir results/v5_run --device cuda --optimizer fused --threads 4
uv run --no-sync python spikeids_v5/suite.py run --run-dir results/v5_run
```

固定規格為 20 seeds、11 組 dataset×model：四個資料集各 ReLU/QCFS，加上 NSL、UNSW、CIC 的 TinyCNN。IoT 是 40 epochs、batch1024，其餘 80 epochs、batch512。每十個 epochs 和最後一個 epoch 按 validation macro recall 選 checkpoint，平手取較早者。BatchNorm 的 singleton tail 合併上一批，不丟樣本。

全域順序是 **所有11組先 fit → 另一套獨立初始化/訓練完整重跑 → 所有對照一致 → 才對 test 評估兩份模型 → logits/機率/預測/metrics 一致**。正式 20 seeds 是 220 次模型訓練，雙重驗證合計 440 次，這是明確的驗收成本，沒有把只重讀同一 checkpoint 當成重訓。

中斷後重新執行同一個 `suite.py run`，會使用原紀錄續跑；所有 protocol/source/data/environment 必須相同。checkpoint 在每十個 epochs／validation／最終 epoch 保存，未保存部分需要從最近 checkpoint 重播。不能改 epochs 後拿舊 optimizer/cosine state 接續成另一個協定。

正式結果是 `results/v5_run/results/`；`replicas/` 是核對組。若途中失敗，所有下游統計／finalize 都停止。不得看完 test 後從兩份選較高分者。`verification_fit.json` 與 `verification_evaluate.json` 必須成功，且它們的 hashes 必須仍對得上實際 checkpoint、predictions 和 plan。

### 接線 smoke test

```shell
uv run --no-sync python spikeids_v5/suite.py freeze --cache-root results/v5_cache --run-dir results/v5_smoke --device cuda --optimizer single --threads 4 --seeds 0 1 --smoke-epochs 2
uv run --no-sync python spikeids_v5/suite.py run --run-dir results/v5_smoke
```

smoke 協定明確標為 `smoke_only`，不能通過 20-seed 論文 finalization。驗收看控制流程與結果重現，不要求 OA≈78 或 macro-F1≈58。

## 6. 統計與論文輸出

```shell
uv run --no-sync python spikeids_v5/run_globecom_stats.py --run-dir results/v5_run
uv run --no-sync python spikeids_v5/run_v4_equivalence.py --run-dir results/v5_run
uv run --no-sync python spikeids_v5/finalize_all_det.py --run-dir results/v5_run --paper-dir paper/globecom
```

同一份結果會先從保存的 test labels/predictions/probabilities 重算 metrics、比對 checkpoint、核對實際 seed ID 與 split/preprocessor identity，而不是信任 aggregate。列數相同不等於樣本相同；相同 epochs 不等於相同 FLOPs／容量／硬體耗能。

所有差值統一 **ReLU − comparator，percentage points**。difference 檢定家族為七種比較×OA/MF1＝14；equivalence 家族為四資料集×OA/MF1＝8。兩個家族各自做 Holm；這是兩個預先區分的研究問題，**不是對兩者合併22個主張宣稱一次總體 FWER=0.05**。需要合併家族時，必須在凍結前設計另一協定，不能看完結果才切換。

TOST 使用 `(1−2α)` 的個別 t interval，並以 `max(p_lower,p_upper)` 作為 IUT p 值；Holm 後的決策不等於每個原始90% CI都是 simultaneous CI。δ 預設1pp在本次 freeze 記錄，不冒稱它已在舊投稿中預先註冊。`delta_min_infimum` 是未校正的敏感度診斷，嚴格大於該界線才通過，不是拿來看完資料改 margin 的工具。

signed-rank 對 ties/zeros 使用整數動態規劃的 conditional sign-flip 分布，差值的小數12位取捨規則固定。它的 exact 指條件分布的計算，不代表獨立性、對稱性等前提已被證明。參數式 TOST 與 signed-rank TOST 並非同一 estimand，不依 Shapiro p 值自動換主檢定。零觀察變異回報參數式推論未定義，不把非零常數差值的 d_z 寫成零或把數值退化冒充無限信心。

`stats_tests.py` 另外提供正態差值假設下、對樣本變異分布做 deterministic quadrature 的 power 與 bounded/bisection required-n。它不是 distribution-free power，也不是 observed power 證明。預設報告不自動用看過的差值選下一批 seeds。

**顯著差異可以和實務等價並存；difference 不顯著也不等於等價。**刪除原 README 預先指定的「IoT一定QCFS較好」「所有四個都等價」結論，依新的報告描述。

### 安全的 LaTeX 接線

finalize 只產生 `result_macros_v5.tex` 與 provenance，不覆寫 `main.tex` 或舊手工 macro。Codex 必須把相關引用改成 `vFive...` 新 macro，並輸入新檔，不能只追加新 macro 又讓正文繼續吃舊檔。

```shell
uv run --no-sync python spikeids_v5/check_paper_consistency.py --run-dir results/v5_run --paper-dir paper/globecom --strict
uv run --no-sync python spikeids_v5/finalize_all_det.py --run-dir results/v5_run --paper-dir paper/globecom --build
```

任何來源缺失、macro缺失、hash不符、檢查失敗都停止；shell使用 `set -euo pipefail`，沒有吞掉失敗的 `|| echo`。僅在 strict 檢查通過後才允許 `latexmk`。小 p 值不顯示成「0.000」。per-class recall 本來就是百分比，不再乘100。

checker 的範圍是受管理的數值來源與保守的文字模式掃描，不能證明整篇自然語言、理論、所有輔助表格或能耗主張正確。報告明確寫 `natural_language_scientific_claims_proven: false`。沒有稿件完整內容與板端實驗，不能宣稱整篇論文已通過。

舊格式消費者需要 view 時，可在這個**新 run namespace**使用 `assemble_nsl_legacy.py`／`assemble_cnn_legacy.py --run-dir ...`；產物在 `legacy/`，保留來源指紋，沒有把舊 JSON 改名洗成新證據。

## 7. L-sweep、轉換、匯出與板端

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
uv run --no-sync python spikeids_v5/export_verified.py --run-dir results/v5_run --dataset nslkdd --model qcfs --output-dir results/v5_export_nsl_qcfs
```

加 `--int8 --int8-max-disagreement <事先選定的容許比例>` 才啟用 QDQ；不要把角括號原文放入 shell。這個容許值是 validation-vector prediction disagreement，不是「test accuracy只能掉5%」的事後規則。校準只取fit rows，不另走舊data loader重新擬合；sample IDs、前處理、checkpoint、ONNX、policy 都互相綁定。BN folding是額外的 `--fold-bn` 選項，浮點重排可能跨越量化邊界，必須通過數值和prediction gate。

原 quantize_qcfs 把 `quant_format` 誤設成 `QuantType.QInt8`；新路徑是 `QuantFormat.QDQ`，type另設QInt8。部分 linear/conv量化的QDQ圖不等於「全INT8」「全部NPU」；算子清單不能代替 vendor mapping report。輸出每次使用新資料夾，不再讓不同資料集共用 `ids_qcfs_L4.onnx` 而覆蓋彼此。

原 N6 kernel 有代表性固定量化參數與人工bias，不能把該微基準直接視為新訓練模型的部署。`deployment_gate.py` 是**離線證據核對器**，不會刷板、halt MCU、改時脈。它要求實際binary、編譯報告、clock原始依據、timing log、相同input vectors及board logits。即使文件一致，也明確不冒稱已做物理量測真實性 attestation；未提供電流/電壓量測就不稱能耗已測。

## 8. 給 Codex 的接手入口

先讀 `CODEX_HANDOFF.md`，再讀 `audit/REVIEW.md` 和實際測試報告。不要執行原 README 的 `train_fast` 範例；不要改正在執行中的 `experiment_multiseed(1).py` 來破壞其 resume。需要修改本套件來源時先停止啟動新的job，另建新版本/run目錄；不改已凍結的來源hash讓它勉強續跑。

在套件目錄執行測試：

```shell
uv run --no-sync python -m pytest tests -q
```

`tests` 使用明確標註的合成資料，不能把測試通過理解成原始資料、GPU、板端、或全論文結果已通過。詳細的測試版本與未執行清單，以 `audit/TEST_REPORT.json` 為準。
