# BK7238 ESP-AT 兼容固件 — 功能测试（写入/回读）

- 端口: COM6 @ 115200
- 结果: **16/16 PASS** (100.0%)

| # | 验证点 | 回读命令 | 期望 | 结果 | 实际响应 |
|---|--------|----------|------|------|----------|
| 1 | STA 模式写入回读 | `AT+CWMODE?` | `\+CWMODE:1\b` | PASS | `AT+CWMODE?  +CWMODE:1 OK ` |
| 2 | SoftAP 模式写入回读 | `AT+CWMODE?` | `\+CWMODE:2\b` | PASS | `AT+CWMODE?  +CWMODE:2 OK ` |
| 3 | _CUR 别名前缀跟随 | `AT+CWMODE_CUR?` | `\+CWMODE_CUR:1\b` | PASS | `AT+CWMODE_CUR?  +CWMODE_CUR:1 OK ` |
| 4 | _DEF 别名前缀跟随 | `AT+CWMODE_DEF?` | `\+CWMODE_DEF:3\b` | PASS | `AT+CWMODE_DEF?  +CWMODE_DEF:3 OK ` |
| 5 | 自动连接开关 | `AT+CWAUTOCONN?` | `\+CWAUTOCONN:1\b` | PASS | `AT+CWAUTOCONN?  +CWAUTOCONN:1 OK ` |
| 6 | 多连接模式 | `AT+CIPMUX?` | `\+CIPMUX:1\b` | PASS | `AT+CIPMUX?  +CIPMUX:1 OK ` |
| 7 | 接收信息附加开关 | `AT+CIPDINFO?` | `\+CIPDINFO:1\b` | PASS | `AT+CIPDINFO?  +CIPDINFO:1 OK ` |
| 8 | 旧名 CIPRECVMODE 写入 | `AT+CIPRECVMODE?` | `\+CIPRECVMODE:1\b` | PASS | `AT+CIPRECVMODE?  +CIPRECVMODE:1 OK ` |
| 9 | CIPRECVMODE/TYPE 共享状态 | `AT+CIPRECVTYPE?` | `\+CIPRECVTYPE:1\b` | PASS | `AT+CIPRECVTYPE?  +CIPRECVTYPE:1 OK ` |
| 10 | 系统提示开关 | `AT+SYSMSG?` | `\+SYSMSG:1\b` | PASS | `AT+SYSMSG?  +SYSMSG:1 OK ` |
| 11 | 睡眠模式 | `AT+SLEEP?` | `\+SLEEP:0\b` | PASS | `AT+SLEEP?  +SLEEP:0 OK ` |
| 12 | DHCP 使能(STA+AP) | `AT+CWDHCP?` | `\+CWDHCP:3\b` | PASS | `AT+CWDHCP?  +CWDHCP:3 OK ` |
| 13 | 国家码/信道范围 | `AT+CWCOUNTRY?` | `\+CWCOUNTRY:CN,1,13,1` | PASS | `AT+CWCOUNTRY?  +CWCOUNTRY:CN,1,13,1 OK ` |
| 14 | CWJAP_CUR 别名探活 | `AT+CWJAP_CUR?` | `No AP|\+CWJAP_CUR:` | PASS | `AT+CWJAP_CUR?  No AP OK ` |
| 15 | STATUS 语义(离线=5/在线=2或3) | `AT+CIPSTATUS?` | `STATUS:[0-5]\b` | PASS | `AT+CIPSTATUS?  STATUS:5 OK ` |
| 16 | 新版连接信息命令 | `AT+CIPSTATE` | `\bOK\b` | PASS | `AT+CIPSTATE  OK ` |
