# 信号来源与检索套路

检索原则：查询词 1–6 个词、由宽到窄；每个候选方向单独查；搜索摘要不够时抓全文；优先原始页面。

## 接入方式约定

- **自动采集**：有公开 API 或相对稳定的数据接口，可直接拉取。
- **半自动**：通过 CSV 导入、RSS、网页检索或 Agent 辅助研究。
- **人工核查**：需要人工查看页面、确认价格、评价或商业化证据。
- **重要**：免费访问网页 ≠ 允许无限自动抓取。各平台 API 的免费额度、权限和条款可能调整，开发前仍需核对当前政策。尤其 Product Hunt 与 Reddit，需先核查用途限制、权限与当前条款。

---

## 一、产品发布与新兴产品发现
回答：最近有哪些新产品？哪些赛道有新玩家进入？

- 重点接入：Product Hunt、Hacker News、GitHub、Indie Hackers
- Product Hunt（日榜/月榜/分类趋势）、BetaList、Uneed、Microlaunch
- Peerlist、There's An AI For That、Futurepedia
- AlternativeTo、SaaSHub、G2、Capterra、GetApp

用法：
- 发现新品：Product Hunt、BetaList、Uneed
- 发现开发者在做什么：Show HN、GitHub、Indie Hackers
- 判断赛道拥挤度：AlternativeTo、SaaSHub、G2、Capterra
- 记录**用户为什么想找替代品**，而不只是产品名称
- 榜单只说明供给，不说明需求与收入

## 二、用户痛点与真实需求（最重要）
回答：用户究竟在抱怨什么、目前如何解决、什么问题反复出现？

- Reddit、Hacker News Ask / Show、Indie Hackers、Quora
- Stack Overflow、Stack Exchange、GitHub Issues、GitHub Discussions
- WordPress.org Support Forums、Chrome Web Store、Firefox Add-ons
- Trustpilot、G2 Reviews、Capterra Reviews

**研究时重点搜索的英文表达**（配置进搜索规则）：
- `alternative to [product]`
- `[product] pricing too expensive`
- `I wish there was a tool`
- `how do you manage [task]`
- `looking for a tool to`
- `best software for [use case]`
- `frustrated with [product]`
- `manual process for [task]`
- `open source alternative to [product]`
- `how do I automate [task]`

记录：原话（一句即可）、链接、日期、该抱怨出现的次数。
不要简单统计帖子数量，要归纳成具体问题，例如"每周手动处理数百个文件""现有工具必须上传隐私数据""竞品价格超出小团队预算"。
合规提醒：Reddit API 需遵守开发者条款与访问限制，不能默认无限量抓取、长期存储或用于任何商业化场景。

## 三、SEO 与关键词需求（核心）
回答：用户会不会主动搜索这个问题？能否通过搜索引擎获得用户？

- Google Trends（CSV 导入 / 人工查询。相对指数，不是绝对搜索量）
- Google Keyword Planner（手动查询 / 接口视权限而定）
- Google Search Console（官方 API，适合验证自己网站的 SEO）
- Google Autocomplete、People Also Ask（只当需求线索，不能当搜索量）
- Google SERP（Agent 检索 / 人工核查，记录地区、语言和查询日期）
- Bing Webmaster Tools、Bing 搜索建议
- Ahrefs Free Keyword Generator、Ahrefs Webmaster Tools
- Semrush、Moz Keyword Explorer、Ubersuggest
- Keyword Tool、AnswerThePublic、AlsoAsked、Exploding Topics
- Glimpse、Keyword Surfer（指标为估算，不能当官方数据）
- Google Search Central（判断 SEO 实施可行性）

**SEO 数据组合法**（以"AI meeting notes"为例）：
1. Google Trends：看近 12 个月和近 5 年趋势
2. Keyword Planner / Ahrefs：找搜索量线索与相关关键词
3. Google SERP：看首页由哪些产品、测评和教程占据
4. G2、Reddit、YouTube 评论：找现有产品未解决的问题
5. 竞品官网：确认价格、目标客户、免费版限制
6. 判断：做通用工具，还是聚焦更具体的工作流

## 四、趋势、社交传播与内容热点
回答：哪些需求正在扩散？警惕只红几天的短期热点。

- Google Trends（CSV / 人工）
- YouTube / YouTube Data API（配额限制）
- TikTok Creative Center、Pinterest Trends
- Instagram、X、Bluesky、Mastodon、Lobsters
- DEV Community、Hashnode、Medium、Substack
- Google Alerts、Talkwalker Alerts

雷达记录四个指标：**首次出现时间、最近 7 天信号量、过去 30 天变化、不同来源数量**。
不能只根据某个帖子爆火就判断市场增长。

## 五、竞品、网站流量与市场竞争
回答：谁已经在做？竞争多激烈？谁可能有收入？靠什么获客？

- Similarweb（流量是估算，免费展示有限）、Semrush、Ahrefs、Moz
- BuiltWith、Wappalyzer、PublicWWW（数据覆盖有局限）
- Wayback Machine（历史快照可能缺失）、Visualping、Distill（监控页面变化）
- 竞品官网 Pricing 页（必须保存页面 URL 和核查时间）、Changelog、公开文档
- G2、Capterra、Trustpilot（评价存在样本偏差）
- Google Play、Apple App Store（仅适用相关应用市场）

竞品库至少存：`name`、`website`、`category`、`target_customer`、`pricing_url`、`pricing_observed_at`、`key_features`、`traffic_estimate`、`traffic_source`、`complaints`、`differentiation`、`evidence_urls`。
没有可靠的流量或收入数据就写"未知"，不要为凑完整而编造数字。

## 六、付费意愿、定价和商业化证据
回答：用户愿意为什么付钱？证据有多强？

- Stripe、Paddle、Lemon Squeezy（公开结账页 / 支付方案线索）
- Gumroad、AppSumo（公开销售页面、价格、客户反馈）
- Acquire.com、Microns、Flippa（产品是否在出售及其公开指标）
- TinySeed、Y Combinator Companies、OpenVC、Crunchbase、Dealroom
- SaaS 产品公开定价页、公开客户案例（注意营销偏差）

**证据强弱判断**：
| 证据 | 支持程度 |
| --- | --- |
| 有人抱怨现有产品难用 | 弱：说明可能有痛点 |
| 有人询问有没有替代产品 | 弱到中：存在寻找方案的行为 |
| 已有竞品公开收费 | 中：市场存在商业化尝试 |
| 有真实用户公开购买或续费案例 | 中到强：需核查真实性与代表性 |
| 多家竞品持续收费且有独立客户案例 | 较强：但仍不代表新产品能盈利 |
| 你自己的落地页测试、预售、试用转化或付费订单 | 对具体产品最有价值 |

注意：支付服务商 Logo、支付按钮、定价页都不是收入证明；融资金额 ≠ 稳定付费需求。

## 七、开发者生态、开源项目和技术需求
回答：有哪些可由独立开发者快速切入的工具型机会？

- GitHub Trending / Search / Releases、GitLab Explore、Codeberg、SourceForge
- PyPI、npm、Docker Hub、Homebrew Formulae
- VS Code Marketplace、JetBrains Marketplace、Chrome Web Store
- Hugging Face、Papers with Code、arXiv
- Stack Overflow、Stack Exchange API

注意：GitHub Stars、包下载量、Docker 拉取量只是关注信号，不能等同于活跃用户、购买意愿或市场规模。

## 八、招聘、外包需求和工作流痛点
回答：企业愿意花钱做的某项工作，是否具有经济价值（但未必能被软件替代）？

- Indeed、LinkedIn Jobs、Wellfound、Remote OK、We Work Remotely
- Upwork、Freelancer、Fiverr、Contra、Malt
- Y Combinator Request for Startups、Techstars
- 政府采购公开平台（sam.gov）

第一版以关键词检索和人工归纳为主。不要默认招聘网站允许无限量抓取岗位数据。

## 九、应用商店、插件市场与垂直生态
回答：哪些范围小、目标用户明确、易做 MVP 的机会？

- Chrome Web Store、Firefox Add-ons
- VS Code Marketplace、JetBrains Marketplace
- WordPress Plugins、Shopify App Store
- Salesforce AppExchange、Atlassian Marketplace
- Figma Community、Canva Apps、Slack Marketplace、Discord App Directory
- Zapier / Make Integrations、Airtable Marketplace、Notion Marketplace
- Hugging Face Spaces

**从插件市场发现机会的三种信号**：
1. 某类插件评价很多，但用户反复抱怨同一功能
2. 某个昂贵 SaaS 的核心功能可拆成更小的插件或独立工具
3. 用户需要把多个工具连接起来，但现有集成不完善

插件市场的用户规模、排名和评价受平台分发机制影响，不能仅凭榜单判断商业价值。

## 十、新闻、融资、行业报告与宏观市场信号
回答：这个需求是否有更大的行业背景，而不只是社区个例？

- TechCrunch、The Verge、Ars Technica、Techmeme、Google News
- MIT Technology Review、The Information（部分收费）
- Crunchbase、Dealroom、CB Insights（部分收费）
- Gartner、McKinsey（部分收费）
- OECD Data、World Bank Data、US Census Bureau、美国劳工统计局 BLS

主要作用是补充背景和验证趋势，不是直接找功能缺口。付费报告摘要不能替代完整研究数据。

---

## 十一、可直接接入的免费公共数据和 API

| 数据源 | 用途 | 建议 |
| --- | --- | --- |
| Hacker News API | 帖子、评论、热度 | 第一批接入 |
| GitHub REST API | 仓库、Issues、搜索结果 | 第一批接入 |
| GitHub GraphQL API | 按需查询结构化数据 | 后续扩展 |
| Stack Exchange API | 问答、标签、问题热度 | 第二批 |
| YouTube Data API | 视频和频道公开数据 | 按配额使用 |
| Google Search Console API | 自有网站真实搜索表现 | 网站上线后 |
| Google Trends | 趋势数据 | 第一版 CSV 导入 |
| Product Hunt API | 产品发布信息 | 先核查权限与用途 |
| Reddit Data API | 公开帖子与评论 | 先核查访问权限与用途 |
| PyPI JSON API | Python 包信息 | 技术赛道研究 |
| npm Registry API | npm 包信息 | 技术赛道研究 |
| Hugging Face Hub API | 模型、数据集和空间 | AI 赛道研究 |
| arXiv API | 论文和新兴研究方向 | 技术趋势研究 |
| OpenAlex API | 学术研究、论文和主题 | 研究型机会 |
| Crossref API | 学术出版物元数据 | 辅助研究 |
| World Bank API | 宏观经济数据 | 行业背景 |
| US Census API | 企业和行业统计 | 美国市场研究 |

不要把"有 API"等同于"可以免费无限使用"。尤其 Product Hunt 与 Reddit，需先核查用途限制、权限和当前条款。

---

## 来源可信度（从强到弱）
用户原帖/评论/工单 > 官方定价页/更新日志 > 公开收入平台 > 第三方评测 > 聚合型榜单文章与卖方博客（竞品写的"替代品对比"属卖方内容，只算弱证据）。只有弱证据的维度，评分上限 5。