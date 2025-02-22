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
        backup_amount=20
        # sync_gdrive=True,
        # gdrive_args=['ObsidianVault', '--sync-direction', 'mirror', '--ignore', 'path=.obsidian,type=all_files']
    )
}

# =============== colors ======================
# Colors for the binding mode letters
COLORS = {
    'default': '#C0C0C0',
    'launch': '#EE21FB',
    'resize': '#F8FB21',
    'focus': '#00A8E1',
    'run_script': '#7a3582',
    'virt': '#00A8E1',
    'proxy': '#22e417',
}

# =============== ws assignment ===============
# binding some workspaces to actual screens by their outputs
# we could parse it from the config, but more simple to add them here
OUTPUTS = {
    'HDMI-0': {
        'ws': [1, 2, 3],
        'capacity': 1
    },
    'DP-0': {
        'ws': [4, 5, 6, 10],
        'capacity': 2
    }
}

# apps windows are usually bulky enough to want to use it
# solely on the screen. But these apps can appear on the same
# screen without banishing to the new ws. All floating windows
# also don't get banished. If a non banishing app has a ws
# assigned, only one app goes there, the rest stay on the
# screen where they are
NON_BANISHING_APPS = [
    'xfce4-terminal',
    'mousepad'
]

@dataclass
class DefaultAssignment:
    """Describes one app behaviour.
    Only for apps with special ws binding.

        name: app class in lower case
        share_screen: if an app wants to reside on the
            screen alone, put False. True means otehr apps
            can be opened on the same screen if output
            capacity allows
        output: output name, if an app has no assigned ws
            but should be opened on the exact screen
        ws: ws where the app should be opened. If there is
            already some app, it will be banished or added
            next to it if the output capacity allows
    
    Makes sense to state either output or ws, not both
    """
    name: str
    share_screen: bool = True
    output: str|None = None
    ws: int|None = None

# apps assignment, mostly for "go default" mode
DEFAULT_ASSIGNMENT = [
    DefaultAssignment('xfce4-terminal', ws=1),
    DefaultAssignment('discord', ws=2),
    DefaultAssignment('code', share_screen=False, ws=5),
    DefaultAssignment('firefox', ws=4), # firefox
    DefaultAssignment('steam', ws=6),
    DefaultAssignment('obs', output=list(OUTPUTS.keys())[0]),
    DefaultAssignment('mpv', share_screen=False, output=list(OUTPUTS.keys())[0]),
    DefaultAssignment('virt-manager', share_screen=False, output=list(OUTPUTS.keys())[0]),
    DefaultAssignment('keepassxc', output=list(OUTPUTS.keys())[0]),
    DefaultAssignment('teamspeak', ws=2),
    DefaultAssignment('obsidian', output=list(OUTPUTS.keys())[0]),
    DefaultAssignment('wireshark', output=list(OUTPUTS.keys())[0]),
    DefaultAssignment('transmission-gtk', ws=10),
]

# ini file for planetside2 to fix before the start
PS2_DIR = '/mnt/kllisre/SteamLibrary/steamapps/common/PlanetSide 2/'
# I can't come up with commands which i3 can't perform
# so it's important to use nop for new modes
NOP_SHORTCUTS = {
    ('ctrl', 'Mod4', 'd'): 'go_default',
    ('ctrl', 'Mod4', 'm'): 'open_mpv',
    ('ctrl', 'Mod4', 's'): 'exchange_screens',
    ('ctrl', 'Mod4', 'j'): 'move_to_left',
    ('ctrl', 'Mod4', 'semicolon'): 'move_to_right',
}

# screen tags, which whindows will be exchanged with each
# other when 'exchange_screens' was used
EXCHANGE_SCREENS = ('DP-0', 'HDMI-0')

# bindings to which output is left, which is right. Used
# in 'move_to_left' and 'move_to_right'. These are actually
# just tags, can be more of them
LEFT_RIGHT = {
    'move_to_left': 'HDMI-0',
    'move_to_right': 'DP-0'
}

# there are several notification daemons. To properly manage
# notification windows, the window class is required
NOTIFICATION_CLASS = 'xfce4-notifyd'

# # it doesn't make sense to get vsync for all games
# # it doesn't require the game to be in steam
# GAMES_VSYNC = ['planetside2']

# # scripts starting and stopping vsync mode
# VSYNC_START = """
#     nvidia-settings --assign CurrentMetaMode="\
#     DP-0: 2560x1440_59.95 +1920+0 {AllowGSYNCCompatible=On}, \
#     HDMI-0: 1920x1080_60 +0+360"
#     nvidia-settings --assign ShowVRRVisualIndicator=1
#     xrandr --output HDMI-0 --off
# """
# VSYNC_STOP = """
#     xrandr --output HDMI-0 --auto
#     nvidia-settings --assign ShowVRRVisualIndicator=0
#     nvidia-settings --assign CurrentMetaMode="\
#     DP-0: 2560x1440_59.95 +1920+0 {AllowGSYNCCompatible=Off}, \
#     HDMI-0: 1920x1080_60 +0+360"
# """
