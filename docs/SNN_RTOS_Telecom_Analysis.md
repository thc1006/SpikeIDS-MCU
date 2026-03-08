# SNN x RTOS x 電信邊緣安全 — 深度技術分析與競賽適配性評估

> **分析日期**: 2026-03-08
> **競賽**: TRON Programming Contest 2026
> **主題**: TRON x AI — Utilizing AI
> **硬體**: STM32N6570-DK (Cortex-M55 + Neural-ART NPU 600 GOPS)
> **核心問題**: SNN 能否透過抽象化技術部署到傳統 NPU，並為電信領域做出貢獻？

---

## 一、抽象化突破：為何 DPDK / SR-IOV 哲學改變了整個技術判斷

### 1.1 DPDK 哲學 — 繞過高層抽象，直接控制硬體

DPDK 的核心不是某個軟體庫，而是一種設計哲學：**繞過高層框架的限制，直接與硬體對話**。

在 Linux 世界：
```
傳統路徑: NIC → kernel driver → socket API → 應用（慢，有 context switch）
DPDK 路徑: NIC → user-space PMD → 應用（零拷貝，直接 DMA）
```

**在 STM32N6 世界的等價映射**：
```
傳統路徑: 模型 → ST Edge AI Suite → 標準 CNN pipeline → NPU（被框架限制算子）
DPDK 路徑: SNN 模型 → 自訂算子分解 → LL_ATON 低階 API → 直接驅動 NPU MAC 陣列
```

**LL_ATON 就是 Neural-ART 的「user-space driver」**。RescueBot（2025 學生組優秀賞）的原始碼已經證明它可以繞過 ST 標準工具鏈，直接控制 NPU 的推論排程。而且 Neural-ART 支援 **Runtime Loadable Models**（`ll_aton_reloc_install()`），可以在運行時動態載入不同模型——這就是 NPU 層面的「熱插拔」。

### 1.2 SR-IOV 哲學 — NPU 資源分時複用

SR-IOV 的核心：一個物理設備虛擬化為多個虛擬功能，各自獨立運作。

**應用在 Neural-ART**：
```
µT-Kernel 任務 A: 載入 SNN 特徵提取模型 → NPU 推論 → 卸載
µT-Kernel 任務 B: 載入 SNN 時序分類模型 → NPU 推論 → 卸載
                  ↑ 由 RTOS 排程器控制切換，透過 ll_aton_reloc_install() 動態載入
```

STM32N6 已有**多模型串接**的成功案例：
- 手部地標偵測：先 palm detection → 再 hand landmark（[GitHub](https://github.com/STMicroelectronics/x-cube-n6-ai-hand-landmarks)）
- Multi-Model Face Recognition Pipeline（[ST Community](https://community.st.com/t5/edge-ai/sharing-my-repo-multi-model-face-recognition-pipeline-on-stm32n6/td-p/826889)）

NPU 時間分片是已被驗證的技術路徑。

### 1.3 抽象化核心 — T=1 SNN 在數學上等價於量化 ANN

這是最關鍵的突破，徹底改變了「NPU 無法跑 SNN」的結論。

#### LIF 神經元的數學分解

```
標準 LIF (Leaky Integrate-and-Fire) 神經元動態：
  V[t] = β · V[t-1] + W · X[t]     ← 膜電位更新
  S[t] = Θ(V[t] - threshold)        ← 脈衝生成（Heaviside 階躍函數）
  V[t] = V[t] · (1 - S[t])          ← 重置

當 T=1（單一時間步）：
  V[1] = β · 0 + W · X = W · X      ← 無歷史狀態，簡化為矩陣乘法
  S[1] = Θ(W·X - threshold)          ← 等價於量化激活函數

結論：T=1 SNN 前向傳播 = 標準 ANN 前向傳播 + 二值化/量化激活
```

#### 2025 年研究驗證

**論文 "One Timestep is Enough"**（arXiv:2510.23383, 2025 年 10 月）：

| 資料集 | T=1 SNN 準確率 | 等效 ANN 準確率 | 差距 |
|--------|:---:|:---:|:---:|
| CIFAR-10 | 98.5% | ~98.8% | -0.3% |
| CIFAR-100 | 89.3% | ~89.6% | -0.3% |
| ImageNet | 81.6% | ~82.0% | -0.4% |

**PASCAL 框架**（arXiv:2505.01730, 2025 年 5 月，[GitHub](https://github.com/BrainSeek-Lab/PASCAL)）：
- 數學證明 QCFS 激活 ANN 和 SNN 之間的**無損等價映射**
- 支援逐層自適應量化步長
- 轉換後的模型使用標準 INT8 算子圖

**NeuroFlex**（arXiv:2511.05215, 2025 年 11 月）：
- 所有張量以 INT8 格式儲存和運算
- 統一 INT8 儲存 + 即時脈衝生成
- 相較 ANN-only 基線，能量延遲積降低 57-67%

#### 技術結論

```
SNN 模型 → PASCAL 框架轉換 → QCFS 激活 ANN → INT8 量化 ONNX
→ ST Edge AI Core 編譯 → Neural-ART 格式 → NPU 部署

NPU 利用率：100%（不是 0%）
SNN 的時序特性：透過多步推論（T>1）或事件驅動編碼在 CPU 側保留
```

---

## 二、SNN 對電信領域的貢獻分析

### 2.1 研究現狀

| 應用場景 | 技術原理 | SNN 優勢 | 研究成熟度 | 關鍵文獻 |
|---------|---------|---------|:---:|---------|
| **網路入侵偵測 (IDS)** | 封包特徵→脈衝編碼→異常分類 | 事件驅動，低功耗 always-on 監控 | 論文驗證 | [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC12546366/) |
| **5G/6G 流量分類** | 時間序列流量特徵→SNN 時序處理 | 天然處理時序模式，比 CNN 省電 | 論文驗證 | [IEEE Xplore](https://ieeexplore.ieee.org/document/11171294/) |
| **5G RedCap + SNN** | 降規 5G + SNN 推論取代 ANN | 能耗降低 ~60%，延長 IoT 設備續航 | 概念驗證 | [MDPI](https://www.mdpi.com/2673-4001/7/1/4) |
| **IoT 邊緣異常偵測** | 多維時間序列→在線演化 SNN | 無監督學習，適應網路行為變化 | 學術原型 | [Springer](https://link.springer.com/article/10.1007/s10994-022-06129-4) |
| **頻譜感知** | 無線訊號→脈衝編碼→頻譜占用偵測 | 超低延遲，事件觸發 | 早期研究 | — |

### 2.2 SNN 的核心能效優勢

| 指標 | 傳統 ANN | 轉換 SNN | 直接訓練 SNN |
|------|:---:|:---:|:---:|
| 每次推論能耗 | ~200 mJ | ~20 mJ | **~5 mJ** |
| 相對 ANN 能效比 | 1x | 10x | **40x** |
| 脈衝稀疏度 < 0.1 時 | — | — | **比 ANN 高效 3.6 倍** |
| INT8 量化 SNN vs FP32 SNN | — | — | **再省 1.42 倍** |

> 參考：[SNN Energy Efficiency Reconsidered (arXiv 2024)](https://arxiv.org/html/2409.08290v1)

### 2.3 為何 SNN 而非 ANN 做網路入侵偵測

| 維度 | 傳統 ANN IDS | SNN IDS |
|------|-------------|---------|
| **能效** | ~200mJ/推論 | ~5mJ/推論（稀疏脈衝，40 倍省電） |
| **時序處理** | 需額外 LSTM/GRU 層 | LIF 神經元天然編碼時間（inter-arrival time = 脈衝間隔） |
| **事件驅動** | 固定頻率推論（浪費） | 僅在封包到達時觸發推論（天然 event-driven） |
| **DDoS 偵測** | 需統計窗口聚合 | 脈衝頻率直接反映流量爆發（spike rate = packet rate） |
| **Always-on** | 高功耗待機 | 超低功耗 idle，封包中斷喚醒 |

**網路流量天然是脈衝式的** — 封包到達就是離散事件，封包間隔就是時間編碼。SNN 是處理這類資料的最自然模型。這不是硬套，是 native fit。

---

## 三、系統架構 — SNN-IDS：基於脈衝神經網路的 IoT 邊緣入侵偵測系統

### 3.1 系統定位

```
定位：在 IoT 網路閘道器部署超低功耗、即時的網路入侵偵測
硬體：STM32N6570-DK（10/100M Ethernet + Neural-ART NPU + LCD）
軟體：µT-Kernel 3.0 + lwIP（已有官方移植）+ SNN 推論引擎
```

### 3.2 分層架構 — DPDK + SR-IOV 哲學的完整體現

```
Layer 0: 硬體直連（DPDK 哲學）
┌──────────────────────────────────────────────────────────────┐
│  Ethernet MAC ←DMA→ SRAM 環形緩衝區（零拷貝）                 │
│  µT-Kernel 中斷服務 → 封包接收任務（最高優先級）                │
│  不經過完整 TCP/IP 協議棧 → 直接讀取 L2/L3 表頭                │
│  = 嵌入式等價的 DPDK PMD（Poll Mode Driver）                   │
└──────────────────────────────────────────────────────────────┘
          │
          ▼
Layer 1: 特徵提取 + 脈衝編碼（µT-Kernel 任務）
┌──────────────────────────────────────────────────────────────┐
│  封包特徵提取：                                                │
│  - 封包大小、協議類型、TCP flags                                │
│  - 封包間隔（inter-arrival time）→ 直接映射為脈衝時序            │
│  - 來源/目的 IP 熵、埠號分布                                    │
│  - 滑動窗口統計（SYN 率、RST 率、分片率）                       │
│                                                                │
│  編碼方式：                                                    │
│  方案 A: Rate coding → 特徵值映射為 INT8（T=1 SNN）            │
│  方案 B: Temporal coding → 多時間步脈衝序列（T=4-8）            │
└──────────────────────────────────────────────────────────────┘
          │
          ▼
Layer 2: NPU 推論（SR-IOV 哲學 — 動態模型切換）
┌──────────────────────────────────────────────────────────────┐
│  模型 1（常駐）: T=1 SNN 快速篩選器                             │
│  - PASCAL 轉換的 INT8 量化模型                                  │
│  - 600 GOPS NPU 全速運行                                       │
│  - 正常流量 → 跳過，異常流量 → 觸發深度分析                      │
│                                                                │
│  模型 2（按需載入）: 多時間步 SNN 深度分類器                      │
│  - ll_aton_reloc_install() 動態載入                             │
│  - T=4-8 unrolled timesteps                                    │
│  - 每 timestep = 一次 NPU 推論 + CPU 膜電位管理                 │
│  - 精確分類攻擊類型（DDoS / PortScan / Slowloris / ...）        │
│                                                                │
│  切換邏輯由 µT-Kernel 信號量控制                                 │
│  = NPU 資源的時間分片虛擬化（SR-IOV 精神）                       │
└──────────────────────────────────────────────────────────────┘
          │
          ▼
Layer 3: 決策 + 輸出
┌──────────────────────────────────────────────────────────────┐
│  LCD 即時顯示：                                                │
│  - 網路流量儀表板（封包率、協議分布、異常計數）                    │
│  - 攻擊事件時間線（紅色高亮）                                    │
│  - SNN 神經元脈衝活動視覺化（展示 SNN 的運作方式）                │
│                                                                │
│  警報輸出：                                                    │
│  - GPIO 蜂鳴器 + LED（即時）                                    │
│  - UART → 外部模組轉發（可選）                                  │
│  - 僅傳輸事件摘要，不傳輸封包內容（隱私保護）                     │
└──────────────────────────────────────────────────────────────┘
```

### 3.3 µT-Kernel 多任務架構

```
µT-Kernel 3.0 任務架構：

├── eth_rx_task    (Priority 8,  4KB) — Ethernet DMA 中斷 → 封包接收
│   └── 零拷貝環形緩衝區管理，封包描述符傳遞
│   └── 硬即時：10/100 Mbps 線速處理，不能丟封包
│
├── feature_task   (Priority 10, 4KB) — 特徵提取 + 脈衝編碼
│   └── 滑動窗口統計，協議解析
│   └── 輸出：INT8 特徵向量 → NPU 輸入緩衝區
│
├── npu_fast_task  (Priority 11, 4KB) — T=1 SNN 快速篩選（常駐模型）
│   └── LL_ATON NPU 推論，< 1ms/推論
│   └── 正常→丟棄，可疑→通知深度分析任務
│
├── npu_deep_task  (Priority 12, 4KB) — 多步 SNN 深度分類（按需載入）
│   └── ll_aton_reloc_install() 動態載入模型
│   └── T 步循環：NPU W*X → CPU 膜電位 → NPU → ...
│   └── 輸出攻擊類型和信賴度
│
├── display_task   (Priority 14, 2KB) — LCD 儀表板渲染
│   └── LTDC 加速，流量圖 + 脈衝活動視覺化
│
└── power_task     (Priority 15, 1KB) — 電源管理
    └── 無流量時 → 降頻 → 深度睡眠 → Ethernet 中斷喚醒
    └── 流量突增 → 動態升頻（DVFS）
```

### 3.4 為何必須用 RTOS（bare-metal 做不到的）

1. **封包接收不能被推論阻塞** — 優先級搶佔保證 `eth_rx_task` 永遠能中斷 NPU 推論
2. **兩階段推論的動態排程** — 快速篩選與深度分析的 NPU 時間片需要信號量/互斥鎖
3. **即時性保證** — DDoS 偵測必須在 100ms 內響應（不是「盡快」，是「必須」）
4. **電源狀態機** — idle / 低流量 / 高流量 / 攻擊 四種模式的切換需要 RTOS 任務管理

---

## 四、SNN 模型部署技術流程

### 4.1 訓練與轉換 Pipeline

```
Phase 1: PC 端 — ANN 訓練
├── 資料集：NSL-KDD / CICIDS2017（標準網路入侵偵測資料集）
├── 模型架構：輕量 1D-CNN 或 MLP（適合 MCU 部署）
├── 激活函數：QCFS（Quantization-Clip-Floor-Shift）
└── 框架：PyTorch

Phase 2: PC 端 — ANN → SNN 轉換
├── 工具：PASCAL 框架 (github.com/BrainSeek-Lab/PASCAL)
├── 逐層自適應量化步長配置
├── 驗證：SNN 推論精度 vs 原始 ANN（目標 < 0.5% 差距）
└── 輸出：INT8 量化 ONNX 模型

Phase 3: PC 端 — NPU 編譯
├── 工具：ST Edge AI Core (stedgeai-core)
├── 輸入：INT8 ONNX → Neural-ART 編譯器優化
├── 輸出：Neural-ART 格式模型權重
└── 權重寫入 XSPI2 NOR Flash (0x70380000)

Phase 4: MCU 端 — 部署與推論
├── LL_ATON API 載入模型
├── T=1 模型：單次 NPU 推論 = 一次 SNN 推理
├── T>1 模型：循環 {NPU 推論 → CPU 膜電位更新 → NPU 推論}
└── µT-Kernel 任務封裝整個推論管線
```

### 4.2 多時間步 SNN 在 NPU 上的展開策略

```
T=1 模式（快速篩選）：
  Input → [NPU: Dense/Conv INT8] → [CPU: Threshold] → Output
  延遲：< 1ms | 能耗：最低 | 精度：ANN 等級

T=4 模式（深度分類）：
  Step 1: Input[0] → [NPU: W*X] → [CPU: V = W*X, S = Θ(V-thr), reset]
  Step 2: Input[1] → [NPU: W*X] → [CPU: V = β*V_prev + W*X, S = Θ(V-thr), reset]
  Step 3: Input[2] → [NPU: W*X] → [CPU: V = β*V_prev + W*X, S = Θ(V-thr), reset]
  Step 4: Input[3] → [NPU: W*X] → [CPU: V = β*V_prev + W*X, S = Θ(V-thr), reset]
  → Spike count decode → Attack classification

  NPU 負責：矩陣乘法 W*X（INT8，硬體加速）
  CPU 負責：膜電位管理 + 閾值判斷（簡單加法+比較，Cortex-M55 輕鬆完成）
  NPU 利用率：~80%（僅在 CPU 膜電位計算時短暫空閒）
```

### 4.3 記憶體估算

| 項目 | 大小 | 儲存位置 |
|------|------|---------|
| T=1 快速篩選模型權重 | ~50-200 KB | XSPI2 NOR Flash |
| T=4 深度分類模型權重 | ~100-500 KB | XSPI2 NOR Flash |
| 膜電位狀態緩衝區 | ~1-4 KB（256 neurons × 4 layers × 4 bytes） | SRAM |
| 封包環形緩衝區 | ~32 KB（256 × 128 bytes/封包描述符） | SRAM |
| NPU 推論工作記憶體 | ~256 KB | SRAM（4.2MB 可用） |
| lwIP TCP/IP stack | ~40 KB code + ~16 KB RAM | SRAM |
| **總計** | **< 1 MB** | **STM32N6 有 4.2MB SRAM，綽綽有餘** |

---

## 五、競賽適配性評估

### 5.1 對照評審偏好

| 評審 | 對 SNN-IDS 的評價預測 | 理由 |
|------|---------------------|------|
| **坂村健**（首席） | **高度共鳴** | IoT 邊緣安全直接對應他的 IoT-Aggregator 願景。「保護邊緣節點」= 保護他畢生在建構的 IoT 基礎設施。SNN 的「仿生計算在邊緣」呼應他 1984 年以來的「物件嵌入電腦彼此協作」哲學 |
| **Paolo Oteri**（ST） | **正面** | NPU 100% 利用 + LL_ATON 深度整合 + 動態模型載入 = 展示 STM32N6 在非視覺領域的深度能力。他作為 ST MCU 行銷 VP，需要看到 NPU 的多元應用潛力 |
| **黑田昭博**（Renesas） | **中性偏正** | 不是 Renesas 板卡，但 SNN + Edge AI 的前沿性本身有技術吸引力 |
| **松井明**（Personal Media） | **中性** | 與 micro:bit 路線無關，但技術深度可能獲得尊重 |

### 5.2 競賽評分維度對照

| 評分維度 | SNN-IDS 表現 | 說明 |
|---------|:---:|------|
| **RTOS 特性利用** | 5/5 | 封包線速處理 + 兩階段 NPU 動態排程 + 電源狀態機，RTOS 是系統運作的必要條件 |
| **AI 深度** | 5/5 | SNN→ANN 等價映射 + NPU 部署 + 多步展開推論，AI 理解深度遠超「調用 Model Zoo 模型」 |
| **NPU 利用** | 5/5 | T=1 SNN = INT8 量化模型，NPU 全速運行。T>1 模式 NPU 利用率 ~80% |
| **社會意義** | 4/5 | IoT 安全是數十億連網裝置的基礎設施問題，對應坂村健 IoT 願景 |
| **完成度可行性** | 3/5 | 需先驗證 PASCAL→INT8→Neural-ART 的 go/no-go（第一週關鍵測試） |
| **Demo 效果** | 3.5/5 | LCD 即時流量儀表板 + SNN 脈衝活動動畫，風格獨特但不如攝影機方案直觀 |
| **技術原創性** | 5/5 | 世界首個 SNN on Neural-ART NPU，可發頂會論文 |
| **開源價值** | 5/5 | SNN→NPU 抽象層 + µT-Kernel 網路安全框架，社群價值極高 |

### 5.3 風險矩陣

| 風險 | 嚴重度 | 機率 | 緩解方案 |
|------|:---:|:---:|---------|
| PASCAL 轉換模型在 Neural-ART 上算子不相容 | **致命** | 中 | **第一週 go/no-go 測試**：轉換一個小 MLP，用 ST Edge AI Core 驗證能否編譯通過 |
| lwIP + µT-Kernel 封包處理性能不足 | 高 | 低 | lwIP 已有官方移植；可降級為 raw Ethernet（不走完整 TCP/IP） |
| 入侵偵測精度不達標 | 中 | 中 | 使用 NSL-KDD / CICIDS2017 標準資料集，PC 端先驗證 ANN→SNN 轉換精度 |
| LCD 視覺化不夠震撼 | 中 | 低 | 設計精美的即時網路流量儀表板 + SNN 脈衝活動動畫 |
| 六個月內無法完成 | 高 | 中 | MVP 範圍：T=1 快速篩選必做，多步深度分類為 stretch goal |

---

## 六、與跌倒偵測方案的最終比較

| 維度 | SNN-IDS（電信邊緣安全） | 跌倒偵測（高齡照護） |
|------|:---:|:---:|
| 技術原創性 | **5/5**（世界首個 SNN on Neural-ART） | 3/5（Model Zoo 現成模型） |
| NPU 利用率 | **5/5**（T=1 SNN = INT8 量化，NPU 全速） | 5/5 |
| 完成度可行性 | 3/5（需先驗證 go/no-go） | **5/5** |
| 社會意義 | 4/5（IoT 安全 + 坂村健 IoT 願景） | **5/5**（高齡化社會） |
| Demo 效果 | 3.5/5（流量儀表板 + 脈衝視覺化） | **5/5**（攝影機即時骨架） |
| 評審共鳴 | 4/5（IoT-Aggregator 安全層） | 4.5/5 |
| RTOS 必要性 | **5/5**（封包線速處理 + 兩階段 NPU 排程） | 5/5 |
| 學術發表潛力 | **5/5**（可投 IEEE/ACM 頂會） | 2/5 |
| **總分** | **34.5/40** | **34.5/40** |

**兩條路線現在是平手。** 選擇取決於團隊背景和風險偏好。

---

## 七、決策建議

### 選 SNN-IDS 如果：
- 有電信/網路安全背景，能快速建構訓練 pipeline
- 追求的不只是獎金，還有學術影響力（可發頂會論文）
- 有能力在第一週完成 go/no-go 技術驗證（PASCAL → INT8 → Neural-ART 編譯測試）
- 願意承擔較高風險換取「如果成功，就是歷史性的里程碑」

### 選跌倒偵測如果：
- 要最大化得獎概率（完成度風險最低）
- 沒有時間做 SNN 轉換的技術驗證
- 更看重視覺 demo 的衝擊力

### 路線 E — 雙投策略（推薦）：
- **Application 類別**投 SNN-IDS
- **Middleware 類別**投「µT-Kernel SNN Inference Abstraction Layer」— SNN→NPU 的抽象映射層本身就是一個獨立中間件成果
- 兩個類別不衝突，且中間件部分是 SNN-IDS 的子集

---

## 八、Go/No-Go 驗證計畫（第一週）

在投入全部開發資源前，必須完成以下驗證：

### 測試 1：PASCAL → Neural-ART 算子相容性

```bash
# PC 端
1. 用 PyTorch 訓練一個 3 層 MLP（QCFS 激活）
2. PASCAL 轉換為 SNN → 匯出 INT8 ONNX
3. stedgeai-core 編譯為 Neural-ART 格式
4. 檢查是否有不支援的算子（如果有，嘗試替代算子或 CPU fallback）
```

### 測試 2：STM32N6 Ethernet 封包接收性能

```
1. µT-Kernel + lwIP 基本 Ethernet 收發
2. 測量最大封包處理率（目標：> 1000 pkt/s）
3. 若 lwIP 太慢，測試 raw Ethernet DMA 模式
```

### 測試 3：NPU 推論延遲

```
1. 部署測試 1 的模型到 STM32N6570-DK
2. 測量單次推論延遲（目標：< 1ms for T=1）
3. 測量模型切換延遲（ll_aton_reloc_install）
```

**三項測試全部通過 → Go，全力開發 SNN-IDS**
**任一項失敗 → 切換到跌倒偵測方案（備選方案已完整規劃）**

---

## 參考資源

### SNN 理論與轉換框架
- [One Timestep is Enough (arXiv 2025)](https://arxiv.org/abs/2510.23383)
- [PASCAL: Precise ANN-SNN Conversion (arXiv 2025)](https://arxiv.org/abs/2505.01730)
- [PASCAL GitHub](https://github.com/BrainSeek-Lab/PASCAL)
- [NeuroFlex: ANN-SNN Co-Execution on INT8 (arXiv 2025)](https://arxiv.org/pdf/2511.05215)
- [Linear LIF SNN Mapping to DNN (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC9448910/)
- [SNN Energy Efficiency Reconsidered (arXiv 2024)](https://arxiv.org/html/2409.08290v1)

### SNN 電信/安全應用
- [Event-Driven IDS using SNN for Edge IoT Security (IEEE 2025)](https://ieeexplore.ieee.org/document/11171294/)
- [Hybrid RNN-SNN for IoT Anomaly Prediction (PMC 2025)](https://pmc.ncbi.nlm.nih.gov/articles/PMC12546366/)
- [5G RedCap + SNN Energy Efficiency (MDPI)](https://www.mdpi.com/2673-4001/7/1/4)
- [Convolutional SNN for Intrusion Detection (Nature 2024)](https://www.nature.com/articles/s41598-024-57691-x)
- [Protocol-Aware Transformer-Spiking Hybrid (Nature 2026)](https://www.nature.com/articles/s41598-026-37367-4)

### STM32N6 / Neural-ART
- [ST Neural-ART NPU Concepts](https://stedgeai-dc.st.com/assets/embedded-docs/stneuralart_programming_model.html)
- [ST Neural-ART Operator Support](https://stm32ai-cs.st.com/assets/embedded-docs/stneuralart_operator_support.html)
- [ST Neural-ART Runtime Loadable Models](https://stedgeai-dc.st.com/assets/embedded-docs/stneuralart_reloc_mode.html)
- [Multi-Model Face Recognition on STM32N6 (ST Community)](https://community.st.com/t5/edge-ai/sharing-my-repo-multi-model-face-recognition-pipeline-on-stm32n6/td-p/826889)
- [STM32N6 Hand Landmarks Multi-Model (GitHub)](https://github.com/STMicroelectronics/x-cube-n6-ai-hand-landmarks)
- [STM32N6 Neural-ART Blog (ST)](https://blog.st.com/stm32n6/)

### µT-Kernel / RTOS
- [µT-Kernel 3.0 + lwIP (UCT)](https://www.uctec.com/iot-products-en/iot-products/os/uct-utk3/)
- [µT-Kernel 3.0 GitHub](https://github.com/tron-forum/mtkernel_3)
- [STM32 Bare Metal Ethernet HAL (GitHub)](https://github.com/stm32-hotspot/CKB-STM32-HAL-Ethernet-BareMetal)

### SNN 嵌入式部署
- [SNN on RISC-V MCU with Sparsity Optimization (arXiv)](https://arxiv.org/html/2405.02146v1)
- [Energy Efficient SNN on Embedded MCU (Springer)](https://link.springer.com/article/10.1007/s00521-024-10191-5)
- [SNN Code Libraries for Embedded Systems (UTK)](https://neuromorphic.eecs.utk.edu/publications/2025-07-29-generating-spiking-neural-network-code-libraries-for-embedded-systems/)
- [Fraunhofer SNN Research](https://www.iis.fraunhofer.de/en/ff/kom/ai/snn.html)

### 坂村健 / TRON 願景
- [Aggregate Computing (TRON Forum)](https://www.tron.org/aggregate-computing/)
- [Ken Sakamura IEEE Ibuka Award](https://www.tron.org/blog/2022/11/ken-sakamura-tron-forum-chair-is-the-recipient-of-2023-ieee-masaru-ibuka-consumer-technology-award/)
- [TRON Intelligent House IEEE Milestone](https://ethw.org/Milestones:The_Pioneering_TRON_Intelligent_House,_1989)

### 競賽官方
- [TRON Programming Contest 2026](https://www.tron.org/programming_contest-2026/)
- [2026 報名頁面](https://www.tron.org/programming_contest-2026/programming_contest_entry-2026/)
- [2025 得獎公告](https://www.tron.org/programming_contest-2025/programming_contest_2025_awards/)
- [2024 得獎公告](https://www.tron.org/programming_contest/programming_contest_2024_awards/)
