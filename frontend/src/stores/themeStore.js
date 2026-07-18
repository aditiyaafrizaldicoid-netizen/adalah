import { defineStore } from "pinia";
import { ref, watch } from "vue";

export const useThemeStore = defineStore("theme", () => {
  const theme = ref(localStorage.getItem("theme") || "dark");

  const toggleTheme = () => {
    theme.value = theme.value === "dark" ? "light" : "dark";
  };

  watch(
    theme,
    (val) => {
      document.documentElement.setAttribute("data-theme", val);
      localStorage.setItem("theme", val);
    },
    { immediate: true },
  );

  return { theme, toggleTheme };
});
