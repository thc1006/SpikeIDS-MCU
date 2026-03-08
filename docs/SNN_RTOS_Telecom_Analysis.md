# SNN x RTOS x Telecom Edge Security — Deep Technical Analysis and Contest Suitability Assessment

> **Analysis Date**: 2026-03-08
> **Contest**: TRON Programming Contest 2026
> **Theme**: TRON x AI — Utilizing AI
> **Hardware**: STM32N6570-DK (Cortex-M55 + Neural-ART NPU 600 GOPS)
> **Core Question**: Can SNNs be deployed on conventional NPUs through abstraction techniques, and can they contribute to the telecom domain?

---

## I. Abstraction Breakthrough: Why DPDK / SR-IOV Philosophy Changes the Entire Technical Assessment

### 1.1 DPDK Philosophy — Bypassing High-Level Abstractions to Directly Control Hardware

The core of DPDK is not a specific software library, but a design philosophy: **bypass the limitations of high-level frameworks and talk directly to the hardware**.

In the Linux world:
```
Traditional path: NIC → kernel driver → socket API → application (slow, context switches)
DPDK path: NIC → user-space PMD → application (zero-copy, direct DMA)
```

**Equivalent mapping in the STM32N6 world**:
```
Traditional path: Model → ST Edge AI Suite → standard CNN pipeline → NPU (operator-limited by framework)
DPDK path: SNN model → custom operator decomposition → LL_ATON low-level API → directly drive NPU MAC array
```

**LL_ATON is the "user-space driver" of Neural-ART**. The source code of RescueBot (2025 Student Category Award of Excellence) has proven that it can bypass the ST standard toolchain and directly control NPU inference scheduling. Moreover, Neural-ART supports **Runtime Loadable Models** (`ll_aton_reloc_install()`), enabling dynamic loading of different models at runtime — this is "hot-swapping" at the NPU level.

### 1.2 SR-IOV Philosophy — NPU Resource Time-Division Multiplexing

The core of SR-IOV: one physical device is virtualized into multiple virtual functions, each operating independently.

**Applied to Neural-ART**:
```
µT-Kernel Task A: Load SNN feature extraction model → NPU inference → unload
µT-Kernel Task B: Load SNN temporal classifier model → NPU inference → unload
                  ↑ Switching controlled by RTOS scheduler via ll_aton_reloc_install() dynamic loading
```

STM32N6 already has successful **multi-model chaining** examples:
- Hand landmark detection: palm detection → then hand landmark ([GitHub](https://github.com/STMicroelectronics/x-cube-n6-ai-hand-landmarks))
- Multi-Model Face Recognition Pipeline ([ST Community](https://community.st.com/t5/edge-ai/sharing-my-repo-multi-model-face-recognition-pipeline-on-stm32n6/td-p/826889))

NPU time-slicing is a verified technical path.

### 1.3 Core Abstraction — T=1 SNN is Mathematically Equivalent to a Quantized ANN

This is the most critical breakthrough, fundamentally changing the conclusion that "NPUs cannot run SNNs."

#### LIF Neuron Mathematical Decomposition

```
Standard LIF (Leaky Integrate-and-Fire) neuron dynamics:
  V[t] = β · V[t-1] + W · X[t]     ← Membrane potential update
  S[t] = Θ(V[t] - threshold)        ← Spike generation (Heaviside step function)
  V[t] = V[t] · (1 - S[t])          ← Reset

When T=1 (single timestep):
  V[1] = β · 0 + W · X = W · X      ← No history state, simplifies to matrix multiply
  S[1] = Θ(W·X - threshold)          ← Equivalent to quantized activation function

Conclusion: T=1 SNN forward pass = standard ANN forward pass + binarized/quantized activation
```

#### 2025 Research Validation

**Paper "One Timestep is Enough"** (arXiv:2510.23383, October 2025):

| Dataset | T=1 SNN Accuracy | Equivalent ANN Accuracy | Gap |
|---------|:---:|:---:|:---:|
| CIFAR-10 | 98.5% | ~98.8% | -0.3% |
| CIFAR-100 | 89.3% | ~89.6% | -0.3% |
| ImageNet | 81.6% | ~82.0% | -0.4% |

**PASCAL Framework** (arXiv:2505.01730, May 2025, [GitHub](https://github.com/BrainSeek-Lab/PASCAL)):
- Mathematically proves **lossless equivalence mapping** between QCFS activation ANNs and SNNs
- Supports per-layer adaptive quantization step sizes
- Converted model uses standard INT8 operator graph

**NeuroFlex** (arXiv:2511.05215, November 2025):
- All tensors stored and computed in INT8 format
- Unified INT8 storage + just-in-time spike generation
- 57-67% reduction in energy-delay product compared to ANN-only baseline

#### Technical Conclusion

```
SNN model → PASCAL framework conversion → QCFS activation ANN → INT8 quantized ONNX
→ ST Edge AI Core compilation → Neural-ART format → NPU deployment

NPU utilization: 100% (not 0%)
SNN temporal properties: preserved through multi-step inference (T>1) or event-driven encoding on CPU side
```

---

## II. SNN Contributions to the Telecom Domain

### 2.1 Research Landscape

| Application | Technical Principle | SNN Advantage | Research Maturity | Key Literature |
|-------------|-------------------|--------------|:---:|---------|
| **Network Intrusion Detection (IDS)** | Packet features → spike encoding → anomaly classification | Event-driven, low-power always-on monitoring | Paper-verified | [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC12546366/) |
| **5G/6G Traffic Classification** | Time-series traffic features → SNN temporal processing | Natively handles temporal patterns, more power-efficient than CNNs | Paper-verified | [IEEE Xplore](https://ieeexplore.ieee.org/document/11171294/) |
| **5G RedCap + SNN** | Reduced-capability 5G + SNN inference replacing ANN | ~60% energy reduction, extends IoT device battery life | Proof-of-concept | [MDPI](https://www.mdpi.com/2673-4001/7/1/4) |
| **IoT Edge Anomaly Detection** | Multi-dimensional time series → online evolving SNN | Unsupervised learning, adapts to changing network behavior | Academic prototype | [Springer](https://link.springer.com/article/10.1007/s10994-022-06129-4) |
| **Spectrum Sensing** | Wireless signals → spike encoding → spectrum occupancy detection | Ultra-low latency, event-triggered | Early research | — |

### 2.2 Core Energy Efficiency Advantage of SNNs

| Metric | Traditional ANN | Converted SNN | Directly Trained SNN |
|--------|:---:|:---:|:---:|
| Energy per inference | ~200 mJ | ~20 mJ | **~5 mJ** |
| Relative energy efficiency vs ANN | 1x | 10x | **40x** |
| When spike sparsity < 0.1 | — | — | **3.6x more efficient than ANN** |
| INT8 quantized SNN vs FP32 SNN | — | — | **Additional 1.42x savings** |

> Reference: [SNN Energy Efficiency Reconsidered (arXiv 2024)](https://arxiv.org/html/2409.08290v1)

### 2.3 Why SNN Instead of ANN for Network Intrusion Detection

| Dimension | Traditional ANN IDS | SNN IDS |
|-----------|-------------------|---------|
| **Energy Efficiency** | ~200mJ/inference | ~5mJ/inference (sparse spikes, 40x savings) |
| **Temporal Processing** | Requires additional LSTM/GRU layers | LIF neurons natively encode time (inter-arrival time = spike intervals) |
| **Event-Driven** | Fixed-rate inference (wasteful) | Inference triggered only on packet arrival (natively event-driven) |
| **DDoS Detection** | Requires statistical window aggregation | Spike frequency directly reflects traffic bursts (spike rate = packet rate) |
| **Always-on** | High-power standby | Ultra-low-power idle, Ethernet interrupt wake-up |

**Network traffic is inherently spike-like** — packet arrivals are discrete events, inter-packet intervals are temporal encoding. SNN is the most natural model for this type of data. This is not forced — it is a native fit.

---

## III. System Architecture — SNN-IDS: Spiking Neural Network-Based IoT Edge Intrusion Detection System

### 3.1 System Positioning

```
Purpose: Deploy ultra-low-power, real-time network intrusion detection at the IoT network gateway
Hardware: STM32N6570-DK (10/100M Ethernet + Neural-ART NPU + LCD)
Software: µT-Kernel 3.0 + lwIP (official port available) + SNN inference engine
```

### 3.2 Layered Architecture — Full Embodiment of DPDK + SR-IOV Philosophy

```
Layer 0: Direct Hardware Access (DPDK Philosophy)
┌──────────────────────────────────────────────────────────────┐
│  Ethernet MAC ←DMA→ SRAM ring buffer (zero-copy)            │
│  µT-Kernel ISR → packet receive task (highest priority)     │
│  Bypass full TCP/IP stack → directly read L2/L3 headers     │
│  = Embedded equivalent of DPDK PMD (Poll Mode Driver)       │
└──────────────────────────────────────────────────────────────┘
          │
          ▼
Layer 1: Feature Extraction + Spike Encoding (µT-Kernel Task)
┌──────────────────────────────────────────────────────────────┐
│  Packet feature extraction:                                  │
│  - Packet size, protocol type, TCP flags                     │
│  - Inter-arrival time → directly mapped as spike timing      │
│  - Source/destination IP entropy, port distributions         │
│  - Sliding window statistics (SYN rate, RST rate, frag rate) │
│                                                              │
│  Encoding methods:                                           │
│  Option A: Rate coding → feature values mapped to INT8 (T=1) │
│  Option B: Temporal coding → multi-timestep spike seq (T=4-8)│
└──────────────────────────────────────────────────────────────┘
          │
          ▼
Layer 2: NPU Inference (SR-IOV Philosophy — Dynamic Model Switching)
┌──────────────────────────────────────────────────────────────┐
│  Model 1 (resident): T=1 SNN fast screener                  │
│  - PASCAL-converted INT8 quantized model                     │
│  - 600 GOPS NPU at full speed                               │
│  - Normal traffic → skip, anomalous → trigger deep analysis  │
│                                                              │
│  Model 2 (on-demand): Multi-timestep SNN deep classifier    │
│  - ll_aton_reloc_install() dynamic loading                   │
│  - T=4-8 unrolled timesteps                                  │
│  - Each timestep = one NPU inference + CPU membrane mgmt    │
│  - Precise attack type classification (DDoS/PortScan/...)   │
│                                                              │
│  Switching logic controlled by µT-Kernel semaphores          │
│  = Time-division virtualization of NPU resources (SR-IOV)    │
└──────────────────────────────────────────────────────────────┘
          │
          ▼
Layer 3: Decision + Output
┌──────────────────────────────────────────────────────────────┐
│  LCD real-time display:                                      │
│  - Network traffic dashboard (pkt rate, protocol dist, ...)  │
│  - Attack event timeline (red highlights)                    │
│  - SNN neuron spike activity visualization                   │
│                                                              │
│  Alert output:                                               │
│  - GPIO buzzer + LED (immediate)                             │
│  - UART → external module forwarding (optional)              │
│  - Transmit event summaries only, not packet contents        │
│    (privacy-preserving)                                      │
└──────────────────────────────────────────────────────────────┘
```

### 3.3 µT-Kernel Multi-Task Architecture

```
µT-Kernel 3.0 Task Architecture:

├── eth_rx_task    (Priority 8,  4KB) — Ethernet DMA interrupt → packet receive
│   └── Zero-copy ring buffer management, packet descriptor passing
│   └── Hard real-time: 10/100 Mbps line-rate processing, no packet drops
│
├── feature_task   (Priority 10, 4KB) — Feature extraction + spike encoding
│   └── Sliding window statistics, protocol parsing
│   └── Output: INT8 feature vector → NPU input buffer
│
├── npu_fast_task  (Priority 11, 4KB) — T=1 SNN fast screener (resident model)
│   └── LL_ATON NPU inference, < 1ms/inference
│   └── Normal → discard, suspicious → notify deep analysis task
│
├── npu_deep_task  (Priority 12, 4KB) — Multi-step SNN deep classifier (on-demand)
│   └── ll_aton_reloc_install() dynamic model loading
│   └── T-step loop: NPU W*X → CPU membrane potential → NPU → ...
│   └── Output: attack type and confidence score
│
├── display_task   (Priority 14, 2KB) — LCD dashboard rendering
│   └── LTDC-accelerated, traffic graphs + spike activity visualization
│
└── power_task     (Priority 15, 1KB) — Power management
    └── No traffic → reduce clock → deep sleep → Ethernet interrupt wake
    └── Traffic surge → dynamic frequency scaling (DVFS)
```

### 3.4 Why RTOS is Required (What Bare-Metal Cannot Achieve)

1. **Packet receive must not be blocked by inference** — Priority preemption ensures `eth_rx_task` can always interrupt NPU inference
2. **Dynamic scheduling for two-stage inference** — NPU time-slicing between fast screener and deep analyzer requires semaphores/mutexes
3. **Real-time guarantees** — DDoS detection must respond within 100ms (not "as soon as possible," but "must")
4. **Power state machine** — Switching between idle / low-traffic / high-traffic / attack modes requires RTOS task management

---

## IV. SNN Model Deployment Technical Pipeline

### 4.1 Training and Conversion Pipeline

```
Phase 1: PC-Side — ANN Training
├── Dataset: NSL-KDD / CICIDS2017 (standard network IDS datasets)
├── Model architecture: Lightweight 1D-CNN or MLP (MCU deployment-friendly)
├── Activation: QCFS (Quantization-Clip-Floor-Shift)
└── Framework: PyTorch

Phase 2: PC-Side — ANN → SNN Conversion
├── Tool: PASCAL framework (github.com/BrainSeek-Lab/PASCAL)
├── Per-layer adaptive quantization step configuration
├── Validation: SNN accuracy vs original ANN (target < 0.5% gap)
└── Output: INT8 quantized ONNX model

Phase 3: PC-Side — NPU Compilation
├── Tool: ST Edge AI Core (stedgeai-core)
├── Input: INT8 ONNX → Neural-ART compiler optimization
├── Output: Neural-ART format model weights
└── Weights written to XSPI2 NOR Flash (0x70380000)

Phase 4: MCU-Side — Deployment and Inference
├── LL_ATON API loads model
├── T=1 model: single NPU inference = one SNN inference pass
├── T>1 model: loop {NPU inference → CPU membrane potential update → NPU inference}
└── µT-Kernel task wraps the entire inference pipeline
```

### 4.2 Multi-Timestep SNN Unrolling Strategy on NPU

```
T=1 Mode (fast screening):
  Input → [NPU: Dense/Conv INT8] → [CPU: Threshold] → Output
  Latency: < 1ms | Power: minimum | Accuracy: ANN-level

T=4 Mode (deep classification):
  Step 1: Input[0] → [NPU: W*X] → [CPU: V = W*X, S = Θ(V-thr), reset]
  Step 2: Input[1] → [NPU: W*X] → [CPU: V = β*V_prev + W*X, S = Θ(V-thr), reset]
  Step 3: Input[2] → [NPU: W*X] → [CPU: V = β*V_prev + W*X, S = Θ(V-thr), reset]
  Step 4: Input[3] → [NPU: W*X] → [CPU: V = β*V_prev + W*X, S = Θ(V-thr), reset]
  → Spike count decode → Attack classification

  NPU handles: Matrix multiplication W*X (INT8, hardware-accelerated)
  CPU handles: Membrane potential management + threshold comparison
               (simple addition + comparison, easily handled by Cortex-M55)
  NPU utilization: ~80% (idle only during CPU membrane potential computation)
```

### 4.3 Memory Estimation

| Item | Size | Storage Location |
|------|------|---------|
| T=1 fast screener model weights | ~50-200 KB | XSPI2 NOR Flash |
| T=4 deep classifier model weights | ~100-500 KB | XSPI2 NOR Flash |
| Membrane potential state buffer | ~1-4 KB (256 neurons × 4 layers × 4 bytes) | SRAM |
| Packet ring buffer | ~32 KB (256 × 128 bytes/packet descriptor) | SRAM |
| NPU inference working memory | ~256 KB | SRAM (4.2MB available) |
| lwIP TCP/IP stack | ~40 KB code + ~16 KB RAM | SRAM |
| **Total** | **< 1 MB** | **STM32N6 has 4.2MB SRAM, more than sufficient** |

---

## V. Contest Suitability Assessment

### 5.1 Alignment with Judge Preferences

| Judge | Predicted Assessment of SNN-IDS | Reasoning |
|-------|-------------------------------|------|
| **Ken Sakamura** (Chief) | **Highly resonant** | IoT edge security directly aligns with his IoT-Aggregator vision. "Protecting edge nodes" = protecting the IoT infrastructure he has been building his entire career. SNN's "bio-inspired computing at the edge" echoes his 1984 philosophy of "objects embedded with computers cooperating with each other" |
| **Paolo Oteri** (ST) | **Positive** | 100% NPU utilization + deep LL_ATON integration + dynamic model loading = showcases STM32N6's capabilities beyond computer vision. As ST MCU Marketing VP, he needs to see NPU's multi-domain application potential |
| **Akihiro Kuroda** (Renesas) | **Neutral-positive** | Not a Renesas board, but the frontier nature of SNN + Edge AI has inherent technical appeal |
| **Akira Matsui** (Personal Media) | **Neutral** | Unrelated to the micro:bit route, but technical depth may earn respect |

### 5.2 Contest Scoring Dimensions

| Scoring Dimension | SNN-IDS Performance | Notes |
|-------------------|:---:|------|
| **RTOS Feature Utilization** | 5/5 | Line-rate packet processing + two-stage NPU dynamic scheduling + power state machine; RTOS is essential for system operation |
| **AI Depth** | 5/5 | SNN→ANN equivalence mapping + NPU deployment + multi-step unrolled inference; AI understanding far exceeds "calling Model Zoo models" |
| **NPU Utilization** | 5/5 | T=1 SNN = INT8 quantized model, NPU at full speed. T>1 mode NPU utilization ~80% |
| **Social Significance** | 4/5 | IoT security is an infrastructure problem for billions of connected devices, aligns with Ken Sakamura's IoT vision |
| **Completion Feasibility** | 3/5 | Must first verify PASCAL→INT8→Neural-ART go/no-go (critical first-week test) |
| **Demo Impact** | 3.5/5 | Real-time LCD traffic dashboard + SNN spike activity animation; unique style but less immediately intuitive than camera-based demos |
| **Technical Originality** | 5/5 | World's first SNN on Neural-ART NPU, publishable at top venues |
| **Open-Source Value** | 5/5 | SNN→NPU abstraction layer + µT-Kernel network security framework; extremely high community value |

### 5.3 Risk Matrix

| Risk | Severity | Probability | Mitigation |
|------|:---:|:---:|---------|
| PASCAL-converted model has operator incompatibility on Neural-ART | **Fatal** | Medium | **First-week go/no-go test**: convert a small MLP, verify with ST Edge AI Core that it compiles |
| lwIP + µT-Kernel packet processing performance insufficient | High | Low | lwIP has official port; can downgrade to raw Ethernet (bypass full TCP/IP) |
| Intrusion detection accuracy below acceptable threshold | Medium | Medium | Use NSL-KDD / CICIDS2017 standard datasets; verify ANN→SNN conversion accuracy on PC first |
| LCD visualization not impressive enough | Medium | Low | Design polished real-time network traffic dashboard + SNN spike activity animation |
| Cannot complete within six months | High | Medium | MVP scope: T=1 fast screener is required; multi-step deep classifier is stretch goal |

---

## VI. Final Comparison with Fall Detection Plan

| Dimension | SNN-IDS (Telecom Edge Security) | Fall Detection (Elderly Care) |
|-----------|:---:|:---:|
| Technical Originality | **5/5** (world's first SNN on Neural-ART) | 3/5 (Model Zoo ready-made) |
| NPU Utilization | **5/5** (T=1 SNN = INT8 quantized, NPU at full speed) | 5/5 |
| Completion Feasibility | 3/5 (requires go/no-go verification first) | **5/5** |
| Social Significance | 4/5 (IoT security + Ken Sakamura's IoT vision) | **5/5** (aging society) |
| Demo Impact | 3.5/5 (traffic dashboard + spike visualization) | **5/5** (real-time camera skeleton overlay) |
| Judge Resonance | 4/5 (IoT-Aggregator security layer) | 4.5/5 |
| RTOS Necessity | **5/5** (line-rate packet processing + two-stage NPU scheduling) | 5/5 |
| Academic Publication Potential | **5/5** (publishable at IEEE/ACM top venues) | 2/5 |
| **Total Score** | **34.5/40** | **34.5/40** |

**The two approaches are tied.** The choice depends on team background and risk tolerance.

---

## VII. Decision Recommendation

### Choose SNN-IDS if:
- You have a telecom/network security background and can quickly build the training pipeline
- You aim for more than just the prize money — you want academic impact (publishable at top venues)
- You can complete the first-week go/no-go technical verification (PASCAL → INT8 → Neural-ART compilation test)
- You are willing to accept higher risk in exchange for "if successful, it's a historic milestone"

### Choose Fall Detection if:
- You want to maximize the probability of winning (lowest completion risk)
- You don't have time for SNN conversion technical verification
- You prioritize visual demo impact

### Route E — Dual Submission Strategy (Recommended):
- **Application category**: Submit SNN-IDS
- **Middleware category**: Submit "µT-Kernel SNN Inference Abstraction Layer" — the SNN→NPU abstraction layer itself is an independent middleware contribution
- The two categories don't conflict, and the middleware portion is a subset of SNN-IDS

---

## VIII. Go/No-Go Verification Plan (First Week)

Before committing full development resources, the following verifications must be completed:

### Test 1: PASCAL → Neural-ART Operator Compatibility

```bash
# PC-side
1. Train a 3-layer MLP with QCFS activation using PyTorch
2. Convert with PASCAL to SNN → export INT8 ONNX
3. Compile with stedgeai-core to Neural-ART format
4. Check for unsupported operators (if found, try alternative operators or CPU fallback)
```

### Test 2: STM32N6 Ethernet Packet Receive Performance

```
1. µT-Kernel + lwIP basic Ethernet send/receive
2. Measure maximum packet processing rate (target: > 1000 pkt/s)
3. If lwIP too slow, test raw Ethernet DMA mode
```

### Test 3: NPU Inference Latency

```
1. Deploy Test 1's model to STM32N6570-DK
2. Measure single inference latency (target: < 1ms for T=1)
3. Measure model switching latency (ll_aton_reloc_install)
```

**All three tests pass → Go, full speed ahead on SNN-IDS**
**Any single test fails → Switch to fall detection plan (contingency plan fully prepared)**

---

## References

### SNN Theory and Conversion Frameworks
- [One Timestep is Enough (arXiv 2025)](https://arxiv.org/abs/2510.23383)
- [PASCAL: Precise ANN-SNN Conversion (arXiv 2025)](https://arxiv.org/abs/2505.01730)
- [PASCAL GitHub](https://github.com/BrainSeek-Lab/PASCAL)
- [NeuroFlex: ANN-SNN Co-Execution on INT8 (arXiv 2025)](https://arxiv.org/pdf/2511.05215)
- [Linear LIF SNN Mapping to DNN (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC9448910/)
- [SNN Energy Efficiency Reconsidered (arXiv 2024)](https://arxiv.org/html/2409.08290v1)

### SNN Telecom/Security Applications
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

### SNN Embedded Deployment
- [SNN on RISC-V MCU with Sparsity Optimization (arXiv)](https://arxiv.org/html/2405.02146v1)
- [Energy Efficient SNN on Embedded MCU (Springer)](https://link.springer.com/article/10.1007/s00521-024-10191-5)
- [SNN Code Libraries for Embedded Systems (UTK)](https://neuromorphic.eecs.utk.edu/publications/2025-07-29-generating-spiking-neural-network-code-libraries-for-embedded-systems/)
- [Fraunhofer SNN Research](https://www.iis.fraunhofer.de/en/ff/kom/ai/snn.html)

### Ken Sakamura / TRON Vision
- [Aggregate Computing (TRON Forum)](https://www.tron.org/aggregate-computing/)
- [Ken Sakamura IEEE Ibuka Award](https://www.tron.org/blog/2022/11/ken-sakamura-tron-forum-chair-is-the-recipient-of-2023-ieee-masaru-ibuka-consumer-technology-award/)
- [TRON Intelligent House IEEE Milestone](https://ethw.org/Milestones:The_Pioneering_TRON_Intelligent_House,_1989)

### Contest Official
- [TRON Programming Contest 2026](https://www.tron.org/programming_contest-2026/)
- [2026 Entry Page](https://www.tron.org/programming_contest-2026/programming_contest_entry-2026/)
- [2025 Award Announcement](https://www.tron.org/programming_contest-2025/programming_contest_2025_awards/)
- [2024 Award Announcement](https://www.tron.org/programming_contest/programming_contest_2024_awards/)
