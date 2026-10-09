"""SoftAP verification for BK7238 ESP-AT compat firmware.
Usage: python ap_check.py COM3
"""
import sys, time, serial

PORT = sys.argv[1] if len(sys.argv) > 1 else 'COM3'

def send(ser, cmd, wait=1.0, expect_lines=None):
    ser.reset_input_buffer()
    ser.write((cmd + '\r\n').encode())
    t0 = time.time()
    buf = b''
    while time.time() - t0 < wait:
        n = ser.in_waiting
        if n:
            buf += ser.read(n)
        else:
            time.sleep(0.05)
    return buf.decode('utf-8', 'replace')

with serial.Serial(PORT, 115200, timeout=0.1) as ser:
    time.sleep(0.3)
    tests = [
        ('AT', 0.5),
        ('AT+CWMODE?', 1.0),
        ('AT+CWSAP?', 1.0),
        ('AT+CWSAP_DEF?', 1.0),
        ('AT+CWLIF', 2.0),
        ('AT+CIPAP?', 1.0),
    ]
    for cmd, w in tests:
        out = send(ser, cmd, w)
        print(f'--- {cmd} ---')
        print(out.strip() or '<no response>')
    # force mode 3
    out = send(ser, 'AT+CWMODE=3', 1.5)
    print('--- AT+CWMODE=3 ---'); print(out.strip())
    time.sleep(2)
    out = send(ser, 'AT+CWSAP?', 1.5)
    print('--- AT+CWSAP? (after mode 3) ---'); print(out.strip())
    out = send(ser, 'AT+CWMODE?', 1.0)
    print('--- AT+CWMODE? ---'); print(out.strip())
