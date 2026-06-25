import io
import re
import statistics
from datetime import datetime
from flask import Flask, render_template, request, jsonify
import pdfplumber

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# ─── Cihaz konfigürasyonu (teknik belgelerden) ─────────────────────────────
# Kaynak: DataServices.pdf — çalışma prensipleri
# Defrost bitiş sıcaklıkları: FF evap +10°C, FRZ evap +4°C
# Kompresör: min 5 dk çalış, min 6 dk dur
# Defrost sıklığı: 12-96 saat arası, ortalama 26 saat
DEVICE_CONFIG = {
    'FF': {
        'name': 'Buzdolabı / Soğutucu (Fresh Food)',
        'normal_min': 0.0,
        'normal_max': 8.0,
        'ideal_min': 2.0,
        'ideal_max': 5.0,
        'door_open_threshold': 2.5,   # 10 dk'da bu kadar ani artış = kapı
        'cooldown_threshold': 8.0,
        'defrost_indicator': 7.0,     # Bu değer üstü → defrost şüphesi
        'min_compressor_on_min': 5,   # Teknik belgeden: min 5 dk çalışır
        'min_compressor_off_min': 6,  # Teknik belgeden: min 6 dk durur
        'color': '#3498db',
        'bg_color': 'rgba(52, 152, 219, 0.15)',
    },
    'FRZ': {
        'name': 'Derin Dondurucu (Freezer)',
        'normal_min': -25.0,
        'normal_max': -12.0,
        'ideal_min': -22.0,
        'ideal_max': -15.0,
        'door_open_threshold': 3.5,
        'cooldown_threshold': -12.0,
        'defrost_indicator': -10.0,   # Bu değer üstü → defrost olabilir
        'min_compressor_on_min': 5,
        'min_compressor_off_min': 6,
        'color': '#8e44ad',
        'bg_color': 'rgba(142, 68, 173, 0.15)',
    },
}

# ─── Hata kodu sözlüğü (DataServices55.pdf'den) ────────────────────────────
ERROR_CODES = {
    'E0':  'Freezer Bölmesi Hava Sensörü Hatası',
    'E1':  'Freezer Bölmesi Evaporatör Sensörü Hatası',
    'E2':  'Fresh Food Bölmesi Evaporatör Sensörü Hatası',
    'E3':  'Fresh Food Bölmesi Hava Sensörü Hatası',
    'E4':  'Freezer Defrost Sistem Hatası',
    'E5':  'Ortam/Nem Sensörü Hatası',
    'E8':  'Buzmatik Hava Sensörü Hatası',
    'E9':  'Buzmatik Motor Hatası',
    'E10': 'Joker Bölmesi (MultiZone) Hava Sensörü Hatası',
    'E11': 'Joker Bölmesi (MultiZone) Evaporatör Sensörü Hatası',
    'E12': 'Joker Defrost Sistem Hatası',
    'E13': 'Freezer Bölmesi Fan Hatası',
    'E14': 'Joker Bölmesi (MultiZone) Fan Hatası',
    'E15': 'Kondanser Fan Hatası',
    'E16': 'Fresh Food Bölmesi Fan Hatası',
    'E17': 'Flap Fan Hatası',
    'E18': 'Biofresh Fan Hatası',
    'E19': 'Flap Hava Sensörü Hatası',
    'E20': 'Biofresh Hava Sensörü Hatası',
    'E22': 'Ping Testi Yapılamadı',
    'E23': 'Ping Testi Yapılamadı',
}


# ─── PDF Parse ──────────────────────────────────────────────────────────────
def parse_testo_pdf(file_bytes):
    records = []
    header_info = {}
    channel_name = None
    report_timestamp = None

    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            raw_text = page.extract_text() or ""

            if report_timestamp is None:
                ts_m = re.search(r'(\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}:\d{2})', raw_text)
                if ts_m:
                    report_timestamp = ts_m.group(1)

            for table in page.extract_tables():
                if not table or len(table) < 2:
                    continue
                header_row = table[0]
                if not header_row or len(header_row) < 3:
                    continue
                if str(header_row[0] or '').strip().upper() != 'ID':
                    continue
                if channel_name is None and header_row[2]:
                    channel_name = str(header_row[2]).strip()

                for row in table[1:]:
                    if not row or len(row) < 3:
                        continue
                    id_str  = str(row[0] or '').strip()
                    dt_str  = str(row[1] or '').strip()
                    tmp_str = str(row[2] or '').strip().replace(',', '.')
                    if not id_str.isdigit():
                        continue
                    try:
                        rid = int(id_str)
                        temp = float(tmp_str)
                        dt = datetime.strptime(dt_str, '%d.%m.%Y %H:%M:%S')
                        records.append({
                            'id': rid,
                            'datetime': dt.isoformat(),
                            'datetime_display': dt_str,
                            'temperature': temp,
                            'timestamp': int(dt.timestamp() * 1000),
                        })
                    except (ValueError, TypeError):
                        pass

    records.sort(key=lambda x: x['id'])
    seen = set()
    unique = []
    for r in records:
        if r['id'] not in seen:
            seen.add(r['id'])
            unique.append(r)

    if unique:
        header_info['start_time']     = unique[0]['datetime_display']
        header_info['end_time']       = unique[-1]['datetime_display']
        header_info['total_readings'] = len(unique)
    if channel_name:
        header_info['channel_name'] = channel_name
    if report_timestamp:
        header_info['report_timestamp'] = report_timestamp

    return header_info, unique


# ─── Cihaz türü tespiti ─────────────────────────────────────────────────────
def detect_device_type(records):
    if not records:
        return 'FF'
    stable = records[5:] if len(records) > 5 else records
    avg = statistics.mean(r['temperature'] for r in stable)
    return 'FRZ' if avg < -5 else 'FF'


# ─── Soğuma başlangıcı ──────────────────────────────────────────────────────
def find_stable_start(records, device_type):
    threshold = DEVICE_CONFIG[device_type]['cooldown_threshold']
    # İlk 3 ardışık okuma threshold altında olduğunda stabil başlangıç say
    for i, r in enumerate(records):
        if r['temperature'] < threshold:
            return max(0, i)
    return 0


# ─── Ölçüm sonu: cihaz dolap dışına çıkarıldı ──────────────────────────────
def find_stable_end(records, device_type):
    """
    Ölçümün sonundaki 'cihaz dolap dışına çıkarıldı' periyodunu tespit eder.
    Son okuma normal_max üstündeyse ve normal aralığa geri dönmemişse,
    bu bölümü analiz dışı bırakır.
    """
    cfg = DEVICE_CONFIG[device_type]
    temps = [r['temperature'] for r in records]
    n = len(temps)

    if n < 6:
        return n

    # Son okuma normal aralıktaysa kırpma yok
    if temps[-1] <= cfg['normal_max']:
        return n

    # Sondan geriye doğru en son normal-aralık okumasını bul
    last_normal_i = -1
    for i in range(n - 1, n // 2, -1):
        if temps[i] <= cfg['normal_max']:
            last_normal_i = i
            break

    if last_normal_i < 0:
        return n  # Ölçümün yarısından fazlası yüksek → kırpma yapmıyoruz

    tail_len  = n - 1 - last_normal_i
    tail_rise = temps[-1] - temps[last_normal_i]

    # En az 2 okuma yüksek + anlamlı yükseliş → cihaz çıkarıldı
    if tail_len >= 2 and tail_rise >= cfg['door_open_threshold'] * 2:
        return last_normal_i + 1

    return n

# ─── Defrost döngüsü tespiti ────────────────────────────────────────────────
# Teknik belge: defrost her 12-96 saatte bir, ort. 26 saatte
# FRZ defrost sonrası evap +4°C'ye, FF evap +10°C'ye ulaşır
def detect_defrost_events(records, device_type):
    """
    Sıcaklık verisinde defrost döngülerini tespit eder.
    - 3+ ardışık artış + toplam yükseliş belirli eşiği geçmeli
    - FF: eşik 7°C | FRZ: eşik -10°C
    """
    cfg = DEVICE_CONFIG[device_type]
    defrosts = []
    temps = [r['temperature'] for r in records]
    n = len(temps)

    i = 1
    while i < n:
        # Sürekli yükseliş dizisi bul
        if temps[i] > temps[i - 1]:
            start = i - 1
            while i < n and temps[i] >= temps[i - 1] - 0.3:
                i += 1
            end = i - 1
            duration_readings = end - start
            total_rise = temps[end] - temps[start]
            peak = temps[end]

            if duration_readings >= 3 and total_rise >= 3.0:
                is_defrost = (device_type == 'FF' and peak > cfg['defrost_indicator']) or \
                             (device_type == 'FRZ' and peak > cfg['defrost_indicator'])
                defrosts.append({
                    'start_idx': start,
                    'end_idx': end,
                    'duration_min': duration_readings * 10,
                    'rise': round(total_rise, 1),
                    'peak': round(peak, 1),
                    'is_defrost': is_defrost,
                    'start_time': records[start]['datetime_display'],
                    'end_time': records[end]['datetime_display'],
                    'start_rid': records[start]['id'],
                })
        else:
            i += 1

    return defrosts


# ─── Döngü analizi ──────────────────────────────────────────────────────────
def analyze_cycles(records, stable_start):
    stable = records[stable_start:]
    if len(stable) < 4:
        return []
    temps = [r['temperature'] for r in stable]

    # Yerel maksimumları bul (dönme noktaları = kompresör devreye girmeden önceki pik)
    peaks_idx = []
    valleys_idx = []
    for i in range(1, len(temps) - 1):
        if temps[i] > temps[i-1] and temps[i] > temps[i+1]:
            peaks_idx.append(i)
        elif temps[i] < temps[i-1] and temps[i] < temps[i+1]:
            valleys_idx.append(i)

    # Ardışık pik aralarından döngü süresini hesapla
    cycle_durations = []
    for k in range(1, len(peaks_idx)):
        dur = (peaks_idx[k] - peaks_idx[k-1]) * 10  # dakika
        cycle_durations.append(dur)

    return {
        'n_peaks': len(peaks_idx),
        'n_valleys': len(valleys_idx),
        'cycle_durations': cycle_durations,
        'avg_cycle_min': round(statistics.mean(cycle_durations)) if cycle_durations else None,
        'min_cycle_min': min(cycle_durations) if cycle_durations else None,
        'max_cycle_min': max(cycle_durations) if cycle_durations else None,
        'temp_range': round(max(temps) - min(temps), 1),
    }


# ─── Episod tespiti (ardışık ihlalleri tek olay olarak gruplar) ─────────────
def group_episodes(records, test_fn, min_duration=2, max_gap=2):
    """
    test_fn(rec) → True olan ardışık kayıtları episod olarak gruplar.
    max_gap: episod içinde kaç ardışık 'False' kayda kadar köprü kurulsun.
    min_duration: episodun kaç kayıttan uzun olması gerektiği.
    """
    episodes = []
    in_ep = False
    ep_start = 0
    gap = 0
    for i, rec in enumerate(records):
        if test_fn(rec):
            if not in_ep:
                in_ep = True
                ep_start = i
            gap = 0
        else:
            if in_ep:
                gap += 1
                if gap > max_gap:
                    ep_end = i - gap
                    if ep_end - ep_start + 1 >= min_duration:
                        episodes.append((ep_start, ep_end))
                    in_ep = False
                    gap = 0
    if in_ep:
        ep_end = len(records) - 1
        if ep_end - ep_start + 1 >= min_duration:
            episodes.append((ep_start, ep_end))
    return episodes



def analyze_faults(records, device_type, stable_start, stable_end=None):
    cfg = DEVICE_CONFIG[device_type]
    faults   = []
    warnings = []
    info_events = []

    if stable_end is None:
        stable_end = len(records)

    if len(records) < 2:
        return faults, warnings, info_events

    # --- Soğuma süreci bilgisi ---
    if stable_start > 0:
        info_events.append({
            'severity': 'INFO',
            'icon': '❄️',
            'title': 'Başlangıç Isınması Atlandı',
            'description': (
                f"İlk {stable_start * 10} dakika ({stable_start} ölçüm) "
                f"başlangıç sıcaklığı ({records[0]['temperature']}°C) nedeniyle analizden çıkarıldı. "
                "Analiz soğutma başladığı andan itibarıyla yapıldı."
            ),
            'time': records[stable_start]['datetime_display'],
            'record_id': records[stable_start]['id'],
        })

    # --- Cihaz çıkarılma bilgisi ---
    if stable_end < len(records):
        removed_count = len(records) - stable_end
        info_events.append({
            'severity': 'INFO',
            'icon': '📤',
            'title': 'Son Bölüm Analizden Çıkarıldı',
            'description': (
                f"Son {removed_count * 10} dakika ({removed_count} ölçüm) "
                "cihazın dolap dışına çıkarıldığı süre olarak değerlendirildi "
                "ve arıza analizine dahil edilmedi."
            ),
            'time': records[stable_end]['datetime_display'],
            'record_id': records[stable_end]['id'],
        })

    stable = records[stable_start:stable_end]
    if not stable:
        return faults, warnings, info_events

    # --- Defrost tespiti ---
    defrosts = detect_defrost_events(stable, device_type)
    for d in defrosts:
        if d['is_defrost']:
            info_events.append({
                'severity': 'INFO',
                'icon': '🔆',
                'title': 'Defrost Döngüsü Tespit Edildi',
                'description': (
                    f"{d['duration_min']} dakikada {d['rise']}°C yükseliş "
                    f"(pik: {d['peak']}°C) — beklenen defrost davranışı. "
                    "Kompresör durup ısıtıcılar çalışmıştır."
                ),
                'time': d['start_time'],
                'record_id': d['start_rid'],
            })
        else:
            # Defrost değil ama uzun süreli artış — şüpheli
            if d['duration_min'] >= 50 and d['rise'] >= 4:
                warnings.append({
                    'severity': 'WARNING',
                    'icon': '📈',
                    'title': 'Uzun Süreli Isınma Eğilimi',
                    'description': (
                        f"{d['duration_min']} dakikada {d['rise']}°C sürekli artış "
                        f"(pik: {d['peak']}°C). "
                        "Fan arızası, hava dolaşım problemi veya kompresör verimsizliği olabilir."
                    ),
                    'time': d['start_time'],
                    'record_id': d['start_rid'],
                    'value': d['peak'],
                })

    # --- Üst sınır ihlali — episod bazlı (ardışık ihlaller tek olay) ---
    stable_temps = [r['temperature'] for r in stable]
    high_eps = group_episodes(stable, lambda r: r['temperature'] > cfg['normal_max'])
    if high_eps:
        total_over_min = sum((e - s + 1) * 10 for s, e in high_eps)
        peak_temp = max(
            stable[j]['temperature']
            for s, e in high_eps for j in range(s, e + 1)
        )
        s0, e0 = high_eps[0]
        pct = round(total_over_min / (len(stable) * 10) * 100)

        if len(high_eps) == 1:
            dur_min = (e0 - s0 + 1) * 10
            desc = (
                f"{stable[s0]['datetime_display']} – {stable[e0]['datetime_display']} "
                f"arasında {dur_min} dakika boyunca sıcaklık "
                f"{cfg['normal_max']}°C üstünde kaldı (en yüksek: {peak_temp:.1f}°C)."
            )
        else:
            desc = (
                f"Ölçüm süresinin %{pct}'inde ({total_over_min} dakika / "
                f"{len(high_eps)} ayrı periyot) sıcaklık "
                f"{cfg['normal_max']}°C üstünde seyretti (en yüksek: {peak_temp:.1f}°C). "
                f"İlk ihlal: {stable[s0]['datetime_display']}."
            )
        if device_type == 'FF':
            desc += " Kapı contası, soğutucu fanı ve gaz dolumunu kontrol edin."
            title = 'Yüksek Sıcaklık — Gıda Güvenliği Riski'
        else:
            desc += " Donmuş ürünler çözünüyor olabilir; gaz kaçağı veya kompresör arızası şüpheli."
            title = 'Dondurucu Sıcaklık Alarmı — Ürünler Tehlikede'
        faults.append({
            'severity': 'CRITICAL',
            'icon': '🔴',
            'title': title,
            'description': desc,
            'time': stable[s0]['datetime_display'],
            'record_id': stable[s0]['id'],
            'value': peak_temp,
        })

    # --- Alt sınır ihlali (FF: donma riski) — episod bazlı ---
    if device_type == 'FF':
        low_eps = group_episodes(stable, lambda r: r['temperature'] < cfg['normal_min'])
        if low_eps:
            min_temp = min(
                stable[j]['temperature']
                for s, e in low_eps for j in range(s, e + 1)
            )
            total_low_min = sum((e - s + 1) * 10 for s, e in low_eps)
            s0, e0 = low_eps[0]
            if len(low_eps) == 1:
                dur = (e0 - s0 + 1) * 10
                desc = (
                    f"{dur} dakika boyunca donma sınırı ({cfg['normal_min']}°C) altında kaldı "
                    f"(en düşük: {min_temp:.1f}°C). "
                    "Termostat set değeri çok düşük veya termistor arızalı olabilir (E3)."
                )
            else:
                desc = (
                    f"{len(low_eps)} ayrı periyotta toplam {total_low_min} dakika "
                    f"donma sınırının altında seyretti (en düşük: {min_temp:.1f}°C). "
                    "Termostat veya E3 sensör kontrolü önerilir."
                )
            warnings.append({
                'severity': 'WARNING',
                'icon': '🧊',
                'title': 'Donma Riski',
                'description': desc,
                'time': stable[s0]['datetime_display'],
                'record_id': stable[s0]['id'],
                'value': min_temp,
            })

    # --- Kapı açılması — özet ---
    door_idx = []
    for i in range(1, len(stable)):
        diff = stable[i]['temperature'] - stable[i - 1]['temperature']
        if diff > cfg['door_open_threshold']:
            if device_type == 'FRZ' and i >= 2:
                prev_diff = stable[i - 1]['temperature'] - stable[i - 2]['temperature']
                if prev_diff > 1.5:
                    continue
            door_idx.append(i)

    if len(door_idx) == 1:
        i = door_idx[0]
        diff = stable[i]['temperature'] - stable[i - 1]['temperature']
        warnings.append({
            'severity': 'WARNING',
            'icon': '🚪',
            'title': 'Kapı Açılması Tespit Edildi',
            'description': (
                f"10 dakikada {diff:.1f}°C ani artış "
                f"({stable[i-1]['temperature']}°C → {stable[i]['temperature']}°C). "
                "Kapı açılmış veya kapı contası sorunlu olabilir."
            ),
            'time': stable[i]['datetime_display'],
            'record_id': stable[i]['id'],
            'value': stable[i]['temperature'],
        })
    elif len(door_idx) > 1:
        diffs = [stable[i]['temperature'] - stable[i - 1]['temperature'] for i in door_idx]
        avg_diff = statistics.mean(diffs)
        warnings.append({
            'severity': 'WARNING',
            'icon': '🚪',
            'title': f'Kapı Açılması — {len(door_idx)} Olay',
            'description': (
                f"Ölçüm süresi boyunca {len(door_idx)} kez ani sıcaklık artışı gözlemlendi "
                f"(ortalama {avg_diff:.1f}°C/10 dk artış). "
                f"İlk olay: {stable[door_idx[0]]['datetime_display']}. "
                "Sık kapı açılması veya kapı contası sızdırmazlığı sorunlu olabilir."
            ),
            'time': stable[door_idx[0]]['datetime_display'],
            'record_id': stable[door_idx[0]]['id'],
        })

    # --- Evaporatör buzlanması tespiti ---
    if device_type == 'FRZ':
        very_cold = [t for t in stable_temps if t < -28]
        if len(very_cold) >= 3:
            faults.append({
                'severity': 'CRITICAL',
                'icon': '🧊',
                'title': 'Evaporatör Buzlanması Şüphesi',
                'description': (
                    f"-28°C altında {len(very_cold)} kayıt tespit edildi. "
                    "Evaporatör üzeri buz kaplanmış olabilir (E1/E4 hata kontrolü). "
                    "Manuel defrost veya defrost sensörü/ısıtıcı kontrolü önerilir."
                ),
                'time': stable[0]['datetime_display'],
                'record_id': stable[0]['id'],
                'value': min(stable_temps),
            })

    # --- Gaz kaçağı / sistem tıkanması şüphesi ---
    # Belge: "5-10 dk kompresör çalışırken soğuma yok ise → gaz kaçağı veya sistem tıkalı"
    # Biz 10 dk aralıklarla ölçüyoruz; trend analizi ile tespit edelim
    if len(stable_temps) >= 12:
        # Son 2 saatin ortalaması ile başlangıç ortalamasını karşılaştır
        first_avg = statistics.mean(stable_temps[:6])
        last_avg  = statistics.mean(stable_temps[-6:])
        drift = last_avg - first_avg

        if device_type == 'FRZ' and drift > 4.0 and last_avg > cfg['normal_max']:
            faults.append({
                'severity': 'CRITICAL',
                'icon': '💨',
                'title': 'Sürekli Isınma Eğilimi — Gaz Kaçağı / Tıkanma Şüphesi',
                'description': (
                    f"Ölçüm süresi boyunca ortalama {drift:.1f}°C ısınma trendi tespit edildi "
                    f"(başlangıç ort.: {first_avg:.1f}°C → son ort.: {last_avg:.1f}°C). "
                    "Kompresör çalışırken evap sensöründe soğuma yoksa gaz kaçağı veya sistem tıkanması. "
                    "Servis testi: kompresör çalıştır, 5-10 dk evap sensörünü izle."
                ),
                'time': stable[-6]['datetime_display'],
                'record_id': stable[-6]['id'],
                'value': last_avg,
            })
        elif device_type == 'FF' and drift > 3.0 and last_avg > cfg['normal_max']:
            faults.append({
                'severity': 'CRITICAL',
                'icon': '💨',
                'title': 'Sürekli Isınma Eğilimi — Soğutma Yetersizliği',
                'description': (
                    f"Ölçüm süresi boyunca {drift:.1f}°C artış eğilimi "
                    f"({first_avg:.1f}°C → {last_avg:.1f}°C). "
                    "Fan arızası, gaz kaçağı veya kondanser kirliliği şüphesi. "
                    "E2/E3 hata kodu kontrolü ve servis testi önerilir."
                ),
                'time': stable[-6]['datetime_display'],
                'record_id': stable[-6]['id'],
                'value': last_avg,
            })

    # --- Kısa döngü (short cycling) tespiti ---
    # Kompresör min 5 dk çalışmalı; 10 dk aralıklı ölçümde 1 okumadan kısa döngü anlaşılamaz
    # Ancak pik-vadi mesafesi çok kısa ise şüphelidir
    cycle_info = analyze_cycles(stable, 0)
    if isinstance(cycle_info, dict):
        if cycle_info.get('min_cycle_min') and cycle_info['min_cycle_min'] < 20:
            warnings.append({
                'severity': 'WARNING',
                'icon': '⚡',
                'title': 'Kısa Çevrim Şüphesi',
                'description': (
                    f"Minimum döngü süresi {cycle_info['min_cycle_min']} dakika — "
                    "kompresör çok sık açılıp kapanıyor olabilir (min. 5 dk çalışmalı, 6 dk durmalı). "
                    "Termostat kalibrasyonu veya kontrol kartı kontrolü önerilir."
                ),
                'time': stable[0]['datetime_display'],
                'record_id': stable[0]['id'],
            })

        if cycle_info.get('avg_cycle_min') and cycle_info['avg_cycle_min'] > 120:
            warnings.append({
                'severity': 'WARNING',
                'icon': '⏱️',
                'title': 'Uzun Döngü Süresi',
                'description': (
                    f"Ortalama döngü süresi {cycle_info['avg_cycle_min']} dakika — "
                    "normalden uzun. Fan verimliliği düşmüş, kondanser kirli veya "
                    "ortam sıcaklığı çok yüksek olabilir."
                ),
                'time': stable[0]['datetime_display'],
                'record_id': stable[0]['id'],
            })

    return faults, warnings, info_events


# ─── İstatistikler ──────────────────────────────────────────────────────────
def calculate_stats(records, stable_start, stable_end=None):
    if stable_end is None:
        stable_end = len(records)
    all_temps    = [r['temperature'] for r in records]
    stable_temps = [r['temperature'] for r in records[stable_start:stable_end]] or all_temps
    cycle_info   = analyze_cycles(records[stable_start:stable_end], 0)

    return {
        'all_min':        min(all_temps),
        'all_max':        max(all_temps),
        'stable_min':     min(stable_temps),
        'stable_max':     max(stable_temps),
        'stable_avg':     round(statistics.mean(stable_temps), 2),
        'stable_stdev':   round(statistics.stdev(stable_temps) if len(stable_temps) > 1 else 0, 2),
        'total_readings': len(records),
        'stable_readings':len(stable_temps),
        'peaks_detected': cycle_info.get('n_peaks', 0) if isinstance(cycle_info, dict) else 0,
        'avg_cycle_min':  cycle_info.get('avg_cycle_min') if isinstance(cycle_info, dict) else None,
        'min_cycle_min':  cycle_info.get('min_cycle_min') if isinstance(cycle_info, dict) else None,
        'max_cycle_min':  cycle_info.get('max_cycle_min') if isinstance(cycle_info, dict) else None,
        'temp_range':     cycle_info.get('temp_range') if isinstance(cycle_info, dict) else None,
    }


# ─── Genel değerlendirme ────────────────────────────────────────────────────
def overall_assessment(faults, warnings, device_type, stats):
    cfg      = DEVICE_CONFIG[device_type]
    in_range = cfg['normal_min'] <= stats['stable_avg'] <= cfg['normal_max']

    if faults:
        return {
            'status': 'CRITICAL',
            'label': 'KRİTİK',
            'color': '#e74c3c',
            'message': f"{len(faults)} kritik arıza tespit edildi. Acil servis müdahalesi gerekli.",
        }
    if warnings:
        return {
            'status': 'WARNING',
            'label': 'UYARI',
            'color': '#f39c12',
            'message': f"{len(warnings)} uyarı mevcut. Servis kontrolü önerilir.",
        }
    if not in_range:
        return {
            'status': 'WARNING',
            'label': 'UYARI',
            'color': '#f39c12',
            'message': (
                f"Ortalama sıcaklık ({stats['stable_avg']}°C) "
                f"önerilen aralık ({cfg['normal_min']}–{cfg['normal_max']}°C) dışında."
            ),
        }
    return {
        'status': 'OK',
        'label': 'NORMAL',
        'color': '#27ae60',
        'message': "Cihaz normal çalışma parametreleri içinde çalışıyor.",
    }


# ─── Teşhis önerileri ───────────────────────────────────────────────────────
def build_recommendations(faults, warnings, device_type, stats):
    recs = []
    cfg  = DEVICE_CONFIG[device_type]

    # Sıcaklık çok yüksek
    if any(f['title'].endswith('Alarmı') or 'Isınma' in f['title'] for f in faults):
        if device_type == 'FRZ':
            recs.append({
                'step': 1,
                'text': 'Servis testine girin → Kompresörü manuel çalıştırın → '
                        '5-10 dakika evaporatör sensörünü izleyin. '
                        'Soğuma yoksa gaz kaçağı veya sistem tıkalı.',
                'code': 'E1 / E4',
            })
            recs.append({
                'step': 2,
                'text': 'Evaporatör sensörü -30°C altı gösteriyorsa evap üstü buz kaplı olabilir. '
                        'Manuel defrost yapın.',
                'code': 'E1',
            })
            recs.append({
                'step': 3,
                'text': 'Kondanser fanı çalışıyor mu? Fan dönmüyorsa veya yavaşsa kontrol edin.',
                'code': 'E15',
            })
        else:
            recs.append({
                'step': 1,
                'text': 'Kapı contasını kontrol edin (sıcak su ile muayene). '
                        'Soğutucu bölme fanı çalışıyor mu?',
                'code': 'E3 / E16',
            })
            recs.append({
                'step': 2,
                'text': 'Servis testinde soğutucu evap sensörünü okuyun. '
                        'Değer beklenen aralıkta değilse sensör değiştirin.',
                'code': 'E2 / E3',
            })

    # Kapı açılması sık tekrarlanıyorsa
    door_warns = [w for w in warnings if 'Kapı' in w['title']]
    if len(door_warns) >= 3:
        recs.append({
            'step': len(recs) + 1,
            'text': f"{len(door_warns)} kapı açılma olayı tespit edildi. "
                    "Kapı contasını ve kapı switch sensörünü kontrol edin.",
            'code': '—',
        })

    # Donma riski
    if any('Donma' in w['title'] for w in warnings):
        recs.append({
            'step': len(recs) + 1,
            'text': 'Termistor direncini multimetre ile ölçün (5K – 200K arasında olmalı). '
                    'Değer dışındaysa sensörü değiştirin.',
            'code': 'E3',
        })

    # Evap buzlanması
    if any('Buzlanma' in f['title'] for f in faults):
        recs.append({
            'step': len(recs) + 1,
            'text': 'Defrost ısıtıcısının direncini ölçün. Termiği kontrol edin. '
                    'E4 kodu görünüyorsa defrost sistem hatası akış diyagramını takip edin.',
            'code': 'E4 / E1',
        })

    if not recs:
        recs.append({
            'step': 1,
            'text': 'Olağandışı durum tespit edilmedi. '
                    'Düzenli bakım: kondanser temizliği (6 ayda 1), kapı contası kontrolü.',
            'code': '—',
        })

    return recs


# ─── Flask Route'ları ────────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/analyze', methods=['POST'])
def analyze():
    if 'file' not in request.files:
        return jsonify({'error': 'Dosya seçilmedi'}), 400

    f = request.files['file']
    if not f.filename.lower().endswith('.pdf'):
        return jsonify({'error': 'Yalnızca PDF dosyaları kabul edilir'}), 400

    file_bytes = f.read()
    if not file_bytes:
        return jsonify({'error': 'Dosya boş'}), 400

    try:
        header_info, records = parse_testo_pdf(file_bytes)
    except Exception as e:
        return jsonify({'error': f'PDF okunamadı: {str(e)}'}), 400

    if not records:
        return jsonify({'error': 'PDF içinde ölçüm verisi bulunamadı'}), 400

    device_type  = detect_device_type(records)
    stable_start = find_stable_start(records, device_type)
    stable_end   = find_stable_end(records, device_type)
    faults, warnings, info_events = analyze_faults(records, device_type, stable_start, stable_end)
    stats        = calculate_stats(records, stable_start, stable_end)
    assessment   = overall_assessment(faults, warnings, device_type, stats)
    recs         = build_recommendations(faults, warnings, device_type, stats)

    return jsonify({
        'header':        header_info,
        'records':       records,
        'device_type':   device_type,
        'device_config': DEVICE_CONFIG[device_type],
        'stable_start':  stable_start,
        'stable_end':    stable_end,
        'stats':         stats,
        'faults':        faults,
        'warnings':      warnings,
        'info_events':   info_events,
        'assessment':    assessment,
        'recommendations': recs,
        'error_codes':   ERROR_CODES,
    })


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
