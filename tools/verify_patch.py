#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Verify docs/patches/esp32c3-compat.patch applies cleanly to a pristine tree.

Materialises each patched path from src/vendor-pristine/<basename>.orig into a
temp tree, then runs `patch --binary -p1 --dry-run` there.

--binary is mandatory: the SDK tree is CRLF and MSYS/Git-Bash patch otherwise
does CRLF<->LF conversion and every hunk "fails (different line endings)".
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATCH = os.path.join(ROOT, 'docs', 'patches', 'esp32c3-compat.patch')
PRISTINE = os.path.join(ROOT, 'src', 'vendor-pristine')

with open(PATCH, 'r', encoding='utf-8', errors='replace') as fh:
    body = fh.read()

paths = []
for m in re.finditer(r'^--- a/(\S+)', body, re.M):
    p = m.group(1)
    if p not in paths:
        paths.append(p)

print('patch references %d file(s)' % len(paths))

tmp = tempfile.mkdtemp(prefix='bkverify_')
try:
    missing = []
    for p in paths:
        base = os.path.basename(p)
        src = os.path.join(PRISTINE, base + '.orig')
        if not os.path.exists(src):
            missing.append((p, src))
            continue
        dst = os.path.join(tmp, p.replace('/', os.sep))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
    if missing:
        for p, s in missing:
            print('  !! no vendor-pristine for %s (%s)' % (p, s))
        sys.exit('cannot build pristine tree')

    print('pristine tree built at %s' % tmp)
    r = subprocess.run(['patch', '--binary', '-p1', '--dry-run', '--forward', '-i', PATCH],
                       cwd=tmp, capture_output=True, text=True)
    out = (r.stdout or '') + (r.stderr or '')
    tail = [ln for ln in out.splitlines()
            if ln.strip() and not ln.startswith('patching file') and 'Hmgr' not in ln]
    print('--- patch --dry-run rc=%d ---' % r.returncode)
    for ln in out.splitlines():
        if ln.startswith('patching file'):
            continue
        if ln.strip():
            print('  ' + ln)
    # also run for real into a throwaway copy to prove the result is byte-identical
    print()
    real = subprocess.run(['patch', '--binary', '-p1', '--forward', '-i', PATCH],
                          cwd=tmp, capture_output=True, text=True)
    print('--- real apply rc=%d ---' % real.returncode)
    if real.returncode != 0:
        print((real.stdout or '') + (real.stderr or ''))
        sys.exit('patch does not apply')

    # compare each patched file against src/modified/
    import shlex
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import gen_patch
    patched = set(paths)
    bad = []
    n_cmp = 0
    for name, rel in gen_patch.FILES.items():
        if rel not in patched:
            print('  (no diff, not in patch: %s)' % name)
            continue
        got = os.path.join(tmp, rel.replace('/', os.sep))
        want = os.path.join(ROOT, 'src', 'modified', name)
        with open(got, 'rb') as f1, open(want, 'rb') as f2:
            if f1.read() != f2.read():
                bad.append(name)
        n_cmp += 1
    print()
    print('compared %d patched file(s) against src/modified/' % n_cmp)
    if bad:
        print('!! patched output differs from src/modified/: %s' % ', '.join(bad))
        sys.exit(1)
    print('== patch applies cleanly and reproduces src/modified/ byte-for-byte ==')
finally:
    shutil.rmtree(tmp, ignore_errors=True)