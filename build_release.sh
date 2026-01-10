#!/bin/bash
pyinstaller \
  --clean \
  --onefile \
  --name="AutoPot-DR" \
  --icon=../imgs/icon.ico \
  --distpath release \
  --workpath build \
  --specpath release \
  src/main.py