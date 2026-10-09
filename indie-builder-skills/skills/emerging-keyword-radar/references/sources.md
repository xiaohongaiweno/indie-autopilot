# 数据源清单

## 1. 趋势数据

### Google Trends
- **用途**：发现搜索热度变化、比较多个词的趋势、查看相关查询
- **入口**：https://trends.google.com/
- **关注**：Rising queries（上升查询）、Breakout terms（爆发词）、地域分布
- **局限**：只有相对值（0-100），没有绝对搜索量；低搜索量词可能不显示

### Google Trends Explore
- **用途**：深入查看单个词的时间线、相关主题、相关查询
- **关注**：过去 12 个月的趋势是否持续上升，而非短期脉冲

### Explore (Google Trends 新版)
- **用途**：发现新兴话题和趋势
- **关注**：Daily Search Trends、Year in Search

## 2. 搜索建议

### Google Autocomplete
- **用途**：发现用户实际输入的查询方式
- **方法**：在 Google 搜索框输入部分词，观察补全建议
- **技巧**：用字母表遍历（keyword + a, keyword + b...）发现更多变体
- **关注**：新出现的补全建议、之前没有的长尾词

### Google Related Searches
- **用途**：搜索结果页底部的"相关搜索"
- **关注**：与主词相关但角度不同的查询

### People Also Ask (PAA)
- **用途**：搜索结果中的"用户还问"
- **关注**：用户的具体问题、问题的措辞方式
- **技巧**：展开一个问题后会加载更多相关问题

### AlsoAsked.com
- **用途**：可视化 People Also Ask 的树状结构
- **免费额度**：有限，但适合快速了解问题结构

### AnswerThePublic
- **用途**：发现围绕关键词的问题、介词、比较词
- **免费额度**：每天有限
- **关注**：what/how/why/best/alternative 等模式

## 3. 社区讨论

### Reddit
- **子版**：r/SaaS, r/Entrepreneur, r/webdev, r/startups, 以及垂直领域子版
- **关注**：新帖中的新表达、反复出现的问题、"is there a tool for..."类帖子
- **技巧**：搜索过去 7 天的帖子，按热度排序

### Hacker News
- **入口**：https://news.ycombinator.com/
- **关注**：Show HN 中的新产品、评论中的需求表达
- **技巧**：用 HN Algolia 搜索特定话题

### V2EX
- **节点**：创意、分享创造、问与答、程序员
- **关注**：中文用户的新需求表达

### Twitter/X
- **关注**：indie dev 圈子的新工具讨论、#buildinpublic 标签
- **技巧**：搜索 "just launched"、"looking for"、"is there a"

### Indie Hackers
- **关注**：产品发布、收入报告中的新趋势
- **技巧**：查看最新帖子和评论

## 4. 新产品发布

### Product Hunt
- **入口**：https://www.producthunt.com/
- **关注**：每日/每周热门产品、新产品类别
- **技巧**：新产品上线后 1-2 周，观察是否出现 "alternative"、"vs" 类搜索

### GitHub Trending
- **入口**：https://github.com/trending
- **关注**：新兴开源项目、新工具类别
- **技巧**：新项目往往会带动相关搜索词

### Changelog 和版本公告
- **关注**：主流产品的新功能发布（Notion、Figma、Linear 等）
- **技巧**：新功能发布后，"how to use [feature]"、"[product] [feature] tutorial" 类查询会出现

## 5. 竞品动态

### 竞品新增页面
- **方法**：定期检查竞品网站的 /blog、/changelog、/resources 页面
- **关注**：竞品开始写的新话题，说明他们发现了搜索需求

### 竞品内容方向
- **方法**：用 Ahrefs/Semrush 免费版查看竞品的新增页面
- **关注**：竞品在哪些新关键词上获得了排名

### 用户评价中的新需求
- **来源**：G2、Capterra、Product Hunt 评论、App Store 评论
- **关注**：用户抱怨缺少的功能、希望有的集成、新的使用场景

## 优先级

1. **Google Trends + Autocomplete**：最直接的搜索需求信号
2. **社区讨论**：发现尚未进入搜索趋势的早期需求
3. **新产品发布**：衍生词的来源
4. **竞品动态**：验证需求是否被市场认可

不需要每次扫描都覆盖所有来源。根据时间和目标选择 2-3 个来源深入。
