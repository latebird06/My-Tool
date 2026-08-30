# IP Purity

IP Purity 是一个本地运行的出口 IP 信誉与网络旁路诊断工具。软件名和图标使用英文，桌面界面使用中文，视觉风格与 WordSprint 保持一致。

## 桌面版

```bash
git clone git@github.com:latebird06/My-Tool.git
cd My-Tool
./install.sh
```

安装完成后可从 Ubuntu 应用菜单搜索 **IP Purity**。安装脚本会复制程序和图标到用户目录，不会覆盖源码仓库；再次执行可安全更新。直接从源码运行也可以使用 `./ipcheck_desktop_app.py`。

当前包含以下模块：

- 自动识别当前 IPv4、IPv6 出口，也可手动检查任意 IPv4/IPv6；
- IPinfo（失败时使用备用源）、Scamalytics、IPQualityScore、AbuseIPDB；
- 多源最高风险原则的透明评分，分别展示信誉风险和泄漏风险；
- IPv4/IPv6 出口地区一致性、本机公网地址与潜在旁路检查；
- systemd-resolved DNS 路由与解析器地区线索；
- 系统默认路由的延迟和丢包测量；
- YouTube、Netflix、Disney+ 的实验性连通性检查；
- 超时、限流、密钥错误、网络失败和解析格式变化的详细状态。

IPQualityScore 与 AbuseIPDB 是可选数据源，密钥保存在同目录 `config.json`，权限为 `0600`，不会写入检测报告。AbuseIPDB 使用官方 `GET /api/v2/check` 接口；IPQS 密钥放在请求头中，不会出现在 URL。

## 命令行

```bash
python3 check_ip_purity.py --json
python3 check_ip_purity.py 8.8.8.8 --json
python3 check_ip_purity.py 2001:4860:4860::8888 --json
```

桌面窗口依赖 GTK 3 和 PyGObject（Ubuntu 包 `python3-gi`），检测核心只使用 Python 标准库；本地模块会调用系统自带的 `ip`、`ping` 和 `resolvectl`。

如果安装脚本提示缺少依赖，在 Ubuntu 执行：

```bash
sudo apt install python3 python3-gi gir1.2-gtk-3.0 iproute2 iputils-ping systemd-resolved
```

## 结果边界

- 信誉数据库是第三方观测，不能保证一个 IP 永远安全或一定可用。
- DNS 服务器地区不同只是旁路线索；anycast、加密 DNS 和代理 fake-IP 模式都可能造成合理差异。
- 本机网卡扫描不能代替浏览器内的 WebRTC ICE/STUN 测试。
- 平台模块只验证 HTTP 连通和响应，不证明账号地区、片库或视频播放已解锁。
- 手动检查第三方 IP 时，应用不会拿该 IP 的国家与本机 DNS 做无意义比较。
