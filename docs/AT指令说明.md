# AT 指令说明（ESP-AT 兼容版）

> 适用固件：`firmware/at-esp32c3-compat_2M.1220.bin`
> 版本标识：`Bin version:BK7238-AT(V1.1.0/esp32c3-compat)`
> 串口：**115200 8N1**，命令以 `\r\n` 结尾，每条命令返回 `OK` 或 `ERROR`
>
> **本固件由 AI 自主移植**，命令名、参数语义、应答格式对齐 **ESP32-C3 ESP-AT**。
> 绝大多数上位机代码把主控从 ESP32-C3 换成 XH-WB3S 后**不用改一行**。

---

## 0. 五分钟上手（照抄即可）

```text
AT                                    # 握手，应答 OK
AT+GMR                                # 查固件版本
AT+CWMODE=1                           # 1=STA 模式（连路由器）
AT+CWDHCPS?                            # 查 DHCP 地址池
AT+CWJAP="你的SSID","你的密码"          # 连 WiFi（异步！）
AT+CIPSTA?                            # 查拿到的 IP
```

**连上WiFi 后最常用的几条：**

```text
AT+CIPSTART="TCP","www.baidu.com",80 # 建 TCP 连接（支持域名）
AT+CIPSEND=10,"sparkleiot"          # 发 10 字节
AT+CIPSEND                            # 裸发（数据通道）
AT+CIPDOMAIN="example.com"           # 域名解析
AT+PING="8.8.8.8"                    # 测试连通
AT+CIPSTATUS                         # 查连接状态
AT+CIPCLOSE=5                         # 断开
```

### ⚠ 三个必须知道的时序

| 事项 | 表现 | 应对 |
|------|------|------|
| `AT+CWJAP` 是**异步**命令 | 立即回 `OK`，2–3s 后才异步给 `WIFI CONNECTED` / `WIFI GOT IP` | **等事件**，别轮询 `OK` 后立刻查 IP |
| `AT+CWLAP` 射频扫描慢 | 耗时 **4–9 秒** | 上位机读超时设 ≥15s |
| 接收数据带 `+IPD` 前缀 | `+IPD,<len>:`（单连接）/ `+IPD,<id>,<len>:`（多连接） | 按 ESP-AT 规则分帧，不要按裸数据解析 |

---

## 1. 基础命令

| 命令 | 说明 | 应答示例 |
|------|------|----------|
| `AT` | 握手测试 | `OK` |
| `ATE0` / `ATE1` | 关 / 开回显 | `OK` |
| `AT+GMR` | 版本信息 | `AT version:1.2.02` / `SDK version:3.0.70` / `Bin version:BK7238-AT(V1.1.0/esp32c3-compat)` |
| `AT+RST` | 重启 | `OK`（约 2s 后应答恢复，5s 完全可用） |
| `AT+SYSRAM?` | 剩余内存 | `+SYSRAM:116280,0` |
| `AT+SYSTIMESTAMP?` | 系统时间戳 | `+SYSTIMESTAMP:1790325505` |
| `AT+SYSSTORE?` | 参数存储模式 | `+SYSSTORE:1` |
| `AT+SYSMSG?` | 系统提示模式 | `+SYSMSG:0` |
| `AT+SLEEP?` | 睡眠模式 | `+SLEEP:0` |
| `AT+UART_CUR?` | 当前串口配置 | `+UART_CUR:115200,3,0,0,0` |
| `AT+UART_DEF?` | 默认串口配置 | `+UART_DEF:115200,8,1,0,0` |
| `AT+CIPSTATUS` | 网络状态 | `STATUS:2` |
| `AT+RESTORE` | 恢复出厂设置 | `ERROR`（本固件不支持，勿用） |

> ⚠ `AT+SLEEP` / `AT+SYSMSG` / `AT+CIPDINFO` / `AT+CIPRECVTYPE` 是**运行时开关**，
> 存在 RAM 里**掉电不保持** —— 这与 ESP-AT 的 `_CUR` 语义一致，符合预期。

---

## 2. Wi-Fi 命令

### 2.1 模式与连接

| 命令 | 说明 | 应答示例 |
|------|------|----------|
| `AT+CWMODE?` | 查询模式（1=STA / 2=AP / 3=AP+STA） | `+CWMODE:1` |
| `AT+CWMODE=<n>` | 设置模式 | `OK` |
| `AT+CWMODE_CUR?` / `_DEF?` | 当前 / 默认模式 | `+CWMODE_CUR:1` |
| `AT+CWJAP="ssid","pwd"` | **连接 AP（异步）** | `OK` → 后续 `WIFI CONNECTED` / `WIFI GOT IP` |
| `AT+CWJAP?` | 查询已连接 AP | `+CWJAP:"MyHomeWiFi","aa:bb:cc:dd:ee:01",1,-47,0,0,0,0,0` |
| `AT+CWLAP` | 扫描 AP（**耗时 4–9s**） | `+CWLAP:(3,"SSID",-46,"BSSID",11)` |
| `AT+CWCOUNTRY?` | 国家码 | `+CWCOUNTRY:CN,1,13,1` |
| `AT+CWAUTOCONN?` | 自动连接开关 | `+CWAUTOCONN:0` |

> `AT+CWLAP` 返回字段：`(加密方式,SSID,RSSI,BSSID,信道)`。
> 加密方式：`0`=OPEN，`1`=WEP，`2`=WPA-PSK，`3`=WPA2-PSK，`4`=WPA/WPA2-PSK，
> `5`=WPA2-Enterprise，`6`=WPA3，`7`=WPA2+WPA3。

### 2.2 SoftAP（模组做热点）

| 命令 | 说明 |
|------|------|
| `AT+CWSAP="ssid","pwd",ch,ecn` | 配置热点。`ecn`：`0`=OPEN / `1`=WEP / `2`=WPA-PSK / `3`=WPA2-PSK / `4`=WPA2-PSK(同时支持 WPA) |
| `AT+CWSAP?` | 查询配置 |
| `AT+CIPAP?` | 查询热点 IP（默认 `192.168.4.1`） |
| `AT+CWDHCPS?` | 查询 DHCP 地址池（默认 `.2`~`.101`） |
| `AT+CWLIF` | 查询已连接的 STA 列表 |

> ⚠ **本固件的 WPA2 SoftAP（`ecn=2/3/4`）无法完成握手** —— 这是厂商预编译 hostapd
> 库的行为，改不了。**做热点请用 `ecn=0`（开放）**：`AT+CWSAP="名字",,8,0`。
>
> 另：上电后热点约需 **5.5s** 才开始广播（要等 RF 校准收敛），属正常。

### 2.3 网络信息

| 命令 | 说明 | 应答示例 |
|------|------|----------|
| `AT+CIFSR` | 本地 IP + MAC | `+CIFSR:STAIP,"192.168.0.163"` / `+CIFSR:STAMAC,"c8:47:8c:11:22:33"` |
| `AT+CIPSTA?` | STA 网络信息 | `+CIPSTA:ip:"..."` / `gateway:"..."` / `netmask:"..."` |
| `AT+CIPSTA_CUR?` / `_DEF?` | 同上，当前 / 默认 | |
| `AT+CIPSTAMAC?` | STA MAC | `+CIPSTAMAC:"c8:47:8c:11:22:33"` |
| `AT+CIPSTAMAC_CUR?` / `_DEF?` | 同上 | |
| `AT+CWDHCP?` | DHCP 设置 | `+CWDHCP:3` |
| `AT+CWDHCP_CUR?` / `_DEF?` | 同上 | |

---

## 3. TCP/IP 命令

### 3.1 连接管理

| 命令 | 说明 |
|------|------|
| `AT+CIPMUX=[0/1]` | 多连接模式。`0`=单连接（`AT+CIPSTART="TCP",...`）/ `1`=多连接（带 linkid） |
| `AT+CIPMUX?` | 查询 |
| `AT+CIPMODE=[0/1]` | 传输模式。`0`=普通 / `1`=透传（**透传后不再解析任何 AT 命令**） |
| `AT+CIPMODE?` | 查询 |
| `AT+CIPSTATUS` | 连接状态 |
| `AT+CIPSTATE` | 连接信息（新版） |
| `AT+CIPDINFO?` | 是否回显接收数据 |
| `AT+CIPRECVTYPE?` / `AT+CIPRECVMODE?` | 接收模式 |

> ⚠ **透传模式（`AT+CIPMODE=1`）是"不可逆"的**：一旦用 `AT+CIPSEND`（无参数）进入透传，
> 模组**不再解析任何 AT 命令**，连回显都没有。退出方式：发 `+++`（前后各留约 1s 静默）。
> 调试时若"只有某个端口全灭、别的正常"，八成是卡在透传态了。

### 3.2 建立连接

| 命令 | 说明 |
|------|------|
| `AT+CIPSTART="TCP","host",port` | 单连接模式建连 |
| `AT+CIPSTART=<linkid>,"TCP","host",port` | 多连接模式建连 |
| `AT+CIPSTART="UDP","host",port[,localport]` | UDP（最后参数是本地绑定端口，可省） |
| `AT+CIPSTART="TLS"/"SSL","host",port` | TLS 连接（见 §6） |
| `AT+CIPSNTPCFG=<enable>,<interval>,<server>` | 配置 SNTP |
| `AT+CIPSNTPTIME?` | 查询 SNTP 时间 |

**`host` 可以是域名**（内部走 DNS），也可以是 IP。

成功应答：立刻 `OK`，随后异步给 `CONNECT`；失败给 `ERROR`。

### 3.3 收发数据

| 命令 | 说明 |
|------|------|
| `AT+CIPSEND=<len>` | 指定长度发送，随后发 `<len>` 字节原始数据。成功回 `SEND OK` |
| `AT+CIPSEND=<len>,"data"` | 不带 linkid，单连接简写 |
| `AT+CIPSEND=<linkid>,<len>` | 多连接模式 |
| `AT+CIPSEND=<linkid>,<len>,"data"` | 多连接 + 带数据 |
| `AT+CIPSEND` | 进入透传，**之后所有串口数据都是网络数据** |

**接收**：模组以 `+IPD` 前缀上报收到的数据
- 单连接：`+IPD,<len>:<data>`
- 多连接：`+IPD,<linkid>,<len>:<data>`

### 3.4 服务端与关闭

| 命令 | 说明 |
|------|------|
| `AT+CIPSERVER=<0/1>[,<port>[,"TCP"/"UDP"]]` | 开关 TCP/UDP 服务端。`0`=关闭（**已修复：原厂关不掉**） |
| `AT+CIPCLOSE=<linkid>` 或 `AT+CIPCLOSE` | 关闭连接 |

> ⚠ `AT+CIPCLOSE` 后资源释放有约 1 秒时延（已修：原厂更久且会导致紧随的
> `AT+CIPSTART` 误报 `linkid error`）。若偶发 `ERROR`，重试一次即可。

### 3.5 其它

| 命令 | 说明 | 应答示例 |
|------|------|----------|
| `AT+PING="host"` | 测试连通 | `+PING:12` / `+PING:TIMEOUT` |
| `AT+CIPDOMAIN="host"` | 域名解析 | `+CIPDOMAIN:"172.66.147.243"` |
| `AT+CIPTCPOPT?` | TCP 选项（本固件不支持） | `ERROR` |

> ⚠ **写 PING 断言前，先确认对端会回 ICMP**。例如路由器网关常配置为不回 ICMP，
> 此时 `+PING:TIMEOUT` 是**正常行为不是固件故障**。测连通性请用 `8.8.8.8` 做基准。

---

## 4. HTTP 命令

| 命令 | 说明 |
|------|------|
| `AT+HTTPCLIENT=<method>,<url>[,<header>[,<body>]]` | 发 HTTP 请求。`method`：`GET`/`POST`/`PUT`/`DELETE`/`HEAD`/`OPTIONS`；URL 须以 `http://` 或 `https://` 开头 |
| `AT+HTTPURLCFG=<url>` | 单独设置 URL |
| `AT+HTTPGETSIZE` | 获取响应正文长度 |
| `AT+HTTPCLIENT?` / `AT+HTTPURLCFG?` | 查询（**本固件不支持**，回 `ERROR`） |

```text
AT+HTTPCLIENT=GET,"http://www.example.com"
```

> ⚠ **已知限制：chunked 响应不脱块**（`utils_httpc.c` 不做分块解析）。
> 无 `Content-Length` 时长度会回落到预置缓冲大小，分块帧原样透传。
> 建议服务端返回带 `Content-Length` 的响应。

---

## 5. MQTT 命令

| 命令 | 说明 |
|------|------|
| `AT+MQTTUSERCFG=<linkid>,<scheme>,<client_id>[,<username>,<password>]` | 配置客户端。`scheme`：`0`=TCP / `1`=TLS |
| `AT+MQTTCONN=<linkid>,<host>,<port>[,<reconnect>]` | 建立连接 |
| `AT+MQTTPUB=<linkid>,<topic>,<qos>,<data>` | 发布 |
| `AT+MQTTSUB=<linkid>,<qos>,<topic>` | 订阅 |
| `AT+MQTTUNS=<linkid>,<topic>` | 退订 |
| `AT+MQTTCLEAN=<linkid>` | 清除会话 |
| `AT+MQTTCONN?` / `AT+MQTTUSERCFG?` | 查询（**本固件不支持**，回 `ERROR`） |

订阅收到消息时以 `+MQTTSUBRECV:<linkid>,"topic",<len>,<payload>` 上报。

> ⚠ `AT+MQTTCONN?` 只能保证"未连接时返回 `ERROR`"（ESP-AT 语义）。
> 连接成功后 host/port 以空串占位——**回读不到真实值**，这是原厂 MQTT 层的限制。

---

## 6. TLS 命令

| 命令 | 说明 |
|------|------|
| `AT+CIPSSLCCONF=<auth_mode>[,<pki_number>,<ca_number>]` | 配置 TLS 认证模式 |
| `AT+CIPSSLCCONF?` | 查询当前配置 |
| `AT+CIPSTART="TLS"/"SSL","host",port` | 建立 TLS 连接 |

**`auth_mode` 取值**：

| 值 | 含义 | 状态 |
|---|---|---|
| `0` | 不认证（**默认**） | ✅ 可用 |
| `1` | 服务器证书 + 私钥 | ⚠ 需 CA 才可用 |
| `2` | 服务器证书（单向） | ⚠ 需 CA 才可用 |
| `3` | 双向认证 | ⚠ 需 CA 才可用 |

> ⚠ **CA 证书无法在运行时装载**（与 ESP-AT 一致：CA 应在编译期烧进 flash 分区）。
> 因此 `auth_mode=1/2/3` 目前**配了也没有可用的 CA**，请用默认的 `auth_mode=0`。
>
> ⚠ **SDK 的 mbedtls 只报静态 RSA 套件、没有 ECDHE**（ClientHello 实测 9 个套件全是
> `TLS_RSA_WITH_AES_*`）。所以要求前向保密的站点会握手失败：
> `www.baidu.com:443` **通**，`www.qq.com` / `www.163.com` **失败**。

---

## 7. BLE 命令（查询类）

| 命令 | 应答示例 |
|------|----------|
| `AT+BLEINIT?` | `+BLEINIT:0` |
| `AT+BLENAME?` | `+BLENAME:"BK_BLE"` |
| `AT+BLEADDR?` | `+BLEADDR:"49:88:42:8c:47:c8"` |
| `AT+BLEADVPARAM?` | `+BLEADVPARAM:160,160,0,7` |
| `AT+BLESCANPARAM?` | `+BLESCANPARAM:0,0,0,100,50` |

---

## 8. ESP-AT → XH-WB3S 命令对照（原厂写法 → 本固件）

上位机代码若用的是 ESP-AT 写法，**不用改**；这里只列出原厂写法与 ESP-AT 的差异，
便于对照理解固件改动。

| 原厂写法 | ESP-AT / 本固件 |
|-----------|---------------|
| `+WLMODE:` | `+CWMODE:` |
| `+WLMAC:` | `+CIPSTAMAC:`（且带引号） |
| `+WSCAN:` | `+CWLAP:` |
| `+BIPSTATUS:...` | `STATUS:<stat>` + `+CIPSTATUS:` |
| `+MQTTCONNSTATE:...` | `+MQTTCONN:` / `ERROR` |
| `CMDRSP:` 前缀 | 无前缀（ESP-AT 没有） |
| `WFI DISCONNECTED` | `WIFI DISCONNECT`（原厂拼写错误，上位机匹配不上） |
| `xx bytes from ... ticks`（PING） | `+PING:<ms>` / `+PING:TIMEOUT` |
| 接收裸数据（无前缀） | `+IPD,<len>:` / `+IPD,<id>,<len>:` |

---

## 9. `_CUR` / `_DEF` 别名

ESP-AT 允许用后缀区分"当前生效值"与"掉电默认值"。本固件支持下列命令的
`_CUR?` 与 `_DEF?` 两种形式，应答前缀**跟随实际命令名**：

```text
AT+CWMODE_CUR?      ->  +CWMODE_CUR:1
AT+CWMODE_DEF?      ->  +CWMODE_DEF:1
AT+CIPSTA_CUR?      ->  +CIPSTA_CUR:ip:"..."
AT+CIPSTAMAC_CUR?   ->  +CIPSTAMAC_CUR:"..."
AT+CWDHCP_CUR?      ->  +CWDHCP_CUR:3
AT+CWJAP_CUR?       ->  +CWJAP_CUR:...
```

---

## 10. 已知限制汇总

| 限制 | 影响 | 说明 |
|------|------|------|
| mbedtls 无 ECDHE | `qq.com` / `163.com` 握手失败 | SDK 层裁剪，改 `.a` 需重编 mbedtls |
| CA 不能运行时装载 | `auth_mode=1/2/3` 暂不可用 | 与 ESP-AT 设计一致，CA 应编译期烧入 |
| chunked 响应不脱块 | HTTP 长响应可能不好解析 | 建议服务端返回 `Content-Length` |
| WPA2 SoftAP 握手失败 | `ecn=2/3/4` 建不了热点 | 厂商预编译 hostapd 所限，**请用 `ecn=0`** |
| `AT+MQTTCONN?` 读不到 host/port | — | 原厂 MQTT 层不持久化，ESP-AT 也同样受限 |
| `AT+SLEEP` 等掉电不保持 | — | 与 ESP-AT `_CUR` 语义一致，符合预期 |

---

## 11. 常见问题排查

| 现象 | 原因与解决 |
|------|-----------|
| 命令完全没回显 | 可能卡在透传态（`CIPMODE=1` +裸发过）。发 `+++` 退出，前 后各留 1s 静默 |
| 只有某个端口失联，别的正常 | 同上，八成是卡透传，不是固件坏 |
| `AT+CWJAP` 之后查不到 IP | 异步命令还没关联完。**等 `WIFI GOT IP` 事件**再查 |
| `AT+CWLAP` 超时 | 射频扫描要 4–9s，读超时设 ≥15s |
| `AT+PING` 全是 TIMEOUT | 先用 `8.8.8.8` 验证。目标不回 ICMP 就会 TIMEOUT，不是固件问题 |
| 上电后热点搜不到 | 正常，需等约 5.5s（RF 校准） |
| 连不上热点（设了密码） | 本固件 WPA2 握手有问题，请改用 `ecn=0` 开放热点 |
| `AT+CIPCLOSE` 后马上重连报 `linkid error` | 资源释放有约 1s 时延，重试一次 |
| HTTPS 握手失败 | 检查目标站点是否要求 ECDHE（本固件只支持静态 RSA） |

---

## 12. 相关文档

- 兼容性测试报告（55 条命令实测）：[`../test/compat_after.md`](../test/compat_after.md)
- 文档 v1.5 全量验收（71 项）：[`../test/doc_v15_report_tls_full2.md`](../test/doc_v15_report_tls_full2.md)
- TLS 能力报告：[`../test/tls_capability_report.md`](../test/tls_capability_report.md)
- 硬件要点（串口/供电/引脚）：[`WB3S硬件要点.md`](WB3S硬件要点.md)
- ESP-AT 官方文档：https://docs.espressif.com/projects/esp-at/zh_CN/latest/esp32c3/index.html