import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import './styles/global.css'  // Ink & Signal 全局样式（必须在 element-plus 之后，覆盖主题变量）
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import App from './App.vue'
import router from './router'
import store from './store'

const app = createApp(App)
app.use(ElementPlus)
// 全局注册 Element Plus 图标组件，使 <component :is="图标名字符串" /> 可用
// （StatCard.vue 等组件通过字符串 prop 动态渲染图标）
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}
app.use(router)
app.use(store)
app.mount('#app')
