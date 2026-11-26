---
title: 二次解包流程
---
# 二次解包流程

返回 [[README|研究导航]]。

```powershell
py -3.11 -m pip install "UnityPy>=1.20,<2" Pillow
py -3.11 scripts/bdsp_unpack.py --output Unpack/v1.3.0/run01 --images ui --raw-fallback
```

全图片尝试使用 `--images all`。仅文件审计使用 `--inventory-only`。每次写入空目录，不覆盖原文件或既有结果。可通过 --shards N --shard I 分片（路径 SHA-256 取模）。CI 默认 8 分片，对全部源文件计算 SHA-256、尝试识别 Unity 容器和列出对象；UI Texture2D/Sprite 输出 PNG；TextAsset 输出字节；MonoBehaviour、SpriteAtlas、AssetBundle、Material、MonoScript 尝试导出 TypeTree JSON，失败可保留原始对象字节。其它对象只索引。UnityPy 运行版本写入 summary，尚未固定到已实测版本。

`_index/sources.jsonl`：源文件路径、大小、SHA-256、文件头、格式、加载结果。
`_index/objects.jsonl`：源文件、序列化文件、PathID、对象类型、名称、输出 SHA-256、错误。
`_index/summary.json`：阶段计数。
`extracted/`：按源文件 SHA-256 隔离的对象产物。
`reconciliation.json`：分片源覆盖率、重复/遗漏检查和未解码计数。

状态 counted/indexed_objects/indexed/parsed_typetree/extracted/validated_png/raw_fallback/decode_error/load_error 不等价。TypeTree 缺失、跨 bundle PPtr/stream 数据未解析、SpriteAtlas UV、Switch 平台纹理布局、Wwise、CRI、NSO、IL2CPP 类型恢复均需要额外验证。CI 不提交生成的原始图片和二进制到 Git，只保留 Actions artifacts。