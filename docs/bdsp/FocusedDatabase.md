---
title: BDSP 第二阶段主数据与图片数据库
tags: [bdsp, unity, il2cpp]
---
# 第二阶段主数据与图片数据库

返回 [[README|研究导航]]；[[SourceInventory|原始目录]]；[[ExtractionPipeline|全量流程]]。

## 第一轮验收
[Run 45780192493](https://github.com/969981/BDSP_Resources/actions/runs/45780192493) 成功，8 分片及对账任务全部成功。18,028 个源文件，14,052 UnityFS，7 Unity serialized，14,059 成功索引容器；1,827,706 对象，132,383 TypeTree JSON，9,804 validated_png，62 decode_error，193 raw_fallback，2 TextAsset，1,685,262 indexed。40,000+ Texture2D 并不等于已解码图片；PNG 只代表文件可读。

## 原始资源
AssetAssistant/Pml/personal_masterdatas 125,957 B；Dpr/masterdatas 449,274 B；UIs/masterdatas/uimasterdatas 353,687 B。Message 12 文件。global-metadata.dat 12,496,504 B。

## 文件名实证
- dp：1302 文件，493 个物种编号（1–493），651 个前三段键，每键均有最后编号 00/01。
- l：542 文件，494 个物种编号（含 0），542 个前三段键，末段均为 00。
- 格式 pmNNNN_AA_BB_CC_dp 或 _l；A/B/C 为未验证业务含义的原始编号。物种编号候选通过文件名推导，形态、性别、异色需原生选择函数证明。
- 例 pm0003_00_01_01_dp、pm0493_16_02_01_dp、pm0000_00_00_00_l。

## 执行
```powershell
py -3.11 -m pip install UnityPy==1.25.4 Pillow==13.0.0
py -3.11 scripts/bdsp_focus.py --output Unpack/v1.3.0/focus
```
SQLite 包含 source/asset/image_key/image_pixel/master_schema/master_array/metadata_types/metadata_fields/metadata_methods 及 image_lookup、metadata_type_fields 视图。表和消息导出保留完整 TypeTree 或 raw，主数据数组结构独立索引；MonoScript 类/命名空间匹配仅为候选，未进行 assembly 所属类型验证。PNG 逐像素回读核对，记录宽高、alpha 极值及包含尺寸的 RGBA SHA-256。像素相等不意味着运行时材质等价。

IL2CPP 元数据布局依据 [Il2CppDumper MetadataClass](https://github.com/Perfare/Il2CppDumper/blob/master/Il2CppDumper/Il2Cpp/MetadataClass.cs) 独立实现；校验 magic、版本、边界、token 类型、字段和方法完整归属，布局不唯一则拒绝。type_index 尚非类型名，字段运行时偏移和方法地址须结合 NSO 原生注册表恢复。不声称已恢复 native selector。

CI 产物保存在 Actions，不提交原图到 Git。第二阶段运行结果以实际 summary 和数据库为准。