import { createApp } from 'vue'
import { defineCustomElements } from '@astrouxds/astro-web-components/loader'
import { Notify, store, vuetify } from '@openc3/vue-common/plugins'

import '@openc3/vue-common/styles'
import '@/assets/stylesheets/layout/layout.scss'

import App from './App.vue'
import router from './router'

defineCustomElements()

Object.getPrototypeOf(System).firstGlobalProp = true

const app = createApp(App)

app.use(store)
app.use(vuetify)
app.use(router)
app.use(Notify, { store })

const options = OpenC3Auth.getInitOptions()
OpenC3Auth.init(options)
  .then(() => {
    // Set the scope variable that will be used for the life of this page load
    // It is always DEFAULT in COSMOS Core
    window.openc3Scope = 'DEFAULT'

    app.mount('#openc3-main')
  })
  .catch((error) => {
    // If authentication cannot start, the app never mounts. Say why on the page
    // rather than leaving an empty background for the operator to guess at.
    console.error('Authentication failed to initialize', error)
    const el = document.getElementById('openc3-main')
    if (el) {
      el.innerHTML =
        '<div style="font-family: sans-serif; color: #fff; padding: 40px; max-width: 720px">' +
        '<h2>Unable to sign in</h2>' +
        '<p>' +
        (error && error.message ? error.message : 'Authentication failed to initialize.') +
        '</p>' +
        '<p>Check that the identity provider is running and reachable, then reload.</p>' +
        '</div>'
    }
  })
