import math

class LocalFrameConverter:
    """
    Konverter Geodesi WGS84 untuk mengubah koordinat meter relatif (X, Y)
    terhadap titik asal (Home / Launch Point) menjadi koordinat GPS asli (Latitude, Longitude).

    Sumbu Lokal:
    - X_meters: Jarak lurus MAJU ke depan sepanjang arah kompas kapal (Heading).
    - Y_meters: Jarak pergeseran ke KANAN (+meter) atau KIRI (-meter) relatif terhadap kepala kapal.
    """

    EARTH_RADIUS_METERS = 6371000.0  # Jari-jari rata-rata bumi dalam meter

    @staticmethod
    def relative_meters_to_gps(home_lat: float, home_lng: float, heading_deg: float,
                                x_meters: float, y_meters: float) -> dict:
        """
        Mengonversi pergeseran (x_meters, y_meters) menjadi koordinat GPS (lat, lng).

        :param home_lat:    Latitude titik awal (Home/Launch Point) dalam derajat.
        :param home_lng:    Longitude titik awal (Home/Launch Point) dalam derajat.
        :param heading_deg: Arah kompas awal kapal saat dilepas (0 = Utara, 90 = Timur).
        :param x_meters:    Jarak maju ke depan (meter).
        :param y_meters:    Jarak geser ke kanan (+meter) atau kiri (-meter).
        :return: dict {"lat": float, "lng": float}
        """
        if home_lat is None or home_lng is None:
            return {"lat": 0.0, "lng": 0.0}

        heading_rad = math.radians(heading_deg)

        # Perhitungan vektor rotasi berdasarkan heading kapal
        # Delta North & Delta East dalam meter
        delta_north = x_meters * math.cos(heading_rad) + y_meters * math.sin(heading_rad)
        delta_east  = x_meters * math.sin(heading_rad) - y_meters * math.cos(heading_rad)

        # Proyeksi Flat-Earth WGS84
        delta_lat = (delta_north / LocalFrameConverter.EARTH_RADIUS_METERS) * (180.0 / math.pi)
        lat_rad = math.radians(home_lat)
        delta_lng = (delta_east / (LocalFrameConverter.EARTH_RADIUS_METERS * math.cos(lat_rad))) * (180.0 / math.pi)

        target_lat = home_lat + delta_lat
        target_lng = home_lng + delta_lng

        return {
            "lat": round(target_lat, 7),
            "lng": round(target_lng, 7),
            "x": x_meters,
            "y": y_meters,
            "x_meters": x_meters,
            "y_meters": y_meters
        }


    @staticmethod
    def convert_meter_waypoints_to_gps(home_lat: float, home_lng: float, heading_deg: float,
                                        meter_waypoints: list) -> list:
        """
        Mengonversi daftar waypoint meter relatif menjadi daftar koordinat GPS.

        :param meter_waypoints: List of dict [{"x": 15.0, "y": 0.0}, {"x": 30.0, "y": 5.0}, ...]
        :return: List of dict [{"seq": 1, "lat": -7.123, "lng": 112.123, "x": 15.0, "y": 0.0}, ...]
        """
        gps_waypoints = []
        for seq, wp in enumerate(meter_waypoints, start=1):
            x = float(wp.get("x", 0.0))
            y = float(wp.get("y", 0.0))
            coord = LocalFrameConverter.relative_meters_to_gps(home_lat, home_lng, heading_deg, x, y)
            coord["seq"] = seq
            gps_waypoints.append(coord)
        return gps_waypoints


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Jarak permukaan bumi antara dua koordinat, dalam METER.

    Dipakai geofence (control/geofence.py) dan siapa pun yang butuh jarak nyata dari
    sepasang lat/lon. MissionEngine punya salinan privatnya sendiri untuk GOTO_GPS;
    yang di sini publik supaya modul baru tidak perlu menyentuh isi kelas itu.
    """
    import math
    R = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def posisi_masuk_akal(lat, lon) -> bool:
    """
    Apakah sepasang koordinat ini layak dipakai untuk keputusan keselamatan?

    Menolak 0,0 secara khusus — itu nilai yang dilaporkan kapal saat GPS BELUM
    mengunci, dan letaknya di Teluk Guinea. Sebuah geofence yang mempercayainya akan
    menyimpulkan kapal berada ribuan kilometer di luar batas dan membatalkan SETIAP
    misi sebelum sempat berjalan.
    """
    try:
        lat = float(lat); lon = float(lon)
    except (TypeError, ValueError):
        return False
    if abs(lat) < 1e-7 and abs(lon) < 1e-7:
        return False
    return -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0
