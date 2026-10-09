import sys, time, serial
PORT = sys.argv[1] if len(sys.argv) > 1 else 'COM3'
with serial.Serial(PORT, 115200, timeout=0.1) as ser:
    time.sleep(0.3)
    ser.reset_input_buffer()
    ser.write(b'AT+RST\r\n')
    t0 = time.time(); buf = b''
    while time.time() - t0 < 12:
        n = ser.in_waiting
        if n: buf += ser.read(n)
        else: time.sleep(0.05)
    print(buf.decode('utf-8', 'replace'))
