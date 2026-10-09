#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Check that src/modified/ is in sync with the SDK working tree.

The mapping is parsed straight out of src/apply.sh so there is a single source of
truth. Any file that differs means an SDK edit was never copied back into
src/modified/ -- running src/apply.sh would silently revert it.
"""
import os
import re
import shlex
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'src')          # $HERE in apply.sh == src/
APPLY = os.path.join(SRC, 'apply.sh')
MODIFIED = os.path.join(SRC, 'modified')
SDK = os.path.join(ROOT, 'sdk', 'BK7238-AT')
BK = os.path.join(SDK, 'beken378')

pairs = []
with open(APPLY, 'r', encoding='utf-8', errors='replace') as fh:
    for line in fh:
        line = line.strip()
        if not line.startswith('cp '):
            continue
        toks = shlex.split(line)
        if len(toks) < 3:
            continue
        src = toks[1]
        dst = toks[2]
        if '$HERE' not in src or '$BK' not in dst:
            continue
        pairs.append((src.replace('$HERE', SRC).replace('"', ''),
                      dst.replace('$BK', BK).replace('"', '')))

print('parsed %d copy rules from src/apply.sh' % len(pairs))
drift = []
for s, d in pairs:
    name = os.path.basename(s)
    if not os.path.exists(s):
        print('  MISSING modified: %s' % name)
        drift.append((name, 'missing-in-modified'))
        continue
    if not os.path.exists(d):
        print('  MISSING sdk    : %s  -> %s' % (name, d))
        drift.append((name, 'missing-in-sdk'))
        continue
    with open(s, 'rb') as f1, open(d, 'rb') as f2:
        b1, b2 = f1.read(), f2.read()
    if b1 == b2:
        print('  OK        %s' % name)
    else:
        # tolerate CRLF vs LF only differences
        if b1.replace(b'\r\n', b'\n') == b2.replace(b'\r\n', b'\n'):
            print('  EOL-ONLY  %s  (content identical, line endings differ)' % name)
        else:
            nb = sum(1 for x, y in zip(b1.replace(b'\r\n', b'\n').split(b'\n'),
                                        b2.replace(b'\r\n', b'\n').split(b'\n')) if x != y)
            print('  DRIFT     %s  (%d bytes vs %d bytes, ~%d differing lines)'
                  % (name, len(b1), len(b2), nb))
            drift.append((name, 'content-differs'))

print()
if drift:
    print('!! %d file(s) OUT OF SYNC -- running src/apply.sh would revert them:' % len(drift))
    for n, why in drift:
        print('   - %s (%s)' % (n, why))
    sys.exit(1)
print('== src/modified/ is in sync with the SDK tree ==')