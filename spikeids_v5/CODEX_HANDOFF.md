# Codex 接手指令：SpikeIDS v5，不以預期結果代替驗證

## 任務與已交付範圍

使用者要求針對 16 GB RAM／Intel 第14代 i5／RTX 4060 Ti 16 GB 修復 SpikeIDS 的資料、訓練、統計與論文數值流程。本套件是可執行的新版本，不是只留 TODO 的 scaffold。先讀 `README.md`、`audit/REVIEW.md`、`audit/TEST_REPORT.json`；它們共同說明科學方法改變、實際測試與未驗收項目。

查閱的遠端來源固定於 `thc1006/SpikeIDS-MCU` 的 `fd769747c4b0ba84f33bae4d26a8754a7ef80238`。這不是本機工作目錄一定等於該 commit 的保證。十個原始上傳檔的雜湊及修改對照在 `audit/`。不要把原 README 中的「authoritative」「已證實」「最高速度」「IoT一定更好」當成事實。

原始交付曾只驗證 CPU 合成資料；後续已有本機 CUDA、真實來源與 ONNX 工程測試，但被拒絕的資料協定不能產生正式研究結果。歷史 `audit/TEST_REPORT.json` 不代表目前候選版本已驗收。以最新 source-bound 測試與 gate 紀錄為準，不把已存在的測試碼視為已執行證據。

## 目前執行狀態（優先於所有歷史命令）

2026-09-26 最新：SM06 已完成兩次實際上板全1024列驗證（run08、run09），
各5120/5120 FP32輸出字與原QDQ參考逐位元相同，超限與分類差異均0；兩次
輸入／列序／輸出也完全一致。原NSL-KDD QCFS primary seed0 epoch80
checkpoint、ONNX、weights、vectors與容差未改，沒有重新訓練或換seed。
後三層dense真NPU signed24累加＋CPU原始requantization；第一層／QCFS為CPU，
實際7HW＋35SW，不是全NPU。SM05曾因我們的CONVACC路由假設錯誤timeout，
SM06依原始拓撲修正並經實板389個NPU整數累加值逐值覆核；負結果全保留。
最終相關合併測試127 passed；驗收程式另加入錯誤身分、假功耗主張與篡改反例。
只驗收固定模型與1024列數值階段，不等於任意輸入、斷電重啟、最佳效能或功耗。
唯一入口：[三板現況](../tools/board_deployment/STATUS.md)與
[固定模型／韌體selection](../tools/board_deployment/N6_SM06_SELECTION.json)。
目前PPK2／RA／ESP未枚舉，N6 CPU已halt；無功耗擷取daemon。
下一步是SM06專屬量測／marker韌體與host（舊40epoch trace不能套42epoch），
再做原向量parity及實際meter同步量測；尚未完成此下一階段，不報假功耗。
[完整新驗收／實測退出／限制](../results/ppk2_n6_bringup_20260925_nAivHM/N6_SM06_NUMERICAL_ACCEPTANCE_20260926.md)。
下列SM04失敗與更早硬體敘述為保留歷史，由本段特定scope取代；未改動
既有440fits／tree／export／統計及論文驗收範圍。

2026-09-26歷史：SM03已修signed16與zero-point相容性；SM04另修第一層
Conv/Cast尺度錯配，原checkpoint／ONNX／weights／1024列／容差全部不變。
第一層native262144量化值全部吻合。SM04實板run05完成1024列，仍有297/5120
logits超限、81列受影響，分類不同0；不能以分類相同冒充驗收。235tests／47
subtests、另新版host23tests、診斷擴展29tests、saved覆核11反例控制通過。
第一失敗列2656真實46斷點診斷：第一層及第一QCFS全部正確，第二NPU dense
兩值差1量化單位，其中一值跨QCFS階梯造成後續誤差。SM04實際7HW＋32SW，
非舊8HW＋1hybrid＋31SW；保留後三層真NPU，不以CPU logits替代。
下一步研究保留NPU累加精度與原始requantization，尚未部署此後續方案。
CPU暫停、PPK USB未枚舉，無正式功耗、無背景重试。保留所有負結果。
[最新實測／反例覆核／限制](../results/ppk2_n6_bringup_20260925_nAivHM/N6_SRAM_ATTEMPT_20260926_05_REVIEW.md)。
下述SM02／尚未修相容性等敘述均為被本段取代的歷史。

2026-09-26 最新：全域runtime初始化已新增SM02獨立variant、真實編譯及上板。
第三次完整1024列均完成，但5103/5120 logits超出原容差，497列分類不同，
正式數值驗證失敗；保留全部原始負結果，不更新論文或報功耗。
原row20五個硬體斷點真實擷取確認：41輸入、量化、第一段NPU運算均正確，
其後CPU反量化把signed16讀成signed8，24/41值錯；錯讀模型逐位元重現41值。
本機ST3.0 wrapper只選S8/U8與generated signed16不相容，來源／ELF核對支持。
NumPy及獨立scalar保存資料重算一致；181 tests/47 subtests通過。
下一步為獨立相容性修正版及新bundle覆核、全1024列重驗；尚未實作此修正，
不能保證後續無其他問題。CPU已暫停、PPK仍移除，無背景重試或功耗擷取。
[第三次實測與逐階段反例覆核](../results/ppk2_n6_bringup_20260925_nAivHM/N6_SRAM_ATTEMPT_20260926_03_REVIEW.md)。
下述「runtime尚未修正／沒有第三次」為已被新證據取代的歷史。

2026-09-26 本次重新接線後：正確 ST-LINK 已偵測，三筆 Vref 約3.270–3.275 V。
已真實 SRAM 載入／讀回原 GPU 訓練 NSL-KDD QCFS seed0 模型與權重。
第一次在 ACK 前被浮點模式擋下；新增獨立 FPSCR RMode 啟動修正，124 tests／
47 subtests 通過，第二次板上驗證確實只改兩個位元且通過原 FP gate。
第二次模型初始化成功，原第一列 row ID20 只提交一次，但5秒無回覆，退出1；
零完成列、沒有 PARITY／RESULT，CPU已暫停，沒有功耗驗收。
已找到明確韌體缺漏：S6及trace版main漏呼叫全域stai_runtime_init，模型init
不等於runtime init；板上NPU全域時鐘與bus interface控制讀回均0。需新variant
修正、交叉編譯與host bundle覆核，尚未實作／部署此修正；沒有第三次重跑排程。
PPK仍移除，現階段不是要求使用者再改接線。
[本次實測與反例覆核、下一階段計畫](../results/ppk2_n6_bringup_20260925_nAivHM/N6_SRAM_ATTEMPT_20260926_02_REVIEW.md)。
以下USB缺失／0.18 V段落為已被此次新觀測取代的歷史。

2026-09-26 08:40 接線回報後更新：使用者回覆接好了，但工作站沒有ST-LINK
枚舉，20次只讀檢查皆無裝置；最後disconnect為08:37:50。尚未讀到新Vref、
未RAM載入；正在核對電腦線是否位於CN6/ST-LINK，不能沿用改接前0.18 V。
[最新接線後檢查](../results/ppk2_n6_bringup_20260925_nAivHM/STANDALONE_RECONNECT_20260926_02.md)。

2026-09-26：PPK2 已移除，使用者改接外部電源與本機；ST-LINK可見但三筆
目標參考僅0.18167–0.18327 V。使用者確認JP2沒有任何兩腳接通，故需在斷電後
只接3–4/USB_SNK；尚未回報完成，沒有RAM載入。固定模型/平台套件與1024列
離線核對通過，host_sram重測76 tests/47 subtests通過；不是板上推論或能耗。
[本次紀錄](../results/ppk2_n6_bringup_20260925_nAivHM/STANDALONE_PREFLIGHT_20260926_01.md)。

2026-09-25 15:16 硬體新觀測：使用者保留原 JP2 1/2 接線，只換 USB2 插槽；
未執行建議的 JP2 3/4／充電器改接。第5次實際 ON 短測完成（3a3986 / 0，
300032筆），較高量程仍僅名義1.02 ms，末2秒近零；沒有提前軟體關閉輸出。
saved-only 覆核與另一 NumPy 重算一致；PPK 重新枚舉在 OFF／STOP 清理後，
不是前段電流消失的證明原因。使用者隨後已確認本次 LD3 紅色常亮，支持
ST-LINK 供電保護切斷；不等於確定1 A超載、板損或唯一成因。沒有第6次ON。
沒有載入模型／燒錄／正式功耗驗收；[本次完整紀錄](../results/ppk2_n6_bringup_20260925_nAivHM/USB2_FIXED_AM_REVIEW_01.md)。

2026-09-25 硬體部署更新：三板正式量測尚未完成，最新入口為
[三平台狀態](../tools/board_deployment/STATUS.md)。固定原 GPU 訓練 NSL-KDD
QCFS primary seed0 QDQ，不使用 legacy CAN 模型。N6 internal-SRAM 模型韌體與
platform initializer、RA4E1 ELF/BIN/HEX、ESP32-S3 candidate03 的 app／bootloader／
partition images 均已有真實交叉編譯；原失敗紀錄保留。RA/ESP 共用 portable C
在主機真跑原1024列，5120輸出字逐位元吻合，但未冒充板上推論。
N6 是8硬體＋1混合＋31軟體 executable epochs；NPU tracing 已另建獨立診斷
韌體（真實67命令成功、80268-byte BIN、root獨立saved覆核通過），但其新ABI
的host整合／板上執行未完成，不以全部CPU週期冒充NPU週期。第4次實際3秒PPK擷取顯示高電流range
僅短暫出現、末2秒近零，未證明量測路徑持續供電，物理原因未唯一確定。
三板全向量板上驗證／真正NPU執行／GPIO對齊能耗與正式論文表尚未驗收。
此更新沒有改動下述440 fits／84 tree／22 exports結果或放寬容差。

2026-09-24 最新更新：**四組雙錨定等輸入BN已實作、真跑一次、独立後覆核及限定驗收；不是export修復。**
最新入口 `results/v5_local_bn_20260924_rPaQeD/STATUS.md`；決策
`LOCAL_BN_PHASE_ACCEPTANCE.json` whole
`b220b3bb8214c7936754952e1ac9bb55fea83708d7370153aa200a052b52c412`，固定93pins。
root決策前核對4264e7退出0；所有來源／plan／模型／50outputs均HOLD。

固定四原primary seed0 ReLU、各1024筆原validation rows及列序、CPU FP32 batch1/thread1。
Plan whole `c7f7ce0a47311fa9e64dd23c5869287f22958c02fea542d4213acda6a8a57f67`；
report whole `bcf93367808b4e4199270361518a362f028b5e9088caa2dae35d80c1d4c4c1bc`。
真CLI77360／2db040退出0，6.4996秒，唯一一次無重試。直接執行原Torch eval BN，
ONNX精確擷取原BN與常數依賴，保留參數／epsilon各自表示／attributes；不跑完整模型、
不重新export、不改精度或容差。每backend用自身原輸入回放，36控制全部逐位元吻合。

兩種原pre-BN輸入錨下，BASIC／DISABLED全部24比較逐位元相同；Torch／ORT全部48
比較有數值差，但只有IoT第三BN兩錨×兩模式共4比較超限：21／23列各21／23值。
其餘11/12BN在兩錨均通過原容差，不代表逐位元相同。IoT第三BN固定backend換錨，
Torch915列／7858值、ORT914／7840；舊傳播比較920／7887。不能相減為因果比例。
所有120比較正值遮罩與signed-zero-only差異0。最大絕對誤差座標本身都通過容差，
不能把它當21／23失敗的channel位置；未證明唯一kernel／epsilon原因或修復最終logits。

獨立saved-only97800／9e80e2退出0：120完整指標、36控制、92state、12局部圖、
24optimized觀測與103held pins吻合；不載checkpoint／Torch／ORT／producer推論。
Retention15818／215c74退出0：new97inputs／15sources／15installed／50outputs、
trace97／42、U89／26、BN83／22、exact41、diag39／28、4177stat／89namespace／24locks
吻合；253小metadata全文hash，不是18.8GB payload重hash。實際退出收據分開保存，
程式自身exit仍null。Scope peak991436800 bytes、端點swap／事件0，非連續或全機保證。

型別缺口在真跑前修好並通過bool／float反例；原失敗XML保留。每工具source-bound測試、
獨立static、真跑及後覆核見ROOT_PHASE_REVIEW.md；有限AI review不等於作者簽核或無bug證明。
下一最小scope是saved-only列出IoT第三BN全部失敗座標／容差餘量；互補scope是16個
Linear／Gemm含classifier雙錨定回放，需先48native逐位元控制。**兩者未執行，需新計畫與
前後審查**；不可直接套用舊計畫重跑。原440neural／84tree／22exports仍FP32 4/11、
QDQ1/11，原17与候選8負結果分開保留。硬體／NPU／能耗／投稿未驗收。
下列「局部BN尚未實作／執行」是歷史狀態。無背景程序自動接受新scope。

2026-09-23 歷史更新：**四組 unfused Torch／ORT 對齊逐層追蹤已實作、
真跑一次、独立後覆核及限定驗收；不是export修復。** 最新入口
`results/v5_unfused_trace_20260923_wMbEyy/STATUS.md`；決策
`UNFUSED_TRACE_PHASE_ACCEPTANCE.json` whole SHA
`73f2ff24e46e8a4b5e2405d2b131c37ac040df9cc3f95504876a8c05ab6eb6df`。
root決策前交叉核對2de345退出0；来源／模型／plan／42輸出全部HOLD。

固定四原primary seed0 ReLU checkpoint、原1024 validation rows及列序，
CPU FP32 batch1/thread1。Plan whole
`bb3e844ce37a6d14842183a874244ba42dbd9aff342e2f84868ad3d4064ee6fe`；
report whole `7547819e7825ff9e89715ba9ecce5cc42a64b7f46ccb640aa9bc1f564452b83a`。
真CLI41002／5ca157退出0，耗時7.325秒，唯一一次、無重試。重用原初始圖，
只加九個中間輸出；移除後整份parsed protobuf與原圖相同，沒有重新export。
Torch及两種ORT模式的native／插樁端點都逐位元重現各自原baseline。

四組首個位元與數值差異皆block0.linear，首次原容差超限stage依序
NSL1／UNSW4／CIC0／IoT4。BASIC／DISABLED全40層比較逐位元相同，
已補上前階段只有maxabs0的限制；全部120比較正值遮罩與signed-zero-only
差異均0。IoT block2 BN超限920列／7887值、ReLU後801／4921；均是
傳播後不同輸入觀測，不能當局部BN因果比例或唯一kernel／FMA原因。
原端點兩模式仍各0/4，超限列／logits為2／2、20／22、17／17、447／909；
argmax皆0不等於數值gate通過或新accuracy。

獨立saved-only61144／da9fe4退出0：120完整逐層＋16原端點指標、92state、
80圖參數角色、4output-only圖與16optimized觀測吻合，82held pins通過；
無checkpoint／Torch／ORT／producer推論。Retention19242／86291e退出0：
78inputs／12sources／15installed／42outputs、U89／26、BN83／22、exact41、
diag39／28、原4177stat／89namespace／24locks吻合；全文hash212小metadata，
不是18.8GB payload重hash。保存scope peak916017152 bytes、端點swap／事件0，
非連續／全機零swap保證。原report pin和三次actual exit均另存，自身exit仍null。

每個新增工具先有來源綁定反例測試與獨立review再真跑；沒有具體未解決的
本phase問題，不宣稱不存在任何bug。完整邊界與來源見ROOT_PHASE_REVIEW.md。
下一個scope是四臂三個BN的雙錨定等輸入局部探針，以Torch／ORT原pre-BN
輸入各為固定錨，先要求各backend原生BN回放逐位元吻合再解讀；**尚未實作
或執行，需新計畫及前後review**。不直接改epsilon／容差／精度或重訓。
原440neural／84tree／22exports仍FP32 4/11、QDQ1/11；原17與候選8負結果
分開保留，不新增或改寫正式denominator。硬體／NPU／能耗／投稿未驗收，
沒有背景程序自動接受新scope。下列「unfused trace尚未實作」均為歷史狀態。

2026-09-23 歷史更新：**四組 unfused ReLU export 候選已實作、真跑一次及完成
限定驗收；BASIC／DISABLED 各0/4，八個新負結果保留，export 尚未修復。**
最新入口 `results/v5_unfused_export_20260923_uVH0Au/STATUS.md`；決策
`UNFUSED_PHASE_ACCEPTANCE.json` whole SHA
`26a52f0c2817923ef594d139a089f35d0b22021b6a290c0cc4aa4c7f6aa2a1ee`。
root 決策前核對80db4b退出0；所有來源／模型／plan／outputs HOLD。

固定原四個 primary seed0 ReLU 最終 checkpoint、原1024筆validation資料與列序，
CPU FP32 batch1/thread1。Plan whole
`add7be4ddb399199b1addc01b623f00eb44796db0467fb3d9d4c65cfcb75c911`；
report whole `7360188fcaa53a44b9da6b7de03625e42370eb5547cdaec2e4a68362623f2cc9`。
真CLI37381／d64725退出0，報告耗時4.01秒，唯一一次、無重試，完整26輸出。
原模型及 fold_bn=False 副本均逐位元重現原 original logits，狀態digest不變。

四張 initial 與八張 session optimized 圖均為4Gemm／3BN／3Relu；initial80個
參數角色與原始位元吻合，每組23份狀態含3個不輸出為權重的int64計數器。
每模式失敗列／logits：NSL2／2、UNSW20／22、CIC17／17、IoT447／909；
argmax全0。不以argmax不變冒充logit gate通過或新accuracy。兩模式最大數值差0，
尚未以signed-zero敏感比較證明其logits逐位元一致。
圖中沒有觀察到BN被消除；保留BN仍不夠，不能宣稱內部kernel沒有融合或唯一原因。

獨立 saved-only checker d8c1b2退出0：全16組指標、92狀態陣列、80個initial
參數角色與8張optimized觀測重核吻合；49held檔原始pins通過，沒有import
Torch／ORT／producer、載checkpoint或重新推論。保留性91211／9648be退出0：
63inputs／9sources／15installed、前BN83pins／22outputs、exact41、diag39／28、
原4177stat／89namespace／24locks、新26輸出吻合；165小metadata全文hash，
不是18.8GB重hash。真實退出收據與原始report pin另存，自身exit仍null。
保存scope peak669650944 bytes、端點swap／事件0；非連續／全機零swap保證。

前置分析FP64接受、optimized unused-opset處理與global-hook拒絕缺口均修正並
adversarial複測後才真跑；失敗XML與舊runner候選保留。完整source-bound測試、
實際退出、獨立後覆核與限制見 `ROOT_PHASE_REVIEW.md`，不以測試總數冒充獨立證明。

原440neural／84tree／22exports保持FP32 4/11、QDQ1/11、17負結果。
新8個候選負結果不混入原22項denominator。下一個scope是unfused Torch／ORT
對齊中間層追蹤，先要求插樁完整輸出逐位元重現這次baseline，再做等輸入局部
Gemm／BN比較；**尚未實作／執行，需新計畫與前後review。** 不放寬容差、
不逐筆補epsilon、不重訓掩蓋失敗。QDQ／NPU／板端延遲能耗與投稿仍未驗收，
沒有背景程序自動接受下一scope。下列「unfused尚未實作」均為歷史狀態。

2026-09-23 歷史更新：**四組ReLU BN folding逐層／等輸入診斷已實作、
真跑及完成限定驗收；不是export修復。** 最新入口
`results/v5_bn_trace_20260922_EJIpEB/STATUS.md`，決策
`BN_PHASE_ACCEPTANCE.json` whole SHA
`398e4637aa89474c17a4965eb80f4b699abdc192df33e5d22b5b5a7d2fe7c0c5`。
root決策前交叉核對754222退出0；來源／模型／plan／outputs全部HOLD。

固定四原primary seed0 ReLU checkpoint，各資料集原1024 validation rows，
CPU FP32 batch1/thread1。原CLI98451／4ed76c實際退出0，報告耗時7.48秒；
plan whole648bb16a22ffe8a3a64d7c7d9c70903ad0cfdda5061c23da46772a8684d016be，
report whole3c9e0af62ad222dddea2b1842f0495f3702b244ceb1b6ef7a96d5600c50f08ed。
原始與folded模型的native／hooked最終輸出都逐位元重現原baseline。
局部探針均取原始上游輸入，原始分支逐位元重現；不是新完整模型候選。

四組第一個不同的已配對點都是block0 BN／folded affine；52組比較的
正值遮罩均未改變，未觀察到ReLU啟用狀態翻轉。IoT23 block2傳播preactivation超限785列／6065值，
等原始輸入局部為207／234；post-ReLU分別672／3791與88／94。
不能相減當因果比例、指認唯一kernel／FMA或宣稱修復。最終freeze仍為
0／7／3／430列、0／7／3／821logits，四組argmax未變；不是新accuracy。
NSL僅freeze陽性控制，原export後續仍失敗。

獨立保存checker96760／cdf164退出0：全部52組指標、4組完整freeze、
原rowID／fingerprint、每組31參數陣列與兩個狀態digest吻合；無checkpoint
或模型forward。BN eps按固定建構方式核對，未重算folding係數。
保留性12127／e3c451退出0：60inputs／6sources／15installed、前41／39pins、
原4177stat／89namespace／24locks、舊28與新22輸出清單不變。不是18.8GB重hash。
另有獨立解讀及導航範圍核對b522b2退出0。保存scope peak746815488 bytes，
端點swap／事件0；非連續或全機監控。退出收據與後覆核分開保存。

先修好helper ReLU分支呼叫契約，以及savedchecker封裝比較、型別、路徑、
-O與末端檔案變更防護後才真跑；所有失敗XML／舊候選保留。各測試範圍
重疊，不以總數宣稱獨立證明；具體來源與實際退出見各審查報告。

原440neural／84tree／22exports不變：FP32 4/11、QDQ1/11、17負結果保留。
下一個相關scope是另建unfused export候選，沿用原模型／baseline／容差，
驗證graph及backend是否再次folding；**尚未實作／執行，不保證通過。**
其餘FP32／QDQ、板端／NPU／能耗延遲及投稿仍未驗收；無背景程序自動接續。
不得原址重跑、移動原證據、逐筆補epsilon或重訓以掩蓋負結果。
下列「BN診斷尚未開始」是歷史狀態，已由本段取代。

2026-09-22 歷史更新：**QCFS 精確算術 phase 已實作、真跑及完成限定驗收；
不是 export 修復。** 最新入口 `results/v5_qcfs_exact_20260922_0BoR5D/STATUS.md`，
决策 `EXACT_PHASE_ACCEPTANCE.json` whole SHA
`1118c3d99347295e45e4fa2aed7af5fde2a651005a7c98fc86739e97a67cb192`。
root決策前唯讀交叉核對2d7403退出0；來源／plan／結果全部HOLD。

只讀原保存IoT23 QCFS position949／rowID5662534／neuron50的輸入、
folded參數與中間值，不載checkpoint、不importTorch/ORT、不跑模型。
固定plan whole `851c388a13f027e800161c16ef5438768ead6c0a8602a3f404eeffffa8644067`。
真實原CLI190ad1退出0，report whole
`a4ba660d2ea6ff190d798a4789d263d56bc6ac489a8868f1b5f2f9b5b6f5c447`。
實際退出與原report8fieldpin另存；程式report自身exit仍null，未以success自報替代。

精確13項乘积加bias為440717681997132211/4611686018427387904，
高於理想5theta/8邊界6738948531/4611686018427387904。
一次RN-even為0x3dc3b7cd，Torch affine0x3dc3b7ce（+1wordstep）、
ORT BASIC/DISABLED0x3dc3b7ca（-3）；兩backend都不等於一次捨入參考。
從各自保存affine逐步重算21個QCFS intermediates全部逐位元吻合，
Floor維持3／2。不能據此指認唯一kernel/FMA樹、runtime違規或訓練不穩定。

獨立原始抽值af0f32外層與child皆退出0：52words、25stages／14bindings及
完整x／IDs fingerprints吻合。獨立另一RN算法13adb8退出0，303typed欄位
重算相同；比較器12controls7e2c7e通過。保留性ae21ba退出0：13inputs／
5sources／15installed stats、前phasepins、原4177stat／89namespace／24locks
吻合；不是重新全文hash18.8GB。Scope peak202596352 bytes，保存端點swap／
OOM counters0，非連續監控。三份actual review與ROOT_PHASE_REVIEW.md記錄界限。

草稿FP64 Constant隱式转FP32缺口已修；26independent＋15root finalsource
controls通過後才真跑。獨立抽值checker的第三層256／128假設錯誤也先被
正控抓出、修正並4controls通過，再讀真資料；錯稿與失敗XML保留。
這些是工具修復，不表示已改模型或解決原export negatives。

原440neural／84tree／FP32 4/11／QDQ1/11與17負結果未變。
下一個工程scope為BN folding診斷，再處理其餘FP32／QDQ；尚未開始，
不得把本phase驗收繼承成新實驗pass。必須新namespace、固定原模型與
1024validation baseline、前後adversarial review及外部實際退出。
不放寬容差、不搜尋row-specific epsilon、不重訓以掩蓋負結果；硬體／
發布／投稿未驗收，沒有背景程序自動啟動它們。

以下介入及更早文字為保留歷史；其中「精確算術尚未實作」已被上段取代。

2026-09-22 歷史更新：**QCFS 逐層追蹤與九條件雙向介入均完成限定驗收；
不是 export 修復，原17項負結果未改。** 最新入口
`results/v5_qcfs_intervention_20260922_YkeMwN/STATUS.md`，決策
`INTERVENTION_PHASE_ACCEPTANCE.json` whole SHA
`67cc02927e7afbf72dc29005c0840672c588af80828a5f3df34d27efbaac4988`。
root決策核對1d8488實際退出0，所有已驗收來源／模型／plan／outputs HOLD。

前一trace workspace為 `results/v5_qcfs_trace_20260922_mQlmHa/`，
決策whole `de9641330f33490f50fe5f7123e78e9db69f847ba03ad1ea0075a417cb157f92`。
真實23965/c03acc退出0，50組matched stages後核對通過、原1024筆
uninstrumented／instrumented endpoints逐位元不變。第一段affine已有4個
FP32步距差，Floor前Torch3.000000238418579／ORT2.999999523162842，
Floor3／2；第一段QCFS output只在保存座標[949,50]不同。

本次介入沿用同一IoT23 QCFS primary seed0、原rowID5662534及全部1024rows。
Torch／ORT BASIC／ORT DISABLED各跑native／sham／counterpart swap；
只互換該一個post-QCFS scalar，原graph的29個下游依賴節點與8個initializer
逐protobuf保留。`suffix.onnx`只供介入診斷，不是完整可部署模型。
真實session34666/a79cac/09f8d3退出0，report whole
`a640dc92c45bc34789501af66d94a0a5c8027918dc0ca68b8d3460a6856783d7`，
固定plan whole `4e4d44efa477fb14ceb64cc3b4a4f3d2c19565c88daa838317af5115af601002`。
六組native/sham全部1024rows逐位元重現；三swap其他1023rows逐位元不變。
獨立保存checker1f4759、科學重算0dbcdb、保留性068c2a/07f449都退出0。

目標列原maxlogitgap0.23552179336547852；雙向swap對相反native的
targetmaxresidual1.430511474609375e-6，globalmax2.86102294921875e-6
來自未改背景列。所有1024rows都通過原atol1e-6/rtol1e-5，但仍有1018rows／
3427values bitwise不同；不能寫成bitwise一致。23metric objects獨立重算一致。
支持這一固定suffix scalar的局部差異傳播，不是唯一Gemm/FMA根因、
accuracy、普遍穩定性或新holdout證據；沒有讀labels或重訓。

前置三個草稿防護缺口（重複binding、未知condition、錯誤層切點）均有
實證失敗／修復／複測，保留失敗XML。59inputs／11sources／15installed、
前17驗收pins、新14outputs／前9traceoutputs、原4177stat／89namespace／
24locks吻合。Scope peak1108660224 bytes、記錄端點swap/events0，非全機
零swap或連續監控保證。完整來源綁定與局限以本workspace後覆核為準。

下一個已審設計在 `FOLLOWON_DESIGN_REVIEW.md`：以保存的13項FP32
dot operands做精確有理數affine及逐步FP32 QCFS核對，辨別理想邊界與
各步rounding。**目前只有設計，尚未實作／執行。** 必須新namespace、前後
review及實際退出；不搜尋row-specific epsilon，不改theta/L或舊判定。
沒有背景程序會自動進入下一scope／重訓／發布／刷板。440 neural、84 tree、
原FP32 4/11、QDQ 1/11、硬體未驗收等限制不變。

以下export診斷及更早段落為保留歷史，不得据此重啟已完成phase。

2026-09-22 歷史更新：**新增 export 數值診斷完成限定驗收；原 17 個負結果未改。**
新 workspace `results/v5_export_engineering_20260922_sx9DXw/`，入口
`STATUS.md`／`DIAGNOSTIC_PHASE_ACCEPTANCE.json`。這是 post-exposure
工程診斷，不替代正式模型、22 項 export、論文或副本。所有原計畫／
來源／checkpoint／結果與新 28 個診斷輸出 HOLD，不得原址重跑。

原 CLI session55513／completione7647f 實際退出0，11個原 primary seed0
checkpoint、四資料集原1024 validation rows、8現存FP32與4QDQ圖檔，
精確重現原 diagnostic 五項數值與判定。新 report whole SHA
`78fb651012f4416673e0bd95104000d1691f7434e5fe1cbef041deba464d9499`；
固定 plan whole SHA
`184c683896d8b32137d82270491713f71cf9f8f798a6e61749c5bd8461f5dead`。
沒有新圖檔、量化、訓練、閾值變更或 test／label 讀取。

獨立實作保存陣列 checker6e3190退出0，55組aggregate比較一致；
保存陣列解讀4f2f3a退出0，55組worst-coordinate lists核對一致、
12對BASIC／DISABLED logits逐位元相同。保留性915bd8退出0：
4177原檔stat、89原namespace、24locks、148本次inputs、5sources及
28outputs吻合；未重新全文hash全部模型，也不是獨立模型forward oracle。
實際執行／後覆核來源與範圍詳見新workspace，不能僅憑本摘要驗收。

關閉BASIC沒有改善本批結果；14上游負結果＝7模型×2模式，其argmax
未變但仍不過原logit gate，另3項是真正QDQ negatives。IoT23 QCFS
僅保存位置949／原row ID5662534的5個logits超限；最大差0.2355217934，
Floor邊界原因仍未證實。IoT23 ReLU freeze則涉及430rows／821logits，
必須分開處理。下一scope應定位QCFS首個逐層分歧；插樁需保持全部
1024筆原最終logits逐位元一致後，才可解讀intermediates。不改theta／L、
checkpoint、樣本、閾值或原graph。尚未執行此下一scope，無背景自動
重訓／發布／刷板。原FP32 4/11、QDQ 1/11與板端未驗收的限制不變。

以下08:25及更早為保留歷史，不能據此重啟已完成copy或誤用旧命令。

2026-09-22 08:25 更新：**本機完整模型／證據副本phase已完成限定驗收。**
review root為 `results/v5_evidence_copy_review_20260922_1srUIm/`，
決策 `LOCAL_COPY_PHASE_ACCEPTANCE.json` 與 `ROOT_LOCAL_COPY_PHASE_REVIEW.md`，
模型入口 `MODEL_STORAGE.md`、最新導航 `STATUS.md`。這是AI operator根據
真實執行／審查的有界決策，不是human／OS／external attestation。

copy session56178／fa81b2退出0；獨立stdlib全目的端byte auditor
`170949c221efc3c15edd8a7f07b82d4e2491107b7e74527e7eb340b2b7947268`
經author10 selected、lifecycle21、contract13與root CLI11測試後，
真正session37711／55edf8退出0。4177檔、18819342389 bytes全目的端SHA
核對完成，包含440正式checkpoint／440預測／84 tree模型及2 RF ONNX。
report `postaudit_actual_01/COPY_POSTAUDIT.json` whole SHA
`82ea495816258f14037d490a4d55a31fa214f5688bb904792c5d7c6e11774c30`；
外部退出 `ROOT_POSTCOPY_ACTUAL_01_EXIT.json` whole SHA
`238c8a9c6d171c3fb987f9261f484142599d570fb6b941615abb806a9ec8fab5`。
root原來源／copy／audit保留性441728退出0；獨立actual handoff988fcb
退出0，MD `ACTUAL_POSTCOPY_HANDOFF_INDEPENDENT_REVIEW.md` 綁原pins、
4177來源與4177副本stat、16raw、24locks、89原namespace及精確輸出集合。

四個auditor草稿實證缺陷已修並覆核：額外request欄位、installed身份域混入
payload、source pin取樣過晚、parent替換後先在外來路徑mkdir。失敗／中斷
測試全保留，不能用合成tests取代上述真實執行。歷史退出收據的
`copy_phase_accepted=false` 不改；新決策才表達後審查後的限定驗收。
原來源、全部copied payload、工具與審查紀錄HOLD。不要再prepare／copy／audit、
重訓、重export、改閾值／checkpoint、搬檔或使用舊package/archive。

本phase沒有模型推論／新數值oracle；17 export negatives原樣保留。
16raw仍外置，installed metadata／6個ordinary executables不等於完整runtime，
24locks不複製／恢復。同主機副本不是offsite／portable backup。9頁審查稿
不是venue ready，板端／NPU／延遲能耗與release／publication未驗收。
phase內自動化與分階段審查已實際執行；沒有背景supervisor會自動進入這些
未驗收項目。未來工程改動須新namespace、前置／後置對抗review與真實退出。
以下07:56及更早皆保留歷史，不能據此誤判尚待copy或重新啟動已完成phase。

2026-09-22 07:56 歷史更新：**完整副本已真正執行成功，獨立後驗證尚待完成。**
copy review root為 `results/v5_evidence_copy_review_20260922_1srUIm/`，
最新狀態見該目錄 `STATUS.md`。copy-only source `cbd6b0f6…`經作者23、
獨立lifecycle34、science43、啟動wrapper14來源綁定測試通過。
真實唯讀prepare58671退出0，交叉核對40cdd3退出0；正式copy56178退出0
（completion fa81b2），原來源／目的端stat與namespace後檢7a26f1亦退出0。
副本 `results/v5_evidence_copy_20260922_r6_1/` 含4177 payload files、
18819342389 bytes，包含全部440正式checkpoint、440預測、84 tree模型。
`COPY_RESULT.json` whole SHA `42522cce793e31b36648fa70194d3fbeb4f22eb19993b8cfac3f282d0887fbb4`；
外部退出 `ROOT_COPY_ACTUAL_01_EXIT.json` whole SHA
`df3002d91a376d0552f015952bd65636f07262f42b84e69dee106f502aca6298`。
所有原檔與副本均HOLD，不重跑copy、不搬檔、不改JSON內路徑。
這只是copy execution成功，`copy_phase_accepted=false`；另一套stdlib
全目的端SHA／原檔保留性auditor正在對抗測試修正，未跑真實postreview。
不把副本當異地／可移植raw-data+完整runtime backup；16原raw來源仍外置，
24既有lock不複製或恢復，17 export negatives完整保留。
舊07:08及以下記錄為歷史，不得據此重啟已完成稿件或copy。

2026-09-22 07:08 更新：**有界論文產物驗收及獨立後覆核完成，接續完整模型／證據副本。**
review root仍為 `results/v5_paper_continued_review_20260922_sQdjK1/`。
最終publisher `aff318db…`經作者39／獨立lifecycle83（含36作者案例）／科學51
測試通過；已實證context互綁、末端工具域、CLI失敗標記及缺raw stream問題
均修正，失敗XML保留，測試數不相加假稱互不重複。真實唯讀preflight14066
退出0後，原CLI publisher17280退出0，root metadata postcheck72646退出0。
`manuscript_acceptance_actual_01/MANUSCRIPT_ARTIFACT_ACCEPTANCE.json` whole SHA
`40cd24ce40a06a98301eaca15ffe37fb68a75fcd8fb2f7c9ae6f82316e4a4fdd`，外部退出收據
`ROOT_MANUSCRIPT_ACCEPTANCE_ACTUAL_EXIT.json` whole SHA
`1abf7974127a49cccacbef7a417a97c0adff482e0a097c45e55a220cbc6bf726`。
4111份原ordinary pins／344 PDF檔／8候選稿檔／2範本檔／43診斷檔及工具域
保持一致；這不是重新hash全部大模型或第三數值oracle。独立actual-handoff
覆核76589實際退出0（feeae6），報告 `MANUSCRIPT_ACCEPTANCE_ACTUAL_POSTREVIEW.md`
與 `MANUSCRIPT_ACCEPTANCE_POSTREVIEW_ACTUAL_EXIT.json` 綁定真實退出及既有來源；
4111原stat／四namespace／工具域均一致。所有accepted artifacts/source保持HOLD。

新PDF `pdf_actual_02/build/main.pdf`，9頁可讀審查範圍已通過。獨立保留性
session30064退出0；Poppler session10970退出0，兩位AI agents均看完9頁。
不是human author signoff、venue page-limit、publication、release或硬體驗收。
440 neural／84 tree及固定22 exports不變，FP32 4/11、QDQ 1/11，17 negatives
完整保留。沒有重訓、再TeX或模型推論。

下一phase正在另建copy-only工具和攻擊測試；尚未執行真正副本。應保存全部
440正式checkpoint／440預測檔／84tree模型及held evidence，不是只seed0。
逐檔hash副本且保留原路徑／inode／stat；不可用舊package/archive搬動原檔。
副本不等於off-site backup或可移植的完整raw-data／installed-libraries replay。
下列06:25及更早文字都是保留歷史狀態，不可據此重啟已完成工作。

2026-09-22 06:25 歷史更新：**修正版 PDF 真實建置／重播成功，獨立後審查尚待完成。**
review root仍為 `results/v5_paper_continued_review_20260922_sQdjK1/`；最新導航見
該目錄 `STATUS.md`。所有已接受440 neural fits、84 tree fits、統計與22項export
分類不變，17 negatives保留；本階段沒有重訓、模型推論或數值export重播。

可讀版型改為六個完整證據附錄，未改科學數值／canonical tables。原e78 CLI
產生 `candidate_actual_03`（79414退出0、postcheck92414退出0）；獨立d21內容
稽核81079a退出0，核對290 result／53 export宏、完整表格及全文。報告與外部
退出收據：`CONTENT_AUDIT_ACTUAL_03.json`／`CONTENT_AUDIT_ACTUAL_03_EXIT.json`。

PDF owner v3 `b7f1372f…`經作者40／life40／science40前置測試，保留原失敗c8，
修復monitor結束後callback生命週期；v3另綁d21內容稽核器。
root第一次service02命令漏參數，82871退出2，argparse拒絕，未TeX／未建stage；
完整失敗見 `ROOT_PDF_SERVICE_02_ARGUMENT_FAILURE_EXIT.json`。固定launcher
經25項獨立真parser/fake-run測試，另授權service03，不隱藏重試。

真正service03 session34716退出0，invocation `d13162eb02144c0681d6125d3169d137`，
runtime101.585s，四次TeX／replay完成。`pdf_actual_02`為新候選PDF目錄，
`ROOT_PDF_ACTUAL_02_EXIT.json` SHA `d7e6841006a7d0169d506fab543d4ef4486ab0193b972e62fa58e2812c9e69cd`。
root唯讀postcheck77085退出0：344份輸出全hash／3335份輸入stat／38次子程序0
與owner PID消失、installed endpoints一致。這不是完整獨立後審查或視覺驗收。
服務16GiB/swap0，observed peak7022096384 bytes；不代表整台host零swap。

接續獨立metadata-only保留性／strict raw resource replay，通過才執行Poppler
字級、字型、頁面geometry與逐頁圖像審查。舊PDF01不可因新版本成功而改pass。
原 `paper/globecom/` 仍為歷史稿，未升格／覆寫。venue page limit、publication、
release、板端、NPU、延遲能耗未驗收。`DOWNSTREAM_RELEASE_GAP_INVENTORY.md`
記錄舊package/archive不相容mixed evidence及非transitive保護；**不得直接
執行舊封裝／歸檔、補假schema、改來源pin、搬移held模型／cache／review路徑。**
以下05:36及更早段落均為保留的歷史狀態。

2026-09-22 05:36 更新：**真實 PDF owner 首次執行失敗，不能驗收或發布。**
session68301 實際退出1，service invocation `135e363da44e4fd7a78f7d1722ea922c`。
前置實際內容獨立核對已通過；本次四次 TeX build 已產生相同 PDF/text，但
adapter 在資源 monitor 結束後仍呼叫已關閉的 callback，拋出
`ValueError: I/O operation on closed file.`。之前 fake monitor 未模擬此生命週期，
29/33/40 測試及 idle smoke 沒有覆蓋這個真實路徑，不能用測試數量掩蓋。
同review root的 `ROOT_PDF_ACTUAL_01_FAILED_EXIT.json`、
`ROOT_PDF_ACTUAL_01_FAILURE_REVIEW.md` 保存真實失敗與根因；
`pdf_actual_01/` 和 c8 原 owner 全部 HOLD，不重啟、不覆寫、不當正式 PDF。
退出後唯讀檢查46723退出0：3335份原input stat保持一致，四份build captures
無例外，固定27檔build consumer通過（replay=False，沒有新TeX/model），
成功owner report不存在。這些不把整體失敗改成pass。
正在另建 `build_pdf_readonly_v2.py`，補真實／lifetime-aware monitor測試，
由独立lifecycle及science reviewer複審後，才以新namespace明示重跑。
不修改440 neural fits／84 tree fits／統計／17 export negatives／候選稿。
kernel service peak 7,733,796,864 bytes、swap peak0，不代表整台host零swap。
PDF、論文、release及板端/NPU/延遲能耗皆尚未驗收。以下05:04及更早為歷史。

2026-09-22 05:04 更新：**真實唯讀論文候選稿已產生，renderer session55545
實際退出0；退出後檢查50461亦實際退出0。** 新稿在
`results/v5_paper_continued_review_20260922_sQdjK1/candidate_actual_01/paper/`，
不在舊 `paper/globecom/`，後者保持原樣、不得當最新結果。
renderer final SHA `e78c2ab7832f089e0a259dd8035bf2bf39d00e10ced623e4927290fcbd9ccd7e`，
經22作者、57獨立lifecycle、36獨立科學、3範本整合測試實際通過；草稿11個
實證缺口已關閉，歷史失敗紀錄保留。此有界覆核不是絕對無bug保證。
root receipt：同review root的 `ROOT_RENDER_ACTUAL_EXIT.json`，file SHA
`3d2e1ce1b120bb33c581910c98fdab2efa01ab60853cc26b915fc12caa815195`。
候選stage正好8檔，3318份ordinary inputs／50來源／已安裝selected build endpoints
與保留namespace在退出後仍一致；未重訓、未重export、未改原statistics。
manifest file SHA `8c8e02d94353235054f0a183e02d4617a881774b3e038688504e016d75f6996e`，
context seal `fb1801f1ac467831fb1cab37686ccb01f360ea56b1f39a323f8e4ad8d21c434d`。
本步單一scope MemoryMax16GiB／MemorySwapMax0，僅有live endpoint，非完整資源
監測或整台host零swap。原稿與範本、已生成8檔、全部已pin證據均HOLD。
**尚未TeX/PDF建置、尚未論文驗收。** 下一步：獨立真實內容核對；修復並攻擊測試
additive PDF adapter的失敗log保留與外層bookends後，才可雙build＋replay及視覺檢查。
不得使用舊finalizer重寫統計、重啟已完成run、改負結果或搬移既有pinned路徑。
release／boards／NPU／latency／energy仍未驗收。以下04:26及更早段落為歷史狀態。

2026-09-22 04:26 更新：**固定22項 mixed-origin export 的證據／分類phase
正式驗收完成，publisher outer session78173實際退出0。** 驗收檔：
`results/v5_export_continuation_postreview_20260922_mw1Fyh/acceptance_actual_01/EXPORT_POSTRUN_ACCEPTANCE.json`，
kind `spikeids_v5_mixed_origin_export_postrun_acceptance`，seal
`0c8af044e22eb88910a929a07f6dcf491a2a0b6ca7e5af40d677e1a739fcca87`，
file SHA `bef81e350f408dfbf5f9aa7608fd7a2a3afddd059f109f42328c83cd715cf185`。
同root的 `ROOT_ACCEPTANCE_ACTUAL_EXIT.json` 記錄真實退出及出版後檢查。
3314份review/input/output承諾保持一致；正結果5、負結果17，仍為FP32 4/11、
QDQ 1/11，**不是全面parity／部署通過**。原3+新19／negative stages／同validator
重播限制／額外validation exposure與engineering amendment均保留。
驗收器8d288a06…經26作者+23獨立測試實際通過；程序身份、末端namespace及
body duration<=child lifetime的3個實證漏洞皆已修復，失敗證據不刪。
新review manifest whole-file SHA
`0321e23ab1fffbdd6a522264973989752f867970bce6440c56494725db51320e`，
封存4工具／4review roles／55支援綁定／3真實root exits；所有已pin檔案HOLD。

下一phase已開始**開發與合成測試**唯讀論文consumer，root
`results/v5_paper_continued_review_20260922_sQdjK1/`；舊renderer不支援此新kind，
不可繞過或假別名成舊schema。新 `tools/render_v5_paper_continued.py` 尚未簽核，
真正candidate/TeX/原main.tex改寫仍須新phase preflight審查後才可執行。
論文、release、boards、NPU、latency、energy仍未驗收。

2026-09-22 04:02 更新：**真實數值重播22/22完成，外層session59443與child
均實際退出0，約93.429秒。** 以同一已複審的數值validator重新運算，不是
第三套独立算法；原門檻、seed0 checkpoint與fit/validation選取不變，未新增
export、negative worker replay、訓練或test推論。全部比較值與原始診斷一致，
17個negative仍保留；FP32 4/11、QDQ 1/11通過，不等於全面部署成功。
報告 `science_actual_01/SCIENCE_REPLAY.json` 在下述postreview root，seal
`042528acbdabc7bad6c37cd1d32a06d7339543201c609d8baad557a64d274a90`；
外層紀錄 `science_owner_01/`、`ROOT_SCIENCE_ACTUAL_EXIT.json`。
3192份held files、54份新診斷／resource檔；raw93 samples／54.219秒只涵蓋
數值loop，前後hash另有endpoints。kernel cgroup peak8,314,343,424 bytes，
16GiB/no-swap／OOM0；該raw window host另有662次swap-in，非整台host零swap。
source4aa5b19e…、life b06a2e97…、observer87c339cd…皆HOLD；最終51整合測試及
18獨立測試實際通過（有重疊不能相加），原7raw+1lateOOM反例保留。
現在建立／複審同phase的mixed-origin驗收器；尚未出版phase acceptance，
論文／release／NPU／板端延遲能耗均未放行。不可重跑已完成的audits。

2026-09-22 03:54 更新：**真實 lifecycle 事後稽核已通過，但数值重播及
phase 驗收尚未完成。** 新紀錄位於
`results/v5_export_continuation_postreview_20260922_mw1Fyh/` 的
`lifecycle_actual_01/LIFECYCLE_AUDIT.json` 與 `lifecycle_owner_01/`。
外層 owner session **8544 實際退出0**，child退出0；69.126秒，核對
3,185份 held files、39次worker執行（22次原執行與17次固定negative replay），
全部17個negative保留。稽核不反序列化模型，不是fresh numerical replay。
audit seal `237152a77286faa3591c28b19ea3fdea53c3e7e9cf1573614f53db244510d2ab`；
明示外層exit紀錄 `ROOT_LIFECYCLE_ACTUAL_EXIT.json`。life source b06a2e97…／
observer 87c339cd… 已HOLD；119作者整合、79独立、2階段補測及46 observer
獨立測試實際通過（重疊不可相加）。observer原8個publication反例保留，
修後都拒絕。數值重播工具的raw counter／owner／late-OOM漏洞仍在修後驗證；
不得在工具複審完成前啟動真正數值重播，也不得改動44個凍結來源。

2026-09-22 03:43 更新：**明示的 export engineering continuation 已完成
22 項分類、owner session 98042 實際退出 0；尚未完成後 phase 驗收。**
FP32 通過 **4/11**，QDQ 通過 **1/11**，`all_parity_gates_passed=false`。
17 個 negatives 分為 6 個 freeze、8 個 FP32 parity、3 個 QDQ parity；
QD 路徑在前置 gate 失敗不能算量化已執行。全部失敗與固定一次 replay 保留，
原 3 項不重匯出；本次只執行原未開始的 19 項。服务 runtime 11min47.605s，
kernel cgroup peak 6,655,496,192 bytes（約6.20 GiB）／cgroup swap與OOM均0。
raw monitor記錄654筆、645.378秒；不涵蓋所有startup/finalhash。
host在該window有7,407次swap-in、0次swap-out，不能說整台host零swap。
不得將執行完成、正確診斷 negative、或 owner 退出 0 說成全面部署通過。

03:31 啟動紀錄：原 3 項與舊失敗保持原樣，只允許執行原矩陣
未開始的 19 項；全部 22 項均須獨立數值診斷。修復的 distribution/module
版本角色、CF1–CF4b 與測試證據接線缺陷皆有獨立反例／修後覆核。
最終實際 **901 回歸 PASS、370 整合／攻擊 PASS、1 真實遙測 PASS**，
owner sessions 71655／19379／11544 均退出 0，來源快照一致。
它們不代表尚未執行完的真實模型全部 parity 通過。

啟動 review：`results/v5_export_recovery_review_20260922_LBCXZ6/REVIEW_RECORD_CONTINUATION.json`，
seal `d1c3dc06d06dd0e1c348581f5e754147b132ac165c8237f109e8bd920474bfba`；
實際 assembler session 37824 退出 0，綁定 44 個來源與 101 個 supporting 檔。
計畫：`results/v5_export_continuation_20260922_r6_1_recovery1/plan.json`，
seal `8086c0fcdc9f8d0c6a9b4390743534ad72e95b14efaa41c9883f6c1acc951791`，
2,851 個 input pins；freeze session 79919 退出 0。
新輸出：`results/v5_exports_20260922_r6_1_remaining19/`。
**44 個來源、全部已綁定 review／test／輸入檔現已 frozen，不得再修改。**

owner session **98042 已實際退出 0**；紀錄位於 review root 的
`continuation_owner_execution/`。03:31 觀測服務
`spikeids-v5-export-cont-20260922-r6-recovery1.service` 為 active，
InvocationID `a1e6520eb5ee4538ab04064d0ce85f3e`、MainPID 1512150；
單一 cgroup MemoryMax=16 GiB／MemorySwapMax=0。
TMPDIR=`/var/tmp/spikeids-v5-export-cont-runtime-20260922-A967JQ`。
不得重啟相同 plan、刪除 successor registry 或用 completion 存在代替實際 exit。
原兩個數值 negatives 不能改成 pass；matrix 完成可以仍有 negatives。
目前等待完成後 lifecycle 與 fresh same-validator 數值重播於
`results/v5_export_continuation_postreview_20260922_mw1Fyh/` 另行審查，
該處開發中的 auditor 還不是驗收。paper／release／boards／NPU／energy 未放行。

2026-09-22 02:40 歷史更新：**神經匯出 r6_1 已因工程驗證錯誤停止，未驗收，
不可重啟舊 plan。**正式 owner session 90285 實際觀察退出 1；服務
`spikeids-v5-export-20260922-r6-1.service` 的 invocation 為
`b6d68bd812df4fbca0b9a983987f5310`。原 controller 位於
`results/v5_export_continuation_20260922_r6_1/`，輸出位於
`results/v5_exports_20260922_r6_1/`。前兩項 NSL ReLU FP32/QDQ 均在 FP32
allclose gate 失敗且固定一次 replay 完全相同；class disagreement 為零不能
代替數值 parity 通過。第三項 NSL QCFS FP32 worker 退出 0，但獨立 consumer
誤將 distribution version `2.10.0` 與 module version `2.10.0+cu128`
直接比較，於 `Export policy mismatch: torch` 停止。其餘 19 項未執行。
這不是 22 項完成，也不是量化、NPU 或部署通過。

`results/v5_export_recovery_review_20260922_LBCXZ6/FAILED_EXPORT_HISTORY.json`
保存失敗執行與 2,740 份輸入的完整 hash/stat 邊界，seal
`4b5e6c6b773856a0bff9ac7786d183acf8061daaf4b70dc5b8c41de4e52fa9f2`；
history writer session 42542 真實退出 0。原 40 個來源、105 個啟動審查檔、
原 failed work/output/owner/registry、神經 1,027 檔與 tree 259 檔均不得更改。
不要刪 registry、改既有 source、去掉 CUDA version 後綴或放寬數值門檻。

02:40 當時正在另建明示的 engineering continuation：保留原 3 項、不重匯出，
以精確 distribution/module/build 分欄驗證原輸出，只在新 namespace 執行
尚未開始的 19 項；新 successor claim 一次性且不可重用。新工具
`tools/continue_v5_exports.py`、`export_v5_continuation_runtime.py`、
`export_v5_continuation_science.py`、`export_v5_build_identity.py` **仍為開發中，
未簽核、未 freeze、未啟動**。不得僅因檔案存在就啟動；要等 source-bound
攻擊測試、独立審查與新 launch record。完成後還須 phase post-review，
paper/release/boards 仍未放行。既有 440 neural fits 與 84 tree fits 驗收不變。

2026-09-21 23:52 接續狀態：**r6-recovery1 的神經網路／統計自動鏈已於
16:19:48（Asia/Taipei）完成，440 fits 與 evaluation 全部完成。**
`results/v5_research_continuation_20260921_r6_recovery1/complete.json` 記錄
16 個階段通過；同名 user service 已結束，不要重新啟動它。
正式神經結果位於 `results/v5_run_20260921_r6_recovery1/`，原先的
primary／replica、checkpoint、prediction、plan、cache、source 全部原地保存。
獨立程式驗證報告檢查 440 checkpoints、440 prediction artifacts、22 executions，
差異與等價統計已產生。這不等於整個專案、論文或板端已驗收。

使用者要求完成後再次 max-rigor adversarial review，並且修完阻擋問題才可
進下一階段。本次 lifecycle／science／tree adapter／controller 的有界覆核
皆通過，記錄在 `results/v5_postrun_review_20260921_BtSToy/`。**固定 84-fit
RF／XGBoost 已完成並通過完成後覆核與驗收；神經 exports／paper／release／
硬體仍未放行。**不得以本段完成摘要代替後續簽核。
新結果不能支持歷史「四資料集皆無差異／皆等價」的說法；不得看完結果後
改 seeds、margin、模型或前處理來修飾結論。同環境重現不證明跨平台重現。
下方所有「尚未訓練」「目前正在驗收」均為有日期的歷史紀錄。

本次已重新 hash 全部 2,239 份原完成證據、驗查全部 440 checkpoints／
prediction artifacts、重算統計；另用 11 個 primary seed-0 模型重新執行
完整 test forward，logits／機率／預測逐位相同。未發現需要重訓神經模型的
具體缺陷；這不是所有 440 個模型都重新 forward，也不消除歷史 test exposure。
IoT 的大幅跨 seed 變異是真實結果，不得用挑 seed／checkpoint 改寫它。

新 tree 修復以 `tools/tree_v5_runtime.py` 與 `tools/run_v5_tree_stage.py`
實作，沒有改寫 26 個 frozen 科學來源。修復 RF 匯出 reference/ORT 設定不一致、
實際 fitted model budget 驗證、同一 aggregate cgroup、完整來源閉包、
same-FD/晚期證據變動等問題；TC-1 至 TC-5 的反例與舊失敗全部保留。
最終主線 **901 PASS + 151 攻擊 PASS**（各實際退出 0），另有獨立 165 項
controller/resource 與 51 項 adapter science 測試。8 項既有 ONNX 棄用警告
沒有隱藏，也沒有為消警告升級已固定環境。精確簽核是 `REVIEW_RECORD_TREE.json`，
seal `fd3b08623a40c0329603349e31f2d166e7c6bc955aa861700bf0b6214c45220a`。

本輪 tree 控制 plan：`results/v5_tree_continuation_20260921_r6_1/plan.json`，
seal `599f1925dd36219f45b8f5b25450c5608b328d56ddc43a8d70e215edee5be38f`，
固定 2,333 pins，模型輸出 `results/v5_tree_20260921_r6_1/`。只做 NSL／UNSW，
各 20 RF seeds＋1 XGB seed，primary／replica 共 84 fits；100 trees／rounds，
CPU 16 threads。23:32 啟動 user service `spikeids-v5-tree-20260921-r6-1.service`，
InvocationID `1b98127136314c17b2750cd2c98ab9f4`、MainPID 1161038。
單一服務 cgroup 包含 controller 及 verifier 子程序，MemoryMax=16 GiB，swap.max=0；
這不是整部實體 16 GB 機器的證明，也不追溯授予旧 neural 相同 aggregate 主張。
NVMe TMPDIR：`/var/tmp/spikeids-v5-tree-runtime-20260921-mS0HcP`。
全部 fits／replica／test／兩份 RF ONNX、獨立 verifier 與 resource replay 已通過，
23:39:30 完成；owner session 65331 實際觀察 service 退出 0，runtime 399.856 秒。
`TREE_OWNER_EXIT_OBSERVATION.json` 保留實際退出證據；active 或 GC 後預設
ExecMainStatus=0 不能代替它。服務已結束，不會自行進入 paper。
不要重啟相同 plan 或修改它綁定的任何來源、測試、review、資料及模型。

本階段完成後又獨立重算 **全部 84 模型／42 pairs／完整 test rows**（3,182,382
model-row evaluations），與正式獨立報告完全一致；另完整核對 **2,602 檔**、
2,333 舊輸入未變，259 scientific tree artifacts 保存齊全。全部 519 raw resource
samples 通過重播；aggregate cgroup 峰值 7,428,460,544 bytes（6.918 GiB），
cgroup swap/OOM=0；host 有 99 次 swap-in，不得稱整台電腦零 swap。
正式 raw monitor 364.603 秒，不涵蓋所有 startup/final-hash 時間；完整 service
仍受同一 kernel cgroup cap，另保留端點／sticky events／journal peak。
9 項實際 trace controls 與 14 項驗收工具 controls 均實際退出 0。

23:52 正式驗收：`results/v5_postrun_review_20260921_BtSToy/TREE_PHASE_ACCEPTANCE.json`，
seal `005cfff750a37a19a2c1dc7f26a03863e666e7a8ecb31199fb0827f50fc65e9c`，
檔案 SHA `847660d87bcbafff5b32566fb9702a488f9694b751112bbe8f3aae0195fb1cb8`。
詳細證據見 `POSTRUN_TREE_SCIENCE_REVIEW.md`、`POSTRUN_TREE_LIFECYCLE_REVIEW.md`、
`TREE_ACCEPTANCE_WRITER_REVIEW.md`。最後一份另澄清：local pre-frozen resource
gate **不是公開或獨立的 preregistration**。producer ledger 1/1 只描述其一次
formal evaluation session，獨立 verifier／audit 也會讀取 test，不能宣稱研究史
只碰 test 一次。XGB 每資料集只有一個 primary seed，不能虛構 SD=0。

下一關是神經模型固定 22 項 ONNX/QDQ attempts 的來源／checkpoint／calibration
前置審查，之後才可執行。新接受的 CPU RF ONNX 不代表這個矩陣、INT8/NPU 或
MCU 已通過。再後面是只讀 paper consumer、完整 robustness/discordance 呈現，
以及保存新增 controller/adapter/exit/resource 證據的 release/archive consumer。
不要在這些 gates 未通過時直接跑舊 publication 或 archive 指令；本輪沒有移走
原模型、刪除失敗紀錄、提交 git 或推送外部。

本次覆核新增的後續執行禁令：**不要對已完成的 r6 run 直接執行
`spikeids_v5/finalize_all_det.py`。**其目前會 atomic 重寫三個已固定
SHA/stat 的統計檔，即使內容相同也會破壞原驗收的 inode/mtime 證據。
paper phase 必須使用另行審查的只讀統計 consumer；原工具與原結果暫不改。
正文還須完整呈現八項 primary／robustness／discordance 結果，不能只留
primary 表格。這些是尚未放行的 publication gates，不是改訓練結果的理由。

2026-09-21 09:02 歷史啟動紀錄：**新的一次性背景自動
接續服務已啟動，正在重新執行完整資料驗收；正式 GPU 訓練尚未開始。**
服務為 `spikeids-v5-research-20260921-r6-recovery1.service`，controller PID
389185、InvocationID `af016a970fd74eafb2b8e886a5d4a134`；驗收 worker
389437、真正 verifier 子程序 389597 已觀測到執行。
新 plan：`results/v5_research_continuation_20260921_r6_recovery1/plan.json`，
seal `8c109cd88b09688e55bacba7f9770fd1e25e52057469c76ed4a001b218efbeb1`。
helper SHA `c28203b83fbd22e350e9c1c0ce66833fed4fb3dd56e0edb220b3e0254b44fd1c`。

流程固定為新 full acceptance → 資料 gate → 60 profile fits → 66 worker
fits → 凍結正式配置 → 220 primary + 220 replica fits → 唯一 evaluation
stage → 統計與獨立驗證。每個階段驗收失敗即停，沒有自動重試或 reboot
resume；不用再發一則訊息才進下一階段。這是程式化 validators，**不是
聲稱未來每階段都已有真人／AI 對未知結果做過 adversarial review**。
此自動鏈不包含 tree／exports／paper／release／板端測量。

最終完整回歸 **859 PASS、0 skips**，172.15 秒，8 個既有 ONNX 棄用警告；
主線實際退出 0。另由主線重跑獨立攻擊模組 **45 PASS、實際退出 0**，
第二獨立審查的 90 個科學/API controls 也通過。報告、歷史失敗與來源快照
在 `results/v5_research_continuation_review_20260921/`；全套 JUnit 是
`root_full_regression_05.xml`（SHA
`8ea3a022b04b3b7c88b4a2568cc53d347f73067741fb9ac2bd83925ca2938954`）。
這些是工程實作驗收，不是未來真結果已通過。

原 r6a/r6b 建置與結構校验皆完成；原 acceptance 在 08:31 收到 SIGBUS
（子程序 -7，原接續 session 43094 實際退出 1）。舊 `failed.json`／全部
收據保留，沒有改成成功。同期 `/tmp` tmpfs user quota 耗盡是合理診斷，
但沒有 core backtrace，不宣稱已證明精確原因。新流程重驗了原 raw/source
及兩 cache 的完整快照，保留 275 個前置證據檔；不重建／改寫原 cache。
新的驗收必須從頭跑完，只有新的 acceptance 通過才會開啟 qualification。

新 TMPDIR 為 repo 外 NVMe
`/var/tmp/spikeids-v5-recovery-runtime-20260921-u0aXsd`，env 與 Python 選擇
皆驗證，非 `/tmp`。每個 stage 16 GiB／零 swap，controller 另有獨立上限；
這不是總和 16 GiB 或實體 16 GB 整機的驗收。帳號 Linger 已設為 yes，
讓 user service 可在登出後持續；未做實際 logout／reboot 測試。
訓練／選型預留目錄皆為 `results/v5_{profiles,workers,run}_20260921_r6_recovery1`。
**勿再啟動相同 plan、修改 pinned 程式／資料／版本或使用這些預留輸出目錄。**
即時 phase 看新 work 內的 `continuation.log`，失敗看 `failed.json` 與
各 stage 的 exit/log；檔案存在與 active service 本身不代表驗收成功。

使用者最新要求是「先把問題找出並修復，再統一重跑」。目前正式重跑尚未開始。

2026-09-21 接續更新（優先於下段歷史狀態）：G0 終止上界及獨立逐輪 replay
已修正並通過 bounded review。真實 r6a NSL/UNSW 又揭露 verifier 的來源追蹤
缺陷：reason-3 重複列的 canonical test 代表可因 train-overlap 被 reason-2 排除。
現以 fresh raw `(X,label)`、official role 及已重播的 component 證明此排除，
且不把被排除來源錯算進 retained-test multiplicity。61 項 focused tests 及
獨立 adversarial review 通過；`verify_r6a_protocol_lifecycle_02.json` 確认真
NSL/UNSW 全部逐資料集 gates 通過（UNSW 18 輪）。01 失敗紀錄仍保留。
這只涵蓋兩資料集／一份 cache，`data_acceptance_passed` 仍為 false。
r6a 四資料集已全部建立完成（57:05.39，主線 session 81451 實際退出碼 0）。
後續四資料集結構校驗也已通過；獨立 r6b 正在建立。全四資料集雙重建與
完整 raw replay acceptance 仍未完成，不可提前訓練。

接續測試：目前已執行 676 項回歸，全部通過、無 skips（127.98 秒；8 項
既有 ONNX exporter deprecation warnings）。證據為
`results/v5_review_20260921_aqHrbg/post_lineage_performance_tests.xml`，SHA-256
`113bd1c4fc58096d1ffec09274668de4584ca9c7bfac04b5d013742b5ca56514`。
這批不包含當時仍開發中的 `test_data_continuation.py`，不是接續工具驗收。
效能 qualification 的 113 項 focused tests 與獨立 5 個正常／5 個攻擊
案例已通過；60/66 次真資料 GPU qualification 本身尚未執行。

上述測試之後已再完成包含接續器的完整 **745 項回歸**：全部通過、無 skips，
132.75 秒，8 項相同 deprecation warnings；最新證據改以
`results/v5_review_20260921_aqHrbg/post_continuation_tests.{log,xml}` 為準，
XML SHA-256 `1c6c84c1c5702ea7e5bf30837acda04abb8c0187492004a0d8a7d736fa489c2f`。

資料接續器已通過 69 項測試及獨立 10 個攻擊／1 個正常流程案例，實際
計畫位於 `results/v5_data_continuation_20260921_r6/plan.json`（seal
`a4eb35b28a7de300c889dece2e225f82cf07fcfbabefd1a7a4748751daa7f600`）。
`run` 已啟動；r6a 原 PID 183207／主線 session 81451 已真實退出 0，
主線已記錄 `a_exit.json`，不可再補寫或覆蓋。`check_a_exit.json` 為 PASS，
peak 4,085,276,672 bytes、swap 0、OOM counters 0，接著已啟動 fresh r6b。
完整進度在同目錄 `prepare_b.log`／`continuation.log`；不能從 metadata
存在或 scope 消失推定程序成功。
接續器僅依序 check A → fresh r6b → check B → independent acceptance，
不會啟動訓練或自動重試。來源與原始資料已固定，勿修改 pinned Python 檔。

r6a CICIDS2017 已在第 7 輪（iteration 6）達零新增合併；fit/validation/test
分別 1,407,599／351,901／439,877，metadata 報告 final-FP32 跨 split overlap
均為 0，仍待完整獨立重播。直接讀取標籤核對 Heartbleed 只有 6／2／3
個 retained patterns；稀有類不確定性必須揭露，不能把 seed 間變異當成
新資料的泛化證據，也不因此事後調整 split 或訓練選模政策。

使用者亦已明確授權直接連接開發板、測試與實驗；不再把未授權刷板當作
既有阻塞。仍須選定 probe/target、保存可讀取韌體與設定、驗證確切寫入區域，
不得自動解除保護或更改安全 option bytes。初始連線／備份紀錄在
`results/v5_hardware_20260921_7dMGgC/SESSION.md`；它不是 v5 正式部署結果。
該 session 已保存 N6 外部 Flash 128 MiB、ESP32-S3 Flash 16 MiB、
RA4E1 Code Flash 512 KiB 的雙次完整且 byte-identical 備份，並經獨立覆核。
RA4E1 Data Flash 雙讀不一致，仍未驗收；不得據此寫入 Data Flash。
既有 RA4E1 韌體 reset/re-run 的 1,000 次 cycles 雙次吻合，只是舊 CAN
模型工程證據，沒有 v5 checkpoint、獨立時脈或能耗驗證。

歷史真資料 gate 失敗（已由上方修復狀態接續，仍保留失敗證據）：531 項回歸與 r6 合成 44 fits 曾通過，
但 fresh r5a cache 在 UNSW 的第 8 輪 collision closure 被不合理上限截斷。
獨立診斷確認原算法需 18 輪才達 fixed point，所有步驟均為嚴格合併；
診斷刻意不出版 cache。另發現舊獨立 verifier 未重播固定 SGKF fold 與歷史
collision unions，可能接受分割規則不符的資料。兩者正在修正與重驗，不能
用先前 531 passes 覆蓋新問題。現行新增的 producer 終止上界來自初始群數 G0；
正式 acceptance 還必須有 `frozen_partition_and_closure_replayed` 全資料重播。
**r5a 部分 cache 未驗收，不得訓練；下一輪 raw audit／兩份 cache 必須重新建立。**
詳見 `results/v5_review_20260921_aqHrbg/` 的失敗、診斷與回歸紀錄。
2026-09-20 r1 已依使用者授權送出 SIGINT 並確認所有該 run 程序退出；
保留 366 個已完成 fit、369 個 checkpoint（含未完成 fit）、log 與原始碼快照。
詳見 `results/v5_run_20260920_r1/STOPPED_NONFORMAL.md`。r1 永遠不是正式結果。
GPU enforced/default power limit 已核對為 165 W，沒有更改科學訓練參數以續跑 r1。

修正候選已合併至工作樹，後續獨立 review 修補也以工作樹為準；
`/tmp/spikeids-v5-next-2ZQsR7/spikeids_v5` 現為過渡期快照，不得覆蓋最新檔案。
必須完成靜止來源下完整測試與合成端到端驗證，然後重做 raw audit、兩份獨立 real cache、
`tools/verify_v5_data.py` acceptance，才可 freeze。舊 r2/r3/r4 不可升格。

新協定採 exact-input-group-disjoint unique-labelled-pattern estimand、
fit-only normalized square-root inverse weights、fixed final epoch；validation
僅供診斷。正式執行需新的 cgroup v2 scope，`MemoryMax=16G`、
`MemorySwapMax=0`，且驗收原始 resource trace。這是程序群記憶體預算，
不是聲稱已在實體 16 GB 整機（含 OS）驗證。範例 scope 僅能在新 plan
全部前置 gates 通過後執行，不能照抄舊 freeze/run 指令。

## 2026-09-21 adversarial-review errata（優先於下方原始步驟）

後續實機稽核推翻了本 handoff 的部分前提；不得照抄舊命令後便宣稱
完成。現行 gate 以 `audit/ADVERSARIAL_REVIEW_20260921.md` 與
`audit/DATA_PROTOCOL_GROUP_DISJOINT_20260921.md` 為準：

- 舊 row-ID split cache 存在大量 exact model-input cross-split overlap，且
  CICIDS2017 的兩個 physical `Fwd Header Length` 欄位被 pandas 自動改名
  後重複輸入。舊 audit/cache/run 全部只可作 non-formal engineering
  evidence；正式流程必須先完成 labelled-pattern dedup、exact-X group split、
  final-FP32 fixed-point collision gate 與兩次 byte-identical real cache build。
- 稀有類 inverse-frequency weighting 與 validation-best selection 對 CIC 的
  1--2 個 validation 樣本過度敏感。正式候選政策改為 fit-only normalized
  square-root inverse weights與 fixed-final-epoch selection；仍須在修正後
  supports 上重新凍結並驗收，不能沿用下方舊的 validation-best 預設。
- 單 job `--stage all` 可繞過全域 test barrier；正式 runner 必須綁 sealed
  plan、execution role 與完整 fit verification，且 exactly one authorized test
  session。未完成此修正前不得啟動新的正式 440-fit run。
- 2026-09-20 r1 已停止並保留工程診斷，但因上述資料問題永遠
  不可升格為論文結果。任何新正式 run 必須使用新的 cache、plan 與 run
  namespace。

## 必須維持的工作規則

保持原專案 `src/`、`scripts/`、舊結果與正在跑的訓練不動，把整個 `spikeids_v5/` 放在原專案根目錄下。本套件的 `models.py` 是隔離 runner 使用的三個模型，不是原專案所有 FlexMLP／匯出相容類別的替代品。不要逐檔覆蓋原 `src`。

先確認本機 git HEAD、工作樹差異和現有 process，但不得自動停止任何 process、改 GPU/CPU 時脈、刷板或重啟設備。不要修改原本 in-flight `experiment_multiseed(1).py`，不能改 source hash 來強行 resume。也不得自動 commit／push。環境使用既有 `.venv` 或 `uv run --no-sync`；不自動升級 torch/CUDA、不把 CPU wheel 換入 GPU 環境。

上段為原始交接權限；後續使用者明確授權的 r1 停止及板上測試，以本檔頂部
接續更新為準。授權不包含任意停止無關程序、整機重啟或解除晶片安全保護。

不採用固定期望 OA/F1 作為測試條件；不為了通過 TOST 改 δ、刪 seeds、改檢定家族、重排 pairing、隱藏未定義指標。任何新結果推翻原文，也應保留並忠實反映。

## 按順序執行

### 1. 核對本地版本與環境

確認套件完整性，保留 `audit/SOURCE_INVENTORY.json` 與 `SHA256SUMS.txt`。閱讀目前 Python、torch、CUDA runtime、driver、GPU型號、OS、RAM/VRAM可用量；結果保存為本次實驗的環境紀錄。`uv run --no-sync python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available())"` 必須在正式 GPU 執行前成功。

執行 `uv run --no-sync python -m pytest spikeids_v5/tests -q`。若缺 pyarrow/onnx/onnxruntime，使用指定環境的 `uv pip` 安裝相容且明確鎖定的版本，再跑被跳過測試；安裝或升級後應先完成驗證，才做 `freeze`。GPU 測試檔會在有 CUDA 的環境解除 skip，但仍需 suite 的完整20seed GPU重跑。

可重跑獨立合成整合驗證：

```shell
systemd-run --user --scope --unit=spikeids-v5-integration -p MemoryMax=16G -p MemorySwapMax=0 uv run --no-sync python spikeids_v5/tests/run_integration.py --work-dir results/v5_synthetic_integration
```

這會產生44次兩個 epochs 的小型 CPU 訓練，不是論文結果。需新工作目錄，不能拿合成資料混入正式 cache。

### 2. 先審資料，再準備正式 cache

核對四資料集的原始檔名、實際列數、特徵順序、label mapping、來源與版本／下載校驗。特別核實 UNSW training/testing 檔的實際角色與 schema，不依大小交換。IoT 的 HuggingFace preprocessed 資料不能自動視為無上游洩漏；確認 categorical 是否仍是原始字串、是否先前對整體資料做過 imputation/encoding/filtering/dedup。

CICIDS／IoT 的 row split 不等於 capture/device/time holdout。確認論文要聲稱什麼。若要未見設備／場景／時間泛化，必須取得來源 group IDs 並另建分組/時間協定；不能從缺失 metadata 猜 group。不同 capture 的 attack classes 可能不齊全，不能為了讓現有15class檢定通過而事後調組。此功能不是本交付假裝已完成的部分。

原完整資料可用後：

```shell
uv run --no-sync python spikeids_v5/suite.py prepare --data-dir data --source-spec-dir spikeids_v5/audit/source_specs --raw-audit results/v5_corrected_audit/data_audit.json --cache-root results/v5_corrected_cache_a
```

檢查 metadata 的 fit/validation/test row IDs、未知 category 計數、非有限值處理、features/class_names，評估合理性但不看 test 準確率調前處理。官方 training 使用20%validation／20260920，不是舊15%／12345。所有模型共用同 cache；必要的政策變更必須進新版本、測試與新 cache。

### 3. 在本機量測效能，不能以名稱判定最快

使用 README §4 的 `tools/qualify_v5_performance.py`：先固定 60-fit profiles，
再固定 66-fit worker 比較，兩階段皆需 fresh 16 GiB/no-swap scope 與已驗收真
cache。完整事件、raw telemetry、checkpoint elapsed 與重現 digest 必須一致；
任何候選失敗使整次 qualification 失敗，不准刪失敗候選再排名。只依 wall
time 選，不依 validation/test 成績。舊 `benchmark_profiles.py` 的獨立診斷
不能代替此 gate；短測也不證明全部 seeds／正式 epochs 必然重現。

記錄 RAM RSS、VRAM峰值、GPUdriver、作業系統、背景負載、電源/散熱狀態和完整 log；本套件不自動修改功耗或時脈。16 GB RAM 不是已實測的硬上限保證。GPU不夠用時不可悄悄改batch/precision，應先排查或另立明示的配置。

### 4. 確認研究協定並凍結

預設是20seeds、11組，IoT40ep/batch1024，其餘80ep/batch512，hidden256，L4，**shifted_v1量化ANN**。使用 fit-only normalized square-root inverse weights 與 fixed-final-epoch checkpoint；每10epoch與最後一次validation僅供診斷，不選模型。

把 corrected QCFS 的+0.5 shift當成新方法版本，不把舊checkpoint載入新公式。原舊floor公式僅透過另一份顯式`legacy_floor_v1`協定診斷。本 suite 不宣稱 trainANN=T1SNN。

差異檢定14個與等價檢定8個各一個家族；各做Holm，不聲稱聯合22個familywise0.05。δ=1pp是本次freeze記錄，不是假造舊投稿的預先註冊。確認研究問題需不需要同一家族更嚴格控制；更改需在正式訓練與test曝光之前完成並重測。

```shell
uv run --no-sync python spikeids_v5/suite.py freeze --cache-root results/v5_corrected_cache_a --raw-audit results/v5_corrected_audit/data_audit.json --data-acceptance results/v5_corrected_audit/data_acceptance.json --run-dir results/v5_run --device cuda --optimizer single --threads 4
systemd-run --user --scope --unit=spikeids-v5-formal -p MemoryMax=16G -p MemorySwapMax=0 uv run --no-sync python spikeids_v5/suite.py run --run-dir results/v5_run
```

`single`是保守示例；已量測確認的其他backend可在freeze時明示。新的所有頂層`.py`來源、環境、資料指紋和超參數凍結後不要修改。若需要修code，另立run目錄，不竄改原manifest。

### 5. 完整獨立重跑與 test 開啟條件

suite先完成所有11組primary，再完成獨立replicas；訓練weight／optimizer／scheduler／RNG／batch order一致後才准許test。20seeds為220次fit，兩套共440次。`verification_fit.json`和`verification_evaluate.json`必須通過。低階fit可在exact identity下resume；正式resource驗收不接受刪除失敗trace或重設test ledger冒充乾淨執行，詳見README。

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
