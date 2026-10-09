# 发布到 GitHub

本文档给**第一次执行发布的人**。全流程约 3 分钟，不需要编程基础。

目标：把本项目上传到 GitHub 公开仓库 `sparkleiot/bk7238-at-esp32c3-compat`，
让所有人都能看到、克隆、下载。

> 仓库创建、推送、Release 三件事已全部自动化，**不需要手工去网页建仓库**。

---

## 前置条件

- 本机已装 Git（`git --version` 有输出即可）
- 项目已完成 V1.0.0 整理（当前状态：本地 1 个提交 + `v1.0.0` 标签，工作树干净）

---

## 第 1 步：生成访问令牌（约 40 秒）

> ⚠️ **GitHub 从 2021 年起永久停用了账号密码推送**，2020 年起也停用了 API 的密码认证。
> 这是服务端硬性策略，**账号密码在这里用不上**，必须用访问令牌（PAT）代替。
> 好消息：有了 PAT，建仓 + 推送 + Release 全自动，不用手动点网页。

打开：

```
https://github.com/settings/tokens/new
```

操作：

1. Note 填 `bk7238-publish`
2. Expiration 选`90 days`
3. **只勾 `public_repo`** 这一项就够（创建公开仓库 + 推送代码）
   - 若要推到私有仓库才需要 `repo`
4. 滚到底点 **Generate token**
5. **立刻复制那串 `ghp_...`** —— 只显示这一次，关掉页面就再也看不到了

---

## 第 2 步：一键发布（1 分钟）

在项目目录打开 **Git Bash**，执行：

```bash
cd C:/Users/99471/Desktop/BK7238_AT
export GH_TOKEN=ghp_第1步复制的令牌
bash tools/publish.sh
```

脚本会依次完成：

| 步骤 | 动作 |
|------|------|
| 1 | 发布前自检：脱敏检查 + `modified/`↔SDK 同步 + 补丁字节级复现 |
| 2 | 调GitHub API **创建公开仓库**（已存在则跳过并核对可见性） |
| 3 | 设置 topics 标签 |
| 4 | `git push -u origin main` |
| 5 | `git push origin v1.0.0` |
| 6 | 创建 Release，正文取 `docs/RELEASE_V1.0.0.md`，附 2 个固件 |
| 7 | 回读校验：可见性 / 默认分支 / tag / Release / 文件数 |
| 8 | `unset GH_TOKEN`，凭据从当前 shell 清除 |

结束时会打印公开访问地址。

### 凭据安全说明

- `GH_TOKEN` 只存在于当前 shell 的环境变量，脚本结束即 `unset`
- 脚本**不会**写入 `~/.git-credentials`、**不会**写进仓库的 `.git/config`
- git 认证走一次性 `http.extraheader`（内存中的 HTTP 头），不落盘

### 单独分步执行（想看每一步细节时）

```bash
# 只建仓不推送
python tools/gh_publish.py --no-push

# 换仓库名/ 私有仓
OWNER=sparkleiot REPO=my-repo bash tools/publish.sh
```

---

## 第 3 步：确认发布成功

打开：

```
https://github.com/sparkleiot/bk7238-at-esp32c3-compat
```

逐项核对：

- [ ] 仓库页面能打开，别人也能访问（**不是** 404，也不是要求登录）
- [ ] 文件列表里有 `README.md`、`docs/`、`src/`、`tools/`、`firmware/`、`test/`
- [ ] 右侧 **Releases** 里能看到 `v1.0.0`，且有 2 个固件附件
- [ ] README 标题下方能看到版本与「供用户测试」的定位说明

**最可靠的验证**：用浏览器**无痕窗口**打开上面的地址，能正常看到就说明确实是公开的。

---

## 常见报错对照

| 报错 | 含义 | 处理 |
|------|------|------|
| `Token 无效或已过期` | PAT 填错、已过期或被撤销 | 回第 1 步重新生成 |
| `HTTP 403`（建仓时） | Token 缺 `public_repo` 权限 | 重新生成并确认勾选 |
| `HTTP 422`（建仓时） | 仓库名已存在，或名称非法 | 换`--repo` 参数 |
| `schannel: failed to receive handshake` | 本机 Git 的 TLS 后端与代理不兼容 | 脚本已内置 openssl 回退，无需处理 |
| `could not read Username` | 网络已通，缺凭据 | 检查 `export GH_TOKEN=` 是否成功 |
| `remote: Repository not found` | 远端仓库没建成 | 看脚本输出里建仓那步是否报 403/422 |

> 本机实测：GitHub **API 可达**（`curl api.github.com` 返回 200），
> 网络层没问题，卡点只在凭据。

---

## 发布后要不要删掉令牌？

发布完成后建议去 https://github.com/settings/tokens 把这个 token 删掉或改短有效期，
反正下次发布重新生成一个 30 秒的事。