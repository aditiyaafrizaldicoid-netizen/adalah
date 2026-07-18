import { ref, watch, nextTick, onBeforeUnmount } from 'vue';

const BLANK = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7';

/**
 * Composable for robust MJPEG <img> streams.
 *
 * The ONLY reliable way to stop an MJPEG stream in a browser is to directly
 * set imgElement.src = '' on the DOM element (not via Vue reactivity).
 * This immediately sends an abort signal. We expose `imgRef` for the component
 * to bind with `ref="imgRef"`.
 */
export function useMjpegStream(srcRef, options = {}) {
    const { retryDelay = 3000 } = options;

    const activeSrc = ref(BLANK);
    const isError = ref(false);
    const retryCount = ref(0);
    const imgRef = ref(null); // Component binds: <img ref="imgRef">

    let retryTimer = null;
    let connectTimer = null;
    let destroyed = false;

    function clearTimers() {
        if (retryTimer) { clearTimeout(retryTimer); retryTimer = null; }
        if (connectTimer) { clearTimeout(connectTimer); connectTimer = null; }
    }

    function buildUrl(src) {
        if (!src) return BLANK;
        const sep = src.includes('?') ? '&' : '?';
        return `${src}${sep}_t=${Date.now()}`;
    }

    function forceAbort() {
        // Direct DOM manipulation — the ONLY reliable way to abort MJPEG in browser
        const el = imgRef.value;
        if (el) {
            el.src = '';    // Immediately aborts the ongoing HTTP request
            el.src = BLANK; // Set to blank pixel so browser doesn't retry old URL
        }
    }

    async function connect(src) {
        if (destroyed) return;
        clearTimers();
        isError.value = false;
        retryCount.value = 0;

        // Step 1: Force-abort the current MJPEG connection via direct DOM access
        forceAbort();

        // Step 2: Mark as blank in Vue state (hides img via v-show/opacity)
        activeSrc.value = BLANK;

        // Step 3: Wait for DOM update
        await nextTick();

        if (destroyed || !src) return;

        // Step 4: Short delay, then open new connection
        // 100ms is enough since we already force-aborted
        connectTimer = setTimeout(() => {
            if (destroyed) return;
            activeSrc.value = buildUrl(src);
        }, 100);
    }

    function onError() {
        if (destroyed) return;
        isError.value = true;
        const src = typeof srcRef === 'object' ? srcRef.value : srcRef;
        if (!src) return;
        clearTimers();
        retryTimer = setTimeout(async () => {
            retryCount.value++;
            await connect(src);
        }, retryDelay);
    }

    function onLoad() {
        isError.value = false;
        retryCount.value = 0;
    }

    function reload() {
        const src = typeof srcRef === 'object' ? srcRef.value : srcRef;
        connect(src);
    }

    // React to source changes
    watch(
        () => (typeof srcRef === 'object' ? srcRef.value : srcRef),
        (newSrc) => connect(newSrc),
        { immediate: true }
    );

    onBeforeUnmount(() => {
        destroyed = true;
        clearTimers();
        forceAbort();
        activeSrc.value = BLANK;
    });

    return { activeSrc, isError, retryCount, imgRef, onError, onLoad, reload, BLANK };
}