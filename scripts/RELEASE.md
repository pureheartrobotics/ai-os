# 发布说明

## 当前状态

| 包 | 线上版本 | 地址 |
| --- | --- | --- |
| `ai-os-desktop` (PyPI) | 0.1.0 | https://pypi.org/project/ai-os-desktop/ |
| `dsh-ai-os` (npm) | 0.3.3（latest） | https://www.npmjs.com/package/dsh-ai-os |

插件市场索引（随 npm 包发布）：

```
https://cdn.jsdelivr.net/npm/dsh-ai-os/market-index.json        固定地址，始终是最新版
https://unpkg.com/dsh-ai-os@<version>/market-index.json         备用，固定到某个版本
```

## npm 镜像

本机 `.npmrc` 用 `registry=https://registry.npmmirror.com/`（淘宝新域名，旧的 `registry.npm.taobao.org` 已废弃）。
**npmmirror 是只读镜像，不能发布**，发布时一律显式指定 `--registry https://registry.npmjs.org/`。

## 发版流程

### npm（每个版本都要 staging）

这个账号的 token 只能暂存，直接 `npm publish` 会报：

```
npm error 403 This token can only publish to a staging area. (E_STAGE_REQUIRED)
```

一条命令做完暂存：

```powershell
# 1. 改 integrations/dsh-ai-os/package.json 的 version
# 2. 校验 token → 重建索引 → 按 DSH 规则校验索引 → npm stage publish
powershell -File scripts\release-npm.ps1 -Token npm_xxx
# 3. 约 1 分钟校验完成后，用 2FA（硬件密钥）在网页点「批准」
#    https://www.npmjs.com/settings/mr.z197009938/packages
# 4. 批准后刷新 jsDelivr 缓存，让固定索引地址指向新版本
powershell -File scripts\release-npm.ps1 -PurgeCdn
```

token 只写进临时 npmrc，脚本结束就删除，不会落到 `~/.npmrc`。

### PyPI

```powershell
powershell -File scripts\publish.ps1 -Only pypi -PypiToken pypi-...
```

`publish.ps1` 不带 `-Only` 时会先发 PyPI，再调用 `release-npm.ps1` 暂存 npm。

### 已知的坑

1. **`npm stage` 需要 npm ≥ 12**，本机自带的是 11.x。`release-npm.ps1` 首次运行会自动装一份到 `%TEMP%\npm12`。
   npm 12 要求 node ≥ 24.15，本机 24.12 只会告警，功能可用。
2. **批准强制要求账号启用 2FA。** 没开 2FA 时 `npm stage approve` 不提示 2FA，而是返回误导性的
   `404 staged version "..." not found`。
3. **暂存的版本会占用版本号**：暂存了 `0.3.3` 就不能再发同一个 `0.3.3`，要先在网页拒绝或换版本号。
4. **DSH 拒绝重定向**，索引地址必须直接返回 200：

   | 地址 | 结果 |
   | --- | --- |
   | `cdn.jsdelivr.net/npm/dsh-ai-os/market-index.json` | ✅ 200，但 CDN 缓存最长 12 小时，发版后要 `-PurgeCdn` |
   | `unpkg.com/dsh-ai-os@<version>/market-index.json` | ✅ 200 |
   | `unpkg.com/dsh-ai-os/market-index.json` | ❌ 302 |
   | `registry.npmmirror.com/dsh-ai-os/latest/files/...` | ❌ 302，指定版本时 403 |

5. 已发布的版本无法修改。索引、README、详情文档都随包发布，改了就要发新版本才会生效。

## 发布前检查

- `pyproject.toml` 的 `version` 与 `integrations/dsh-ai-os/package.json` 的 `version` 都已改成新版本号
- `python -m twine check dist/*` 通过
- `npm pack --dry-run` 共 14 个文件：`LICENSE`、`README.md`、`cordis.patch.yml`、`docs/`（两份详情 + 两张预览图）、
  `icon.svg`、`lib/client.js`、`lib/index.js`、`locale/en.json`、`locale/zh.json`、`market-index.json`、`package.json`

## 发布后验证

```powershell
npm view dsh-ai-os version --registry https://registry.npmjs.org/
pip install ai-os-desktop --upgrade
```

干净环境走一遍：

```sh
pip install ai-os-desktop
dsh plugin add dsh-ai-os
```

按 **F8** 说「打开记事本」，确认有语音卡片、有回复朗读、插件页「桌面操作」是绿色。

插件市场验收：

1. 插件 → 打开实验性插件「自定义插件索引」→ 发现 → 添加索引源 → 粘贴固定索引地址
2. 列表里出现「AI OS · 语音操作电脑」，分类「电脑操作」，标签「免手操作 / MCP 工具 / Windows」，版本是刚发布的版本
3. 点进去能看到详情文档（来自 `locale/*.json` 的 `meta.detail`），点安装能装上
