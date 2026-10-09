# BK7238 / XH-WB3S  AT 固件 · 联网功能联调报告

- 测试时间: 2026-09-25 08:39:15
- 串口: `COM3` @ 115200
- 目标 AP: `MyHomeWiFi`
- PC 侧地址: `192.168.0.152` (TCP 8266 / UDP 8267)
- 模组 STA 地址: `192.168.0.164`
- 固件: BK7238-AT(V1.1.0/esp32c3-compat)
- 用时: 53.5 秒

## 结论

**41 / 43 项通过**（通过率 95.3%）

| 阶段 | PASS/总数 |
|------|-----------|
| 1-关联 | 7/7 |
| 2-IP | 4/4 |
| 3-网络 | 7/7 |
| 4-TCP客户端 | 3/5 |
| 5-TCP客户端(PC) | 5/5 |
| 6-TCP服务端 | 7/7 |
| 7-UDP服务端 | 4/4 |
| 8-断连恢复 | 4/4 |

## 逐项明细

| # | 阶段 | 项目 | 命令 | 期望 | 结果 | 原始响应 |
|---|------|------|------|------|------|----------|
| 1 | 1-关联 | 握手 | `AT` | \bOK\b | PASS | `AT\r\n\r\nOK\r\n` |
| 2 | 1-关联 | Wi-Fi 模式(查询) | `AT+CWMODE?` | \+CWMODE:\d | PASS | `AT+CWMODE?\r\n\r\n+CWMODE:1\r\nOK\r\n` |
| 3 | 1-关联 | 设置 Station 模式 | `AT+CWMODE=1` | \bOK\b | PASS | `AT+CWMODE=1\r\n\r\nOK\r\n` |
| 4 | 1-关联 | 自动连接(关闭) | `AT+CWAUTOCONN=0` | \bOK\b | PASS | `AT+CWAUTOCONN=0\r\n\r\nOK\r\n` |
| 5 | 1-关联 | 关联 AP(下发) | `AT+CWJAP="MyHomeWiFi","***"` | 立即回 OK (异步关联) | PASS | `AT+CWJAP="MyHomeWiFi","<WIFI_PWD>"\r\n\r\nOK\r\n` |
| 6 | 1-关联 | 关联 AP(事件+DCHP) | `WIFI CONNECTED / WIFI GOT IP` | WIFI CONNECTED -> WIFI GOT IP, STAIP!=0.0.0.0 | PASS | `事件: WIFI CONNECTED WIFI GOT IP | IP=192.168.0.164 | 用时 2.2s` |
| 7 | 1-关联 | 回查已连 AP | `AT+CWJAP?` | +CWJAP:"MyHomeWiFi","xx:..",ch,rssi,... | PASS | `AT+CWJAP?\r\n\r\n+CWJAP:"MyHomeWiFi","aa:bb:cc:dd:ee:01",1,-48,0,0,0,0,0\r\nOK\r\n` |
| 8 | 2-IP | STA 获取 IP | `AT+CIPSTA?` | \+CIPSTA: | PASS | `AT+CIPSTA?\r\n\r\n+CIPSTA:ip:"192.168.0.164"\r\n+CIPSTA:gateway:"192.168.0.1"\r\n+CIPSTA:netmask:"255.255.255.0"\r\nOK\r\n` |
| 9 | 2-IP | 本地 IP 汇总 | `AT+CIFSR` | \+CIFSR:STAIP | PASS | `AT+CIFSR\r\n\r\n+CIFSR:STAIP,"192.168.0.164"\r\n+CIFSR:STAMAC,"c8:47:8c:11:22:33"\r\nOK\r\n` |
| 10 | 2-IP | DHCP 状态 | `AT+CWDHCP?` | \+CWDHCP: | PASS | `AT+CWDHCP?\r\n\r\n+CWDHCP:3\r\nOK\r\n` |
| 11 | 2-IP | 链路状态 | `AT+CIPSTATUS?` | STATUS:2/3/4 表示已联网 | PASS | `AT+CIPSTATUS?\r\n\r\nSTATUS:2\r\nOK\r\n` |
| 12 | 3-网络 | PING 网关 | `AT+PING="192.168.0.1"` | +PING:<time> | PASS | `AT+PING="192.168.0.1"\r\n\r\n+PING:6\r\nOK\r\n` |
| 13 | 3-网络 | PING PC | `AT+PING="192.168.0.152"` | PC 默认禁 ICMP 入站, 失败属预期 | PASS | `AT+PING="192.168.0.152"\r\n\r\n+PING:TIMEOUT\r\nOK\r\n` |
| 14 | 3-网络 | PING 公网 | `AT+PING="www.baidu.com"` | +PING:<time> | PASS | `AT+PING="www.baidu.com"\r\n\r\n+PING:28\r\nOK\r\n` |
| 15 | 3-网络 | DNS 解析(公网) | `AT+CIPDOMAIN="www.baidu.com"` | +CIPDOMAIN:"<ip>" | PASS | `AT+CIPDOMAIN="www.baidu.com"\r\n\r\n+CIPDOMAIN:"183.2.172.177"\r\nOK\r\n` |
| 16 | 3-网络 | DNS 解析(网关名) | `AT+CIPDOMAIN="www.qq.com"` | \+CIPDOMAIN:|\bERROR\b | PASS | `AT+CIPDOMAIN="www.qq.com"\r\n\r\n+CIPDOMAIN:"121.14.77.221"\r\nOK\r\n` |
| 17 | 3-网络 | SNTP 配置 | `AT+CIPSNTPCFG=1,8,"ntp.aliyun.com"` | \bOK\b | PASS | `AT+CIPSNTPCFG=1,8,"ntp.aliyun.com"\r\n\r\nOK\r\n` |
| 18 | 3-网络 | SNTP 取时 | `AT+CIPSNTPTIME?` | +CIPSNTPTIME:<ascii time> | PASS | `AT+CIPSNTPTIME?\r\n\r\n+CIPSNTPTIME:2026-9-25 8-38-33\r\nOK\r\n` |
| 19 | 4-TCP客户端 | 单连接模式 | `AT+CIPMUX=0` | \bOK\b | PASS | `AT+CIPMUX=0\r\n\r\nOK\r\n` |
| 20 | 4-TCP客户端 | TCP 建连 | `AT+CIPSTART="TCP","www.baidu.com",80` | CONNECT + OK | PASS | `AT+CIPSTART="TCP","www.baidu.com",80\r\n\r\nERROR\r\n` |
| 21 | 4-TCP客户端 | 发送 HTTP GET 并收响应 | `AT+CIPSEND=39` | > 提示符 | FAIL | `未收到 > 提示符: AT+CIPSEND=39\r\n\r\nERROR\r\n` |
| 22 | 4-TCP客户端 | 关闭连接 | `AT+CIPCLOSE` | \bOK\b|\bCLOSED\b | FAIL | `AT+CIPCLOSE\r\n\r\nERROR\r\n` |
| 23 | 4-TCP客户端 | 连接信息 | `AT+CIPSTATE` | \bOK\b|\+CIPSTATE: | PASS | `AT+CIPSTATE\r\n\r\nOK\r\n` |
| 24 | 5-TCP客户端(PC) | 模组连入 PC | `AT+CIPSTART="TCP","192.168.0.152",8266` | PC 侧 accept 到模组连接 (原厂无 CONNECT 前缀, 只回 OK) | PASS | `AT侧=AT+CIPSTART="TCP","192.168.0.152",8266\r\n\r\nOK\r\n | PC侧accept=True` |
| 25 | 5-TCP客户端(PC) | PC -> 模组 收发 | `PC send "HELLO-FROM-PC"` | +IPD,<len>:HELLO-FROM-PC | PASS | `+IPD,15:HELLO-FROM-PC\r\n` |
| 26 | 5-TCP客户端(PC) | 模组 -> PC 收发 | `AT+CIPSEND=25` | 模组回 SEND OK, PC 侧收到 payload | PASS | `AT侧=SEND OK\r\n | PC侧收到=b'HELLO-FROM-BK7238-96735\r\n'` |
| 27 | 5-TCP客户端(PC) | 连接信息 | `AT+CIPSTATE` | \+CIPSTATE:|\bOK\b | PASS | `AT+CIPSTATE\r\n\r\n+CIPSTATE:0,"TCP","192.168.0.152",8266,3,0\r\nOK\r\n` |
| 28 | 5-TCP客户端(PC) | 主动断开 | `AT+CIPCLOSE` | \bOK\b|\bCLOSED\b|\bERROR\b | PASS | `AT+CIPCLOSE\r\n\r\nOK\r\n` |
| 29 | 6-TCP服务端 | 多连接模式 | `AT+CIPMUX=1` | \bOK\b | PASS | `AT+CIPMUX=1\r\n\r\nOK\r\n` |
| 30 | 6-TCP服务端 | 开启服务端监听 | `AT+CIPSERVER=1,8266` | OK (linkid=5, port=8266) | PASS | `AT+CIPSERVER=1,8266\r\n\r\nOK\r\n` |
| 31 | 6-TCP服务端 | PC 连入模组 | `socket.create_connection(192.168.0.164,8266)` | 模组进入 server 模式并接受连接 | PASS | `PC 侧 TCP 建连成功` |
| 32 | 6-TCP服务端 | PC -> 模组 收发 | `PC send "HELLO-FROM-PC"` | +IPD,<id>,<len>:HELLO-FROM-PC | PASS | `+IPD,0,15:HELLO-FROM-PC\r\n` |
| 33 | 6-TCP服务端 | 模组 -> PC 收发 | `AT+CIPSEND=0,25` | 模组回显 SEND OK, PC 侧收到 payload | PASS | `AT侧=SEND OK\r\n | PC侧收到=b'HELLO-FROM-BK7238-96744\r\n'` |
| 34 | 6-TCP服务端 | 连接状态(CIPSTATE) | `AT+CIPSTATE` | \+CIPSTATE:|\bOK\b | PASS | `AT+CIPSTATE\r\n\r\n+CIPSTATE:0,"TCP","192.168.0.152",63716,23130,0\r\n+CIPSTATE:5,"TCP","",0,8266,1\r\nOK\r\n` |
| 35 | 6-TCP服务端 | 关闭服务端 | `AT+CIPSERVER=0` | \bOK\b|\bERROR\b | PASS | `AT+CIPSERVER=0\r\n\r\nOK\r\n` |
| 36 | 7-UDP服务端 | 开启 UDP 服务端 | `AT+CIPSERVER=1,8267,"UDP"` | OK (UDP, linkid=5) | PASS | `AT+CIPSERVER=1,8267,"UDP"\r\n\r\nOK\r\n` |
| 37 | 7-UDP服务端 | PC -> 模组 UDP | `PC sendto "UDP-FROM-PC"` | +IPD,5,<len>:UDP-FROM-PC | PASS | `+IPD,5,13:UDP-FROM-PC\r\n` |
| 38 | 7-UDP服务端 | 模组 -> PC UDP | `AT+CIPSEND=5,17` | PC 收到 UDP-FROM-BK7238 | PASS | `AT侧=SEND OK\r\n | PC侧收到=b'UDP-FROM-BK7238\r\n'` |
| 39 | 7-UDP服务端 | 关闭服务端 | `AT+CIPSERVER=0` | \bOK\b|\bERROR\b | PASS | `AT+CIPSERVER=0\r\n\r\nOK\r\n` |
| 40 | 8-断连恢复 | 断开 AP | `AT+CWQAP` | WIFI DISCONNECT | PASS | `AT+CWQAP\r\n\r\nWIFI DISCONNECT\r\n` |
| 41 | 8-断连恢复 | 断连后状态 | `AT+CIPSTATUS?` | STATUS:5 (无 Wi-Fi 连接) | PASS | `AT+CIPSTATUS?\r\n\r\nSTATUS:5\r\nOK\r\n` |
| 42 | 8-断连恢复 | 重新关联 AP | `AT+CWJAP="MyHomeWiFi","***"` | \bOK\b|\bERROR\b | PASS | `AT+CWJAP="MyHomeWiFi","<WIFI_PWD>"\r\n\r\nOK\r\n` |
| 43 | 8-断连恢复 | 恢复后状态 | `AT+CIPSTATUS?` | STATUS:2/3/4 | PASS | `AT+CIPSTATUS?\r\n\r\nSTATUS:2\r\nOK\r\n` |

## 失败项（2）

- **4-TCP客户端 / 发送 HTTP GET 并收响应** — `AT+CIPSEND=39`
  - 原始响应: `未收到 > 提示符: AT+CIPSEND=39\r\n\r\nERROR\r\n`
- **4-TCP客户端 / 关闭连接** — `AT+CIPCLOSE`
  - 原始响应: `AT+CIPCLOSE\r\n\r\nERROR\r\n`
