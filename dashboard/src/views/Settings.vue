<template>
  <div style="padding: 20px;">
    <h2>系统设置</h2>

    <!-- 收录检测设置 -->
    <el-card header="收录检测设置" style="margin-bottom: 20px;">
      <el-form :model="config" label-width="220px">
        <el-form-item label="收录检测频率（天/次）">
          <el-input-number v-model="config.index_scan_frequency" :min="1" :max="30" />
        </el-form-item>
        <el-form-item label="爬虫并发数">
          <el-input-number v-model="config.spider_concurrent" :min="1" :max="10" />
        </el-form-item>
        <el-form-item label="爬虫最小间隔（秒）">
          <el-input-number v-model="config.spider_interval_min" :min="1" :max="60" />
        </el-form-item>
        <el-form-item label="爬虫最大间隔（秒）">
          <el-input-number v-model="config.spider_interval_max" :min="1" :max="60" />
        </el-form-item>
      </el-form>
    </el-card>

    <!-- AI 采信检测设置 -->
    <el-card header="AI 采信检测设置" style="margin-bottom: 20px;">
      <el-form :model="config" label-width="220px">
        <el-form-item label="采信检测频率（天/次）">
          <el-input-number v-model="config.citation_scan_frequency" :min="1" :max="30" />
        </el-form-item>
        <el-form-item label="问题生成模型">
          <el-input v-model="config.ai_question_model" placeholder="deepseek-v4-flash" />
          <div class="hint">用于推断文章发布目的和生成检测问题的 LLM 模型（DeepSeek）</div>
        </el-form-item>
        <el-form-item label="引用检测模型">
          <el-checkbox-group v-model="citationModels">
            <!-- 注意：DeepSeek 不支持联网搜索，已于 providers.py 移除，不再是可选引用检测模型。
                 保留此处注释避免后续误加回。不勾选则自动使用所有已配置 API Key 的模型。 -->
            <el-checkbox label="doubao">豆包</el-checkbox>
            <el-checkbox label="qwen">千问</el-checkbox>
            <el-checkbox label="ernie">文心</el-checkbox>
            <el-checkbox label="openai">ChatGPT</el-checkbox>
            <el-checkbox label="gemini">Gemini</el-checkbox>
            <el-checkbox label="claude">Claude</el-checkbox>
          </el-checkbox-group>
          <div class="hint">不勾选则自动使用所有已配置 API Key 的模型；DeepSeek 因不支持联网搜索已移除，不再作为引用检测模型。</div>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- AI API Key 管理 -->
    <el-card header="AI API Key 管理" style="margin-bottom: 20px;">
      <el-alert type="warning" :closable="false" style="margin-bottom: 16px;">
        <template #title>
          <strong>国内大模型厂商接入须知</strong>
        </template>
        <div style="line-height: 1.8; font-size: 12px;">
          ① 国内厂商（豆包/千问/文心）除创建 API Key 外，还需在对应控制台 <b>单独激活模型</b> 并 <b>开通联网搜索插件</b>，否则引用检测会报 ModelNotOpen / ToolNotOpen 错误。<br/>
          ② 每个输入框下方可点击 <b>"接入指引与常见错误"</b> 查看该厂商的开通步骤、控制台链接、地域限制与错误对照表。<br/>
          ③ API Key 仅在服务端存储，前端仅显示脱敏值（如 sk-****81f）。修改后点击"保存配置"生效，留空表示不修改。
        </div>
      </el-alert>
      <el-form :model="config" label-width="220px">
        <el-form-item
          v-for="item in apiKeyItems"
          :key="item.key"
          :label="item.label"
        >
          <div class="key-row">
            <el-input v-model="config[item.key]" show-password :placeholder="item.placeholder" style="flex: 1;" />
            <el-button
              :loading="testingKey === item.key"
              :type="testResult[item.key]?.success === true ? 'success' : (testResult[item.key]?.success === false ? 'danger' : 'default')"
              @click="testApiKey(item.key)"
            >测试</el-button>
          </div>
          <div class="hint">{{ item.hint }}</div>

          <!-- 接入指引与常见错误（可展开） -->
          <div v-if="item.guide" class="guide-toggle" @click="toggleGuide(item.key)">
            <el-icon class="guide-arrow"><component :is="guideOpen[item.key] ? 'ArrowDown' : 'ArrowRight'" /></el-icon>
            <span>接入指引与常见错误</span>
            <el-tag v-if="item.guide.mustOpenTool" size="small" type="warning" effect="plain" style="margin-left: 8px;">需开通联网搜索</el-tag>
          </div>
          <el-collapse-transition>
            <div v-show="guideOpen[item.key]" class="guide-box">
              <div class="guide-row"><span class="g-label">平台</span><span class="g-value">{{ item.guide.platform }}</span></div>
              <div class="guide-row"><span class="g-label">控制台</span>
                <a class="g-link" :href="item.guide.consoleUrl" target="_blank" rel="noopener">{{ item.guide.consoleUrl }}</a>
              </div>
              <div class="guide-row"><span class="g-label">地域</span><span class="g-value">{{ item.guide.region }}</span></div>
              <div class="guide-row"><span class="g-label">默认模型</span><span class="g-value">{{ item.guide.model }}</span></div>
              <div class="guide-row"><span class="g-label">开通步骤</span></div>
              <ol class="guide-steps">
                <li v-for="(s, i) in item.guide.steps" :key="i" v-html="s"></li>
              </ol>
              <div class="guide-row"><span class="g-label">常见错误对照</span></div>
              <ul class="guide-errors">
                <li v-for="(e, i) in item.guide.errors" :key="i">
                  <code>{{ e.code }}</code> <span class="err-arrow">→</span> {{ e.fix }}
                </li>
              </ul>
            </div>
          </el-collapse-transition>

          <div v-if="testResult[item.key]" class="test-result" :class="testResult[item.key].success ? 'ok' : 'fail'">
            <el-icon><component :is="testResult[item.key].success ? 'CircleCheck' : 'CircleClose'" /></el-icon>
            {{ testResult[item.key].message }}
          </div>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 操作按钮 -->
    <div style="text-align: center;">
      <el-button type="primary" @click="saveConfig">保存配置</el-button>
      <el-button type="warning" @click="triggerScan('index')">立即收录扫描</el-button>
      <el-button type="warning" @click="triggerScan('citation')">立即 AI 采信扫描</el-button>
      <!-- I3：新增 AI 收录检测 / 全量扫描触发入口，对接 Phase 3 统一扫描入口 -->
      <el-button type="success" @click="triggerScan('ai_index')">AI 收录扫描</el-button>
      <el-button type="success" @click="triggerScan('all')">全量扫描</el-button>
    </div>

    <!-- 扫描运行状态面板（阶段 4 - ⑤）：触发扫描后滑出，实时显示进度+模型状态。
         I2：透传 task-ids 给 ScanPanel，all 类型时驱动三阶段进度环（index → ai_index → citation）。 -->
    <ScanPanel v-model="scanPanelVisible" :task-id="scanTaskId" :task-ids="scanTaskIds" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, reactive } from 'vue'
import { ElMessage } from 'element-plus'
import { CircleCheck, CircleClose, ArrowDown, ArrowRight } from '@element-plus/icons-vue'
import api from '../api'
import ScanPanel from '../components/ScanPanel.vue'
import { useScanTrigger } from '@/composables/useScanTrigger'

const config = ref({})

// 引用检测模型复选框：与 config.ai_citation_models（逗号分隔字符串）双向同步
const citationModels = computed({
  get() {
    const val = config.value.ai_citation_models || ''
    return val ? val.split(',').map(s => s.trim()).filter(Boolean) : []
  },
  set(val) {
    config.value.ai_citation_models = val.join(',')
  }
})

// API Key 配置项元数据：统一渲染输入框 + 测试按钮，避免重复模板。
// 注意：deepseek 为问题生成模型（非引用检测），其余为引用检测模型。
// guide 字段为各厂商接入指引（平台/控制台/地域/模型/步骤/常见错误），点击"接入指引与常见错误"展开。
const apiKeyItems = [
  {
    key: 'ai_deepseek_api_key',
    label: 'DeepSeek API Key',
    placeholder: 'sk-...',
    hint: '问题生成+目的推断用（必填），OpenAI 兼容接口。无需开通联网搜索工具。',
    guide: {
      platform: 'DeepSeek 开放平台',
      consoleUrl: 'https://platform.deepseek.com/api_keys',
      region: '无地域限制，国内可直连',
      model: 'deepseek-v4-flash（问题生成模型，非引用检测。可在上方"问题生成模型"字段修改）',
      mustOpenTool: false,
      steps: [
        '注册 DeepSeek 账号并完成实名认证',
        '进入 API Keys 页面创建 Key（sk- 开头）',
        '账户需充值余额（按 token 计费，新用户有免费额度）',
        'DeepSeek 为 OpenAI 兼容 chat 接口，<b>无需额外开通联网搜索工具</b>',
      ],
      errors: [
        { code: '402 insufficient balance', fix: '账户余额不足，请充值' },
        { code: '401 Authentication Fails', fix: 'API Key 错误或已失效，重新创建' },
        { code: '400 Model Not Found', fix: '模型名拼写错误，确认使用 deepseek-v4-flash 等有效模型' },
      ],
    },
  },
  {
    key: 'ai_dashscope_api_key',
    label: 'DashScope API Key（千问）',
    placeholder: 'sk-...',
    hint: '千问引用检测用（阿里云百炼平台）。',
    guide: {
      platform: '阿里云百炼（DashScope）',
      consoleUrl: 'https://bailian.console.aliyun.com/?apiKey=1#/api-key',
      region: 'cn-beijing / cn-hangzhou（华东2/华北2）',
      model: 'qwen3.6-plus（默认，可在系统环境变量 CITATION_QWEN_MODEL 覆盖）',
      mustOpenTool: true,
      steps: [
        '开通阿里云账号 → 进入百炼控制台',
        '左侧"API-KEY 管理"创建 Key（sk- 开头）',
        '在"模型广场"开通通义千问模型服务（如 qwen-plus / qwen3.6-plus）',
        '<b>必须开通联网搜索能力</b>：百炼控制台 → 模型广场 → 确认 qwen 模型支持联网搜索（enable_thinking 关闭后调用 web_search）',
        '点"测试"验证 Key 与联网搜索是否同时可用',
      ],
      errors: [
        { code: 'AccessDenied', fix: '未开通百炼或该模型服务 → 模型广场开通' },
        { code: 'InvalidApiKey', fix: 'Key 错误或地域不匹配' },
        { code: '无 sources 返回', fix: '联网搜索未生效，确认模型支持并已开通搜索能力' },
      ],
    },
  },
  {
    key: 'ai_ark_api_key',
    label: 'ARK API Key（豆包）',
    placeholder: 'ark-...',
    hint: '豆包引用检测用（火山引擎方舟平台）。',
    guide: {
      platform: '火山引擎方舟（Ark）',
      consoleUrl: 'https://console.volcengine.com/ark/region:ark+cn-beijing/apiKey',
      region: '仅 cn-beijing（北京）地域',
      model: 'doubao-seed-2-0-lite-260428（默认，pro 版需单独激活）',
      mustOpenTool: true,
      steps: [
        '开通火山引擎账号 → 进入方舟控制台（cn-beijing 地域）',
        '左侧"API Key"创建 Key（ark- 开头）',
        '在"模型广场"激活所用模型（如 doubao-seed-2-0-lite-260428）—— <b>不激活会报 ModelNotOpen</b>',
        '<b>必须开通联网搜索插件</b>（不开通会报 ToolNotOpen）：<br/><a href="https://console.volcengine.com/common-buy/CC_content_plugin" target="_blank" rel="noopener">https://console.volcengine.com/common-buy/CC_content_plugin</a>',
        '模型与插件均激活后，点"测试"验证',
      ],
      errors: [
        { code: 'ModelNotOpen', fix: '模型未激活 → 方舟控制台"模型广场"激活对应模型 ID' },
        { code: 'ToolNotOpen: web search', fix: '联网搜索未开通 → 上方 CC_content_plugin 链接开通插件' },
        { code: '401', fix: 'Key 错误或未授权该模型' },
        { code: '404 Not Found', fix: '模型 ID 错误或地域不对，确认用 cn-beijing 且模型 ID 拼写正确' },
      ],
    },
  },
  {
    key: 'ai_baidu_api_key',
    label: '百度千帆 API Key（文心）',
    placeholder: '',
    hint: '文心引用检测用（百度千帆平台）。',
    guide: {
      platform: '百度千帆大模型平台',
      consoleUrl: 'https://console.bce.baidu.com/qianfan/ais/console/applicationConsole/application',
      region: '百度智能云（多地域可选）',
      model: 'ernie-5.0（默认）',
      mustOpenTool: true,
      steps: [
        '登录百度智能云 → 进入千帆大模型平台',
        '"应用接入"创建应用，获取 API Key 与 Secret Key',
        '在"模型服务"开通文心一言对应模型（如 ERNIE-5.0）',
        '<b>必须开启联网搜索</b>：请求中 web_search.enable=true，需模型支持（ernie 系列部分模型支持）',
        '点"测试"验证',
      ],
      errors: [
        { code: '110 access token invalid', fix: 'API Key / Secret Key 错误，检查应用凭证' },
        { code: '18 Open api daily request limit reached', fix: 'QPS/配额超限，提升配额或更换模型' },
        { code: '模型不支持 web_search', fix: '更换支持联网搜索的 ERNIE 模型版本' },
      ],
    },
  },
  {
    key: 'ai_openai_api_key',
    label: 'OpenAI API Key',
    placeholder: 'sk-...',
    hint: 'ChatGPT 引用检测用。国内访问需代理。',
    guide: {
      platform: 'OpenAI Platform',
      consoleUrl: 'https://platform.openai.com/api-keys',
      region: '国内不可直连，需通过代理访问',
      model: 'gpt-5（默认）',
      mustOpenTool: true,
      steps: [
        '登录 OpenAI Platform → API Keys 创建 Key（sk- 开头）',
        '账户需绑定付费方式并充值余额',
        '<b>必须开通 web_search 工具</b>：Responses API 中 tools=[{type:"web_search"}]，该工具单独计费',
        '确认网络可访问 api.openai.com（国内需代理）',
      ],
      errors: [
        { code: '401 Incorrect API key', fix: 'Key 错误或已撤销' },
        { code: '429 Rate limit', fix: '触发限流，降低频率或升级套餐' },
        { code: '403 Country/region', fix: '区域受限，需使用代理' },
      ],
    },
  },
  {
    key: 'ai_gemini_api_key',
    label: 'Gemini API Key',
    placeholder: '',
    hint: 'Gemini 引用检测用（Google AI Studio）。国内访问需代理。',
    guide: {
      platform: 'Google AI Studio',
      consoleUrl: 'https://aistudio.google.com/app/apikey',
      region: '国内不可直连，需通过代理访问',
      model: 'gemini-2.5-flash（默认）',
      mustOpenTool: false,
      steps: [
        '登录 Google AI Studio → Get API Key 创建 Key',
        'Gemini 自带 google_search grounding 工具，<b>无需单独开通</b>',
        '在请求中 tools=[{"google_search":{}}] 启用联网搜索',
        '确认网络可访问 generativelanguage.googleapis.com（国内需代理）',
      ],
      errors: [
        { code: '403 User location not supported', fix: '区域受限，需使用代理切换至支持的地区' },
        { code: '429 RESOURCE_EXHAUSTED', fix: '免费配额用尽，升级或等待重置' },
        { code: 'API key not valid', fix: 'Key 错误或已删除，重新创建' },
      ],
    },
  },
  {
    key: 'ai_anthropic_api_key',
    label: 'Anthropic API Key',
    placeholder: 'sk-ant-...',
    hint: 'Claude 引用检测用。国内访问需代理。',
    guide: {
      platform: 'Anthropic Console',
      consoleUrl: 'https://console.anthropic.com/settings/keys',
      region: '国内不可直连，需通过代理访问',
      model: 'claude-sonnet-4-5（默认）',
      mustOpenTool: true,
      steps: [
        '登录 Anthropic Console → API Keys 创建 Key（sk-ant- 开头）',
        '账户需充值余额',
        '<b>必须开通 web_search 工具</b>：tools=[{type:"web_search_20250305"}]，该工具单独计费',
        '确认网络可访问 api.anthropic.com（国内需代理）',
      ],
      errors: [
        { code: '401 invalid x-api-key', fix: 'Key 错误或已失效' },
        { code: '429 rate_limit', fix: '触发限流，降低频率或升级用量层级' },
        { code: '400 tool not found', fix: 'web_search 工具名/版本错误，确认用 web_search_20250305' },
      ],
    },
  },
]

// 接入指引展开状态：guideOpen[key] 控制每个厂商指引区块的展开/收起
const guideOpen = reactive({})
function toggleGuide(key) {
  guideOpen[key] = !guideOpen[key]
}

// 测试中状态 + 测试结果：testingKey 标记当前正在测试的 key，testResult 存各 key 的结果
const testingKey = ref('')
const testResult = reactive({})

// 扫描面板状态（阶段 4 - ⑤ + I1+I2+I4）：
// 使用 useScanTrigger 复用扫描触发逻辑，统一调 /admin/scan/trigger（Phase 3 统一入口），
// 支持 index/citation/ai_index/all 四种类型。taskIds 仅在 all 类型时填充，
// 驱动 ScanPanel 三阶段进度环（index → ai_index → citation）。
const {
  trigger: triggerScanTask,
  taskIds: scanTaskIds,
  currentTaskId: scanTaskId,
  panelVisible: scanPanelVisible,
} = useScanTrigger()

// 测试单个 API Key：调用后端 /config/test-key 端点即时验证。
// 若输入框是脱敏占位（含 ****）或为空，后端会用已存储的 Key 测试。
async function testApiKey(keyType) {
  testingKey.value = keyType
  // 清掉旧结果，避免显示陈旧状态
  testResult[keyType] = undefined
  try {
    const currentValue = config.value[keyType] || ''
    const res = await api.post('/config/test-key', {
      key_type: keyType,
      api_key: currentValue,
    })
    testResult[keyType] = {
      success: !!res.data.success,
      message: res.data.message || (res.data.success ? 'Key 可用' : 'Key 不可用'),
    }
  } catch (e) {
    const detail = e.response?.data?.detail || e.message || '测试请求失败'
    testResult[keyType] = { success: false, message: detail }
  } finally {
    testingKey.value = ''
  }
}

onMounted(async () => {
  try {
    const res = await api.get('/config')
    config.value = res.data
  } catch (e) {
    console.error('加载配置失败', e)
    ElMessage.error('加载配置失败')
  }
})

const saveConfig = async () => {
  try {
    await api.put('/config', config.value)
    ElMessage.success('配置保存成功')
    // 重新加载以获取脱敏后的 API Key 显示
    const res = await api.get('/config')
    config.value = res.data
  } catch (e) {
    ElMessage.error('保存失败')
  }
}

// I4：迁移到 Phase 3 统一扫描入口 /admin/scan/trigger（body 传 scan_type）。
// 旧路径参数式 /scan/trigger/{type} 已 deprecated 且不支持 ai_index/all。
// useScanTrigger 内部调统一入口，并设置 currentTaskId / taskIds / panelVisible。
const triggerScan = async (type) => {
  try {
    const data = await triggerScanTask(type)
    // currentTaskId 为 null 表示无待检测 URL：关闭面板，提示用户
    if (!scanTaskId.value) {
      scanPanelVisible.value = false
      ElMessage.info(data.message || '没有待检测的 URL')
    } else {
      ElMessage.success(data.message || '扫描任务已触发')
    }
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '触发失败')
  }
}
</script>

<style scoped>
.hint {
  font-size: 12px;
  color: var(--mute, #909399);
  margin-top: 4px;
}
.key-row {
  display: flex;
  gap: 8px;
  width: 100%;
}
.test-result {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 6px;
  font-size: 12px;
  padding: 4px 8px;
  border-radius: var(--radius-md, 4px);
}
.test-result.ok {
  color: #67c23a;
  background: #f0f9eb;
}
.test-result.fail {
  color: #f56c6c;
  background: #fef0f0;
}

/* 接入指引与常见错误 */
.guide-toggle {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-top: 8px;
  padding: 4px 10px;
  font-size: 12px;
  font-weight: 500;
  color: var(--signal, #0D9488);
  cursor: pointer;
  border-radius: var(--radius-pill, 999px);
  border: 1px solid var(--signal-line, rgba(13, 148, 136, 0.30));
  background: var(--signal-soft, rgba(13, 148, 136, 0.10));
  transition: background var(--transition-fast, 150ms ease-out);
  user-select: none;
}
.guide-toggle:hover {
  background: rgba(13, 148, 136, 0.18);
}
.guide-arrow {
  font-size: 12px;
}
.guide-box {
  margin-top: 8px;
  padding: 12px 14px;
  background: var(--paper, #FAFAF7);
  border: 1px solid var(--ink-line, rgba(26, 26, 26, 0.12));
  border-radius: var(--radius-md, 4px);
  font-size: 12px;
  line-height: 1.7;
  color: var(--ink, #1A1A1A);
}
.guide-row {
  display: flex;
  gap: 8px;
  margin-bottom: 4px;
}
.g-label {
  flex: 0 0 64px;
  color: var(--mute, #78716C);
  font-weight: 600;
}
.g-value {
  flex: 1;
}
.g-link {
  color: var(--signal, #0D9488);
  text-decoration: none;
  word-break: break-all;
}
.g-link:hover {
  text-decoration: underline;
}
.guide-steps {
  margin: 4px 0 8px 16px;
  padding-left: 8px;
}
.guide-steps li {
  margin-bottom: 4px;
}
.guide-errors {
  margin: 4px 0 0 16px;
  padding-left: 8px;
  list-style: none;
}
.guide-errors li {
  margin-bottom: 4px;
}
.guide-errors code {
  background: rgba(231, 111, 81, 0.12);
  color: var(--alert, #E76F51);
  padding: 1px 6px;
  border-radius: 3px;
  font-family: var(--font-mono, monospace);
  font-size: 11px;
}
.err-arrow {
  color: var(--mute, #78716C);
  margin: 0 4px;
}
</style>
