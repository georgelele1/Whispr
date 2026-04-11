#!/usr/bin/env bash
set -e

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUNTIME_DIR="${ROOT_DIR}/runtime"
VENV_DIR="${RUNTIME_DIR}/venv"
PYTHON_BIN="${PYTHON_BIN:-python3.11}"

echo "Project root: ${ROOT_DIR}"
echo "Using Python: ${PYTHON_BIN}"

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "Error: ${PYTHON_BIN} not found."
  echo "Please install Python 3.11 first."
  exit 1
fi

rm -rf "${VENV_DIR}"
mkdir -p "${RUNTIME_DIR}"

"${PYTHON_BIN}" -m venv "${VENV_DIR}"

"${VENV_DIR}/bin/pip" install --upgrade pip setuptools wheel
"${VENV_DIR}/bin/pip" install -r "${ROOT_DIR}/backend/requirements.txt"

echo "Testing runtime..."
"${VENV_DIR}/bin/python" "${ROOT_DIR}/backend/app.py" cli get-language

echo ""
echo "Runtime setup complete."
echo "Python: ${VENV_DIR}/bin/python"