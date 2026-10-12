#!/bin/sh
# De AH login-proxy hoort bij de connector; zonder connector is er geen proxy.
if [ -f /app/weekmenu_ah/proxy.py ]; then
    python /app/weekmenu_ah/proxy.py >/tmp/ah-proxy.log 2>&1 &
fi

# Start Flask
exec python app.py
