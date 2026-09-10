<template>
  <div>
    <top-bar :menus="[]" :title="title" />
    <v-container class="pa-4" style="max-width: 700px">
      <v-tabs v-model="activeTab" class="mb-4">
        <v-tab value="upload">Upload</v-tab>
        <v-tab value="request">Request File</v-tab>
        <v-tab value="downloads">Downloads</v-tab>
      </v-tabs>
      <v-window v-model="activeTab">
        <v-window-item value="upload">
          <v-card>
            <v-card-title>Queue a CFDP File Uplink</v-card-title>
            <v-card-text>
              <v-alert v-if="error" type="error" density="compact" class="mb-4" closable @click:close="error = null">
                {{ error }}
              </v-alert>
              <v-alert v-if="lastQueued" type="success" density="compact" class="mb-4" closable @click:close="lastQueued = null">
                Queued: {{ lastQueued }}
              </v-alert>
              <v-form ref="form" v-model="formValid">
                <v-file-input
                  :key="fileInputKey"
                  v-model="selectedFile"
                  label="File"
                  hint="File from your own computer to transfer"
                  persistent-hint
                  show-size
                  prepend-icon="mdi-paperclip"
                  :rules="[(v) => !!fileFrom(v) || 'A file is required']"
                  class="mb-4"
                  @update:model-value="onFileSelected"
                />
                <v-text-field
                  v-model="remoteName"
                  label="Remote Name"
                  hint="File name the destination will store the transfer under"
                  persistent-hint
                  :rules="[(v) => !!v || 'Remote name is required']"
                  class="mb-4"
                />
                <v-text-field
                  v-model="destinationEntityId"
                  label="Destination Entity ID"
                  hint="CFDP entity ID of the transfer destination"
                  persistent-hint
                  type="number"
                  :rules="[(v) => (v !== '' && v !== null && v !== undefined) || 'Destination entity ID is required']"
                  class="mb-4"
                />
                <v-expansion-panels class="mb-4">
                  <v-expansion-panel title="Advanced">
                    <v-expansion-panel-text>
                      <v-text-field
                        v-model="sequenceNumber"
                        label="Sequence Number (optional)"
                        hint="Defaults to the next auto-allocated sequence number"
                        persistent-hint
                        type="number"
                        class="mb-4 mt-2"
                      />
                      <v-text-field
                        v-model="pduDelaySeconds"
                        label="PDU Delay Seconds (optional)"
                        hint="Delay between sent PDUs, minimum 0.1s"
                        persistent-hint
                        type="number"
                        step="0.1"
                      />
                    </v-expansion-panel-text>
                  </v-expansion-panel>
                </v-expansion-panels>
                <v-btn block color="primary" :disabled="submitting" :loading="submitting" @click="submit">
                  Send File
                </v-btn>
              </v-form>
            </v-card-text>
          </v-card>
        </v-window-item>

        <v-window-item value="request">
          <v-card>
            <v-card-title>Request a File (FILE_GET)</v-card-title>
            <v-card-text>
              <v-alert v-if="getError" type="error" density="compact" class="mb-4" closable @click:close="getError = null">
                {{ getError }}
              </v-alert>
              <v-alert v-if="getSent" type="success" density="compact" class="mb-4" closable @click:close="getSent = null">
                {{ getSent }}
              </v-alert>
              <v-form ref="getForm" v-model="getFormValid">
                <v-text-field
                  v-model="getRemoteFileName"
                  label="File Name on WarpOS"
                  hint="The file to fetch from the remote system"
                  persistent-hint
                  :rules="[(v) => !!v || 'File name is required']"
                  class="mb-4"
                />
                <v-text-field
                  v-model="getSaveAsName"
                  label="Save As"
                  hint="Name to give the downloaded file once received -- shows up under the Downloads tab"
                  persistent-hint
                  :rules="[(v) => !!v || 'Save-as name is required']"
                  class="mb-4"
                />
                <v-text-field
                  v-model="getLocalEntityId"
                  label="Your Entity ID"
                  hint="This ground station's CFDP entity ID (warplink's configured LOCAL_ENTITY_ID)"
                  persistent-hint
                  type="number"
                  :rules="[(v) => (v !== '' && v !== null && v !== undefined) || 'Required']"
                  class="mb-4"
                />
                <v-text-field
                  v-model="getRemoteEntityId"
                  label="WarpOS Entity ID"
                  hint="The flight system's current CFDP entity ID -- must match exactly or the command is rejected"
                  persistent-hint
                  type="number"
                  :rules="[(v) => (v !== '' && v !== null && v !== undefined) || 'Required']"
                  class="mb-4"
                />
                <v-btn block color="primary" :disabled="requestingFile" :loading="requestingFile" @click="requestFile">
                  Request File
                </v-btn>
              </v-form>
            </v-card-text>
          </v-card>
        </v-window-item>

        <v-window-item value="downloads">
          <v-card>
            <v-card-title class="d-flex align-center justify-space-between">
              Downloaded Files
              <v-btn
                icon="mdi-refresh"
                variant="text"
                density="comfortable"
                :loading="refreshingDownloads"
                @click="refreshDownloads"
              />
            </v-card-title>
            <v-card-text>
              <v-alert v-if="downloadsError" type="error" density="compact" class="mb-4" closable @click:close="downloadsError = null">
                {{ downloadsError }}
              </v-alert>
              <v-list v-if="downloadedFiles.length">
                <v-list-item
                  v-for="file in downloadedFiles"
                  :key="file.name"
                  :title="file.name"
                  :subtitle="`${formatSize(file.size)} — ${formatDate(file.modified)}`"
                >
                  <template #append>
                    <v-btn icon="mdi-download" variant="text" @click="downloadFile(file.name)" />
                  </template>
                </v-list-item>
              </v-list>
              <div v-else class="text-medium-emphasis">No files yet.</div>
            </v-card-text>
          </v-card>
        </v-window-item>
      </v-window>
    </v-container>
  </div>
</template>

<script>
import { Api, axios, OpenC3Api } from '@openc3/js-common/services'
import { TopBar } from '@openc3/vue-common/components'

// Must match the prefixes CFDP_SERVICE polls/reads in cfdp_service.py.
const QUEUE_PREFIX = 'cfdp/outgoing/queue/'
const FILES_PREFIX = 'cfdp/outgoing/files/'
const UPLOAD_BUCKET = 'OPENC3_TOOLS_BUCKET'

// Same host path CFDP_SERVICE's OUTPUT_DIR writes received files into (see
// OPENC3_CFDP_VOLUME in .env) -- exposed read-only via OpenC3's built-in
// volume storage routes, no custom backend needed. Must match
// CfdpReceiver.COMPLETE_SUBDIR in cfdp_core.py -- that's the only
// subdirectory files get atomically moved into once a transfer is fully
// received and checksum-verified.
const DOWNLOAD_VOLUME = 'OPENC3_CFDP_VOLUME'
const DOWNLOADS_PATH = 'incoming/complete/'
const DOWNLOADS_POLL_MS = 5000

const COMMAND_TARGET = 'WARPI'
const FILE_GET_PACKET = 'STORAGE_MANAGER_FILE_GET'

const sanitize = (name) => name.replace(/[^A-Za-z0-9._-]/g, '_')

// Uploads to the given bucket key via OpenC3's presigned-PUT flow (same
// route the Bucket Explorer tool uses) and returns once the PUT completes.
async function uploadToBucket(key, data) {
  const { data: presigned } = await Api.get(`/openc3-api/storage/upload/${encodeURIComponent(key)}`, {
    params: { bucket: UPLOAD_BUCKET },
  })
  await axios({
    method: presigned.method,
    url: presigned.url,
    headers: presigned.headers,
    data,
  })
}

function errorMessage(e) {
  return (e.response && e.response.data && e.response.data.message) || e.message || String(e)
}

export default {
  components: {
    TopBar,
  },
  data() {
    return {
      title: 'CFDP Uplink',
      activeTab: 'upload',
      api: null,

      // Upload tab
      formValid: false,
      submitting: false,
      error: null,
      lastQueued: null,
      selectedFile: null,
      fileInputKey: 0,
      remoteName: '',
      destinationEntityId: '',
      sequenceNumber: '',
      pduDelaySeconds: '',

      // Request File (FILE_GET) tab
      getFormValid: false,
      requestingFile: false,
      getError: null,
      getSent: null,
      getRemoteFileName: '',
      getSaveAsName: '',
      getLocalEntityId: '0',
      getRemoteEntityId: '0',

      // Downloads tab
      downloadedFiles: [],
      downloadsError: null,
      refreshingDownloads: false,
    }
  },
  created() {
    this.api = new OpenC3Api()
    this.refreshDownloads()
    this._downloadsPoll = setInterval(() => this.refreshDownloads(), DOWNLOADS_POLL_MS)
  },
  beforeUnmount() {
    clearInterval(this._downloadsPoll)
  },
  methods: {
    // v-file-input's v-model has returned either a bare File or a File[]
    // depending on Vuetify version -- normalize both shapes here.
    fileFrom(value) {
      return Array.isArray(value) ? value[0] : value
    },
    onFileSelected(value) {
      const file = this.fileFrom(value)
      if (file && !this.remoteName) {
        this.remoteName = file.name
      }
    },
    async submit() {
      const { valid } = await this.$refs.form.validate()
      if (!valid) {
        return
      }
      const file = this.fileFrom(this.selectedFile)
      this.submitting = true
      this.error = null
      try {
        // Upload the file bytes first -- only queue the request once the
        // source it references is guaranteed to already exist, so
        // CFDP_SERVICE never races ahead of the upload.
        const fileKey = `${FILES_PREFIX}${Date.now()}_${sanitize(file.name)}`
        await uploadToBucket(fileKey, file)

        const request = {
          source_key: fileKey,
          source_filename: file.name,
          remote_name: this.remoteName,
          destination_entity_id: Number(this.destinationEntityId),
        }
        if (this.sequenceNumber !== '' && this.sequenceNumber !== null) {
          request.sequence_number = Number(this.sequenceNumber)
        }
        if (this.pduDelaySeconds !== '' && this.pduDelaySeconds !== null) {
          request.pdu_delay_seconds = Number(this.pduDelaySeconds)
        }

        const requestKey = `${QUEUE_PREFIX}${Date.now()}_${sanitize(this.remoteName)}.json`
        await uploadToBucket(requestKey, JSON.stringify(request))

        this.lastQueued = requestKey
        this.$notify.normal({
          title: 'CFDP Uplink',
          body: `Queued transfer request ${requestKey}`,
        })
        this.$refs.form.reset()
        // VForm.reset() clears selectedFile's v-model but Vuetify doesn't
        // reliably clear the underlying native <input type="file">, leaving
        // the previous file's name displayed -- force a remount instead.
        this.selectedFile = null
        this.fileInputKey += 1
      } catch (e) {
        this.error = errorMessage(e)
        this.$notify.serious({
          title: 'CFDP Uplink failed',
          body: this.error,
        })
      } finally {
        this.submitting = false
      }
    },
    async requestFile() {
      const { valid } = await this.$refs.getForm.validate()
      if (!valid) {
        return
      }
      this.requestingFile = true
      this.getError = null
      try {
        await this.api.cmd(COMMAND_TARGET, FILE_GET_PACKET, {
          // Command field names are from the requester's point of view and
          // read backwards from the flight side's own local/remote naming --
          // see StorageManager.cpp's FILE_GET handler. REMOTE_NAME is the
          // file to fetch off WarpOS; LOCAL_NAME is what to call it once
          // it's back here (and is the name it'll show up under in the
          // Downloads tab).
          REMOTE_NAME: this.getRemoteFileName,
          LOCAL_NAME: this.getSaveAsName,
          LOCAL_ID: Number(this.getLocalEntityId),
          REMOTE_ID: Number(this.getRemoteEntityId),
        })
        this.getSent = `Requested "${this.getRemoteFileName}" from WarpOS as "${this.getSaveAsName}"`
        this.$notify.normal({ title: 'CFDP Uplink', body: this.getSent })
      } catch (e) {
        this.getError = errorMessage(e)
        this.$notify.serious({ title: 'File request failed', body: this.getError })
      } finally {
        this.requestingFile = false
      }
    },
    async refreshDownloads() {
      this.refreshingDownloads = true
      try {
        // root goes in the URL path here (not a query param) -- matches
        // Bucket Explorer's own /storage/files/:root/(*path) usage.
        // incoming/complete/ only ever contains transfers CfdpReceiver has
        // verified are fully received and checksum-correct -- files under
        // incoming/in_progress/ or incoming/failed/ are deliberately not
        // listed here (see cfdp_core.py's CfdpReceiver docstring).
        const { data } = await Api.get(`/openc3-api/storage/files/${DOWNLOAD_VOLUME}/${DOWNLOADS_PATH}`)
        const [, files] = data
        this.downloadedFiles = (files || []).sort((a, b) => new Date(b.modified) - new Date(a.modified))
        this.downloadsError = null
      } catch (e) {
        this.downloadsError = errorMessage(e)
      } finally {
        this.refreshingDownloads = false
      }
    },
    async downloadFile(name) {
      try {
        const { data } = await Api.get(
          `/openc3-api/storage/download_file/${encodeURIComponent(DOWNLOADS_PATH + name)}`,
          { params: { volume: DOWNLOAD_VOLUME } },
        )
        const bytes = atob(data.contents)
        const buffer = new Uint8Array(bytes.length)
        for (let i = 0; i < bytes.length; i++) {
          buffer[i] = bytes.charCodeAt(i)
        }
        const blob = new Blob([buffer])
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = data.filename
        a.click()
        URL.revokeObjectURL(url)
      } catch (e) {
        this.downloadsError = errorMessage(e)
        this.$notify.serious({ title: 'Download failed', body: this.downloadsError })
      }
    },
    formatSize(bytes) {
      if (bytes < 1024) return `${bytes} B`
      if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
      return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
    },
    formatDate(value) {
      return value ? new Date(value).toLocaleString() : ''
    },
  },
}
</script>
