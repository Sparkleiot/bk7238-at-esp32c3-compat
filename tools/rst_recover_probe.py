"""干净探测：每次只发一条 AT，量AT+RST 之后 AT 恢复应答需要多久。

⚠ 为什么必须"每次只发一条"（2026-10-09 踩过，这是个会把固件误判成故障的陷阱）：
早先的探测脚本每0.6s 就往串口塞一条 `AT`，模组 UART 任务来不及消费，
回显队列溢出后 `AT` 回 `ERROR`（实测一次读到 17 个回显 + ERROR），
于是"越探测越测不出来"——一度误判 COM6 复位后 240s不应答、疑似死机。
用干净单次探测复测，实际是 `AT+RST` 应答 2.1s、AT 完全恢复 5.2s，完全正常。

**测"复位后多久恢复"永远只发一条命令，读完再发下一条。**

用法:
    python tools/rst_recover_probe.py COM6
"""
import serial, time, sys
port = sys.argv[1] if len(sys.argv) > 1 else 'COM6'
s = serial.Serial(port, 115200, timeout=0.1)
time.sleep(0.4)

def probe(wait=3.0):
    """发一条 AT, 等 wait 秒, 判断有无 OK。返回 True/False"""
    s.reset_input_buffer()
    s.write(b'AT\r\n')
    time.sleep(wait)
    d = s.read(4096)
    return b'OK' in d, d

# 先排空可能残留的回显
time.sleep(1.0); s.reset_input_buffer()

print('=== 发 AT+RST，然后每次只发一条 AT 探测 ===', flush=True)
s.reset_input_buffer()
s.write(b'AT+RST\r\n')
t0 = time.time()
ok, d = probe(2.0)
print('%6.2fs  RST 本身应答=%s %r' % (time.time()-t0, ok, d[:40]), flush=True)

for i in range(30):
    ok, d = probe(3.0)
    el = time.time()-t0
    if ok:
        print('%6.2fs  >>> AT 恢复应答（探测 %d 次）' % (el, i+1), flush=True)
        break
    print('%6.2fs  探测 %d: 无 OK, 读到 %d 字节 %r' % (el, i+1, len(d), d[:40]), flush=True)
else:
    print('%6.2fs  30 次探测（约 90s）始终无 OK' % (time.time()-t0), flush=True)
s.close()
