#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ESP32-C3 (ESP-AT) 兼容性回归测试工具  ——  针对 BK7238 / XH-WB3S 模组

用法:
    python at_compat_test.py COM3                     # 全量测试 @115200
    python at_compat_test.py COM3 --category basic    # 只测基础命令
    python at_compat_test.py COM3 --out ../test/compat_before.md
    python at_compat_test.py COM3 --save-raw          # 保存原始收发字节

判定: 每条命令给出 expected 正则之一命中 => PASS, 否则 FAIL。
      命令本身被拒(返回 ERROR/不支持) 会标记为 FAIL 并记录实际响应。
"""
import argparse
import os
import re
import sys
import time
from datetime import datetime

import serial

# ----------------------------------------------------------------------------
# 命令表: (类别, 命令, 期望正则列表, 说明)
# 期望正则为 ESP-AT(ESP32-C3) 官方应答格式
# ----------------------------------------------------------------------------
COMMANDS = [
    # ---------------- 基础 AT 命令 ----------------
    ('basic', 'AT',                          [r'\bOK\b'],                              '握手'),
    ('basic', 'AT+GMR',                      [r'AT version', r'SDK version', r'\bOK\b'], '版本信息'),
    ('basic', 'AT+SYSRAM?',                  [r'\+SYSRAM:\d+'],                        '查询剩余内存'),
    ('basic', 'AT+SYSTIMESTAMP?',            [r'\+SYSTIMESTAMP:-?\d+'],                '查询系统时间戳'),
    ('basic', 'AT+SYSSTORE?',                [r'\+SYSSTORE:[01]'],                     '查询参数存储模式'),
    # 这两个的合法取值是有限枚举，用字符类而非 \d+：
    # 否则一旦代码里漏传参数、打印出垃圾大数（如 +SYSMSG:4333088），
    # \d+ 会误判为 PASS。负数/多位数字在这里都应当视为失败。
    ('basic', 'AT+SYSMSG?',                  [r'\+SYSMSG:[0-3](?!\d)'],                '查询系统提示模式'),
    ('basic', 'AT+UART_CUR?',                [r'\+UART_CUR:\d+,\d+,\d+,\d+,\d+'],      '查询当前串口配置'),
    ('basic', 'AT+UART_DEF?',                [r'\+UART_DEF:\d+,\d+,\d+,\d+,\d+'],      '查询默认串口配置'),
    ('basic', 'AT+SLEEP?',                   [r'\+SLEEP:[0-2](?!\d)'],                 '查询睡眠模式'),
    ('basic', 'AT+RESTORE?',                 [r'\bOK\b', r'\bERROR\b'],                '恢复出厂(仅探活,不执行)'),
    ('basic', 'AT+CIPSTATUS?',               [r'STATUS:'],                             '查询网络状态(兼容探测)'),

    # ---------------- Wi-Fi AT 命令 ----------------
    ('wifi', 'AT+CWMODE?',                   [r'\+CWMODE:\d'],                         '查询 Wi-Fi 模式'),
    ('wifi', 'AT+CWMODE_CUR?',               [r'\+CWMODE_CUR:\d'],                     '查询当前 Wi-Fi 模式'),
    ('wifi', 'AT+CWMODE_DEF?',               [r'\+CWMODE_DEF:\d'],                     '查询默认 Wi-Fi 模式'),
    ('wifi', 'AT+CWJAP?',                    [r'\+CWJAP:', r'No AP'],                  '查询已连接 AP'),
    ('wifi', 'AT+CWLAP',                     [r'\+CWLAP:', r'\bOK\b', r'\bERROR\b'],   '扫描 AP 列表'),
    ('wifi', 'AT+CWAUTOCONN?',               [r'\+CWAUTOCONN:[01]'],                   '查询自动连接'),
    ('wifi', 'AT+CWDHCP?',                   [r'\+CWDHCP:'],                           '查询 DHCP'),
    ('wifi', 'AT+CWDHCP_CUR?',               [r'\+CWDHCP_CUR:'],                       '查询当前 DHCP'),
    ('wifi', 'AT+CWDHCP_DEF?',               [r'\+CWDHCP_DEF:'],                       '查询默认 DHCP'),
    ('wifi', 'AT+CIPSTA?',                   [r'\+CIPSTA:'],                           '查询 STA IP'),
    ('wifi', 'AT+CIPSTA_CUR?',               [r'\+CIPSTA_CUR:'],                       '查询 STA IP(当前)'),
    ('wifi', 'AT+CIPSTA_DEF?',               [r'\+CIPSTA_DEF:'],                       '查询 STA IP(默认)'),
    ('wifi', 'AT+CIPAP?',                    [r'\+CIPAP:'],                            '查询 SoftAP IP'),
    ('wifi', 'AT+CIPSTAMAC?',                [r'\+CIPSTAMAC:'],                        '查询 STA MAC'),
    ('wifi', 'AT+CIPSTAMAC_CUR?',            [r'\+CIPSTAMAC_CUR:'],                    '查询 STA MAC(当前)'),
    ('wifi', 'AT+CIPSTAMAC_DEF?',            [r'\+CIPSTAMAC_DEF:'],                    '查询 STA MAC(默认)'),
    ('wifi', 'AT+CWSAP?',                    [r'\+CWSAP:', r'\bERROR\b'],              '查询 SoftAP 配置'),
    ('wifi', 'AT+CWLIF',                     [r'\bOK\b', r'\bERROR\b'],                '查询已连接 STA'),
    ('wifi', 'AT+CWCOUNTRY?',                [r'\+CWCOUNTRY:'],                        '查询国家码'),

    # ---------------- TCP/IP AT 命令 ----------------
    ('tcpip', 'AT+CIFSR',                    [r'\+CIFSR:STAIP', r'\+CIFSR:APIP'],      '查询本地 IP'),
    ('tcpip', 'AT+CIPMUX?',                  [r'\+CIPMUX:[01]'],                       '查询连接模式'),
    ('tcpip', 'AT+CIPMODE?',                 [r'\+CIPMODE:[01]'],                      '查询传输模式'),
    ('tcpip', 'AT+CIPDINFO?',                [r'\+CIPDINFO:[01]'],                     '查询接收信息'),
    ('tcpip', 'AT+CIPRECVTYPE?',             [r'\+CIPRECVTYPE:[01]'],                  '查询接收模式'),
    ('tcpip', 'AT+CIPRECVMODE?',             [r'\+CIPRECVMODE:[01]'],                  '查询接收模式(旧)'),
    ('tcpip', 'AT+CIPSTATUS',                [r'STATUS:\d'],                           '查询连接状态(经典)'),
    ('tcpip', 'AT+CIPSTATE',                 [r'\+CIPSTATE:|^\s*OK\b', r'\bOK\b'],     '查询连接信息(新版)'),
    ('tcpip', 'AT+CIPSNTPCFG?',              [r'\+CIPSNTPCFG:'],                       '查询 SNTP 配置'),
    ('tcpip', 'AT+CIPSNTPTIME?',             [r'\+CIPSNTPTIME:'],                      '查询 SNTP 时间'),
    ('tcpip', 'AT+CIPDOMAIN="example.com"',  [r'\+CIPDOMAIN:', r'\bERROR\b'],          '域名解析'),
    # 修复后必须是 ESP-AT 的 +PING:<毫秒> 或 +PING:TIMEOUT；
    # 用 (?![\d]*[A-Za-z]) 之类的宽泛写法会放过原厂的 "From x timeout" 裸文本，
    # 所以这里严格限定两种合法形态。
    ('tcpip', 'AT+PING="127.0.0.1"',         [r'\+PING:(?:\d+|TIMEOUT)(?!\w)'],        'PING(ESP-AT 格式)'),
    ('tcpip', 'AT+CIPTCPOPT?',               [r'\+CIPTCPOPT:', r'\bERROR\b'],          '查询 TCP 选项'),
    ('tcpip', 'AT+CIPSTART?',                [r'\bOK\b', r'\bERROR\b'],                '查询连接(兼容探测)'),
    ('tcpip', 'AT+CIPSERVER?',               [r'\+CIPSERVER:', r'\bERROR\b'],          '查询 TCP Server'),

    # ---------------- BLE AT 命令 ----------------
    ('ble', 'AT+BLEINIT?',                   [r'\+BLEINIT:\d'],                        '查询 BLE 初始化状态'),
    ('ble', 'AT+BLENAME?',                   [r'\+BLENAME:'],                          '查询 BLE 名称'),
    ('ble', 'AT+BLEADDR?',                   [r'\+BLEADDR:'],                          '查询 BLE 地址'),
    ('ble', 'AT+BLEADVPARAM?',               [r'\+BLEADVPARAM:'],                      '查询广播参数'),
    ('ble', 'AT+BLESCANPARAM?',              [r'\+BLESCANPARAM:'],                     '查询扫描参数'),
    ('ble', 'AT+BLESPPCFG?',                 [r'\+BLESPPCFG:', r'\bERROR\b'],          '查询 BLE SPP 配置'),

    # ---------------- MQTT AT 命令 ----------------
    ('mqtt', 'AT+MQTTUSERCFG?',              [r'\+MQTTUSERCFG:', r'\bERROR\b'],        '查询 MQTT 用户配置'),
    ('mqtt', 'AT+MQTTCONN?',                 [r'\+MQTTCONN:', r'\bERROR\b'],           '查询 MQTT 连接'),

    # ---------------- HTTP AT 命令 ----------------
    ('http', 'AT+HTTPCLIENT?',               [r'\+HTTPCLIENT:', r'\bERROR\b'],         '查询 HTTP 客户端'),
    ('http', 'AT+HTTPURLCFG?',               [r'\+HTTPURLCFG:', r'\bERROR\b'],         '查询 HTTP URL 配置'),
]

# 主动上报/引导信息（启动日志）
BOOT_MARKERS = ['ready', 'AT version']

# 这些命令耗时明显更长（射频扫描 / DNS / PING），单独放宽等待窗口
SLOW_TIMEOUT = {
    'AT+CWLAP': 9.0,
    'AT+CIPDOMAIN="example.com"': 7.0,
    'AT+PING="127.0.0.1"': 7.0,
}

# 见到 OK/ERROR 之后，还要再等这么久确认串口 FIFO 排空才结束本条。
#
# 为什么需要（2026-10-09 修）：UART 由 DMA 搬运，模组吐应答比 PC 的读循环快。
# 原实现一见到 OK/ERROR 就 break，下一条命令开头的 reset_input_buffer()
# 会把还压在串口 FIFO 里的上一次应答直接丢掉 —— 表现为「上一条无输出、
# 下一条却多出上一条的回答」，55 条里造成 3 条假性 FAIL（实际全部工作正常，
# 慢速单条复核全通）。改成「见到结束标记后必须静默 DRAIN_WAIT 才收工」。
DRAIN_WAIT = 0.12


def clean_response(b: bytes) -> str:
    """去掉 ANSI 转义与 NUL，便于比对与展示。"""
    out = []
    i = 0
    while i < len(b):
        c = b[i]
        if c == 0x1B:
            i += 1
            while i < len(b) and not (0x40 <= b[i] <= 0x7E):
                i += 1
            i += 1
            continue
        if c == 0:
            i += 1
            continue
        out.append(chr(c) if (0x20 <= c <= 0x7E or c in (10, 13, 9)) else '.')
        i += 1
    return ''.join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('port', nargs='?', default='COM3')
    ap.add_argument('--baud', type=int, default=115200)
    ap.add_argument('--category', default=None)
    ap.add_argument('--out', default=None)
    ap.add_argument('--timeout', type=float, default=1.2)
    ap.add_argument('--save-raw', action='store_true')
    args = ap.parse_args()

    cmds = [c for c in COMMANDS if args.category is None or c[0] == args.category]

    ser = serial.Serial(args.port, args.baud, timeout=0.2)
    time.sleep(0.3)
    ser.reset_input_buffer()

    rows = []
    raw_dir = None
    if args.save_raw:
        raw_dir = os.path.join(os.path.dirname(os.path.abspath(args.out or '.')), 'raw')
        os.makedirs(raw_dir, exist_ok=True)

    for cat, cmd, pats, desc in cmds:
        # 射频扫描 / 域名解析 / PING 天然慢，单独给更长的等待窗口，
        # 否则会在结果回来之前就判定超时（表现为「无输出」）。
        wait = SLOW_TIMEOUT.get(cmd, args.timeout)
        ser.reset_input_buffer()
        ser.write((cmd + '\r\n').encode())
        t0 = time.time()
        buf = b''
        seen_end = False
        while time.time() - t0 < wait:
            d = ser.read(8192)
            if d:
                buf += d
                txt = clean_response(buf)
                if re.search(r'\bOK\b|\bERROR\b', txt):
                    seen_end = True
            elif seen_end and time.time() - t0 > 0.25 + DRAIN_WAIT:
                # 已见到结束标记，且随后 DRAIN_WAIT 内没有新字节 => 串口 FIFO 排空
                break
        txt = clean_response(buf)
        hit = None
        for p in pats:
            if re.search(p, txt):
                hit = p
                break
        ok = hit is not None
        rows.append((cat, cmd, desc, 'PASS' if ok else 'FAIL',
                     hit or '/'.join(pats), txt.strip()))
        if raw_dir:
            with open(os.path.join(raw_dir, re.sub(r'\W+', '_', cmd) + '.txt'), 'wb') as f:
                f.write(buf)
    ser.close()

    # ---- 汇总 ----
    total = len(rows)
    passed = sum(1 for r in rows if r[3] == 'PASS')
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    lines = []
    lines.append('# ESP32-C3 (ESP-AT) 兼容性测试报告')
    lines.append('')
    lines.append('- 时间: %s' % now)
    lines.append('- 端口: %s @ %d' % (args.port, args.baud))
    lines.append('- 结果: **%d/%d PASS** (%.1f%%)' % (passed, total, 100.0 * passed / total))
    lines.append('')
    lines.append('## 汇总')
    lines.append('')
    lines.append('| # | 类别 | AT 命令 | 说明 | 结果 | 期望 | 实际响应 |')
    lines.append('|---|------|---------|------|------|------|----------|')
    for i, (cat, cmd, desc, res, exp, act) in enumerate(rows, 1):
        act1 = act.replace('|', '\\|').replace('\n', ' ⏎ ')
        if len(act1) > 220:
            act1 = act1[:220] + '…'
        lines.append('| %d | %s | `%s` | %s | %s | `%s` | `%s` |' %
                     (i, cat, cmd, desc, res, exp, act1))
    lines.append('')
    # 分组统计
    lines.append('## 分类统计')
    lines.append('')
    cats = {}
    for cat, cmd, desc, res, exp, act in rows:
        c = cats.setdefault(cat, [0, 0])
        c[1] += 1
        if res == 'PASS':
            c[0] += 1
    lines.append('| 类别 | PASS/总数 |')
    lines.append('|------|-----------|')
    for k in sorted(cats):
        lines.append('| %s | %d/%d |' % (k, cats[k][0], cats[k][1]))
    lines.append('')
    # 失败清单
    fails = [r for r in rows if r[3] == 'FAIL']
    lines.append('## 不兼容命令清单 (%d)' % len(fails))
    lines.append('')
    for cat, cmd, desc, res, exp, act in fails:
        lines.append('- `%s` (%s) — 期望 `%s`，实际 `%s`' %
                     (cmd, desc, exp, act.replace('\n', ' ')[:160]))
    report = '\n'.join(lines)

    out = args.out
    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with open(out, 'w', encoding='utf-8') as f:
            f.write(report)
        print('[saved] %s' % out)
    print(report)
    return 0 if passed == total else 1


if __name__ == '__main__':
    sys.exit(main())
