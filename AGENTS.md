# BDSP Resources
- 原始 1.3.0 目录只读。派生输出放 Unpack/v1.3.0/，不覆盖输入。
- 每个结果记录来源、大小、SHA-256、工具版本、对象 ID、阶段和错误。
- 文件计数、对象索引、提取、解析、验证必须分开；未知格式/字段标注 UNKNOWN。
- 文档使用 Obsidian Markdown；参见 docs/bdsp/README.md。
- 不把生成的大型二进制或图片直接提交 Git；CI 使用 artifacts。