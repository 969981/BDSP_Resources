---
title: BDSPResourceCore 原生关联与图片选择器
tags: [bdsp, il2cpp, sqlite, native]
---
# BDSPResourceCore
返回 [[README|研究导航]]；[[FocusedDatabase|第二阶段数据库]]。

## 第二阶段实测
[Run 45781504382](https://github.com/969981/BDSP_Resources/actions/runs/45781504382) PASS。1,844/1,844 图片源覆盖；1,844 Sprite + 1,844 Texture2D PNG；dp 像素哈希 2,582 种，l 1,084 种（分别统计，不等于全局唯一数）。三个 master 1,163 MonoBehaviour，Message 1,280；命名空间与类匹配 2,443/2,443（尚未核实程序集）。日志报告 11,812 TypeDefinition、105,088 FieldDefinition、71,155 MethodDefinition，24.2–24.5 布局。注意：第二阶段日志所列 section[19] 字节数与代码固定索引及类型数量不一致；不能将日志作为原始元数据完全验收，第三阶段对源文件逐行独立重验并查找唯一实际 section。

Pml 原生表：Personal 560、AddPersonal 651、Item 1823、Waza 827、Evolve 560、WazaOboe 560、TamagoWaza 560、WazaMachine 201、SealData 97、Grow 8、UgItemTable 957。数量含占位，不能作为有效业务实体数量。

## 第三阶段
- 使用固定第二阶段 artifact 和原始 metadata，验证 type/field/method 每行；恢复 ImageDefinition 的程序集及类型范围。MonoBehaviour m_Script 的同一 serialized file PPtr + MonoScript class/namespace/assembly + 唯一 metadata type ID 才标 verified。外部引用标 unresolved。
- master_record 保存顶层结构数组每条记录、原始 ordinal、对象 PathID 与来源。不用 monsno 代替 Personal.id。
- 比较 AddPersonal(monsno,formno) 与 dp 文件名头两段的多重集合，逐项输出差异；相等亦非原生选择函数证明。
- NSO 解压、可用段哈希校验、MOD0 RELA 相对重定位、Assembly-CSharp.dll 指针引用、候选 codegen module 方法表验证、按 MethodDef token RID 提取 ARM64 128 字节反汇编窗口。两版独立保存，窗口不等于完整函数；候选模块和方法不等于 native selector 已恢复。
- SQLite 只读查询：BDSPResourceCore.personal(monsno)、item(no)、image_candidates(species,field_a,field_b,field_c,kind)。图片接口只返回原始编号候选，不隐式回退或伪造性别异色语义。

## 验收与产物
[第三阶段 Actions](https://github.com/969981/BDSP_Resources/actions)；产物 bdsp-resource-core，包含 bdsp-core.sqlite、core_summary.json、addpersonal_image_comparison.json、双版本 native JSON（若成功）。图片文件仍在第二阶段 bdsp-pokemon-images artifact，数据库 output 路径相对第二阶段 focus 根。原生选择函数尚未闭合；需后续追踪调用者、格式字符串、性别分支和异常回退。