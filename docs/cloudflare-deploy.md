# Cloudflare 部署配置指南

## 设置步骤

### 1. 获取 Cloudflare 凭证

#### 创建 API Token
1. 登录 [Cloudflare Dashboard](https://dash.cloudflare.com/profile/api-tokens)
2. 点击 "Create Token"
3. 选择 "Create Custom Token"
4. 配置权限：
   - **Account** > **Cloudflare Workers Scripts** > Edit
   - **Account** > **Cloudflare D1** > Edit (如果使用数据库)
   - **Zone** > **Zone Settings** > Read (如果使用自定义域名)
5. 点击 "Continue to summary" → "Create Token"
6. 复制 token（只显示一次）

#### 获取 Account ID
1. 在 Cloudflare Dashboard 首页
2. 右侧边栏找到 "Account ID"
3. 复制 Account ID

### 2. 配置 GitHub Secrets

1. 进入你的 GitHub 仓库
2. 点击 **Settings** → **Secrets and variables** → **Actions**
3. 点击 **New repository secret**
4. 添加两个 secret：

| Name | Value |
|------|-------|
| `CLOUDFLARE_API_TOKEN` | 你的 Cloudflare API Token |
| `CLOUDFLARE_ACCOUNT_ID` | 你的 Cloudflare Account ID |

### 3. 项目配置

#### 方式 A：使用 wrangler.toml（推荐）

在项目目录创建 `wrangler.toml`：

```toml
name = "your-project-name"
main = "src/index.js"
compatibility_date = "2026-10-10"

# 如果是 Pages 项目
[site]
bucket = "./dist"

# 环境变量
[env.production]
vars = { ENVIRONMENT = "production" }

[env.preview]
vars = { ENVIRONMENT = "preview" }
```

#### 方式 B：自动配置

如果没有 `wrangler.toml`，工作流会自动创建基础配置并部署静态文件。

### 4. 部署流程

#### Preview 部署（测试环境）
```bash
# 在 GitHub Actions 中
1. 进入 Actions → "Deploy: Cloudflare"
2. 点击 "Run workflow"
3. 输入 project_id
4. 选择 environment: "preview"
5. 点击 "Run workflow"
```

#### Production 部署（生产环境）
```bash
# 在 GitHub Actions 中
1. 进入 Actions → "Deploy: Cloudflare"
2. 点击 "Run workflow"
3. 输入 project_id
4. 选择 environment: "production"
5. 点击 "Run workflow"
```

### 5. 状态转换

部署工作流会：
- Preview: 保持当前状态，部署到预览 URL
- Production: 转换状态到 `launched`，创建发布 Issue

### 6. 访问部署

部署完成后：
- **Preview**: `https://<project-name>.<subdomain>.pages.dev`
- **Production**: `https://<project-name>.<subdomain>.pages.dev` 或自定义域名

## 常见问题

### Q: 如何添加自定义域名？
A: 在 Cloudflare Dashboard → Pages/Workers → 项目设置 → Custom domains

### Q: 如何配置环境变量？
A: 在 `wrangler.toml` 中使用 `[env.production.vars]` 或在 Cloudflare Dashboard 设置

### Q: 部署失败怎么办？
A: 检查：
1. API Token 权限是否正确
2. Account ID 是否正确
3. 查看 Actions 日志获取详细错误

## 示例项目结构

```
projects/my-product/
├── state.json
├── wrangler.toml
├── src/
│   └── index.js
└── dist/
    └── index.html
```

## 下一步

部署成功后，系统会：
1. 更新项目状态为 `launched`
2. 创建发布 Issue
3. 可以开始 `growing` 阶段的活动
