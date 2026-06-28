const path = require('path')

const root = __dirname
const backend = path.join(root, 'vendor', 'tickflow-stock-panel', 'backend')
const python = process.env.PYTHON_BIN || path.join(root, '.venv', 'bin', 'python')
const backendPython = process.env.TICKFLOW_PYTHON_BIN || path.join(backend, '.venv', 'bin', 'python')
const recapDb = process.env.RECAP_DB_PATH || path.join(root, 'data', 'recap.db')
const pythonPath = [root, path.join(root, 'src'), process.env.PYTHONPATH].filter(Boolean).join(path.delimiter)

// Docker Compose is the authoritative production topology. This PM2 file is a
// portable local-development fallback.
module.exports = {
  apps: [
    {
      name: 'data-pipeline',
      cwd: root,
      script: python,
      args: '-m src.data_pipeline',
      interpreter: 'none',
      autorestart: true,
      max_restarts: 5,
      min_uptime: 10000,
      watch: false,
      env: {
        PATH: process.env.PATH,
        PYTHONPATH: pythonPath,
        RECAP_DB_PATH: recapDb
      }
    },
    {
      name: 'recap-scheduler',
      cwd: root,
      script: python,
      args: '-m recap_scheduler',
      interpreter: 'none',
      autorestart: true,
      max_restarts: 5,
      min_uptime: 10000,
      watch: false,
      env: {
        PATH: process.env.PATH,
        PYTHONPATH: pythonPath,
        RECAP_DB_PATH: recapDb
      }
    },
    {
      name: 'tickflow-backend',
      cwd: backend,
      script: backendPython,
      args: '-m uvicorn app.main:app --host 0.0.0.0 --port 3018',
      interpreter: 'none',
      autorestart: true,
      watch: false,
      env: {
        NODE_ENV: 'production',
        PATH: process.env.PATH,
        RECAP_DB_PATH: recapDb
      }
    }
  ]
}
