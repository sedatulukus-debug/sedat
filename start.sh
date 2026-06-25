#!/bin/bash
if [ ! -f "venv/bin/python" ]; then
    echo " HATA: Kurulum yapilmamis. Once ./install.sh calistirin."
    exit 1
fi

echo ""
echo " Testo 174T - Analiz Sistemi baslatiliyor..."
echo " Adres: http://127.0.0.1:5000"
echo " Kapatmak icin CTRL+C"
echo ""

# Tarayıcıyı aç (arka planda, 1 sn sonra)
(sleep 1 && \
  if command -v xdg-open &>/dev/null; then xdg-open http://127.0.0.1:5000; \
  elif command -v open &>/dev/null;    then open http://127.0.0.1:5000; fi) &

venv/bin/python app.py
