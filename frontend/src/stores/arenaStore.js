import { defineStore } from "pinia";
import { ref, computed } from "vue";

import { API_BASE } from "@/config/api";

export const useArenaStore = defineStore("arena", () => {
  // ── Saved arenas from DB ────────────────────────────────────────────────
  const savedArenas = ref([]);
  const isLoadingArenas = ref(false);

  // ── Active working arena (in-progress / being edited) ───────────────────
  const activeArena = ref({
    id: null,          // null = unsaved new arena
    name: "",
    description: "",
    buoys: [],         // [{ id, type: 'red'|'green', lat, lng, label }]
    trails: [],        // [{ id, type: 'green'|'blue', label, points: [{lat,lng}] }]
  });

  // ── Placement state ─────────────────────────────────────────────────────
  // 'buoy_red' | 'buoy_green' | 'trail_green' | 'trail_blue' | null
  const activePlaceTool = ref(null);
  const activeTrailPoints = ref([]);  // points accumulating for current trail being drawn

  const isDrawingTrail = computed(() =>
    activePlaceTool.value === "trail_green" || activePlaceTool.value === "trail_blue"
  );

  const totalElements = computed(
    () => activeArena.value.buoys.length + activeArena.value.trails.length
  );

  // ── Tool management ──────────────────────────────────────────────────────
  function setTool(tool) {
    // Same tool clicked again → deactivate
    if (activePlaceTool.value === tool) {
      activePlaceTool.value = null;
      activeTrailPoints.value = [];
      return;
    }
    // Switching away from trail mid-draw → discard
    if (isDrawingTrail.value) {
      activeTrailPoints.value = [];
    }
    activePlaceTool.value = tool;
  }

  function clearTool() {
    activePlaceTool.value = null;
    activeTrailPoints.value = [];
  }

  // ── Place element on map click ───────────────────────────────────────────
  function placeElement(lat, lng) {
    const tool = activePlaceTool.value;
    if (!tool) return;

    if (tool === "buoy_red" || tool === "buoy_green") {
      const type = tool === "buoy_red" ? "red" : "green";
      const count = activeArena.value.buoys.filter((b) => b.type === type).length + 1;
      activeArena.value.buoys.push({
        id: Date.now(),
        type,
        lat: parseFloat(lat.toFixed(7)),
        lng: parseFloat(lng.toFixed(7)),
        label: `${type === "red" ? "Merah" : "Hijau"} ${count}`,
      });
    } else if (tool === "trail_green" || tool === "trail_blue") {
      activeTrailPoints.value.push({
        lat: parseFloat(lat.toFixed(7)),
        lng: parseFloat(lng.toFixed(7)),
      });
    }
  }

  // Finish the trail being drawn (minimum 2 points)
  function finishTrail() {
    if (activeTrailPoints.value.length < 2) return;
    const type = activePlaceTool.value === "trail_green" ? "green" : "blue";
    const count = activeArena.value.trails.filter((t) => t.type === type).length + 1;
    activeArena.value.trails.push({
      id: Date.now(),
      type,
      label: `Trail ${type === "green" ? "Hijau" : "Biru"} ${count}`,
      points: [...activeTrailPoints.value],
    });
    activeTrailPoints.value = [];
  }

  // ── Element removal ──────────────────────────────────────────────────────
  function removeBuoy(id) {
    activeArena.value.buoys = activeArena.value.buoys.filter((b) => b.id !== id);
  }

  function removeTrail(id) {
    activeArena.value.trails = activeArena.value.trails.filter((t) => t.id !== id);
  }

  function clearAll() {
    activeArena.value.buoys = [];
    activeArena.value.trails = [];
    activeTrailPoints.value = [];
  }

  // ── DB Operations ────────────────────────────────────────────────────────
  async function fetchArenas() {
    isLoadingArenas.value = true;
    try {
      const res = await fetch(`${API_BASE}/api/v1/arenas`);
      const json = await res.json();
      if (json.status === "success") {
        savedArenas.value = (json.data || []).map((a) => ({
          ...a,
          buoys: typeof a.buoys === "string" ? JSON.parse(a.buoys || "[]") : (a.buoys || []),
          trails: typeof a.trails === "string" ? JSON.parse(a.trails || "[]") : (a.trails || []),
        }));
      }
    } catch (e) {
      console.warn("[ArenaStore] fetchArenas failed:", e);
    } finally {
      isLoadingArenas.value = false;
    }
  }

  async function saveArena() {
    if (!activeArena.value.name.trim()) return { ok: false, message: "Nama arena wajib diisi" };

    const payload = {
      name: activeArena.value.name.trim(),
      description: activeArena.value.description,
      buoys: JSON.stringify(activeArena.value.buoys),
      trails: JSON.stringify(activeArena.value.trails),
    };

    try {
      let res;
      if (activeArena.value.id) {
        // Update existing
        res = await fetch(`${API_BASE}/api/v1/arenas/${activeArena.value.id}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
      } else {
        // Create new
        res = await fetch(`${API_BASE}/api/v1/arenas`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
      }
      const json = await res.json();
      if (json.status === "success") {
        // Update ID if newly created
        if (!activeArena.value.id && json.data?.id) {
          activeArena.value.id = json.data.id;
        }
        await fetchArenas();
        return { ok: true, message: activeArena.value.id ? "Arena diperbarui" : "Arena disimpan" };
      }
      return { ok: false, message: json.message || "Gagal menyimpan" };
    } catch (e) {
      return { ok: false, message: `Error: ${e.message}` };
    }
  }

  async function deleteArena(id) {
    try {
      const res = await fetch(`${API_BASE}/api/v1/arenas/${id}`, { method: "DELETE" });
      const json = await res.json();
      if (json.status === "success") {
        await fetchArenas();
        // Reset if active arena was the deleted one
        if (activeArena.value.id === id) resetActiveArena();
        return true;
      }
    } catch (e) {
      console.error("[ArenaStore] deleteArena failed:", e);
    }
    return false;
  }

  function loadArena(arena) {
    activeArena.value = {
      id: arena.id,
      name: arena.name,
      description: arena.description || "",
      buoys: (arena.buoys || []).map((b) => ({ ...b, id: b.id || Date.now() + Math.random() })),
      trails: (arena.trails || []).map((t) => ({ ...t, id: t.id || Date.now() + Math.random() })),
    };
    clearTool();
  }

  function resetActiveArena() {
    activeArena.value = { id: null, name: "", description: "", buoys: [], trails: [] };
    clearTool();
  }

  // Fetch on init
  fetchArenas();

  return {
    savedArenas, isLoadingArenas,
    activeArena, activePlaceTool, activeTrailPoints,
    isDrawingTrail, totalElements,
    setTool, clearTool, placeElement, finishTrail,
    removeBuoy, removeTrail, clearAll,
    fetchArenas, saveArena, deleteArena, loadArena, resetActiveArena,
  };
});
