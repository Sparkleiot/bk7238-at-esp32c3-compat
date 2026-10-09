#!/usr/bin/env python3
"""粗略解析 PE 依赖 DLL / 架构，用于诊断 Windows 可执行文件无法启动的问题。"""
import struct
import sys


def main(path):
    f = open(path, 'rb').read()
    pe = struct.unpack_from('<I', f, 0x3c)[0]
    if f[pe:pe + 4] != b'PE\x00\x00':
        print('not PE')
        return
    mach = struct.unpack_from('<H', f, pe + 4)[0]
    print('machine=0x%04x (%s)' % (mach, {0x14c: 'i386', 0x8664: 'x64', 0x1c0: 'arm', 0x1c4: 'armnt'}.get(mach, '?')))
    nsec = struct.unpack_from('<H', f, pe + 6)[0]
    optsz = struct.unpack_from('<H', f, pe + 20)[0]
    opt = pe + 24
    magic = struct.unpack_from('<H', f, opt)[0]
    print('optmagic=0x%04x (%s)' % (magic, {0x10b: 'PE32', 0x20b: 'PE32+'}.get(magic, '?')))
    dd = opt + (96 if magic == 0x10b else 112)
    imp_rva, imp_sz = struct.unpack_from('<II', f, dd + 8)

    sh = pe + 24 + optsz
    secs = []
    for i in range(nsec):
        o = sh + i * 40
        name = f[o:o + 8].rstrip(b'\x00').decode(errors='replace')
        vsz, va, rsz, ra = struct.unpack_from('<IIII', f, o + 8)
        secs.append((va, vsz, ra, rsz, name))

    def r2o(rva):
        for va, vsz, ra, rsz, name in secs:
            if va <= rva < va + max(vsz, rsz):
                return ra + (rva - va)
        return None

    o = r2o(imp_rva)
    if o is None:
        print('no import table')
        return
    dlls = []
    while True:
        ent = f[o:o + 20]
        if len(ent) < 20 or ent == b'\x00' * 20:
            break
        namerva = struct.unpack_from('<I', ent, 12)[0]
        if namerva == 0:
            break
        no = r2o(namerva)
        dlls.append(f[no:f.index(b'\x00', no)].decode(errors='replace'))
        o += 20
    print('DLLs:', dlls)


if __name__ == '__main__':
    main(sys.argv[1])
