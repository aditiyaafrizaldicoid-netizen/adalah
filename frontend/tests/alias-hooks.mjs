/**
 * Menerjemahkan alias "@/" milik Vite agar berkas uji bisa mengimpor store apa
 * adanya lewat `node --test`.
 *
 * Alias ini didefinisikan di vite.config.js dan hanya dipahami Vite. Tanpa hook
 * ini, store yang mengimpor "@/config/api" tidak bisa diuji sama sekali di Node —
 * dan store yang tidak bisa diuji adalah store yang bugnya baru ketahuan di danau.
 */
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../src");

export function resolve(specifier, context, nextResolve) {
  // Alias "@/..." → src/...
  if (specifier.startsWith("@/")) {
    let berkas = path.join(SRC, specifier.slice(2));
    // Vite melengkapi ekstensi sendiri; Node ESM menuntutnya ditulis.
    if (!path.extname(berkas)) berkas += ".js";
    return nextResolve(pathToFileURL(berkas).href, context);
  }

  // Impor relatif tanpa ekstensi ("./vesselStore") — juga dilengkapi Vite,
  // juga ditolak Node.
  if (specifier.startsWith(".") && !path.extname(specifier)) {
    return nextResolve(specifier + ".js", context);
  }

  return nextResolve(specifier, context);
}
