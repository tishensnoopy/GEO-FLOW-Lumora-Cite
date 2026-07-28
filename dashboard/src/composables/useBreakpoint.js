// dashboard/src/composables/useBreakpoint.js
import { ref, onMounted, onUnmounted } from 'vue'

/**
 * 响应式断点检测。
 * - lg: >= 1280px（桌面，侧栏展开）
 * - md: 768-1279px（平板，侧栏折叠为图标）
 * - sm: < 768px（移动，侧栏隐藏，底部 Tab）
 */
export function useBreakpoint() {
  const width = ref(typeof window !== 'undefined' ? window.innerWidth : 1280)
  const breakpoint = ref('lg')
  const isMobile = ref(false)
  const isTablet = ref(false)
  const isDesktop = ref(true)

  function update() {
    width.value = window.innerWidth
    if (width.value >= 1280) {
      breakpoint.value = 'lg'
      isDesktop.value = true
      isTablet.value = false
      isMobile.value = false
    } else if (width.value >= 768) {
      breakpoint.value = 'md'
      isDesktop.value = false
      isTablet.value = true
      isMobile.value = false
    } else {
      breakpoint.value = 'sm'
      isDesktop.value = false
      isTablet.value = false
      isMobile.value = true
    }
  }

  onMounted(() => {
    update()
    window.addEventListener('resize', update, { passive: true })
  })

  onUnmounted(() => {
    window.removeEventListener('resize', update)
  })

  return { width, breakpoint, isMobile, isTablet, isDesktop }
}
