<template>
  <div class="quick-command-row">
    <button
      v-for="cmd in commands"
      :key="cmd.text"
      class="quick-chip"
      @click="$emit('command', cmd.text)"
    >{{ cmd.icon }} {{ cmd.label }}</button>
  </div>
</template>

<script>
export default {
  name: 'QuickCommands',
  emits: ['command'],
  setup () {
    const commands = [
      { icon: '🚗', label: '去光谷广场（避堵）', text: '从武汉理工大学到光谷广场，开车避开拥堵' },
      { icon: '🍲', label: '附近火锅店', text: '帮我找附近评分高的火锅店' },
      { icon: '⛽', label: '先加油再去机场', text: '先去加油站，再去天河机场' },
      { icon: '🚶', label: '步行去最近地铁站', text: '步行去最近地铁站' }
    ]
    return { commands }
  }
}
</script>
