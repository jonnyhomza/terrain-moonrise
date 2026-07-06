import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import spiceypy as sp


class MoonriseError(ValueError):
    pass


APP_DIR = Path(__file__).resolve().parent
PROJECT_DATA_DIR = APP_DIR / "data"
WINDOWS_MOON_DATA_DIR = Path(
    r"C:\Users\jonat\OneDrive\Documents\Random (not important)\Moon"
)

KERNELS = [
    "pck00011.tpc",
    "latest_leapseconds.tls",
    "earth_1962_250826_2125_combined.bpc",
    "de440s.bsp",
]
HORIZON_FILENAME = "terrain_horizon_profile_geodesic.csv"


def data_dir_has_required_files(path):
    required_names = [*KERNELS, HORIZON_FILENAME]
    return all((path / name).exists() for name in required_names)


DEFAULT_MOON_DATA_DIR = (
    PROJECT_DATA_DIR
    if data_dir_has_required_files(PROJECT_DATA_DIR)
    else WINDOWS_MOON_DATA_DIR
)
MOON_DATA_DIR = Path(os.environ.get("MOON_DATA_DIR", DEFAULT_MOON_DATA_DIR))
HORIZON_CSV = MOON_DATA_DIR / HORIZON_FILENAME
HORIZON_AZIMUTH_CORRECTION_DEG = 0.0

LATITUDE_DEG = 61.111922
LONGITUDE_DEG = -149.6889729705
ALTITUDE_KM = 0.006
LOCAL_TIMEZONE = "America/Anchorage"

STEP_MINUTES = 1
PLOT_HOURS_AROUND_RISE = 1.0
HORIZON_PLOT_AZ_MIN_DEG = 0.0
HORIZON_PLOT_AZ_MAX_DEG = 180.0
FILTER_RISES_TO_PLOT_AZIMUTH_RANGE = False

TARGET = "MOON"
OBSERVER = "EARTH"
FRAME = "ITRF93"
ABCORR = "LT+S"

_kernel_lock = Lock()
_kernels_loaded = False
_horizon_cache = None


def _require_file(path):
    if not path.exists():
        raise MoonriseError(f"Required file was not found: {path}")


def load_spice_kernels():
    global _kernels_loaded
    if _kernels_loaded:
        return

    with _kernel_lock:
        if _kernels_loaded:
            return

        for kernel in KERNELS:
            kernel_path = MOON_DATA_DIR / kernel
            _require_file(kernel_path)
            sp.furnsh(str(kernel_path))

        _kernels_loaded = True


def get_local_tz():
    try:
        return ZoneInfo(LOCAL_TIMEZONE)
    except Exception as exc:
        raise MoonriseError(
            f"Could not load timezone {LOCAL_TIMEZONE!r}. "
            "On Windows, run: pip install tzdata"
        ) from exc


def local_day_bounds(date_string):
    try:
        entered_date = datetime.fromisoformat(date_string)
    except ValueError as exc:
        raise MoonriseError("Date must use YYYY-MM-DD format.") from exc

    if entered_date.time() != datetime.min.time():
        raise MoonriseError("Date must not include a time. Use YYYY-MM-DD.")

    local_tz = get_local_tz()
    local_start = entered_date.replace(tzinfo=local_tz)
    local_end = local_start + timedelta(days=1)
    return local_start, local_end


def spice_utc_string(dt_utc):
    return dt_utc.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def build_time_grid_for_local_day(date_string, step_minutes=1):
    local_start, local_end = local_day_bounds(date_string)
    start_utc = local_start.astimezone(timezone.utc)
    end_utc = local_end.astimezone(timezone.utc)

    step = timedelta(minutes=step_minutes)
    times_utc = []
    t = start_utc
    while t <= end_utc:
        times_utc.append(t)
        t += step

    return times_utc


def observer_position_and_neu_matrix(latitude_deg, longitude_deg, altitude_km):
    latitude_rad = np.deg2rad(latitude_deg)
    longitude_rad = np.deg2rad(longitude_deg)

    radii = sp.bodvrd("EARTH", "RADII", 3)[1]
    equ_radius = radii[0]
    pol_radius = radii[2]
    flattening = (equ_radius - pol_radius) / equ_radius

    obs_pos = sp.georec(
        longitude_rad,
        latitude_rad,
        altitude_km,
        equ_radius,
        flattening,
    )

    east = np.array([-np.sin(longitude_rad), np.cos(longitude_rad), 0.0])
    north = np.array([
        -np.sin(latitude_rad) * np.cos(longitude_rad),
        -np.sin(latitude_rad) * np.sin(longitude_rad),
        np.cos(latitude_rad),
    ])
    up = np.array([
        np.cos(latitude_rad) * np.cos(longitude_rad),
        np.cos(latitude_rad) * np.sin(longitude_rad),
        np.sin(latitude_rad),
    ])

    return obs_pos, np.vstack((north, east, up))


def moon_az_el_for_times(times_utc, obs_pos, itrf93_to_neu):
    azimuths = []
    elevations = []

    for dt_utc in times_utc:
        et = sp.utc2et(spice_utc_string(dt_utc))
        state, _ = sp.spkezr(TARGET, et, FRAME, ABCORR, OBSERVER)

        obs_vec_itrf = state[:3] - obs_pos
        obs_vec_neu = itrf93_to_neu @ obs_vec_itrf

        _, azimuth_rad, elevation_rad = sp.recazl(
            obs_vec_neu,
            azccw=True,
            elplsz=True,
        )

        azimuths.append(np.rad2deg(azimuth_rad) % 360.0)
        elevations.append(np.rad2deg(elevation_rad))

    return np.array(azimuths), np.array(elevations)


def load_horizon_csv():
    global _horizon_cache
    if _horizon_cache is not None:
        return _horizon_cache

    _require_file(HORIZON_CSV)
    df = pd.read_csv(HORIZON_CSV)
    required = {"azimuth_deg", "horizon_angle_deg"}
    if not required.issubset(df.columns):
        raise MoonriseError(
            "Horizon CSV must contain azimuth_deg and horizon_angle_deg columns."
        )

    az = df["azimuth_deg"].to_numpy(dtype=float)
    el = df["horizon_angle_deg"].to_numpy(dtype=float)
    az = (az + HORIZON_AZIMUTH_CORRECTION_DEG) % 360.0

    order = np.argsort(az)
    az = az[order]
    el = el[order]

    unique_az, unique_indices = np.unique(az, return_index=True)
    unique_el = el[unique_indices]
    _horizon_cache = (unique_az, unique_el)
    return _horizon_cache


def horizon_elevation_at_azimuth(az_query, horizon_az, horizon_el):
    az_query = np.asarray(az_query, dtype=float) % 360.0
    covers_full_circle = horizon_az[0] <= 1.0 and horizon_az[-1] >= 359.0

    if covers_full_circle:
        az_ext = np.concatenate([horizon_az - 360.0, horizon_az, horizon_az + 360.0])
        el_ext = np.concatenate([horizon_el, horizon_el, horizon_el])
        return np.interp(az_query, az_ext, el_ext)

    return np.interp(az_query, horizon_az, horizon_el, left=np.nan, right=np.nan)


def interpolate_angle_deg(a0, a1, fraction):
    delta = ((a1 - a0 + 180.0) % 360.0) - 180.0
    return (a0 + fraction * delta) % 360.0


def find_horizon_crossings(times_utc, moon_az, moon_el, horizon_az, horizon_el):
    terrain_el_at_moon = horizon_elevation_at_azimuth(
        moon_az,
        horizon_az,
        horizon_el,
    )

    clearance = moon_el - terrain_el_at_moon
    crossings = []
    eps = 1e-9

    for i in range(len(clearance) - 1):
        c0 = clearance[i]
        c1 = clearance[i + 1]

        if not (np.isfinite(c0) and np.isfinite(c1)):
            continue

        if abs(c0) < eps:
            fraction = 0.0
        elif c0 * c1 < 0:
            fraction = -c0 / (c1 - c0)
        else:
            continue

        t0 = times_utc[i]
        t1 = times_utc[i + 1]
        crossing_time_utc = t0 + fraction * (t1 - t0)
        crossing_az = interpolate_angle_deg(moon_az[i], moon_az[i + 1], fraction)
        crossing_moon_el = moon_el[i] + fraction * (moon_el[i + 1] - moon_el[i])
        crossing_horizon_el = horizon_elevation_at_azimuth(
            np.array([crossing_az]),
            horizon_az,
            horizon_el,
        )[0]

        crossings.append({
            "kind": "rising" if c0 < c1 else "setting",
            "time_utc": crossing_time_utc,
            "azimuth_deg": crossing_az,
            "elevation_deg": crossing_horizon_el,
            "moon_elevation_deg": crossing_moon_el,
        })

    return crossings, terrain_el_at_moon


def filter_rising_crossings_for_entered_day(crossings, date_string):
    local_start, local_end = local_day_bounds(date_string)
    rises = []
    for crossing in crossings:
        local_time = crossing["time_utc"].astimezone(get_local_tz())
        if crossing["kind"] == "rising" and local_start <= local_time < local_end:
            rises.append(crossing)
    return rises


def filter_rises_by_azimuth_range(rises, az_min_deg, az_max_deg):
    return [
        rise
        for rise in rises
        if az_min_deg <= rise["azimuth_deg"] <= az_max_deg
    ]


def moonrise_plot_mask(times_utc, rises, date_string, hours_around_rise):
    if not rises:
        return np.zeros(len(times_utc), dtype=bool)

    local_start, local_end = local_day_bounds(date_string)
    window = timedelta(hours=hours_around_rise)
    mask = np.zeros(len(times_utc), dtype=bool)

    for rise in rises:
        rise_local = rise["time_utc"].astimezone(get_local_tz())
        window_start_local = max(local_start, rise_local - window)
        window_end_local = min(local_end, rise_local + window)
        window_start_utc = window_start_local.astimezone(timezone.utc)
        window_end_utc = window_end_local.astimezone(timezone.utc)

        for i, t_utc in enumerate(times_utc):
            if window_start_utc <= t_utc < window_end_utc:
                mask[i] = True

    return mask


def dt_payload(dt_utc):
    local_dt = dt_utc.astimezone(get_local_tz())
    utc_dt = dt_utc.astimezone(timezone.utc)
    return {
        "local": local_dt.isoformat(),
        "local_label": local_dt.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "utc": utc_dt.isoformat(),
        "utc_label": utc_dt.strftime("%Y-%m-%d %H:%M:%S UTC"),
    }


def finite_point(azimuth, elevation, time_utc=None):
    point = {
        "azimuth_deg": round(float(azimuth), 6),
        "elevation_deg": round(float(elevation), 6),
    }
    if time_utc is not None:
        point["time"] = dt_payload(time_utc)
    return point


def compute_moonrise(date_string):
    load_spice_kernels()
    local_day_bounds(date_string)

    times_utc = build_time_grid_for_local_day(date_string, STEP_MINUTES)
    obs_pos, itrf93_to_neu = observer_position_and_neu_matrix(
        LATITUDE_DEG,
        LONGITUDE_DEG,
        ALTITUDE_KM,
    )
    moon_az, moon_el = moon_az_el_for_times(times_utc, obs_pos, itrf93_to_neu)
    horizon_az, horizon_el = load_horizon_csv()

    crossings, terrain_el_at_moon = find_horizon_crossings(
        times_utc,
        moon_az,
        moon_el,
        horizon_az,
        horizon_el,
    )
    rises = filter_rising_crossings_for_entered_day(crossings, date_string)

    if FILTER_RISES_TO_PLOT_AZIMUTH_RANGE:
        rises = filter_rises_by_azimuth_range(
            rises,
            HORIZON_PLOT_AZ_MIN_DEG,
            HORIZON_PLOT_AZ_MAX_DEG,
        )

    plot_mask = moonrise_plot_mask(
        times_utc,
        rises,
        date_string,
        PLOT_HOURS_AROUND_RISE,
    )
    valid_moon = np.isfinite(terrain_el_at_moon) & plot_mask
    horizon_plot_mask = (
        (horizon_az >= HORIZON_PLOT_AZ_MIN_DEG)
        & (horizon_az <= HORIZON_PLOT_AZ_MAX_DEG)
    )

    moon_path = [
        finite_point(az, el, time_utc)
        for time_utc, az, el, valid in zip(times_utc, moon_az, moon_el, valid_moon)
        if valid
    ]
    horizon_profile = [
        finite_point(az, el)
        for az, el, valid in zip(horizon_az, horizon_el, horizon_plot_mask)
        if valid
    ]

    rise_payload = []
    for rise in rises:
        rise_payload.append({
            "time": dt_payload(rise["time_utc"]),
            "azimuth_deg": round(float(rise["azimuth_deg"]), 6),
            "elevation_deg": round(float(rise["elevation_deg"]), 6),
            "moon_elevation_deg": round(float(rise["moon_elevation_deg"]), 6),
        })

    return {
        "date": date_string,
        "timezone": LOCAL_TIMEZONE,
        "observer": {
            "latitude_deg": LATITUDE_DEG,
            "longitude_deg": LONGITUDE_DEG,
            "altitude_km": ALTITUDE_KM,
        },
        "plot": {
            "azimuth_min_deg": HORIZON_PLOT_AZ_MIN_DEG,
            "azimuth_max_deg": HORIZON_PLOT_AZ_MAX_DEG,
            "hours_around_rise": PLOT_HOURS_AROUND_RISE,
        },
        "rises": rise_payload,
        "moon_path": moon_path,
        "horizon_profile": horizon_profile,
        "message": None
        if rise_payload
        else "No terrain moonrise found for that local date.",
    }
