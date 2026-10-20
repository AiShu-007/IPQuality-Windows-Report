# 来源与许可证

本项目是 xykt/IPQuality 的第三方 Windows 便携适配与图片报告扩展，不是上游官方发行版。

- 上游：https://github.com/xykt/IPQuality
- `ipquality-original.sh`：保留下载的上游原文件，不改写原始内容，版本 v2026-09-16。
- 2026-10-20 新增/修改：Windows 启动、依赖打包、代理环境设置、IPQS JSON 字段修正、图片排版、SMTP CONNECT 与 DoH 补充查询。
- 本项目源码整体按 GNU AGPL v3 发布，完整文本见 LICENSE；新增代码 Copyright (C) 2026 sunzh815。
- 本工具按现状提供，不附带任何担保；可按 LICENSE 复制、修改及再发布。

便携包的 Python、Pillow、curl、jq、bc、Git for Windows/MSYS 工具各按自身许可证发布。
构建时保留上游许可证，并在 THIRD_PARTY.md 记录二进制版本、来源和对应源码入口。
运行时从使用者自己的 Windows 证书库读取公开根证书，构建者的证书库不会分发。
