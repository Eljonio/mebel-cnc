#!/usr/bin/env bash
# Headless-скриншот HTML (WebGL через SwiftShader). Свой профиль во временной папке — живой браузер не трогаем.
# Только программный рендер (Mesa/SwiftShader): дискретную видеокарту не задействуем. Нужен google-chrome.
# shot.sh <файл.html> <выход.png> [ширина высота] [#хэш или ?параметры]
set -euo pipefail
src="$(realpath "$1")"; out="$2"; w="${3:-1400}"; h="${4:-900}"; hash="${5:-}"
prof="$(mktemp -d)"
trap 'rm -rf "$prof"' EXIT
env __EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/50_mesa.json __GLX_VENDOR_LIBRARY_NAME=mesa \
  VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/lvp_icd.json VK_DRIVER_FILES=/usr/share/vulkan/icd.d/lvp_icd.json \
  __EGL_EXTERNAL_PLATFORM_CONFIG_DIRS=/nonexistent CUDA_VISIBLE_DEVICES= DISPLAY= \
  google-chrome --headless=new --no-first-run --no-default-browser-check --user-data-dir="$prof" \
  --use-angle=swiftshader --enable-unsafe-swiftshader --ignore-gpu-blocklist --hide-scrollbars \
  --disable-vulkan --disable-features=Vulkan \
  --window-size="$w,$h" --virtual-time-budget=9000 --screenshot="$out" "file://$src$hash" >/dev/null 2>&1
test -s "$out" && echo "$out"
