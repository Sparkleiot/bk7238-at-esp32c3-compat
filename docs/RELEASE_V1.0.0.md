## V1.0.0 —— 首个对外发布版本（供用户测试）

把 Sparkleiot XH-WB3S（Beken BK7238）原厂 AT 固件，改造成**ESP32-C3 / ESP-AT 兼容版**：
凡是原本写给 ESP-AT 的上位机代码，换到这块模组上应当直接可用。

> 这是首个对外发布版本，**模组不需要退回、不归还、不回收**，请直接留在你手上长期测试。

---

### 这个版本解决了什么

原厂 AT 固件与 ESP-AT 有若干**协议层与行为层差异**，会让上位机代码在 BK7238 上出错。本版本把它们逐条对齐：

| 差异点 | 本版本行为 |
|---|---|
| `AT+GMR` 版本信息格式 | 与 ESP-AT 一致的四行格式 |
| TCP/UDP 接收数据前缀 | 补齐 `+IPD` / `+IURD` 前缀 |
| `AT+CIPCLOSE` | 改为**同步**，返回 `OK` 时连接已真正关闭（原为异步，会导致紧随的 `CIPSTART` 报 linkid error） |
| `AT+CIPSTART` 连接超时 | 增加超时，避免永久阻塞 |
| `AT+PING` | 自研 ICMP 实现，返回 `+PING:<rtt>` / `+PING:TIMEOUT` |
| 线程槽 | 连接句柄槽可正确回收，不再只增不减 |
| `AT+CIPSERVER=0` | 可正常关闭 passive server |
| `AT+CIPSTART="TLS"` | 已可用（含 `AT+CIPSSLCCONF?`，接受 `"SSL"` 别名） |
| SoftAP 数据面 | 补`net_wlan_add_netif()`：DHCP 能拿到 IP，但 ping/TCP/UDP 全部失效的坑已修 |
| 上电恢复 SoftAP | RF 校准就绪后再起 AP，不再静默失败导致模组不广播 beacon |

---

### 测试状态（全部真机实测）

| 测试套件 | 结果 |
|---|---|
| 文档 v1.5 全量验收（单模组连真实 AP） | **71 PASS / 0 FAIL / 2 N/A** |
| 模组对模组（STA↔SoftAP，五阶段含 UDP 透传） | **37 PASS / 0 FAIL** |
| TLS 能力 | **5 PASS / 0 FAIL** |
| AT 兼容性 | **55 / 55 PASS** |
| 功能测试 | **16 / 16 PASS** |

报告在仓库的 [`test/`](test/) 目录。

**已知限制**：HTTP chunked 响应未做脱块处理（`utils_httpc.c` 分块解析，不影响模组对模组场景）。

---

### 使用前必读

1. **烧录会覆盖原厂固件。** 回退方法见 README §8。
2. **AT 命令格式**见 [`docs/AT指令说明.md`](docs/AT指令说明.md)，与 ESP-AT 的差异逐条列明。
3. **回归脚本**见 README §1.4，烧录后可用它自测。
4. **发现问题请提 GitHub Issue**，附上 `AT+GMR` 输出与复现步骤。

烧录后模组不会自动连 WiFi（整片烧录会清空 env 里存的配置），请先用串口工具下发
`AT+CWJAP="你的SSID","你的密码"` 配网再做联调测试。

---

### 许可

自有新增工作采用 MIT；`src/` 内含第三方组件，各按其条款，
详见 [`LICENSE`](LICENSE) 与 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。
Sparkleiot 已获 Beken 对 SDK 的授权，但该授权不传递给SDK 集成的第三方组件。