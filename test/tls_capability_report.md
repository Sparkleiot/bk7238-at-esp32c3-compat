# `AT+CIPSTART="TLS"` 能力缺口 —— 闭合报告

- 时间: 2026-10-08 14:10
- 被测: COM5 / COM6 / COM7（三模组统一刷同一版固件）
- 固件: `firmware/at-esp32c3-compat_2M.1220.bin`（`out/bk7238_2M.1220.bin`，2026-10-08 14:07 构建）
- 验证脚本: `tools/tls_probe.py`（功能）、`tools/tls_sniff.py`（抓 ClientHello）、`tools/tls_dbg2.py`（日志）
- 回归: `test/doc_v15_report_tls_full2.md` = **71 PASS / 0 FAIL / 2 N/A**（与改动前一致，零回归）
- 载荷说明: 报告中的收发负载原为第三方教程示例（域名 11 字节 / 公司名 36 字节），
  已替换为品牌标识 sparkleiot (10 字节) 与 SparkleIOT (10 字节)，
  CIPSEND 长度参数同步改为 10。替换不涉及 AT 解析与协议收发路径。

## 1. 结论

`AT+CIPSTART="TLS"` 从 **100% 失败** 变为 **可用**：握手成功、`AT+CIPSEND` 双向收发正常、
`+IPD` 正常上报。同时补齐 ESP-AT 的 `AT+CIPSSLCCONF[?]` 命令与经典 `"SSL"` 写法。

```
[PASS] AT+CIPSSLCCONF?              -> +CIPSSLCCONF:0,0,0
[PASS] AT+CIPSSLCCONF=2,0,0 / =0
[PASS] AT+CIPSTART="TLS"  CONNECT   TLSv1.2 AES256-SHA256
[PASS] CIPSEND 双向     服务端 recv 10B -> SEND OK -> +IPD,10:sparkleiot
[PASS] AT+CIPSTART="SSL" CONNECT   (ESP-AT 经典写法)
== 5 PASS / 0 FAIL ==
公网: www.baidu.com:443 -> CONNECT OK
```

## 2. 根因：4 个缺陷叠加

| # | 缺陷 | 后果 | 修法 |
|---|---|---|---|
| 1 | `HAL_TLS_mbedtls.c` 硬编码 `MBEDTLS_SSL_VERIFY_REQUIRED`，而 AT 层无装载 CA 的命令 | CA 链恒空，握手必败 | 按 ESP-AT `AT+CIPSSLCCONF` 的 auth_mode 选择；**0 = 不认证（ESP-AT 官方模式，也是默认）** |
| 2 | `network_app.c setup_msg_network()` 装配 `ssl_connect_params` 的代码**整段被注释** | 字段全零 | 在 TLS/DTLS 分支显式装配 auth_mode / timeout_ms=10s / ca=NULL / psk=NULL |
| 3 | 自动继承 env 里的全局 PSK（历史测试残留 64 个 hex 字符） | `mbedtls_ssl_conf_psk` 返回 `0x7100` **打死整个连接** | 刻意不自动继承（ESP-AT 也是按 link 显式配置）+ HAL 内加长度守卫 |
| 4 | `mbedtls_ssl_conf_own_cert` 被无条件调用，而证书上下文零初始化 | 直接报错 | 只在 auth_mode=1/3（真给了客户端证书）时调用 |

## 3. 顺带挖出两个被"永不超时"掩盖的老 bug

厂商把 `mbedtls_ssl_conf_read_timeout` 设成 `0`（= 阻塞），所以下面两个缺陷永远触发不到。
我加了 10s 超时兜底后立刻暴露：

| # | 缺陷 | 表象 | 修法 |
|---|---|---|---|
| 5 | `HAL_TLS_Read` 把 `mbedtls_ssl_read` 的 **0 当致命错误** → `ATSVR_ERR_SSL_READ` → `network_app.c:544` 判定"对端关闭" → 拆链路。但 0 在 mbedtls 里是**读超时/暂时无数据** | 空闲连接莫名 `0,CLOSED` | 改为 `break` 走 `ATSVR_ERR_SSL_NOTHING_TO_READ`；真正的对端关闭返回负值 CONN_EOF，仍走致命分支，不会漏判 |
| 6 | `HAL_TLS_Read` 要求 **`*read_len == totalLen`（读满缓冲）** 才返回 SUCCESS，而 TCP 侧 `hal_tcp_read_noblock` 是单次 recv、读到多少交多少 | 小包永远填不满 `REV_NETWORK_DATA_LEN` ⇒ 返回 `SSL_READ_TIMEOUT` ⇒ RX 线程只在 SUCCESS 时吐 `+IPD` ⇒ **数据被静默丢弃** | 改为 `*read_len > 0` 即成功交付 |

另外 `HAL_DTLS_mbedtls.c` 同类问题：0 会掉进 `default` 原样返回，而 `0 == ATSVR_RET_SUCCESS`
⇒ 会报一个 `read_len=0` 的假 `+IPD,0,`。已加 `case 0`。

## 4. ESP-AT 兼容补充

- **新命令 `AT+CIPSSLCCONF[?]`** — `=<auth_mode>[,<pki_number>,<ca_number>]`，语义对齐 ESP-AT
  （auth_mode：0 不认证 / 1 客户端证书 / 2 校验服务端 / 3 双向）。
  存函数级静态，**刻意不动 `ENV_PARAM` 布局**（flash env 向后兼容优先），复位回默认 0。
- **`"SSL"` 别名** — `AT+CIPSTART` 的类型串原来只认 `TLS`/`tls`/`DTLS`，现接受 ESP-AT 经典的 `"SSL"`/`"ssl"`。
- **`AT+CIPSEND` 补 TLS** — 类型白名单原来只放行 TCP/UDP，连上了也一个包都发不出去。
  `network_tcp_send_msg()` 内部是靠 `netwrite` 函数指针分发的，对 TLS 本来就通用，补白名单即可
  （单连接与多连接两个分支都补）。

## 5. 已知限制（SDK 层，非本次可修）

**这个 mbedtls 构建只报静态 RSA 套件、零 ECDHE。** ClientHello 实测（`tools/tls_sniff.py`）：

```
client ver = 0x0303 (TLS 1.2)，共 9 个套件，全部是 TLS_RSA_WITH_AES_*
0x003D 0x0035 0x003C 0x002F 0x00AF 0x008D 0x00AE 0x008C 0x00FF
```

`config.h` 里 `MBEDTLS_KEY_EXCHANGE_ECDHE_RSA_ENABLED` / `ECDH_C` / `ECDSA_C` / `ECP_C` 都是开着的，
但握手时没被选中。因此：

| 目标 | 结果 |
|---|---|
| `www.baidu.com:443` | **CONNECT OK** |
| `www.qq.com:443` | ERROR |
| `www.163.com:443` | ERROR |

⇒ 需要前向保密（ECDHE）的站点会握手失败。这是 SDK 的 mbedtls 裁剪问题，
要修需改 `ssl_ciphersuites.c` 的默认套件表并重新编译 mbedtls。

**测试服务器必须放宽 cipher**：`ctx.set_ciphers('ALL:@SECLEVEL=0')`。
OpenSSL 3.x 默认 cipher 串刻意排除无前向保密的 RSA-kex，否则报 `NO_SHARED_CIPHER` ——
**这是测试侧配置问题，不是固件 bug**。

## 6. 踩坑备忘

- **测 TLS 时别开 `ATE1`**：mbedtls 的 `bk_printf` 逐字节写 UART1 且无锁，日志会淹没 AT 应答，
  反而什么都抓不到。要日志用 `tools/tls_dbg2.py`（默认 ATE0）。
- **诊断链路**：`CIPSTART` 返回 ERROR 时，用 `tls_sniff.py` 裸 TCP 抓 ClientHello 看套件，
  用 `tls_dbg2.py` 看 `>` 提示与原始 AT 对话，比猜快得多。

## 7. 文件与补丁

- SDK 改动 4 个文件：`HAL_TLS_mbedtls.c`、`HAL_DTLS_mbedtls.c`、`network_app.c`、
  `network_interface.h`、`atsvr_net_cmd.c`（共 5 个）。
- `src/modified/` 已同步（**29 个文件**），`docs/patches/esp32c3-compat.patch` 已重生成
  （**27 文件 / 120209 字节**）并通过 `tools/verify_patch.py` 校验：
  干净应用到厂商原始树，且逐字节复现 `modified/`。
- `src/vendor-pristine/` 新增两个**真·厂商原版**，从 `sdk/BK7238-AT-v1.1.0.zip` 原始包提取
  （校验过不含本次改动、且含原版硬编码的 `VERIFY_REQUIRED`）。