---
name: indie-tech-architecture
description: 独立开发者技术架构。选择技术栈、设计系统架构、做技术决策，平衡开发效率、维护成本和可扩展性。当用户说「技术选型」「架构设计」「用什么技术栈」「tech stack」「architecture」「技术决策」时使用。
---

# 独立开发者技术架构

为独立开发者选择合适的技术栈和架构。核心问题：什么技术最适合一个人开发和维护？如何在开发效率和长期可维护性之间平衡？

## 铁律

1. **选熟悉的，不选时髦的。** 独立开发者的时间是最大成本，学习新技术的成本远高于团队。
2. **单体优先。** 除非有明确理由，否则用单体架构。微服务的复杂度不适合一个人。
3. **托管服务 > 自建。** 用 Vercel/Railway/Supabase 等托管服务，不要自建基础设施。
4. **标准化 > 定制化。** 用成熟框架的默认约定，不要自己发明模式。
5. **可逆决策快速做，不可逆决策谨慎做。** 技术栈选择大多可逆，不要过度分析。

## 技术选型框架

### 评估维度
- **开发速度**：能否快速出 MVP？
- **学习成本**：你熟悉这个技术吗？
- **维护成本**：一个人能维护吗？
- **生态系统**：有成熟的库和服务吗？
- **部署简易度**：能一键部署吗？
- **成本**：免费层够用吗？超出后成本如何？

### 常见技术栈推荐

#### Web SaaS
- **前端**：Next.js / Nuxt.js / SvelteKit
- **后端**：同框架 API routes 或 Supabase/Firebase
- **数据库**：PostgreSQL (Supabase) / MongoDB (Atlas)
- **认证**：Clerk / Auth0 / Supabase Auth / NextAuth
- **支付**：Stripe / LemonSqueezy / Paddle
- **部署**：Vercel / Railway / Fly.io

#### 桌面应用
- **跨平台**：Electron / Tauri
- **原生**：Swift (macOS) / C# (Windows)
- **更新**：内置自动更新机制

#### 浏览器扩展
- **Manifest V3**：Chrome/Edge/Firefox
- **构建工具**：Plasmo / WXT
- **发布**：Chrome Web Store / Firefox Add-ons

#### 移动应用
- **跨平台**：React Native / Flutter
- **原生**：Swift (iOS) / Kotlin (Android)
- **后端**：Supabase / Firebase

### 架构决策

#### 单体 vs 微服务
**选单体当：**
- 团队 < 3 人
- 产品早期
- 没有明确的独立扩展需求

**考虑微服务当：**
- 有组件需要独立扩展（如视频处理）
- 团队增长到需要独立部署
- 不同组件有不同技术需求

#### 服务器 vs 无服务器
**选无服务器当：**
- 流量波动大
- 不想管理服务器
- 成本敏感（按用量付费）

**选服务器当：**
- 需要长连接（WebSocket）
- 需要持久化进程
- 成本可预测（固定流量）

#### 自建 vs 托管
**优先托管：**
- 数据库（Supabase、PlanetScale）
- 认证（Clerk、Auth0）
- 文件存储（Cloudflare R2、AWS S3）
- 邮件（Resend、SendGrid）
- 搜索（Algolia、Meilisearch Cloud）

## 工作流程

### 1. 需求分析
从其他 Skill 收集：
- `mvp-scope-planner`：MVP 功能列表
- `product-requirements`：功能和非功能需求
- `product-validation`：目标用户和规模

### 2. 技术选型
- 列出候选技术
- 按评估维度打分
- 选择最合适的（不是最完美的）
- 记录决策原因

### 3. 架构设计
- 系统架构图
- 数据模型
- API 设计
- 第三方服务集成

### 4. 开发环境
- 本地开发设置
- 环境变量管理
- 数据库迁移
- 测试策略

### 5. 部署策略
- 部署平台选择
- CI/CD 流程
- 监控和日志
- 备份策略

### 6. 技术债务预算
明确允许的技术妥协：
- 硬编码配置
- 同步处理
- 基础错误处理
- 手动部署

但要记录：这些是**有意的妥协**，发布后逐步改进。

## 成本估算

### 免费层估算（MVP 阶段）
- 托管：Vercel free / Railway $5 credit
- 数据库：Supabase free / PlanetScale free
- 认证：Clerk free (10k MAU) / Supabase free
- 邮件：Resend free (3k/month)
- 监控：Sentry free / LogSnag free
- **总计**：$0-$20/月

### 增长后成本（1000 用户）
- 托管：$20-$50/月
- 数据库：$25-$50/月
- 认证：$0-$25/月
- 邮件：$20-$50/月
- 监控：$26-$50/月
- **总计**：$100-$250/月

## 与其他 Skill 的关系

- `mvp-scope-planner`：MVP 范围指导技术需求
- `product-requirements`：需求指导架构设计
- `ai-coding-workflow`：技术栈指导开发
- `security-privacy-review`：安全审查
- `deployment-operations`：部署和运维
- `saas-cost-monitor`：成本监控

## 输出格式

```
## 技术架构方案

### 技术栈选择
- 前端：...
- 后端：...
- 数据库：...
- 认证：...
- 支付：...
- 部署：...

### 架构图
...

### 数据模型
...

### 第三方服务
| 服务 | 用途 | 成本 |
|---|---|---|

### 技术决策记录
| 决策 | 选择 | 原因 |
|---|---|---|

### 开发环境设置
- ...

### 部署策略
- ...
```

