# Skill 交接关系

## 主流程

```
indie-product-radar → emerging-keyword-radar → product-validation → competitor-intelligence / seo-opportunity-research
  → product-positioning → mvp-scope-planner → product-requirements
  → indie-tech-architecture → ai-coding-workflow
  → launch-readiness-qa → deployment-operations / launch-campaign-planner
  → indie-product-reach → product-analytics / customer-feedback-loop
  → indie-builder-memory
```

## 阶段交接

### Discovery → Definition
- `indie-product-radar` 输出的 Top 机会卡 → `product-validation` 验证
- `emerging-keyword-radar` 输出的高执行价值关键词 → `seo-opportunity-research` 深入分析；同时为 `content-marketing-engine` 提供内容选题，为 `indie-product-reach` 提供关键词策略
- 验证通过的方向 → `competitor-intelligence` + `seo-opportunity-research` 并行研究
- 研究结论 → `product-positioning` 定义差异化

### Definition → Build
- `mvp-scope-planner` 的功能清单 → `product-requirements` 写成用户故事和验收标准
- `product-requirements` + `product-positioning` → `product-ux-conversion` 审查转化体验
- `product-requirements` → `indie-tech-architecture` 选型和 PoC

### Build → Launch
- `indie-tech-architecture` + `ai-coding-workflow` 完成开发
- `security-privacy-review` 审查安全和隐私
- `launch-readiness-qa` 上线前全面验收
- `deployment-operations` 执行部署
- `launch-campaign-planner` 规划发布活动

### Launch → Growth
- `indie-product-reach` 执行推广（SEO、目录、社区、内容、邮件、社会证明）
- `content-marketing-engine` + `distribution-channel-research` 持续内容和渠道扩展
- `google-indexing-diagnostics` 诊断收录问题
- `product-analytics` 定义和追踪增长指标
- `conversion-optimization` 优化转化漏斗
- `pricing-monetization` 调整定价策略
- `customer-feedback-loop` 收集和处理用户反馈

### Growth → Maintain
- `product-lifecycle-manager` 评估继续/转型/维护/停止
- `project-retrospective` 复盘目标与实际
- `saas-cost-monitor` 监控成本
- `technical-debt-manager` 管理技术债
- `indie-builder-memory` 沉淀经验
- `support-knowledge-base` 整理支持文档
- `indie-workflow-automation` 自动化重复工作
- `skills-quality-auditor` 审查 Skills 本身质量

## 规则

- 并非所有项目都必须走完所有模块。
- `emerging-keyword-radar` 可与 `indie-product-radar` 并行使用，也可独立运行发现内容选题。
- `seo-opportunity-research` 可作为 Radar 的深入研究模块。
- `google-indexing-diagnostics` 等增长专项仅在需要深入时调用。
- `indie-builder-memory` 负责跨项目经验沉淀；`skills-quality-auditor` 负责审查 Skills 本身。
- 每个 Skill 的输出应包含状态和证据，供下游 Skill 直接使用。
