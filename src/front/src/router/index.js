import { createRouter, createWebHashHistory } from 'vue-router'
import ChatbotView from '../views/ChatbotView.vue'

const routes = [
  {
    path: '/',
    name: 'chatbot',
    component: ChatbotView
  }
]

const router = createRouter({
  history: createWebHashHistory(),
  routes
})

export default router
