import time
import sys
from pymavlink import mavutil
from config import config


def set_param(master, param_name, value, param_type=mavutil.mavlink.MAV_PARAM_TYPE_REAL32, timeout=3):
    """Set param dan tunggu konfirmasi PARAM_VALUE dari flight controller."""
    param_bytes = param_name.encode() if isinstance(param_name, str) else param_name
    master.mav.param_set_send(
        master.target_system, master.target_component,
        param_bytes, float(value), param_type
    )
    ack = master.recv_match(
        type='PARAM_VALUE',
        condition=f"PARAM_VALUE.param_id=='{param_name}'",
        timeout=timeout
    )
    if ack is None:
        print(f"  ⚠️  {param_name}: TIDAK ADA ACK (mungkin gagal / param tidak dikenal)")
        return False
    print(f"  ✅ {param_name} = {ack.param_value}")
    return True


def wait_mode(master, target_mode_str, timeout=5):
    start = time.time()
    while time.time() - start < timeout:
        hb = master.recv_match(type='HEARTBEAT', blocking=True, timeout=1)
        if hb is None:
            continue
        mode_str = mavutil.mode_string_v10(hb)
        armed = bool(hb.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
        if mode_str == target_mode_str:
            return True, armed
    return False, None


def main():
    print("========================================")
    print("      ASV SERVO & THRUSTER TESTER       ")
    print("========================================")
    print(f"Connecting to {config.CONNECTION_STRING} at {config.BAUDRATE} baud...")

    try:
        master = mavutil.mavlink_connection(config.CONNECTION_STRING, baud=config.BAUDRATE)
    except Exception as e:
        print(f"Gagal konek: {e}")
        return

    print("Menunggu heartbeat dari Pixhawk...")
    master.wait_heartbeat()
    print("Heartbeat diterima! System ID:", master.target_system)

    # =========================================================
    # 1. Set param dasar (arming check, failsafe, safety default)
    # =========================================================
    print("\n[1/5] Konfigurasi param dasar...")
    set_param(master, "ARMING_CHECK", 0, mavutil.mavlink.MAV_PARAM_TYPE_INT32)
    set_param(master, "FS_THR_ENABLE", 0, mavutil.mavlink.MAV_PARAM_TYPE_INT32)

    needs_reboot = set_param(master, "BRD_SAFETY_DEFLT", 0, mavutil.mavlink.MAV_PARAM_TYPE_INT32)

    # =========================================================
    # 2. Set SERVOx_FUNCTION -> RCPassThru untuk channel target
    #    Ubah list ini sesuai channel yang mau bosku pakai untuk test
    #    1 = RCPassThru (langsung ikut RC input channel yang sama nomornya)
    # =========================================================
    print("\n[2/5] Konfigurasi SERVOx_FUNCTION jadi RCPassThru...")
    TEST_CHANNELS = [1, 2, 3, 4]  # <-- sesuaikan channel yang mau dites
    for ch in TEST_CHANNELS:
        set_param(master, f"SERVO{ch}_FUNCTION", 1, mavutil.mavlink.MAV_PARAM_TYPE_INT32)

    # =========================================================
    # 3. Reboot kalau BRD_SAFETY_DEFLT baru diubah (supaya safety switch
    #    otomatis OFF setelah boot, tanpa perlu pencet tombol fisik)
    # =========================================================
    if needs_reboot:
        print("\n[3/5] Reboot Pixhawk supaya BRD_SAFETY_DEFLT berlaku...")
        confirm = input("  Reboot sekarang? (y/n): ")
        if confirm.lower() == 'y':
            master.mav.command_long_send(
                master.target_system, master.target_component,
                mavutil.mavlink.MAV_CMD_PREFLIGHT_REBOOT_SHUTDOWN,
                0, 1, 0, 0, 0, 0, 0, 0
            )
            print("  Menunggu Pixhawk boot ulang (10 detik)...")
            time.sleep(10)
            master = mavutil.mavlink_connection(config.CONNECTION_STRING, baud=config.BAUDRATE)
            master.wait_heartbeat()
            print("  Heartbeat diterima kembali setelah reboot.")
        else:
            print("  Reboot dilewati. Safety switch fisik mungkin masih perlu ditekan manual.")
    else:
        print("\n[3/5] Reboot dilewati (BRD_SAFETY_DEFLT sudah 0 / tidak berubah).")

    # =========================================================
    # 4. ARM
    # =========================================================
    print("\n[4/5] Melakukan FORCE ARM...")
    master.mav.command_long_send(
        master.target_system, master.target_component,
        mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
        0, 1, 2989, 0, 0, 0, 0, 0
    )
    ack = master.recv_match(type='COMMAND_ACK', blocking=True, timeout=3)
    print(f"  ARM ACK: {ack}")

    # =========================================================
    # 5. Set Mode MANUAL + verifikasi
    # =========================================================
    print("\n[5/5] Mengubah mode ke MANUAL...")
    master.set_mode('MANUAL')
    ok, armed = wait_mode(master, 'MANUAL', timeout=5)
    if ok:
        print(f"  ✅ Mode MANUAL aktif. Armed: {armed}")
    else:
        print("  ⚠️  Mode belum terkonfirmasi MANUAL, lanjut tetap dicoba.")

    print("\n✅ SETUP SELESAI. SIAP MENGGERAKKAN SERVO!")
    print(f"   (Channel yang di-passthrough: {TEST_CHANNELS})")

    rc_channels = [65535] * 18

    try:
        while True:
            print("\n--------------------------------")
            ch_str = input("Masukkan Channel (1-18) [atau 'q' untuk keluar]: ")
            if ch_str.lower() == 'q':
                break

            try:
                ch = int(ch_str)
                if not (1 <= ch <= 18):
                    print("Channel harus antara 1 dan 18!")
                    continue
            except ValueError:
                print("Input tidak valid.")
                continue

            pwm_str = input(f"Masukkan PWM untuk Channel {ch} (1000-2000): ")
            try:
                pwm = int(pwm_str)
                if not (1000 <= pwm <= 2000):
                    print("PWM harus antara 1000 dan 2000!")
                    continue
            except ValueError:
                print("Input tidak valid.")
                continue

            rc_channels[ch - 1] = pwm
            print(f"Mengirim RC_OVERRIDE... Ch{ch} = {pwm}µs")

            # Kirim berulang dengan interval kecil biar tidak kena timeout failsafe RC override
            for _ in range(3):
                master.mav.rc_channels_override_send(
                    master.target_system,
                    master.target_component,
                    *rc_channels[:18]
                )
                time.sleep(0.05)

    except KeyboardInterrupt:
        print("\nDibatalkan.")

    print("\nMembersihkan...")
    master.mav.rc_channels_override_send(
        master.target_system, master.target_component, *([65535] * 18)
    )
    master.mav.command_long_send(
        master.target_system, master.target_component,
        mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 0, 0, 0, 0, 0, 0, 0, 0
    )
    print("Selesai.")


if __name__ == "__main__":
    main()