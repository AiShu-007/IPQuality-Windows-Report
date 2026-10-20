# Windows x64 便携版 v1.0.1

下载名称包含 Portable 的 ZIP，完整解压后打开代理软件，双击 Start.cmd 即可。

- 自动读取系统静态代理、代理环境变量和常见本机端口。
- 验证 HTTP 代理能访问公网并取得有效 IPv4 后直接开始检测，无需回车确认。
- 检测不到可用代理时才提示输入；仍支持 --proxy 手动指定。
- 保留完整 PNG、JSON、TXT、ANSI、明细及离线自检。

支持 Windows 10/11 x64，无需安装 Python、Git 或 Docker。仅 TUN/PAC 或自定义端口且未配置系统代理时，可能需手动指定 HTTP/mixed 端口。多代理同时运行时优先选择有效的系统代理，可用 --proxy 覆盖。不切换节点，不修改系统代理。

基于 xykt/IPQuality，第三方适配，AGPL-3.0。
