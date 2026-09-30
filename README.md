# SpikeIDS-MCU — 可稽核的 v5 研究管線

目前狀態（2026-09-24）：正式神經網路與 tree baseline 實驗、固定 export 矩陣、有界論文產物審查，以及本機完整模型／證據副本驗收已完成。新增的 export 數值診斷、QCFS 追蹤／介入／精確算術核對、四組 BN folding 診斷、unfused ReLU 候選、逐層追蹤及雙錨定等輸入 BN 診斷均已真實執行並完成限定後覆核。最新BN診斷36個原生回放全部逐位元吻合，120組比較獨立重算一致；等輸入下11/12個BN通過原容差，IoT23第三個BN仍有21／23列超限。原候選仍各0/4，未修復整體數值門檻。**這不代表所有 export 通過，也不是投稿、release 或板端效能驗收。**

以下 `results/` 連結指向本工作站產物，目前尚未發布新的可下載 release。既有公開舊版、旧稿及旧數字不能替代這些來源綁定的 v5 證據。

## 目前應使用的入口

- [最新 phase 狀態：雙錨定等輸入 BN 診斷，非 export 修復](results/v5_local_bn_20260924_rPaQeD/STATUS.md)
- [前一 phase：四組 unfused 逐層對齊追蹤](results/v5_unfused_trace_20260923_wMbEyy/STATUS.md)
- [前一 phase：四組 unfused ReLU export 候選，兩模式各0/4](results/v5_unfused_export_20260923_uVH0Au/STATUS.md)
- [前一 phase：四組 BN folding 診斷](results/v5_bn_trace_20260922_EJIpEB/STATUS.md)
- [前一 phase：QCFS 精確算術核對](results/v5_qcfs_exact_20260922_0BoR5D/STATUS.md)
- [前一 phase：QCFS 雙向介入](results/v5_qcfs_intervention_20260922_YkeMwN/STATUS.md)、[逐層追蹤](results/v5_qcfs_trace_20260922_mQlmHa/STATUS.md)、[原 export 數值診斷](results/v5_export_engineering_20260922_sx9DXw/STATUS.md)
- [論文 phase 狀態](results/v5_paper_continued_review_20260922_sQdjK1/STATUS.md)
- [已審查的 9 頁 PDF](results/v5_paper_continued_review_20260922_sQdjK1/pdf_actual_02/build/main.pdf)
- [對應論文原始稿](results/v5_paper_continued_review_20260922_sQdjK1/candidate_actual_03/paper/main.tex)
- [論文產物驗收](results/v5_paper_continued_review_20260922_sQdjK1/manuscript_acceptance_actual_01/MANUSCRIPT_ARTIFACT_ACCEPTANCE.json)、[實際退出紀錄](results/v5_paper_continued_review_20260922_sQdjK1/ROOT_MANUSCRIPT_ACCEPTANCE_ACTUAL_EXIT.json)、[獨立後覆核](results/v5_paper_continued_review_20260922_sQdjK1/MANUSCRIPT_ACCEPTANCE_ACTUAL_POSTREVIEW.md)
- [v5 方法與操作文件](spikeids_v5/README.md)、[接續工作 handoff](spikeids_v5/CODEX_HANDOFF.md)
- [正式模型與副本存放入口](results/v5_evidence_copy_review_20260922_1srUIm/MODEL_STORAGE.md)、[本機副本驗收](results/v5_evidence_copy_review_20260922_1srUIm/LOCAL_COPY_PHASE_ACCEPTANCE.json)

## 已完成的範圍

| 項目 | 目前結果 |
| --- | --- |
| 神經網路正式實驗 | 440 fits：220 primary＋220 replica；[原始 run](results/v5_run_20260921_r6_recovery1/) |
| RF／XGBoost baseline | 84 fits；[原始 tree run](results/v5_tree_20260921_r6_1/) |
| 固定 export 矩陣 | 原 3＋續跑 19，共 22 項；FP32 parity 通過 4/11、QDQ 通過 1/11；17 個負結果保留 |
| 新增 export 診斷 | 11 個原 checkpoint 重現全部原判定；保存 logits 的 55 組比較後驗證通過；12 組 BASIC／DISABLED 輸出逐位元相同，未改判原 17 個負結果 |
| QCFS 邊界定位與介入 | 原1024筆插樁不改最終輸出；九條件單座標雙向介入及獨立後覆核通過，支持所選樣本的局部差異傳播，非 export 修復 |
| QCFS 精確算術 | 原保存座標的13項dot精確加總與逐步FP32核對完成；獨立抽值52words、303欄位重算及21個保存stage比較吻合，不代表找出唯一kernel原因 |
| 四組 BN folding 診斷 | 原模型各1024筆native／hooked輸出逐位元重現；52組逐層／等輸入比較、4组freeze與狀態digest獨立吻合；最終超限列仍0／7／3／430，未修復export |
| 四組 unfused ReLU 候選 | 初始及 session 保存圖均保留3個BN；BASIC／DISABLED各0/4，超限列2／20／17／447，argmax未變；16組比較與保留性獨立吻合，8個新負結果另存 |
| 四組 unfused 對齊追蹤 | native／插樁端點逐位元重現，120組逐層與16組原端點比較獨立吻合；四組首個數值差異皆為block0.linear，BASIC／DISABLED全部40層比較逐位元相同；尚未隔離局部BN原因 |
| 雙錨定等輸入 BN 診斷 | 36個原生回放逐位元重現，120組比較、92state與12局部圖獨立吻合；IoT第三個BN兩錨21／23列超限，其餘11個BN通過原容差；不能分攤因果比例或宣稱export修復 |
| 論文產物 | 內容核對、真實 PDF build/replay、保留性、9 頁視覺檢查及驗收後覆核完成 |
| 模型與證據副本 | 4,177 檔／18.819 GB；複製與獨立完整 SHA-256 驗證均實際退出 0，保留性與交接覆核通過，見[副本 phase](results/v5_evidence_copy_review_20260922_1srUIm/STATUS.md) |

440 個正式 checkpoint、440 份預測與 84 個 tree 模型保留在原始 run；不只保存 seed 0。副本工具逐檔核對來源與寫入內容後，另一套獨立程式已重新完整雜湊全部目的端 payload；原檔未搬移、未以 hardlink 替代。副本不等於異地備份或包含全部 raw data／系統套件的可移植重播環境，也不是重新推論或重新證明數值結論。

## 必須保留的研究限制

- 固定 benchmark、既有 test exposure、資料來源與泛化限制見新稿；不能宣稱新的未接觸 holdout 或跨裝置／時間泛化已成立。
- 不支持「四資料集全部等效」：差異與等效／robustness 結果須按稿件完整表格分別解讀。
- 17 個 export 負結果不是可隱藏的工程雜訊；軟體 parity 通過也不代表 NPU／實體部署通過。
- 9 頁稿件是完整證據審查版，尚未確認投稿頁數與版型限制；AI-agent 覆核不等於作者簽核或外部認證。
- N6／RA4E1／ESP32 的 v5 板端部署、延遲及能耗尚未驗收。不得引用舊 timing／energy 檔作為新結果。

## 接續與保護規則

每個 issue／phase 都必須經對抗審查、修復與有來源綁定的實際測試；只有檔案存在、程式內寫了 success 或合成測試通過，均不足以判定真實執行成功。需要外部觀察的實際退出與後覆核。

自動化是已固定、已審查 phase 內的執行與檢查，不是無人自動修程式或略過審查。失敗即停、保留原失敗；修復後用新計畫／新目錄明示接續。神經訓練主線曾自動接續資料驗收、選型、440 fits、evaluation 與統計；tree、export、paper、copy 則各用另外審查的階段工具。本輪已完成，沒有背景 supervisor 等待自動發布或刷板。

已完成的 plans／來源／模型／結果保持不變；不要直接重新訓練、覆寫、移動或刪除。舊 `tools/package_v5_artifacts.py` 與 `tools/archive_pre_v5.py` 不適用目前 mixed-origin 證據鏈；原因見[相容性盤點](results/v5_paper_continued_review_20260922_sQdjK1/DOWNSTREAM_RELEASE_GAP_INVENTORY.md)。新版 copy-only 工具須通過自己的 gate，不能以舊工具代跑。

IoT23 QCFS 原 validation row ID `5662534` 已定位到第一段 Floor 跨箱（Torch 3／ORT 2）。固定單一輸出座標雙向替換後，目標樣本對相反 backend 原生輸出的最大殘差為 `1.430511474609375e-6`，原差為 `0.23552179336547852`；全部1024列通過原容差，但不等於逐位元一致。[精確 affine／QCFS 算術核對](results/v5_qcfs_exact_20260922_0BoR5D/STATUS.md)的21個保存中間值重算吻合，不能指定唯一Gemm/FMA累加順序或宣稱runtime違規。

接續的[四組 BN folding 診斷](results/v5_bn_trace_20260922_EJIpEB/STATUS.md)已完成，52組比較未觀察到ReLU啟用狀態翻轉；IoT23第三段完整傳播與等原始輸入局部比較分別有785／207列preactivation超限，不能相減當因果比例。其後的[unfused export 候選](results/v5_unfused_export_20260923_uVH0Au/STATUS.md)也已真跑及後覆核：四張初始圖及八張session保存圖都保留3個BN，但兩種模式仍各0/4。[unfused對齊追蹤](results/v5_unfused_trace_20260923_wMbEyy/STATUS.md)確認四組在block0.linear已有數值差異，首次超出原容差的stage依序為1／4／0／4；不能把首次超限當成唯一根因。

最新[雙錨定等輸入BN診斷](results/v5_local_bn_20260924_rPaQeD/STATUS.md)的50檔及獨立後覆核完成：36個原生回放逐位元吻合，BASIC／DISABLED全部24個等輸入比較逐位元相同；Torch／ORT在IoT第三個BN仍有21／23列超限。固定backend換輸入錨則有915／914列超限，舊傳播比較920列；這些不是可相減的因果成分。下一個最小scope是只讀保存陣列列出全部失敗座標與容差餘量；互補實驗是16個Linear／Gemm含classifier的雙錨定原生回放，兩者尚未執行，需新計畫與審查。原8個候選負結果與原22項矩陣分開；不逐筆補epsilon、不放寬容差、不重訓440 fits以掩蓋失敗。

## 歷史內容與歸檔

先前 README 的全部內容已逐位元保存於[歷史 README 副本](archive/legacy_documentation_20260922/README.pre_manuscript_acceptance.md)，[歸檔紀錄](archive/legacy_documentation_20260922/ARCHIVE_RECORD.md)記錄原 SHA-256。該副本內的相對連結依原 repo 根目錄解讀，舊成果主張不是目前已驗證的結論。

舊 `paper/globecom/`、舊結果及 legacy 實驗程式仍原址保留供追查，不是最新稿件或 v5 數字入口。已固定路徑的證據不能為了清理目錄而搬走；使用新首頁與 phase index 區分目前成果、歷史失敗和未驗收項目。
