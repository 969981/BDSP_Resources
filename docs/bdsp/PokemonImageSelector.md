---
title: BDSP PokemonImageSelector 原生追踪
tags: [bdsp, il2cpp, native, sprite]
---
# PokemonImageSelector 原生追踪
返回 [[README|研究导航]]；[[ResourceCore|第三阶段]]。

## 第三阶段验收
[Run 45782126029](https://github.com/969981/BDSP_Resources/actions/runs/45782126029) PASS。原始 metadata 逐行复核通过，TypeDefinition section 19、ImageDefinition section 20、45 images、11,812 types。2,443/2,443 PPtr、程序集、命名空间、类及类型关联 verified。
AddPersonal 651 行与 dp 651 组三段键，投影到 (monsno,formno) 与 (species_candidate,field_a) 后多重集合交集 558，双方各 93 余项；不是一一对应。例 dp 独有键 (3,0,1), (12,0,1), (19,0,1), (25,0,1)。字段 B 的业务含义和转换规则仍待验证。
两版各 551,315 RELA relative relocations；唯一 Assembly-CSharp module 候选：
| binary | module | method pointer table | slots |
|---|---|---|---|
| main | 0x49BD680 | 0x495D440 | 48084 |
| shiny_pearl_main | 0x49BE4B0 | 0x495E270 | 48084 |

main 候选入口（模块相对 VA）：
| 方法 | VA |
|---|---|
| Dpr.SubContents.Utils.GetPokemonAssetbundleName | 0x186B360 |
| Dpr.GMS.MonsIconData.GetMonsIconSprByFormNo | 0x1C94A70 |
| Dpr.UI.PokemonIcon.Load (token 100684053) | 0x1D8DFC0 |
| Dpr.UI.PokemonIcon.Load (token 100684054) | 0x1D8E360 |
| Dpr.UI.PokemonIcon.get_monsIcon | 0x1D8DF90 |
| Dpr.UI.PokemonIcon.get_itemIcon | 0x1D8DFA0 |
| Dpr.UI.PokemonIcon.get_ballDecoIcon | 0x1D8DFB0 |

## 第四阶段工具
- 逐物种保存 Personal、AddPersonal 完整原始记录及 dp 键；分类为直接投影多重集合相同、仅数量相同、数量不同，保留差异。
- 扫描主数据中实际 pm 命名键；保留完整来源、PathID、数组序号和字段路径。
- 搜索 metadata managed string literal，保留 literal index 与文件偏移；字符串存在不代表使用者已定位。
- 两版独立重验 SHA、module 指针和槽位数；导出 Assembly-CSharp 全部 MethodDef token → 模块相对 VA；识别地址别名。
- 使用 ARM64 B/BL 直接分支扫描定位入口引用；输出种子函数的反汇编和直接调用候选。相邻方法起点仅为分析窗口候选边界，不能作为真实函数结束；未追踪间接分支、跨模块调用、寄存器数据流、异常或字符串运行时装载。
- 不将 93 条差异自动映射到性别变体；native_selector_verified 保持 false，直至完整规则验证。

## 产物
bdsp-selector-evidence：species_reconciliation.json、master_image_key_hits.json、metadata_image_literals.json、双版本 method_map 和 selector_trace、selector_summary.json。
原始资源只读；继续使用研究分支，不合并 master。
