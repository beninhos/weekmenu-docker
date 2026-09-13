from weekmenu import create_app

app = create_app()

if __name__ == '__main__':
    # debug=True houdt de Werkzeug PIN-console aan voor deze beta-versie, zodat
    # een crash op de live-instantie meteen leesbaar is. use_reloader=False is
    # cruciaal: de reloader-fork breekt de DumpJob-supervisor (elke reload
    # markeert net-gestarte jobs als 'error') en geeft de threading.Lock in
    # services/ah.py z'n eigen exemplaar per worker, waardoor de token-refresh-
    # race die die lock juist moest afvangen alsnog kan gebeuren.
    app.run(host='0.0.0.0', port=5001, debug=True, use_reloader=False)
