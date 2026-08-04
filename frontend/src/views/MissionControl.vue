<script setup>
import { ref, computed } from 'vue';
import { useMissionStore, STEP_TYPES, getStepTypeDef } from '@/stores/missionStore';
import { useVesselStore } from '@/stores/vesselStore';
import {
  Flag, Play, Square, RotateCcw, Plus, Trash2, ChevronUp, ChevronDown,
  ListOrdered, Cpu, Zap, Navigation, Camera, Anchor, CheckCircle2, Clock,
  AlertTriangle, FolderOpen, GripVertical, CircleStop, PauseCircle, Save
} from 'lucide-vue-next';

const mission = useMissionStore();
const vessel = useVesselStore();

const showStepPicker = ref(false);
const editingStepIdx = ref(null);
const showSavePresetModal = ref(false);
const presetNameInput = ref('');

async function handleSavePreset() {
  if (!presetNameInput.value.trim()) return;
  const ok = await mission.saveCurrentAsPreset(presetNameInput.value.trim());
  if (ok) {
    presetNameInput.value = '';
    showSavePresetModal.value = false;
  }
}


// Map icon string to Lucide component
const iconMap = {
  '⚡': Zap, '🎯': Cpu, '🧭': Navigation, '📷': Camera, '⚓': Anchor, '🏁': Flag
};

function getStatusColor(status) {
  switch (status) {
    case 'RUNNING': return 'text-success';
    case 'PAUSED': return 'text-warning';
    case 'FINISHED': return 'text-emerald-400';
    case 'ABORTED': return 'text-danger';
    default: return 'text-(--text-secondary)';
  }
}

function getStepStatus(idx) {
  const mIdx = mission.currentStepIdx;
  const status = mission.missionStatus;
  if (status !== 'IDLE' && idx < mIdx) return 'done';
  if (status === 'RUNNING' && idx === mIdx) return 'active';
  return 'pending';
}
</script>

<template>
  <div class="p-4 h-full flex flex-col gap-4 overflow-hidden">

    <!-- ─── Header ───────────────────────────────────────────────────────── -->
    <div class="flex justify-between items-center flex-shrink-0">
      <div>
        <h1 class="text-xl font-black text-(--text-primary) tracking-tight flex items-center gap-2">
          <Flag class="text-primary w-5 h-5" />
          MISSION CONTROL
        </h1>
        <p class="text-[10px] text-(--text-secondary) uppercase font-bold tracking-widest mt-0.5">
          Autonomous Sequence Pipeline Builder
        </p>
      </div>

      <!-- Mission Status Badge -->
      <div class="flex items-center gap-3">
        <div class="px-4 py-2 rounded-xl border glass-card flex items-center gap-2 min-w-[140px] justify-center"
          :class="{
            'border-success/40 bg-success/10': mission.missionStatus === 'RUNNING',
            'border-warning/40 bg-warning/10': mission.missionStatus === 'PAUSED',
            'border-primary/40 bg-primary/10': mission.missionStatus === 'ABORTED',
            'border-(--border-subtle)': mission.missionStatus === 'IDLE' || mission.missionStatus === 'FINISHED'
          }">
          <span class="w-2 h-2 rounded-full"
            :class="{
              'bg-success animate-pulse': mission.missionStatus === 'RUNNING',
              'bg-warning': mission.missionStatus === 'PAUSED',
              'bg-primary': mission.missionStatus === 'ABORTED',
              'bg-(--text-muted)': mission.missionStatus === 'IDLE',
              'bg-emerald-400': mission.missionStatus === 'FINISHED',
            }"></span>
          <span class="text-xs font-black uppercase" :class="getStatusColor(mission.missionStatus)">
            {{ mission.missionStatus }}
          </span>
        </div>
        <div class="text-right">
          <span class="text-[10px] text-(--text-secondary) uppercase font-black block">ELAPSED</span>
          <span class="text-xl font-mono font-black text-(--text-primary)">{{ mission.formattedTime }}</span>
        </div>
      </div>
    </div>

    <!-- ─── Control Bar ──────────────────────────────────────────────────── -->
    <div class="flex gap-3 flex-shrink-0">
      <!-- Start / Pause / Resume -->
      <button v-if="mission.missionStatus === 'IDLE' || mission.missionStatus === 'ABORTED' || mission.missionStatus === 'FINISHED'"
        @click="mission.startMission()"
        :disabled="!mission.steps.length"
        class="flex items-center gap-2 bg-success text-slate-900 font-black px-5 py-2.5 rounded-xl hover:bg-emerald-400 transition-all shadow-lg shadow-success/20 disabled:opacity-40 disabled:cursor-not-allowed text-xs uppercase">
        <Play class="w-4 h-4 fill-current" /> START MISSION
      </button>

      <button v-else-if="mission.missionStatus === 'RUNNING'"
        @click="mission.pauseMission()"
        class="flex items-center gap-2 bg-warning text-slate-900 font-black px-5 py-2.5 rounded-xl hover:bg-yellow-400 transition-all text-xs uppercase">
        <PauseCircle class="w-4 h-4" /> PAUSE
      </button>

      <button v-else-if="mission.missionStatus === 'PAUSED'"
        @click="mission.resumeMission()"
        class="flex items-center gap-2 bg-success text-slate-900 font-black px-5 py-2.5 rounded-xl hover:bg-emerald-400 transition-all text-xs uppercase">
        <Play class="w-4 h-4 fill-current" /> RESUME
      </button>

      <!-- Abort (only when running or paused) -->
      <button v-if="mission.missionStatus === 'RUNNING' || mission.missionStatus === 'PAUSED'"
        @click="mission.abortMission()"
        class="flex items-center gap-2 bg-primary text-slate-900 font-black px-5 py-2.5 rounded-xl hover:bg-red-600 transition-all shadow-lg shadow-primary/20 text-xs uppercase">
        <CircleStop class="w-4 h-4" /> ABORT
      </button>

      <!-- Reset -->
      <button @click="mission.resetMission()"
        class="flex items-center gap-2 bg-(--bg-secondary) text-(--text-primary) font-bold px-5 py-2.5 rounded-xl hover:bg-card transition-all border border-(--border-subtle) text-xs uppercase">
        <RotateCcw class="w-4 h-4" /> RESET
      </button>
    </div>

    <!-- ─── Main Content Grid ─────────────────────────────────────────────── -->
    <div class="flex-1 grid grid-cols-12 gap-4 overflow-hidden min-h-0">

      <!-- ══ LEFT: Mission Pipeline Builder ══ -->
      <div class="col-span-12 lg:col-span-7 flex flex-col gap-3 overflow-hidden min-h-0">

        <!-- Add Step Button -->
        <div class="flex gap-2 flex-shrink-0">
          <div class="relative flex-1">
            <button @click="showStepPicker = !showStepPicker"
              class="w-full flex items-center justify-center gap-2 border-2 border-dashed border-(--border-subtle) hover:border-primary/50 hover:text-primary text-(--text-muted) rounded-xl py-2.5 text-xs font-black uppercase transition-all">
              <Plus class="w-4 h-4" /> Add Mission Step
            </button>

            <!-- Step Type Picker Dropdown -->
            <div v-if="showStepPicker"
              class="absolute top-full left-0 right-0 mt-2 glass-card border border-(--border-primary) rounded-xl p-2 z-30 shadow-2xl space-y-1">
              <button v-for="def in STEP_TYPES" :key="def.type"
                @click="() => { mission.addStep(def.type); showStepPicker = false; }"
                class="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg border transition-all hover:scale-[1.01] text-left"
                :class="def.bg">
                <span class="text-lg w-6 flex-shrink-0">{{ def.icon }}</span>
                <span class="text-xs font-black uppercase tracking-wider" :class="def.color">{{ def.label }}</span>
              </button>
            </div>
          </div>

          <!-- Presets -->
          <div class="relative group">
            <button class="flex items-center gap-2 bg-(--bg-secondary) px-4 py-2.5 rounded-xl border border-(--border-subtle) text-xs font-bold text-(--text-secondary) hover:text-(--text-primary) uppercase transition-all">
              <FolderOpen class="w-4 h-4" /> Presets
            </button>
            <div class="absolute top-full right-0 mt-2 w-72 glass-card border border-(--border-primary) rounded-xl p-2 z-30 shadow-2xl space-y-1 hidden group-hover:block max-h-60 overflow-y-auto">
              <div v-for="p in mission.presets" :key="p.id || p.name"
                class="flex items-center justify-between px-3 py-2 rounded-lg bg-card/50 hover:bg-primary/10 text-(--text-secondary) text-xs font-bold transition-all group/item">
                <button @click="mission.loadPreset(p)" class="text-left flex-1 min-w-0">
                  <span class="truncate block group-hover/item:text-primary">{{ p.name }}</span>
                  <span class="block text-[10px] opacity-60 font-normal">
                    {{ p.steps.length }} steps <span v-if="p.isDb" class="text-emerald-400 font-bold ml-1">• DB</span>
                  </span>
                </button>
                <button v-if="p.isDb" @click.stop="mission.deletePreset(p.dbId)" title="Hapus preset dari database"
                  class="p-1 rounded text-(--text-muted) hover:text-danger hover:bg-danger/10 transition-colors ml-2">
                  <Trash2 class="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          </div>

          <!-- Save to DB Button -->
          <button @click="showSavePresetModal = true" :disabled="!mission.steps.length"
            title="Simpan alur misi saat ini ke Database"
            class="flex items-center gap-2 bg-(--bg-secondary) px-4 py-2.5 rounded-xl border border-(--border-subtle) text-xs font-bold text-(--text-secondary) hover:text-success uppercase transition-all disabled:opacity-30">
            <Save class="w-4 h-4 text-success" /> Save DB
          </button>
        </div>

        <!-- Pipeline Steps List -->
        <div class="flex-1 overflow-y-auto space-y-2 pr-1 min-h-0"
          @click.self="showStepPicker = false">

          <div v-if="!mission.steps.length"
            class="flex flex-col items-center justify-center h-40 text-(--text-muted) text-xs gap-2 border-2 border-dashed border-(--border-subtle) rounded-xl">
            <Flag class="w-6 h-6 opacity-40" />
            <span class="font-bold uppercase">Belum ada mission steps</span>
            <span class="text-[10px] opacity-60">Tekan "+ Add Mission Step" untuk memulai</span>
          </div>

          <template v-else>
            <div v-for="(step, idx) in mission.steps" :key="step.id"
              class="relative rounded-xl border transition-all"
              :class="{
                'border-success/60 bg-success/5 shadow-lg shadow-success/10': getStepStatus(idx) === 'done',
                'border-primary/60 bg-primary/5 shadow-lg shadow-primary/10 ring-1 ring-primary/30': getStepStatus(idx) === 'active',
                'border-(--border-subtle) bg-card/30': getStepStatus(idx) === 'pending'
              }">
              <div class="flex items-start gap-3 p-3">
                <!-- Step number & status icon -->
                <div class="flex flex-col items-center gap-1 flex-shrink-0 w-8 mt-1">
                  <div class="w-7 h-7 rounded-full flex items-center justify-center text-[10px] font-black border"
                    :class="{
                      'bg-success text-slate-900 border-success': getStepStatus(idx) === 'done',
                      'bg-primary text-slate-900 border-primary animate-pulse': getStepStatus(idx) === 'active',
                      'bg-card text-(--text-muted) border-(--border-subtle)': getStepStatus(idx) === 'pending'
                    }">
                    <CheckCircle2 v-if="getStepStatus(idx) === 'done'" class="w-4 h-4" />
                    <Clock v-else-if="getStepStatus(idx) === 'active'" class="w-4 h-4 animate-spin" />
                    <span v-else>{{ idx + 1 }}</span>
                  </div>
                  <!-- Connector line -->
                  <div v-if="idx < mission.steps.length - 1" class="w-0.5 h-4 bg-(--border-subtle) rounded"></div>
                </div>

                <!-- Step content -->
                <div class="flex-1 min-w-0">
                  <div class="flex items-center gap-2 mb-2">
                    <span class="text-sm">{{ getStepTypeDef(step.type)?.icon }}</span>
                    <input v-model="step.name"
                      class="bg-transparent text-xs font-black text-(--text-primary) uppercase tracking-wide flex-1 outline-none border-b border-transparent hover:border-(--border-subtle) focus:border-primary transition-colors"
                      :disabled="mission.missionStatus === 'RUNNING'" />
                    <span class="text-[9px] font-bold uppercase px-1.5 py-0.5 rounded"
                      :class="getStepTypeDef(step.type)?.bg + ' ' + getStepTypeDef(step.type)?.color">
                      {{ step.type.replace('_', ' ') }}
                    </span>
                  </div>

                  <!-- Step Fields -->
                  <div class="flex flex-wrap gap-3">
                    <template v-for="field in getStepTypeDef(step.type)?.fields" :key="field.key">
                      <div class="flex items-center gap-2 bg-(--bg-secondary) px-2 py-1 rounded-lg border border-(--border-subtle)">
                        <span class="text-[10px] text-(--text-muted) font-bold uppercase">{{ field.label }}:</span>
                        <input v-model.number="step[field.key]" :type="field.type" step="any"
                          :disabled="mission.missionStatus === 'RUNNING'"
                          class="bg-transparent text-xs font-mono font-bold text-(--text-primary) w-24 outline-none" />
                      </div>
                    </template>
                  </div>

                  <!-- Running indicator -->
                  <div v-if="getStepStatus(idx) === 'active'" class="mt-2 flex items-center gap-2">
                    <div class="h-1 flex-1 bg-(--bg-secondary) rounded-full overflow-hidden">
                      <div class="h-full bg-primary rounded-full animate-pulse w-2/3"></div>
                    </div>
                    <span class="text-[9px] text-primary font-mono font-black">IN PROGRESS</span>
                  </div>
                </div>

                <!-- Actions -->
                <div class="flex flex-col gap-1 flex-shrink-0">
                  <button @click="mission.moveStep(idx, idx - 1)"
                    :disabled="idx === 0 || mission.missionStatus === 'RUNNING'"
                    class="p-1 rounded text-(--text-muted) hover:text-(--text-primary) disabled:opacity-20 hover:bg-card transition-all">
                    <ChevronUp class="w-3 h-3" />
                  </button>
                  <button @click="mission.moveStep(idx, idx + 1)"
                    :disabled="idx === mission.steps.length - 1 || mission.missionStatus === 'RUNNING'"
                    class="p-1 rounded text-(--text-muted) hover:text-(--text-primary) disabled:opacity-20 hover:bg-card transition-all">
                    <ChevronDown class="w-3 h-3" />
                  </button>
                  <button @click="mission.removeStep(idx)"
                    :disabled="mission.missionStatus === 'RUNNING'"
                    class="p-1 rounded text-(--text-muted) hover:text-primary disabled:opacity-20 hover:bg-primary/10 transition-all">
                    <Trash2 class="w-3 h-3" />
                  </button>
                </div>
              </div>
            </div>
          </template>
        </div>
      </div>

      <!-- ══ RIGHT: Timeline & Log ══ -->
      <div class="col-span-12 lg:col-span-5 flex flex-col gap-4 overflow-hidden min-h-0">

        <!-- Live Progress Panel -->
        <div class="glass-card p-4 flex-shrink-0 space-y-3">
          <div class="flex justify-between items-center">
            <span class="text-[10px] font-black uppercase tracking-widest text-(--text-secondary) flex items-center gap-2">
              <Cpu class="w-3.5 h-3.5 text-primary" /> Live Mission Progress
            </span>
            <span class="text-[10px] font-mono font-bold text-primary">
              {{ mission.progressPct }}% Complete
            </span>
          </div>

          <!-- Progress bar -->
          <div class="h-1.5 bg-(--bg-secondary) rounded-full overflow-hidden">
            <div class="h-full bg-primary rounded-full transition-all duration-500"
              :style="{ width: `${mission.progressPct}%` }">
            </div>
          </div>

          <!-- Current step info -->
          <div v-if="mission.currentStep?.type" class="p-2 rounded-lg bg-primary/10 border border-primary/30">
            <div class="flex items-center gap-2">
              <span class="text-sm">{{ getStepTypeDef(mission.currentStep.type)?.icon }}</span>
              <div>
                <div class="text-xs font-black text-primary uppercase tracking-wide">{{ mission.currentStep.name }}</div>
                <div class="text-[10px] text-(--text-secondary) font-mono">
                  {{ mission.currentStep.type }}
                  <span v-if="mission.currentStep.type === 'TRACKING_BUOY'">
                    | Pass: {{ mission.buoyPassCount }}/{{ mission.currentStep.pass_count }}
                  </span>
                </div>
              </div>
            </div>
          </div>
          <div v-else class="text-xs text-(--text-muted) italic text-center py-2">
            Mission idle — configure steps and press START
          </div>
        </div>

        <!-- Mission Timeline (visual steps overview) -->
        <div class="glass-card flex-1 flex flex-col overflow-hidden min-h-0">
          <div class="p-3 border-b border-(--border-subtle) flex-shrink-0">
            <span class="text-[10px] font-black uppercase tracking-widest text-(--text-secondary) flex items-center gap-2">
              <ListOrdered class="w-3.5 h-3.5 text-primary" /> Timeline Overview
            </span>
          </div>
          <div class="flex-1 overflow-y-auto p-3 space-y-2">
            <div v-if="!mission.steps.length" class="text-xs text-(--text-muted) italic text-center py-4">
              No steps defined
            </div>
            <div v-for="(step, idx) in mission.steps" :key="step.id"
              class="flex items-center gap-3 p-2 rounded-lg transition-all"
              :class="{
                'bg-success/10 text-success': getStepStatus(idx) === 'done',
                'bg-primary/10 text-primary': getStepStatus(idx) === 'active',
                'text-(--text-muted)': getStepStatus(idx) === 'pending'
              }">
              <CheckCircle2 v-if="getStepStatus(idx) === 'done'" class="w-4 h-4 flex-shrink-0" />
              <Clock v-else-if="getStepStatus(idx) === 'active'" class="w-4 h-4 flex-shrink-0 animate-spin" />
              <span v-else class="w-4 h-4 flex-shrink-0 flex items-center justify-center text-[9px] font-black bg-card rounded-full border border-(--border-subtle)">
                {{ idx + 1 }}
              </span>
              <div class="flex-1 min-w-0">
                <div class="text-[11px] font-bold truncate">{{ step.name }}</div>
                <div class="text-[9px] opacity-60 font-mono">{{ step.type }}</div>
              </div>
            </div>
          </div>
        </div>

        <!-- Activity Log -->
        <div class="glass-card flex-shrink-0 max-h-40 flex flex-col overflow-hidden">
          <div class="px-3 py-2 border-b border-(--border-subtle) flex-shrink-0">
            <span class="text-[10px] font-black uppercase tracking-widest text-(--text-secondary) flex items-center gap-2">
              <AlertTriangle class="w-3.5 h-3.5 text-warning" /> Activity Log
            </span>
          </div>
          <div class="flex-1 overflow-y-auto p-2 space-y-1 font-mono text-[10px]">
            <div v-for="w in vessel.warnings.slice(0, 8)" :key="w.id"
              class="text-(--text-secondary) hover:text-(--text-primary) transition-colors">
              <span class="text-primary">[{{ new Date(w.timestamp).toLocaleTimeString() }}]</span>
              <span class="font-bold uppercase ml-1">[{{ w.code }}]</span> {{ w.message }}
            </div>
            <div v-if="vessel.warnings.length === 0" class="text-(--text-muted) italic py-2 text-center">
              No active logs.
            </div>
          </div>
        </div>

      </div>
    </div>

    <!-- Save Preset Modal -->
    <div v-if="showSavePresetModal" class="fixed inset-0 bg-slate-950/80 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div class="glass-card border border-(--border-primary) p-6 rounded-2xl w-full max-w-md space-y-4 shadow-2xl">
        <h3 class="text-sm font-black uppercase text-(--text-primary) tracking-wide flex items-center gap-2">
          <Save class="w-4 h-4 text-success" /> Save Mission Preset to Database
        </h3>
        <p class="text-xs text-(--text-secondary)">
          Simpan alur urutan {{ mission.steps.length }} langkah saat ini ke dalam database agar tersimpan secara permanen.
        </p>
        <input v-model="presetNameInput" placeholder="Nama Preset (misal: Rute Kualifikasi 1)..."
          @keyup.enter="handleSavePreset"
          class="w-full bg-(--bg-secondary) border border-(--border-subtle) rounded-xl px-4 py-2.5 text-xs text-(--text-primary) font-bold outline-none focus:border-primary" />
        <div class="flex justify-end gap-2 pt-2">
          <button @click="showSavePresetModal = false" class="px-4 py-2 rounded-xl bg-card text-xs font-bold text-(--text-secondary) hover:bg-slate-700">
            Batal
          </button>
          <button @click="handleSavePreset" :disabled="!presetNameInput.trim()"
            class="px-5 py-2 rounded-xl bg-success text-slate-900 text-xs font-black uppercase hover:bg-emerald-400 disabled:opacity-40">
            Simpan ke DB
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

