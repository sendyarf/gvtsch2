const path = require("path");

// Use the project-local virtualenv python so PM2 never falls back to the
// PEP-668-managed system Python. Create it on the server with:
//   python3 -m venv venv && . venv/bin/activate && pip install -r requirements.txt
const normalizeInterpreter = () =>
  process.platform === "win32"
    ? path.join(__dirname, "venv", "Scripts", "python.exe")
    : path.join(__dirname, "venv", "bin", "python");

const INTERPRETER = normalizeInterpreter();

module.exports = {
  apps: [
    {
      name: "gvtsch2",
      script: "run_all.py",
      args: "--daemon",
      interpreter: INTERPRETER,
      cwd: __dirname,
      exec_mode: "fork",
      time: true,
      instances: 1,
      autorestart: true,
      min_uptime: "10s",
      max_restarts: 20,
      restart_delay: 5000,
      exp_backoff_restart_delay: 1000,
      kill_timeout: 10000,
      max_memory_restart: "1G",
      out_file: "./logs/gvtsch2-out.log",
      error_file: "./logs/gvtsch2-err.log",
      log_date_format: "YYYY-MM-DD HH:mm:ss Z",
      env: {
        PYTHONUNBUFFERED: "1",
      },
    },
    {
      // Real-time live scores: polls /api/match/detail_live every LIVE_INTERVAL
      // seconds and writes live.json (fetched by the frontend, overlaid onto
      // sch.json). Kept separate from the 3-min scraper cycle on purpose.
      name: "gvtsch2-live",
      script: "live.py",
      interpreter: INTERPRETER,
      cwd: __dirname,
      exec_mode: "fork",
      time: true,
      instances: 1,
      autorestart: true,
      min_uptime: "10s",
      max_restarts: 20,
      restart_delay: 3000,
      exp_backoff_restart_delay: 1000,
      kill_timeout: 10000,
      max_memory_restart: "512M",
      out_file: "./logs/gvtsch2-live-out.log",
      error_file: "./logs/gvtsch2-live-err.log",
      log_date_format: "YYYY-MM-DD HH:mm:ss Z",
      env: {
        PYTHONUNBUFFERED: "1",
        LIVE_INTERVAL: "10",   // seconds between detail_live polls
      },
    },
    {
      // Serve sch.json (and friends) publicly for the frontend.
      // Example: fetch("https://your-vps:9015/sch.json")  (CORS enabled)
      name: "gvtsch2-serve",
      script: "serve_public.py",
      interpreter: INTERPRETER,
      cwd: __dirname,
      exec_mode: "fork",
      time: true,
      autorestart: true,
      // Jangan tight-loop kalau port dipakai / interpreter hilang:
      // anggap "stabil" hanya jika hidup >= 10 detik, dan mundurkan
      // restart secara eksponensial agar tidak 245x dalam 8 menit.
      min_uptime: "10s",
      max_restarts: 20,
      restart_delay: 2000,
      exp_backoff_restart_delay: 1000,
      kill_timeout: 5000,
      max_memory_restart: "256M",
      out_file: "./logs/gvtsch2-serve-out.log",
      error_file: "./logs/gvtsch2-serve-err.log",
      log_date_format: "YYYY-MM-DD HH:mm:ss Z",
      env: {
        PYTHONUNBUFFERED: "1",
        GVT_SERVE_HOST: "127.0.0.1",   // loopback; expose it via nginx
        GVT_SERVE_PORT: "9015",
      },
    },
  ],
};