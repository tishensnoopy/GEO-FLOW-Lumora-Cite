<template>
  <div class="signal-strip" role="marquee" aria-label="实时监测事件">
    <div class="signal-strip-label mono">SIGNAL · LIVE</div>
    <div class="signal-strip-viewport">
      <div class="signal-strip-track">
        <div class="signal-strip-item" v-for="(evt, i) in events" :key="i">
          <span class="evt-time mono">{{ evt.time }}</span>
          <span class="evt-engine" :class="evt.status">{{ evt.engine }}</span>
          <span class="evt-action">{{ evt.action }}</span>
          <span class="evt-title">{{ evt.title }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  events: { type: Array, default: () => [] },
})
</script>

<style scoped>
.signal-strip {
  display: flex;
  align-items: center;
  gap: var(--space-md);
  height: 44px;
  background: var(--ink);
  color: var(--paper);
  border-radius: var(--radius-md);
  overflow: hidden;
  padding: 0 var(--space-md);
  flex: 1;
}
.signal-strip-label {
  background: var(--ink);
  padding-right: var(--space-md);
  color: var(--signal);
  font-size: var(--fs-mono);
  letter-spacing: 0.2em;
  white-space: nowrap;
  font-weight: 500;
  flex-shrink: 0;
}
.signal-strip-label::before {
  content: '●';
  margin-right: 6px;
  animation: blink 1.5s ease-in-out infinite;
}
@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}
.signal-strip-viewport {
  flex: 1;
  overflow: hidden;
  -webkit-mask-image: linear-gradient(to right, transparent 0%, black 24px, black calc(100% - 24px), transparent 100%);
  mask-image: linear-gradient(to right, transparent 0%, black 24px, black calc(100% - 24px), transparent 100%);
}
.signal-strip-track {
  display: flex;
  gap: var(--space-xl);
  white-space: nowrap;
  animation: ticker 30s linear infinite;
}
@keyframes ticker {
  0%   { transform: translateX(0); }
  100% { transform: translateX(-50%); }
}
.signal-strip-item {
  display: inline-flex;
  align-items: center;
  gap: var(--space-xs);
  font-size: var(--fs-mono);
}
.evt-time { color: var(--mute); }
.evt-engine { padding: 1px 6px; border-radius: var(--radius-sm); font-weight: 500; }
.evt-engine.indexed { background: var(--signal-soft); color: var(--signal); }
.evt-engine.cited   { background: var(--depth-soft);  color: var(--depth); }
.evt-engine.pending { background: rgba(201, 151, 0, 0.15); color: #C99700; }
.evt-engine.failed  { background: var(--alert-soft);  color: var(--alert); }
.evt-action { color: var(--paper); opacity: 0.7; }
.evt-title { color: var(--paper); }
.signal-strip:hover .signal-strip-track { animation-play-state: paused; }

/* 移动端：信号条字体缩小 */
@media (max-width: 768px) {
  .signal-strip-track { animation-duration: 40s; }
}
</style>
