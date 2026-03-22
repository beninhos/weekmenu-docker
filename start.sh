#!/bin/sh
# Start de AH login proxy op de achtergrond
/usr/local/bin/ah-login-proxy >/tmp/ah-proxy.log 2>&1 &

# Start Flask
exec python app.py
