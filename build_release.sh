#!/bin/bash
pyinstaller \
  --clean \
  --onefile \
  --name="AutoPot-DR-v1.2.0" \
  --icon=../imgs/icon.ico \
  --add-data "../imgs;imgs" \
  --distpath release \
  --workpath build \
  --specpath release \
  src/main.py