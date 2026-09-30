# 實際驗證結果

2026-09-20，最終來源已核對與兩輪整合流程記錄一致。

## 自動化測試

**90 passed、3 skipped、0 failures、0 errors**，共93個案例。原始log：`test_run.log`；JUnit：`test_results.xml`。

三項跳過：CUDA硬體、Parquet依賴、ONNX/ONNXRuntime依賴。它們不是已通過。安裝嘗試因DNS限制失敗，保留`dependency_install.log`。

## 真實執行的合成資料整合流程

四資料集×11個dataset/modeljob，seeds0/1，2epochs；primary與replica合計**44次獨立模型訓練、44次checkpoint test評估**。涵蓋prepare→freeze→fit→independentrepeat→testcomparison→stats→legacyviews→ANN/frozenlayerwise→IFdiagnostic。錯counts、錯seed、錯aggregate、錯dataidentity、缺replica均被拒絕。smoke不能通過paperfinalize。

另外實際跑benchmark_profiles、verify_reproducibility與L=1/4的sweep CLI：**20次獨立訓練、8次test評估**。加總64次整合訓練、52次checkpoint評估，不包含pytest單元測試內其他訓練。全部使用合成資料，不是正式論文數字。

日誌與每step exitcode位於`integration/`、`auxiliary/`。這些CPU短程時間不應外推成4060Ti完整工作時間，合成準確率也不可引用為研究成果。

## 環境

Python 3.13.5；PyTorch 2.10.0+cpu；NumPy 2.3.5；pandas 2.2.3；SciPy 1.17.0；scikit-learn 1.8.0；statsmodels 0.14.6；pytest 9.0.2。CUDA可用：False。

## 尚未驗收

真實四資料集全20seed、RTX4060Ti速度與峰值RAM/VRAM、Windows專用分支、Parquet、ONNX/QDQ、全部NPUcompiler/firmware端到端、實際latency/energy、完整論文/LaTeX。RF/XGBoost與其餘舊sourcepaths也不是因本套件主流程通過就自動驗收。

完整版本、scope、來源與testsource SHA-256見`TEST_REPORT.json`。目前結果支持「可執行、所測CPU路徑與證據檢查已通過」，不支持「任何環境必然最快或永不出錯」。
