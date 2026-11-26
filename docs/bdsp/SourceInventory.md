---
title: BDSP 原始资源审计
source_commit: 321b2216f8d017f09e6b0decdf6bd6e2ce66e0c9
---
# 原始资源审计
返回 [[README|研究导航]]。

原始根：`1.3.0/5146edd5f9d0579a488ea31d0610e859_NCA/`

- `0/main` 37,895,896 B；`0/shiny_pearl_main` 37,886,548 B；另有 rtld、sdk、subsdk0、main.npdm。
- `1/Data/Managed/Metadata/global-metadata.dat` 12,496,504 B。
- `1/Data/resources.assets` 1,061,248 B；配套 `resources.assets.resS` 3,255,872 B。
- `1/Data/StreamingAssets/AssetAssistant/` 18 个子目录和 Dpr.bin。
- Pml：2 个文件，128,671 B；`Pml/Pml` 样本头 UnityFS、格式版本 7、Unity 2019.4.27f1（仅此样本确认）；`Pml/personal_masterdatas` 125,957 B。
- Message：12 个文件，15,165,688 B，含 common_msbt 与 10 种语言/文字版本（含日语假名和汉字变体）。
- UIs：1,995 个文件，84,836,299 B，其中 textures_mass/pokemon_dp 1,302、textures_mass/pokemon_l 542；均为文件数，不是图片数。
- Dpr：141 个文件，69,797,159 B，含 masterdatas。
- Pokemon Database：5,748 个文件，625,210,344 B，含战斗动画等。

证据来自 Git tree，以上是选定子树的完整文件统计（不代表整仓总数）。详见 [原始版本目录](https://github.com/969981/BDSP_Resources/tree/321b2216f8d017f09e6b0decdf6bd6e2ce66e0c9/1.3.0)。