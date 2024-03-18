from os.path import expanduser
from dataclasses import dataclass


# The class to store full information for a backup of some app
# or directory. Includes the location of the source files, 
# backup destination and the amount of backups
@dataclass
class Backup:
    source_location: str
    backup_dir: str
    backup_amount: int = 3
# List of apps, which need a backup with source/destination parameters
# used only lowercase
BACKUPS = {
    'keepassxc': Backup(
        source_location=expanduser('~/Documents/Kee/'),
        backup_dir='/mnt/kllisre/Backups/Kee/'
    ),
    'obsidian': Backup(
        source_location=expanduser('~/Documents/ObsidianVault/'),
        backup_dir='/mnt/kllisre/Backups/Obsidian/'
    )
}
# Colors for the binding mode letters
COLORS = {
    'default': '#C0C0C0',
    'launch': '#EE21FB',
    'resize': '#F8FB21',
    'focus': '#00A8E1'
}
# ini file for planetside2 to fix before the start
PS2_DIR = '/mnt/kllisre/SteamLibrary/steamapps/common/PlanetSide 2/'
# I can't come up with commands which i3 can't perform
# so it's important to use nop for new modes
NOP_SHORTCUTS = {
    ('shift', 'Mod4', 'd'): 'assign_windows',
    ('shift', 'Mod4', 'm'): 'open_mkv',
    ('shift', 'Mod4', 's'): 'switch_windows'
}
# Games, which require picom to turn off and steam to not go on top of them
# the script checks if any of substrings, listed here, occured in the
# name of an application. 
GAMES = ['Planetside2', 'World of Warcraft']
# where helper files for i3_manager_genmon are located
I3_HELPER_FILES = '.config/i3/i3_manager_assets/'
