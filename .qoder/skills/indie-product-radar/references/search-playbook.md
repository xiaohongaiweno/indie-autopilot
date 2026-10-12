# 搜索查询手册（Search Playbook）

系统化的查询模板，提升搜索效率和证据质量。每个查询配预期结果和判断标准。

## 使用原则

1. **查询词 1–6 个词**，由宽到窄
2. **每个候选方向单独查**，不要合并查询
3. **搜索摘要不够时抓全文**
4. **优先原始页面**（用户原帖 > 评测文章 > 聚合榜单）
5. **记录搜索日期**，结果会随时间变化

---

## 一、痛点发现查询

**目标**：找到用户真实抱怨和未解决的问题

### 英文查询模板（优先级从高到低）

| 查询模板 | 预期结果 | 判断标准 |
|---|---|---|
| `"alternative to [product]"` | 用户在找替代品 | ≥3 个独立帖子 = 强信号 |
| `"[product] pricing too expensive"` | 用户对价格不满 | 看是否有具体替代方案讨论 |
| `"I wish there was a tool to [task]"` | 用户明确表达需求 | 看任务是否具体、可解决 |
| `"how do you manage [task]"` | 用户在找解决方案 | 看回复是否提到 Excel/手动/多工具拼凑 |
| `"looking for a tool to [task]"` | 用户主动寻找 | 看是否有推荐，推荐的产品是否有明显弱点 |
| `"best software for [use case]"` | 用户在比较方案 | 看评论区是否有不满 |
| `"frustrated with [product]"` | 用户对现有方案不满 | 看抱怨是否具体、重复出现 |
| `"manual process for [task]"` | 用户在手动解决 | 手动 = 自动化机会 |
| `"open source alternative to [product]"` | 用户在找免费/自托管方案 | 看是否有商业化空间 |
| `"how do I automate [task]"` | 用户想自动化 | 看任务是否适合 SaaS 化 |
| `"[product] vs [competitor]"` | 用户在比较 | 看评论区是否有"都不够好"的声音 |
| `"[product] stopped working"` | 用户遇到故障 | 看是否是常见问题、官方是否响应 |
| `"[product] problems"` | 用户遇到问题 | 看问题是否普遍、是否未解决 |
| `"site:reddit.com [product] alternative"` | Reddit 上的替代品讨论 | Reddit 用户更真实 |
| `"site:news.ycombinator.com [topic]"` | HN 上的讨论 | HN 用户更技术导向 |

### 中文查询模板

| 查询模板 | 预期结果 | 判断标准 |
|---|---|---|
| `"[产品] 替代品"` | 用户在找替代品 | 看是否有具体推荐 |
| `"[产品] 太贵了"` | 用户对价格不满 | 看是否有替代方案讨论 |
| `"有没有工具可以 [任务]"` | 用户明确表达需求 | 看任务是否具体 |
| `"你们怎么管理 [任务]"` | 用户在找解决方案 | 看回复是否提到手动/Excel |
| `"推荐一个 [场景] 软件"` | 用户在找方案 | 看推荐的产品是否有弱点 |
| `"[产品] 不好用"` | 用户不满 | 看抱怨是否具体、重复 |
| `"怎么自动化 [任务]"` | 用户想自动化 | 看任务是否适合 SaaS 化 |

---

## 二、商业化证据查询

**目标**：确认有人愿意付费、市场有商业化空间

### 定价与收入查询

| 查询模板 | 预期结果 | 判断标准 |
|---|---|---|
| `"[product] pricing"` | 竞品定价页 | 记录价格、功能分层 |
| `"[product] plans"` | 竞品定价方案 | 看是否有免费版、企业版 |
| `"[product] vs [competitor]"` | 竞品对比 | 看价格差异、功能差异 |
| `site:trustmrr.com "[topic]"` | 公开收入数据 | TrustMRR 数据相对可靠 |
| `site:indiehackers.com "[product] revenue"` | 独立开发者收入分享 | 注意幸存者偏差 |
| `site:starterstory.com "[topic]"` | 创业案例 | 看收入、成本、利润 |
| `"[product] acquired"` | 产品被收购 | 收购价 = 市场价值信号 |
| `site:acquire.com "[topic]"` | 产品在出售 | 出售原因、要价、收入 |
| `site:flippa.com "[topic]"` | 产品在出售 | 同上 |
| `"[product] customers"` | 客户案例 | 看客户规模、行业 |

### 广告与营销查询

| 查询模板 | 预期结果 | 判断标准 |
|---|---|---|
| `"[product] review"` | 评测文章 | 看是否有付费推广痕迹 |
| `"[product] sponsored"` | 赞助内容 | 有赞助 = 有预算 = 有收入 |
| `"ads:[product]"` | 付费广告 | 有广告 = 有预算 = 有收入 |

---

## 三、竞品弱点查询

**目标**：找到竞品的具体弱点，确定切入缝隙

### 评价与反馈查询

| 查询模板 | 预期结果 | 判断标准 |
|---|---|---|
| `"[product] review" site:g2.com` | G2 评价 | 看 1-3 星评价的共同主题 |
| `"[product] review" site:capterra.com` | Capterra 评价 | 同上 |
| `"[product] review" site:trustpilot.com` | Trustpilot 评价 | 同上 |
| `"[product] problems" site:reddit.com` | Reddit 上的问题 | 看是否是普遍问题 |
| `"[product] issues" site:github.com` | GitHub Issues | 看未解决的 bug、功能请求 |
| `"[product] stopped working"` | 故障报告 | 看是否是常见问题 |
| `"[product] slow"` | 性能问题 | 性能 = 可优化的缝隙 |
| `"[product] expensive"` | 价格抱怨 | 价格 = 可切入的缝隙 |
| `"[product] missing [feature]"` | 功能缺失 | 缺失功能 = 可切入的缝隙 |

### 竞品动态查询

| 查询模板 | 预期结果 | 判断标准 |
|---|---|---|
| `"[product] changelog"` | 更新日志 | 看更新频率、方向 |
| `"[product] blog"` | 官方博客 | 看是否活跃、关注什么 |
| `"[product] layoffs"` | 裁员新闻 | 裁员 = 可能停更 |
| `"[product] acquisition"` | 被收购 | 收购后可能涨价/停更 |
| `"[product] price increase"` | 涨价 | 涨价 = 用户不满 = 机会 |

---

## 四、市场规模查询

**目标**：粗估潜在用户基数和市场空间

### 用户基数查询

| 查询模板 | 预期结果 | 判断标准 |
|---|---|---|
| `"how many [user type] in [industry]"` | 用户基数 | 交叉验证多个来源 |
| `"[industry] market size"` | 市场规模报告 | 注意报告年份、来源 |
| `"[topic] TAM SAM SOM"` | 市场分析 | 看假设是否合理 |
| `site:statista.com "[topic]"` | 统计数据 | Statista 数据相对可靠 |
| `"number of [user type] worldwide"` | 全球用户数 | 看是否包含目标市场 |

### 招聘与外包查询

| 查询模板 | 预期结果 | 判断标准 |
|---|---|---|
| `"[skill] jobs" site:indeed.com` | 招聘帖子 | 招聘量 = 需求强度 |
| `"[skill] freelance" site:upwork.com` | 外包需求 | 外包量 = 需求强度 |
| `"[tool] expert" site:linkedin.com` | 专家需求 | 专家需求 = 工具化机会 |

---

## 五、趋势与热点查询

**目标**：判断需求是否在增长、是否是短期热点

### 趋势查询

| 查询模板 | 预期结果 | 判断标准 |
|---|---|---|
| `site:trends.google.com "[topic]"` | Google Trends 数据 | 看 12 个月和 5 年趋势 |
| `"[topic] trending"` | 热点讨论 | 看是否持续升温 |
| `"[topic] 2024" OR "[topic] 2025"` | 最新讨论 | 看是否有新玩家进入 |
| `"[topic] growth"` | 增长数据 | 看是否有具体数字 |

### 社交媒体查询

| 查询模板 | 预期结果 | 判断标准 |
|---|---|---|
| `"[topic]" site:twitter.com` | Twitter 讨论 | 看讨论量、参与者 |
| `"[topic]" site:youtube.com` | YouTube 视频 | 看视频数量、观看量 |
| `"[topic]" site:tiktok.com` | TikTok 视频 | 看是否是短期热点 |
| `"[topic]" site:substack.com` | Substack 文章 | 看是否有深度分析 |

---

## 六、技术可行性查询

**目标**：评估技术实现难度和风险

### 技术方案查询

| 查询模板 | 预期结果 | 判断标准 |
|---|---|---|
| `"how to build [product]"` | 技术方案 | 看复杂度、所需技术栈 |
| `"[technology] tutorial"` | 教程 | 看学习曲线 |
| `"[API] documentation"` | API 文档 | 看 API 稳定性、限制 |
| `"[API] rate limit"` | API 限制 | 看是否满足需求 |
| `"[API] pricing"` | API 成本 | 看是否影响利润 |

### 开源方案查询

| 查询模板 | 预期结果 | 判断标准 |
|---|---|---|
| `"[product] open source" site:github.com` | 开源替代品 | 看 Stars、更新频率、维护者 |
| `"[library] npm` | npm 包 | 看下载量、维护状态 |
| `"[library] pypi` | PyPI 包 | 看下载量、维护状态 |

---

## 七、获客渠道查询

**目标**：找到可触达目标用户的渠道

### 社区查询

| 查询模板 | 预期结果 | 判断标准 |
|---|---|---|
| `"[topic] community"` | 社区 | 看活跃度、规模 |
| `"[topic] forum"` | 论坛 | 看活跃度、规模 |
| `"[topic] subreddit"` | Subreddit | 看订阅数、活跃度 |
| `"[topic] discord"` | Discord 服务器 | 看成员数、活跃度 |
| `"[topic] slack"` | Slack 群组 | 看成员数、活跃度 |

### 内容渠道查询

| 查询模板 | 预期结果 | 判断标准 |
|---|---|---|
| `"[topic] blog"` | 博客 | 看流量、影响力 |
| `"[topic] newsletter"` | Newsletter | 看订阅数、影响力 |
| `"[topic] podcast"` | Podcast | 听听众数、影响力 |
| `"[topic] influencer"` | KOL | 看粉丝数、影响力 |

---

## 查询结果记录模板

每次搜索后记录：

```
查询：[查询词]
日期：[搜索日期]
结果数量：[N 条]
Top 3 结果：
1. [标题] - [链接] - [一句话摘要]
2. ...
3. ...
判断：[强信号/中等信号/弱信号/无信号]
备注：[补充说明]
```
