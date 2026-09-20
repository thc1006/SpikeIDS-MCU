# 查閱來源與用途

查閱日：2026-09-20。文件頁面顯示的新版軟體版本，不代表已在本測試環境跑過那個版本。實際版本以 TEST_REPORT.json 為準。程式碼來源、官方定義與本次自行推導/測試分開記錄；來源數量不能代替驗證。

## 第一手技術依據

|來源|本次使用範圍|
|---|---|
|PyTorch 2.10 reproducibility：<https://docs.pytorch.org/docs/2.10/notes/randomness.html>|本次實測2.10版本的確定性設定與跨版本/平台限制，不宣稱無條件bitidentity|
|PyTorch performance tuning：<https://docs.pytorch.org/tutorials/recipes/recipes/tuning_guide.html>|減少CPU–GPU同步、set_to_none與可量測的實作選項，不據此編造4060Ti加速倍率|
|PyTorch Adam：<https://docs.pytorch.org/docs/2.10/generated/torch.optim.Adam.html>|single/foreach/fused是不同實作路徑，需在固定配置下驗證|
|PyTorch BN fusion：<https://docs.pytorch.org/docs/2.10/generated/torch.nn.utils.fusion.fuse_linear_bn_eval.html>|eval/runningstat前提；affine=False實際支援依本次測試發現另處理|
|NVIDIA cuBLAS：<https://docs.nvidia.com/cuda/cublas/index.html#results-reproducibility>|workspace與結果重現條件；不是整個PyTorch模型無bug證明|
|scikit-learn pitfalls：<https://scikit-learn.org/stable/common_pitfalls.html>|先split，再僅training fit，包括preprocessing/featureselection|
|scikit-learn metrics：<https://scikit-learn.org/stable/modules/model_evaluation.html>|PRF、MCC、AUC與average語義，實際oracle測試見tests|
|SciPy Wilcoxon：<https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.wilcoxon.html>|ties/zeros/浮點差值與permutation；自製DP與SciPy exhaustive結果比較|
|statsmodels paired TOST：<https://www.statsmodels.org/stable/generated/statsmodels.stats.weightstats.ttost_paired.html>|配對等價t檢定的獨立數值oracle|
|statsmodels multipletests：<https://www.statsmodels.org/stable/generated/statsmodels.stats.multitest.multipletests.html>|Holm調整的獨立數值oracle|
|Lakens 2017，Equivalence Tests：<https://pmc.ncbi.nlm.nih.gov/articles/PMC5502906/>|TOST、1−2alphaCI、實務等價與顯著差異可以同時成立；未據此證明資料假設|
|Bu et al.，Optimal ANN-SNN Conversion：<https://arxiv.org/abs/2303.04347>|QCFS ANN與SNN conversion不是同一段運算；理論expectederror不等於所有輸入逐位相同|
|QCFS原作者程式：<https://github.com/putshua/ANN_SNN_QCFS/blob/main/Models/layer.py>|ANN分支+0.5 shift；T>0的IF膜電位/循環/reset；讀到的blob為7553fc7ca05e744df96cd35714868c0b163e72ab|
|ONNX Runtime quantization：<https://onnxruntime.ai/docs/performance/model-optimizations/quantization.html>|QuantFormat.QDQ與QuantType區分、校準、lossy quantization與activation debugging；不等於NPU已映射|
|ONNX Runtime原始API：<https://github.com/microsoft/onnxruntime/blob/main/onnxruntime/quantization/quantize.py>|quantize_static參數的列舉型別；真實本地版本仍需運行驗證|
|ST量化說明：<https://stedgeai-dc.st.com/assets/embedded-docs/quantization.html>|廠商工具鏈語境；不代替某個已編譯模型的mapping report|
|UNSW資料建立者：<https://research.unsw.edu.au/projects/unsw-nb15-dataset>|資料來源/攻擊類型背景；本機parquet副本角色/內容仍需核對|
|CICIDS資料建立者：<https://www.unb.ca/cic/datasets/ids-2017.html>|attack日程/場景/檔案來源；rowrandomsplit不自動驗證time/capture泛化|
|IoT-23資料建立者：<https://www.stratosphereips.org/datasets-iot23>|場景/設備/標註來源；不能把某HFpreprocessedsubset視為已核實全原資料|

## 固定使用者倉庫快照

Repository: `thc1006/SpikeIDS-MCU`，branch查閱時為`v4`。
Commit: `fd769747c4b0ba84f33bae4d26a8754a7ef80238`。

讀取經使用者已連接GitHub connector完成，沒有在容器git clone。主要讀取檔案：

- `src/models.py`、`data_loaders.py`、`metrics.py`、`stats_tests.py`。
- `src/experiment_iot23.py`、`experiment_cicids2017.py`相關loader區段。
- `src/quantize_qcfs.py`、`export_qcfs_onnx.py`。
- `src/layerwise_analysis.py`、`experiment_qcfs_lsweep.py`相關主流程。
- `firmware/n6/src/kernels_mlp.c`、`bench.c`相關量化/計時區段。

這個清單不是整倉庫每一檔皆讀完的聲明。原始上傳十檔已完整提供並用於diff；檔案SHA詳見SOURCE_INVENTORY.json。未聲稱完整firmware、treebaselines、所有export變體或論文正文已完成審查。

## 本次推導與證據性質

T1反例由明示θ/L/x及IF初始膜電位直接計算；power是正態母體假設下對樣本變異分布的數值積分；exact signedrank是在所述條件分布下的DP。這些計算皆有測試，但不是底層library/OS/hardware無bug的形式化證明。

所有SHA是完整性/來源一致性標記，不是加密簽章或實體量測attestation；有權重寫所有資料與雜湊者仍能偽造一整套自洽紀錄。出版時宜另外保存只讀、外部時間戳或第三方可核對的原始證據；本套件不假裝提供不存在的信任根。
