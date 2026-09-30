# 對十個上傳檔及核心依賴的審查紀錄

查閱日：2026-09-20。遠端依賴以`fd769747c4b0ba84f33bae4d26a8754a7ef80238`固定。本表的「確認」指原始程式可直接支持，不等於已執行該程式的正式GPU實驗。修正碼位於隔離`spikeids_v5/`，不自動修改原repo。

## 十個檔案：逐一處理

|原上傳檔|已確認問題|新版本處理|
|---|---|---|
|README(10).md|§4/§12指向不同trainer；15%與20%val矛盾；要求特定OA/MF1才算修好；預先指定IoT優勝結論；固定耗時/workers開銷無實機證据|全新README與CODEX_HANDOFF；單一suite；明示方法版本與未驗證範圍；不以成績驗收|
|experiment_all.py|UNSW/CIC/IoT直接NotImplemented；protocol沒有dataset；output固定NSL；所謂raw IoT/CIC loader已對全資料處理；L硬編4|全部四dataset實作；chunked fit-only cache；dataset/class/features/split/前處理與來源封裝；L/formula顯式；獨立訓練與test兩階段|
|assemble_nsl_legacy(1).py|固定n_train125973排斥合法valholdout；assert可被python-O省略；未檢每record的seed；nullableAUC可能float(None)；信任aggregate；non-atomic/default=str|只讀新namespace完成且驗證過的source；檢真實ID/cache/state/predictions；重算aggregate；原子嚴格JSON；不污染舊檔|
|assemble_cnn_legacy(1).py|列數相同被稱為保證相同split；只看seed總list及epochs；可帶入staleaggregate|按rowID hashes/preprocessor/rawfingerprint/seed/batchorder檢查；同epoch稱matched epoch budget，不聲稱FLOPs或容量相同|
|run_globecom_stats(1).py|以prefix/min(n)配對；缺比較就縮家族；sd0時非零常數差的dz被寫0；TOST CI固定90%；NaN/defaultstr|seedID嚴格配對；14個difference/8個equivalence明示；nullableundefined但不縮Holmfamily；1−2alphaCI；嚴格JSON；exact conditional signedrank|
|run_v4_equivalence(1).py|用陳舊TRAIN_BATCH推估；missingNone==None可能判valid；缺seed時自造0..n；Shapiro失敗就換estimand；delta_min語意不嚴謹；歷史preregistration無證據|直接核實產物protocol/資料；不造ID；meanTOST固定主檢定，signedrank敏感度另列；delta_min是嚴格infimum；只記錄本次freeze|
|finalize_all_det(1).py|只驗20筆；per-class recall本為百分比卻再×100；先改macro/build後沒強制全文check；p格式可能0.000|統一verified evidence→新macro/provenance；不改主文/舊macro；smallp<0.001；build前strictcheck；不由數字產生預設結論|
|check_paper_consistency(1).py|缺JSON、缺macro、缺stats比較常直接continue；in_preamble未真正使用；僅局部regex不能證全文|缺證據即失敗；完整managedmacro字串+provenance核對；literalbracedTeXinput遞迴；循環/缺檔/非支援動態input拒絕；明示仍非語意證明|
|run_v4_rerun(1).sh|仍呼叫被取代train_fast；硬編本機path/workers2；檔案完成訊息不能證deterministic|相對套件路徑、exec、set-euo-pipefail；新suite全域barrier與固定plan，無自動背景process管理|
|finalize_and_check(1).sh|pipeline缺pipefail；checker失敗以`||echo`吞掉仍build且印done|錯誤returncode保留；只交給嚴格finalize；沒有假成功或自動修論文結論|

## 額外追查的重大科學問題

### 1. QCFS、T=1和BN folding

原`src/models.py`的QCFS沒有原作者ANN分支的+0.5 shift；`IDS_MLP_QCFS.forward`只是feed-forward ANN，沒有時間、membrane或reset。這足以否定「該檔已實作並驗證T1轉換」，但不代表任何可能的多bit/multispike編碼都被否定。

反例：θ=1、L=4、x=.25，shiftedANN輸出.25。初始膜電位.5、每step最多一個θ幅度spike的IF在T1只到.75，輸出0。因此不是逐神經元一般等式。原作者論文/實作將ANN量化與T>0IF分支分開；期望轉換誤差的理論主張不能移植為每個輸入都逐位等同。

新公式與舊公式分版本、分fingerprint。快取L只移除CPU同步，不把除法改乘reciprocal而跨floor邊界。BN只在eval且有觀察到runningstats後可融合；affine=False/biasNone/dtype處理有實際測試。BN融合是浮點近似等價，QCFS邊界可能放大微小差異，故實際validationvector gate不能省。

新`snn_analysis.py`包含明示IF與readout診斷；新layerwise只比較ANN/frozenANN。兩者不自行產生「SNN=T1」「能耗已測」結論。

### 2. 資料：不只主程式的test選checkpoint

`data_loaders.py`NSL/UNSW在train+testconcat上fitencoder；UNSW還用testunion決定labels。`experiment_iot23.load_iot23`在完整df編碼，之後才split，所以它不是rawloader。`experiment_cicids2017`先用全資料判constantfeature，又允許CSV缺shard略過。這些均被新cache路徑繞開，沒有在舊已編碼frame上再次fit假裝修好。

新數字不能和舊數字當同一實驗。正式原始資料在這裡不可用，因此featureidentity和上游來源仍需本機確認。CIC常數保留、負值不按testmin改policy，可能使features不同於舊69。IoT歷史五群中的C&C不是純C&C。只排除split-ID重疊、encoder/scaler/test-selectionleak，沒有冒稱排除重複flow或跨capture/device/time的依賴。

### 3. 指標：不是所有舊公式都錯

完整classes都存在時，原macroF1、precision/recall、weightedPRF、multiclassMCC的主公式基本符合常規；不應為了寫嚴重審查就硬指它們錯。已確認問題在輸入驗證、missingclass定義、binaryAUC矩陣傳法以及捕捉錯誤後回None掩蓋原因。原per-class accuracy實際為recall；macro_acc等於fixedclassmacrorecall；不能把欄位名誤解成one-vs-restaccuracy。

新指標用scikit-learn獨立oracle測試binary/5/15類，嚴格機率shape/finite/normalization，明確未定義情形。最終數字從存下的predictions重新計算，不信任先前aggregate。

### 4. 統計與等價性

TOST的標準誤基於每seed的配對差，而非不相關兩組樣本；同seed順序不是可靠身分，需原始IDs。差異不顯著不能證等價；差異顯著也不排除差值落於事先margin內而等價。README預設「IoT顯著所以不等價」的二分敘述不保留。

常數差值sd0不能寫dz0。新版參數式推論回undefined而不造p0；這是保守處理數值退化，不聲稱所有定義都必須如此。測試也抓到[.1]*20的floatingstd可能非零，所以明確用零range識別常數。

exact signedrank處理ties/zeros；TOST primary mean與pseudomedian敏感度不混；Holm對未定義保留家族位置。power計算是normalmodel條件下的quadrature並和MonteCarlo比對，不是distributionfree也不是事後觀察power的研究證明。

### 5. ONNX／QDQ／板端：存在直接缺陷，硬體結果未被洗成通過

原`quantize_qcfs.py`的`quant_format=QuantType.QInt8`混淆format與dtype；ONNXRuntime官方示例用QuantFormat.QDQ。原export依prefix讀不同datasetcheckpoint，卻全部寫`ids_qcfs_L{L}.onnx`，有跨模型覆蓋風險。只驗一個未seed隨機vector且ORTdiff僅列印，不能驗train/exportparity。某op在手寫白名單不等於該圖在指定toolchain已映射NPU。

原`firmware/n6/src/kernels_mlp.c`固定Q_MULT/Q_SHIFT且bias=(k&7)-3，屬代表性kernel基準；不能當選定checkpoint與實際quantparams已部署的證據。`bench.c`保存了部分HALclock依據，但沒有實體板資料就不重新聲稱CPUclock/端到端latency正確。

新export綁定cache/checkpoint/validation/calibrationIDs/seed，使用專屬新outputdir；QDQ與BNfold都有顯式policy。板端gate只做離線文件/向量/clock/graphhash核對，仍標記physicalauthenticityFalse、energyMeasuredFalse。ONNX/ORT在本環境缺依賴且安裝因DNS失敗，這条路徑沒有被實測通過。

### 6. L-sweep與舊表格

查到的L-sweep實際L={2,4,8,16}、5seeds、60epochs，README另處寫{1,2,4,8}；不能任選一個當既定研究。其train用finalepoch，不是和主程式完全相同的testcheckpoint-selectionbug；但loader仍有上述洩漏，且用test表事後justifyL4是另一種適應性風險。舊schema-smoke產生零數字，只能測schema不能冒充訓練驗證。新版要求明示levels，沿用同cache/runner，測試真的跑訓練。

## 實際驗證與仍需工作

詳見`TEST_REPORT.json`與原始logs。前幾輪發現的contextmanager遺失、BNaffine=False及常數小數variance問題已修復並回歸；測試自身一次把comment中的train_fast字串誤判為可執行舊入口，已修成只檢查非comment行，不是刪除功能測試。

尚未執行：使用者的4060Ti/WindowsCUDA、真實四資料集全20seed、完整Parquet/ONNX/QDQ匯出、NPUcompiler/firmware部署、實體latency/energy、完整原manuscript/LaTeX編譯。RF/XGBoost與所有其他舊quantize/export/n6輔助腳本未逐一替換；它們不能繼續無來源地餵新版paper。這些項目不能靠上述10檔重構就宣稱完成。

## 主要原始與官方依據

完整連結、查閱範圍見`SOURCES.md`。來源包括：固定repo snapshot、QCFS原作者實作/論文、PyTorch reproducibility/tuning/BN fusion文件、sklearn leakage/metrics文件、SciPy signedrank、statsmodels pairedTOST及Holm、Lakens等價檢定原文、ONNXRuntimequantization文件、CIC/IoT資料建立者說明。程式注釋與README只當待驗證材料，不當作獨立證據。
