# Systematic Literature Search Protocol

**Date of execution**: 2026-04-12
**Searcher**: Hsiu-Chi Tsai (NYCU)
**Purpose**: Document the literature search used to support the hedged
novelty statement "first publicly documented IDS deployment on a Cortex-M
class MCU with a general-purpose neural accelerator (Neural-ART)" in the
GLOBECOM 2026 submission.

This protocol is cited from the paper's Introduction and included as a
supplementary document in the submission package.

---

## 1. Databases consulted

| Database | URL | Coverage |
|---|---|---|
| IEEE Xplore | https://ieeexplore.ieee.org | IEEE conferences + journals |
| ACM Digital Library | https://dl.acm.org | ACM conferences + journals |
| arXiv | https://arxiv.org | Preprints across cs.CR, cs.LG, cs.NE, eess.SP |
| Google Scholar | https://scholar.google.com | Cross-database meta-search |
| Semantic Scholar | https://www.semanticscholar.org | Citation-graph search |

---

## 2. Queries executed (all on 2026-04-12)

| # | Query string | Database(s) | Hits inspected |
|---|---|---|---|
| Q1 | `"STM32N6" AND ("intrusion detection" OR "IDS")` | IEEE, ACM, arXiv, Google Scholar | top 50 |
| Q2 | `"Neural-ART" AND ("IDS" OR "intrusion" OR "network security")` | IEEE, ACM, Google Scholar | top 50 |
| Q3 | `"Cortex-M" AND "NPU" AND ("security" OR "IDS" OR "intrusion")` | IEEE, arXiv, Google Scholar | top 50 |
| Q4 | `"MCU NPU" AND ("network intrusion" OR "IDS")` | Google Scholar, Semantic Scholar | top 30 |
| Q5 | `"ANN-SNN conversion" AND ("NPU" OR "MCU") AND "deployment"` | arXiv, Google Scholar | top 50 |
| Q6 | `"Ethos-U55" AND ("intrusion detection" OR "IDS")` | IEEE, Google Scholar | top 30 |
| Q7 | `"Cortex-M55" AND ("IDS" OR "anomaly detection")` | IEEE, arXiv, Google Scholar | top 30 |
| Q8 | `"on-device" AND "network intrusion" AND ("Cortex" OR "microcontroller")` | Google Scholar | top 50 |

**Date range**: 2020-01-01 to 2026-04-12 (6+ years, covering the era during
which commercial Cortex-M NPUs — STM32N6, Ethos-U55, Alif Ensemble — became
broadly available).

---

## 3. Inclusion and exclusion criteria

### Inclusion
- Reports **on-device** execution of a network intrusion detector
- Hardware platform is a **commodity MCU** (ARM Cortex-M series or RISC-V equivalent)
- Platform contains a **general-purpose neural accelerator / NPU** (not a fixed-function CNN engine)
- Peer-reviewed paper, conference paper, or arXiv preprint

### Exclusion
- **FPGA-only** platforms (Farooq 2025, various VNA designs) — different hardware class, orders-of-magnitude different power/cost envelope
- **Fixed-function neuromorphic ASICs** (Akida AKD1000, Loihi 2) — not programmable with standard INT8 operators
- **AI-specialized MCUs with a fixed CNN engine** (MAX78000, GAP9 when run in fixed mode) — the accelerator is not a general-purpose NPU and cannot run arbitrary quantized ANN topologies
- **MCU without any neural accelerator** (pure Cortex-M CPU inference)
- **GPU / SBC** (Raspberry Pi, Jetson, x86) — different hardware class
- **Simulation studies** on SNN that were never deployed to hardware

---

## 4. Hardware-class definitions (scope of the novelty claim)

**In-scope (comparable to STM32N6 + Neural-ART)**:
- ARM Cortex-M55 + Ethos-U55 (Synaptics SR110, Nuvoton M55M1)
- ARM Cortex-M85 + Ethos-U85 (Himax WE2)
- Alif Ensemble / Alif Balletto (Cortex-M55 + Ethos-U55)
- Any other Cortex-M or RISC-V MCU paired with a programmable NPU supporting INT8 Conv/Gemm/ReLU

**Out-of-scope (explicitly acknowledged)**:
- MAX78000 (Cortex-M4 + fixed CNN accelerator) — covered by Ngo et al. 2022 HH-NIDS, which we cite as the closest prior art on **AI-specialized** MCUs, while noting the different hardware class.
- FPGA IDS (Farooq et al. 2025, 1162M inferences/sec on Edge-IIoT dataset) — different hardware class, different dataset, not directly comparable; cited in related work as the SOTA for FPGA-based IDS.
- Akida AKD1000 (Zahm et al. 2024) — cited as closest prior art on neuromorphic ASIC.

---

## 5. Findings

### 5.1 No matching prior work found
No paper in the searched databases reports an intrusion detector
deployed on a commodity ARM Cortex-M MCU paired with a general-purpose
NPU (Neural-ART or Ethos-U-class).

### 5.2 Closest prior art (cited in the paper's Related Work)
| Paper | Hardware | Why not a match |
|---|---|---|
| Ngo et al. 2022 (HH-NIDS) | MAX78000 (Cortex-M4 + fixed CNN engine) | AI-specialized MCU, not a general-purpose NPU |
| Zahm et al. 2024 | BrainChip Akida AKD1000 | Neuromorphic ASIC, not a Cortex-M + NPU |
| Chehade et al. 2025 | STM32F7 (Cortex-M7, CPU only) | No NPU on board; CPU inference only |
| Diab et al. 2025 | Raspberry Pi 3B+ | SBC class, not MCU |
| Farooq et al. 2025 | Xilinx FPGA (raw-packet pipeline) | FPGA class, Edge-IIoT dataset |
| Bruschi et al. 2024 | Generic MCU (Cortex-M4) | No neural accelerator |
| Wang, Prajwalasimha, Mustafa, Karthik | Various MCU/CPU | No NPU accelerator |

### 5.3 CICIDS2017 dataset critique literature (acknowledged in Limitations)
- **Engelen et al. 2021** ("Troubleshooting an Intrusion Detection Dataset: the CICIDS2017 Case Study", IEEE WTMC'21): documents TCP splitting bugs, duplicate flows, mislabeled port scans. We acknowledge this and use the HuggingFace cleaned version.
- **Lanvin et al.** (subsequent critique): further flaws in label alignment.

### 5.4 NSL-KDD non-stationarity critique
Multiple surveys (Tavallaee 2009, McHugh 2000, and recent 2020-2024 reviews)
critique NSL-KDD for being derived from 1998 DARPA traffic, which does not
reflect modern IoT/5G traffic distributions. We retain NSL-KDD for
benchmark continuity with the MCU-IDS literature (HH-NIDS, Chehade, Diab
all report NSL-KDD-derived results) and explicitly caveat this in the
Dataset section.

---

## 6. Reproducibility

| Item | Value |
|---|---|
| Executed on | 2026-04-12 |
| By | Hsiu-Chi Tsai |
| Total queries | 8 distinct string variants across 5 databases |
| Hits inspected | ≈ 320 unique records |
| Protocol file | `docs/novelty_search_protocol.md` (this file) |
| Paper reference | Introduction §1, footnote referencing this file |

The paper's novelty statement is hedged as follows:

> "To the best of our knowledge, following the systematic literature
> search protocol documented in the supplementary material, no prior
> work has publicly reported an intrusion detector deployed on a
> commodity ARM Cortex-M-class MCU paired with a general-purpose neural
> accelerator."

This hedging is sufficient to defend the paper against concerns about
overclaimed novelty while honestly communicating what was verified and
what remains outside our search window.

---

## 7. Conclusion

No matching prior work was found in the searched databases within the
defined hardware class. The novelty claim is therefore defensible under
the hedging language above. If a reviewer identifies a missed reference,
we will update this protocol document and adjust the paper's language
accordingly during revision.
