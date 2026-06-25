#!/bin/bash
echo ""
echo " ============================================"
echo "  Testo 174T Olcum Analiz Sistemi - Kurulum"
echo " ============================================"
echo ""

# Python kontrolü
if ! command -v python3 &>/dev/null; then
    echo " HATA: python3 bulunamadi. Lutfen Python 3.9+ kurun."
    exit 1
fi
echo " Python bulundu: $(python3 --version)"

# Sanal ortam
echo " [1/3] Sanal ortam olusturuluyor..."
python3 -m venv venv

# Paketler
echo " [2/3] Paketler yukleniyor..."
venv/bin/pip install --upgrade pip --quiet
venv/bin/pip install flask pdfplumber --quiet

# Klasör
echo " [3/3] Klasor yapisi hazirlaniyor..."
mkdir -p knowledge_base

# start.sh yetkisi
chmod +x start.sh 2>/dev/null

echo ""
echo " ============================================"
echo "  Kurulum tamamlandi!"
echo "  Baslatmak icin: ./start.sh"
echo " ============================================"
echo ""
