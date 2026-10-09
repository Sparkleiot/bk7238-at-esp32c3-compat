import sys, time, serial
for port in ['COM5', 'COM6']:
    try:
        with serial.Serial(port, 115200, timeout=0.5) as ser:
            time.sleep(0.3)
            ser.reset_input_buffer()
            ser.write(b'AT\r\n')
            time.sleep(0.8)
            out = ser.read(200).decode('utf-8', 'replace').strip()
            print(f'{port}: {out!r}')
    except Exception as e:
        print(f'{port}: ERROR {e}')
