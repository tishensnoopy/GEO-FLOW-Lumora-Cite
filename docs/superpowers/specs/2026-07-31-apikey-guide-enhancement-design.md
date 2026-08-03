# API Key 配置傻瓜化增强设计

> 状态：待审查
> 日期：2026-07-31
> 范围：dashboard 前端 `Settings.vue` API Key 管理卡片

## 一、背景与问题

用户反馈 API Key 配置界面的提示"不够傻瓜化"。当前 [Settings.vue](file:///home/tishensnoopy/GEO%20FLOW+LUMORA%20CITE/dashboard/src/views/Settings.vue) 已实现可展开的"接入指引与常见错误"面板，包含平台/控制台/地域/默认模型/开通步骤/常见错误对照，但存在 3 个关键缺口：

1. **无价格信息** —— 用户不知道各平台大概要花多少钱、有没有免费额度、联网搜索是否额外收费
2. **步骤不够透彻** —— 缺少菜单层级路径，新手找不到控制台入口
3. **缺少费用预估** —— 用户无法评估"监测一个客户每月大概多少钱"

## 二、设计目标

让一个没有大模型平台使用经验的运营人员，能独立完成：
- 判断各平台大概成本，决定先开通哪个
- 按步骤指引找到控制台对应页面，拿到 API Key
- 开通必须的模型与联网搜索插件
- 通过"测试"按钮验证配置成功

## 三、已确认的决策

| 决策点 | 选择 |
|--------|------|
| 币种展示 | 国内平台用¥，国外平台用$并括号附¥换算（汇率7.2） |
| 费用估算 | 显示单次引用检测估算（输入~2000token + 输出~1000token + 1次联网搜索） |
| 价格时效 | 每个价格行末尾标注"（截至2026-07，以官网为准）" |
| 步骤详细度 | 细化到菜单路径，如"控制台 → 左侧菜单在线推理 → API Key 页 → 创建" |

## 四、最新定价数据（2026年7月调研）

### 4.1 国内平台（人民币）

| 平台 | 模型 | 输入¥/百万token | 输出¥/百万token | 免费额度 | 联网搜索额外 |
|------|------|----------------|----------------|---------|-------------|
| DeepSeek | deepseek-v4-flash | 1（缓存命中0.02） | 2 | 新用户赠送 | 无需（不支持联网） |
| 千问（百炼） | qwen-plus | 0.8 | 2 | 100万token（180天） | 按token计费，含在输出内 |
| 豆包（方舟） | doubao-seed-2.0-lite | 0.6~1.8 | 3.6~10.8 | 有体验额度 | 联网内容插件：2万次/月免费，超¥4/千次 |
| 文心（千帆） | ERNIE-4.5-Turbo | 0.8 | 3.2 | ERNIE-3.5/Speed 永久免费 | web_search 按token计费 |

### 4.2 国外平台（美元，附¥换算）

| 平台 | 模型 | 输入 | 输出 | 免费额度 | 联网搜索额外 |
|------|------|------|------|---------|-------------|
| OpenAI | GPT-5.6 Luna | $1（¥7.2） | $6（¥43.2） | 无 | $10/千次搜索 |
| Gemini | gemini-2.5-flash | $0.30（¥2.2） | $2.50（¥18） | 免费层（限速5RPM） | 5000次/月免费，超$14/千次 |
| Claude | Sonnet 4.6 | $3（¥21.6） | $15（¥108） | 无 | $10/千次搜索 |

## 五、UI 改动设计

### 5.1 数据结构增强

在每个厂商的 `guide` 对象中新增 `pricing` 字段：

```js
guide: {
  platform: '...',
  consoleUrl: '...',
  region: '...',
  model: '...',
  pricing: {
    currency: 'CNY',  // 或 'USD'
    input: '¥1',  // 每百万token
    output: '¥2',
    cacheHit: '¥0.02',  // 可选，缓存命中价
    freeQuota: '新用户赠送额度',
    searchExtra: '无需联网搜索',  // 或 '联网内容插件：2万次/月免费，超出¥4/千次'
    perCallEstimate: '约¥0.004',  // 单次引用检测估算
  },
  mustOpenTool: true/false,
  steps: [/* 细化到菜单路径 */],
  errors: [...],
}
```

### 5.2 模板新增行

在"默认模型"行下方、"开通步骤"行上方，新增 3 行：

```html
<div class="guide-row">
  <span class="g-label">价格参考</span>
  <span class="g-value">
    输入 {{ item.guide.pricing.input }} / 输出 {{ item.guide.pricing.output }} 每百万token
    <span v-if="item.guide.pricing.cacheHit">（缓存命中{{ item.guide.pricing.cacheHit }}）</span>
    <span class="price-disclaimer">（截至2026-07，以官网为准）</span>
  </span>
</div>
<div class="guide-row">
  <span class="g-label">免费额度</span>
  <span class="g-value">{{ item.guide.pricing.freeQuota }}</span>
</div>
<div class="guide-row">
  <span class="g-label">单次检测约</span>
  <span class="g-value g-highlight">{{ item.guide.pricing.perCallEstimate }}</span>
  <span class="g-sub">（输入~2000 + 输出~1000 token + 1次联网搜索）</span>
</div>
```

### 5.3 顶部 Alert 增强说明

现有 alert 保持不变，仅确认第①②③条已覆盖到位（已覆盖）。

### 5.4 步骤细化示例（豆包）

原步骤：
```
开通火山引擎账号 → 进入方舟控制台（cn-beijing 地域）
左侧"API Key"创建 Key（ark- 开头）
在"模型广场"激活所用模型
必须开通联网搜索插件
```

细化后：
```
1. 注册火山引擎账号（https://console.volcengine.com）→ 完成实名认证
2. 顶部地域切换器选择"北京（cn-beijing）"
3. 左侧菜单"方舟大模型服务平台" → "在线推理" → "API Key" → 点"创建 API Key"（ark- 开头）
4. 左侧菜单"模型广场" → 搜索 doubao-seed-2-0-lite → 点"激活模型"（不激活会报 ModelNotOpen）
5. 开通联网内容插件：访问 https://console.volcengine.com/common-buy/CC_content_plugin → 点"开通"（不开通会报 ToolNotOpen）
6. 回到本页点"测试"按钮，验证 Key + 模型 + 插件均可用
```

## 六、单次引用检测费用估算逻辑

引用检测单次调用典型消耗：
- 输入：~2000 token（系统提示词 + 问题 + 客户信息）
- 输出：~1000 token（AI 回答 + 引用 sources）
- 联网搜索：1 次

估算公式：
```
单次费用 = 输入量/1M × 输入价 + 输出量/1M × 输出价 + 联网搜索单次价
```

各平台估算结果：
- DeepSeek（不参与引用检测，仅问题生成）：约 ¥0.004/次
- 千问 qwen-plus：2000/1M×0.8 + 1000/1M×2 = ¥0.0036/次
- 豆包 doubao-seed-2.0-lite：2000/1M×0.6 + 1000/1M×3.6 = ¥0.0048/次
- 文心 ERNIE-4.5-Turbo：2000/1M×0.8 + 1000/1M×3.2 = ¥0.0048/次
- OpenAI GPT-5.6 Luna：2000/1M×$1 + 1000/1M×$6 = $0.008/次 ≈ ¥0.058/次
- Gemini 2.5-flash：2000/1M×$0.30 + 1000/1M×$2.50 = $0.0031/次 ≈ ¥0.022/次
- Claude Sonnet 4.6：2000/1M×$3 + 1000/1M×$15 = $0.021/次 ≈ ¥0.15/次

## 七、样式增强

新增 CSS 类：
- `.price-disclaimer`：灰色小字，价格时效声明
- `.g-highlight`：橙色加粗，单次检测费用
- `.g-sub`：灰色小字，补充说明

## 八、范围与非目标

### 范围内
- 修改 `dashboard/src/views/Settings.vue`：增强 `apiKeyItems` 数据 + 模板新增 3 行 + CSS

### 非目标
- 不修改后端 API Key 测试接口
- 不修改 API Key 存储/读取逻辑
- 不增加"月费计算器"交互功能（仅显示静态估算值）
- 不增加截图/图片（用菜单路径文字替代）

## 九、验证方式

1. `cd dashboard && npm run build` 通过
2. 启动前端 dev server，打开设置页，逐个展开 7 个厂商指引：
   - 价格参考行显示正确币种
   - 免费额度行有内容
   - 单次检测估算行显示
   - 步骤细化到菜单路径
3. 价格时效声明可见
