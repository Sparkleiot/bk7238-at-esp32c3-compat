#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Raw TLS ClientHello sniffer: print exactly which cipher suites the module offers.

Listening as a plain TCP socket (no TLS) so we can parse the ClientHello ourselves.
Used to diagnose NO_SHARED_CIPHER against a local OpenSSL server.
"""
import socket
import struct
import sys

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8443

NAMES = {
    0x002F: 'TLS_RSA_WITH_AES_128_CBC_SHA',
    0x0035: 'TLS_RSA_WITH_AES_256_CBC_SHA',
    0x003C: 'TLS_RSA_WITH_AES_128_CBC_SHA256',
    0x009C: 'TLS_RSA_WITH_AES_128_GCM_SHA256',
    0x009D: 'TLS_RSA_WITH_AES_256_GCM_SHA384',
    0xC013: 'TLS_ECDHE_RSA_WITH_AES_128_CBC_SHA',
    0xC014: 'TLS_ECDHE_RSA_WITH_AES_256_CBC_SHA',
    0xC027: 'TLS_ECDHE_RSA_WITH_AES_128_CBC_SHA256',
    0xC028: 'TLS_ECDHE_RSA_WITH_AES_256_CBC_SHA384',
    0xC02F: 'TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256',
    0xC030: 'TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384',
    0xC023: 'TLS_ECDHE_ECDSA_WITH_AES_128_CBC_SHA256',
    0xC024: 'TLS_ECDHE_ECDSA_WITH_AES_256_CBC_SHA384',
    0xC02B: 'TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256',
    0xC02C: 'TLS_ECDHE_ECDSA_WITH_AES_256_GCM_SHA384',
    0xCCA8: 'TLS_ECDHE_RSA_WITH_CHACHA20_POLY1305_SHA256',
    0xCCA9: 'TLS_ECDHE_ECDSA_WITH_CHACHA20_POLY1305_SHA256',
    0xCCAA: 'TLS_DHE_RSA_WITH_CHACHA20_POLY1305_SHA256',
}

srv = socket.socket()
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(('0.0.0.0', PORT))
srv.listen(1)
srv.settimeout(40)
print('sniffer on :%d' % PORT)
try:
    c, addr = srv.accept()
except socket.timeout:
    print('no connection')
    sys.exit(1)

c.settimeout(5)
buf = b''
need = 5
while len(buf) < need:
    try:
        d = c.recv(4096)
    except socket.timeout:
        break
    if not d:
        break
    buf += d
    if len(buf) >= 5:
        need = 5 + struct.unpack('>H', buf[3:5])[0]
        # give it one extra read cycle so we don't parse a split record
        if len(buf) >= need:
            break

print('from %s:%d, %d bytes' % (addr[0], addr[1], len(buf)))
if len(buf) < 47:
    print('too short')
    sys.exit(1)

p = 0
rec_ver = struct.unpack('>H', buf[1:3])[0]
rec_type = buf[0]
rec_len = struct.unpack('>H', buf[3:5])[0]
# handshake header: type(1) + length(3), then ClientHello body
p = 5
hs_type = buf[p]
hs_len = int.from_bytes(buf[p + 1:p + 4], 'big')
p += 4
hs_ver = struct.unpack('>H', buf[p:p + 2])[0]
p += 2
p += 32  # random
sid_len = buf[p]
p += 1 + sid_len
if len(buf) < p + 2:
    print('!! truncated before cipher list (have %d, need %d)' % (len(buf), p + 2))
    sys.exit(1)
cs_len = struct.unpack('>H', buf[p:p + 2])[0]
p += 2
print('record ver=0x%04x type=%d len=%d | hs type=0x%02x len=%d | client ver=0x%04x | cs_list_len=%d | total=%d'
      % (rec_ver, rec_type, rec_len, hs_type, hs_len, hs_ver, cs_len, len(buf)))
if p + cs_len > len(buf):
    print('!! truncated: need %d bytes for cipher list, have %d'
          % (cs_len, len(buf) - p))
    sys.exit(1)
n = cs_len // 2
suites = struct.unpack('>%dH' % n, buf[p:p + cs_len])
print('offered %d cipher suite(s):' % n)
for s in suites:
    print('   0x%04X  %s' % (s, NAMES.get(s, '(unknown)')))
comp_len = struct.unpack('>H', buf[p + cs_len:p + cs_len + 2])[0] if len(buf) > p + cs_len + 2 else 0
p += cs_len + 2 + comp_len
if len(buf) > p + 2:
    ext_total = struct.unpack('>H', buf[p:p + 2])[0]
    p += 2
    end = p + ext_total
    print('extensions (%d bytes):' % ext_total)
    while p + 4 <= end:
        et, el = struct.unpack('>HH', buf[p:p + 4])
        body = buf[p + 4:p + 4 + el]
        nm = {0: 'server_name', 5: 'status_request', 10: 'supported_groups',
              11: 'ec_point_formats', 13: 'signature_algorithms',
              16: 'ALPN', 43: 'supported_versions', 45: 'psk_key_exchange_modes',
              51: 'key_share', 23: 'extended_master_secret'}.get(et, str(et))
        extra = ''
        if et == 10 and len(body) >= 2:
            gl = struct.unpack('>H', body[0:2])[0]
            groups = struct.unpack('>%dH' % (gl // 2), body[2:2 + gl])
            extra = ' groups=' + ','.join('%04X' % g for g in groups)
        if et == 43 and len(body) >= 1:
            vl = body[0]
            vers = struct.unpack('>%dH' % (vl // 2), body[1:1 + vl])
            extra = ' versions=' + ','.join('0x%04X' % v for v in vers)
        if et == 13 and len(body) >= 2:
            sl = struct.unpack('>H', body[0:2])[0]
            sigs = struct.unpack('>%dH' % (sl // 2), body[2:2 + sl])
            extra = ' sigs=' + ','.join('%04X' % s for s in sigs[:14])
        print('   ext %-4d %-26s len=%d%s' % (et, nm, el, extra))
        p += 4 + el
c.close()
srv.close()