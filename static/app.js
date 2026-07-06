const form = document.querySelector("#moonForm");
const dateInput = document.querySelector("#dateInput");
const statusEl = document.querySelector("#status");
const riseListEl = document.querySelector("#riseList");
const canvas = document.querySelector("#moonChart");
const ctx = canvas.getContext("2d");

const colors = {
  ink: "#172033",
  muted: "#667085",
  grid: "#d9e1ea",
  horizon: "#246b8f",
  moon: "#d77a2d",
  moonFill: "#fff2d7",
  panel: "#ffffff",
};

dateInput.value = new Date().toISOString().slice(0, 10);
drawEmptyChart();

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  await calculate(dateInput.value);
});

async function calculate(date) {
  setLoading(true);
  riseListEl.innerHTML = "";

  try {
    const response = await fetch(`/api/moonrise?date=${encodeURIComponent(date)}`);
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Calculation failed.");
    }

    renderResult(payload);
  } catch (error) {
    statusEl.textContent = error.message;
    drawEmptyChart("No chart available");
  } finally {
    setLoading(false);
  }
}

function setLoading(isLoading) {
  const button = form.querySelector("button");
  button.disabled = isLoading;
  button.textContent = isLoading ? "Calculating..." : "Calculate";
  if (isLoading) {
    statusEl.textContent = "Calculating Moon position and terrain crossing...";
  }
}

function renderResult(data) {
  if (data.rises.length === 0) {
    statusEl.textContent = data.message;
  } else if (data.rises.length === 1) {
    statusEl.textContent = `Moonrise: ${data.rises[0].time.local_label}`;
  } else {
    statusEl.textContent = `${data.rises.length} terrain moonrises found.`;
  }

  riseListEl.innerHTML = data.rises.map((rise) => `
    <article class="rise-card">
      <strong>${rise.time.local_label}</strong>
      <span>Az ${rise.azimuth_deg.toFixed(2)} deg</span>
      <span>Horizon ${rise.elevation_deg.toFixed(2)} deg</span>
    </article>
  `).join("");

  drawChart(data);
}

function drawEmptyChart(label = "Waiting for date") {
  sizeCanvas();
  ctx.fillStyle = colors.panel;
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = colors.muted;
  ctx.font = "28px system-ui, sans-serif";
  ctx.textAlign = "center";
  ctx.fillText(label, canvas.width / 2, canvas.height / 2);
}

function drawChart(data) {
  sizeCanvas();

  const padding = { left: 72, right: 28, top: 34, bottom: 62 };
  const plotW = canvas.width - padding.left - padding.right;
  const plotH = canvas.height - padding.top - padding.bottom;

  const allElevations = [
    ...data.horizon_profile.map((p) => p.elevation_deg),
    ...data.moon_path.map((p) => p.elevation_deg),
    ...data.rises.map((p) => p.elevation_deg),
  ];
  const yCenter = (Math.min(...allElevations) + Math.max(...allElevations)) / 2;
  const yRange = (Math.max(...allElevations) - Math.min(...allElevations)) * 1.35;
  const yMin = yCenter - yRange / 2;
  const yMax = yCenter + yRange / 2;
  
  const xMin = data.plot.azimuth_min_deg;
  const xMax = data.plot.azimuth_max_deg;
  
  const xScale = (az) => padding.left + ((az - xMin) / (xMax - xMin)) * plotW;
  const yScale = (el) => padding.top + (1 - ((el - yMin) / (yMax - yMin))) * plotH;

  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = colors.panel;
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  //drawGrid(padding, plotW, plotH, xMin, xMax, yMin, yMax, xScale, yScale);
  drawLine(data.horizon_profile, xScale, yScale, colors.horizon, 3);
  drawSegmentedMoonPath(data.moon_path, xScale, yScale);
  drawRises(data.rises, xScale, yScale);
  //drawLegend();
}

function drawGrid(padding, plotW, plotH, xMin, xMax, yMin, yMax, xScale, yScale) {
  ctx.strokeStyle = colors.grid;
  ctx.lineWidth = 1;
  ctx.fillStyle = colors.muted;
  ctx.font = "22px system-ui, sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "top";

  for (let az = xMin; az <= xMax; az += 30) {
    const x = xScale(az);
    line(x, padding.top, x, padding.top + plotH);
    //ctx.fillText(String(az), x, padding.top + plotH + 14);
  }

  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  const step = niceStep((yMax - yMin) / 6);
  const first = Math.ceil(yMin / step) * step;
  for (let el = first; el <= yMax; el += step) {
    const y = yScale(el);
    line(padding.left, y, padding.left + plotW, y);
    //ctx.fillText(String(Math.round(el)), padding.left - 12, y);
  }

  ctx.strokeStyle = colors.ink;
  ctx.lineWidth = 2;
  ctx.strokeRect(padding.left, padding.top, plotW, plotH);

  ctx.fillStyle = colors.ink;
  ctx.textAlign = "center";
  ctx.textBaseline = "bottom";
  //ctx.fillText("Azimuth, degrees clockwise from true north", padding.left + plotW / 2, canvas.height - 10);

  ctx.save();
  ctx.translate(22, padding.top + plotH / 2);
  ctx.rotate(-Math.PI / 2);
  //ctx.fillText("Elevation angle, degrees", 0, 0);
  ctx.restore();
}

function drawLine(points, xScale, yScale, color, width) {
  if (points.length < 2) return;
  ctx.beginPath();
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  points.forEach((point, index) => {
    const x = xScale(point.azimuth_deg);
    const y = yScale(point.elevation_deg);
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

function drawSegmentedMoonPath(points, xScale, yScale) {
  if (points.length < 2) return;

  ctx.strokeStyle = colors.moon;
  ctx.lineWidth = 4;
  ctx.beginPath();
  let drawing = false;

  for (let i = 0; i < points.length; i += 1) {
    const point = points[i];
    const previous = points[i - 1];
    const x = xScale(point.azimuth_deg);
    const y = yScale(point.elevation_deg);
    const gap = previous && Math.abs(point.azimuth_deg - previous.azimuth_deg) > 8;

    if (!drawing || gap) {
      ctx.moveTo(x, y);
      drawing = true;
    } else {
      ctx.lineTo(x, y);
    }
  }
  ctx.stroke();
}

function drawRises(rises, xScale, yScale) {
  rises.forEach((rise) => {
    const x = xScale(rise.azimuth_deg);
    const y = yScale(rise.elevation_deg);
    ctx.fillStyle = colors.moonFill;
    ctx.strokeStyle = colors.moon;
    ctx.lineWidth = 4;
    ctx.beginPath();
    ctx.arc(x, y, 11, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();

    ctx.fillStyle = colors.ink;
    ctx.font = "22px system-ui, sans-serif";
    ctx.textAlign = "left";
    ctx.textBaseline = "bottom";
    ctx.fillText(rise.time.local_label.slice(11, 16), x + 16, y - 12);
  });
}
/*
function drawLegend() {
  ctx.font = "22px system-ui, sans-serif";
  ctx.textAlign = "left";
  ctx.textBaseline = "middle";
  legendItem(86, 34, colors.horizon, "Terrain horizon");
  legendItem(312, 34, colors.moon, "Moon path near moonrise");
}
*/

function legendItem(x, y, color, label) {
  ctx.strokeStyle = color;
  ctx.lineWidth = 5;
  line(x, y, x + 34, y);
  ctx.fillStyle = colors.ink;
  ctx.fillText(label, x + 44, y);
}

function niceStep(raw) {
  const power = Math.pow(10, Math.floor(Math.log10(raw)));
  const scaled = raw / power;
  if (scaled <= 1) return power;
  if (scaled <= 2) return 2 * power;
  if (scaled <= 5) return 5 * power;
  return 10 * power;
}

function line(x1, y1, x2, y2) {
  ctx.beginPath();
  ctx.moveTo(x1, y1);
  ctx.lineTo(x2, y2);
  ctx.stroke();
}

function sizeCanvas() {
  const box = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.floor(box.width * dpr);
  canvas.height = Math.floor(box.height * dpr);
  ctx.setTransform(1, 0, 0, 1, 0, 0);
}
