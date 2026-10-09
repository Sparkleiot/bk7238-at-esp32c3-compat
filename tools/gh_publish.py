#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gh_publish.py —— BK7238 AT 固件一键发布到 GitHub 公开仓库。

做四件事：
  1. 用 API 创建远端空仓库（若不存在）
  2. git push main + tag
  3. 创建 GitHub Release（附固件与报告）
  4. 回读校验：仓库可见性 / 默认分支 / tag / Release / 文件数

用法（推荐：凭据走环境变量，不落盘、不进 shell 历史）：

  export GH_TOKEN=ghp_xxxxxxxxxxxx        # 或 GITHUB_TOKEN
  python tools/gh_publish.py --owner sparkleiot --repo bk7238-at-esp32c3-compat

只创建仓库不推送：
  python tools/gh_publish.py --owner <o> --repo <r> --no-push

依赖：仅标准库（urllib）。git 命令走 subprocess。
"""

import argparse
import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com"
UA = "bk7238-at-publisher/1.0"


# ---------------------------------------------------------------- helpers

def die(msg, code=1):
    print("[FAIL] " + msg, file=sys.stderr)
    sys.exit(code)


def info(msg):
    print("[ .. ] " + msg, flush=True)


def ok(msg):
    print("[ OK ] " + msg, flush=True)


def api(method, path, token, body=None, raw=False):
    """调用 GitHub API。返回 (status, parsed_json_or_bytes)。"""
    url = API + path
    data = None
    headers = {
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": UA,
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = resp.read()
            if raw:
                return resp.status, payload
            return resp.status, (json.loads(payload) if payload else {})
    except urllib.error.HTTPError as e:
        payload = e.read()
        try:
            return e.code, json.loads(payload)
        except Exception:
            return e.code, {"raw": payload[:400].decode("utf-8", "replace")}


def git(*args, check=True, capture=True):
    cmd = ["git"] + list(args)
    info("git " + " ".join(args[:3]) + (" ..." if len(args) > 3 else ""))
    p = subprocess.run(cmd, capture_output=capture, text=True,
                       encoding="utf-8", errors="replace")
    if check and p.returncode != 0:
        out = (p.stdout or "") + (p.stderr or "")
        die("git %s 失败 (rc=%d)\n%s" % (" ".join(args), p.returncode, out[-2000:]))
    return p


# ---------------------------------------------------------------- steps

def check_token(token):
    st, data = api("GET", "/user", token)
    if st != 200:
        die("Token 无效或已过期（GitHub 返回 %s）。请重新生成 PAT。" % st)
    ok("Token 有效，账号 = %s" % data.get("login"))
    return data


def check_scope(token):
    """检查 token 是否有 repo / public_repo 写权限。"""
    st, data = api("GET", "/user?scope=repo,public_repo", token, raw=True)
    hdr = b""
    try:
        # 重新请求拿 header（api() 不回传 header，这里简单二次调用）
        req = urllib.request.Request(API + "/user", headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "User-Agent": UA,
        }, method="GET")
        with urllib.request.urlopen(req, timeout=30) as resp:
            hdr = resp.headers
    except Exception as e:
        info("无法读取 rate_limit 头（%s），跳过 scope 检查" % e)
    sc = hdr.get("X-OAuth-Scopes", "") if hdr else ""
    if sc:
        info("Token scopes: %s" % sc)
    return sc


def ensure_repo(owner, repo, token, private=False, description=None):
    """仓库不存在则创建；已存在则核对可见性。返回 (是否新建, 仓库信息)。"""
    full = "%s/%s" % (owner, repo)
    st, data = api("GET", "/repos/" + full, token)
    if st == 200:
        ok("仓库已存在：%s（visibility=%s, private=%s）"
           % (full, data.get("visibility"), data.get("private")))
        if data.get("private") != private:
            st2, d2 = api("PATCH", "/repos/" + full, token,
                          {"private": private, "description": description or data.get("description")})
            if st2 == 200:
                ok("已把可见性改为 %s" % ("private" if private else "public"))
            else:
                info("改可见性失败（%s），需要仓库 admin 权限：%s" % (st2, d2))
        return False, data
    if st != 404:
        die("查询仓库失败：HTTP %s %s" % (st, data))

    info("仓库 %s 不存在，正在创建……" % full)
    body = {
        "name": repo,
        "description": description or "ESP32-C3 / ESP-AT 兼容 AT 固件（Beken BK7238 / Sparkleiot XH-WB3S）",
        "private": private,
        "auto_init": False,          # 不要 README，避免与本地冲突
        "has_issues": True,
        "has_wiki": False,
        "has_projects": False,
    }
    st, data = api("POST", "/user/repos", token, body)
    if st == 201:
        ok("已创建仓库 %s（%s）" % (full, "private" if private else "public"))
        return True, data
    if st == 422:
        die("创建仓库返回 422（多半是名字已存在或名称非法）：%s" % data)
    if st == 403:
        die("创建仓库被拒（403）：Token 缺 `public_repo`/`repo` 权限，或该账号不能建公开仓库。\n%s" % data)
    die("创建仓库失败：HTTP %s %s" % (st, data))


def set_topics(owner, repo, token, topics):
    st, _ = api("PUT", "/repos/%s/%s/topics" % (owner, repo), token, {"names": topics})
    if st in (200, 204):
        ok("已设置 topics：%s" % ", ".join(topics))
    else:
        info("设置 topics 失败（HTTP %s），可忽略" % st)


def do_push(remote_url, token, branch, tag):
    """用一次性 extraheader 做认证，不写入磁盘凭据。"""
    hdr = "Authorization: Basic " + base64.b64encode(
        ("x-access-token:" + token).encode()).decode()

    # 记下原remote，建仓/推送失败时要还原，不能把仓库 config 改成半成品状态
    p_old = git("remote", "get-url", "origin", check=False)
    old_url = (p_old.stdout or "").strip() if p_old.returncode == 0 else None

    def push_once():
        p = git("-c", "http.sslBackend=openssl", "-c", "http.extraheader=" + hdr,
                "push", "-u", "origin", branch, check=False)
        if p.returncode != 0:
            # 再退回默认 TLS 后端试一次（部分环境openssl 后端反而不行）
            info("openssl 后端 push 失败，换默认后端重试……")
            p = git("-c", "http.extraheader=" + hdr, "push", "-u", "origin", branch, check=False)
        return p

    try:
        git("remote", "set-url", "origin", remote_url)
        info("推送到 %s" % remote_url)
        p = push_once()
        if p.returncode != 0:
            die("push main 失败：\n%s" % ((p.stdout or "") + (p.stderr or ""))[-2000:])
        ok("已推送分支 %s" % branch)

        if tag:
            p = git("-c", "http.sslBackend=openssl", "-c", "http.extraheader=" + hdr,
                    "push", "origin", tag, check=False)
            if p.returncode != 0:
                info("推 tag 失败（可稍后手动补）：\n%s" % ((p.stdout or "") + (p.stderr or ""))[-600:])
            else:
                ok("已推送标签 %s" % tag)
    except SystemExit:
        # 推送失败：把origin 还原回去，别留半成品
        if old_url:
            git("remote", "set-url", "origin", old_url, check=False)
            info("已把 origin 还原为 %s" % old_url)
        raise


def ensure_release(owner, repo, token, tag, name, body_md, assets):
    st, data = api("GET", "/repos/%s/%s/releases/tags/%s" % (owner, repo, tag), token)
    if st == 200:
        ok("Release %s 已存在（id=%s），更新其说明" % (tag, data.get("id")))
        rid = data["id"]
        st, data = api("PATCH", "/repos/%s/%s/releases/%s" % (owner, repo, rid),
                       token, {"name": name, "body": body_md, "draft": False, "prerelease": False})
        if st != 200:
            die("更新 Release 失败：HTTP %s %s" % (st, data))
    else:
        st, data = api("POST", "/repos/%s/%s/releases" % (owner, repo), token, {
            "tag_name": tag, "name": name, "body": body_md,
            "draft": False, "prerelease": False,
        })
        if st != 201:
            die("创建 Release 失败：HTTP %s %s" % (st, data))
        rid = data["id"]
        ok("已创建 Release %s（id=%s）" % (tag, rid))

    # 上传附件（已存在同名 asset 则删了重传）
    for path in assets:
        if not os.path.isfile(path):
            info("附件不存在，跳过：%s" % path)
            continue
        fname = os.path.basename(path)
        st, existing = api("GET", "/repos/%s/%s/releases/%s/assets" % (owner, repo, rid), token)
        if st == 200:
            for a in existing:
                if a.get("name") == fname:
                    api("DELETE", "/repos/%s/%s/releases/assets/%s"
                        % (owner, repo, a["id"]), token)
                    info("删除同名旧附件 %s" % fname)
        url = "https://uploads.github.com/repos/%s/%s/releases/%s/assets?name=%s" % (
            owner, repo, rid, urllib.parse.quote(fname))
        data = open(path, "rb").read()
        req = urllib.request.Request(url, data=data, method="POST", headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "User-Agent": UA,
            "Content-Type": "application/octet-stream",
            "Content-Length": str(len(data)),
        })
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                ok("已上传附件 %s（%d 字节）" % (fname, len(data)))
        except urllib.error.HTTPError as e:
            info("附件 %s 上传失败：HTTP %s %s" % (fname, e.code, e.read()[:200]))
    return rid


def verify(owner, repo, token, tag, branch, expect_private=False):
    print("\n================ 回读校验 ================")
    full = "%s/%s" % (owner, repo)
    st, d = api("GET", "/repos/" + full, token)
    if st != 200:
        die("校验失败：仓库读不到 %s" % full)
    ok("仓库存在，可见性 = %s（private=%s）" % (d.get("visibility"), d.get("private")))
    if d.get("private") != expect_private:
        die("可见性不符合预期：private=%s" % d.get("private"))
    ok("默认分支 = %s" % d.get("default_branch"))

    st, refs = api("GET", "/repos/%s/git/refs/tags" % full, token)
    tags = [r["ref"].split("/")[-1] for r in refs] if st == 200 else []
    if tag in tags:
        ok("标签存在：%s" % tag)
    else:
        info("⚠ 标签列表：%s" % (tags or "（空）"))

    st, rel = api("GET", "/repos/%s/releases/tags/%s" % (full, tag), token)
    if st == 200:
        ok("Release「%s」已发布，下载数=%s，附件=%s"
           % (rel.get("name"), rel.get("download_count"),
              [a["name"] for a in rel.get("assets", [])]))
        print("---- Release 正文 ----")
        print((rel.get("body") or "")[:1200])
    else:
        info("⚠ 未找到 Release %s（HTTP %s）" % (tag, st))

    st, tree = api("GET", "/repos/%s/git/trees/%s?recursive=1" % (full, d.get("default_branch")), token)
    if st == 200:
        n = len([t for t in tree.get("tree", []) if t["type"] == "blob"])
        ok("默认分支共 %d 个文件，truncated=%s" % (n, tree.get("truncated")))
    print("=========================================\n")
    print("公开访问地址：https://github.com/%s" % full)


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="BK7238 AT 固件一键发布到 GitHub")
    ap.add_argument("--owner", default="sparkleiot")
    ap.add_argument("--repo", default="bk7238-at-esp32c3-compat")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--tag", default="v1.0.0")
    ap.add_argument("--token", help="PAT（不传则读环境变量 GH_TOKEN / GITHUB_TOKEN）")
    ap.add_argument("--private", action="store_true", help="建成私有仓库（默认公开）")
    ap.add_argument("--no-push", action="store_true", help="只建仓不推送")
    ap.add_argument("--no-release", action="store_true", help="不建 Release")
    ap.add_argument("--description")
    ap.add_argument("--release-name")
    ap.add_argument("--release-body", help="从文件读取 Release 正文（UTF-8）")
    ap.add_argument("--asset", action="append", default=[],
                    help="Release 附件，可多次指定")
    a = ap.parse_args()

    token = a.token or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        die("没有找到 token。请：\n"
            "  export GH_TOKEN=ghp_你的令牌\n"
            "或 python tools/gh_publish.py --token ghp_你的令牌 ...")

    who = check_token(token)
    check_scope(token)

    created, repo_info = ensure_repo(a.owner, a.repo, token, a.private, a.description)
    set_topics(a.owner, a.repo, token,
               ["esp32-c3", "esp-at", "at-command", "beken", "bk7238",
                "x-wb3s", "sparkleiot", "wifi", "embedded", "firmware"])

    if not a.no_push:
        url = repo_info.get("clone_url") or (
            "https://github.com/%s/%s.git" % (a.owner, a.repo))
        do_push(url, token, a.branch, a.tag)

    if not a.no_release and not a.no_push:
        body = ""
        if a.release_body and os.path.isfile(a.release_body):
            body = open(a.release_body, encoding="utf-8").read()
        name = a.release_name or ("%s —— ESP32-C3 / ESP-AT 兼容 AT 固件" % a.tag)
        ensure_release(a.owner, a.repo, token, a.tag, name, body, a.asset)

    verify(a.owner, a.repo, token, a.tag, a.branch, a.private)
    print("发布流程完成。账号 %s（%s）" % (who.get("login"), who.get("name") or "—"))


if __name__ == "__main__":
    main()