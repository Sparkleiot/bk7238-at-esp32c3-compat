# 第三方组件声明（THIRD PARTY NOTICES）

本项目（`bk7238-at-esp32c3-compat`）的 `src/` 目录与 `docs/patches/esp32c3-compat.patch`
中包含**第三方厂商的源代码**。这些文件的著作权归各原作者所有，
本项目**仅因技术需要进行修改或打包再分发**，不代表本项目作者对这些代码主张著作权。

**请务必阅读本文件。** 每一处第三方代码都保留其原有的版权声明与许可条款；
若某文件的原始许可未在本文件中列明，请以该文件内部的声明为准。

---

## 一、SPARKLEIOT 自有资产（版权 © Sparkleiot）

以下内容为本项目原创或由本项目作者编写，可自由使用：

| 内容 | 位置 |
|------|------|
| AT 命令对齐层（`atsvr_cmd.c` / `atsvr_net_cmd.c` / `atsvr_wlan.c` 等 22 个文件中的 ESP-AT 兼容改造） | `src/modified/` |
| `AT+CIPSSLCCONF` 命令实现 | `src/modified/atsvr_net_cmd.c` |
| TLS 能力修复（`auth_mode` / PSK 守卫 / 读超时语义修正） | `src/modified/HAL_TLS_mbedtls.c`、`HAL_DTLS_mbedtls.c` |
| 网络缺陷修复（`+IPD` 前缀、TCP 超时、线程槽、CIPCLOSE 异步、SoftAP netif） | `src/modified/` 下多个文件 |
| 全部测试脚本（85 个 Python 工具） | `tools/` |
| AT 指令手册、兼容性差距分析、硬件要点 | `docs/*.md` |
| 构建与自检工具（`build.sh` / `gen_patch.py` / `check_modified_sync.py` / `verify_patch.py`） | `tools/` |
| 验收报告 | `test/` |

本项目源码中以`@@` 标记的 hunk 段落、以及 `docs/AT指令说明.md` 中描述的行为，
属于本项目的原创工作。

---

## 二、Tencent THL A29 Limited（MIT License）

以下文件带有如下声明，许可为 **MIT**：

```
 * Copyright (C) 2016 THL A29 Limited, a Tencent company. All rights reserved.
 * Copyright (C) 2018-2020 THL A29 Limited, a Tencent company. All rights reserved.
 * Licensed under the MIT License (the "License"); you may not use this file except in
 * compliance with the License. You may obtain a copy of the License at
 * http://opensource.org/licenses/MIT
```

| 文件 | 说明 |
|------|------|
| `src/modified/network_socket.c` | TCP/UDP socket 封装 |
| `src/modified/network_interface.h` | 网络接口类型定义（`SSLConnectParams` 扩展为本项目新增） |
| `src/modified/qcloud_at_mqtt.c` | 腾讯云 MQTT AT 客户端 |
| `src/modified/HAL_TCP_lwip.c` | TCP HAL（lwIP 适配） |
| `src/modified/HAL_UDP_lwip.c` | UDP HAL（lwIP 适配） |
| `src/modified/HAL_TLS_mbedtls.c` | TLS HAL |
| `src/modified/HAL_DTLS_mbedtls.c` | DTLS HAL |

对应的原厂备份（同样含上述声明）：

- `src/vendor-pristine/network_socket.c.orig`
- `src/vendor-pristine/network_interface.h.orig`
- `src/vendor-pristine/qcloud_at_mqtt.c.orig`
- `src/vendor-pristine/HAL_TCP_lwip.c.orig`
- `src/vendor-pristine/HAL_UDP_lwip.c.orig`
- `src/vendor-pristine/HAL_TLS_mbedtls.c.orig`
- `src/vendor-pristine/HAL_DTLS_mbedtls.c.orig`

> MIT 许可允许使用、复制、修改、合并、再分发与销售，**唯一要求是保留上述版权声明与许可文本**。
> 这些声明已完整保留在各自文件头部。
> 本项目对这些文件的修改（TLS 能力修复、`SSLConnectParams` 扩展）同样按 MIT 条款发布。

**MIT License 全文**

```
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## 三、Marvell International Ltd.

以下文件带有如下声明：

```
 * Copyright (C) 2008-2015, Marvell International Ltd.
```

| 文件 | 说明 |
|------|------|
| `src/modified/dhcp-server.c` | DHCP 服务器实现 |
| `src/modified/dhcp-server-main.c` | DHCP 服务器主入口 |
| `src/modified/dhcp-priv.h` | DHCP 私有头文件 |
| `src/vendor-pristine/dhcp-server.c.orig` | 同上（原厂备份） |
| `src/vendor-pristine/dhcp-server-main.c.orig` | 同上（原厂备份） |
| `src/vendor-pristine/dhcp-priv.h.orig` | 同上（原厂备份） |

> ⚠️ **本项目未能确认这些文件的完整许可条款**（文件内仅标注著作权，
> 未见 MIT / BSD / Apache 等具体许可文本）。
>
> 它们被包含在 Beken SDK 发行包中并随本模组固件使用。
> 若你打算**将本仓库整体或`src/` 目录再分发**，建议：
> 1. 向 Marvell 或你的 SDK 供应方确认这些文件的再分发条款；
> 2. 或从你的分发版本中移除 `src/modified/dhcp-server.c`、
>    `src/modified/dhcp-server-main.c`、`src/modified/dhcp-priv.h`
>    及其 `src/vendor-pristine/` 下的对应 `.orig` 备份，
>    仅保留编译产物 `firmware/*.bin`。
>
> 这不影响本项目的 AT 命令兼容性——这些文件属于 DHCP 服务端实现，
> 与 AT 层无关。

---

## 四、Alibaba Group Holding Limited

以下文件带有如下声明：

```
 * Copyright (C) 2015-2017 Alibaba Group Holding Limited
```

| 文件 | 说明 |
|------|------|
| `src/modified/utils_httpc.c` | HTTP 客户端实现 |
| `src/vendor-pristine/utils_httpc.c.orig` | 同上（原厂备份） |

> ⚠️ **本项目未能确认该文件的完整许可条款**（仅见著作权标注）。
>
> 同样建议：若整体再分发，请先核实许可，或从分发版本中移除该文件
> （HTTP 客户端可由其他实现替代，不影响 AT 命令层）。

---

## 五、lwIP / RT-Thread（GPL —— 本仓库已彻底不依赖）

`ping.c` 是 lwIP 生态的 **GPL v2/v3 传染性copyleft** 组件，其原始版权声明为：

```
COPYRIGHT (C) 2006-2018, RT-Thread Development Team
This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
GNU General Public License for more details.
```

**本仓库既不包含、也不修改、也不依赖该文件。**

| 项目 | 状态 |
|------|------|
| `src/modified/ping.c` | ❌ 不在版本控制中（`.gitignore` 已拦截） |
| `src/vendor-pristine/ping.c.orig` | ❌ 不在版本控制中 |
| `docs/patches/esp32c3-compat.patch` | ❌ **不含该文件的任何 hunk** |
| SDK 侧的 `ping.c` | ✅ 保持厂商原样、**零改动** |

**为什么能做到**：本项目需要 `AT+PING` 的 ESP-AT 语义（回`+PING:<毫秒>`）。
早期版本直接改这个 GPL 文件来加 `at_ping_ex()`，现已改为在
**`src/modified/atsvr_esp_compat.c`** 里自研一份ICMP Echo
（函数 `atsvr_icmp_ping_once`），只调用 lwIP 的**公开 socket API**
（`lwip_socket` / `lwip_setsockopt` / `lwip_sendto` / `lwip_recvfrom` / `lwip_close`），
**不复制、不改写 `ping.c` 的任何代码**。

这样做同时解决了两个问题：
1. **许可合规**：GPL 代码在本仓库中彻底不存在，本仓库的 MIT 双轨声明因此成立。
2. **可构建性**：`src/apply.sh` 不再 `cp` 这个文件。若保留那条 `cp`，一旦文件不在
   仓库里，脚本会在 `set -e` 下**中途失败**，导致其后的 8 个文件
   （`HAL_TLS_mbedtls.c` / `HAL_TCP_lwip.c` / `network_socket.c` / `application.mk`
   / `sys_config_bk7238.h` 等）**根本不会被覆盖**，克隆者会编出缺关键修复的固件。

实测结果（`+PING:<毫秒>` 正常返回 RTT、TIMEOUT 语义正确）见 `test/at_ping_finding.md`。

---

## 六、Beken（基础 SDK 提供方）

本项目的基线为Sparkleiot `BK7238_AT` V1.1.0（Beken `beken378` SDK 3.0.70）。
除上述已明确归属的第三方组件外，`src/` 下其余文件为 Beken 提供的 SDK 源码。

**这些文件的使用与再分发须遵守 Beken / Sparkleiot 的 SDK 授权条款。**

`src/vendor-pristine/` 目录是 Beken 原厂文件的**逐字节备份**，仅用于
生成 `docs/patches/esp32c3-compat.patch` 时的差异对比。

---

## 七、预编译二进制库（未包含在本仓库中）

以下为预编译的 `.a` 静态库，**其源码与许可未包含在本仓库**，
本项目也无法修改其内部行为：

| 库 | 用途 | 备注 |
|----|------|------|
| `hostapd` | SoftAP | README §6.1 记录的 WPA2 握手失败问题源于此库 |
| `mbedtls` | TLS/DTLS | README §6.1 记录"仅静态 RSA 套件、无 ECDHE"源于此库 |
| `lwIP` | TCP/IP 协议栈 | — |
| `wpa` | STA 侧认证 | — |

这些库已包含在 Beken SDK 发行包中，随 `sdk/` 目录提供（`sdk/` 不在本仓库内）。

---

## 八、汇总：使用本仓库前请确认

1. **MIT 部分**（腾讯系文件）→ 自由使用，保留声明即可。
2. **Marvell / Alibaba 部分** → 许可条款未明，整体再分发前请核实。
3. **Beken SDK 部分** → 须遵守 Beken / Sparkleiot 授权条款。
4. **GPL 部分**（lwIP `ping.c`） → ✅ **本仓库已彻底不依赖**（既不含、也不改、
   补丁里也无其hunk）。`AT+PING` 已在 `atsvr_esp_compat.c` 里自研实现。
   你若要自行取用 lwIP 的 `ping.c`，请从 Beken SDK 发行包获取并遵守 GPL v2/v3。
5. **原厂手册**（`docs/*.docx`）→ 版权属 Sparkleiot / Beken，本仓库仅供本模组使用者参考。

若你对某项归属有疑问，请查阅对应文件顶部的原始版权声明——
**原始文件中的声明始终优先于本文件。**
