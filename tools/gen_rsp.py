#!/usr/bin/env python3
"""生成 gcc 响应文件 work/ccflags.rsp。

背景: 本 SDK 的编译命令行约 18.4K 字符(-I 就有 237 个目录),
      而 Windows 上 make 只能安全传递 <8191 字符, 超出会被截断,
      表现为 `arm-none-eabi-gcc: error: -E or -x required when input is
      from standard input`(输入文件那一段被截掉了)。

做法: 把 CFLAGS + INCLUDES（编译选项）+ 源文件前的部分全部塞进 rsp 文件,
      然后用 `CC="<gcc> @<rsp>"` + `CFLAGS= INCLUDES=` 覆盖 make 变量
      (命令行的变量赋值优先级最高, 会盖掉 makefile 里的 =/+=),
      编译命令因此缩短到约 0.1K。rsp 是 gcc 原生支持的机制, 最标准稳妥。

用法: python tools/gen_rsp.py
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SDK = os.path.join(ROOT, 'sdk', 'BK7238-AT')
MAKE = os.path.join(ROOT, 'tools', 'gmake', 'make.exe')
OUT = os.path.join(ROOT, 'work', 'ccflags.rsp')
PROBE = 'out/./beken378/func/airkiss/airkiss_pingpong.o'


def main():
    tcbin = None
    tcdir = os.path.join(ROOT, 'sdk', 'toolchain')
    for d in sorted(os.listdir(tcdir)):
        p = os.path.join(tcdir, d, 'bin')
        if os.path.exists(os.path.join(p, 'arm-none-eabi-gcc.exe')):
            tcbin = p
            break
    if not tcbin:
        print('!! 找不到工具链', file=sys.stderr)
        return 1
    gcc = os.path.join(tcbin, 'arm-none-eabi-gcc.exe').replace('\\', '/')

    env = dict(os.environ)
    env['FREERTOS_EXEC_PATH'] = tcbin.replace('\\', '/') + '/'
    env['ARM_GCC_TOOLCHAIN'] = env['FREERTOS_EXEC_PATH']

    # 用 -B 强制认为目标过期, 保证 make -n 一定打印出编译命令
    subprocess.run([MAKE, '-f', 'application.mk', 'ROOT_DIR=' + SDK.replace('\\', '/'),
                    'ENCRYPT=./tools/crc_binary/encrypt.exe', 'ENCRYPT_ARGS=',
                    '-B', '-n', PROBE],
                   cwd=SDK, env=env, capture_output=True, text=True, errors='replace')
    p = subprocess.run([MAKE, '-f', 'application.mk', 'ROOT_DIR=' + SDK.replace('\\', '/'),
                        'ENCRYPT=./tools/crc_binary/encrypt.exe', 'ENCRYPT_ARGS=',
                        '-B', '-n', PROBE],
                       cwd=SDK, env=env, capture_output=True, text=True, errors='replace')

    line = None
    for l in p.stdout.splitlines():
        if l.strip().startswith(gcc) and ' -c ' in l:
            line = l
            break
    if not line:
        print('!! 未能取得完整编译命令, 前 1500 字符:\n' + p.stdout[:1500], file=sys.stderr)
        return 1

    head, tail = line.split(' -c ', 1)
    opts = head[len(gcc):].strip()          # gcc 之后、-c 之前的所有选项
    # gcc 对 rsp 内容按空白/换行切分, 这里每行一个选项更稳
    toks = opts.split()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        for t in toks:
            f.write(t + '\n')
    print('[rsp] 原命令 %d 字符 -> rsp 内 %d 个选项' % (len(line), len(toks)))
    print('[rsp] 写出 %s' % os.path.relpath(OUT, ROOT))
    newlen = len(gcc) + len(' @work/ccflags.rsp') + len(' -c ' + tail)
    print('[rsp] 编译命令将缩短到约 %d 字符 (<8191 限制)' % newlen)
    return 0


if __name__ == '__main__':
    sys.exit(main())
