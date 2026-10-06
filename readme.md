<div align="center">

# Auto Potion Tool 🧌

[![Dwarven Realms](https://img.shields.io/badge/Dwarven%20Realms%20-5.3.2.0-purple)]()
[![Windows](https://img.shields.io/badge/Platform-Windows-blue)]()

</div>

A game tool for Dwarven Realms that automatically uses potions when HP drops below a configurable threshold and the player has at least one potion. It attaches to the game process via pymem and resolves health, energy (the game's mana-like resource), and potion fields through Unreal's live object graph and reflected property names. Health, energy, and potion values are looked up at runtime instead of using a pointer chain for each value. It validates known module-relative hints for Unreal globals and scans writable module data if those globals move; unsupported Unreal layouts are rejected without sending inputs. Memory reading runs in a separate background thread with thread-safe operation. Features a PyQt5 overlay window with transparency and always-on-top behavior and is also thread-safe for responsiveness.

**⚠️ Warning**: This tool is intended for **offline use only**. While it may work online, use it at your own risk and discretion.



**A few important notes:**

* While it's not a guarantee of survival, it will save you most of the time. It works with any class or build, just make sure you always have enough potions!
* Because of how the game handles health and damage over time (DoT), if you take a lot of DoT or very fast hits, your HP can drop below the threshold very quickly, multiple times or stay below the threshold even with potion drinks. The potion will trigger as soon as your real HP drops below the threshold, but if the accumulated or incoming damage is higher than what a potion can heal, you might still die.


## ✨ Features

<p align="center">
  <img src="imgs/OverlayOFF.png" alt="Overlay OFF" width="45%"/>
  <img src="imgs/OverlayON.png" alt="Overlay ON" width="45%"/>
</p>

* **Auto Potion**: Automatically triggers a potion when HP falls below a set percentage and the player has at least one potion (prevents spamming when out of potions).
* **Potion count display**: The overlay shows available potions and the maximum capacity.
* **Energy display**: The overlay shows current and maximum Energy, the game's mana-like resource.
* **Potion log**: The overlay displays a log of recent potion uses, showing HP values and timestamps for each use. The console log for each use also shows remaining potion count.
* **Overlay UI**: Movable, lockable PyQt5 overlay showing status, potions, HP, Energy, and logs.
* **Customizable Hotkeys**: Easily change hotkeys for toggling ON/OFF, locking, and closing the overlay.
* **Safe & Configurable**: All settings in a user-friendly config file.

## 🛠️ Setup Instructions

You can use the tool in three ways:

### 1. Download the Executable

* Download the latest release from the Releases page.
* Run the `.exe` file directly.

### 2. Local Setup

* Clone the repository:  
```bash
git clone https://github.com/leobrqz/AutoPot-DR
cd AutoPot-DR
```
* Install dependencies:  
```bash
pip install -r requirements.txt
```
Now either run it with python or build the executable.

### Run with Python

* Run the application:  
```bash
python src/main.py
```

### Build the Executable Yourself

* Build the executable with PyInstaller:  
```bash
./build_release.sh
```
* The executable will be in the `release` folder.

## ⚙️ Configuration

The application creates a `config_user.ini` file on first run with default settings. You can modify this file to customize the tool's behavior.

### General 

- **`health_threshold`** (default: `30.0`)
  - The health percentage threshold at which the tool will automatically use a potion.


### Overlay 

- **`pos_x`** (default: `200`)
- **`pos_y`** (default: `880`)
- **`locked`** (default: `False`)
  - Whether the overlay is locked (cannot be moved) on startup.

### Keybinds 

Customize the global hotkeys used to control the tool:

- **`hotkey_lock`** (default: `home`)
  - Toggle overlay lock/unlock (prevents moving the overlay).
- **`hotkey_toggle`** (default: `insert`)
  - Toggle auto potion feature on/off.
- **`hotkey_close`** (default: `end`)
  - Close the application.



