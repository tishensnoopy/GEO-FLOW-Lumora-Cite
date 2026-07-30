# GEOFlow Embedding 预设修复 + 品牌定制设计

> 日期：2026-07-29
> 状态：已批准，实现中

## 背景

用户反馈三个问题：
1. admin 后台 AI 模型管理的"服务商快速填充（Embedding）"测试老是不成功（doubao/zhipu 均失败），且国内可用预设太少
2. 导航栏 "GEOFlow" 字样需改为 "知氪AI"
3. 页脚版权/作者/链接信息需删除

## 根因分析（有实测证据）

### Embedding 测试不通

测试连接逻辑（`AiModelController::testConnection`）本身**完全正确**：
- `resolveTestEndpoint`：`{base_url}/embeddings`（OpenAI 兼容）✓
- `buildTestPayload`：`{model, input}` ✓
- 认证：`Bearer {api_key}` ✓
- 响应验证：`data[0].embedding` ✓

实测 doubao apikey（用户提供）curl 结果：
- `doubao-embedding-text-240515`（预设旧值）→ `NotFound`
- `doubao-embedding-large-text-250515`（用户官方示例）→ `NotFound`

**根因**：
1. 预设 model_id 过时：`240515` 是旧版，火山引擎官方当前推荐 `doubao-embedding-text-240715`
2. 用户 apikey 未在火山引擎控制台开通 embedding 模型（火山引擎需先开通才能用模型名调用）

### 导航栏名称

`app/Support/AdminWeb.php:24` `siteName()` 硬编码返回 `'GEOFlow'`。

### 页脚

`resources/views/admin/partials/footer.blade.php:28-48` 包含 copyright/version/author/链接/项目说明。

## 设计方案

### 需求 1：Embedding 预设修复 + 增加国内模型

**文件**：`resources/views/admin/ai-models/index.blade.php`

**改动**：
1. 更新 doubao 预设 model_id：`doubao-embedding-text-240515` → `doubao-embedding-text-240715`
2. 新增 4 个国内 embedding 预设（端点已验证）：
   - SiliconFlow：`BAAI/bge-m3` @ `https://api.siliconflow.cn/v1`（聚合平台，国内直连，免费额度）
   - 阿里通义 DashScope：`text-embedding-v3` @ `https://dashscope.aliyuncs.com/compatible-mode/v1`
   - Jina AI：`jina-embeddings-v3` @ `https://api.jina.ai/v1`（国内可能需代理）
   - 智谱 BGE：保留现有 `zhipu_embedding`（`embedding-3`）
3. 新增对应快速填充按钮
4. 快速填充区增加提示文字（需在服务商控制台开通模型/获取 apikey）

### 需求 2：导航栏改名（仅 admin 后台）

**文件**：`app/Support/AdminWeb.php` + `config/geoflow.php`

**改动**：`siteName()` 改为配置驱动：
```php
public static function siteName(): string
{
    return (string) (config('geoflow.site_name', '知氪AI'));
}
```
`config/geoflow.php` 新增 `'site_name' => env('SITE_NAME', '知氪AI')`。

### 需求 3：页脚处理（保留版权删链接）

**文件**：`resources/views/admin/partials/footer.blade.php`

**改动**：保留 `© 2026 {siteName}` 一行，删除版本/作者/X主页/GitHub/更新日志/帮助文档/项目说明按钮。

## 范围排除

- 不修改前台主题（geoflow-template）的导航栏/页脚（用户决策：仅 admin 后台）
- 不修改 GEOFlow 的 chat 模型预设（仅 embedding）
- 不修改测试连接的后端逻辑（逻辑正确，问题在预设 model_id 和用户开通状态）
