<template>
  <div class="configuration-container">
    <h3>⚙️ 会话配置</h3>
    <p class="config-lead">调整系统提示词、模型来源与工具能力，控制当前导航助手的工作方式。</p>

    <div class="config-field">
      <label for="instructions">系统指令</label>
      <textarea
        id="instructions"
        v-model="instructions"
        placeholder="请输入系统提示词..."
      ></textarea>
    </div>

    <div class="config-field">
      <label for="agentName">智能体名称</label>
      <input
        type="text"
        id="agentName"
        v-model="agentName"
        placeholder="请输入智能体名称"
      />
    </div>

    <div class="config-field">
      <label>Model Provider</label>
      <div class="model-options" id="modelOptions">
        <label
          v-for="model in models"
          :key="model.provider"
          class="model-option"
          :class="{
            selected: modelProvider === model.provider,
            disabled: !model.available,
          }"
          :data-provider="model.provider"
          @click="selectModel(model)"
        >
          <div class="model-option-header">
            <input
              type="radio"
              name="modelProvider"
              :value="model.provider"
              :checked="modelProvider === model.provider"
              :disabled="!model.available"
              @change="selectModel(model)"
            />
            <div class="model-info">
              <div class="model-name-line">
                <span class="model-name">{{ model.name }}</span>
                <span
                  v-if="!model.available"
                  class="model-unavailable-reason"
                >
                  ({{ model.provider.toUpperCase() }}_API_KEY not set)
                </span>
              </div>
              <div class="model-tags">
                <span
                  v-for="tag in model.tags"
                  :key="tag"
                  class="model-tag"
                  :class="tag.toLowerCase()"
                >{{ tag }}</span>
              </div>
            </div>
          </div>
        </label>
      </div>
    </div>

    <div class="config-field">
      <label class="tools-label">
        Equipped Tools
        <span
          v-if="toolsDisabled"
          class="tools-disabled-hint"
        >(Not supported by this model)</span>
      </label>
      <div class="tools-list">
        <div
          v-for="tool in tools"
          :key="tool.name"
          class="tool-item"
          :class="{ disabled: toolsDisabled }"
        >{{ tool.icon }} {{ tool.name }}</div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, onMounted } from 'vue'

export default {
  name: 'ConfigPanel',
  emits: ['voice-disabled'],
  setup (_, { emit }) {
    const instructions = ref('你是车载导航助手小导。优先完成导航相关需求，回复简洁清晰，必要时追问缺失信息。')
    const agentName = ref('小导')
    const modelProvider = ref('dashscope')

    const models = ref([
      { provider: 'dashscope', name: 'DashScope', tags: ['Audio', 'Image'], available: true },
      { provider: 'gemini', name: 'Gemini', tags: ['Text', 'Audio', 'Image', 'Tool'], available: true },
      { provider: 'openai', name: 'OpenAI', tags: ['Text', 'Audio', 'Tool'], available: true }
    ])

    const tools = [
      { name: 'execute_python_code', icon: '🐍' },
      { name: 'execute_shell_command', icon: '💻' },
      { name: 'view_text_file', icon: '📄' }
    ]

    const toolsDisabled = computed(() => {
      return modelProvider.value !== 'gemini' && modelProvider.value !== 'openai'
    })

    function selectModel (model) {
      if (!model.available) return
      modelProvider.value = model.provider
    }

    async function checkAvailableModels () {
      try {
        const resp = await fetch('/api/check-models')
        const availability = await resp.json()
        console.log('Model availability:', availability)

        let hasAvailable = false
        models.value.forEach(m => {
          m.available = !!availability[m.provider]
          if (m.available) hasAvailable = true
        })

        // 若当前选中不可用，切到第一个可用
        const current = models.value.find(m => m.provider === modelProvider.value)
        if (!current || !current.available) {
          const first = models.value.find(m => m.available)
          modelProvider.value = first ? first.provider : ''
        }

        if (!hasAvailable) {
          emit('voice-disabled', true)
        }
      } catch (err) {
        console.error('Failed to check model availability:', err)
      }
    }

    onMounted(() => {
      checkAvailableModels()
    })

    return {
      instructions,
      agentName,
      modelProvider,
      models,
      tools,
      toolsDisabled,
      selectModel,
      checkAvailableModels
    }
  }
}
</script>
