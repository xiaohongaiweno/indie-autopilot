# Indie Builder Skills

独立开发者全生命周期 Skill 家族。31 个 Skill 覆盖从机会发现到产品维护的完整流程。

## 目录结构

```
indie-builder-skills/
├── skills/                    # 31 个独立 Skill
│   ├── indie-product-radar/   # 产品雷达（机会发现）
│   ├── emerging-keyword-radar/# 新兴关键词雷达
│   ├── product-validation/    # 需求验证
│   ├── ...                    # 其余 29 个 Skill
│   └── technical-debt-manager/
├── shared/                    # 跨 Skill 通用资源
│   ├── working-standards.md   # 通用工作标准
│   └── assets/                # 共享模板（决策记录、实验、经验卡片、任务）
├── radar-data/                # 产品雷达运行数据（运行时生成）
├── CATALOG.md                 # 完整清单与推荐流程
├── HANDOFF-MAP.md             # Skill 间交接关系
└── manifest.json              # 包元数据
```

## Skill 结构

每个 Skill 遵循统一规范：

```
<skill-name>/
├── SKILL.md          # 必需：前置元数据 + 工作指令
├── references/       # 可选：参考文档（按需加载到上下文）
└── assets/           # 可选：输出模板和文件（不加载到上下文）
```

## 使用原则

1. 按当前任务调用所需 Skill，不必每次运行全部。
2. 外部事实、价格、平台规则和竞品能力应记录来源与核验日期。
3. 不编造数据、用户反馈、测试结果或已执行操作。
4. `planned`、`submitted`、`published` 和 `verified` 是不同状态，不能混用。
5. 这是可编辑的 Markdown Skill 包，不会自动连接账户、浏览器、代码仓库或发布平台。

## 安装

将整个目录放入 Qoder skills 路径：

- 项目级：`.qoder/skills/`
- 用户级：`~/.qoder-cn/skills/`

重启会话或运行 `/skills reload`，然后使用 `/skills list` 验证。
