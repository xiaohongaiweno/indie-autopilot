---
name: deployment-operations
description: 部署与运维。配置 CI/CD、部署流程、监控告警和日常运维。当用户说「部署」「CI/CD」「监控」「运维」「怎么发布」「deploy」「deployment」「monitoring」「ops」时使用。
---

# 部署与运维

配置自动化部署和监控。核心问题：如何安全发布？如何快速发现问题？如何快速恢复？

## 铁律

1. **自动化优先。** 手动部署容易出错，能自动化就自动化。
2. **零停机部署。** 用户不应该感知到部署过程。
3. **快速回滚。** 发布失败时能在 5 分钟内回滚。
4. **监控先行。** 没有监控就不要发布。
5. **文档化运维。** 所有操作都有文档，包括故障恢复。

## 部署策略

### 静态站点 / JAMstack
- **平台**：Vercel、Netlify、Cloudflare Pages
- **部署**：Git push 自动部署
- **预览**：每个 PR 生成预览 URL
- **回滚**：一键回滚到任意版本
- **成本**：免费层通常够用

### Web 应用（Node.js / Python / Go）
- **平台**：Railway、Fly.io、Render、DigitalOcean App Platform
- **部署**：Git push 或 Docker 镜像
- **扩展**：自动扩展或手动调整
- **回滚**：回滚到上一个版本
- **成本**：$5-$50/月起

### 数据库
- **托管数据库**：Supabase、PlanetScale、Neon、MongoDB Atlas
- **备份**：自动每日备份
- **恢复**：Point-in-time recovery
- **迁移**：版本化迁移脚本
- **成本**：免费层 → $25/月起

### 容器化部署
- **Docker**：容器化应用
- **Docker Compose**：本地开发
- **Kubernetes**：通常不需要（复杂度太高）
- **替代方案**：Railway、Fly.io（内置容器支持）

## CI/CD 配置

### GitHub Actions 示例
```yaml
name: Deploy
on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Setup
        run: npm ci
      - name: Test
        run: npm test
      - name: Deploy
        run: |
          # 部署命令
        env:
          DEPLOY_TOKEN: ${{ secrets.DEPLOY_TOKEN }}
```

### 基本流程
1. **代码推送** → 触发 CI
2. **安装依赖** → 构建应用
3. **运行测试** → 单元测试、集成测试
4. **构建镜像**（可选）→ Docker 镜像
5. **部署** → 推送到生产环境
6. **健康检查** → 验证部署成功
7. **通知** → 成功/失败通知

### 环境管理
- **开发环境**：本地开发
- **预览环境**：每个 PR 一个环境
- ** staging 环境**：发布前测试（可选）
- **生产环境**：真实用户

## 监控与告警

### 应用监控
- **错误追踪**：Sentry、LogRocket、Bugsnag
- **性能监控**：New Relic、Datadog、AppSignal
- **日志管理**：Logtail、Papertrail、CloudWatch Logs
- **正常运行时间**：UptimeRobot、BetterStack、Pingdom

### 业务监控
- **用户注册**：每日注册数
- **活跃度**：DAU/MAU
- **转化率**：注册→付费
- **收入**：MRR、ARR
- **流失率**：取消订阅率

### 告警规则
- **错误率**：> 1% 触发告警
- **响应时间**：P95 > 1s 触发告警
- **正常运行时间**：< 99.9% 触发告警
- **服务器资源**：CPU > 80% 触发告警

### 告警渠道
- **即时通知**：Slack、Discord、短信
- **邮件通知**：非紧急告警
- **电话通知**：严重故障

## 备份与恢复

### 数据库备份
- **自动备份**：每日自动备份
- **保留策略**：保留 30 天
- **测试恢复**：定期测试恢复流程
- **异地备份**：备份到不同区域

### 文件备份
- **用户上传**：S3、R2、GCS（自带冗余）
- **配置文件**：Git 版本控制
- **环境变量**：加密存储

### 灾难恢复
- **RTO**（恢复时间目标）：< 1 小时
- **RPO**（恢复点目标）：< 1 天
- **恢复流程**：文档化恢复步骤
- **定期演练**：每季度演练一次

## 工作流程

### 1. 部署准备
- 代码审查通过
- 测试全部通过
- 数据库迁移准备
- 回滚计划准备

### 2. 部署执行
- 合并到 main 分支
- CI/CD 自动部署
- 监控部署过程
- 验证部署成功

### 3. 部署验证
- 健康检查通过
- 核心功能正常
- 性能指标正常
- 错误率未上升

### 4. 日常运维
- 监控告警
- 日志审查
- 性能优化
- 安全更新

### 5. 故障处理
- 发现问题 → 评估影响
- 通知团队 → 开始修复
- 修复或回滚 → 验证恢复
- 事后分析 → 改进流程

## 成本优化

### 免费层策略
- Vercel/Netlify：静态站点和前端
- Supabase/PlanetScale：数据库
- Cloudflare：CDN 和 DNS
- GitHub Actions：CI/CD

### 成本控制
- 设置预算告警
- 监控资源使用
- 优化查询和缓存
- 清理无用资源

## 与其他 Skill 的关系

- `indie-tech-architecture`：技术栈指导部署选择
- `launch-readiness-qa`：发布前检查
- `security-privacy-review`：安全配置
- `saas-cost-monitor`：成本监控
- `support-knowledge-base`：故障处理文档

## 输出格式

```
## 部署与运维方案

### 部署架构
- 托管平台：...
- 数据库：...
- CDN：...

### CI/CD 流程
- ...

### 监控配置
- 错误追踪：...
- 性能监控：...
- 告警规则：...

### 备份策略
- 数据库备份：...
- 文件备份：...
- 恢复测试：...

### 运维手册
- 部署流程：...
- 回滚流程：...
- 故障处理：...

### 成本估算
- 月成本：$X
- 免费层：...
- 付费服务：...
```

