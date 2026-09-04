"""
Geo-tag untuk Position and Mission Imaging Infos.

SATU-SATUNYA sumber format untuk seluruh field geo-tag yang diminta juri, dipakai
bersama oleh overlay gambar hasil TAKE_IMAGE dan sidecar JSON-nya. Formatnya juga
digandakan di base station (frontend/src/utils/geotag.js) untuk tampilan layar —
kalau salah satu diubah, ubah keduanya.

Field yang wajib ada (sesuai lembar ketentuan):
  - Day        [Sun, Mon, Tue, Wed, Thu, Fri, Sat]
  - Date       [DD/MM/YYYY]
  - Time       [hh:mm:ss]
  - Coordinate — pilih salah satu:
      Format A: Degree, Decimal      → [S 3.56734 E 104.67235]
      Format B: Degree, Minute       → [S 3° 43,5423' E 104° 33,6445']
  - Speed Over Ground (SOG)          dalam knot DAN km/jam
  - Course Over Ground (COG)         dalam derajat

CATATAN PEMISAH DESIMAL: lembar ketentuan tidak konsisten — judul Format A menulis
placeholder [DD,DDDD] (koma) sedangkan CONTOH-nya memakai titik (3.56734), sementara
Format B memakai koma pada menit (43,5423). Di sini yang diikuti adalah CONTOH-nya,
karena itu yang paling mungkin dibandingkan juri. Kalau ternyata harus koma semua,
ubah DECIMAL_SEP_A di bawah — tidak ada tempat lain yang perlu disentuh.
"""

import json
import math
import os
from datetime import datetime
from typing import Any, Dict, Optional

# Nama hari WAJIB bahasa Inggris persis seperti lembar ketentuan. Ditulis eksplisit,
# TIDAK memakai strftime("%a") — hasil strftime ikut locale sistem, dan perangkat di
# kapal bisa saja ber-locale Indonesia sehingga keluar "Sen"/"Sel" yang tidak dikenali
# juri. Kegagalan seperti itu tidak akan terlihat sampai hari lomba.
_DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")  # datetime.weekday(): Senin = 0

DECIMAL_SEP_A = "."   # pemisah desimal Format A (lihat catatan di docstring)
DECIMAL_SEP_B = ","   # pemisah desimal menit Format B

KNOTS_PER_MS = 1.94384   # 1 m/s = 1.94384 knot
KMH_PER_MS = 3.6         # 1 m/s = 3.6 km/jam


def format_day(dt: datetime) -> str:
    """Nama hari 3 huruf: Sun/Mon/Tue/Wed/Thu/Fri/Sat."""
    return _DAY_NAMES[dt.weekday()]


def format_date(dt: datetime) -> str:
    """Tanggal DD/MM/YYYY."""
    return dt.strftime("%d/%m/%Y")


def format_time(dt: datetime) -> str:
    """Jam hh:mm:ss, 24 jam."""
    return dt.strftime("%H:%M:%S")


def _hemisphere(value: float, is_lat: bool) -> str:
    if is_lat:
        return "N" if value >= 0 else "S"
    return "E" if value >= 0 else "W"


def format_coord_a(lat: float, lon: float, decimals: int = 5) -> str:
    """Format A — Degree, Decimal. Contoh: 'S 3.56734 E 104.67235'."""
    lat_s = f"{abs(float(lat)):.{decimals}f}".replace(".", DECIMAL_SEP_A)
    lon_s = f"{abs(float(lon)):.{decimals}f}".replace(".", DECIMAL_SEP_A)
    return f"{_hemisphere(lat, True)} {lat_s} {_hemisphere(lon, False)} {lon_s}"


def _deg_min(value: float, decimals: int = 4) -> str:
    """Satu komponen Format B: derajat bulat + menit desimal. Contoh: \"3° 43,5423'\"."""
    absolute = abs(float(value))
    degrees = int(absolute)
    minutes = (absolute - degrees) * 60.0
    # Pembulatan menit bisa menyentuh 60,0000 (mis. 3.99999999 derajat) — itu bukan
    # koordinat yang sah dan harus naik ke derajat berikutnya, bukan dicetak apa adanya.
    minutes_s = f"{minutes:.{decimals}f}"
    if float(minutes_s) >= 60.0:
        degrees += 1
        minutes_s = f"{0.0:.{decimals}f}"
    return f"{degrees}° {minutes_s.replace('.', DECIMAL_SEP_B)}'"


def format_coord_b(lat: float, lon: float) -> str:
    """Format B — Degree, Minute. Contoh: \"S 3° 43,5423' E 104° 33,6445'\"."""
    return (f"{_hemisphere(lat, True)} {_deg_min(lat)} "
            f"{_hemisphere(lon, False)} {_deg_min(lon)}")


def build_fields(telemetry: Dict[str, Any], dt: Optional[datetime] = None) -> Dict[str, Any]:
    """
    Rakit seluruh field geo-tag dari satu dict telemetri (hasil get_telemetry_dict()).

    Mengembalikan nilai TERFORMAT (untuk overlay & tampilan) sekaligus nilai MENTAH
    (untuk sidecar JSON), supaya angka aslinya tidak hilang oleh pembulatan tampilan.

    `cog_valid=False` berarti kapal terlalu pelan sehingga arah geraknya tidak berarti —
    COG ditulis "-" alih-alih memampang arah basi di gambar yang akan dinilai.
    """
    dt = dt or datetime.now()
    lat = float(telemetry.get("lat") or 0.0)
    lon = float(telemetry.get("lon") or 0.0)
    sog_ms = float(telemetry.get("ground_speed") or 0.0)
    cog_valid = bool(telemetry.get("cog_valid"))
    cog = float(telemetry.get("cog") or 0.0)

    return {
        "day": format_day(dt),
        "date": format_date(dt),
        "time": format_time(dt),
        "coord_a": format_coord_a(lat, lon),
        "coord_b": format_coord_b(lat, lon),
        "sog_knot": round(sog_ms * KNOTS_PER_MS, 2),
        "sog_kmh": round(sog_ms * KMH_PER_MS, 2),
        "cog_deg": round(cog, 2) if cog_valid else None,
        "cog_valid": cog_valid,
        # Nilai mentah — jangan dipakai untuk tampilan, hanya untuk arsip/analisis.
        "raw": {
            "lat": lat, "lon": lon,
            "sog_ms": sog_ms,
            "cog_deg": cog,
            "heading_deg": float(telemetry.get("heading") or 0.0),
            "timestamp_iso": dt.isoformat(timespec="seconds"),
        },
    }


def overlay_lines(fields: Dict[str, Any]) -> list:
    """Baris teks yang dicetak ke gambar, urut sesuai lembar ketentuan."""
    cog = f"{fields['cog_deg']:.2f} deg" if fields["cog_deg"] is not None else "- (kapal terlalu pelan)"
    return [
        f"{fields['day']} {fields['date']} {fields['time']}",
        f"A: {fields['coord_a']}",
        f"B: {fields['coord_b']}",
        f"SOG: {fields['sog_knot']:.2f} knot / {fields['sog_kmh']:.2f} km/h",
        f"COG: {cog}",
    ]


def draw_overlay(frame, fields: Dict[str, Any]):
    """
    Cetak geo-tag ke gambar (kotak gelap semi-transparan di kiri bawah).

    Ukuran font & tebal garis diskalakan terhadap lebar frame supaya tetap terbaca
    baik pada 640px maupun 1920px — geo-tag yang tidak terbaca sama saja dengan
    tidak ada saat dinilai.
    """
    import cv2  # lokal: agar modul ini tetap bisa diuji tanpa OpenCV terpasang

    h, w = frame.shape[:2]
    scale = max(0.4, min(1.2, w / 1600.0))
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.6 * scale
    thickness = max(1, int(round(1.6 * scale)))
    pad = int(12 * scale)
    line_h = int(28 * scale)

    lines = overlay_lines(fields)
    text_w = max(cv2.getTextSize(t, font, font_scale, thickness)[0][0] for t in lines)
    box_w = min(w, text_w + pad * 2)
    box_h = line_h * len(lines) + pad
    y0 = h - box_h - pad

    # Latar gelap semi-transparan supaya teks putih tetap terbaca di atas air terang.
    panel = frame[max(y0, 0):y0 + box_h, 0:box_w]
    if panel.size:
        cv2.rectangle(panel, (0, 0), (panel.shape[1], panel.shape[0]), (0, 0, 0), -1)
        cv2.addWeighted(panel, 0.55, frame[max(y0, 0):y0 + box_h, 0:box_w], 0.45, 0,
                        frame[max(y0, 0):y0 + box_h, 0:box_w])

    for i, text in enumerate(lines):
        y = y0 + pad + line_h * i + int(line_h * 0.55)
        cv2.putText(frame, text, (pad, y), font, font_scale, (255, 255, 255),
                    thickness, cv2.LINE_AA)
    return frame


def save_geotagged_image(frame, telemetry: Dict[str, Any], out_dir: str,
                         label: str = "", dt: Optional[datetime] = None,
                         extra: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """
    Simpan gambar ber-geo-tag + sidecar JSON berisi field yang sama.

    JSON-nya bukan pelengkap iseng: overlay bisa terbaca manusia tapi angkanya sudah
    dibulatkan untuk tampilan, sedangkan JSON menyimpan nilai mentah sehingga hasil
    lomba tetap bisa diaudit/diolah ulang tanpa membaca piksel.

    `extra` ikut ditulis ke sidecar JSON. Dipakai mencatat KAMERA MANA yang
    mengambil foto ini — bukti yang bertahan setelah lomba, sementara nama berkas
    bisa saja tertukar saat disalin.

    Return path gambar, atau None kalau gagal (frame kosong / OpenCV bermasalah).
    Kegagalan TIDAK dilempar sebagai exception: misi yang sedang berjalan tidak boleh
    ikut berhenti hanya karena satu foto gagal disimpan.
    """
    if frame is None or getattr(frame, "size", 0) == 0:
        print("[Geotag] ⚠️ Tidak ada frame kamera — foto TAKE_IMAGE dilewati.")
        return None

    try:
        import cv2

        dt = dt or datetime.now()
        fields = build_fields(telemetry, dt)
        os.makedirs(out_dir, exist_ok=True)

        safe_label = "".join(c if c.isalnum() or c in "-_" else "_" for c in (label or "")).strip("_")
        stem = dt.strftime("%Y%m%d_%H%M%S")
        if safe_label:
            stem = f"{stem}_{safe_label}"

        img_path = os.path.join(out_dir, f"{stem}.jpg")
        json_path = os.path.join(out_dir, f"{stem}.json")

        stamped = draw_overlay(frame.copy(), fields)
        if not cv2.imwrite(img_path, stamped):
            print(f"[Geotag] ⚠️ Gagal menulis {img_path}")
            return None

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump({"image": os.path.basename(img_path), **fields,
                       **(extra or {})}, f, indent=2, ensure_ascii=False)

        print(f"[Geotag] 📸 Foto misi tersimpan: {img_path}")
        for line in overlay_lines(fields):
            print(f"[Geotag]    {line}")
        return img_path
    except Exception as e:
        print(f"[Geotag] ⚠️ Gagal menyimpan foto ber-geotag: {e}")
        return None
