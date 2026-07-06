from flask import Flask, jsonify, request, send_from_directory

from moonrise_core import MoonriseError, compute_moonrise


app = Flask(__name__, static_folder="static", static_url_path="")


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/moonrise")
def moonrise():
    date_string = request.args.get("date", "").strip()
    if not date_string:
        return jsonify({"error": "A date query parameter is required."}), 400

    try:
        return jsonify(compute_moonrise(date_string))
    except MoonriseError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        app.logger.exception("Moonrise calculation failed")
        return jsonify({"error": f"Moonrise calculation failed: {exc}"}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
