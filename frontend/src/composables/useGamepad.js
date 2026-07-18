import { ref, onMounted, onUnmounted } from 'vue';

export function useGamepad() {
  const isConnected = ref(false);
  const gamepadName = ref('');
  const axes = ref([]);
  const buttons = ref([]);
  const error = ref(null);

  let animationFrameId = null;

  const updateGamepadState = () => {
    // Get the first connected gamepad
    const gamepads = navigator.getGamepads ? navigator.getGamepads() : [];
    let gp = null;
    
    for (let i = 0; i < gamepads.length; i++) {
      if (gamepads[i]) {
        gp = gamepads[i];
        break;
      }
    }

    if (gp) {
      isConnected.value = true;
      gamepadName.value = gp.id;
      // Copy axes to make it reactive
      axes.value = [...gp.axes];
      // Map buttons to boolean values (pressed state)
      buttons.value = gp.buttons.map(b => typeof b === 'object' ? b.pressed : b === 1.0);
    } else {
      isConnected.value = false;
      gamepadName.value = '';
    }

    // Schedule next update
    animationFrameId = requestAnimationFrame(updateGamepadState);
  };

  const handleGamepadConnected = (e) => {
    console.log("Gamepad connected:", e.gamepad.id);
    isConnected.value = true;
    gamepadName.value = e.gamepad.id;
  };

  const handleGamepadDisconnected = (e) => {
    console.log("Gamepad disconnected:", e.gamepad.id);
    isConnected.value = false;
    gamepadName.value = '';
    axes.value = [];
    buttons.value = [];
  };

  onMounted(() => {
    if (!('getGamepads' in navigator)) {
      error.value = "Browser Anda tidak mendukung Gamepad API.";
      return;
    }
    
    window.addEventListener("gamepadconnected", handleGamepadConnected);
    window.addEventListener("gamepaddisconnected", handleGamepadDisconnected);
    
    // Start polling loop
    animationFrameId = requestAnimationFrame(updateGamepadState);
  });

  onUnmounted(() => {
    window.removeEventListener("gamepadconnected", handleGamepadConnected);
    window.removeEventListener("gamepaddisconnected", handleGamepadDisconnected);
    if (animationFrameId) {
      cancelAnimationFrame(animationFrameId);
    }
  });

  return {
    isConnected,
    gamepadName,
    axes,
    buttons,
    error
  };
}
