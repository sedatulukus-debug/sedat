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
    for i, r in enumerate(records):
        if r['temperature'] < threshold:
            return max(0, i)
    return 0


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


# ─── Ana arıza analizi ──────────────────────────────────────────────────────
def analyze_faults(records, device_type, stable_start):
    cfg = DEVICE_CONFIG[device_type]
    faults   = []
    warnings = []
    info_events = []

    if len(records) < 2:
        return faults, warnings, info_events

    # --- Soğuma süreci bilgisi ---
    if stable_start > 0:
        info_events.append({
            'severity': 'INFO',
            'icon': '❄️',
            'title': 'Soğuma Süreci Tamamlandı',
            'description': (
                f"Cihaz {records[0]['temperature']}°C başlangıç sıcaklığından "
                f"normal çalışma aralığına {stable_start * 10} dakikada ulaştı."
            ),
            'time': records[stable_start]['datetime_display'],
            'record_id': records[stable_start]['id'],
        })

    stable = records[stable_start:]
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

    # --- Sıcaklık sınır kontrolleri ---
    last_high_id = -99
    last_low_id  = -99
    last_door_id = -99

    for i, rec in enumerate(stable):
        temp = rec['temperature']
        rid  = rec['id']
        dt   = rec['datetime_display']

        # Üst sınır ihlali
        if temp > cfg['normal_max'] and (rid - last_high_id) > 3:
            last_high_id = rid
            title = ('Yüksek Sıcaklık Alarmı' if device_type == 'FF'
                     else 'Dondurucu Sıcaklık Alarmı — Ürünler Tehlikede')
            desc = (
                f"Sıcaklık {temp}°C — izin verilen üst sınır {cfg['normal_max']}°C aşıldı."
            )
            if device_type == 'FF':
                desc += " Gıda güvenliği riski. Kontrol edin: kapı contası, fan çalışması, gaz dolumu."
            else:
                desc += " Donmuş ürünler çözünüyor olabilir. Gaz kaçağı veya kompresör arızası şüpheli."
            faults.append({
                'severity': 'CRITICAL',
                'icon': '🔴',
                'title': title,
                'description': desc,
                'time': dt,
                'record_id': rid,
                'value': temp,
            })

        # Alt sınır ihlali (FF için donma riski)
        if device_type == 'FF' and temp < cfg['normal_min'] and (rid - last_low_id) > 3:
            last_low_id = rid
            warnings.append({
                'severity': 'WARNING',
                'icon': '🧊',
                'title': 'Donma Riski',
                'description': (
                    f"Sıcaklık {temp}°C — donma sınırı ({cfg['normal_min']}°C) altında. "
                    "Termostat set değeri çok düşük veya termistor arızalı olabilir (E3 kontrolü)."
                ),
                'time': dt,
                'record_id': rid,
                'value': temp,
            })

        # Kapı açılması tespiti
        if i > 0:
            prev  = stable[i - 1]
            diff  = temp - prev['temperature']
            prev2 = stable[i - 2]['temperature'] if i >= 2 else None

            if device_type == 'FF':
                if diff > cfg['door_open_threshold'] and (rid - last_door_id) > 3:
                    last_door_id = rid
                    warnings.append({
                        'severity': 'WARNING',
                        'icon': '🚪',
                        'title': 'Kapı Açılması Tespit Edildi',
                        'description': (
                            f"10 dakikada {diff:.1f}°C ani artış "
                            f"({prev['temperature']}°C → {temp}°C). "
                            "Kapı açılmış veya kapı contası sorunlu olabilir."
                        ),
                        'time': dt,
                        'record_id': rid,
                        'value': temp,
                    })
            else:  # FRZ
                if diff > cfg['door_open_threshold'] and (rid - last_door_id) > 3:
                    is_gradual = (prev2 is not None and
                                  (prev['temperature'] - prev2) > 1.5)
                    if not is_gradual:
                        last_door_id = rid
                        warnings.append({
                            'severity': 'WARNING',
                            'icon': '🚪',
                            'title': 'Kapı Açılması / Ani Sıcaklık Artışı',
                            'description': (
                                f"10 dakikada {diff:.1f}°C ani artış "
                                f"({prev['temperature']}°C → {temp}°C). "
                                "Kapı açılmış veya dış ısı etkisi olabilir. "
                                "Sürekli tekrar ediyorsa kapı contasını kontrol edin."
                            ),
                            'time': dt,
                            'record_id': rid,
                            'value': temp,
                        })

    # --- Evaporatör buzlanması tespiti ---
    # Teknik belge: "-30°C civarı değerler → evap üzeri buz kaplı olabilir"
    stable_temps = [r['temperature'] for r in stable]
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
    cycle_info = analyze_cycles(records, stable_start)
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
def calculate_stats(records, stable_start):
    all_temps    = [r['temperature'] for r in records]
    stable_temps = [r['temperature'] for r in records[stable_start:]] or all_temps
    cycle_info   = analyze_cycles(records, stable_start)

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
    faults, warnings, info_events = analyze_faults(records, device_type, stable_start)
    stats        = calculate_stats(records, stable_start)
    assessment   = overall_assessment(faults, warnings, device_type, stats)
    recs         = build_recommendations(faults, warnings, device_type, stats)

    return jsonify({
        'header':        header_info,
        'records':       records,
        'device_type':   device_type,
        'device_config': DEVICE_CONFIG[device_type],
        'stable_start':  stable_start,
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
