#!/bin/bash
pyinstaller \
  --clean \
  --onefile \
  --name="AutoPot-DR" \
  --icon=../imgs/icon.ico \
  --add-data "../imgs;imgs" \
  --distpath release \
  --workpath build \
  --specpath release \
  src/main.py