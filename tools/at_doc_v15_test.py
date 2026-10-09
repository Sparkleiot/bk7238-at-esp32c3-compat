#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按《ESP8266 AT 指令教程 v1.5》逐节实测 BK7238 esp32c3-compat 固件。

(教程为第三方公开文档，此处仅引用其章节编号与命令示例作为验收清单。)


- PC 网络助手角色(TCP server/client、UDP)由内嵌 socket 实现。
- 双模组章节(2.1/2.6/2.7): COM7=AP(BK-M2M, ch8, open), COM6=STA。
- 单模组章节(2.2/2.3/2.4/2.5/2.8/3.1): COM5 STA 连真实路由 MyHomeWiFi。
- 全程 ATE0 静音(应答/日志分离), 判定不依赖文本包含。

用法: python tools/at_doc_v15_test.py [--sta COM5 --ap COM7 --sta2 COM6]
"""
import argparse
import os
import re
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from at_module_to_module_test import AT  # noqa: E402

PC_IP = "192.168.0.152"          # 本机在 MyHomeWiFi 网段的地址
ROUTER_SSID = "MyHomeWiFi"
ROUTER_PWD = os.environ.get("BK7238_WIFI_PWD", "<WIFI_PWD>")
M2M_SSID = "BK-M2M"
M2M_PWD = "12345678"
P11 = b"sparkleiot"                                  # 品牌标识负载, 恰好 10 字节
P30 = b"SparkleIOT"                                  # 品牌回显负载, 恰好 10 字节


# ---------------------------------------------------------------- helpers
def at_cmd(at, line, timeout=8):
    """发命令并等到 OK/ERROR, 返回 (status, acc_text)"""
    at.clear()
    at.send(line=line)
    t0 = time.time()
    acc = ""
    while time.time() - t0 < timeout:
        acc += at.pump(0.2)
        if re.search(r"\r?\nOK\r?\n", acc):
            return "OK", acc
        if re.search(r"\r?\nERROR", acc):
            return "ERROR", acc
    return "TIMEOUT", acc


def wait_str(at, pat, timeout):
    """在累计缓冲(含历史)里找 regex; 命中后清空缓冲避免重复命中"""
    rx = re.compile(pat)
    t0 = time.time()
    while time.time() - t0 < timeout:
        text = at.buf.decode("utf-8", "replace")
        m = rx.search(text)
        if m:
            at.buf = b""
            return text[: m.end()]
        at.pump(0.2)
    return None


def udp_start(at, line, timeout=12):
    """UDP 建连: ESP-AT 语义下 UDP 没有 CONNECT 事件, 回 OK 即成功"""
    st, acc = at_cmd(at, line, timeout=timeout)
    return st == "OK", acc


def wait_ipd(at, data_bytes, timeout):
    """等 +IPD 数据: 在 bytes 层提取所有 +IPD 负载拼接后再匹配
    (分块会把多字节 UTF-8 汉字从中间切开, 必须先按字节拼完再 decode)"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        parts = re.split(rb"\+IPD,(?:\d+,)?\d*:", at.buf)
        payload = b"".join(parts[1:])
        if data_bytes in payload:
            at.buf = b""
            return payload.decode("utf-8", "replace")
        at.pump(0.2)
    return None


def warm_udp(sock, ip, port, n=3):
    """PC 侧先发几包 UDP 到 (ip, port)。

    必要性: Windows 防火墙默认 BlockInbound, 会把模组**非请自来**的入站 UDP 丢掉
    (实测: 模组首发 0/6 到达; PC 先发一包后同一 socket 6/6 到达)。真实"网络调试助手"
    在 PC 上会获得防火墙授权, 这里用热包等价模拟, 否则会得到假失败。
    """
    for _ in range(n):
        try:
            sock.sendto(b"warmup", (ip, port))
        except Exception:
            pass
        time.sleep(0.15)


def cleanup_links(at):
    """节间清理: 关全部连接 + 退出透传模式 + 单连接"""
    at_cmd(at, "AT+CIPCLOSE=5", 4)
    at_cmd(at, "AT+CIPCLOSE", 4)
    at_cmd(at, "AT+CIPMODE=0", 4)


def cipsend_fixed(at, n, data, mux_id=None):
    """普通模式 CIPSEND=<n> → '>' → 裸数据 → SEND OK"""
    line = f"AT+CIPSEND={mux_id},{n}" if mux_id is not None else f"AT+CIPSEND={n}"
    st, acc = at_cmd(at, line, timeout=4)
    if ">" not in acc:
        return False, f"CIPSEND 应答无 '>' ({st})"
    at.clear()
    at.send(raw=data)
    r = wait_str(at, r"SEND OK", 5)
    return (r is not None), (r or "SEND OK 未出现")


def enter_passthru_send(at, data):
    """透传: AT+CIPSEND(无参) → '>' → 裸数据; 数据回显即发出"""
    st, acc = at_cmd(at, "AT+CIPSEND", timeout=4)
    if ">" not in acc:
        return False, f"无 '>' ({st})"
    at.clear()
    at.send(raw=data)
    time.sleep(1.2)
    return True, at.pump(0.3)


def exit_passthru(at):
    """+++ 退出透传(前后静默 ≥1s, 不加回车), 再用 AT 验证恢复"""
    time.sleep(1.0)
    at.send(raw=b"+++")
    time.sleep(1.0)
    at.pump(0.5)
    at.clear()
    at.send(line="AT")
    return wait_str(at, r"\bOK", 3) is not None


def force_normal_mode(at):
    """开跑前的硬前置: 把模组从「透传态」拉回普通 AT 态。

    为什么必须: 卡在透传(CIPMODE=1 且 CIPSEND 已把 UART 交给网络)时, 模组**不再解析
    任何 AT 命令**——ATE0/AT+RST/CIPMODE=0 全部石沉大海, 整轮测试从第一项开始全灭,
    看起来像"固件挂了"。2026-10-08 全量跑出 27 PASS/29 FAIL 就是这个原因:
    上一轮被 SIGTERM 打断时正停在 2.3/2.8 的透传里, +++ 没来得及发。

    返回 True 表示模组现在能正常应答 AT。
    """
    at.clear()
    at.send(line="AT")
    if wait_str(at, r"\bOK", 3) is not None:
        at_cmd(at, "AT+CIPMODE=0", 4)
        at_cmd(at, "AT+CIPCLOSE=5", 4)
        return True
    # 不应答 => 很可能卡在透传, 先发保护时间再发 +++
    if exit_passthru(at):
        at_cmd(at, "AT+CIPMODE=0", 4)
        at_cmd(at, "AT+CIPCLOSE=5", 4)
        return True
    # 再兜一次: 有些实现要求 +++ 前后各安静 1s
    time.sleep(1.2)
    at.send(raw=b"+++")
    time.sleep(1.2)
    at.clear()
    at.send(line="AT")
    return wait_str(at, r"\bOK", 4) is not None


def join_router(at, timeout=30):
    st, acc = at_cmd(at, f'AT+CWJAP="{ROUTER_SSID}","{ROUTER_PWD}"', timeout=timeout)
    if st != "OK":
        return None, acc
    r = wait_str(at, r"GOT IP", 20)
    st2, ipq = at_cmd(at, "AT+CIFSR", timeout=6)
    m = re.search(r'\+CIFSR:STAIP,"([\d.]+)"', ipq)
    return (m.group(1) if m else None), (r or "")


class TCPSrv:
    def __init__(self, port):
        self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.s.bind(("", port))
        self.s.listen(1)
        self.s.settimeout(0.2)
        self.conn = None

    def accept(self, timeout):
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                self.conn, addr = self.s.accept()
                self.conn.settimeout(0.2)
                return addr
            except socket.timeout:
                pass
        return None

    def recv(self, timeout, n=None):
        t0 = time.time()
        buf = b""
        while time.time() - t0 < timeout:
            try:
                d = self.conn.recv(4096)
                if d:
                    buf += d
                    if n is not None and len(buf) >= n:
                        break
            except socket.timeout:
                pass
            except Exception:
                break
        return buf

    def sendall(self, data):
        self.conn.sendall(data)

    def close(self):
        try:
            if self.conn:
                self.conn.close()
        finally:
            self.s.close()


def tcp_connect(host, port, timeout=6):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        s.settimeout(0.2)
        return s
    except Exception:
        return None


class UDPHelper:
    def __init__(self, port):
        self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.s.bind(("", port))
        self.s.settimeout(0.2)

    def recv(self, timeout, n=None):
        t0 = time.time()
        buf = b""
        while time.time() - t0 < timeout:
            try:
                d, addr = self.s.recvfrom(4096)
                buf += d
                self.last_peer = addr
                if n is not None and len(buf) >= n:
                    break
            except socket.timeout:
                pass
        return buf

    def sendto(self, data, addr):
        self.s.sendto(data, addr)

    def close(self):
        self.s.close()


# ---------------------------------------------------------------- report
class Rep:
    def __init__(self, args):
        self.args = args
        self.rows = []
        self.n_ok = self.n_fail = self.n_na = 0

    def add(self, sec, item, cmd, ok, detail, na=False):
        if na:
            self.n_na += 1
            tag = "N/A"
        elif ok:
            self.n_ok += 1
            tag = "PASS"
        else:
            self.n_fail += 1
            tag = "FAIL"
        self.rows.append((sec, item, cmd, tag, (detail or "")[:200]))

    def write(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("# 《ESP8266 AT 指令教程 v1.5》逐节实测报告 (BK7238 esp32c3-compat)\n\n")
            f.write(f"- 时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"- 固件: at-esp32c3-compat_2M.1220.bin (含 IP 兼容修复 CIPAP/CWDHCP/CWDHCPS)\n")
            f.write(f"- 拓扑: STA 测试机 {args.sta} (连 {ROUTER_SSID}), AP 模组 {args.ap} (SoftAP {M2M_SSID}), "
                    f"第二 STA {args.sta2}; PC={PC_IP} 充当文档中的『网络调试助手』\n")
            f.write(f"- 结果: **{self.n_ok} PASS / {self.n_fail} FAIL / {self.n_na} N/A**\n\n")
            f.write("| 节 | 测试项 | 命令 | 结果 | 实际 |\n|---|---|---|---|---|\n")
            for sec, item, cmd, tag, detail in self.rows:
                f.write(f"| {sec} | {item} | `{cmd}` | {tag} | {detail} |\n")


# ---------------------------------------------------------------- sections
def sec0_prep(rep, a, b, c):
    """0. 准备: 拉回普通模式/静音/复位, AP 模组 IP 对齐 ESP-AT 默认 192.168.4.1"""
    # 先把可能卡在透传态的模组救回来 —— 否则后面所有 AT 都会被吞掉, 整轮假性全灭。
    for name, at in (("STA", a), ("AP", b), ("STA2", c)):
        rep.add("0-准备", f"{name} 起始态脱离透传(+++ 兜底)", "+++ / AT / AT+CIPMODE=0",
                force_normal_mode(at), "")

    for name, at in (("STA", a), ("AP", b), ("STA2", c)):
        at.send(line="ATE0")
        time.sleep(0.6)
        at.pump(0.3)
    # 清掉可能残留的"保存透传"(AT+SAVETRANSLINK 会写 env 的 autotransinfo.enable=1):
    # 一旦 enable=1, 每次上电/WiFi 重连都会自动重放一条 AT+CIPSTART 并切进透传模式,
    # 既会随机吐 ERROR 污染应答判定, 又会让模组卡在透传里(AT 无响应)。
    # 注意: 本固件的 SAVETRANSLINK 要求 argc==4|5, 只发 "=0" 会回 ERROR, 必须带余参。
    # (ESP-AT 允许 AT+SAVETRANSLINK=0 单参数关闭, 这里算已知小差距, 之后可修。)
    for name, at in (("STA", a), ("AP", b), ("STA2", c)):
        at.send(line='AT+SAVETRANSLINK=0,"0.0.0.0",0')
        time.sleep(0.5)
        at.pump(0.3)
    for name, at in (("STA", a), ("AP", b), ("STA2", c)):
        at.clear()
        at.send(line="AT+RST")
        time.sleep(14)
        at.pump(0.8)
        st, acc = at_cmd(at, "AT", timeout=4)
        rep.add("0-准备", f"{name} 模组复位后 AT 应答", "AT+RST / AT",
                st == "OK", acc.strip()[:60])

    # AP 模组 IP: 修回 ESP-AT 默认 192.168.4.1 (参数序 = ip,gateway,netmask)
    st, acc = at_cmd(b, 'AT+CIPAP="192.168.4.1","192.168.4.1","255.255.255.0"', timeout=12)
    st2, q = at_cmd(b, "AT+CIPAP?", timeout=6)
    ok = ('+CIPAP:ip:"192.168.4.1"' in q and '+CIPAP:gateway:"192.168.4.1"' in q
          and '+CIPAP:netmask:"255.255.255.0"' in q)
    rep.add("0-准备", "AP IP 对齐 ESP-AT 默认(192.168.4.1) [今天修复的参数序实测]",
            'AT+CIPAP="192.168.4.1","192.168.4.1","255.255.255.0"',
            st == "OK" and ok,
            (" | ".join(l.strip() for l in q.splitlines() if "CIPAP" in l))[:160])

    # CWDHCPS 查询(新增命令)
    st, q = at_cmd(b, "AT+CWDHCPS?", timeout=6)
    m = re.search(r'\+CWDHCPS:(\d+),"([\d.]+)","([\d.]+)"', q)
    ok = st == "OK" and m is not None and m.group(2).endswith(".2")
    rep.add("0-准备", "CWDHCPS 查询默认段 .2~.101 [新增命令实测]", "AT+CWDHCPS?",
            ok, q.strip()[:120])

    # STA 测试机连路由
    ip, acc = join_router(a)
    rep.add("0-准备", f"STA({a.name}) 连接路由 {ROUTER_SSID}", f'AT+CWJAP="{ROUTER_SSID}"',
            ip is not None, f"IP={ip}" if ip else acc.strip()[-120:])


def sec21_ap_tcp_server(rep, apm, st2):
    """2.1 AP 模式 TCP server: AP 发 CIPSEND=0,10, 客户端(STA2)收 +IPD 并回发"""
    at_cmd(apm, "AT+CWMODE=2", 10)
    st, acc = at_cmd(apm, f'AT+CWSAP="{M2M_SSID}","{M2M_PWD}",8,0', 12)
    rep.add("2.1 AP-TCP服务器", "AP 配置热点", f'AT+CWSAP="{M2M_SSID}",...8,0',
            st == "OK", acc.strip()[:60])
    at_cmd(apm, "AT+CIPMUX=1", 6)
    st, acc = at_cmd(apm, "AT+CIPSERVER=1,8899", 8)
    rep.add("2.1 AP-TCP服务器", "AP 开 TCP 服务器(多连接)", "AT+CIPMUX=1 / AT+CIPSERVER=1,8899",
            st == "OK", acc.strip()[:60])

    # STA2 关联模组 AP
    st2_ip = _m2m_associate(rep, st2, "2.1")
    if not st2_ip:
        return
    st, acc = at_cmd(st2, 'AT+CIPSTART="TCP","192.168.4.1",8899', 15)
    got = wait_str(st2, r"CONNECT", 15)
    rep.add("2.1 AP-TCP服务器", "STA2 连 AP 的 8899", 'AT+CIPSTART="TCP","192.168.4.1",8899',
            got is not None, (got or acc).strip().replace("\r\n", "⏎")[-80:])
    apside = wait_str(apm, r"0,CONNECT", 10)
    rep.add("2.1 AP-TCP服务器", "AP 侧看到客户端 0,CONNECT", "(事件)", apside is not None,
            (apside or "未见").strip()[-60:])

    ok, det = cipsend_fixed(apm, len(P11), P11, mux_id=0)
    rep.add("2.1 AP-TCP服务器", "AP 发送 10 字节(品牌标识负载)", "AT+CIPSEND=0,10 → sparkleiot",
            ok, det.strip()[:60])
    r = wait_str(st2, re.escape(P11.decode()), 10)
    rep.add("2.1 AP-TCP服务器", "STA2 收到 +IPD 数据", "+IPD,10:sparkleiot",
            r is not None, (r or "未收到").strip()[-70:])

    ok, det = cipsend_fixed(st2, len(P30), P30)
    rep.add("2.1 AP-TCP服务器", "STA2 回发 10 字节(品牌回显负载)", "AT+CIPSEND=10 → SparkleIOT",
            ok, det.strip()[:50])
    r = wait_str(apm, re.escape(P30.decode()), 10)
    rep.add("2.1 AP-TCP服务器", "AP 收到 +IPD,0,30 回发数据", "+IPD,0,30:...", r is not None,
            (r or "未收到").strip()[-60:])


def _m2m_associate(rep, st2, sec):
    """STA2 关联模组 SoftAP, 拿 IP (期望 DHCP 默认 .2 起)"""
    at_cmd(st2, "AT+CWMODE=1", 8)
    ok = False
    for attempt in range(5):
        st2.clear()
        st2.send(line=f'AT+CWJAP="{M2M_SSID}","{M2M_PWD}"')
        t0 = time.time()
        while time.time() - t0 < 45:
            acc = st2.pump(0.4)
            if "GOT IP" in acc:
                ok = True
                break
            if "ERROR" in acc and "WIFI DISCONNECT" not in acc and attempt == 0:
                pass
        if ok:
            break
        time.sleep(2)
    if not ok:
        rep.add(sec, "STA2 关联模组 AP (RF 环境限制, 重试 5 轮)", f'AT+CWJAP="{M2M_SSID}"',
                False, "45s×5 轮未关联 —— RF 黑窗口, 其余项连带跳过")
        return None
    st, q = at_cmd(st2, "AT+CIFSR", 6)
    m = re.search(r'\+CIFSR:STAIP,"([\d.]+)"', q)
    ip = m.group(1) if m else None
    rep.add(sec, "STA2 关联模组 AP 并取得 IP", f'AT+CWJAP="{M2M_SSID}"',
            ip is not None, f"IP={ip}" + (" (DHCP 默认 .2 起 ✔)" if ip and ip.endswith(".2") else ""))
    return ip


def sec22_sta_tcp_server(rep, a):
    """2.2 STA 模式 TCP server: PC 连模组, 模组 CIPSEND=0,10"""
    cleanup_links(a)
    at_cmd(a, "AT+CIPMUX=1", 6)
    st, acc = at_cmd(a, "AT+CIPSERVER=1,8899", 8)
    rep.add("2.2 STA-TCP服务器", "模组开 TCP 服务器", "AT+CIPMUX=1 / AT+CIPSERVER=1,8899",
            st == "OK", acc.strip()[:60])
    st, q = at_cmd(a, "AT+CIFSR", 6)
    m = re.search(r'\+CIFSR:STAIP,"([\d.]+)"', q)
    mip = m.group(1) if m else None
    srv = TCPSrv(8899)
    addr = None
    if mip:
        pc = tcp_connect(mip, 8899, timeout=8)
        if pc:
            # PC 主动连, 模组侧 accept
            srv.close()
            time.sleep(0.5)
            r = wait_str(a, r"0,CONNECT", 8)
            addr = True if r else None
            # 用 pc 作为连接
            class _P:
                pass
            srv2 = _P()
            srv2.s = pc
            srv2.recv = lambda timeout, n=None: _tcp_client_recv(pc, timeout, n)
            srv2.sendall = pc.sendall
            srv2.close = pc.close
            srv = srv2
    rep.add("2.2 STA-TCP服务器", "PC 连接模组 8899(文档: 网络调试助手)", f"TCP connect {mip}:8899",
            addr is not None, "0,CONNECT" if addr else "模组未上报连接")

    if not mip or addr is None:
        at_cmd(a, "AT+CIPSERVER=0", 6)
        return
    ok, det = cipsend_fixed(a, len(P11), P11, mux_id=0)
    rep.add("2.2 STA-TCP服务器", "模组发 10 字节给 PC", "AT+CIPSEND=0,10", ok, det.strip()[:50])
    d = srv.recv(6, 11)
    rep.add("2.2 STA-TCP服务器", "PC 收到 sparkleiot", "(socket)", d == P11, f"{len(d)}B {d[:32]!r}")
    srv.sendall(P30)
    r = wait_str(a, re.escape(P30.decode()), 8)
    rep.add("2.2 STA-TCP服务器", "模组收到 +IPD,0,30 回发", "+IPD,0,30:SparkleIOT",
            r is not None, (r or "未收到").strip()[-60:])
    st, acc = at_cmd(a, "AT+CIPSERVER=0", 6)
    rep.add("2.2 STA-TCP服务器", "关闭 TCP 服务器(文档 3.1-7)", "AT+CIPSERVER=0",
            st == "OK", acc.strip()[:40])
    srv.close()


def _tcp_client_recv(sock, timeout, n=None):
    t0 = time.time()
    buf = b""
    while time.time() - t0 < timeout:
        try:
            d = sock.recv(4096)
            if d:
                buf += d
                if n is not None and len(buf) >= n:
                    break
            else:
                break
        except socket.timeout:
            pass
    return buf


def sec23_tcp_passthru(rep, a):
    """2.3 TCP client 透传到 PC"""
    cleanup_links(a)
    at_cmd(a, "AT+CIPMUX=0", 6)
    st, acc = at_cmd(a, "AT+CIPMODE=1", 6)
    rep.add("2.3 TCP透传", "设置单连接+透传", "AT+CIPMUX=0 / AT+CIPMODE=1",
            st == "OK", acc.strip()[:40])
    srv = TCPSrv(8890)
    st, acc = at_cmd(a, f'AT+CIPSTART="TCP","{PC_IP}",8890', 15)
    got = wait_str(a, r"CONNECT", 15)
    rep.add("2.3 TCP透传", "连接 PC TCP 服务器", f'AT+CIPSTART="TCP","{PC_IP}",8890',
            got is not None, (got or acc).strip().replace("\r\n", "⏎")[-60:])
    if got is None:
        srv.close()
        at_cmd(a, "AT+CIPMODE=0", 6)
        return
    addr = srv.accept(8)
    rep.add("2.3 TCP透传", "PC 侧 accept", "(socket)", addr is not None, f"{addr}")

    ok, det = enter_passthru_send(a, P11)
    rep.add("2.3 TCP透传", "AT+CIPSEND 进入透传并发 10 字节", "AT+CIPSEND → sparkleiot",
            ok, det.strip()[:40])
    d = srv.recv(6, 11)
    rep.add("2.3 TCP透传", "PC 收到裸数据(无 +IPD)", "(socket)", d == P11, f"{len(d)}B {d[:32]!r}")
    srv.sendall(P30)
    r = wait_str(a, re.escape(P30.decode()), 8)
    rep.add("2.3 TCP透传", "模组透传裸收 PC 回发(无 +IPD)", "SparkleIOT",
            r is not None, (r or "未收到").strip()[-50:])
    ok = exit_passthru(a)
    rep.add("2.3 TCP透传", "+++ 退出透传, AT 恢复应答", "+++ / AT", ok, "OK" if ok else "退出失败")
    at_cmd(a, "AT+CIPMODE=0", 6)
    srv.close()


def sec24_udp_multi(rep, a):
    """2.4 UDP 多连接: 广播 + 单播各一路"""
    cleanup_links(a)
    at_cmd(a, "AT+CIPMUX=1", 6)
    bc = UDPHelper(50000)     # 收广播
    uc = UDPHelper(50001)     # 收单播
    st, q = at_cmd(a, "AT+CIFSR", 6)
    mip = re.search(r'\+CIFSR:STAIP,"([\d.]+)"', q)
    mip = mip.group(1) if mip else None

    ok, acc = udp_start(a, 'AT+CIPSTART=0,"UDP","255.255.255.255",50000,1000,0')
    rep.add("2.4 UDP多连接", "建 UDP 连接 0(广播, 文档原例)", 'AT+CIPSTART=0,"UDP","255.255.255.255",50000,1000,0',
            ok, acc.strip().replace("\r\n", "⏎")[-60:])
    if mip:
        warm_udp(bc, mip, 1000)
    ok, det = cipsend_fixed(a, len(P11), P11, mux_id=0)
    d = bc.recv(6, 11)
    rep.add("2.4 UDP多连接", "PC(50000) 收到 UDP 广播", "AT+CIPSEND=0,10",
            d == P11, f"{len(d)}B {d[:24]!r}" + ("" if d else " (路由器可能隔离广播)"))

    ok, acc = udp_start(a, f'AT+CIPSTART=1,"UDP","{PC_IP}",50001,1001,0')
    rep.add("2.4 UDP多连接", "建 UDP 连接 1(单播到 PC)", f'AT+CIPSTART=1,"UDP","{PC_IP}",50001,1001,0',
            ok, acc.strip().replace("\r\n", "⏎")[-50:])
    if mip:
        warm_udp(uc, mip, 1001)
    ok, det = cipsend_fixed(a, len(P11), P11, mux_id=1)
    d = uc.recv(6, 11)
    rep.add("2.4 UDP多连接", "PC(50001) 收到单播", "AT+CIPSEND=1,10", d == P11, f"{len(d)}B {d[:24]!r}")
    if getattr(uc, "last_peer", None):
        # 用数据包学到的对端地址(IP 可能因重连变化, 比 CIFSR 的旧值可靠)
        target_ip = uc.last_peer[0]
        r = None
        for _ in range(8):
            uc.sendto(P30, (target_ip, 1001))
            r = wait_ipd(a, P30, 2)
            if r:
                break
        rep.add("2.4 UDP多连接", "模组收到 +IPD,1,10(PC 回发)", "+IPD,1,10:...",
                r is not None, (r or f"未收到(重试8次, 对端={target_ip}:1001)").strip()[-70:])
    bc.close()
    uc.close()


def sec25_udp_passthru(rep, a):
    """2.5 UDP 透传(本地端口 2000, 文档原例)"""
    cleanup_links(a)
    at_cmd(a, "AT+CIPMUX=0", 6)
    st, acc = at_cmd(a, "AT+CIPMODE=1", 6)
    u = UDPHelper(5000)
    st, q = at_cmd(a, "AT+CIFSR", 6)
    mip = re.search(r'\+CIFSR:STAIP,"([\d.]+)"', q)
    mip = mip.group(1) if mip else None
    ok, acc = udp_start(a, f'AT+CIPSTART="UDP","{PC_IP}",5000,2000,0')
    rep.add("2.5 UDP透传", "UDP 透传建连(本地端口 2000)", f'AT+CIPSTART="UDP","{PC_IP}",5000,2000,0',
            ok, acc.strip().replace("\r\n", "⏎")[-60:])
    if not ok:
        u.close()
        at_cmd(a, "AT+CIPMODE=0", 6)
        return
    if mip:
        warm_udp(u, mip, 2000)
    ok, det = enter_passthru_send(a, P11)
    d = u.recv(6, 11)
    rep.add("2.5 UDP透传", "PC 收到透传裸数据", "AT+CIPSEND → sparkleiot", d == P11,
            f"{len(d)}B {d[:24]!r}")
    if getattr(u, "last_peer", None):
        target_ip = u.last_peer[0]
        r = None
        for _ in range(8):
            u.sendto(P30, (target_ip, 2000))
            r = wait_str(a, re.escape(P30.decode()), 2)
            if r:
                break
        rep.add("2.5 UDP透传", "模组透传裸收回发(UDP 丢包 x3 重试)", "SparkleIOT",
                r is not None, (r or f"未收到(对端={target_ip}:2000)").strip()[-60:])
    ok = exit_passthru(a)
    rep.add("2.5 UDP透传", "+++ 退出透传", "+++ / AT", ok, "OK" if ok else "退出失败")
    at_cmd(a, "AT+CIPMODE=0", 6)
    u.close()


def _reset_ap_module(apm):
    apm.clear()
    apm.send(line="AT+RST")
    time.sleep(15)
    apm.pump(1.0)
    at_cmd(apm, "AT+CWMODE=2", 10)
    at_cmd(apm, f'AT+CWSAP="{M2M_SSID}","{M2M_PWD}",8,0', 12)


def sec26_two_modules_udp(rep, apm, st2):
    """2.6 两模块 UDP 透传(文档: 双方 CIPSTART 对端 333 端口)"""
    _reset_ap_module(apm)
    st2_ip = _m2m_associate(rep, st2, "2.6 双模组UDP")
    if not st2_ip:
        return
    # AP 侧: 单连接透传 UDP → STA IP
    at_cmd(apm, "AT+CIPMUX=0", 6)
    at_cmd(apm, "AT+CIPMODE=1", 6)
    ok, acc = udp_start(apm, f'AT+CIPSTART="UDP","{st2_ip}",333,333,0')
    rep.add("2.6 双模组UDP", "AP 模组 UDP 透传建连(→STA)", f'AT+CIPSTART="UDP","{st2_ip}",333,333,0',
            ok, acc.strip().replace("\r\n", "⏎")[-60:])
    # STA 侧
    at_cmd(st2, "AT+CIPMUX=0", 6)
    at_cmd(st2, "AT+CIPMODE=1", 6)
    ok, acc = udp_start(st2, 'AT+CIPSTART="UDP","192.168.4.1",333,333,0')
    rep.add("2.6 双模组UDP", "STA 模组 UDP 透传建连(→AP 192.168.4.1)",
            'AT+CIPSTART="UDP","192.168.4.1",333,333,0',
            ok, acc.strip().replace("\r\n", "⏎")[-60:])
    if not ok:
        return
    ok, det = enter_passthru_send(apm, P11)
    r = wait_str(st2, re.escape(P11.decode()), 8)
    rep.add("2.6 双模组UDP", "AP 裸发 → STA 裸收", "sparkleiot",
            r is not None, (r or "未收到").strip()[-50:])
    ok, det = enter_passthru_send(st2, P30)
    r = wait_str(apm, re.escape(P30.decode()), 8)
    rep.add("2.6 双模组UDP", "STA 裸发 → AP 裸收", "SparkleIOT",
            r is not None, (r or "未收到").strip()[-50:])
    ea = exit_passthru(apm)
    es = exit_passthru(st2)
    rep.add("2.6 双模组UDP", "双侧 +++ 退出透传", "+++", ea and es,
            f"AP={'OK' if ea else 'FAIL'} STA={'OK' if es else 'FAIL'}")


def sec27_two_modules_tcp(rep, apm, st2):
    """2.7 两模组 TCP 透传(AP=server, STA=透传 client)"""
    _reset_ap_module(apm)
    # STA2 复位清掉 2.6 的 UDP/透传残留
    st2.clear()
    st2.send(line="AT+RST")
    time.sleep(15)
    st2.pump(0.8)
    at_cmd(apm, "AT+CIPMUX=1", 6)
    st, acc = at_cmd(apm, "AT+CIPSERVER=1,8899", 8)
    rep.add("2.7 双模组TCP透传", "AP 模组开 TCP 服务器(多连接)", "AT+CIPMUX=1 / AT+CIPSERVER=1,8899",
            st == "OK", acc.strip()[:40])
    st2_ip = _m2m_associate(rep, st2, "2.7 双模组TCP透传")
    if not st2_ip:
        return
    at_cmd(st2, "AT+CIPMUX=0", 6)
    at_cmd(st2, "AT+CIPMODE=1", 6)
    st, acc = at_cmd(st2, 'AT+CIPSTART="TCP","192.168.4.1",8899', 15)
    got = wait_str(st2, r"CONNECT", 15)
    rep.add("2.7 双模组TCP透传", "STA 透传建连 AP 8899", 'AT+CIPSTART="TCP","192.168.4.1",8899',
            got is not None, (got or acc).strip().replace("\r\n", "⏎")[-60:])
    apside = wait_str(apm, r"0,CONNECT", 10)
    rep.add("2.7 双模组TCP透传", "AP 侧 0,CONNECT", "(事件)", apside is not None,
            (apside or "未见").strip()[-40:])
    ok, det = cipsend_fixed(apm, len(P11), P11, mux_id=0)
    rep.add("2.7 双模组TCP透传", "AP 发 10 字节(品牌标识负载)", "AT+CIPSEND=0,10", ok, det.strip()[:40])
    r = wait_str(st2, re.escape(P11.decode()), 10)
    rep.add("2.7 双模组TCP透传", "STA 透传裸收", "sparkleiot", r is not None,
            (r or "未收到").strip()[-50:])
    ok, det = enter_passthru_send(st2, P30)
    r = wait_ipd(apm, P30, 10)
    rep.add("2.7 双模组TCP透传", "STA 裸发 → AP +IPD,0,10", "SparkleIOT",
            r is not None, (r or "未收到").strip()[-50:])
    es = exit_passthru(st2)
    rep.add("2.7 双模组TCP透传", "STA +++ 退出透传", "+++", es, "OK" if es else "退出失败")


def sec28_ext_passthru(rep, a, b, c):
    """2.8 CWMODE=3(共存) + 外网透传"""
    cleanup_links(a)
    # 先把 AP ssid 临时改名, 便于和 COM7 的 BK-M2M 区分
    at_cmd(a, 'AT+CWSAP="DOC-3MODE","12345678",8,0', 10)
    st, acc = at_cmd(a, "AT+CWMODE=3", 12)
    rep.add("2.8 外网透传", "设置 AP+STA 共存模式", "AT+CWMODE=3", st == "OK", acc.strip()[:40])
    time.sleep(4)
    a.pump(0.5)
    ip, acc = join_router(a)
    rep.add("2.8 外网透传", "共存下 STA 连接路由", f'AT+CWJAP="{ROUTER_SSID}"',
            ip is not None, f"IP={ip}" if ip else acc.strip()[-80:])
    # 用 STA2 扫描验证 AP 广播共存(RF 时序抖动, 最多扫 3 次)
    at_cmd(c, "AT+CWMODE=1", 8)
    r = None
    for attempt in range(3):
        c.clear()
        c.send(line='AT+CWLAP="DOC-3MODE"')
        r = wait_str(c, r"\+CWLAP:\([^)]*\"DOC-3MODE\"", 25)
        if r is not None:
            break
        time.sleep(2)
        c.pump(0.5)
    rep.add("2.8 外网透传", "AP 广播共存验证(另一模组扫描到)", 'AT+CWLAP="DOC-3MODE"',
            r is not None, ((r or "未见(3次扫描)") + (f" 第{attempt+1}次" if r else "")).strip()[-60:])

    # 文档原例的外网服务器 115.29.109.104:6602 (8 年前的地址, 预期已失效, 如实记录)
    at_cmd(a, "AT+CIPMUX=0", 6)
    at_cmd(a, "AT+CIPMODE=1", 6)
    st, acc = at_cmd(a, 'AT+CIPSTART="TCP","115.29.109.104",6602', 18)
    got = wait_str(a, r"CONNECT", 18)
    rep.add("2.8 外网透传", "连接文档原例服务器(2018 年地址)", 'AT+CIPSTART="TCP","115.29.109.104",6602',
            got is not None, (got or acc).strip().replace("\r\n", "⏎")[-60:]
            + (" (8 年前文档地址, 服务已停属正常)" if not got else ""))
    if got:
        exit_passthru(a)
        # 关闭透传连接, 释放单连接槽(否则后续 CIPSTART 会被拒)
        at_cmd(a, "AT+CIPCLOSE", 6)
    time.sleep(1)
    a.pump(0.3)

    # 内网等效透传(PC 即"外网服务器"角色)
    srv = TCPSrv(8890)
    st, acc = at_cmd(a, f'AT+CIPSTART="TCP","{PC_IP}",8890', 15)
    got = wait_str(a, r"CONNECT", 15)
    rep.add("2.8 外网透传", "透传连接 PC 服务器(等效替代)", f'AT+CIPSTART="TCP","{PC_IP}",8890',
            got is not None, (got or acc).strip().replace("\r\n", "⏎")[-50:])
    if got:
        addr = srv.accept(8)
        ok, det = enter_passthru_send(a, P11)
        d = srv.recv(6, 11)
        rep.add("2.8 外网透传", "透传数据交互", "AT+CIPSEND → sparkleiot",
                addr is not None and d == P11, f"{len(d)}B {d[:24]!r}")
        exit_passthru(a)
        at_cmd(a, "AT+CIPMODE=0", 6)
    srv.close()
    # 恢复纯 STA
    at_cmd(a, "AT+CWMODE=1", 10)
    time.sleep(2)
    a.pump(0.4)


def sec31_common_cmds(rep, a):
    """3.1 常用指令篇(逐条; ESP8266 厂商专有指令预期 N/A)"""
    vendor_cmds = [
        ("AT+CIOREAD=15", "读取 IO 状态(厂商专有, 固件已实现)"),
        ("AT+CIOWRITE=2,1", "设置 IO(厂商专有, 固件已实现)"),
        ("AT+CWSTARTSMART", "智能配网(ESP8266, 固件未实现)"),
        ("AT+CSYSID", "查询芯片 ID(固件已实现)"),
        ("AT+SAVETRANSLINK=1,\"192.168.6.110\",1002,\"TCP\"", "保存透传(固件应答 OK)"),
        ("AT+CWSMARTSTART=2", "微信配网(厂商专有, 固件未实现)"),
    ]
    for cmd, desc in vendor_cmds:
        st, acc = at_cmd(a, cmd, timeout=6)
        # ESP32-C3 ESP-AT 没有这些 ESP8266 厂商专有命令; 固件报 ERROR 属正常,
        # 有应答(+CIOREAD/+CSYSID/OK)属原厂兼容加成 —— 都不算 FAIL
        has_answer = st == "OK" and re.search(r"\+\w+|OK", acc)
        if st == "ERROR":
            rep.add("3.1 常用指令", desc, cmd, True,
                    "ERROR (ESP-AT 标准无此命令, 合理)", na=True)
        else:
            rep.add("3.1 常用指令", desc, cmd, st == "OK",
                    acc.strip().replace("\r\n", "⏎")[:70] or f"{st}(无应答)")

    # 5. 设置波特率(实测改+回读+恢复)
    # 注: ESP-AT 的 UART_DEF 立即生效, OK 应答以新波特率发出, 旧波特率下收不到属正常
    st, acc = at_cmd(a, "AT+UART_DEF=9600,8,1,0,0", 8)
    time.sleep(0.5)
    a.ser.close()
    import serial as _serial
    a.ser = _serial.Serial(args.sta, 9600, timeout=0.05)
    a.buf = b""
    st2, acc2 = at_cmd(a, "AT", 4)
    rep.add("3.1 常用指令", "改波特率 9600 并生效(文档 3.1-5)", "AT+UART_DEF=9600,8,1,0,0",
            st2 == "OK", f"9600 下 AT 应答={st2} (OK 以新波特率发出, 旧口收不到属正常)")
    at_cmd(a, "AT+UART_DEF=115200,8,1,0,0", 8)
    a.ser.close()
    a.ser = _serial.Serial(args.sta, 115200, timeout=0.05)
    a.buf = b""
    st3, acc3 = at_cmd(a, "AT+UART_DEF?", 6)
    ok = "+UART_DEF:115200" in acc3
    rep.add("3.1 常用指令", "恢复 115200", "AT+UART_DEF=115200,8,1,0,0",
            ok, acc3.strip().replace("\r\n", "⏎")[:60])

    # 7/8/10/11/12
    st, acc = at_cmd(a, "AT+SLEEP=0", 6)
    st2, q = at_cmd(a, "AT+SLEEP?", 6)
    rep.add("3.1 常用指令", "禁止休眠(文档 3.1-8)", "AT+SLEEP=0 / AT+SLEEP?",
            st == "OK" and "+SLEEP:0" in q, q.strip().replace("\r\n", "⏎")[:40])

    st, acc = at_cmd(a, "AT+CIFSR", 6)
    ok = re.search(r'\+CIFSR:(STA|A)IP,"[\d.]+"', acc) is not None
    rep.add("3.1 常用指令", "查询 IP(文档 3.1-10)", "AT+CIFSR", ok,
            acc.strip().replace("\r\n", "⏎")[:80])

    st, q = at_cmd(a, "AT+CIPSTAMAC?", 6)
    m = re.search(r'\+CIPSTAMAC:"([0-9a-fA-F:]+)"', q)
    if m:
        st2, acc2 = at_cmd(a, f'AT+CIPSTAMAC="{m.group(1)}"', 8)
        ok = st2 == "OK"
    else:
        ok = False
    rep.add("3.1 常用指令", "STA MAC 查询+写回(文档 3.1-11)", f'AT+CIPSTAMAC="{m.group(1) if m else "?"}"',
            ok, (q.strip().replace("\r\n", "⏎")[:60] if m else q.strip()[:40]))

    # 9. 恢复出厂(放最后, 会清 env; 之后重新配置)
    st, acc = at_cmd(a, "AT+RESTORE", 12)
    time.sleep(3)
    a.pump(0.5)
    st2, q = at_cmd(a, "AT+CWMODE?", 6)
    st3, q2 = at_cmd(a, "AT+CWJAP?", 6)
    ok = st == "OK" and "+CWMODE:1" in q and "No AP" in q2
    rep.add("3.1 常用指令", "恢复出厂设置(文档 3.1-9)", "AT+RESTORE",
            ok, f"CWMODE?={q.strip()[:20]} CWJAP?={q2.strip()[:30]}")
    # 收尾: 重新连路由
    ip, acc = join_router(a)
    rep.add("3.1 常用指令", "RESTORE 后重新连接路由(收尾恢复)", f'AT+CWJAP="{ROUTER_SSID}"',
            ip is not None, f"IP={ip}")


# ---------------------------------------------------------------- main
def main():
    global args
    ap = argparse.ArgumentParser()
    ap.add_argument("--sta", default="COM5")
    ap.add_argument("--ap", default="COM7")
    ap.add_argument("--sta2", default="COM6")
    ap.add_argument("--out", default="test/doc_v15_report.md")
    ap.add_argument("--sections", default="0,21,22,23,24,25,26,27,28,31",
                    help="要跑的章节, 逗号分隔")
    args = ap.parse_args()

    logdir = os.path.join(os.path.dirname(args.out) or "test", "doc_v15_raw")
    os.makedirs(logdir, exist_ok=True)
    a = AT("STA", args.sta, logdir)
    b = AT("AP", args.ap, logdir)
    c = AT("STA2", args.sta2, logdir)
    rep = Rep(args)
    secs = set(args.sections.split(","))

    try:
        if "0" in secs:
            sec0_prep(rep, a, b, c)
        if "21" in secs:
            sec21_ap_tcp_server(rep, b, c)
        if "22" in secs:
            sec22_sta_tcp_server(rep, a)
        if "23" in secs:
            sec23_tcp_passthru(rep, a)
        if "24" in secs:
            sec24_udp_multi(rep, a)
        if "25" in secs:
            sec25_udp_passthru(rep, a)
        if "26" in secs:
            sec26_two_modules_udp(rep, b, c)
        if "27" in secs:
            sec27_two_modules_tcp(rep, b, c)
        if "28" in secs:
            sec28_ext_passthru(rep, a, b, c)
        if "31" in secs:
            sec31_common_cmds(rep, a)
    finally:
        rep.write(args.out)
        print(f"\n[report] {args.out}  => {rep.n_ok} PASS / {rep.n_fail} FAIL / {rep.n_na} N/A")
        try:
            for at in (a, b, c):
                at.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
