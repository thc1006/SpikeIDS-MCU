# Codex 接手指令：SpikeIDS v5，不以預期結果代替驗證

## 任務與已交付範圍

使用者要求針對 16 GB RAM／Intel 第14代 i5／RTX 4060 Ti 16 GB 修復 SpikeIDS 的資料、訓練、統計與論文數值流程。本套件是可執行的新版本，不是只留 TODO 的 scaffold。先讀 `README.md`、`audit/REVIEW.md`、`audit/TEST_REPORT.json`；它們共同說明科學方法改變、實際測試與未驗收項目。

查閱的遠端來源固定於 `thc1006/SpikeIDS-MCU` 的 `fd769747c4b0ba84f33bae4d26a8754a7ef80238`。這不是本機工作目錄一定等於該 commit 的保證。十個原始上傳檔的雜湊及修改對照在 `audit/`。不要把原 README 中的「authoritative」「已證實」「最高速度」「IoT一定更好」當成事實。

**本次已在 CPU 合成 CSV 做實際訓練、獨立重跑、resume、完整11組流程與數值驗證。沒有在使用者的 CUDA GPU／真實資料／MCU 上執行；Parquet 與 ONNX/QDQ 路徑也尚待可用依賴下驗收。**以機器可讀測試報告為準，不把已存在的測試碼視為已執行證據。

## 必須維持的工作規則

保持原專案 `src/`、`scripts/`、舊結果與正在跑的訓練不動，把整個 `spikeids_v5/` 放在原專案根目錄下。本套件的 `models.py` 是隔離 runner 使用的三個模型，不是原專案所有 FlexMLP／匯出相容類別的替代品。不要逐檔覆蓋原 `src`。

先確認本機 git HEAD、工作樹差異和現有 process，但不得自動停止任何 process、改 GPU/CPU 時脈、刷板或重啟設備。不要修改原本 in-flight `experiment_multiseed(1).py`，不能改 source hash 來強行 resume。也不得自動 commit／push。環境使用既有 `.venv` 或 `uv run --no-sync`；不自動升級 torch/CUDA、不把 CPU wheel 換入 GPU 環境。

不採用固定期望 OA/F1 作為測試條件；不為了通過 TOST 改 δ、刪 seeds、改檢定家族、重排 pairing、隱藏未定義指標。任何新結果推翻原文，也應保留並忠實反映。

## 按順序執行

### 1. 核對本地版本與環境

確認套件完整性，保留 `audit/SOURCE_INVENTORY.json` 與 `SHA256SUMS.txt`。閱讀目前 Python、torch、CUDA runtime、driver、GPU型號、OS、RAM/VRAM可用量；結果保存為本次實驗的環境紀錄。`uv run --no-sync python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available())"` 必須在正式 GPU 執行前成功。

執行 `uv run --no-sync python -m pytest spikeids_v5/tests -q`。若缺 pyarrow/onnx/onnxruntime，使用指定環境的 `uv pip` 安裝相容且明確鎖定的版本，再跑被跳過測試；安裝或升級後應先完成驗證，才做 `freeze`。GPU 測試檔會在有 CUDA 的環境解除 skip，但仍需 suite 的完整20seed GPU重跑。

可重跑獨立合成整合驗證：

```shell
uv run --no-sync python spikeids_v5/tests/run_integration.py --work-dir results/v5_synthetic_integration
```

這會產生44次兩個 epochs 的小型 CPU 訓練，不是論文結果。需新工作目錄，不能拿合成資料混入正式 cache。

### 2. 先審資料，再準備正式 cache

核對四資料集的原始檔名、實際列數、特徵順序、label mapping、來源與版本／下載校驗。特別核實 UNSW training/testing 檔的實際角色與 schema，不依大小交換。IoT 的 HuggingFace preprocessed 資料不能自動視為無上游洩漏；確認 categorical 是否仍是原始字串、是否先前對整體資料做過 imputation/encoding/filtering/dedup。

CICIDS／IoT 的 row split 不等於 capture/device/time holdout。確認論文要聲稱什麼。若要未見設備／場景／時間泛化，必須取得來源 group IDs 並另建分組/時間協定；不能從缺失 metadata 猜 group。不同 capture 的 attack classes 可能不齊全，不能為了讓現有15class檢定通過而事後調組。此功能不是本交付假裝已完成的部分。

原完整資料可用後：

```shell
uv run --no-sync python spikeids_v5/suite.py prepare --data-dir data --cache-root results/v5_cache
```

檢查 metadata 的 fit/validation/test row IDs、未知 category 計數、非有限值處理、features/class_names，評估合理性但不看 test 準確率調前處理。官方 training 使用20%validation／20260920，不是舊15%／12345。所有模型共用同 cache；必要的政策變更必須進新版本、測試與新 cache。

### 3. 在本機量測效能，不能以名稱判定最快

使用 README 的 `benchmark_profiles.py`，至少比較 MLP/QCFS 與 TinyCNN 有代表性的資料集。候選 single/foreach/fused、1/4 threads 分別在兩個新程序量測；只有同候選完整訓練狀態 hash 一致才可選入排名。依 wall time 選，不依 validation 或 test 成績。短 benchmark 不證明全20seeds/80epochs必然重現。

記錄 RAM RSS、VRAM峰值、GPUdriver、作業系統、背景負載、電源/散熱狀態和完整 log；本套件不自動修改功耗或時脈。16 GB RAM 不是已實測的硬上限保證。GPU不夠用時不可悄悄改batch/precision，應先排查或另立明示的配置。

### 4. 確認研究協定並凍結

預設是20seeds、11組，IoT40ep/batch1024，其餘80ep/batch512，hidden256，L4，**shifted_v1量化ANN**。每10epoch+最後一個以validation macro recall選最佳、平手最早。

把 corrected QCFS 的+0.5 shift當成新方法版本，不把舊checkpoint載入新公式。原舊floor公式僅透過另一份顯式`legacy_floor_v1`協定診斷。本 suite 不宣稱 trainANN=T1SNN。

差異檢定14個與等價檢定8個各一個家族；各做Holm，不聲稱聯合22個familywise0.05。δ=1pp是本次freeze記錄，不是假造舊投稿的預先註冊。確認研究問題需不需要同一家族更嚴格控制；更改需在正式訓練與test曝光之前完成並重測。

```shell
uv run --no-sync python spikeids_v5/suite.py freeze --cache-root results/v5_cache --run-dir results/v5_run --device cuda --optimizer single --threads 4
uv run --no-sync python spikeids_v5/suite.py run --run-dir results/v5_run
```

`single`是保守示例；已量測確認的其他backend可在freeze時明示。新的所有頂層`.py`來源、環境、資料指紋和超參數凍結後不要修改。若需要修code，另立run目錄，不竄改原manifest。

### 5. 完整獨立重跑與 test 開啟條件

suite先完成所有11組primary，再完成獨立replicas；訓練weight／optimizer／scheduler／RNG／batch order一致後才准許test。20seeds為220次fit，兩套共440次。`verification_fit.json`和`verification_evaluate.json`必須通過。再次執行相同suite命令可resume，不會用不同budget冒充同一次實驗。

primary是正式成績，replica只是核對，不能挑高分的一份。不要因舊README稱「IoT要78分」而把未達數值當程式錯誤。非有限值、輸出缺失、錯seed、錯來源、任何該失敗的檢查不得降成warning。

### 6. 次要研究／部署不是自動完成

L-sweep明示L集合後使用同fit-only cache/runner，不能看結果重寫L4選擇理由。`snn_analysis.py`可產生有時間步、膜電位、reset的IF驗證資料，但只是所定義IF與讀出下的validation診斷；不包含外部SNN框架或神經形態硬體的完整獨立驗證。`layerwise_analysis.py`是ANN→frozenANN，不是舊INT8圖的免審替代。

ONNX先跑可用依賴測試，之後對**選定seed、checkpoint、同一前處理和輸入向量**做FP32/ONNX/QDQ核對。BN folding明示、prediction disagreement與數值容許值在輸出前固定；失敗不可用放寬門檻掩飾。QDQ不是全INT8或全NPU證據。

N6/RA4E1/ESP32-S3正式部署需另一條端到端證據：trained checkpoint→前處理→校準→ONNX→vendor compiler mapping→binary→board輸入/輸出→原始timer/clock。舊N6代表性固定Q_MULT/Q_SHIFT與人工bias只可當microbenchmark。不得將`deployment_gate.py`檔案一致pass描述成現場物理量測已attest。實際刷板與測試需使用者授權，不在本套件自動執行。

RF/XGBoost及所有其他舊baseline／NPUcompiler版本／完整firmware目錄本次沒有逐檔重構完畢；論文用到它們的數字時要獨立追源、測試或移除相關主張。不能用主分類pipeline通過帶過。

### 7. 論文數值與文字

執行統計與finalize。新macro寫`result_macros_v5.tex`，不覆蓋手工舊macro。明確更新正文引用、表格、圖、方法與結論；未被v5覆蓋的輔助表格逐筆記錄來源。保留「原test已被探索」的揭露，新程式不能洗掉過去test-selection。

刪除「不顯著＝等價」「顯著＝不等價」兩種錯誤推論。顯著且在margin內等價可以同時成立。零觀察variance的t推論未定義不是證明等價。Mean difference、pseudomedian與每seed固定split變異不能混成新資料集泛化。

`check_paper_consistency --strict`和`--build`通過只證明受管理的數值與有限文字模式，不能宣稱整篇論文無錯。完整TeX自然語言、圖與外部表格仍需人類審閱。引用需要真實最新來源，不要保留原README無證據的「76%」「4–5小時」「固定5–15%」數字。

## 最後交回使用者的東西

交付實際變更清單、commit/dirty狀態、測試log與所有skips、GPU完整verification與benchmark報告、資料來源/分組限制、正式primary結果、部署是否驗證、paper數值check、仍未通過項目。不要寫「所有問題已根除」「絕對無懈可擊」；讓證據指出已通過的範圍。
