#!/usr/bin/env python3
"""生成 include 目录清单, 供 CPATH 使用。

用法: python tools/gen_inc_list.py         # 生成 work/inc_list.txt (每行一个目录)
原理: 用 make -n 打印某个对象的真实编译命令, 从中抽出全部 -I<dir>。
      build.sh 会把它们拼成 CPATH, 从而不必出现在命令行里
      (Windows/make 的命令行上限 8191, 原样会到 18K 而被截断)。
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SDK = os.path.join(ROOT, 'sdk', 'BK7238-AT')
MAKE = os.path.join(ROOT, 'tools', 'gmake', 'make.exe')
OUT = os.path.join(ROOT, 'work', 'inc_list.txt')
PROBE_TARGET = 'out/./beken378/func/airkiss/airkiss_pingpong.o'


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

    env = dict(os.environ)
    env['FREERTOS_EXEC_PATH'] = tcbin.replace('\\', '/') + '/'
    env['ARM_GCC_TOOLCHAIN'] = env['FREERTOS_EXEC_PATH']

    cmd = [MAKE, '-n', '-f', 'application.mk',
           'ROOT_DIR=' + SDK.replace('\\', '/'),
           'ENCRYPT=./tools/crc_binary/encrypt.exe', 'ENCRYPT_ARGS=',
           PROBE_TARGET]
    p = subprocess.run(cmd, cwd=SDK, env=env, capture_output=True, text=True,
                       errors='replace')
    line = None
    for l in p.stdout.splitlines():
        if 'arm-none-eabi-gcc' in l and '-c ' in l:
            line = l
            break
    if not line:
        print('!! 未能取得编译命令\n' + p.stdout[-2000:], file=sys.stderr)
        return 1

    dirs = []
    seen = set()
    for m in re.finditer(r'-I(\S+)', line):
        d = m.group(1)
        if d in seen:
            continue
        seen.add(d)
        dirs.append(d)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(dirs) + '\n')
    print('[gen] %d 个 include 目录 -> %s' % (len(dirs), os.path.relpath(OUT, ROOT)))
    print('[gen] 命令中原 -I 占用 %d 字符, 移除后命令长约 %d'
          % (sum(len(d) + 3 for d in dirs),
             len(line) - sum(len(d) + 3 for d in dirs)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
