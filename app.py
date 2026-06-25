import io
import re
import statistics
from datetime import datetime
from flask import Flask, render_template, request, jsonify
import pdfplumber

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB

DEVICE_CONFIG = {
    'FF': {
        'name': 'Buzdolabı / Soğutucu',
        'normal_min': 0.0,
        'normal_max': 8.0,
        'ideal_min': 2.0,
        'ideal_max': 5.0,
        'door_open_threshold': 2.5,
        'cooldown_threshold': 8.0,
        'unit': '°C',
        'color': '#3498db',
        'bg_color': 'rgba(52, 152, 219, 0.15)',
    },
    'FRZ': {
        'name': 'Derin Dondurucu',
        'normal_min': -25.0,
        'normal_max': -12.0,
        'ideal_min': -22.0,
        'ideal_max': -15.0,
        'door_open_threshold': 3.5,
        'cooldown_threshold': -12.0,
        'unit': '°C',
        'color': '#8e44ad',
        'bg_color': 'rgba(142, 68, 173, 0.15)',
    },
}


def parse_testo_pdf(file_bytes):
    records = []
    header_info = {}
    channel_name = None
    report_timestamp = None

    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            # Extract raw text for metadata (page header/footer)
            raw_text = page.extract_text() or ""

            # Report generation timestamp from page footer "DD.MM.YYYY HH:MM:SS"
            if report_timestamp is None:
                ts_m = re.search(r'(\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}:\d{2})', raw_text)
                if ts_m:
                    report_timestamp = ts_m.group(1)

            # Extract data table
            tables = page.extract_tables()
            for table in tables:
                if not table or len(table) < 2:
                    continue
                # Identify header row: [ID, Tarih/Saat, CHANNEL_NAME]
                header_row = table[0]
                if not header_row or len(header_row) < 3:
                    continue
                col0 = str(header_row[0] or '').strip().upper()
                if col0 != 'ID':
                    continue
                # Extract channel name once
                if channel_name is None and header_row[2]:
                    channel_name = str(header_row[2]).strip()

                # Parse data rows
                for row in table[1:]:
                    if not row or len(row) < 3:
                        continue
                    id_str  = str(row[0] or '').strip()
                    dt_str  = str(row[1] or '').strip()
                    tmp_str = str(row[2] or '').strip()
                    if not id_str.isdigit():
                        continue
                    tmp_str = tmp_str.replace(',', '.')
                    try:
                        record_id = int(id_str)
                        temp = float(tmp_str)
                        dt = datetime.strptime(dt_str, '%d.%m.%Y %H:%M:%S')
                        records.append({
                            'id': record_id,
                            'datetime': dt.isoformat(),
                            'datetime_display': dt_str,
                            'temperature': temp,
                            'timestamp': int(dt.timestamp() * 1000),
                        })
                    except (ValueError, TypeError):
                        pass

    records.sort(key=lambda x: x['id'])
    # Remove duplicates (same id from overlapping table headers)
    seen = set()
    unique_records = []
    for r in records:
        if r['id'] not in seen:
            seen.add(r['id'])
            unique_records.append(r)

    if unique_records:
        header_info['start_time'] = unique_records[0]['datetime_display']
        header_info['end_time']   = unique_records[-1]['datetime_display']
        header_info['total_readings'] = len(unique_records)
    if channel_name:
        header_info['channel_name'] = channel_name
    if report_timestamp:
        header_info['report_timestamp'] = report_timestamp

    return header_info, unique_records


def detect_device_type(records):
    if not records:
        return 'FF'
    # Use readings after initial 5 to avoid cool-down bias
    stable = records[5:] if len(records) > 5 else records
    avg = statistics.mean(r['temperature'] for r in stable)
    return 'FRZ' if avg < -5 else 'FF'


def find_stable_start(records, device_type):
    threshold = DEVICE_CONFIG[device_type]['cooldown_threshold']
    for i, r in enumerate(records):
        if device_type == 'FRZ':
            if r['temperature'] < threshold:
                return max(0, i)
        else:
            if r['temperature'] < threshold:
                return max(0, i)
    return 0


def analyze_faults(records, device_type, stable_start):
    config = DEVICE_CONFIG[device_type]
    faults = []
    warnings = []
    info_events = []

    if len(records) < 2:
        return faults, warnings, info_events

    # Cool-down info
    if stable_start > 0:
        minutes = stable_start * 10
        info_events.append({
            'severity': 'INFO',
            'icon': '❄️',
            'title': 'Soğuma Süreci Tamamlandı',
            'description': (
                f"Cihaz, {records[0]['temperature']}°C başlangıç sıcaklığından "
                f"normal çalışma aralığına {minutes} dakikada ulaştı."
            ),
            'time': records[stable_start]['datetime_display'],
            'record_id': records[stable_start]['id'],
        })

    stable_records = records[stable_start:]

    # Duplicate tracking to avoid repeat alerts for sustained high temp
    last_high_temp_id = -99
    last_door_open_id = -99

    for i, rec in enumerate(stable_records):
        temp = rec['temperature']
        rid = rec['id']
        dt = rec['datetime_display']

        # Upper limit breach
        if temp > config['normal_max'] and (rid - last_high_temp_id) > 2:
            last_high_temp_id = rid
            faults.append({
                'severity': 'CRITICAL',
                'icon': '🔴',
                'title': 'Yüksek Sıcaklık Alarmı',
                'description': (
                    f"Sıcaklık {temp}°C — güvenli üst sınır "
                    f"{config['normal_max']}°C aşıldı."
                ),
                'time': dt,
                'record_id': rid,
                'value': temp,
            })

        # Freezing risk for FF
        if device_type == 'FF' and temp < config['normal_min']:
            warnings.append({
                'severity': 'WARNING',
                'icon': '🧊',
                'title': 'Donma Riski',
                'description': f"Sıcaklık {temp}°C — donma eşiği ({config['normal_min']}°C) altında.",
                'time': dt,
                'record_id': rid,
                'value': temp,
            })

        # Too high for FRZ (excluding initial period already handled)
        if device_type == 'FRZ' and temp > config['normal_max'] and (rid - last_high_temp_id) > 3:
            last_high_temp_id = rid
            faults.append({
                'severity': 'CRITICAL',
                'icon': '🔴',
                'title': 'Dondurucu Sıcaklık Alarmı',
                'description': (
                    f"Sıcaklık {temp}°C — -12°C güvenli sınırını aştı. "
                    "Ürünler çözünme riski altında."
                ),
                'time': dt,
                'record_id': rid,
                'value': temp,
            })

        # Door open detection (sudden rise in one interval)
        if i > 0:
            prev = stable_records[i - 1]
            diff = temp - prev['temperature']
            prev2_temp = stable_records[i - 2]['temperature'] if i >= 2 else None

            if device_type == 'FF':
                if diff > config['door_open_threshold'] and (rid - last_door_open_id) > 3:
                    last_door_open_id = rid
                    warnings.append({
                        'severity': 'WARNING',
                        'icon': '🚪',
                        'title': 'Kapı Açılması Tespit Edildi',
                        'description': (
                            f"10 dakikada {diff:.1f}°C ani sıcaklık artışı "
                            f"({prev['temperature']}°C → {temp}°C). Kapı açılmış olabilir."
                        ),
                        'time': dt,
                        'record_id': rid,
                        'value': temp,
                    })
            else:  # FRZ
                # Sudden spike (not a gradual defrost ramp)
                if diff > config['door_open_threshold'] and (rid - last_door_open_id) > 3:
                    # Confirm: check if previous reading also rose rapidly
                    is_gradual = prev2_temp is not None and (prev['temperature'] - prev2_temp) > 1.5
                    if not is_gradual:
                        last_door_open_id = rid
                        warnings.append({
                            'severity': 'WARNING',
                            'icon': '🚪',
                            'title': 'Kapı Açılması / Ani Sıcaklık Artışı',
                            'description': (
                                f"10 dakikada {diff:.1f}°C ani artış "
                                f"({prev['temperature']}°C → {temp}°C). "
                                "Kapı açılmış veya harici ısı kaynağı etkisi olabilir."
                            ),
                            'time': dt,
                            'record_id': rid,
                            'value': temp,
                        })

    # Compressor stress: 6+ consecutive rising readings with total rise > 4°C
    # For FRZ this is only flagged if temp EXCEEDS normal_max (thermostat cycling is normal)
    rising_streak = 0
    for i in range(1, len(stable_records)):
        curr_t = stable_records[i]['temperature']
        prev_t = stable_records[i - 1]['temperature']
        if curr_t > prev_t:
            rising_streak += 1
            if rising_streak == 6:
                rise = curr_t - stable_records[i - 6]['temperature']
                if rise > 4.0:
                    # For FRZ, only warn if temperature is approaching or above the critical threshold
                    if device_type == 'FRZ' and curr_t < config['normal_max']:
                        pass  # Normal defrost/thermostat cycle — skip
                    else:
                        warnings.append({
                            'severity': 'WARNING',
                            'icon': '⚙️',
                            'title': 'Uzun Süreli Sıcaklık Artışı',
                            'description': (
                                f"60 dakika boyunca {rise:.1f}°C kesintisiz artış "
                                f"({stable_records[i-6]['temperature']}°C → {curr_t}°C). "
                                "Kompresör aşırı yüklenmiş veya soğutma kapasitesi yetersiz olabilir."
                            ),
                            'time': stable_records[i]['datetime_display'],
                            'record_id': stable_records[i]['id'],
                            'value': curr_t,
                        })
        else:
            rising_streak = 0

    return faults, warnings, info_events


def calculate_stats(records, stable_start):
    all_temps = [r['temperature'] for r in records]
    stable_temps = [r['temperature'] for r in records[stable_start:]] or all_temps

    # Cycle detection (peaks/valleys in stable period)
    peaks = 0
    for i in range(1, len(stable_temps) - 1):
        if stable_temps[i] > stable_temps[i - 1] and stable_temps[i] > stable_temps[i + 1]:
            peaks += 1

    avg_cycle_min = None
    if peaks > 1 and len(stable_temps) > 2:
        total_min = len(stable_temps) * 10
        avg_cycle_min = round(total_min / peaks)

    return {
        'all_min': min(all_temps),
        'all_max': max(all_temps),
        'stable_min': min(stable_temps),
        'stable_max': max(stable_temps),
        'stable_avg': round(statistics.mean(stable_temps), 2),
        'stable_stdev': round(statistics.stdev(stable_temps) if len(stable_temps) > 1 else 0, 2),
        'total_readings': len(records),
        'stable_readings': len(stable_temps),
        'peaks_detected': peaks,
        'avg_cycle_min': avg_cycle_min,
    }


def overall_assessment(faults, warnings, device_type, stats):
    config = DEVICE_CONFIG[device_type]
    in_range = config['normal_min'] <= stats['stable_avg'] <= config['normal_max']

    if faults:
        return {
            'status': 'CRITICAL',
            'label': 'KRİTİK',
            'color': '#e74c3c',
            'message': f"{len(faults)} kritik arıza tespit edildi. Acil müdahale gerekli.",
        }
    if warnings:
        return {
            'status': 'WARNING',
            'label': 'UYARI',
            'color': '#f39c12',
            'message': f"{len(warnings)} uyarı mevcut. Kontrol önerilir.",
        }
    if not in_range:
        return {
            'status': 'WARNING',
            'label': 'UYARI',
            'color': '#f39c12',
            'message': f"Ortalama sıcaklık ({stats['stable_avg']}°C) önerilen aralık dışında.",
        }
    return {
        'status': 'OK',
        'label': 'NORMAL',
        'color': '#27ae60',
        'message': "Cihaz normal çalışma parametreleri içinde.",
    }


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

    device_type = detect_device_type(records)
    stable_start = find_stable_start(records, device_type)
    faults, warnings, info_events = analyze_faults(records, device_type, stable_start)
    stats = calculate_stats(records, stable_start)
    assessment = overall_assessment(faults, warnings, device_type, stats)

    return jsonify({
        'header': header_info,
        'records': records,
        'device_type': device_type,
        'device_config': DEVICE_CONFIG[device_type],
        'stable_start': stable_start,
        'stats': stats,
        'faults': faults,
        'warnings': warnings,
        'info_events': info_events,
        'assessment': assessment,
    })


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
