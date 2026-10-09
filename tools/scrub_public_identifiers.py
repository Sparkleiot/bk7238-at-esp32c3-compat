"""公开仓库前的隐私脱敏：把真实 BSSID / MAC / SSID 换成中性占位值。

只处理"可识别到具体设备或家庭网络"的标识：
  - 真实 BSSID（路由器 MAC）
  - 模组 STA MAC
  - 家庭/办公 WiFi 的 SSID
保留 ESP-AT 文档语义所需的格式（xx:xx:xx:xx:xx:xx）。

映射表放在 tools/privacy_map.local.py —— 该文件**不入 Git**
（含真实值），所以本脚本自身可以安全公开。

用法：
    python tools/scrub_public_identifiers.py            # 脱敏 git 已跟踪的文件
    python tools/scrub_public_identifiers.py --check    # 只检查不修改，退出码 1 = 有残留
"""
import argparse
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MAP_FILE = os.path.join(HERE, "privacy_map.local.py")


def load_map():
    """从不入库的本地映射表加载替换规则。"""
    if not os.path.isfile(MAP_FILE):
        print("找不到映射表: %s" % MAP_FILE, file=sys.stderr)
        print("请参照本目录下的同名模板创建它（该文件已被 .gitignore 排除）。",
              file=sys.stderr)
        sys.exit(2)
    ns = {}
    with open(MAP_FILE, encoding="utf-8") as f:
        exec(compile(f.read(), MAP_FILE, "exec"), ns)
    return ns.get("REPL", {}), ns.get("SSID_REPL", {})


def build_patterns(repl, ssid_repl):
    """把映射表编译成 (compiled_bytes_regex, replacement_str) 列表。

    对**字节**编译：直接处理原始字节，避免任何解码/编码环节把SDK 源的
    CRLF 行尾改掉（这是本项目反复踩过的坑，见 README §10.3）。
    """
    pats = []
    for real, fake in repl.items():
        pats.append((re.compile(re.escape(real.encode("utf-8")), re.IGNORECASE), fake))
    for real, fake in ssid_repl.items():
        # SSID：前后不能是字母/数字/下划线/连字符，避免误伤子串
        pats.append((
            re.compile(rb"(?<![A-Za-z0-9_-])" + re.escape(real.encode("utf-8"))
                       + rb"(?![A-Za-z0-9_-])"),
            fake,
        ))
    return pats


def scrub_bytes(raw, pats, skip_paths=()):
    """对原始字节做替换，**不做任何换行转换**（保住 SDK 源的 CRLF）。"""
    hits = 0
    for pat, fake in pats:
        raw, n = pat.subn(fake.encode("utf-8"), raw)
        hits += n
    return raw, hits


# 这些文件里出现的标识符是**文档说明**（例如"原SSID 已被替换为 MyHomeWiFi"），
# 属于要公开的信息本身，不应脱敏。也会让本脚本不会命中自己的注释。
SKIP_FILES = ("README.md", "tools/scrub_public_identifiers.py")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="只检查不修改；有残留时退出码 1")
    args = ap.parse_args()

    os.chdir(os.path.dirname(HERE))  # 项目根

    repl, ssid_repl = load_map()
    pats = build_patterns(repl, ssid_repl)
    if not pats:
        print("映射表为空，无事可做。", file=sys.stderr)
        return 0

    files = subprocess.run(
        ["git", "ls-files", "-z"], capture_output=True, check=True,
    ).stdout.split(b"\0")
    files = [f.decode("utf-8") for f in files if f]

    total = 0
    touched = []
    for path in files:
        if not os.path.isfile(path):
            continue
        if path.replace("\\", "/") in SKIP_FILES:
            continue
        with open(path, "rb") as f:
            raw = f.read()
        new, n = scrub_bytes(raw, pats)
        if n == 0:
            continue
        total += n
        touched.append((path, n))
        if not args.check:
            with open(path, "wb") as f:
                f.write(new)

    verb = "检查到残留" if args.check else "脱敏完成"
    print("%s，共 %d 处，涉及 %d 个文件：" % (verb, total, len(touched)))
    for path, n in touched:
        print("  %-45s %d 处" % (path, n))
    if not touched:
        print("  （无命中）")

    return 1 if (args.check and total) else 0


if __name__ == "__main__":
    sys.exit(main())
