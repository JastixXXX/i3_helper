from os.path import expanduser
from dataclasses import dataclass
from datetime import timedelta


# =============== backups =====================
class Backup:
    """The class to store full information for a backup of some app
    or directory. The backup can be made on a local drive, or on both - 
    google drive and local drive. Makes no sense to backup only on
    gdrive. Unreliable

    source_location: what to backup, path
    backup_dir: where to backup locally, path
    backup_amount: last three backups cover last
        three days when there were some changes.
        The rest - a backup per 2 weeks. 0 means
        no limit to such backups. Doesn't work for
        4 items though, because there is no way
        to store intermediate backups
    old_backup_interval: the way to change that
        2 weeks from above
    sync_gdrive: a flag that backup on gdrive is
        required
    gdrive_args: a list of arguments to pass to
        gdrive sync script
    """
    # pun any of these two to None to turn off gdrive backup
    gdrive_python_path = expanduser('~/Documents/Scripts/gdrive_manage/venv/bin/python')
    gdrive_script_path = expanduser('~/Documents/Scripts/gdrive_manage/gdrive_manage.py')
    
    def __init__(
        self,
        source_location: str,
        backup_dir: str,
        backup_amount: int = 4,
        old_backup_interval: timedelta = timedelta(weeks=2),
        sync_gdrive: bool = False,
        gdrive_args: list|None = None        
    ) -> None:
        self.source_location = source_location
        self.backup_dir = backup_dir
        self.backup_amount = backup_amount
        self.old_backup_interval = old_backup_interval
        self.sync_gdrive = sync_gdrive
        self.gdrive_args = gdrive_args

# List of apps, which need a backup with source/destination parameters
# apps names are only lowercase. Don't forget the app name in backup_dir
# otherwise all backups of all apps will be messed up
BACKUPS = {
    'keepassxc': Backup(
        source_location=expanduser('~/Documents/Kee/'),
        backup_dir='/mnt/kllisre/Backups/Kee/'
    ),
    'obsidian': Backup(
        source_location=expanduser('~/Documents/ObsidianVault/'),
        backup_dir='/mnt/kllisre/Backups/Obsidian/',
        sync_gdrive=True,
        gdrive_args=['--sync-direction', 'mirror', '--ignore', 'path=.obsidian,type=all_files']
    ),
    'testapp': Backup(
        source_location=expanduser('~/Documents/temp/1'),
        backup_dir=expanduser('~/Documents/temp/2'),
        backup_amount=7,
        old_backup_interval=timedelta(days=2)
    )
}

# =============== colors ======================
# Colors for the binding mode letters
COLORS = {
    'default': '#C0C0C0',
    'launch': '#EE21FB',
    'resize': '#F8FB21',
    'focus': '#00A8E1',
    'ps2': '#8509e4',
    'virt': '#00A8E1',
    'proxy': '#22e417',
}

# =============== ws assignment ===============
# dinding some workspaces to actual screens by their outputs
OUTPUTS = {
    'DP-0': ['1', '2', '3'],
    'HDMI-0': ['4', '5', '6']
}
# apps windows are usually bulky enough to wast to use it
# solely on the screen. But these apps can appear on the same
# screen without banishing to the new ws. All floating windows
# also don't get banished
NON_BANISHING_APPS = [
    'terminal',
    'mousepad'
]

@dataclass
class DefaultAssignment:
    """Describes one app behaviour.
    Only for apps with special ws binding.

        name: app class in lower case
        share_screen: a list of apps which won't be
            banished when opened next to the current one.
            Except those, which are in NON_BANISHING_APPS
        output: output name, if an app has no assigned ws
            but should be opened on an exact screen
        ws: ws where the app should be opened. If there is
            already some app, it will be banished.
    
    Makes sense to state either output or ws, not both
    """
    name: str
    share_screen: list|None = None
    output: str|None = None
    ws: str|None = None

# apps assignment, mostly for "go default" mode
DEFAULT_ASSIGNMENT = [
    DefaultAssignment('discord', ['teamspeak'], ws='2'),
    DefaultAssignment('code', ws='5'),
    DefaultAssignment('navigator', ws='4'), # firefox
    DefaultAssignment('steam', ws='6'),
    DefaultAssignment('obs', output=list(OUTPUTS.keys())[0]),
    DefaultAssignment('mpv', output=list(OUTPUTS.keys())[0]),
    DefaultAssignment('keepassxc', output=list(OUTPUTS.keys())[0]),
    DefaultAssignment('teamspeak', ['discord'], ws='2'),
    DefaultAssignment('obsidian', output=list(OUTPUTS.keys())[0]),
    DefaultAssignment('wireshark', output=list(OUTPUTS.keys())[0]),
]

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
GAMES = ['Planetside2', 'World of Warcraft', 'Мир танков']
# where helper files for i3_manager_genmon are located
I3_HELPER_FILES = '.config/i3/i3_manager_assets/'

