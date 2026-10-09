#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
BK7238 / XH-WB3S 烧录 + 验证脚本 (COM3)

封装 bk_loader_v4.exe，规避其「失败仍返回退出码 0」的坑：
  * 只有日志出现 `all pass` / `Download complete` 才判定成功；
  * 出现 could not open port / PermissionError / 拒绝访问 / ERROR / FAIL 判失败；
  * 烧录后自动重启并从 115200 读取启动日志 + 执行 AT 握手验证。

用法:
    python flash_at.py firmware/at-esp32c3-compat.bin
    python flash_at.py firmware/xxx.bin --port COM3 --baud 2000000
    python flash_at.py firmware/xxx.bin --no-verify
"""
import argparse
import os
import re
import subprocess
import sys
import time
from datetime import datetime

import serial

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LOADER = os.path.join(HERE, 'bk_loader_v4.exe')

SUCCESS_RE = re.compile(r'all pass|Download complete|download complete', re.I)
ERROR_RE = re.compile(
    r'could not open port|PermissionError|could not open|拒绝访问|Traceback|'
    r'\bFAIL(ED)?\b|ERROR #|not found', re.I)


def flash(bin_path, port, baud, addr):
    cmd = [LOADER, 'download', '-p', port, '-b', str(baud), '-r',
           '-i', '%s@%s' % (bin_path, addr)]
    print('[flash] ' + ' '.join(cmd))
    t0 = time.time()
    p = subprocess.Popen(cmd, cwd=os.path.dirname(LOADER), stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, bufsize=1)
    lines = []
    for raw in iter(p.stdout.readline, b''):
        try:
            ln = raw.decode('utf-8', 'replace').rstrip()
        except Exception:
            ln = repr(raw)
        lines.append(ln)
        if ln.strip():
            print('  ' + ln)
    p.wait()
    dur = time.time() - t0
    text = '\n'.join(lines)
    ok = bool(SUCCESS_RE.search(text)) and not ERROR_RE.search(text)
    print('[flash] exit=%s elapsed=%.1fs -> %s' % (p.returncode, dur, 'PASS' if ok else 'FAIL'))
    return ok, text, dur


def verify(port, baud):
    """复位后读取启动日志并做 AT 握手。"""
    print('[verify] %s @%d' % (port, baud))
    try:
        s = serial.Serial(port, baud, timeout=0.2)
    except Exception as e:
        print('[verify] open failed: %s %s' % (type(e).__name__, e))
        return False, b''
    buf = b''
    # 触发复位: 部分板子靠 DTR/RTS，这里先监听，再发 AT 轮询
    t0 = time.time()
    while time.time() - t0 < 2.0:
        d = s.read(8192)
        if d:
            buf += d
    if b'OK' not in buf:
        # ATE0 持久化时无回显, 且烧后 2s 可能只读到 banner —— 没见 OK
        # 就继续 AT 握手 (banner 恰含 "OK" 的概率极低, 误报方向安全)
        for _ in range(10):
            s.write(b'AT\r\n')
            time.sleep(0.3)
            d = s.read(8192)
            if d:
                buf += d
                if b'OK' in buf:
                    break
    s.close()
    txt = bytes(x for x in buf if 0x20 <= x <= 0x7E or x in (10, 13))
    print('[verify] %d bytes: %s' % (len(buf), repr(txt[:400])))
    ok = b'OK' in buf
    return ok, buf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('bin')
    ap.add_argument('--port', default='COM3')
    ap.add_argument('--baud', type=int, default=2000000)
    ap.add_argument('--addr', default='0x0-0xFFFFFFF')
    ap.add_argument('--no-verify', action='store_true')
    ap.add_argument('--log', default=None)
    args = ap.parse_args()

    binp = args.bin if os.path.isabs(args.bin) else os.path.join(ROOT, args.bin)
    if not os.path.exists(binp):
        print('bin not found: %s' % binp)
        return 2
    print('[info] bin=%s (%d bytes)' % (binp, os.path.getsize(binp)))

    ok, text, dur = flash(binp, args.port, args.baud, args.addr)

    vok = None
    if ok and not args.no_verify:
        time.sleep(1.5)
        vok, _ = verify(args.port, 115200)

    logp = args.log or os.path.join(ROOT, 'test', 'flash_%s.log' %
                                    datetime.now().strftime('%Y%m%d_%H%M%S'))
    os.makedirs(os.path.dirname(logp), exist_ok=True)
    with open(logp, 'w', encoding='utf-8') as f:
        f.write('bin=%s\nport=%s baud=%d addr=%s\nelapsed=%.1fs\n'
                'flash=%s verify=%s\n\n%s\n'
                % (binp, args.port, args.baud, args.addr, dur,
                   'PASS' if ok else 'FAIL', vok, text))
    print('[log] %s' % logp)
    print('RESULT=%s' % ('PASS' if ok and (vok is not False) else 'FAIL'))
    return 0 if (ok and (vok is not False)) else 1


if __name__ == '__main__':
    sys.exit(main())
