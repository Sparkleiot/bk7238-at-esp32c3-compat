# BK7238 (ESP-AT 兼容) HTTP / MQTT 联网实测报告

- 时间: 2026-09-25 17:49:25
- 固件: at-esp32c3-compat_2M.1220.bin
- 目标 AP: `MyHomeWiFi`   MQTT broker: `broker.emqx.io:1883`
- 串口: COM7   (单模组纯 STA, 走公网)

## 本轮固件修复项 (HTTP 部分)

| 文件 | 问题 | 修复 |
|------|------|------|
| `atsvr_http_cmd.c` `http_output_size()` | 把文档占位符的尖括号原样写进格式串, 输出 `+HTTPCLIENT:<29506>,<...>`; 上位机按 ESP-AT 解析匹配不到 | 改正为 `+HTTPCLIENT:%d,` / `+HTTPGETSIZE:%d\r\n` |
| `atsvr_http_cmd.c` `http_output_data()` | 每调用一次就追加收尾 `\r\n`; 而 `HTTP_SIZE=1024` 使大响应被 recv 成 ~29 个分片, 每个分片都调一次 → 正文中间混进 30 个裸 CRLF | 去掉函数内的 `\r\n`, 改由调用方在整条响应输出完后补一次 |
| `atsvr_http_cmd.c` HTTPS 分支 | 正文偏移用 `ssl_parse_data_start_position()+2`, 多吃 2 字节(实测响应头变成 `TP/1.1 200 OK`, 丢了 `HT`); 且成功路径 `goto exit` 跳过收尾, HTTPS 请求从不回 `OK` | 改按 `strstr(\"\\r\\n\\r\\n\")+4` 定位正文; 补发 `http_output_ok()`; `<len>` 改报实际吐出的字节数 |
| `utils_httpc.c` `user_httpclient_recv_response()` | 只有整包(头+正文)一次 recv 到齐才输出, 否则每个分片都再打印一次 size → `AT+HTTPGETSIZE` 无限重复; 且首包附带的正文被丢弃(分片响应丢开头字节) | 重写为流式输出: size 只报一次, 按 `Content-Length` 严格截断, 正文收满即收工 |

## 已知缺口 / 限制

1. **`AT+CIPSTART="TLS"` 不可用**(本表第 15 项): 固件 `HAL_TLS_mbedtls.c` 强制 `MBEDTLS_SSL_VERIFY_REQUIRED`, 且固件没有任何 AT 证书/CA 配置命令(`AT+CIPSSLCONFIG` / `AT+CIPSSLCCONF` 等不存在), 无 CA 时握手必然失败。**但 `AT+HTTPCLIENT` 的 HTTPS 通道走另一套 `sl_tls.c`(`ssl_create()` 不设 authmode), 实测可用**; MQTT(scheme=1 TCP) 与 HTTP(明文) 同样不受影响。
2. **chunked 响应不脱块**: 目标站不返回 `Content-Length` 时(如 example.com), `size` 回落为预置缓冲长度, 响应体原样透传分块帧(`22f\r\n...\r\n0\r\n\r\n`)。ESP-AT 会先脱块再上报, 这里未实现。
3. **无 CA 校验**: HTTPS 通道不校验服务器证书(与 ESP-AT 的默认行为一致, 但生产环境需自行加固)。

| # | 阶段 | 测试项 | 命令 | 结果 | 实际 |
|---|------|--------|------|------|------|
| 1 | 0-基础 | 模组应答 | `AT` | PASS | OK |
| 2 | 0-基础 | 关闭透传模式(清残留) | `AT+CIPMODE=0` | PASS |  |
| 3 | 0-基础 | 设为纯 STA 模式 | `AT+CWMODE=1` | PASS | OK |
| 4 | 1-关联 | 关联真实 AP `MyHomeWiFi` 并取 IP | `AT+CWJAP` | PASS | 第 1 次尝试 / STAIP=192.168.0.175 |
| 5 | 1-关联 | 查询 STA IP/网关/DNS | `AT+CIPSTA?` | PASS | +CIPSTA:ip:"192.168.0.175"  +CIPSTA:gateway:"192.168.0.1"  +CIPSTA:netmask:"255.255.255.0"  OK |
| 6 | 2-DNS | 域名解析 www.baidu.com | `AT+CIPDOMAIN` | PASS | 183.2.172.177 |
| 7 | 2-DNS | 域名解析 broker.emqx.io | `AT+CIPDOMAIN` | PASS | 44.232.241.40 |
| 8 | 2-DNS | PING 解析出的公网 IP | `AT+PING="<baidu-ip>"` | PASS | +PING:24ms |
| 9 | 3-HTTP | HTTP GET www.baidu.com:80 | `AT+CIPSTART+CIPSEND` | PASS | 状态行 HTTP/1.1 200 / 响应 30123B / 正文 有 |
| 10 | 3-HTTP | HTTP GET example.com:80 | `AT+CIPSTART+CIPSEND` | PASS | 状态行 HTTP/1.1 200 / 响应 901B |
| 11 | 3b-HTTP CLI | HTTPCLIENT 明文 GET www.baidu.com | `AT+HTTPCLIENT=2,0,...,1` | PASS | size=29506 正文字节=29506 收尾=OK size==正文=✔ 正文杂散CR=0 头部无尖括号=✔ 首24=b'<!DOCTYPE html>\n<html>\n<' |
| 12 | 3b-HTTP CLI | HTTPCLIENT 明文 GET example.com | `AT+HTTPCLIENT=2,0,...,1` | PASS | size=1024 正文字节=571 收尾=OK (该站响应为 chunked 无 Content-Length, size 回落为预置缓冲长度, 分块帧原样透传) 首24=b'22f\r\n<!doctype html><htm' |
| 13 | 3b-HTTP CLI | HTTPCLIENT HTTPS GET www.baidu.com:443 | `AT+HTTPCLIENT=2,0,...,1,2` | PASS | size=29506 正文字节=29506 收尾=OK size==正文=✔ 首24=b'<!DOCTYPE html>\n<html>\n<' |
| 14 | 3b-HTTP CLI | HTTPGETSIZE 只上报一次且以 OK 收尾 | `AT+HTTPGETSIZE="..."` | PASS | 上报次数=1 size=29506 尾部=b'+HTTPGETSIZE:29506\r\nOK' |
| 15 | 4-TLS | TLS 建连 www.baidu.com:443 | `AT+CIPSTART="TLS"` | FAIL | ERROR |
| 16 | 5-MQTT | MQTT 用户配置(scheme=1 应为 TCP) | `AT+MQTTUSERCFG` | PASS | OK |
| 17 | 5-MQTT | 连接 broker broker.emqx.io:1883 | `AT+MQTTCONN` | PASS | +MQTTCONN:OK / 收到: 18B |
| 18 | 5-MQTT | 查询 MQTT 连接状态 | `AT+MQTTCONN?` | PASS | +MQTTCONN:0,1,"TCP","",0,"0",0  OK |
| 19 | 5-MQTT | 订阅 bk7238/at/test | `AT+MQTTSUB` | PASS | OK |
| 20 | 5-MQTT | 发布到已订阅主题(QoS1) | `AT+MQTTPUB` | PASS | +MQTTPUB:OK |
| 21 | 5-MQTT | 订阅自收 (上报 +MQTTSUBRECV) | `+MQTTSUBRECV` | PASS | +MQTTSUBRECV:0,"bk7238/at/test",17,hello-from-bk7238 |
| 22 | 5-MQTT | 取消订阅 | `AT+MQTTUNSUB` | PASS | OK |
| 23 | 5-MQTT | 断开 MQTT 连接 | `AT+MQTTCLEAN` | PASS | OK |
| 24 | 5-MQTT | 断连后 AT+MQTTCONN? 返回 ERROR | `AT+MQTTCONN?` | PASS | ERROR |
| 25 | 6-收尾 | 关闭残留 TCP 连接 | `AT+CIPCLOSE` | PASS |  |

**合计: 24 PASS / 1 FAIL**
