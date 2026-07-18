<script setup>
import { useScoringStore } from '@/stores/scoringStore';
import ScoreCalculator from "../components/scoring/ScoreCalculator.vue";
import MissionScoreBoard from "../components/scoring/MissionScoreBoard.vue";
import LiveScoreboard from "../components/scoring/LiveScoreboard.vue";
import ImageQualityJudge from "../components/scoring/ImageQualityJudge.vue";
import { Trophy } from "lucide-vue-next";

const scoring = useScoringStore();
</script>

<template>
  <div class="p-6 h-full overflow-y-auto space-y-6">
    <div class="flex justify-between items-end">
      <div>
        <h1 class="text-2xl font-bold text-(--text-primary) tracking-tight flex items-center gap-3">
          <Trophy class="text-warning w-6 h-6" />
          SCORING SYSTEM
        </h1>
        <p class="text-(--text-secondary) text-xs mt-1 uppercase tracking-widest font-bold">Real-time Performance Metrics</p>
      </div>
      <div class="text-4xl font-black text-primary font-mono tracking-tighter">
        {{ scoring.totalScore.toFixed(2) }} <span class="text-sm text-(--text-secondary) font-bold uppercase">Points</span>
      </div>
    </div>

    <div class="grid grid-cols-12 gap-6">
       <!-- Score Calculator & Breakdown (Sub-components) -->
       <div class="col-span-12 lg:col-span-8 flex flex-col gap-6">
          <ScoreCalculator />
          <MissionScoreBoard />
       </div>

       <!-- Leaderboard (Sub-component) -->
       <div class="col-span-12 lg:col-span-4">
          <LiveScoreboard />
       </div>

       <!-- Image Judging (Sub-component) -->
       <div class="col-span-12">
          <ImageQualityJudge />
       </div>
    </div>
  </div>
</template>
