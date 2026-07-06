# Terrain Moonrise Web App

Simple iPhone-friendly web app for the terrain moonrise script.

## Run

```powershell
pip install -r requirements.txt
python app.py
```

Open `http://localhost:5000` on the computer running the app.

To use it from an iPhone on the same Wi-Fi network, open:

```text
http://YOUR-COMPUTER-IP:5000
```

For local development, the app reads kernels and the horizon CSV from:

```text
C:\Users\jonat\OneDrive\Documents\Random (not important)\Moon
```

To point it at a copied data folder instead:

```powershell
$env:MOON_DATA_DIR = "C:\path\to\moon\data"
python app.py
```

## Use Away From Home

To work when your computer is off or the phone is not on your Wi-Fi, this app
needs to run on an internet-hosted server. The iPhone will only load the web
page; the server will do the SPICE calculation.

Copy these files into `data/` before deploying:

```text
pck00011.tpc
latest_leapseconds.tls
earth_1962_250826_2125_combined.bpc
de440s.bsp
terrain_horizon_profile_geodesic.csv
```

The app is ready for a Docker-based host using the included `Dockerfile`.
Production hosts should run:

```text
gunicorn --bind 0.0.0.0:5000 --workers 1 --threads 4 --timeout 120 app:app
```

After it is deployed, open the HTTPS URL on the iPhone and use Add to Home
Screen. It will behave like a small app, but it will still need internet access.
