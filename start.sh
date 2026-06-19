#!/bin/sh
# Start de AH login-proxy (Python + curl_cffi) op de achtergrond
python /app/ah-proxy/proxy.py >/tmp/ah-proxy.log 2>&1 &

# Start Flask
exec python app.py
