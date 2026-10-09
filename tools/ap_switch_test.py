"""Verify runtime CWMODE switching starts/stops SoftAP without reboot."""
import sys, time, serial
PORT = 'COM5'

def send(ser, cmd, wait=1.5):
    ser.reset_input_buffer()
    ser.write((cmd + '\r\n').encode())
    t0 = time.time(); buf = b''
    while time.time() - t0 < wait:
        n = ser.in_waiting
        if n: buf += ser.read(n)
        else: time.sleep(0.05)
    return buf.decode('utf-8', 'replace').strip()

with serial.Serial(PORT, 115200, timeout=0.1) as ser:
    time.sleep(0.3)
    print('GMR:', send(ser, 'AT+GMR', 1.5)[:120])
    print('CWSAP?:', send(ser, 'AT+CWSAP?', 1.5))
    print('CWSAP_CUR?:', send(ser, 'AT+CWSAP_CUR?', 1.5))
    print('CWMODE=1:', send(ser, 'AT+CWMODE=1', 2.0))
    print('>>> scan now (AP should be GONE)')
    time.sleep(8)   # give PC time to scan in parallel? no - caller scans after
    print('CWMODE=3:', send(ser, 'AT+CWMODE=3', 2.0))
    print('>>> scan now (AP should be BACK, no reboot)')
    time.sleep(3)
    print('CWSAP? after:', send(ser, 'AT+CWSAP?', 1.5))
