# ==============================================================================
# 🚢 ASV FLIGHT CONTROLLER MAKEFILE
# ==============================================================================

.PHONY: run clean clear restart test test-unit help

# Set environment variable agar Python tidak membuat bytecode (.pyc / __pycache__)
export PYTHONDONTWRITEBYTECODE=1

# Command default ketika mengetik `make`
all: run

# Jalankan sistem Flight Controller
run:
	@echo "🚢 Memulai ASV Flight Controller (tanpa bytecode cache)..."
	@python3 main.py

# Bersihkan semua file cache Python (__pycache__, *.pyc, *.pyo)
clean clear:
	@echo "🧹 Membersihkan semua cache Python (__pycache__ & *.pyc)..."
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -name "*.pyc" -delete 2>/dev/null || true
	@find . -name "*.pyo" -delete 2>/dev/null || true
	@echo "✅ Cache berhasil dibersihkan total!"

# Bersihkan cache lalu jalankan ulang Flight Controller
restart: clean run

# Verifikasi sintaks semua file Python dalam modul
test:
	@echo "🔍 Verifikasi sintaks kompilasi file Python..."
	@python3 -m py_compile main.py connection/*.py control/*.py core/*.py vision/*.py camera/*.py
	@echo "✅ Semua file Python valid dan bebas error sintaks!"

# Uji perilaku, bukan cuma sintaks. Memakai unittest bawaan Python — sengaja
# tanpa pustaka tambahan, supaya bisa dijalankan di Mini PC apa adanya tanpa
# memasang apa pun lebih dulu.
test-unit:
	@echo "🧪 Uji perilaku di tests/ ..."
	@python3 -m unittest discover -s tests -t . -q
	@echo "🧪 Uji di tools/ ..."
	@# Berkas uji di tools/ berdiri sendiri (punya __main__) dan TIDAK terjaring
	@# unittest discover di atas. Dijalankan satu per satu supaya tidak diam-diam
	@# tertinggal — uji shutter di sana menjaga bug lapangan yang sudah pernah
	@# terjadi, dan uji opsi panel menjaga dropdown tetap berarti sama di kapal.
	@for f in tools/uji_*.py; do \
		echo "  → $$f"; \
		python3 "$$f" >/dev/null 2>&1 || { python3 "$$f"; exit 1; }; \
	done
	@echo "✅ Semua uji lolos."

# Tampilkan petunjuk penggunaan Makefile
help:
	@echo "Gunakan salah satu perintah berikut:"
	@echo "  make run     - Jalankan Flight Controller (python3 main.py)"
	@echo "  make clean   - Bersihkan semua cache __pycache__ & file .pyc"
	@echo "  make restart - Bersihkan cache lalu jalankan ulang sistem"
	@echo "  make test      - Verifikasi sintaks kompilasi file Python"
	@echo "  make test-unit - Jalankan uji perilaku (geofence, dll)"
