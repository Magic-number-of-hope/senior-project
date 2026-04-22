<template>
  <div class="config-panel card">
    <h3>⚙️ 会话配置</h3>

    <div class="config-field">
      <label for="instructions">系统指令</label>
      <textarea
        id="instructions"
        v-model="session.instructions"
        placeholder="请输入系统提示词..."
      />
    </div>

    <div class="config-field">
      <label for="agentName">智能体名称</label>
      <input type="text" id="agentName" v-model="session.agentName" placeholder="请输入智能体名称" />
    </div>

    <div class="config-field">
      <label>Model Provider</label>
      <div class="model-options">
        <label
          v-for="model in models"
          :key="model.value"
          class="model-option"
          :class="{
            selected: session.modelProvider === model.value,
            disabled: !session.modelAvailability[model.value]
          }"
          @click="selectModel(model.value)"
        >
          <div class="model-option-header">
            <input
              type="radio"
              name="modelProvider"
              :value="model.value"
              :checked="session.modelProvider === model.value"
              :disabled="!session.modelAvailability[model.value]"
              @change="session.modelProvider = model.value"
            />
            <div class="model-info">
              <div class="model-name-line">
                <span class="model-name">{{ model.name }}</span>
                <span
                  v-if="!session.modelAvailability[model.value]"
                  class="model-unavailable"
                >
                  ({{ model.value.toUpperCase() }}_API_KEY not set)
                </span>
              </div>
              <div class="model-tags">
                <span v-for="tag in model.tags" :key="tag" class="model-tag" :class="tag">{{ tag }}</span>
              </div>
            </div>
          </div>
        </label>
      </div>
    </div>

    <div class="config-field">
      <label class="tools-label">
        Equipped Tools
        <span v-if="!session.supportsTools" class="tools-hint">(Not supported by this model)</span>
      </label>
      <div class="tools-list">
        <div
          v-for="tool in tools"
          :key="tool.name"
          class="tool-item"
          :class="{ disabled: !session.supportsTools }"
        >
          {{ tool.icon }} {{ tool.name }}
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import { useSessionStore } from '../stores/session'

const session = useSessionStore()

const models = [
  { value: 'dashscope', name: 'DashScope', tags: ['audio', 'image'] },
  { value: 'gemini', name: 'Gemini', tags: ['text', 'audio', 'image', 'tool'] },
  { value: 'openai', name: 'OpenAI', tags: ['text', 'audio', 'tool'] },
]

const tools = [
  { icon: '🐍', name: 'execute_python_code' },
  { icon: '💻', name: 'execute_shell_command' },
  { icon: '📄', name: 'view_text_file' },
]

function selectModel(value) {
  if (session.modelAvailability[value]) {
    session.modelProvider = value
  }
}

onMounted(async () => {
  try {
    const resp = await fetch(`${window.location.protocol}//${window.location.host}/api/check-models`)
    const availability = await resp.json()
    session.modelAvailability = availability

    // Auto-select first available
    if (!availability[session.modelProvider]) {
      for (const m of models) {
        if (availability[m.value]) { session.modelProvider = m.value; break }
      }
    }
  } catch (err) {
    console.error('Failed to check models:', err)
  }
})
</script>

<style scoped>
.config-panel {
  padding: 1.5rem;
}
.config-panel h3 {
  font-size: 1.125rem;
  font-weight: 600;
  margin-bottom: 1rem;
  color: var(--text-primary);
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.config-field {
  margin-bottom: 1.25rem;
}
.config-field:last-child { margin-bottom: 0; }
.config-field label {
  display: block;
  font-weight: 500;
  margin-bottom: 0.5rem;
  color: var(--text-secondary);
  font-size: 0.875rem;
}

.model-options {
  display: flex;
  gap: 0.75rem;
}
.model-option {
  flex: 1;
  padding: 0.75rem;
  border: 2px solid var(--border);
  border-radius: var(--radius);
  cursor: pointer;
  transition: all 0.15s ease;
  background: #fff;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.model-option:hover:not(.disabled) {
  border-color: var(--blue);
  background: var(--blue-bg);
}
.model-option.selected {
  border-color: var(--blue);
  background: var(--blue-light);
}
.model-option.disabled {
  opacity: 0.5;
  cursor: not-allowed;
  background: hsl(0, 0%, 98%);
}
.model-option-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.model-option input[type="radio"] {
  margin: 0;
  cursor: pointer;
  flex-shrink: 0;
}
.model-info {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  flex: 1;
}
.model-name-line {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.model-name { font-weight: 600; color: var(--text-primary); }
.model-unavailable {
  font-size: 0.625rem;
  color: var(--text-muted);
  font-style: italic;
}
.model-tags { display: flex; gap: 0.375rem; flex-wrap: wrap; }
.model-tag {
  display: inline-flex;
  align-items: center;
  padding: 0.125rem 0.5rem;
  font-size: 0.75rem;
  font-weight: 500;
  border-radius: 0.25rem;
  background: var(--border);
  color: var(--text-secondary);
}
.model-tag.text { background: hsl(200, 95%, 90%); color: hsl(200, 95%, 30%); }
.model-tag.audio { background: hsl(280, 85%, 90%); color: hsl(280, 85%, 30%); }
.model-tag.image { background: hsl(25, 95%, 90%); color: hsl(25, 95%, 30%); }
.model-tag.tool { background: hsl(142, 71%, 90%); color: hsl(142, 71%, 30%); }

.tools-label {
  display: block;
  font-weight: 500;
  margin-bottom: 0.5rem;
  color: var(--text-secondary);
  font-size: 0.875rem;
}
.tools-hint {
  font-size: 0.75rem;
  color: var(--text-muted);
  font-style: italic;
  margin-left: 0.5rem;
}
.tools-list { display: flex; gap: 0.5rem; }
.tool-item {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0.5rem 0.75rem;
  background: #fff;
  border: 2px solid var(--border);
  border-radius: var(--radius-sm);
  font-size: 0.875rem;
  color: var(--text-secondary);
  font-weight: 500;
  transition: all 0.15s ease;
}
.tool-item.disabled {
  background: hsl(0, 0%, 96%);
  color: var(--text-muted);
  opacity: 0.6;
}

@media (max-width: 760px) {
  .model-options { flex-direction: column; }
  .tools-list { flex-direction: column; }
}
</style>
