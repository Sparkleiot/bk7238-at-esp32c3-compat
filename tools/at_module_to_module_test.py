#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""BK7238 双模组 (模组对模组) TCP/UDP 透传联调

拓扑:
  COM7 = AP 模组  (SoftAP "BK-M2M", WPA2) + TCP/UDP 服务端 (CIPSERVER)
  COM5 = STA 模组 (关联 BK-M2M) + TCP/UDP 客户端 (CIPSTART)

场景:
  1. AP 广播验证 (COM5 做 AT+CWLAP 扫描, 验证运行时 CWMODE 切换修复)
  2. TCP 普通模式: 双向 CIPSEND / +IPD / CONNECT/CLOSED 事件
  3. TCP 透传: CIPMODE=1 + CIPSEND(无参) 裸收发 + +++ 退出
  4. UDP 普通模式: CIPSERVER UDP 对端学习 + 双向收发
  5. UDP 透传: CIPMODE=1 + UDP CIPSEND 裸收发

用法: python tools/at_module_to_module_test.py [--ap COM6] [--sta COM5] [--out test/module_to_module.md]
"""
import argparse
import os
import re
import sys
import time

import serial

AP_SSID = "BK-M2M"
AP_PWD = "12345678"
TCP_PORT = 8260
UDP_PORT = 8261

# SoftAP 加密方式 (ESP-AT ecn: 0=OPEN 2=WPA_PSK 3=WPA2_PSK 4=WPA_WPA2_PSK)
# 注意: 实测本固件的 SoftAP 目前只在 OPEN(0) 下能稳定完成关联,
# ecn=2/3/4 时 AP 侧 hostapd 会在 sta_add 后立刻拆链(AP_CONNECT_FAILED),
# 从未发出 EAPOL-Key 1/4。故默认走 0, 可用 --ecn 覆盖做对照。
AP_ECN = 0

# +IPD 头 (兼容单连接 +IPD,len: 与多连接 +IPD,id,len: 两种格式)
IPD_HEAD = re.compile(r"\+IPD(?:,\d+)?(?:,\d+)?:")


class AT:
    def __init__(self, name, port, logdir):
        self.name = name
        self.ser = serial.Serial(port, 115200, timeout=0.05)
        self.buf = b""
        self.log = open(os.path.join(logdir, f"{name}.log"), "wb")

    def close(self):
        try:
            self.ser.close()
        finally:
            self.log.close()

    def pump(self, dur=0.2):
        """读 dur 秒内的所有输出, 记入日志, 返回增量文本"""
        t0 = time.time()
        inc = b""
        while time.time() - t0 < dur:
            n = self.ser.in_waiting
            if n:
                data = self.ser.read(n)
                inc += data
                self.log.write(data)
                self.log.flush()
            else:
                time.sleep(0.02)
        self.buf += inc
        return inc.decode("utf-8", "replace")

    def clear(self):
        self.pump(0.1)
        self.buf = b""

    def send(self, line=None, raw=None):
        assert (line is None) != (raw is None)
        if line is not None:
            data = (line + "\r\n").encode()
        else:
            data = raw
        self.log.write(b"\n>>> SEND: " + data + b"\n")
        self.ser.write(data)

    def expect(self, pattern, timeout=10):
        """在累计缓冲里找 regex, 找到返回 match 及之前的全部文本"""
        rx = re.compile(pattern.encode() if isinstance(pattern, str) else pattern)
        t0 = time.time()
        while time.time() - t0 < timeout:
            m = rx.search(self.buf)
            if m:
                consumed = self.buf[: m.end()]
                self.buf = self.buf[m.end():]
                return consumed.decode("utf-8", "replace")
            self.pump(0.2)
        return None

    def cmd(self, line, ok_pat=r"\bOK\r?\n", err_pat=r"\bERROR", timeout=8):
        """发命令: 先等回显, 只把回显之后的应答算作本命令结果(防误吃异步事件)"""
        self.clear()
        self.send(line=line)
        self.expect(re.escape(line), timeout=5)  # 等回显; 失败也继续
        t0 = time.time()
        while time.time() - t0 < timeout:
            text = self.buf.decode("utf-8", "replace")
            if re.search(ok_pat, text):
                time.sleep(0.1)
                self.pump(0.2)
                text = self.buf.decode("utf-8", "replace")
                self.buf = b""
                return True, text
            if re.search(err_pat, text):
                self.buf = b""
                return False, text
            self.pump(0.2)
        text = self.buf.decode("utf-8", "replace")
        self.buf = b""
        return False, text

    def recv_payload(self, payload, timeout=8):
        """等接收侧收齐 payload (容忍 +IPD 分块/多个 +IPD 头)"""
        t0 = time.time()
        acc = ""
        while time.time() - t0 < timeout:
            acc += self.pump(0.3)
            if payload in IPD_HEAD.sub("", acc):
                return True, acc
        return False, acc


class Report:
    def __init__(self, path, ap_port="?", sta_port="?"):
        self.path = path
        self.ap_port = ap_port
        self.sta_port = sta_port
        self.rows = []
        self.n_pass = 0
        self.n_fail = 0

    def add(self, stage, item, cmd, ok, detail):
        status = "PASS" if ok else "FAIL"
        if ok:
            self.n_pass += 1
        else:
            self.n_fail += 1
        self.rows.append((stage, item, cmd, status, detail.replace("|", "/").replace("\n", " ⏎ ")))
        print(f"[{status}] {stage} | {item}")

    def save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("# BK7238 模组对模组 TCP/UDP 透传联调报告\n\n")
            f.write(f"- 时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"- AP 模组: {self.ap_port} (SoftAP `{AP_SSID}`), STA 模组: {self.sta_port}\n")
            f.write(f"- 固件: at-esp32c3-compat_2M.1220.bin (同版双模组)\n\n")
            f.write("| # | 阶段 | 测试项 | 命令 | 结果 | 实际 |\n|---|------|--------|------|------|------|\n")
            for i, (stage, item, cmd, st, det) in enumerate(self.rows, 1):
                f.write(f"| {i} | {stage} | {item} | `{cmd}` | {st} | {det} |\n")
            f.write(f"\n**合计: {self.n_pass} PASS / {self.n_fail} FAIL**\n")
        print(f"\n报告: {self.path}  =>  {self.n_pass} PASS / {self.n_fail} FAIL")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ap", default="COM7", help="AP 模组串口")
    ap.add_argument("--sta", default="COM5", help="STA 模组串口")
    ap.add_argument("--out", default="test/module_to_module.md")
    ap.add_argument("--ecn", type=int, default=AP_ECN,
                    help="SoftAP 加密方式 (0=OPEN, 2/3/4=WPA*; 默认 0)")
    ap.add_argument("--ch", type=int, default=8,
                    help="SoftAP 信道 (默认 8; 信道 1 与环境里真实 AP 同频干扰, 关联会持续超时)")
    ap.add_argument("--no-rst", action="store_true",
                    help="跳过测前 AT+RST (默认双模组复位, 走上电干净路径)")
    args = ap.parse_args()

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    logdir = os.path.join(os.path.dirname(args.out), "m2m_raw")
    os.makedirs(logdir, exist_ok=True)

    apm = AT("AP", args.ap, logdir)
    stm = AT("STA", args.sta, logdir)
    rep = Report(args.out, args.ap, args.sta)

    def exit_passthrough(at):
        """+++ 退出透传(带 1s 前后静默)"""
        time.sleep(1.2)
        at.send(raw=b"+++")
        time.sleep(1.2)
        at.pump(0.3)

    def cleanup_links():
        """两模组清残留链路"""
        for at in (stm, apm):
            at.cmd("AT+CIPCLOSE", timeout=4)
            at.cmd("AT+CIPSERVER=0", timeout=6)

    def sr(port, line, timeout=6):
        """发一条命令并收集应答文本（丢掉之前缓冲）"""
        port.clear()
        port.send(line=line)
        t0 = time.time()
        acc = ""
        while time.time() - t0 < timeout:
            acc += port.pump(0.3)
        port.buf = b""
        return acc

    def sta_ip():
        txt = sr(stm, "AT+CIFSR", 3)
        m = re.search(r'\+CIFSR:STAIP,"?(\d+\.\d+\.\d+\.\d+)"?', txt)
        return m.group(1) if m else None

    def join_ap(timeout=300):
        """关联 AP。判定只认 AT+CIFSR 里的 STAIP ——
        事件文本 "WIFI GOT IP" 会被其它线程的日志按字节打断, 不可靠。
        实测本固件首次关联很慢(前几次 AUTH 没人应), 所以循环重发 CWJAP。"""
        attempt = 0
        t_end = time.time() + timeout
        while time.time() < t_end:
            attempt += 1
            stm.clear()
            stm.send(line=f'AT+CWJAP="{AP_SSID}","{AP_PWD}"')
            stm.expect(r"\bOK\b", timeout=6)
            for _ in range(8):          # 每轮给它 ~24s
                time.sleep(3)
                ip = sta_ip()
                if ip and ip != "0.0.0.0":
                    return True, ip, attempt
            time.sleep(2)               # 轮间隔, 让上层状态机退干净
        return False, None, attempt

    def ensure_ip(timeout=300):
        """等后台 autoconnect 把 IP 等来。RF 劣化时段显式 CWJAP 会一直失败,
        但模块后台在自动重连 —— 实测在测试中途自行恢复(WIFI GOT IP 出现在
        阶段 3 建连重试之间), 所以这里纯轮询 CIFSR, 不再打扰关联状态机。"""
        t0 = time.time()
        while time.time() - t0 < timeout:
            ip = sta_ip()
            if ip and ip != "0.0.0.0":
                return ip
            time.sleep(5)
        return None

    def reset_module(at, label, boot_wait=16):
        """测前复位: 关键是让 AP 模组走 env 自动恢复的上电干净路径。
        此前多轮重配实验会毒死 AP 的 lwIP netif(闭源库异步 ap_disable
        摘链), 表现为 beacon/DHCP 照常但 ICMP/TCP/UDP 全死。RST 后 env
        里保存的 CWMODE=2 + CWSAP(BK-M2M) 自动恢复, netif 从上电路径
        注册, 数据面即正常(实测 ping 18/10ms)。"""
        at.clear()
        at.send(line="AT+RST")
        at.expect(r"ready|OK|invalid", timeout=8)
        time.sleep(boot_wait)          # 上电自动恢复 SoftAP 需要时间
        at.pump(0.5)
        at.buf = b""
        # 复位后确认能应答
        at.send(line="AT")
        res = at.expect(r"\r?\nOK", timeout=6)
        at.buf = b""
        rep.add("0-拓扑", f"{label} 测前复位 (走干净上电路径)", "AT+RST",
                res is not None, "复位后 AT 应答正常" if res else "复位后 AT 无应答")
        return res is not None

    try:
        # ---------- 阶段 0: 拓扑建立 ----------
        if not args.no_rst:
            ap_alive = reset_module(apm, "AP 模组")
            sta_alive = reset_module(stm, "STA 模组")
            if not (ap_alive and sta_alive):
                raise RuntimeError("测前复位后模组无应答, 终止")

        # 先把两端的 wpa/AT 日志静音(ATE0) —— 日志和 AT 应答共用 UART1,
        # 两条线程按字节交错会把 "0,CONNECT"/"SEND OK"/"+IPD" 打断,
        # 后面所有 expect() 都会误判。实测这是之前偶发 FAIL 的主因。
        for at in (apm, stm):
            at.send(line="ATE0")
            time.sleep(0.6)
            at.pump(0.4)
            at.buf = b""

        # 状态归零: 前一轮/手工实验可能残留 CIPMUX=1 或透传模式。
        # CIPMUX=1 时单连接形式的 AT+CIPSTART="TCP",... 会因 argv[1] 被当
        # linkid 解析而必然 ERROR —— 曾经造成一轮"数据面全灭"的假象。
        for at in (apm, stm):
            at.send(line="AT+CIPMODE=0")
            time.sleep(0.4)
            at.send(line="AT+CIPMUX=0")
            time.sleep(0.4)
            at.pump(0.4)
            at.buf = b""

        ok, out = apm.cmd("AT")
        rep.add("0-拓扑", "AP 模组应答", "AT", ok, out.strip())
        ok, out = stm.cmd("AT")
        rep.add("0-拓扑", "STA 模组应答", "AT", ok, out.strip())

        ok, out = apm.cmd("AT+CWMODE=2")
        rep.add("0-拓扑", "AP 模组设纯 AP 模式", "AT+CWMODE=2", ok, out.strip())

        # 幂等配置: 若 env 里的 SoftAP 配置已与目标一致, 跳过 CWSAP 重配。
        # 原因: 运行时重配走 stop->start, 厂商闭源库的异步 ap_disable 会把
        # 重新 add 的 lwIP netif 拆掉 —— beacon 照常广播、DHCP 照常分发
        # (dhcp_server 直接用 g_uap.netif, 绕过链表), 但 ICMP/TCP/UDP 全废,
        # 表现为关联后 ping 网关超时、CIPSTART 连接失败。上电路径则完全正常。
        # 测试前用 AT+RST 让 AP 走 env 自动恢复, 即可全程避开重配路径。
        ok, out = apm.cmd("AT+CWSAP?", timeout=6)
        m = re.search(r'\+CWSAP:"([^"]*)","([^"]*)",(\d+),(\d+)', out)
        if ok and m and m.group(1) == AP_SSID and m.group(2) == AP_PWD \
                and int(m.group(3)) == args.ch and int(m.group(4)) == args.ecn:
            rep.add("0-拓扑", "SoftAP 配置已一致(跳过重配, 保持上电路径 netif)",
                    "AT+CWSAP? 匹配", True, out.strip())
        else:
            ok, out = apm.cmd(f'AT+CWSAP="{AP_SSID}","{AP_PWD}",{args.ch},{args.ecn}', timeout=10)
            rep.add("0-拓扑", f"AP 模组配置 SoftAP(ecn={args.ecn})", "AT+CWSAP", ok, out.strip())
            time.sleep(10)  # SoftAP 重启(尤其已运行时重配)需要较长时间才能广播

        ok, out = apm.cmd("AT+CWSAP?")
        rep.add("0-拓扑", "AP 模组 CWSAP 查询", "AT+CWSAP?", ok and AP_SSID in out, out.strip())

        ok, out = stm.cmd("AT+CWMODE=1")
        rep.add("0-拓扑", "STA 模组设纯 STA 模式", "AT+CWMODE=1", ok, out.strip())

        # 若已连着别的 AP 先退网
        stm.cmd("AT+CWQAP", timeout=6)

        # 扫描(验证 SoftAP 广播, 顺带验证运行时 CWMODE 切换修复)
        # 只认真正的扫描结果行: 命令回显里也含 SSID, 用字符串包含会假阳性;
        # 且必须扫到 BK-M2M 本身 —— 只匹配任意 "+CWLAP:(" 会被环境里的
        # 真实 AP 假阳性(BK-M2M 未广播时依然 PASS, 掩盖 beacon 停播)。
        #
        # 为什么要扫多次 (2026-10-09 修):
        #   BK-M2M 固定在 ch8, 而扫描是跳频的 —— 单次扫描有概率整轮都停在
        #   别的信道而漏掉它。实测同一时刻连续 3 次扫描的结果是
        #   "没扫到 / 没扫到 / 扫到(-40dBm)", 只扫一次会把**beacon 正常**
        #   误判成没广播, 后面 join_ap 因此连不上, 于是 TCP/UDP 阶段连环失败
        #   (实测同一份固件因此跑出过 26/11 与 34/3 的巨大波动)。
        #   这里扫到为止, 上限 scan_tries 次。
        scan_tries = 4
        res, seen_try = None, 0
        for i in range(scan_tries):
            stm.clear()
            stm.send(line="AT+CWLAP")
            seen_try = i + 1
            res = stm.expect(rf'\+CWLAP:\([^)]*"{AP_SSID}"', timeout=25)
            if res is not None:
                break
            # 扫不到多半是 beacon 还没起来 / 正在重配, 给它时间再来
            time.sleep(4)
        rep.add("1-AP广播", "STA 扫描到 BK-M2M (SoftAP 广播验证)", "AT+CWLAP",
                res is not None,
                (("第 %d 次扫描命中: " % seen_try) + res.strip()) if res is not None
                else "连续 %d 次扫描均未扫到 BK-M2M" % scan_tries)

        joined, sta_ip_str, tries = join_ap(timeout=150)
        rep.add("1-AP广播", "STA 关联 AP 并获得 IP", "AT+CWJAP",
                joined, f"第 {tries} 次尝试后 STAIP={sta_ip_str or '未获取'}")

        # 注意: 不要写 "sta_ip = sta_ip_str" —— 会遮蔽上面的 sta_ip() 函数,
        # 自愈重关联时 join_ap 内部调用 sta_ip() 会 TypeError 崩掉。
        sta_ip_str_var = sta_ip_str

        ok, out = apm.cmd("AT+CIPAP?")
        m = re.search(r"\+CIPAP:ip:\"?(\d+\.\d+\.\d+\.\d+)\"?", out)
        ap_ip = m.group(1) if m else None
        rep.add("1-AP广播", "AP 模组读取 IP", "AT+CIPAP?", ap_ip is not None, f"AP IP = {ap_ip}")
        if not ap_ip:
            raise RuntimeError("未取到 AP IP, 终止")

        # ---------- 阶段 1.5: 关联后数据面基线 ----------
        # 在开任何服务端之前先测模块侧 ping, 把"链路质量差(RF 时变)"和
        # "透传逻辑问题"区分开 —— 若这里 FAIL, 后面 TCP/UDP 全灭是 RF
        # 丢包所致, 不是透传问题。ping 失败先 CWQAP 重关联一次再测
        # (对付边际关联), 仍失败才认 FAIL。
        def baseline_ping():
            stm.clear()
            stm.send(line=f'AT+PING="{ap_ip}"')
            t0 = time.time()
            txt = ""
            while time.time() - t0 < 20:
                txt += stm.pump(0.3)
                if re.search(r"\+PING:\s*\d+", txt) or "ERROR" in txt:
                    break
            return bool(re.search(r"\+PING:\s*\d+", txt)), txt

        ping_ok, ptxt = baseline_ping()
        if not ping_ok:
            # 自愈: 先等后台 autoconnect(RF 劣化时段显式 CWJAP 只会更糟,
            # 实测它能自己恢复) -> 仍无 IP 再 CWQAP 显式重关联 -> 再 ping
            ip2 = ensure_ip(timeout=240)
            if ip2:
                sta_ip_str_var = ip2
                ping_ok, ptxt = baseline_ping()
                ptxt = "(等待后台自动重连后) " + ptxt
            else:
                stm.cmd("AT+CWQAP", timeout=6)
                time.sleep(2)
                joined2, ip2, tries2 = join_ap(timeout=200)
                if joined2:
                    ping_ok, ptxt = baseline_ping()
                    ptxt = f"(重关联第 {tries2} 次后) " + ptxt
                else:
                    ip2 = ensure_ip(timeout=180)
                    if ip2:
                        ping_ok, ptxt = baseline_ping()
                        ptxt = "(二轮后台等待后) " + ptxt
        rep.add("1-AP广播", "关联后数据面基线 (STA ping AP)", f'AT+PING="{ap_ip}"',
                ping_ok, ptxt.strip()[-90:] or "(无输出)")

        # ---------- 阶段 2: TCP 普通模式 ----------
        def sta_tcp_connect(label, tries=3):
            """TCP 建连(带重试)。RF 高丢包时 TCP 握手会 10s 超时回 ERROR,
            且对端可能已 accept 留下半开连接 —— 重试前先 CIPCLOSE 清理。"""
            for i in range(tries):
                stm.clear()
                stm.send(line=f'AT+CIPSTART="TCP","{ap_ip}",{TCP_PORT}')
                res = stm.expect(r"CONNECT", timeout=12)
                if res is not None:
                    return True, i + 1, (res or "").strip()[-60:]
                stm.cmd("AT+CIPCLOSE", timeout=4)
                time.sleep(1)
            return False, tries, "未见 CONNECT(重试后仍失败)"

        apm.cmd("AT+CIPMUX=1")
        ok, out = apm.cmd(f"AT+CIPSERVER=1,{TCP_PORT}", timeout=10)
        rep.add("2-TCP普通", "AP 侧开 TCP 服务端", "AT+CIPSERVER=1", ok, out.strip())

        ok, tries, res = sta_tcp_connect("阶段2")
        rep.add("2-TCP普通", "STA 侧建 TCP 连接 (CONNECT 事件)", "AT+CIPSTART",
                ok, f"第 {tries} 次尝试 | {res}")

        res = apm.expect(r"0,CONNECT", timeout=5)
        rep.add("2-TCP普通", "AP 侧收到客户端接入 (0,CONNECT)", "(被动)", res is not None,
                (res or "未见 0,CONNECT").strip()[-40:])

        # STA -> AP
        payload = "HELLO-FROM-STA"
        stm.clear()
        stm.send(line=f"AT+CIPSEND={len(payload)}")
        stm.expect(r">", timeout=5)
        stm.send(raw=payload.encode())
        res2 = stm.expect(r"SEND OK", timeout=8)
        ok, acc = apm.recv_payload(payload, timeout=8)
        rep.add("2-TCP普通", "STA→AP 数据 (AP 侧 +IPD)", f"AT+CIPSEND={len(payload)}",
                ok, acc.strip()[-60:] or "(AP 未收到)")

        # AP -> STA
        payload = "WORLD-FROM-AP"
        apm.clear()
        apm.send(line=f"AT+CIPSEND=0,{len(payload)}")
        apm.expect(r">", timeout=5)
        apm.send(raw=payload.encode())
        res2 = apm.expect(r"SEND OK", timeout=8)
        ok, acc = stm.recv_payload(payload, timeout=8)
        rep.add("2-TCP普通", "AP→STA 数据 (STA 侧 +IPD)", f"AT+CIPSEND=0,{len(payload)}",
                ok, acc.strip()[-60:] or "(STA 未收到)")

        # STA 主动断开 → AP 应报 0,CLOSED
        ok, _ = stm.cmd("AT+CIPCLOSE")
        rep.add("2-TCP普通", "STA 断开连接", "AT+CIPCLOSE", ok, "")
        res = apm.expect(r"0,CLOSED", timeout=6)
        rep.add("2-TCP普通", "AP 收到断开事件 (0,CLOSED)", "(被动)", res is not None,
                (res or "未见 0,CLOSED").strip()[-40:])

        ok2, _ = apm.cmd("AT+CIPSERVER=0", timeout=10)
        rep.add("2-TCP普通", "关闭 TCP 服务端", "AT+CIPSERVER=0", ok2, "")

        # ---------- 阶段 3: TCP 透传 ----------
        ok, out = apm.cmd(f"AT+CIPSERVER=1,{TCP_PORT}", timeout=10)
        rep.add("3-TCP透传", "AP 侧重开 TCP 服务端", "AT+CIPSERVER=1", ok, out.strip())

        ok, out = stm.cmd("AT+CIPMODE=1")
        rep.add("3-TCP透传", "STA 设透传模式", "AT+CIPMODE=1", ok, out.strip())

        ok, tries, res = sta_tcp_connect("阶段3")
        rep.add("3-TCP透传", "STA 透传建连 (RF 抖动自动重试)", "AT+CIPSTART", ok,
                f"第 {tries} 次尝试 | {res}")

        stm.clear()
        stm.send(line="AT+CIPSEND")
        res = stm.expect(r">", timeout=5)
        rep.add("3-TCP透传", "STA 进入透传 (提示符)", "AT+CIPSEND", res is not None,
                (res or "未见 >").strip()[-30:])

        payload = "TCP-PASSTHRU-DATA-0123456789"
        stm.send(raw=payload.encode())
        ok, acc = apm.recv_payload(payload, timeout=8)
        rep.add("3-TCP透传", "STA 裸发→AP 收到数据(+IPD 分块容忍)", "(裸数据)",
                ok, acc.strip()[-70:] or "(AP 未收到)")

        payload = "TCP-PONG-FROM-AP"
        apm.clear()
        apm.send(line=f"AT+CIPSEND=0,{len(payload)}")
        apm.expect(r">", timeout=5)
        apm.send(raw=payload.encode())
        time.sleep(1.0)
        stm.pump(1.0)
        raw_all = stm.buf.decode("utf-8", "replace")
        stm.buf = b""
        ok_raw = payload in IPD_HEAD.sub("", raw_all) and "+IPD" not in raw_all
        rep.add("3-TCP透传", "AP 回发→STA 收裸数据(无+IPD)", "AT+CIPSEND=0,n", ok_raw,
                raw_all.strip()[-60:] or "(空)")

        # +++ 退出
        exit_passthrough(stm)
        stm.buf = b""
        ok, out = stm.cmd("AT")
        rep.add("3-TCP透传", "+++ 退出透传后 AT 恢复", "+++/AT", ok,
                out.strip() if ok else "AT 无应答, 可能仍卡在透传")

        stm.cmd("AT+CIPMODE=0")
        stm.cmd("AT+CIPCLOSE")
        apm.cmd("AT+CIPSERVER=0", timeout=10)

        # ---------- 阶段 4: UDP 普通模式 ----------
        ok, out = apm.cmd(f'AT+CIPSERVER=1,{UDP_PORT},"UDP"', timeout=10)
        rep.add("4-UDP普通", "AP 侧开 UDP 服务端", 'AT+CIPSERVER=1,,"UDP"', ok, out.strip())

        stm.clear()
        stm.send(line=f'AT+CIPSTART="UDP","{ap_ip}",{UDP_PORT},{UDP_PORT+100},0')
        res = stm.expect(r"OK|CONNECT", timeout=10)
        rep.add("4-UDP普通", "STA 建 UDP 连接 (含 udp mode 参数)", "AT+CIPSTART=UDP", res is not None,
                (res or "无应答").strip()[-50:])

        payload = "UDP-FROM-STA"
        ok = False
        acc = ""
        for i in range(3):           # UDP 无重传, 高丢包时多打几枪
            stm.clear()
            stm.send(line=f"AT+CIPSEND={len(payload)}")
            stm.expect(r">", timeout=5)
            stm.send(raw=payload.encode())
            stm.expect(r"SEND OK|SEND ERROR", timeout=8)
            ok, acc = apm.recv_payload(payload, timeout=6)
            if ok:
                break
            time.sleep(1)
        rep.add("4-UDP普通", "STA→AP UDP (对端学习, 丢包重试)", f"AT+CIPSEND={len(payload)}",
                ok, f"第 {i+1} 次尝试 | " + (acc.strip()[-50:] or "(AP 未收到)"))

        payload = "UDP-FROM-AP"
        ok = False
        acc = ""
        for i in range(3):           # 对端学习依赖上面收到过包; 回发失败重试
            apm.clear()
            apm.send(line=f"AT+CIPSEND=5,{len(payload)}")
            apm.expect(r">", timeout=5)
            apm.send(raw=payload.encode())
            apm.expect(r"SEND OK|SEND ERROR", timeout=8)
            ok, acc = stm.recv_payload(payload, timeout=6)
            if ok:
                break
            time.sleep(1)
        rep.add("4-UDP普通", "AP→STA UDP 回发 (丢包重试)", f"AT+CIPSEND=5,{len(payload)}",
                ok, f"第 {i+1} 次尝试 | " + (acc.strip()[-50:] or "(STA 未收到)"))

        stm.cmd("AT+CIPCLOSE")
        ok2, _ = apm.cmd("AT+CIPSERVER=0", timeout=10)
        rep.add("4-UDP普通", "关闭 UDP 服务端", "AT+CIPSERVER=0", ok2, "")

        # ---------- 阶段 5: UDP 透传 ----------
        ok, out = apm.cmd(f'AT+CIPSERVER=1,{UDP_PORT},"UDP"', timeout=10)
        rep.add("5-UDP透传", "AP 侧重开 UDP 服务端", 'AT+CIPSERVER=1,,"UDP"', ok, out.strip())

        ok, out = stm.cmd("AT+CIPMODE=1")
        ok2, out2 = stm.cmd(f'AT+CIPSTART="UDP","{ap_ip}",{UDP_PORT},{UDP_PORT+100},0', timeout=10)
        rep.add("5-UDP透传", "STA 透传 UDP 建连", "CIPMODE=1/CIPSTART", ok and ok2, out2.strip())

        stm.clear()
        stm.send(line="AT+CIPSEND")
        res = stm.expect(r">", timeout=5)
        payload = "UDP-PASSTHRU-DATA"
        ok = False
        acc = ""
        for i in range(6):           # UDP 透传裸发, 高丢包多打几枪
            stm.send(raw=payload.encode())
            ok, acc = apm.recv_payload(payload, timeout=6)
            if ok:
                break
            time.sleep(1)
        rep.add("5-UDP透传", "STA 裸发→AP 收到 (UDP 透传, 丢包重试)", "(裸数据)",
                ok, f"第 {i+1} 次尝试 | " + (acc.strip()[-50:] or "(AP 未收到)"))

        payload = "UDP-PONG"
        ok = False
        raw_all = ""
        for i in range(6):           # 回发依赖对端学习, 丢包重试
            apm.clear()
            apm.send(line=f"AT+CIPSEND=5,{len(payload)}")
            apm.expect(r">", timeout=5)
            apm.send(raw=payload.encode())
            apm.expect(r"SEND OK|SEND ERROR", timeout=8)
            time.sleep(1.0)
            stm.pump(1.0)
            raw_all = stm.buf.decode("utf-8", "replace")
            stm.buf = b""
            ok_raw = payload in IPD_HEAD.sub("", raw_all) and "+IPD" not in raw_all
            if ok_raw:
                break
            time.sleep(1)
        ok = payload in IPD_HEAD.sub("", raw_all) and "+IPD" not in raw_all
        rep.add("5-UDP透传", "AP 回发→STA 收裸数据", "AT+CIPSEND=5,n", ok,
                raw_all.strip()[-60:] or "(空)")

        exit_passthrough(stm)
        stm.buf = b""
        ok, out = stm.cmd("AT")
        rep.add("5-UDP透传", "+++ 退出后 AT 恢复", "+++/AT", ok,
                out.strip() if ok else "AT 无应答")

        stm.cmd("AT+CIPMODE=0")
        stm.cmd("AT+CIPCLOSE")
        apm.cmd("AT+CIPSERVER=0", timeout=10)

    finally:
        # 兜底恢复: 防止留在透传
        for at in (stm, apm):
            try:
                exit_passthrough(at)
                at.send(line="AT+CIPMODE=0")
                at.send(line="AT+CIPCLOSE")
                at.send(line="AT+CIPSERVER=0")
                at.pump(0.5)
            except Exception:
                pass
        apm.close()
        stm.close()
        rep.save()

    return 1 if rep.n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
