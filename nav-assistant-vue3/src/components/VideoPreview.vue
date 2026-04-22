<template>
  <div class="video-container" v-show="isActive">
    <video
      id="videoPreview"
      autoplay
      muted
      playsinline
      class="video-preview"
    ></video>
  </div>
</template>

<script setup>
defineProps({ isActive: Boolean })
</script>

<style scoped>
.video-container {
  display: flex;
  flex-direction: column;
  align-items: center;
}
.video-preview {
  width: 100%;
  max-width: 640px;
  border-radius: var(--radius);
  border: 1px solid var(--border);
  background: #000;
}
</style>
