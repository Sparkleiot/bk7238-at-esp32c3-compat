# ESP32-C3 (ESP-AT) 兼容性差距分析 —— BK7238 / XH-WB3S

测试工具：`tools/at_compat_test.py`（54 条命令，逐条比对 ESP-AT 官方应答格式）
基线固件：模组出厂/现有固件 `BK7238-AT-1.0.14.bin`（`AT+GMR` → `ATVER:1.2.02`，`SDKVER:3.0.70`）
基线结果：**29 / 54 PASS（53.7%）**
原始报告：`test/compat_before.md`，原始收发字节：`test/raw/`

---

## 一、三类问题

### A. 应答前缀被改名（最致命 —— 上位机解析直接失败）

| 命令 | 现有响应 | ESP-AT 应为 |
|------|----------|-------------|
| `AT+CWMODE?` | `+WLMODE:3,1` | `+CWMODE:3` |
| `AT+CIPSTAMAC?` | `+WLMAC:c8:47:8c:11:22:33` | `+CIPSTAMAC:"c8:47:8c:11:22:33"` |
| `AT+CIPSTATUS?` | `+BIPSTATUS:ALL disconnect` | `STATUS:<stat>` + `+CIPSTATUS:<type>,"<ip>",<port>,...` |
| `AT+CIPAP?` | `CMDRSP:+CIPAP:192.168.4.1,255.255.255.0,192.168.4.1` | `+CIPAP:ip:"192.168.4.1"` … （无 `CMDRSP:` 前缀，值需带引号、分行） |
| `AT+MQTTCONN?` | `+MQTTCONNSTATE:disconnect,...` | `+MQTTCONN:<link_id>,<state>,...` |

> 这类问题**不会返回 ERROR**，但上位机按 ESP-AT 解析会拿不到数据，属于「静默不兼容」，
> 比直接报错更隐蔽，必须优先修。

### B. 完全缺失的命令（返回 ERROR）

基础类：`AT+SYSRAM?`、`AT+SYSMSG?`、`AT+UART_CUR?`、`AT+UART_DEF?`、`AT+SLEEP`
Wi-Fi 类：`AT+CWMODE_CUR?`、`AT+CWMODE_DEF?`、`AT+CWAUTOCONN?`、`AT+CWDHCP_CUR?`、
`AT+CWDHCP_DEF?`、`AT+CIPSTA_CUR?`、`AT+CIPSTA_DEF?`、`AT+CIPSTAMAC_CUR?`、
`AT+CIPSTAMAC_DEF?`、`AT+CWCOUNTRY?`
TCP/IP 类：`AT+CIPMODE?`、`AT+CIPDINFO?`、`AT+CIPRECVTYPE?`、`AT+CIPSTATUS`、
`AT+CIPSERVER?`、`AT+CIPTCPOPT?`

### C. 格式/内容不符

| 命令 | 问题 |
|------|------|
| `AT+CWJAP?` | 只回 `OK`，应为未连接时回 `No AP` + `OK`；已连接时回 `+CWJAP:"ssid","mac",<ch>,<rssi>` |
| `AT+CIPSTA?` | 值没有引号：`+CIPSTA:ip:0.0.0.0` → 应为 `+CIPSTA:ip:"0.0.0.0"`；且缺 `gateway`/`netmask` 之外的 `+CIPSTA:` 行格式一致性 |
| `AT+PING="127.0.0.1"` | 回的是原始 ICMP 行 `60 bytes from ...`，ESP-AT 应为 `+PING:<time>` 或 `+PING:TIMEOUT`（失败） |
| `AT+CIPDOMAIN="example.com"` | 无任何响应（连 OK/ERROR 都没有）→ 超时，需修 |

---

## 二、已经兼容的部分（不需要动）

- 基础：`AT`、`AT+GMR`、`AT+SYSTIMESTAMP?`、`AT+SYSSTORE?`
- Wi-Fi：`AT+CWJAP`、`AT+CWLAP`、`AT+CWDHCP?`、`AT+CWLIF`、`AT+CWSAP` 的**命令形式**
- TCP/IP：`AT+CIFSR`、`AT+CIPMUX?`、`AT+CIPSNTPCFG?`、`AT+CIPSNTPTIME?`
- BLE：`AT+BLEINIT?`、`AT+BLENAME?`、`AT+BLEADDR?`、`AT+BLEADVPARAM?`、`AT+BLESCANPARAM?`（BLE 子系统已相当完整，含 GATTS/GATTC/HID/SPP）
- MQTT / HTTP：命令名已注册（`MQTTUSERCFG`/`MQTTCONN`/`MQTTSUB`/`MQTTPUB`/`MQTTUNSUB`/`MQTTCLEAN`、`HTTPCLIENT`/`HTTPGETSIZE`/`HTTPURLCFG`）

> 从固件字符串表可见，现有 AT 层**已经实现了绝大部分 ESP-AT 命令名**，
> 主要工作量在 **应答格式对齐 + 补齐缺失命令 + 加入 `_CUR`/`_DEF` 别名**，而不是从零实现协议栈。

---

## 三、修复方案（优先级从高到低）

1. **改用 ESP-AT 应答前缀**：`+WLMODE`→`+CWMODE`、`+WLMAC`→`+CIPSTAMAC`、
   `+BIPSTATUS`→`STATUS:` 体系、去掉 `CMDRSP:` 前缀、`+MQTTCONNSTATE`→`+MQTTCONN`。
2. **补 `_CUR` / `_DEF` 别名**：`CWMODE`、`CWDHCP`、`CIPSTA`、`CIPSTAMAC`、`CIPAP`、`CIPSTAMAC`。
3. **补缺失命令**：`SYSRAM`、`SYSMSG`、`UART_CUR`、`UART_DEF`、`SLEEP`、`CWAUTOCONN`、
   `CWCOUNTRY`、`CIPMODE`、`CIPDINFO`、`CIPRECVTYPE`、`CIPSTATUS`、`CIPSERVER`、`CIPTCPOPT`。
4. **修正 `AT+PING` / `AT+CIPDOMAIN` 输出格式**。
5. **统一 `AT+GMR` 输出**为 ESP-AT 的 `AT version:` / `SDK version:` / `compile time:` 三段式。

## 四、验证方法

```bash
# 烧录前（当前固件）
python tools/at_compat_test.py COM3 --out test/compat_before.md
# 烧录后（新固件）
python tools/at_compat_test.py COM3 --out test/compat_after.md
```
目标：`compat_after.md` 中 PASS 率 ≥ 90%（受限于 BK7238 无以太网、无 IPv6 等硬件差异，
少数 ESP32-C3 专有命令可标注为「硬件不支持，明确回 ERROR」）。
