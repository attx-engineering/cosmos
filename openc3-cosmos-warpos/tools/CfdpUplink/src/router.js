import { createRouter, createWebHistory } from 'vue-router'
import { prependBasePath } from '@openc3/js-common/utils'

const routes = [
  {
    path: '/:path*',
    name: 'CFDP Uplink',
    component: () => import('./tools/CfdpUplink/CfdpUplink.vue'),
  },
]
routes.forEach(prependBasePath)

export default createRouter({
  history: createWebHistory(),
  routes,
})
