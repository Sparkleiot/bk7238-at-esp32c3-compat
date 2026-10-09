#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
BK7238 (ESP32-C3 兼容 AT 固件) 功能测试 —— 写入 + 回读校验

tools/at_compat_test.py 只验证「命令存在、应答格式对」，本脚本进一步验证
「设置类命令真的生效、且回读命令名与写入命令名一致」。

重点覆盖:
  1. 写入 -> 回读 值是否一致
  2. AT+CWMODE_CUR / _DEF 等别名回读时前缀是否跟随实际命令名
     (ESP-AT 要求 +CWMODE_CUR: 而不是 +CWMODE:)
  3. AT+CIPRECVMODE 与 AT+CIPRECVTYPE 是同一份状态

用法:
    python tools/at_functional_test.py COM3
    python tools/at_functional_test.py COM3 --out test/functional.md
"""
import argparse
import os
import re
import sys
import time

import serial

# (set_cmd, read_cmd, expect_regex, desc, restore_cmd)
CASES = [
    ('AT+CWMODE=1',        'AT+CWMODE?',        r'\+CWMODE:1\b',          'STA 模式写入回读',      None),
    ('AT+CWMODE=2',        'AT+CWMODE?',        r'\+CWMODE:2\b',          'SoftAP 模式写入回读',   'AT+CWMODE=1'),
    ('AT+CWMODE_CUR=1',    'AT+CWMODE_CUR?',    r'\+CWMODE_CUR:1\b',      '_CUR 别名前缀跟随',     None),
    ('AT+CWMODE=3',        'AT+CWMODE_DEF?',    r'\+CWMODE_DEF:3\b',      '_DEF 别名前缀跟随',     'AT+CWMODE=1'),
    ('AT+CWAUTOCONN=1',    'AT+CWAUTOCONN?',    r'\+CWAUTOCONN:1\b',      '自动连接开关',          'AT+CWAUTOCONN=0'),
    ('AT+CIPMUX=1',        'AT+CIPMUX?',        r'\+CIPMUX:1\b',          '多连接模式',            'AT+CIPMUX=0'),
    ('AT+CIPDINFO=1',      'AT+CIPDINFO?',      r'\+CIPDINFO:1\b',        '接收信息附加开关',      'AT+CIPDINFO=0'),
    ('AT+CIPRECVMODE=1',   'AT+CIPRECVMODE?',   r'\+CIPRECVMODE:1\b',     '旧名 CIPRECVMODE 写入', None),
    ('AT+CIPRECVTYPE?',    None,                r'\+CIPRECVTYPE:1\b',     'CIPRECVMODE/TYPE 共享状态', 'AT+CIPRECVTYPE=0'),
    ('AT+SYSMSG=1',        'AT+SYSMSG?',        r'\+SYSMSG:1\b',          '系统提示开关',          'AT+SYSMSG=0'),
    ('AT+SLEEP=0',         'AT+SLEEP?',         r'\+SLEEP:0\b',           '睡眠模式',              None),
    ('AT+CWDHCP=1,1',      'AT+CWDHCP?',        r'\+CWDHCP:3\b',          'DHCP 使能(STA+AP)',     None),
    ('AT+CWCOUNTRY=CN,1,13,1', 'AT+CWCOUNTRY?', r'\+CWCOUNTRY:CN,1,13,1', '国家码/信道范围',       None),
    ('AT+CWJAP_CUR?',      None,                r'No AP|\+CWJAP_CUR:',     'CWJAP_CUR 别名探活',    None),
    ('AT+CIPSTATUS?',      None,                r'STATUS:[0-5]\b',        'STATUS 语义(离线=5/在线=2或3)', None),
    ('AT+CIPSTATE',        None,                r'\bOK\b',                '新版连接信息命令',      None),
]


def clean(b: bytes) -> str:
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


def talk(ser, cmd, wait=1.5):
    ser.reset_input_buffer()
    ser.write((cmd + '\r\n').encode())
    t0 = time.time()
    buf = b''
    while time.time() - t0 < wait:
        d = ser.read(8192)
        if d:
            buf += d
            if re.search(r'\bOK\b|\bERROR\b', clean(buf)) and time.time() - t0 > 0.25:
                break
    return clean(buf)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('port', nargs='?', default='COM3')
    ap.add_argument('--baud', type=int, default=115200)
    ap.add_argument('--out', default=None)
    args = ap.parse_args()

    ser = serial.Serial(args.port, args.baud, timeout=0.2)
    time.sleep(0.3)
    ser.reset_input_buffer()

    rows = []
    npass = 0
    for setcmd, readcmd, pattern, desc, restore in CASES:
        writes = ''
        if setcmd:
            writes = talk(ser, setcmd)
            if not re.search(r'\bOK\b', writes):
                rows.append((desc, setcmd, pattern, 'FAIL',
                             '写入未回 OK: %s' % writes.replace('\n', ' ')[:70]))
                continue
        read = readcmd or setcmd
        resp = talk(ser, read)
        ok = bool(re.search(pattern, resp))
        npass += ok
        if restore:
            talk(ser, restore)
        rows.append((desc, read, pattern, 'PASS' if ok else 'FAIL',
                     resp.replace('\n', ' ').replace('\r', '')[:90]))

    ser.close()

    total = len(CASES)
    lines = []
    lines.append('# BK7238 ESP-AT 兼容固件 — 功能测试（写入/回读）\n')
    lines.append('- 端口: %s @ %d' % (args.port, args.baud))
    lines.append('- 结果: **%d/%d PASS** (%.1f%%)\n'
                 % (npass, total, 100.0 * npass / total))
    lines.append('| # | 验证点 | 回读命令 | 期望 | 结果 | 实际响应 |')
    lines.append('|---|--------|----------|------|------|----------|')
    for i, (desc, read, pat, res, resp) in enumerate(rows, 1):
        lines.append('| %d | %s | `%s` | `%s` | %s | `%s` |'
                     % (i, desc, read, pat, res, resp))
    lines.append('')
    text = '\n'.join(lines)
    print(text)

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, 'w', encoding='utf-8') as f:
            f.write(text)
        print('[report] %s' % args.out)

    return 0 if npass == total else 1


if __name__ == '__main__':
    sys.exit(main())
