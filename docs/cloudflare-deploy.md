# Cloudflare 部署

`autopilot deploy` 把项目发布到 Cloudflare。部署不是 agent 任务，而是一条
shell 命令，它的**成功**才是 `launched` 状态成立的理由。

完整参考见 [local-usage.md](local-usage.md#9-deploying-to-cloudflare)；本文只讲
Cloudflare 特有的部分。

---

## 1. 它插在流程的哪里

```
release_pending
  ⏸ GATE before_production_release      ← 你批准上生产
  🚀 wrangler deploy                    ← pre-transition action
  → launched                            ← 只有部署成功才记录
```

这个顺序是有意的：部署失败时项目**留在 `release_pending`**，没有 `deployment`
产物，可以重试，绝不会被谎报为已上线。

---

## 2. 凭据

需要两个值：

| 名称 | 从哪来 |
|---|---|
| `CLOUDFLARE_API_TOKEN` | Cloudflare Dashboard → My Profile → API Tokens → Create Token，模板选 **Edit Cloudflare Workers** |
| `CLOUDFLARE_ACCOUNT_ID` | Workers & Pages 页面右侧的 Account ID |

第一次运行 `autopilot deploy` 时会在交互式终端提示你输入（`getpass`，不回显），
并写入 `.env`：

- `.env` 已在 `.gitignore` 中
- 写入权限是 `0600`（仅本人可读）
- 值**不会被打印**，也不会出现在命令行里（避免被 `ps` 看到），而是通过环境变量传给 wrangler

想跳过提示就自己写进 `.env`：

```
CLOUDFLARE_API_TOKEN=...
CLOUDFLARE_ACCOUNT_ID=...
```

---

## 3. 部署什么

按顺序在**代码目录**（默认 `app/`，即 `building` 阶段写出真实代码的地方）里查找，
找不到再回落到项目根目录（兼容手工建的项目）：

| 找到 | 当作 | 命令 |
|---|---|---|
| `wrangler.toml` / `wrangler.json` / `wrangler.jsonc` | Worker | `wrangler deploy` |
| `dist/` 或 `public/`（非空） | Pages 站点 | `wrangler pages deploy <dir>` |

两者都没有时会报错并告诉你该放什么，**不会伪造一个占位站点**。

> `build/` **不**在静态目录列表里。它是流水线自己写构建元数据的地方，
> 曾经被误判为要发布的网站——那会把 `mock-building-result.json` 这类记账文件
> 当成产品发布出去。

代码目录可以用 `deploy.source_dir` 改：

```yaml
# config/pipeline.yaml
deploy:
  source_dir: app
```

### wrangler 怎么调用

默认 `npx wrangler`。如果已全局安装，或想用别的包管理器，改配置：

```yaml
deploy:
  wrangler: ["wrangler"]              # 全局安装
  # wrangler: ["pnpm", "dlx", "wrangler"]
```

也可以只在一次运行里覆盖：

```bash
AUTOPILOT_WRANGLER="pnpm dlx wrangler" ./autopilot.py deploy my-product
```

---

## 4. 常用命令

```bash
./autopilot.py deploy my-product --dry-run              # 只打印将执行的命令
./autopilot.py deploy my-product                        # 门 → 部署 → launched
./autopilot.py deploy my-product --environment preview   # 加 --env preview
./autopilot.py deploy my-product --yes                  # 自动过门
./autopilot.py deploy-status my-product                 # URL / 类型 / 域名状态
```

对已经 `launched` 的项目，`deploy` 会原地重新部署，不改状态。

---

## 5. 挂自定义域名（需要你手动一次）

Cloudflare 的自定义域名要在 Dashboard 里操作，所以流水线**停下来提示你**，
而不是假装替你做了。部署成功后会打印步骤：

1. <https://dash.cloudflare.com> → Workers & Pages → 你的项目
2. Settings → Domains & Routes → Add → Custom Domain
3. 输入域名，按提示把 DNS 指过去（域名已托管在 Cloudflare 会自动配好）
4. 生效后记录下来：

```bash
./autopilot.py domain my-product --domain myapp.com
```

这写进 `deploy/deployment.json` 和审计日志，**不改变项目阶段**（挂域名是部署后的
手动步骤）。之后 `deploy-status` 会显示它，重新部署也会保留。

---

## 6. 排错

| 现象 | 原因与处理 |
|---|---|
| `缺少 Cloudflare 凭据` | 写进 `.env`，或在交互式终端运行以便被提示 |
| `没有可部署的内容` | `app/` 里既没有 wrangler 配置也没有非空的 `dist/`/`public/`。构建阶段的产物是 mock 时属正常，需要用 live adapter 真的写出代码 |
| `部署失败：...`，项目仍在 `release_pending` | **这是正确行为**。修好原因后重跑 `deploy` |
| `项目处于 'X'，不能部署` | 只有 `release_pending`（首次）和 `launched`（重新部署）可以部署 |
| npm 缓存 `EPERM` | 沙箱禁止写 npm 缓存。在不受限的环境里运行，或全局装 wrangler 后设 `AUTOPILOT_WRANGLER=wrangler` |
| 403 / 权限错误 | Token 缺少 Workers 权限，或 Account ID 不对 |

---

## 7. 项目结构示例

```
projects/my-product/
  app/                        # building 阶段写出的真实代码
    wrangler.toml
    src/index.js
  build/                      # 流水线元数据，不是产品
    building-result.json
  deploy/
    deployment.json           # URL、类型、环境、命令、域名、历史
  state.json
```

---

## 下一步

- 完整本地流程：[local-usage.md](local-usage.md)
- 部署后的真实数据回流：[local-usage.md](local-usage.md#10-closing-the-loop-real-search-console--ga4-data)
