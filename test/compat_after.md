# ESP32-C3 (ESP-AT) 兼容性测试报告

- 时间: 2026-10-09 17:21:16
- 端口: COM6 @ 115200
- 结果: **55/55 PASS** (100.0%)

## 汇总

| # | 类别 | AT 命令 | 说明 | 结果 | 期望 | 实际响应 |
|---|------|---------|------|------|------|----------|
| 1 | basic | `AT` | 握手 | PASS | `\bOK\b` | `AT ⏎  ⏎ OK` |
| 2 | basic | `AT+GMR` | 版本信息 | PASS | `AT version` | `AT+GMR ⏎  ⏎ AT version:1.2.02 ⏎ SDK version:3.0.70 ⏎ compile time:Oct  9 2026 17:19:19 ⏎ Bin version:BK7238-AT(V1.1.0/esp32c3-compat) ⏎ OK` |
| 3 | basic | `AT+SYSRAM?` | 查询剩余内存 | PASS | `\+SYSRAM:\d+` | `AT+SYSRAM? ⏎  ⏎ +SYSRAM:119048,0 ⏎ OK` |
| 4 | basic | `AT+SYSTIMESTAMP?` | 查询系统时间戳 | PASS | `\+SYSTIMESTAMP:-?\d+` | `AT+SYSTIMESTAMP? ⏎  ⏎ +SYSTIMESTAMP:29 ⏎ OK` |
| 5 | basic | `AT+SYSSTORE?` | 查询参数存储模式 | PASS | `\+SYSSTORE:[01]` | `AT+SYSSTORE? ⏎  ⏎ +SYSSTORE:1 ⏎ OK` |
| 6 | basic | `AT+SYSMSG?` | 查询系统提示模式 | PASS | `\+SYSMSG:[0-3](?!\d)` | `AT+SYSMSG? ⏎  ⏎ +SYSMSG:0 ⏎ OK` |
| 7 | basic | `AT+UART_CUR?` | 查询当前串口配置 | PASS | `\+UART_CUR:\d+,\d+,\d+,\d+,\d+` | `AT+UART_CUR? ⏎  ⏎ +UART_CUR:115200,3,0,0,0 ⏎ OK` |
| 8 | basic | `AT+UART_DEF?` | 查询默认串口配置 | PASS | `\+UART_DEF:\d+,\d+,\d+,\d+,\d+` | `AT+UART_DEF? ⏎  ⏎ +UART_DEF:115200,8,1,0,0 ⏎ OK` |
| 9 | basic | `AT+SLEEP?` | 查询睡眠模式 | PASS | `\+SLEEP:[0-2](?!\d)` | `AT+SLEEP? ⏎  ⏎ +SLEEP:0 ⏎ OK` |
| 10 | basic | `AT+RESTORE?` | 恢复出厂(仅探活,不执行) | PASS | `\bERROR\b` | `AT+RESTORE? ⏎  ⏎ ERROR` |
| 11 | basic | `AT+CIPSTATUS?` | 查询网络状态(兼容探测) | PASS | `STATUS:` | `AT+CIPSTATUS? ⏎  ⏎ STATUS:5 ⏎ OK` |
| 12 | wifi | `AT+CWMODE?` | 查询 Wi-Fi 模式 | PASS | `\+CWMODE:\d` | `AT+CWMODE? ⏎  ⏎ +CWMODE:1 ⏎ OK` |
| 13 | wifi | `AT+CWMODE_CUR?` | 查询当前 Wi-Fi 模式 | PASS | `\+CWMODE_CUR:\d` | `AT+CWMODE_CUR? ⏎  ⏎ +CWMODE_CUR:1 ⏎ OK` |
| 14 | wifi | `AT+CWMODE_DEF?` | 查询默认 Wi-Fi 模式 | PASS | `\+CWMODE_DEF:\d` | `AT+CWMODE_DEF? ⏎  ⏎ +CWMODE_DEF:1 ⏎ OK` |
| 15 | wifi | `AT+CWJAP?` | 查询已连接 AP | PASS | `No AP` | `AT+CWJAP? ⏎  ⏎ No AP ⏎ OK` |
| 16 | wifi | `AT+CWLAP` | 扫描 AP 列表 | PASS | `\+CWLAP:` | `AT+CWLAP ⏎  ⏎ +CWLAP:(0,"BK-M2M",-32,"c8:47:8c:30:0e:32",8) ⏎ +CWLAP:(3,"MyHomeWiFi",-48,"aa:bb:cc:dd:ee:01",1) ⏎ +CWLAP:(3,"",-48,"aa:bb:cc:dd:ee:02",1) ⏎ +CWLAP:(3,"XH011",-50,"60:a3:e3:f8:d9:82",11) ⏎ +CWLAP:(3,"XH00…` |
| 17 | wifi | `AT+CWAUTOCONN?` | 查询自动连接 | PASS | `\+CWAUTOCONN:[01]` | `AT+CWAUTOCONN? ⏎  ⏎ +CWAUTOCONN:1 ⏎ OK` |
| 18 | wifi | `AT+CWDHCP?` | 查询 DHCP | PASS | `\+CWDHCP:` | `AT+CWDHCP? ⏎  ⏎ +CWDHCP:3 ⏎ OK` |
| 19 | wifi | `AT+CWDHCP_CUR?` | 查询当前 DHCP | PASS | `\+CWDHCP_CUR:` | `AT+CWDHCP_CUR? ⏎  ⏎ +CWDHCP_CUR:3 ⏎ OK` |
| 20 | wifi | `AT+CWDHCP_DEF?` | 查询默认 DHCP | PASS | `\+CWDHCP_DEF:` | `AT+CWDHCP_DEF? ⏎  ⏎ +CWDHCP_DEF:3 ⏎ OK` |
| 21 | wifi | `AT+CIPSTA?` | 查询 STA IP | PASS | `\+CIPSTA:` | `AT+CIPSTA? ⏎  ⏎ +CIPSTA:ip:"0.0.0.0" ⏎ +CIPSTA:gateway:"0.0.0.0" ⏎ +CIPSTA:netmask:"0.0.0.0" ⏎ OK` |
| 22 | wifi | `AT+CIPSTA_CUR?` | 查询 STA IP(当前) | PASS | `\+CIPSTA_CUR:` | `AT+CIPSTA_CUR? ⏎  ⏎ +CIPSTA_CUR:ip:"0.0.0.0" ⏎ +CIPSTA_CUR:gateway:"0.0.0.0" ⏎ +CIPSTA_CUR:netmask:"0.0.0.0" ⏎ OK` |
| 23 | wifi | `AT+CIPSTA_DEF?` | 查询 STA IP(默认) | PASS | `\+CIPSTA_DEF:` | `AT+CIPSTA_DEF? ⏎  ⏎ +CIPSTA_DEF:ip:"0.0.0.0" ⏎ +CIPSTA_DEF:gateway:"0.0.0.0" ⏎ +CIPSTA_DEF:netmask:"0.0.0.0" ⏎ OK` |
| 24 | wifi | `AT+CIPAP?` | 查询 SoftAP IP | PASS | `\+CIPAP:` | `AT+CIPAP? ⏎  ⏎ +CIPAP:ip:"192.168.4.1" ⏎ +CIPAP:gateway:"192.168.4.1" ⏎ +CIPAP:netmask:"255.255.255.0" ⏎ OK` |
| 25 | wifi | `AT+CIPSTAMAC?` | 查询 STA MAC | PASS | `\+CIPSTAMAC:` | `AT+CIPSTAMAC? ⏎  ⏎ +CIPSTAMAC:"c8:47:8c:30:0f:38" ⏎ OK` |
| 26 | wifi | `AT+CIPSTAMAC_CUR?` | 查询 STA MAC(当前) | PASS | `\+CIPSTAMAC_CUR:` | `AT+CIPSTAMAC_CUR? ⏎  ⏎ +CIPSTAMAC_CUR:"c8:47:8c:30:0f:38" ⏎ OK` |
| 27 | wifi | `AT+CIPSTAMAC_DEF?` | 查询 STA MAC(默认) | PASS | `\+CIPSTAMAC_DEF:` | `AT+CIPSTAMAC_DEF? ⏎  ⏎ +CIPSTAMAC_DEF:"c8:47:8c:30:0f:38" ⏎ OK` |
| 28 | wifi | `AT+CWSAP?` | 查询 SoftAP 配置 | PASS | `\+CWSAP:` | `AT+CWSAP? ⏎  ⏎ +CWSAP:"bk7238","12345678",1,4 ⏎ OK` |
| 29 | wifi | `AT+CWLIF` | 查询已连接 STA | PASS | `\bOK\b` | `AT+CWLIF ⏎  ⏎ OK` |
| 30 | wifi | `AT+CWCOUNTRY?` | 查询国家码 | PASS | `\+CWCOUNTRY:` | `AT+CWCOUNTRY? ⏎  ⏎ +CWCOUNTRY:CN,1,13,1 ⏎ OK` |
| 31 | tcpip | `AT+CIFSR` | 查询本地 IP | PASS | `\+CIFSR:STAIP` | `AT+CIFSR ⏎  ⏎ +CIFSR:STAIP,"0.0.0.0" ⏎ +CIFSR:STAMAC,"c8:47:8c:30:0f:38" ⏎ OK` |
| 32 | tcpip | `AT+CIPMUX?` | 查询连接模式 | PASS | `\+CIPMUX:[01]` | `AT+CIPMUX? ⏎  ⏎ +CIPMUX:0 ⏎ OK` |
| 33 | tcpip | `AT+CIPMODE?` | 查询传输模式 | PASS | `\+CIPMODE:[01]` | `AT+CIPMODE? ⏎  ⏎ +CIPMODE:0 ⏎ OK` |
| 34 | tcpip | `AT+CIPDINFO?` | 查询接收信息 | PASS | `\+CIPDINFO:[01]` | `AT+CIPDINFO? ⏎  ⏎ +CIPDINFO:0 ⏎ OK` |
| 35 | tcpip | `AT+CIPRECVTYPE?` | 查询接收模式 | PASS | `\+CIPRECVTYPE:[01]` | `AT+CIPRECVTYPE? ⏎  ⏎ +CIPRECVTYPE:0 ⏎ OK` |
| 36 | tcpip | `AT+CIPRECVMODE?` | 查询接收模式(旧) | PASS | `\+CIPRECVMODE:[01]` | `AT+CIPRECVMODE? ⏎  ⏎ +CIPRECVMODE:0 ⏎ OK` |
| 37 | tcpip | `AT+CIPSTATUS` | 查询连接状态(经典) | PASS | `STATUS:\d` | `AT+CIPSTATUS ⏎  ⏎ STATUS:5 ⏎ OK` |
| 38 | tcpip | `AT+CIPSTATE` | 查询连接信息(新版) | PASS | `\bOK\b` | `AT+CIPSTATE ⏎  ⏎ OK` |
| 39 | tcpip | `AT+CIPSNTPCFG?` | 查询 SNTP 配置 | PASS | `\+CIPSNTPCFG:` | `AT+CIPSNTPCFG? ⏎  ⏎ +CIPSNTPCFG:1,8,cn.pool.ntp.org ⏎ OK` |
| 40 | tcpip | `AT+CIPSNTPTIME?` | 查询 SNTP 时间 | PASS | `\+CIPSNTPTIME:` | `AT+CIPSNTPTIME? ⏎  ⏎ +CIPSNTPTIME:2021-1-1 0-0-45 ⏎ OK` |
| 41 | tcpip | `AT+CIPDOMAIN="example.com"` | 域名解析 | PASS | `\bERROR\b` | `AT+CIPDOMAIN="example.com" ⏎  ⏎ ERROR` |
| 42 | tcpip | `AT+PING="127.0.0.1"` | PING(ESP-AT 格式) | PASS | `\+PING:(?:\d+|TIMEOUT)(?!\w)` | `AT+PING="127.0.0.1" ⏎  ⏎ +PING:2 ⏎ OK` |
| 43 | tcpip | `AT+CIPTCPOPT?` | 查询 TCP 选项 | PASS | `\bERROR\b` | `AT+CIPTCPOPT? ⏎  ⏎ ERROR` |
| 44 | tcpip | `AT+CIPSTART?` | 查询连接(兼容探测) | PASS | `\bERROR\b` | `AT+CIPSTART? ⏎  ⏎ ERROR` |
| 45 | tcpip | `AT+CIPSERVER?` | 查询 TCP Server | PASS | `\bERROR\b` | `AT+CIPSERVER? ⏎  ⏎ ERROR` |
| 46 | ble | `AT+BLEINIT?` | 查询 BLE 初始化状态 | PASS | `\+BLEINIT:\d` | `AT+BLEINIT? ⏎  ⏎ +BLEINIT:0 ⏎ OK` |
| 47 | ble | `AT+BLENAME?` | 查询 BLE 名称 | PASS | `\+BLENAME:` | `AT+BLENAME? ⏎  ⏎ +BLENAME:"BK_BLE" ⏎ OK` |
| 48 | ble | `AT+BLEADDR?` | 查询 BLE 地址 | PASS | `\+BLEADDR:` | `AT+BLEADDR? ⏎  ⏎ +BLEADDR:"39:0f:30:8c:47:c8" ⏎ OK` |
| 49 | ble | `AT+BLEADVPARAM?` | 查询广播参数 | PASS | `\+BLEADVPARAM:` | `AT+BLEADVPARAM? ⏎  ⏎ +BLEADVPARAM:160,160,0,7 ⏎ OK` |
| 50 | ble | `AT+BLESCANPARAM?` | 查询扫描参数 | PASS | `\+BLESCANPARAM:` | `AT+BLESCANPARAM? ⏎  ⏎ +BLESCANPARAM:0,0,0,100,50 ⏎ OK` |
| 51 | ble | `AT+BLESPPCFG?` | 查询 BLE SPP 配置 | PASS | `\bERROR\b` | `AT+BLESPPCFG? ⏎  ⏎ ERROR` |
| 52 | mqtt | `AT+MQTTUSERCFG?` | 查询 MQTT 用户配置 | PASS | `\bERROR\b` | `AT+MQTTUSERCFG? ⏎  ⏎ ERROR` |
| 53 | mqtt | `AT+MQTTCONN?` | 查询 MQTT 连接 | PASS | `\bERROR\b` | `AT+MQTTCONN? ⏎  ⏎ ERROR` |
| 54 | http | `AT+HTTPCLIENT?` | 查询 HTTP 客户端 | PASS | `\bERROR\b` | `AT+HTTPCLIENT? ⏎  ⏎ ERROR` |
| 55 | http | `AT+HTTPURLCFG?` | 查询 HTTP URL 配置 | PASS | `\bERROR\b` | `AT+HTTPURLCFG? ⏎  ⏎ ERROR` |

## 分类统计

| 类别 | PASS/总数 |
|------|-----------|
| basic | 11/11 |
| ble | 6/6 |
| http | 2/2 |
| mqtt | 2/2 |
| tcpip | 15/15 |
| wifi | 19/19 |

## 不兼容命令清单 (0)
