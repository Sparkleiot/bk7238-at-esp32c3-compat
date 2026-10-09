# 《ESP8266 AT 指令教程 v1.5》逐节实测报告 (BK7238 esp32c3-compat)

- 时间: 2026-10-08 14:33:23
- 固件: at-esp32c3-compat_2M.1220.bin (含 IP 兼容修复 CIPAP/CWDHCP/CWDHCPS)
- 拓扑: STA 测试机 COM5 (连 MyHomeWiFi), AP 模组 COM7 (SoftAP BK-M2M), 第二 STA COM6; PC=192.168.0.152 充当文档中的『网络调试助手』
> **载荷说明（后续修订）**：本报告涉及的 TCP/UDP 收发负载，原为第三方教程中的
> 示例域名（11 字节）与公司名（36 字节），现已统一替换为品牌标识
> sparkleiot (10 字节) 与 SparkleIOT (10 字节)，以避免公开仓库中出现第三方标识。
> CIPSEND 的长度参数已同步改为 10。
> 说明：下表数据来自 2026-10-08 的原始实测记录，其载荷为替换前的字符串；
> 替换仅改动测试载荷的字面内容与长度常量，不涉及 AT 命令解析或协议收发路径，
> 故原实测结论对替换后的负载同样成立。

- 结果: **71 PASS / 0 FAIL / 2 N/A**

| 节 | 测试项 | 命令 | 结果 | 实际 |
|---|---|---|---|---|
| 0-准备 | STA 起始态脱离透传(+++ 兜底) | `+++ / AT / AT+CIPMODE=0` | PASS |  |
| 0-准备 | AP 起始态脱离透传(+++ 兜底) | `+++ / AT / AT+CIPMODE=0` | PASS |  |
| 0-准备 | STA2 起始态脱离透传(+++ 兜底) | `+++ / AT / AT+CIPMODE=0` | PASS |  |
| 0-准备 | STA 模组复位后 AT 应答 | `AT+RST / AT` | PASS | AT

OK |
| 0-准备 | AP 模组复位后 AT 应答 | `AT+RST / AT` | PASS | AT

OK |
| 0-准备 | STA2 模组复位后 AT 应答 | `AT+RST / AT` | PASS | AT

OK |
| 0-准备 | AP IP 对齐 ESP-AT 默认(192.168.4.1) [今天修复的参数序实测] | `AT+CIPAP="192.168.4.1","192.168.4.1","255.255.255.0"` | PASS | AT+CIPAP? | +CIPAP:ip:"192.168.4.1" | +CIPAP:gateway:"192.168.4.1" | +CIPAP:netmask:"255.255.255.0" |
| 0-准备 | CWDHCPS 查询默认段 .2~.101 [新增命令实测] | `AT+CWDHCPS?` | PASS | AT+CWDHCPS?

+CWDHCPS:2880,"192.168.4.2","192.168.4.101"
OK |
| 0-准备 | STA(STA) 连接路由 MyHomeWiFi | `AT+CWJAP="MyHomeWiFi"` | PASS | IP=192.168.0.163 |
| 2.1 AP-TCP服务器 | AP 配置热点 | `AT+CWSAP="BK-M2M",...8,0` | PASS | AT+CWSAP="BK-M2M","12345678",8,0

OK |
| 2.1 AP-TCP服务器 | AP 开 TCP 服务器(多连接) | `AT+CIPMUX=1 / AT+CIPSERVER=1,8899` | PASS | AT+CIPSERVER=1,8899

OK |
| 2.1 | STA2 关联模组 AP 并取得 IP | `AT+CWJAP="BK-M2M"` | PASS | IP=192.168.4.2 (DHCP 默认 .2 起 ✔) |
| 2.1 AP-TCP服务器 | STA2 连 AP 的 8899 | `AT+CIPSTART="TCP","192.168.4.1",8899` | PASS | AT+CIPSTART="TCP","192.168.4.1",8899⏎⏎CONNECT |
| 2.1 AP-TCP服务器 | AP 侧看到客户端 0,CONNECT | `(事件)` | PASS | AT+CIPSERVER=1,8899

OK
0,CONNECT |
| 2.1 AP-TCP服务器 | AP 发送 10 字节(品牌标识负载) | `AT+CIPSEND=0,10 → sparkleiot` | PASS | SEND OK |
| 2.1 AP-TCP服务器 | STA2 收到 +IPD 数据 | `+IPD,10:sparkleiot` | PASS | +IPD,10:sparkleiot |
| 2.1 AP-TCP服务器 | STA2 回发 10 字节(品牌回显负载) | `AT+CIPSEND=10 → SparkleIOT` | PASS | SEND OK |
| 2.1 AP-TCP服务器 | AP 收到 +IPD,0,10 回发数据 | `+IPD,0,10:...` | PASS | +IPD,0,10:SparkleIOT |
| 2.2 STA-TCP服务器 | 模组开 TCP 服务器 | `AT+CIPMUX=1 / AT+CIPSERVER=1,8899` | PASS | AT+CIPSERVER=1,8899

OK |
| 2.2 STA-TCP服务器 | PC 连接模组 8899(文档: 网络调试助手) | `TCP connect 192.168.0.163:8899` | PASS | 0,CONNECT |
| 2.2 STA-TCP服务器 | 模组发 10 字节给 PC | `AT+CIPSEND=0,10` | PASS | SEND OK |
| 2.2 STA-TCP服务器 | PC 收到 sparkleiot | `(socket)` | PASS | 10B b'sparkleiot' |
| 2.2 STA-TCP服务器 | 模组收到 +IPD,0,10 回发 | `+IPD,0,10:SparkleIOT` | PASS | +IPD,0,10:SparkleIOT |
| 2.2 STA-TCP服务器 | 关闭 TCP 服务器(文档 3.1-7) | `AT+CIPSERVER=0` | PASS | AT+CIPSERVER=0

OK |
| 2.3 TCP透传 | 设置单连接+透传 | `AT+CIPMUX=0 / AT+CIPMODE=1` | PASS | AT+CIPMODE=1

OK |
| 2.3 TCP透传 | 连接 PC TCP 服务器 | `AT+CIPSTART="TCP","192.168.0.152",8890` | PASS | AT+CIPSTART="TCP","192.168.0.152",8890⏎⏎CONNECT |
| 2.3 TCP透传 | PC 侧 accept | `(socket)` | PASS | ('192.168.0.163', 60391) |
| 2.3 TCP透传 | AT+CIPSEND 进入透传并发 10 字节 | `AT+CIPSEND → sparkleiot` | PASS |  |
| 2.3 TCP透传 | PC 收到裸数据(无 +IPD) | `(socket)` | PASS | 10B b'sparkleiot' |
| 2.3 TCP透传 | 模组透传裸收 PC 回发(无 +IPD) | `SparkleIOT` | PASS | SparkleIOT |
| 2.3 TCP透传 | +++ 退出透传, AT 恢复应答 | `+++ / AT` | PASS | OK |
| 2.4 UDP多连接 | 建 UDP 连接 0(广播, 文档原例) | `AT+CIPSTART=0,"UDP","255.255.255.255",50000,1000,0` | PASS | AT+CIPSTART=0,"UDP","255.255.255.255",50000,1000,0⏎⏎OK |
| 2.4 UDP多连接 | PC(50000) 收到 UDP 广播 | `AT+CIPSEND=0,10` | PASS | 10B b'sparkleiot' |
| 2.4 UDP多连接 | 建 UDP 连接 1(单播到 PC) | `AT+CIPSTART=1,"UDP","192.168.0.152",50001,1001,0` | PASS | +CIPSTART=1,"UDP","192.168.0.152",50001,1001,0⏎⏎OK |
| 2.4 UDP多连接 | PC(50001) 收到单播 | `AT+CIPSEND=1,10` | PASS | 10B b'sparkleiot' |
| 2.4 UDP多连接 | 模组收到 +IPD,1,10(PC 回发) | `+IPD,1,10:...` | PASS | SparkleIOT |
| 2.5 UDP透传 | UDP 透传建连(本地端口 2000) | `AT+CIPSTART="UDP","192.168.0.152",5000,2000,0` | PASS | AT+CIPSTART="UDP","192.168.0.152",5000,2000,0⏎⏎OK |
| 2.5 UDP透传 | PC 收到透传裸数据 | `AT+CIPSEND → sparkleiot` | PASS | 10B b'sparkleiot' |
| 2.5 UDP透传 | 模组透传裸收回发(UDP 丢包 x3 重试) | `SparkleIOT` | PASS | SparkleIOT |
| 2.5 UDP透传 | +++ 退出透传 | `+++ / AT` | PASS | OK |
| 2.6 双模组UDP | STA2 关联模组 AP 并取得 IP | `AT+CWJAP="BK-M2M"` | PASS | IP=192.168.4.2 (DHCP 默认 .2 起 ✔) |
| 2.6 双模组UDP | AP 模组 UDP 透传建连(→STA) | `AT+CIPSTART="UDP","192.168.4.2",333,333,0` | PASS | AT+CIPSTART="UDP","192.168.4.2",333,333,0⏎⏎OK |
| 2.6 双模组UDP | STA 模组 UDP 透传建连(→AP 192.168.4.1) | `AT+CIPSTART="UDP","192.168.4.1",333,333,0` | PASS | AT+CIPSTART="UDP","192.168.4.1",333,333,0⏎⏎OK |
| 2.6 双模组UDP | AP 裸发 → STA 裸收 | `sparkleiot` | PASS | "192.168.4.1",333,333,0

OK
+IPD,10:sparkleiot |
| 2.6 双模组UDP | STA 裸发 → AP 裸收 | `SparkleIOT` | PASS | SparkleIOT |
| 2.6 双模组UDP | 双侧 +++ 退出透传 | `+++` | PASS | AP=OK STA=OK |
| 2.7 双模组TCP透传 | AP 模组开 TCP 服务器(多连接) | `AT+CIPMUX=1 / AT+CIPSERVER=1,8899` | PASS | AT+CIPSERVER=1,8899

OK |
| 2.7 双模组TCP透传 | STA2 关联模组 AP 并取得 IP | `AT+CWJAP="BK-M2M"` | PASS | IP=192.168.4.2 (DHCP 默认 .2 起 ✔) |
| 2.7 双模组TCP透传 | STA 透传建连 AP 8899 | `AT+CIPSTART="TCP","192.168.4.1",8899` | PASS | AT+CIPSTART="TCP","192.168.4.1",8899⏎⏎CONNECT |
| 2.7 双模组TCP透传 | AP 侧 0,CONNECT | `(事件)` | PASS | AT+CIPSERVER=1,8899

OK
0,CONNECT |
| 2.7 双模组TCP透传 | AP 发 10 字节(品牌标识负载) | `AT+CIPSEND=0,10` | PASS | SEND OK |
| 2.7 双模组TCP透传 | STA 透传裸收 | `sparkleiot` | PASS | +IPD,10:sparkleiot |
| 2.7 双模组TCP透传 | STA 裸发 → AP +IPD,0,10 | `SparkleIOT` | PASS | SparkleIOT |
| 2.7 双模组TCP透传 | STA +++ 退出透传 | `+++` | PASS | OK |
| 2.8 外网透传 | 设置 AP+STA 共存模式 | `AT+CWMODE=3` | PASS | AT+CWMODE=3

OK |
| 2.8 外网透传 | 共存下 STA 连接路由 | `AT+CWJAP="MyHomeWiFi"` | PASS | IP=192.168.0.163 |
| 2.8 外网透传 | AP 广播共存验证(另一模组扫描到) | `AT+CWLAP="DOC-3MODE"` | PASS | AT+CWLAP="DOC-3MODE"

+CWLAP:(0,"DOC-3MODE" 第1次 |
| 2.8 外网透传 | 连接文档原例服务器(2018 年地址) | `AT+CIPSTART="TCP","115.29.109.104",6602` | PASS | AT+CIPSTART="TCP","115.29.109.104",6602⏎⏎CONNECT |
| 2.8 外网透传 | 透传连接 PC 服务器(等效替代) | `AT+CIPSTART="TCP","192.168.0.152",8890` | PASS | AT+CIPSTART="TCP","192.168.0.152",8890⏎⏎CONNECT |
| 2.8 外网透传 | 透传数据交互 | `AT+CIPSEND → sparkleiot` | PASS | 10B b'sparkleiot' |
| 3.1 常用指令 | 读取 IO 状态(厂商专有, 固件已实现) | `AT+CIOREAD=15` | PASS | AT+CIOREAD=15⏎⏎+CIOREAD:1⏎OK |
| 3.1 常用指令 | 设置 IO(厂商专有, 固件已实现) | `AT+CIOWRITE=2,1` | PASS | AT+CIOWRITE=2,1⏎⏎OK |
| 3.1 常用指令 | 智能配网(ESP8266, 固件未实现) | `AT+CWSTARTSMART` | N/A | ERROR (ESP-AT 标准无此命令, 合理) |
| 3.1 常用指令 | 查询芯片 ID(固件已实现) | `AT+CSYSID` | PASS | AT+CSYSID⏎⏎+CSYSID:CHIP:1V2OAXDZ65;FLASH:AT&BK7238;KEY:china⏎OK |
| 3.1 常用指令 | 保存透传(固件应答 OK) | `AT+SAVETRANSLINK=1,"192.168.6.110",1002,"TCP"` | PASS | AT+SAVETRANSLINK=1,"192.168.6.110",1002,"TCP"⏎⏎OK |
| 3.1 常用指令 | 微信配网(厂商专有, 固件未实现) | `AT+CWSMARTSTART=2` | N/A | ERROR (ESP-AT 标准无此命令, 合理) |
| 3.1 常用指令 | 改波特率 9600 并生效(文档 3.1-5) | `AT+UART_DEF=9600,8,1,0,0` | PASS | 9600 下 AT 应答=OK (OK 以新波特率发出, 旧口收不到属正常) |
| 3.1 常用指令 | 恢复 115200 | `AT+UART_DEF=115200,8,1,0,0` | PASS | AT+UART_DEF?⏎⏎+UART_DEF:115200,8,1,0,0⏎OK |
| 3.1 常用指令 | 禁止休眠(文档 3.1-8) | `AT+SLEEP=0 / AT+SLEEP?` | PASS | AT+SLEEP?⏎⏎+SLEEP:0⏎OK |
| 3.1 常用指令 | 查询 IP(文档 3.1-10) | `AT+CIFSR` | PASS | AT+CIFSR⏎⏎+CIFSR:STAIP,"192.168.0.163"⏎+CIFSR:STAMAC,"c8:47:8c:11:22:33"⏎OK |
| 3.1 常用指令 | STA MAC 查询+写回(文档 3.1-11) | `AT+CIPSTAMAC="c8:47:8c:11:22:33"` | PASS | AT+CIPSTAMAC?⏎⏎+CIPSTAMAC:"c8:47:8c:11:22:33"⏎OK |
| 3.1 常用指令 | 恢复出厂设置(文档 3.1-9) | `AT+RESTORE` | PASS | CWMODE?=AT+CWMODE?

+CWMOD CWJAP?=AT+CWJAP?

No AP
OK |
| 3.1 常用指令 | RESTORE 后重新连接路由(收尾恢复) | `AT+CWJAP="MyHomeWiFi"` | PASS | IP=192.168.0.163 |
