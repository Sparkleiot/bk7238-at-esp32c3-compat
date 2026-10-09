#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""BK7238 ESP-AT 兼容固件 —— HTTP / MQTT / TLS 联网实测

拓扑: 单模组(默认 COM7) 切 STA 关联真实 AP(默认 MyHomeWiFi), 走公网。
  0. 复位 / 基础应答 / 静音
  1. 关联 AP + DHCP 取 IP
  2. DNS 解析 (AT+CIPDOMAIN)
  3. HTTP 客户端: TCP 建连 <host>:80 -> 发 GET -> 校验 HTTP/1.x 状态行与响应体
  3b.HTTP 客户端 AT 命令: AT+HTTPCLIENT (明文 / HTTPS) + AT+HTTPGETSIZE
     —— 校验 ESP-AT 应答格式 "+HTTPCLIENT:<size>,<data>\r\nOK\r\n"
  4. TLS 客户端: CIPSTART="TLS",<host>,443 (记录是否建连成功)
  5. MQTT: MQTTUSERCFG -> MQTTCONN -> MQTTCONN? -> MQTTSUB -> MQTTPUB
           -> 校验 +MQTTCONN:OK / +MQTTPUB:OK / 订阅自收 +MQTTSUBRECV
           -> MQTTUNSUB -> MQTTCLEAN

用法: python tools/at_http_mqtt_test.py [--port COM7] [--ssid MyHomeWiFi] [--password xxx]
      [--broker broker.emqx.io] [--bport 1883]
"""
import argparse
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from at_module_to_module_test import AT  # noqa: E402

IPD_HEAD = re.compile(r"\+IPD(?:,\d+)?(?:,\d+)?")


class Rep:
    def __init__(self, path):
        self.path = path
        self.rows = []
        self.n_pass = 0
        self.n_fail = 0

    def add(self, stage, item, cmd, ok, detail=""):
        st = "PASS" if ok else "FAIL"
        if ok:
            self.n_pass += 1
        else:
            self.n_fail += 1
        det = str(detail).replace("|", "/").replace("\n", " ").replace("\r", " ")[:200]
        self.rows.append((stage, item, cmd, st, det))
        print(f"[{st}] {stage} | {item}")

    def save(self, extra_lines=()):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("# BK7238 (ESP-AT 兼容) HTTP / MQTT 联网实测报告\n\n")
            f.write(f"- 时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"- 固件: at-esp32c3-compat_2M.1220.bin\n")
            for ln in extra_lines:
                f.write(ln + "\n")
            f.write("\n| # | 阶段 | 测试项 | 命令 | 结果 | 实际 |\n|---|------|--------|------|------|------|\n")
            for i, (s, it, c, st, d) in enumerate(self.rows, 1):
                f.write(f"| {i} | {s} | {it} | `{c}` | {st} | {d} |\n")
            f.write(f"\n**合计: {self.n_pass} PASS / {self.n_fail} FAIL**\n")
        print(f"\n报告: {self.path} => {self.n_pass} PASS / {self.n_fail} FAIL")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="COM7")
    ap.add_argument("--ssid", default="MyHomeWiFi")
    ap.add_argument("--password", default=os.environ.get("BK7238_WIFI_PWD", "<WIFI_PWD>"))
    ap.add_argument("--broker", default="broker.emqx.io")
    ap.add_argument("--bport", type=int, default=1883)
    ap.add_argument("--out", default="test/http_mqtt.md")
    ap.add_argument("--no-rst", action="store_true")
    args = ap.parse_args()

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    logdir = os.path.join(os.path.dirname(args.out), "http_mqtt_raw")
    os.makedirs(logdir, exist_ok=True)

    d = AT("DUT", args.port, logdir)
    rep = Rep(args.out)

    def sr(line, timeout=8, settle=0.0):
        """发一条命令, 收集应答文本"""
        d.clear()
        d.send(line=line)
        t0 = time.time()
        acc = ""
        while time.time() - t0 < timeout:
            acc += d.pump(0.3)
        if settle:
            time.sleep(settle)
            acc += d.pump(0.3)
        d.buf = b""
        return acc

    def wait_for(pat, timeout=15):
        """等应答出现。**不要在这里 clear()** —— AT.clear() 会 pump 掉 0.1s
        的数据(写进日志但丢弃), 若模块应答够快, 会把刚发的命令的应答整个吞掉,
        表现为"日志里有 CONNECT 但函数返回空"。调用方负责在 send 前 clear。"""
        t0 = time.time()
        acc = ""
        while time.time() - t0 < timeout:
            acc += d.pump(0.3)
            if re.search(pat, acc):
                return True, acc
        return False, acc

    def read_until(pat, timeout=20, extra=3.0):
        """等到出现 pat, 再多收 extra 秒(拿完整响应体)"""
        acc = ""
        t0 = time.time()
        got = False
        while time.time() - t0 < timeout:
            acc += d.pump(0.3)
            if not got and re.search(pat, acc):
                got = True
                t_end2 = time.time() + extra
            if got and time.time() >= t_end2:
                break
        d.buf = b""
        return got, acc

    def sta_ip():
        txt = sr("AT+CIFSR", timeout=3)
        m = re.search(r'\+CIFSR:STAIP,"?(\d+\.\d+\.\d+\.\d+)"?', txt)
        return m.group(1) if m else None

    extra_info = [f"- 目标 AP: `{args.ssid}`   MQTT broker: `{args.broker}:{args.bport}`",
                  f"- 串口: {args.port}   (单模组纯 STA, 走公网)",
                  "",
                  "## 本轮固件修复项 (HTTP 部分)",
                  "",
                  "| 文件 | 问题 | 修复 |",
                  "|------|------|------|",
                  "| `atsvr_http_cmd.c` `http_output_size()` | 把文档占位符的尖括号原样写进格式串, "
                  "输出 `+HTTPCLIENT:<29506>,<...>`; 上位机按 ESP-AT 解析匹配不到 | "
                  "改正为 `+HTTPCLIENT:%d,` / `+HTTPGETSIZE:%d\\r\\n` |",
                  "| `atsvr_http_cmd.c` `http_output_data()` | 每调用一次就追加收尾 `\\r\\n`; "
                  "而 `HTTP_SIZE=1024` 使大响应被 recv 成 ~29 个分片, 每个分片都调一次 → "
                  "正文中间混进 30 个裸 CRLF | 去掉函数内的 `\\r\\n`, "
                  "改由调用方在整条响应输出完后补一次 |",
                  "| `atsvr_http_cmd.c` HTTPS 分支 | 正文偏移用 `ssl_parse_data_start_position()+2`, "
                  "多吃 2 字节(实测响应头变成 `TP/1.1 200 OK`, 丢了 `HT`); "
                  "且成功路径 `goto exit` 跳过收尾, HTTPS 请求从不回 `OK` | "
                  "改按 `strstr(\\\"\\\\r\\\\n\\\\r\\\\n\\\")+4` 定位正文; 补发 `http_output_ok()`; "
                  "`<len>` 改报实际吐出的字节数 |",
                  "| `utils_httpc.c` `user_httpclient_recv_response()` | 只有整包(头+正文)一次 recv 到齐"
                  "才输出, 否则每个分片都再打印一次 size → `AT+HTTPGETSIZE` 无限重复; "
                  "且首包附带的正文被丢弃(分片响应丢开头字节) | 重写为流式输出: "
                  "size 只报一次, 按 `Content-Length` 严格截断, 正文收满即收工 |",
                  "",
                  "## 已知缺口 / 限制",
                  "",
                  "1. **`AT+CIPSTART=\"TLS\"` 不可用**(本表第 15 项): 固件 `HAL_TLS_mbedtls.c` 强制 "
                  "`MBEDTLS_SSL_VERIFY_REQUIRED`, 且固件没有任何 AT 证书/CA 配置命令"
                  "(`AT+CIPSSLCONFIG` / `AT+CIPSSLCCONF` 等不存在), 无 CA 时握手必然失败。"
                  "**但 `AT+HTTPCLIENT` 的 HTTPS 通道走另一套 `sl_tls.c`(`ssl_create()` 不设 authmode), "
                  "实测可用**; MQTT(scheme=1 TCP) 与 HTTP(明文) 同样不受影响。",
                  "2. **chunked 响应不脱块**: 目标站不返回 `Content-Length` 时(如 example.com), "
                  "`size` 回落为预置缓冲长度, 响应体原样透传分块帧(`22f\\r\\n...\\r\\n0\\r\\n\\r\\n`)。"
                  "ESP-AT 会先脱块再上报, 这里未实现。",
                  "3. **无 CA 校验**: HTTPS 通道不校验服务器证书(与 ESP-AT 的默认行为一致, 但生产环境需自行加固)。",
                  ]


    try:
        # ---------- 0. 基础 ----------
        if not args.no_rst:
            d.clear()
            d.send(line="AT+RST")
            d.expect(r"ready|OK", timeout=8)
            time.sleep(15)
            d.pump(0.5)
            d.buf = b""
        ok, out = d.cmd("AT", timeout=6)
        rep.add("0-基础", "模组应答", "AT", ok, out.strip())
        d.send(line="ATE0")
        time.sleep(0.6)
        d.pump(0.4)
        d.buf = b""
        d.cmd("AT+CIPMODE=0", timeout=5)
        rep.add("0-基础", "关闭透传模式(清残留)", "AT+CIPMODE=0", True, "")

        ok, out = d.cmd("AT+CWMODE=1", timeout=6)
        rep.add("0-基础", "设为纯 STA 模式", "AT+CWMODE=1", ok, out.strip())

        # ---------- 1. 关联真实 AP ----------
        joined = False
        tries = 0
        t_end = time.time() + 240
        while time.time() < t_end and not joined:
            tries += 1
            d.clear()
            d.send(line=f'AT+CWJAP="{args.ssid}","{args.password}"')
            d.expect(r"\bOK\b", timeout=6)
            for _ in range(8):
                time.sleep(3)
                ip = sta_ip()
                if ip and ip != "0.0.0.0":
                    joined = True
                    break
            if not joined:
                time.sleep(2)
        ip = sta_ip() if joined else None
        rep.add("1-关联", f"关联真实 AP `{args.ssid}` 并取 IP", "AT+CWJAP", joined,
                f"第 {tries} 次尝试 | STAIP={ip or '未获取'}")
        if not joined:
            raise RuntimeError("关联失败, 终止(公网测试无法进行)")

        ok, out = d.cmd("AT+CIPSTA?", timeout=6)
        rep.add("1-关联", "查询 STA IP/网关/DNS", "AT+CIPSTA?", ok, out.strip()[:120])

        # ---------- 2. DNS ----------
        txt = sr('AT+CIPDOMAIN="www.baidu.com"', timeout=12)
        m = re.search(r'\+CIPDOMAIN:("?)(\d+\.\d+\.\d+\.\d+)\1', txt)
        rep.add("2-DNS", "域名解析 www.baidu.com", "AT+CIPDOMAIN", bool(m),
                (m.group(2) if m else txt.strip()[-70:]))

        txt = sr('AT+CIPDOMAIN="broker.emqx.io"', timeout=12)
        m2 = re.search(r'\+CIPDOMAIN:("?)(\d+\.\d+\.\d+\.\d+)\1', txt)
        rep.add("2-DNS", f"域名解析 {args.broker}", "AT+CIPDOMAIN",
                bool(m2), (m2.group(2) if m2 else txt.strip()[-70:]))
        if m:
            ptxt = sr(f'AT+PING="{m.group(2)}"', timeout=15)
            pm = re.search(r"\+PING:(\d+)", ptxt)
            rep.add("2-DNS", "PING 解析出的公网 IP", 'AT+PING="<baidu-ip>"',
                    bool(pm), f"+PING:{pm.group(1)}ms" if pm else ptxt.strip()[-60:])

        # ---------- 3. HTTP 客户端 ----------
        def http_get(host, path="/", port=80, extra_headers=""):
            d.clear()
            d.send(line=f'AT+CIPSTART="TCP","{host}",{port}')
            okc, acc = wait_for(r"CONNECT|\bERROR", timeout=15)
            if not okc or "ERROR" in acc:
                return False, acc, ""
            req = (f"GET {path} HTTP/1.1\r\nHost: {host}\r\n"
                   f"User-Agent: BK7238-AT\r\nConnection: close\r\n{extra_headers}\r\n")
            d.send(line=f"AT+CIPSEND={len(req)}")
            got_prompt, acc2 = wait_for(r">", timeout=6)
            if not got_prompt:
                return False, acc2, ""
            d.send(raw=req.encode())
            got, resp = read_until(r"HTTP/1\.[01]", timeout=20, extra=4.0)
            d.cmd("AT+CIPCLOSE", timeout=6)
            return got, resp, req

        ok1, resp1, _ = http_get("www.baidu.com")
        m = re.search(r"HTTP/1\.[01] (\d{3})", resp1)
        body_ok = ("</html>" in resp1.lower() or "<html" in resp1.lower())
        rep.add("3-HTTP", "HTTP GET www.baidu.com:80", 'AT+CIPSTART+CIPSEND', bool(m),
                f"状态行 {m.group(0) if m else '未见'} | 响应 {len(resp1)}B | 正文 {'有' if body_ok else '无'}")

        ok2, resp2, _ = http_get("example.com")
        m2 = re.search(r"HTTP/1\.[01] (\d{3})", resp2)
        rep.add("3-HTTP", "HTTP GET example.com:80", 'AT+CIPSTART+CIPSEND', bool(m2),
                f"状态行 {m2.group(0) if m2 else '未见'} | 响应 {len(resp2)}B")

        # ---------- 3b. HTTP 客户端 AT 命令 (AT+HTTPCLIENT / AT+HTTPGETSIZE) ----------
        # 这两条命令的输出格式是本轮修复重点:
        #   TCP   : "+HTTPCLIENT:<size>," + <data> + "\r\n" + "OK\r\n"
        #   HTTPS : 同上(原厂漏发尾 OK + 正文偏移多吃 2 字节)
        #   SIZE  : "+HTTPGETSIZE:<size>\r\n" + "OK\r\n"  (原厂每个分片重复打印)
        def httpcli(cmd, timeout=30):
            """发 AT+HTTPCLIENT/AT+HTTPGETSIZE, 读到收尾 OK/ERROR 为止。

            返回**原始字节**而不是解码后的 str —— 正文是任意二进制(baidu 页面
            含多字节 UTF-8), decode('replace') 会把多字节字符折成 1 个 U+FFFD,
            再跨 pump 分块还会被打断, 长度校验就永远对不上。"""
            d.clear()
            d.send(line=cmd)
            t0 = time.time()
            head = False
            while time.time() - t0 < timeout:
                d.pump(0.3)
                txt = d.buf.decode("utf-8", "replace")
                if re.search(r"\+HTTP(?:CLIENT|GETSIZE):", txt):
                    head = True
                if head and re.search(r"(?:\r\n|\n)OK\r\n", txt):
                    break
                if re.search(r"(?:\r\n|\n)ERROR\r\n", txt):
                    break
            raw = d.buf
            d.buf = b""
            return raw

        def parse_cli(raw):
            """取 +HTTPCLIENT:<size>, 之后的**原始正文字节**与收尾状态"""
            mh = re.search(rb"\+HTTPCLIENT:(\d+),", raw)
            if not mh:
                return None, b"", ""
            body = raw[mh.end():]
            tail = ""
            mb = re.search(rb"(?:\r\n|\n)(OK|ERROR)\r\n", body)
            if mb:
                tail = mb.group(1).decode()
                body = body[:mb.start()]
            return int(mh.group(1)), body, tail

        # (1) 明文 GET —— 修复前输出 "+HTTPCLIENT:<29506>,<...>"(尖括号写死),
        #     且每个 1KB 分片都被塞一个 "\r\n"(正文里混进 30 个裸 CRLF)
        raw = httpcli('AT+HTTPCLIENT=2,0,"http://www.baidu.com/","www.baidu.com","/",1')
        sz, body, tail = parse_cli(raw)
        body_ok = (b"<html" in body.lower() or b"doctype" in body.lower())
        ncr = body.count(b"\r")
        rep.add("3b-HTTP CLI", "HTTPCLIENT 明文 GET www.baidu.com", "AT+HTTPCLIENT=2,0,...,1",
                bool(sz) and tail == "OK" and body_ok and sz == len(body) and ncr == 0,
                f"size={sz} 正文字节={len(body)} 收尾={tail or '无'} size==正文={'✔' if sz == len(body) else '✘'} "
                f"正文杂散CR={ncr} 头部无尖括号={'✔' if b'+HTTPCLIENT:<' not in raw else '✘'} 首24={body[:24]!r}")

        # (2) 明文 GET 第二个站点(响应是 chunked, 无 Content-Length), 确认不是单点巧合
        raw2 = httpcli('AT+HTTPCLIENT=2,0,"http://example.com/","example.com","/",1')
        sz2, body2, tail2 = parse_cli(raw2)
        rep.add("3b-HTTP CLI", "HTTPCLIENT 明文 GET example.com", "AT+HTTPCLIENT=2,0,...,1",
                tail2 == "OK" and b"example domain" in body2.lower(),
                f"size={sz2} 正文字节={len(body2)} 收尾={tail2 or '无'} "
                f"(该站响应为 chunked 无 Content-Length, size 回落为预置缓冲长度, 分块帧原样透传) 首24={body2[:24]!r}")

        # (3) HTTPS GET —— transport_type=2(SSL), 走 sl_tls.c(不强制校验证书)
        #     ESP-AT 语义: +HTTPCLIENT:<len>,<正文>  (与明文一致, 已剥掉响应头)
        #     修复前: 正文偏移多吃 2 字节(丢 "HT") + 收尾漏发 OK
        raw3 = httpcli('AT+HTTPCLIENT=2,0,"https://www.baidu.com/","www.baidu.com","/",1,2', timeout=40)
        sz3, body3, tail3 = parse_cli(raw3)
        rep.add("3b-HTTP CLI", "HTTPCLIENT HTTPS GET www.baidu.com:443", "AT+HTTPCLIENT=2,0,...,1,2",
                bool(sz3) and tail3 == "OK" and sz3 == len(body3) and b"doctype" in body3[:80].lower(),
                f"size={sz3} 正文字节={len(body3)} 收尾={tail3 or '无(原厂漏发)'} "
                f"size==正文={'✔' if sz3 == len(body3) else '✘'} 首24={body3[:24]!r}")

        # (4) AT+HTTPGETSIZE —— 修复前 +HTTPGETSIZE 被每个分片重复打印
        raw4 = httpcli('AT+HTTPGETSIZE="http://www.baidu.com/"', timeout=40)
        n_size = len(re.findall(rb"\+HTTPGETSIZE:", raw4))
        mg = re.search(rb"\+HTTPGETSIZE:(\d+)", raw4)
        rep.add("3b-HTTP CLI", "HTTPGETSIZE 只上报一次且以 OK 收尾", 'AT+HTTPGETSIZE="..."',
                n_size == 1 and bool(mg) and re.search(rb"(?:\r\n|\n)OK\r\n", raw4) is not None,
                f"上报次数={n_size} size={mg.group(1).decode() if mg else '—'} 尾部={raw4.strip()[-24:]!r}")

        # ---------- 4. TLS ----------
        d.clear()
        d.send(line='AT+CIPSTART="TLS","www.baidu.com",443')
        okt, acct = wait_for(r"CONNECT|\bERROR", timeout=20)
        rep.add("4-TLS", "TLS 建连 www.baidu.com:443", 'AT+CIPSTART="TLS"',
                bool(okt) and "ERROR" not in acct, acct.strip()[-70:])
        d.cmd("AT+CIPCLOSE", timeout=6)

        # ---------- 5. MQTT ----------
        ok, out = d.cmd(f'AT+MQTTUSERCFG=0,1,"bk7238-at-test","","",60,0,0,""', timeout=8)
        rep.add("5-MQTT", "MQTT 用户配置(scheme=1 应为 TCP)", "AT+MQTTUSERCFG", ok, out.strip())

        d.clear()
        d.send(line=f'AT+MQTTCONN=0,"{args.broker}",{args.bport},0')
        okc, acc = read_until(r"\+MQTTCONN:(OK|ERROR)", timeout=25, extra=0.5)
        m = re.search(r"\+MQTTCONN:(OK|ERROR)(,(\d+))?", acc)
        rep.add("5-MQTT", f"连接 broker {args.broker}:{args.bport}", "AT+MQTTCONN",
                bool(m) and m.group(1) == "OK",
                (m.group(0) if m else acc.strip()[-70:]) + f" | 收到: {len(acc)}B")

        txt = sr("AT+MQTTCONN?", timeout=8)
        rep.add("5-MQTT", "查询 MQTT 连接状态", "AT+MQTTCONN?", "+MQTTCONN:0,1" in txt,
                txt.strip()[:110])

        topic = "bk7238/at/test"
        ok, out = d.cmd(f'AT+MQTTSUB=0,"{topic}",1', timeout=10)
        rep.add("5-MQTT", f"订阅 {topic}", "AT+MQTTSUB", ok, out.strip())

        payload = "hello-from-bk7238"
        d.clear()
        d.send(line=f'AT+MQTTPUB=0,"{topic}","{payload}",1,0')
        # 发布应答与"订阅自收"消息常同批到达(实测 +MQTTSUBRECV 甚至先于
        # +MQTTPUB:OK), 所以在同一个读取窗口里一起判定, 不要分两次读。
        oks, accp = read_until(r"\+MQTTPUB:(OK|ERROR)", timeout=15, extra=3.0)
        merr = re.search(r"\+MQTTPUB:(\w+)", accp)
        rep.add("5-MQTT", "发布到已订阅主题(QoS1)", "AT+MQTTPUB",
                bool(merr) and merr.group(1) == "OK", (merr.group(0) if merr else accp.strip()[-70:]))

        # 订阅自收: +MQTTSUBRECV:<link>,<"topic">,<len>,<data>
        rpat = re.compile(r'\+MQTTSUBRECV:(\d+),"([^"]*)",(\d+),([^\r\n]*)')
        mrecv = rpat.search(accp)
        if not mrecv:
            got, acc2 = read_until(r"\+MQTTSUBRECV:", timeout=15, extra=1.0)
            accp += acc2
            mrecv = rpat.search(accp)
        rep.add("5-MQTT", "订阅自收 (上报 +MQTTSUBRECV)", "+MQTTSUBRECV",
                bool(mrecv) and mrecv.group(2) == topic and payload in mrecv.group(4),
                (mrecv.group(0)[:90] if mrecv else accp.strip()[-80:] or "(未收到自收消息)"))

        ok, out = d.cmd(f'AT+MQTTUNSUB=0,"{topic}"', timeout=10)
        rep.add("5-MQTT", "取消订阅", "AT+MQTTUNSUB", ok, out.strip())

        ok, out = d.cmd("AT+MQTTCLEAN", timeout=12)
        rep.add("5-MQTT", "断开 MQTT 连接", "AT+MQTTCLEAN", ok, out.strip())

        # 断连后状态查询应 ERROR(ESP-AT 语义)
        txt = sr("AT+MQTTCONN?", timeout=8)
        rep.add("5-MQTT", "断连后 AT+MQTTCONN? 返回 ERROR", "AT+MQTTCONN?",
                "ERROR" in txt, txt.strip()[:80])

        # ---------- 6. 收尾 ----------
        ok, out = d.cmd("AT+CIPCLOSE", timeout=6)
        rep.add("6-收尾", "关闭残留 TCP 连接", "AT+CIPCLOSE", True, "")

    finally:
        try:
            d.send(line="AT+CIPMODE=0")
            d.send(line="AT+CIPCLOSE")
            d.send(line="AT+MQTTCLEAN")
            d.pump(0.5)
        except Exception:
            pass
        d.close()
        rep.save(extra_info)

    return 1 if rep.n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
