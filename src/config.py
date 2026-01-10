"""
Configuration management module.
Handles loading, creating, and saving configuration file.
"""
import os
import configparser
from pathlib import Path


class Config:
    """Manages application configuration from INI file."""
    
    CONFIG_FILE = "config_user.ini"
    
    # Default values
    DEFAULT_HEALTH_THRESHOLD = 30.0
    DEFAULT_ADDRESS_CURRENT_HEALTH = "0x0"
    DEFAULT_ADDRESS_MAX_HEALTH = "0x0"
    DEFAULT_ADDRESS_POTION_COUNT = "0x0"
    DEFAULT_OVERLAY_POS_X = 200
    DEFAULT_OVERLAY_POS_Y = 880
    DEFAULT_OVERLAY_LOCKED = False
    
    def __init__(self):
        """Initialize config, create file if missing."""
        self.config = configparser.ConfigParser()
        self._ensure_config_file()
        self._load_config()
    
    def _ensure_config_file(self):
        """Create config file with defaults if it doesn't exist."""
        if not os.path.exists(self.CONFIG_FILE):
            self._create_default_config()
    
    def _create_default_config(self):
        """Create config file with default values."""
        self.config['SETTINGS'] = {
            'HEALTH_THRESHOLD': str(self.DEFAULT_HEALTH_THRESHOLD),
            'ADDRESS_CURRENT_HEALTH': self.DEFAULT_ADDRESS_CURRENT_HEALTH,
            'ADDRESS_MAX_HEALTH': self.DEFAULT_ADDRESS_MAX_HEALTH,
            'ADDRESS_POTION_COUNT': self.DEFAULT_ADDRESS_POTION_COUNT
        }
        self.config['OVERLAY'] = {
            'POS_X': str(self.DEFAULT_OVERLAY_POS_X),
            'POS_Y': str(self.DEFAULT_OVERLAY_POS_Y),
            'LOCKED': str(self.DEFAULT_OVERLAY_LOCKED)
        }
        
        try:
            with open(self.CONFIG_FILE, 'w') as f:
                self.config.write(f)
        except Exception as e:
            print(f"Error creating config file: {e}")
    
    def _load_config(self):
        """Load configuration from file."""
        try:
            self.config.read(self.CONFIG_FILE)
        except Exception as e:
            print(f"Error loading config file: {e}, using defaults")
    
    def _save_config(self):
        """Save current configuration to file."""
        try:
            with open(self.CONFIG_FILE, 'w') as f:
                self.config.write(f)
        except Exception as e:
            print(f"Error saving config file: {e}")
    
    # Getter methods
    def get_health_threshold(self):
        """Get health threshold percentage."""
        try:
            return float(self.config.get('SETTINGS', 'HEALTH_THRESHOLD', 
                                        fallback=self.DEFAULT_HEALTH_THRESHOLD))
        except (ValueError, configparser.NoOptionError):
            return self.DEFAULT_HEALTH_THRESHOLD
    
    def get_address_current_health(self):
        """Get current health memory address."""
        return self.config.get('SETTINGS', 'ADDRESS_CURRENT_HEALTH',
                              fallback=self.DEFAULT_ADDRESS_CURRENT_HEALTH)
    
    def get_address_max_health(self):
        """Get max health memory address."""
        return self.config.get('SETTINGS', 'ADDRESS_MAX_HEALTH',
                              fallback=self.DEFAULT_ADDRESS_MAX_HEALTH)
    
    def get_address_potion_count(self):
        """Get potion count memory address."""
        return self.config.get('SETTINGS', 'ADDRESS_POTION_COUNT',
                              fallback=self.DEFAULT_ADDRESS_POTION_COUNT)
    
    def get_overlay_pos_x(self):
        """Get overlay X position."""
        try:
            return int(self.config.get('OVERLAY', 'POS_X',
                                      fallback=self.DEFAULT_OVERLAY_POS_X))
        except (ValueError, configparser.NoOptionError):
            return self.DEFAULT_OVERLAY_POS_X
    
    def get_overlay_pos_y(self):
        """Get overlay Y position."""
        try:
            return int(self.config.get('OVERLAY', 'POS_Y',
                                      fallback=self.DEFAULT_OVERLAY_POS_Y))
        except (ValueError, configparser.NoOptionError):
            return self.DEFAULT_OVERLAY_POS_Y
    
    def get_overlay_locked(self):
        """Get overlay locked state."""
        try:
            value = self.config.get('OVERLAY', 'LOCKED',
                                   fallback=str(self.DEFAULT_OVERLAY_LOCKED))
            return value.lower() in ('true', '1', 'yes')
        except (ValueError, configparser.NoOptionError):
            return self.DEFAULT_OVERLAY_LOCKED
    
    # Setter methods
    def set_overlay_pos(self, x, y):
        """Save overlay position to config."""
        if 'OVERLAY' not in self.config:
            self.config['OVERLAY'] = {}
        self.config['OVERLAY']['POS_X'] = str(x)
        self.config['OVERLAY']['POS_Y'] = str(y)
        self._save_config()
    
    def set_overlay_locked(self, locked):
        """Save overlay locked state to config."""
        if 'OVERLAY' not in self.config:
            self.config['OVERLAY'] = {}
        self.config['OVERLAY']['LOCKED'] = str(locked)
        self._save_config()
