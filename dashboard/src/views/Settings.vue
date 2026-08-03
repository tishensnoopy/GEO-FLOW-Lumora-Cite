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

              <!-- 价格参考 / 免费额度 / 单次检测估算（傻瓜化：让用户一眼看清成本） -->
              <div v-if="item.guide.pricing" class="guide-row">
                <span class="g-label">价格参考</span>
                <span class="g-value">
                  输入 <b>{{ item.guide.pricing.input }}</b> / 输出 <b>{{ item.guide.pricing.output }}</b>
                  <span class="g-unit">每百万token</span>
                  <span v-if="item.guide.pricing.cacheHit">（缓存命中{{ item.guide.pricing.cacheHit }}）</span>
                  <span class="price-disclaimer">（截至2026-07，以官网为准）</span>
                </span>
              </div>
              <div v-if="item.guide.pricing" class="guide-row">
                <span class="g-label">免费额度</span>
                <span class="g-value">{{ item.guide.pricing.freeQuota }}</span>
              </div>
              <div v-if="item.guide.pricing" class="guide-row">
                <span class="g-label">联网搜索</span>
                <span class="g-value">{{ item.guide.pricing.searchExtra }}</span>
              </div>
              <div v-if="item.guide.pricing" class="guide-row estimate-row">
                <span class="g-label">单次检测约</span>
                <span class="g-value">
                  <b class="g-highlight">{{ item.guide.pricing.perCallEstimate }}</b>
                  <span class="g-sub">（输入~2000 + 输出~1000 token + 1次联网搜索）</span>
                </span>
              </div>

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
    <!-- 扫描类型说明：帮助用户区分 4 种扫描的含义、区别与扫描范围 -->
    <el-alert type="info" :closable="false" style="margin-bottom: 16px;">
      <template #title>
        <strong>扫描类型说明（所有扫描均为增量，不会重复扫描已检测过的内容）</strong>
      </template>
      <div style="line-height: 1.9; font-size: 12px;">
        <b>① 搜索引擎收录检测</b>：检测网址是否被百度/谷歌/必应等搜索引擎收录。<b>范围</b>：仅扫描<b>新增/未检测过</b>的已分发网址（SEO 基础）<br/>
        <b>② AI 收录检测</b>：检测网址是否被豆包/千问/文心等 AI 大模型收录进知识库。<b>范围</b>：仅扫描<b>新增或上次失败</b>的网址×模型组合（GEO 核心）<br/>
        <b>③ AI 引用检测</b>：检测文章内容是否被 AI 大模型在回答中引用并提及。<b>范围</b>：仅扫描<b>已收录 + 有监测问题 + 未检测过采信</b>的网址（AI 采信）<br/>
        <b>④ 全量检测（三合一）</b>：依次执行 ①→②→③ 全流程。<b>范围</b>：三阶段全跑，但每阶段仍是增量扫描，不会重复检测已出结果的内容<br/>
        <span style="color: var(--mute, #78716C);">提示：如需重新检测某个网址，请在"文章列表"中单独触发该网址的重扫。</span>
      </div>
    </el-alert>

    <!-- 预估消耗：基于后端 /admin/scan/estimate 返回的 pending 数量 + 已配置模型实时计算 -->
    <el-card v-if="estimateCosts" class="estimate-card" shadow="never" style="margin-bottom: 16px;">
      <template #header>
        <div class="estimate-header">
          <span><strong>本次扫描预估消耗</strong> <span class="e-sub">（基于当前待扫描数量，增量计算）</span></span>
          <el-button text size="small" :loading="estimateLoading" @click="loadEstimate">
            <el-icon><Refresh /></el-icon> 刷新
          </el-button>
        </div>
      </template>
      <div class="estimate-grid">
        <div class="estimate-item">
          <div class="e-label">① 搜索引擎收录</div>
          <div class="e-value">{{ estimateCosts.index.count }} 条网址</div>
          <div class="e-cost free">免费（仅爬虫，不调 AI）</div>
        </div>
        <div class="estimate-item">
          <div class="e-label">② AI 收录检测</div>
          <div class="e-value">{{ estimateCosts.ai_index.count }} 次调用
            <span class="e-models" v-if="estimateCosts.ai_index.models.length">
             （{{ estimateCosts.ai_index.models.map(m => MODEL_LABELS[m] || m).join(' / ') }}）
            </span>
          </div>
          <div class="e-cost">预估 <b>{{ formatCost(estimateCosts.ai_index.cost) }}</b></div>
        </div>
        <div class="estimate-item">
          <div class="e-label">③ AI 引用检测</div>
          <div class="e-value">{{ estimateCosts.citation.count }} 个网址 × {{ estimateCosts.citation.modelCount }} 个模型</div>
          <div class="e-cost" v-if="estimateCosts.citation.count">
            预估 <b>{{ formatCost(estimateCosts.citation.costMin) }} ~ {{ formatCost(estimateCosts.citation.costMax) }}</b>
          </div>
          <div class="e-cost free" v-else>暂无符合条件的网址</div>
        </div>
        <div class="estimate-item estimate-total">
          <div class="e-label">④ 全量检测合计</div>
          <div class="e-value">{{ estimateCosts.index.count + estimateCosts.ai_index.count + estimateCosts.citation.count }} 项任务</div>
          <div class="e-cost">
            预估 <b class="e-highlight">{{ formatCost(estimateCosts.total.costMin) }} ~ {{ formatCost(estimateCosts.total.costMax) }}</b>
          </div>
        </div>
      </div>
      <div class="estimate-note">
        说明：① 零成本；② 按各模型实际调用次数精确计算；③ 为上界预估（实际只检测已收录模型子集，费用可能更低）；价格截至2026-07，以官网为准。
      </div>
    </el-card>

    <div class="scan-buttons">
      <el-tooltip content="保存上方的所有配置项（检测频率、API Key 等）。扫描前请先保存配置。" placement="top" effect="dark">
        <el-button type="primary" @click="saveConfig">保存配置</el-button>
      </el-tooltip>
      <el-tooltip content="增量扫描：仅检测新增/未检测过的已分发网址，是否被百度/谷歌/必应等搜索引擎收录。已检测过的不重复扫描。" placement="top" effect="dark">
        <el-button type="warning" @click="triggerScan('index')">① 搜索引擎收录检测</el-button>
      </el-tooltip>
      <el-tooltip content="增量扫描：仅检测新增或上次失败的 网址×AI模型 组合，是否被豆包/千问/文心等 AI 大模型收录进知识库。已出结果的不重复扫描。" placement="top" effect="dark">
        <el-button type="success" @click="triggerScan('ai_index')">② AI 收录检测</el-button>
      </el-tooltip>
      <el-tooltip content="增量扫描：仅检测 已被AI收录 + 客户有监测问题 + 未检测过采信 的网址，是否被 AI 大模型在回答中引用。条件不满足的网址自动跳过。" placement="top" effect="dark">
        <el-button type="success" @click="triggerScan('citation')">③ AI 引用检测</el-button>
      </el-tooltip>
      <el-tooltip content="依次执行 ①→②→③ 全流程，每阶段仍为增量扫描（不重复检测已出结果的内容）。最全面但耗时最长。如需重扫单个网址请在文章列表操作。" placement="top" effect="dark">
        <el-button type="danger" @click="triggerScan('all')">④ 全量检测（三合一）</el-button>
      </el-tooltip>
    </div>

    <!-- 扫描运行状态面板（阶段 4 - ⑤）：触发扫描后滑出，实时显示进度+模型状态。
         I2：透传 task-ids 给 ScanPanel，all 类型时驱动三阶段进度环（index → ai_index → citation）。 -->
    <ScanPanel v-model="scanPanelVisible" :task-id="scanTaskId" :task-ids="scanTaskIds" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, reactive } from 'vue'
import { ElMessage } from 'element-plus'
import { CircleCheck, CircleClose, ArrowDown, ArrowRight, Refresh } from '@element-plus/icons-vue'
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
      pricing: {
        input: '¥1',
        output: '¥2',
        cacheHit: '¥0.02',
        freeQuota: '新用户赠送额度（官网不时发放，如充10送10活动）',
        searchExtra: '无需开通（DeepSeek 不支持联网搜索，仅用于问题生成）',
        perCallEstimate: '¥0.004（仅问题生成，非引用检测）',
      },
      mustOpenTool: false,
      steps: [
        '打开 <a href="https://platform.deepseek.com" target="_blank" rel="noopener">platform.deepseek.com</a> → 注册账号（支持手机号/邮箱）→ 完成实名认证',
        '登录后左侧菜单"API Keys" → 点"创建 API Key" → 复制 Key（sk- 开头，仅显示一次务必保存）',
        '左侧菜单"费用管理" → 充值余额（按 token 计费，新用户有赠送额度可先体验）',
        'DeepSeek 为 OpenAI 兼容 chat 接口，<b>无需额外开通联网搜索工具</b>，充值后即可用',
        '回到本页粘贴 Key → 点"测试"按钮验证',
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
      model: 'qwen-plus（默认，可在系统环境变量 CITATION_QWEN_MODEL 覆盖）',
      pricing: {
        input: '¥0.8',
        output: '¥2',
        freeQuota: '新用户 100 万 token 免费（开通百炼后 180 天内有效）',
        searchExtra: '联网搜索按 token 计费，费用含在输出 token 内，不单独收费',
        perCallEstimate: '约 ¥0.004',
      },
      mustOpenTool: true,
      steps: [
        '打开 <a href="https://bailian.console.aliyun.com" target="_blank" rel="noopener">bailian.console.aliyun.com</a> → 用阿里云账号登录 → 首次进入点"立即开通"百炼服务（免费开通）',
        '左侧菜单"API-KEY 管理" → 点"创建我的 API-KEY" → 选择业务空间 → 复制 Key（sk- 开头）',
        '左侧菜单"模型广场" → 搜索"qwen-plus" → 进入模型详情 → 点"开通服务"（<b>不开通会报 AccessDenied</b>）',
        '<b>必须开通联网搜索能力</b>：模型广场 → 确认 qwen-plus 支持"联网搜索"工具 → 在调用时传入 enable_search=true（本系统已自动配置）',
        '回到本页粘贴 Key → 点"测试"验证 Key 与联网搜索是否同时可用',
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
      pricing: {
        input: '¥0.6~1.8',
        output: '¥3.6~10.8',
        freeQuota: '有体验额度（具体以控制台显示为准）',
        searchExtra: '联网内容插件：2万次/月免费，超出 ¥4/千次',
        perCallEstimate: '约 ¥0.005（2万次/月免费额度内）/ ¥0.009（超出后）',
      },
      mustOpenTool: true,
      steps: [
        '打开 <a href="https://console.volcengine.com" target="_blank" rel="noopener">console.volcengine.com</a> → 注册火山引擎账号 → 完成实名认证',
        '页面顶部地域切换器 → 选择"<b>北京（cn-beijing）</b>"（方舟仅此地域可用）',
        '左侧菜单"方舟大模型服务平台" → "在线推理" → "API Key" → 点"创建 API Key" → 复制 Key（ark- 开头）',
        '左侧菜单"模型广场" → 搜索"doubao-seed-2-0-lite" → 进入详情 → 点"<b>激活模型</b>"（不激活会报 ModelNotOpen）',
        '<b>必须开通联网内容插件</b>：访问 <a href="https://console.volcengine.com/common-buy/CC_content_plugin" target="_blank" rel="noopener">CC_content_plugin</a> → 点"开通"（不开通会报 ToolNotOpen: web search）',
        '模型与插件均激活后 → 回到本页点"测试"按钮验证',
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
      model: 'ernie-4.5-turbo（默认，ERNIE-3.5/Speed 永久免费可作备选）',
      pricing: {
        input: '¥0.8',
        output: '¥3.2',
        freeQuota: 'ERNIE-3.5-8K / ERNIE-Speed-8K 永久免费不限量；ERNIE-4.5-Turbo 新用户 100 万 token（3 个月）',
        searchExtra: 'web_search 按 token 计费，费用含在输出 token 内，不单独收费',
        perCallEstimate: '约 ¥0.005',
      },
      mustOpenTool: true,
      steps: [
        '打开 <a href="https://console.bce.baidu.com/qianfan/overview" target="_blank" rel="noopener">console.bce.baidu.com/qianfan</a> → 登录百度智能云账号 → 完成实名认证',
        '首次进入点"立即开通"千帆模型服务（免费开通）→ 左侧菜单"应用接入" → "创建应用" → 填写应用名称 → 确认创建',
        '应用列表点"查看" → 复制 <b>API Key</b>（bce-v3- 开头）与 <b>Secret Key</b> → 本系统只需填 API Key',
        '左侧菜单"模型服务" → 找到"ERNIE-4.5-Turbo" → 点"开通服务"（<b>不开通会报 110 access token invalid</b>）',
        '<b>必须开启联网搜索</b>：调用时传 web_search.enable=true（本系统已自动配置），需模型支持（ernie 系列部分模型支持）',
        '回到本页粘贴 API Key → 点"测试"验证',
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
      model: 'gpt-5.6-luna（默认，轻量经济款；可在环境变量 CITATION_OPENAI_MODEL 覆盖为 terra/sol）',
      pricing: {
        input: '$1（¥7.2）',
        output: '$6（¥43.2）',
        cacheHit: '$0.1（¥0.72）',
        freeQuota: '无免费额度，需充值后使用',
        searchExtra: 'web_search 工具 $10/千次（约 ¥72/千次），每次搜索约 ¥0.07',
        perCallEstimate: '约 ¥0.13（含联网搜索费用）',
      },
      mustOpenTool: true,
      steps: [
        '打开 <a href="https://platform.openai.com" target="_blank" rel="noopener">platform.openai.com</a> → 注册/登录 OpenAI 账号（<b>国内需先配置代理</b>）',
        '左侧菜单"API Keys" → 点"Create new secret key" → 复制 Key（sk- 开头，仅显示一次务必保存）',
        '左侧菜单"Settings" → "Billing" → 绑定信用卡并充值余额（<b>不充值会报 429</b>）',
        '<b>必须开通 web_search 工具</b>：Responses API 中 tools=[{type:"web_search"}]，该工具单独计费 $10/千次（本系统已自动配置）',
        '确认网络可访问 api.openai.com（国内需代理）→ 回到本页粘贴 Key → 点"测试"验证',
      ],
      errors: [
        { code: '401 Incorrect API key', fix: 'Key 错误或已撤销' },
        { code: '429 Rate limit', fix: '触发限流或余额不足，降低频率或充值' },
        { code: '403 Country/region', fix: '区域受限，需使用代理切换至支持的地区' },
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
      model: 'gemini-2.5-flash（默认，性价比最佳；可选 flash-lite 更便宜）',
      pricing: {
        input: '$0.30（¥2.2）',
        output: '$2.50（¥18）',
        freeQuota: '有免费层（限速 5 RPM / 20 次/天），适合小规模测试',
        searchExtra: 'Google 搜索 grounding：每月 5000 次免费，超出 $14/千次（约 ¥100/千次）',
        perCallEstimate: '约 ¥0.022（5000次/月免费额度内）/ ¥0.12（超出后）',
      },
      mustOpenTool: false,
      steps: [
        '打开 <a href="https://aistudio.google.com" target="_blank" rel="noopener">aistudio.google.com</a> → 登录 Google 账号（<b>国内需先配置代理</b>）',
        '左侧菜单"Get API Key" → 点"Create API Key" → 选择项目 → 复制 Key',
        'Gemini 自带 <b>google_search grounding 工具，无需单独开通</b>（与豆包/千问不同）',
        '在请求中 tools=[{"google_search":{}}] 启用联网搜索（本系统已自动配置）',
        '确认网络可访问 generativelanguage.googleapis.com（国内需代理）→ 回到本页粘贴 Key → 点"测试"验证',
      ],
      errors: [
        { code: '403 User location not supported', fix: '区域受限，需使用代理切换至支持的地区' },
        { code: '429 RESOURCE_EXHAUSTED', fix: '免费配额用尽，升级付费层或等待重置' },
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
      model: 'claude-sonnet-4-6（默认；可选 haiku-4-5 更便宜 $1/$5）',
      pricing: {
        input: '$3（¥21.6）',
        output: '$15（¥108）',
        cacheHit: '$0.30（¥2.16）',
        freeQuota: '无免费额度，需充值后使用（新用户有 $5 体验额度）',
        searchExtra: 'web_search 工具 $10/千次（约 ¥72/千次），每次搜索约 ¥0.07',
        perCallEstimate: '约 ¥0.22（含联网搜索费用）',
      },
      mustOpenTool: true,
      steps: [
        '打开 <a href="https://console.anthropic.com" target="_blank" rel="noopener">console.anthropic.com</a> → 注册/登录 Anthropic 账号（<b>国内需先配置代理</b>）',
        '左侧菜单"API Keys" → 点"Create Key" → 复制 Key（sk-ant- 开头，仅显示一次务必保存）',
        '左侧菜单"Settings" → "Billing" → 充值余额（最低 $5，<b>不充值会报 429</b>）',
        '<b>必须开通 web_search 工具</b>：tools=[{type:"web_search_20250305"}]，单独计费 $10/千次（本系统已自动配置）',
        '确认网络可访问 api.anthropic.com（国内需代理）→ 回到本页粘贴 Key → 点"测试"验证',
      ],
      errors: [
        { code: '401 invalid x-api-key', fix: 'Key 错误或已失效' },
        { code: '429 rate_limit', fix: '触发限流或余额不足，降低频率或充值' },
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

// ---------- 扫描预估消耗 ----------
// 各模型单次检测费用（元），基于 pricing 数据的 perCallEstimate 拆分。
// ai_index 收录检测 prompt 短（~100 token 输入/输出，无显式联网搜索），约为 citation 的 1/5。
// citation 引用检测含完整 prompt（~2000 输入 + ~1000 输出 + 1 次联网搜索）。
const aiIndexUnitCost = {
  qwen: 0.001, doubao: 0.001, ernie: 0.001,
  openai: 0.015, gemini: 0.003, claude: 0.03,
}
const citationUnitCost = {
  qwen: 0.004, doubao: 0.005, ernie: 0.005,
  openai: 0.13, gemini: 0.022, claude: 0.22,
}
const MODEL_LABELS = {
  qwen: '千问', doubao: '豆包', ernie: '文心',
  openai: 'ChatGPT', gemini: 'Gemini', claude: 'Claude',
}

const scanEstimate = ref(null)
const estimateLoading = ref(false)

// 计算各扫描类型预估费用
const estimateCosts = computed(() => {
  if (!scanEstimate.value) return null
  const est = scanEstimate.value

  // index：零成本（仅爬虫，不调 AI）
  const indexCount = est.index?.count || 0

  // ai_index：按 model_counts 精确计算（count 已含模型维度）
  const aiCounts = est.ai_index?.model_counts || {}
  let aiIndexCost = 0
  for (const [model, cnt] of Object.entries(aiCounts)) {
    aiIndexCost += cnt * (aiIndexUnitCost[model] || 0.002)
  }
  const aiIndexCount = est.ai_index?.count || 0
  const aiModels = est.ai_index?.models || []

  // citation：count × 模型数 × 单价范围（上界预估，实际只检测已收录子集）
  const citCount = est.citation?.count || 0
  const citModels = est.citation?.models || []
  let citMin = 0, citMax = 0
  if (citCount && citModels.length) {
    const costs = citModels.map(m => citationUnitCost[m] || 0.01)
    citMin = citCount * Math.min(...costs)
    citMax = citCount * Math.max(...costs)
  }

  return {
    index: { count: indexCount },
    ai_index: { count: aiIndexCount, cost: aiIndexCost, models: aiModels },
    citation: { count: citCount, modelCount: citModels.length, costMin: citMin, costMax: citMax },
    total: {
      costMin: aiIndexCost + citMin,
      costMax: aiIndexCost + citMax,
    },
  }
})

function formatCost(v) {
  if (v === 0) return '¥0'
  if (v < 0.01) return `¥${v.toFixed(4)}`
  if (v < 1) return `¥${v.toFixed(3)}`
  return `¥${v.toFixed(2)}`
}

async function loadEstimate() {
  estimateLoading.value = true
  try {
    const res = await api.get('/admin/scan/estimate')
    scanEstimate.value = res.data
  } catch (e) {
    console.warn('加载扫描预估失败', e)
  } finally {
    estimateLoading.value = false
  }
}

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
  // 加载扫描预估消耗（pending 数量 + 预估费用）
  loadEstimate()
})

const saveConfig = async () => {
  try {
    await api.put('/config', config.value)
    ElMessage.success('配置保存成功')
    // 重新加载以获取脱敏后的 API Key 显示
    const res = await api.get('/config')
    config.value = res.data
    // 重新加载预估（API Key 变化可能影响已配置模型数）
    loadEstimate()
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
    // 扫描触发后重新加载预估（pending 数量已变化）
    loadEstimate()
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

/* 价格参考相关样式（傻瓜化增强） */
.g-unit {
  font-size: 11px;
  color: var(--mute, #78716C);
  margin-left: 2px;
}
.price-disclaimer {
  font-size: 11px;
  color: var(--mute, #78716C);
  margin-left: 4px;
  font-style: italic;
}
.estimate-row {
  margin-top: 6px;
  padding: 6px 8px;
  background: rgba(231, 159, 63, 0.08);
  border-radius: var(--radius-md, 4px);
  border-left: 3px solid var(--signal, #E79F3F);
}
.g-highlight {
  color: var(--alert, #E76F51);
  font-size: 13px;
}
.g-sub {
  font-size: 11px;
  color: var(--mute, #78716C);
  margin-left: 4px;
}
.guide-row b {
  color: var(--ink, #1A1A1A);
  font-weight: 600;
}

/* 扫描按钮组：flex 换行排列，适配窄屏 */
.scan-buttons {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 10px;
  margin-bottom: 20px;
}

/* 预估消耗卡片样式 */
.estimate-card {
  border: 1px solid var(--border, #E5E5E5);
  background: linear-gradient(135deg, rgba(231, 159, 63, 0.04), rgba(46, 184, 124, 0.04));
}
.estimate-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.e-sub {
  font-size: 12px;
  color: var(--mute, #78716C);
  font-weight: normal;
}
.estimate-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
}
.estimate-item {
  padding: 12px 14px;
  background: rgba(255, 255, 255, 0.7);
  border-radius: var(--radius-md, 6px);
  border: 1px solid var(--border, #EDEDED);
}
.estimate-total {
  background: rgba(231, 159, 63, 0.1);
  border-color: var(--signal, #E79F3F);
}
.e-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--ink, #1A1A1A);
  margin-bottom: 6px;
}
.e-value {
  font-size: 12px;
  color: var(--body, #444);
  margin-bottom: 4px;
}
.e-models {
  color: var(--mute, #78716C);
  font-size: 11px;
}
.e-cost {
  font-size: 13px;
  color: var(--body, #444);
}
.e-cost.free {
  color: var(--ok, #2EB87C);
  font-size: 12px;
}
.e-cost b {
  color: var(--alert, #E76F51);
}
.e-highlight {
  font-size: 15px;
}
.estimate-note {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px dashed var(--border, #E5E5E5);
  font-size: 11px;
  color: var(--mute, #78716C);
  line-height: 1.6;
}
</style>
