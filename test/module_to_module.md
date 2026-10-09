# BK7238 模组对模组 TCP/UDP 透传联调报告

- 时间: 2026-10-09 17:26:18
- AP 模组: COM7 (SoftAP `BK-M2M`), STA 模组: COM6
- 固件: at-esp32c3-compat_2M.1220.bin (同版双模组)
- 载荷说明: 报告中的收发负载原为第三方教程示例（域名 11 字节 / 公司名 36 字节），
  已替换为品牌标识 sparkleiot (10 字节) 与 SparkleIOT (10 字节)，
  CIPSEND 长度参数同步改为 10。替换不涉及 AT 解析与协议收发路径。

| # | 阶段 | 测试项 | 命令 | 结果 | 实际 |
|---|------|--------|------|------|------|
| 1 | 0-拓扑 | AP 模组 测前复位 (走干净上电路径) | `AT+RST` | PASS | 复位后 AT 应答正常 |
| 2 | 0-拓扑 | STA 模组 测前复位 (走干净上电路径) | `AT+RST` | PASS | 复位后 AT 应答正常 |
| 3 | 0-拓扑 | AP 模组应答 | `AT` | PASS | OK |
| 4 | 0-拓扑 | STA 模组应答 | `AT` | PASS | OK |
| 5 | 0-拓扑 | AP 模组设纯 AP 模式 | `AT+CWMODE=2` | PASS | OK |
| 6 | 0-拓扑 | SoftAP 配置已一致(跳过重配, 保持上电路径 netif) | `AT+CWSAP? 匹配` | PASS | +CWSAP:"BK-M2M","12345678",8,0 ⏎ OK |
| 7 | 0-拓扑 | AP 模组 CWSAP 查询 | `AT+CWSAP?` | PASS | +CWSAP:"BK-M2M","12345678",8,0 ⏎ OK |
| 8 | 0-拓扑 | STA 模组设纯 STA 模式 | `AT+CWMODE=1` | PASS | OK |
| 9 | 1-AP广播 | STA 扫描到 BK-M2M (SoftAP 广播验证) | `AT+CWLAP` | PASS | 第 1 次扫描命中: +CWLAP:(0,"BK-M2M" |
| 10 | 1-AP广播 | STA 关联 AP 并获得 IP | `AT+CWJAP` | PASS | 第 1 次尝试后 STAIP=192.168.4.3 |
| 11 | 1-AP广播 | AP 模组读取 IP | `AT+CIPAP?` | PASS | AP IP = 192.168.4.1 |
| 12 | 1-AP广播 | 关联后数据面基线 (STA ping AP) | `AT+PING="192.168.4.1"` | PASS | +PING:4 ⏎ OK |
| 13 | 2-TCP普通 | AP 侧开 TCP 服务端 | `AT+CIPSERVER=1` | PASS | OK |
| 14 | 2-TCP普通 | STA 侧建 TCP 连接 (CONNECT 事件) | `AT+CIPSTART` | PASS | 第 1 次尝试 / CONNECT |
| 15 | 2-TCP普通 | AP 侧收到客户端接入 (0,CONNECT) | `(被动)` | PASS | 0,CONNECT |
| 16 | 2-TCP普通 | STA→AP 数据 (AP 侧 +IPD) | `AT+CIPSEND=14` | PASS | +IPD,0,14:HELLO-FROM-STA |
| 17 | 2-TCP普通 | AP→STA 数据 (STA 侧 +IPD) | `AT+CIPSEND=0,13` | PASS | +IPD,13:WORLD-FROM-AP |
| 18 | 2-TCP普通 | STA 断开连接 | `AT+CIPCLOSE` | PASS |  |
| 19 | 2-TCP普通 | AP 收到断开事件 (0,CLOSED) | `(被动)` | PASS | 0,CLOSED |
| 20 | 2-TCP普通 | 关闭 TCP 服务端 | `AT+CIPSERVER=0` | PASS |  |
| 21 | 3-TCP透传 | AP 侧重开 TCP 服务端 | `AT+CIPSERVER=1` | PASS | OK |
| 22 | 3-TCP透传 | STA 设透传模式 | `AT+CIPMODE=1` | PASS | OK |
| 23 | 3-TCP透传 | STA 透传建连 (RF 抖动自动重试) | `AT+CIPSTART` | PASS | 第 1 次尝试 / CONNECT |
| 24 | 3-TCP透传 | STA 进入透传 (提示符) | `AT+CIPSEND` | PASS | > |
| 25 | 3-TCP透传 | STA 裸发→AP 收到数据(+IPD 分块容忍) | `(裸数据)` | PASS | 0,CONNECT ⏎ +IPD,0,20:TCP-PASSTHRU-DATA-01+IPD,0,8:23456789 |
| 26 | 3-TCP透传 | AP 回发→STA 收裸数据(无+IPD) | `AT+CIPSEND=0,n` | PASS | TCP-PONG-FROM-AP |
| 27 | 3-TCP透传 | +++ 退出透传后 AT 恢复 | `+++/AT` | PASS | OK |
| 28 | 4-UDP普通 | AP 侧开 UDP 服务端 | `AT+CIPSERVER=1,,"UDP"` | PASS | OK |
| 29 | 4-UDP普通 | STA 建 UDP 连接 (含 udp mode 参数) | `AT+CIPSTART=UDP` | PASS | OK |
| 30 | 4-UDP普通 | STA→AP UDP (对端学习, 丢包重试) | `AT+CIPSEND=12` | PASS | 第 1 次尝试 / +IPD,5,12:UDP-FROM-STA |
| 31 | 4-UDP普通 | AP→STA UDP 回发 (丢包重试) | `AT+CIPSEND=5,10` | PASS | 第 1 次尝试 / +IPD,11:UDP-FROM-AP |
| 32 | 4-UDP普通 | 关闭 UDP 服务端 | `AT+CIPSERVER=0` | PASS |  |
| 33 | 5-UDP透传 | AP 侧重开 UDP 服务端 | `AT+CIPSERVER=1,,"UDP"` | PASS | OK |
| 34 | 5-UDP透传 | STA 透传 UDP 建连 | `CIPMODE=1/CIPSTART` | PASS | OK |
| 35 | 5-UDP透传 | STA 裸发→AP 收到 (UDP 透传, 丢包重试) | `(裸数据)` | PASS | 第 1 次尝试 / +IPD,5,17:UDP-PASSTHRU-DATA |
| 36 | 5-UDP透传 | AP 回发→STA 收裸数据 | `AT+CIPSEND=5,n` | PASS | UDP-PONG |
| 37 | 5-UDP透传 | +++ 退出后 AT 恢复 | `+++/AT` | PASS | OK |

**合计: 37 PASS / 0 FAIL**
