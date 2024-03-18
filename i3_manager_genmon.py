#!/usr/bin/env python3

# The script shows current i3 binding mode via
# notifications. Replaces same feature of i3 bar

import os
import subprocess
from i3ipc import Connection, Event, con
from datetime import date, datetime
from time import sleep
from threading import Thread
from i3_manager_assets.windows_account import WindowsAccount
# importing already defined user classes to prepare ps2 client settings
from i3_manager_assets.ps2_user import PS2_player
from i3_manager_assets.config import *
from pyperclip import paste

#################### just shared variables ###################
# Notification container
NOTIFICATION_CON = None
# A list of opened apps which require backup for their files
FOR_BACKUP = []
# A currently active binding mode. Assume that it's default because 
# there is no way to request it, only listen to events
BINDING_MODE = 'default'
# All actuall screens. Supposed to hold references to OneScreen
SCREENS = {}
# A flag to cuf off extra checks when working with scratchpad
# needed to prevent stem to show up on top of the game
GAME_MODE = False
                    
# contains an information about a screen state for quick output
class OneScreen:

    def __init__(self, name: str, active_ws: str | None = None, split_type: str | None = None) -> None:
        # turns screen output name into a file name which starts with i3
        self.name = f'/tmp/i3_{name}'
        # currently active workspace
        self.active_ws = active_ws
        # h or v for the output
        self._split_type = split_type
        # splith or splitv, the inner i3ipc value
        self.inner_split_type = None

    @property
    def split_type(self) -> str | None:
        return self._split_type

    @split_type.setter
    def split_type(self, value: str) -> None:
        match value:
            case 'splitv':
                self._split_type = 'v'
            case 'splith':
                self._split_type = 'h'
            case 'tabbed':
                self._split_type = 't'
            case 'stacked':
                self._split_type = 's'
        self.inner_split_type = value               

    def write_state(self) -> None:
        """Forms a colorized string and writes it to a file"""

        with open(self.name, 'w+') as f:
            color = COLORS.get(BINDING_MODE, '#E34234')
            f.write(f'<txt><span foreground="{color}"> {BINDING_MODE}</span> | {self.split_type} | {self.active_ws} </txt>')

####################### initialization ############################

# Create the Connection object that can be used to send commands and subscribe
# to events.
i3 = Connection()
windows_account = WindowsAccount(i3)
windows_account.init_windows()

def get_screens() -> None:
    """Gets the information about the initial state of workspaces, like
    active workspaces and their layouts"""

    # Basicly returns an item for each connected screen and xroot in addition
    for screen in i3.get_outputs():
        # we need only phisical screens
        if 'xroot' not in screen.name:
            SCREENS[screen.name] = OneScreen(screen.name)
    # this is the only way get visible right now workspaces, get_tree() doesn't give this
    for ws in i3.get_workspaces():
        if ws.visible:
            SCREENS[ws.output].active_ws = ws.name
    # getting layouts like splitv and splith for each visible workspace
    for ws in i3.get_tree().workspaces():
        for screen in SCREENS.values():
            if screen.active_ws == ws.name:
                screen.split_type = ws.layout
                screen.write_state()

####################### helper functions ##############################

def sendmessage(title: str, message: str='', timeout: str='0') -> None:
    """Sends a message to notification daemon in a separate process.
    urgency=critical makes a message stay until closed manually,
    for other message types types don't forget timeout"""

    # uses i3 icon for the message
    icon = '/usr/share/doc/i3/logo-30.png'
    subprocess.Popen(['notify-send', '-i', icon, '-t', timeout, title, message])

def process_searcher(proc_name: str) -> None:
    """Searches the process by name, returns True if found"""        

    try:
        subprocess.check_output(['pgrep', '-U', str(os.getuid()), proc_name])
        return True
    except subprocess.CalledProcessError:
        return False

def process_killer(proc_name: str) -> None:
    """Tries to gently kill a process for three times, then tries
    to terminate it if no success"""

    try:
        for _ in range(3):
            # gentle kills a user owned process
            if process_searcher(proc_name):
                subprocess.Popen(['pkill', '-U', str(os.getuid()), proc_name])
            else:
                break
            sleep(1)
        else:
            # terminate
            if process_searcher(proc_name):
                subprocess.Popen(['pkill', '-9', '-U', str(os.getuid()), proc_name])    
    except subprocess.CalledProcessError:
        pass

def rewrite_all_binding_modes() -> None:
    """Updates binding mode for all screens/files because the mode is global"""

    for v in SCREENS.values():
        v.write_state()

def close_old_notification() -> None:
    """Closes the current, binding mode related notification and
    sets NOTIFICATION_CON to default"""

    # if NOTIFICATION_CON has a reference to a container - the notification has to be killed
    global NOTIFICATION_CON
    if isinstance(NOTIFICATION_CON, con.Con):
        NOTIFICATION_CON.command('kill')
    # set to defaul
    NOTIFICATION_CON = None

def find_in_scratchpad(w_class: str) -> list:
    """Helper function. Searches for a specified window class in the
    scratchpad. We could just store container scratchpad references,
    but this is more universal option"""

    scratchpad = i3.get_tree().scratchpad()
    return scratchpad.find_classed(w_class)

def update_binding_modes(focused: con.Con) -> None:
    """Updates the information about layout types.
    Takes focused because this container is also used
    in caller functions"""

    if focused.type == 'workspace':
        layout = focused.layout
    else:
        layout = focused.parent.layout
    output = focused.ipc_data['output']
    # refresh a file if layout changed
    if SCREENS[output].inner_split_type != layout:
        SCREENS[output].split_type = layout
        SCREENS[output].write_state()    

def get_the_game_name(container: con.Con) -> str | None:
    """Checks if a given container has the name attribute at all,
    and if it has, then checks if it's a steam game and if
    it's in GAMES, returns the GAMES item"""
    # if there is no name or it's not a steam app, break
    if 'steam_app_' in container.window_class and hasattr(container, 'name'):
        game_name = str(container.name)
    else:
        return
    # Check if this app is in the list
    for game in GAMES:
        if game in game_name:
            return game

def get_newest_mtime(source_path: str) -> int:
    """Returns mtime of a newest file in a given path,
    rounded to int, ignoring dotfiles/dotdirs"""
    max_mtime = 0
    # recursivly walk the directory
    for root, _, files in os.walk(source_path):
        # ignore dotfiles/dotdirs
        if not '/.' in root:
            # iterate over all files in a current dir
            for file in files:
                # if a file is newer, than we met before - update the value
                file_mtime = os.path.getmtime(os.path.join(root, file))
                if file_mtime > max_mtime:
                    max_mtime = file_mtime
    return int(max_mtime)

############################ event handlers #############################

def on_mode_change(i3, e) -> None:
    """Handler of mode change event"""

    global NOTIFICATION_CON, BINDING_MODE
    # close a notification from the previous binding mode if happened to be on
    close_old_notification()
    # for the genmon we should take only the first word of a binding mode name
    # and show the rest in a notification
    new_mode = e.change.split('[')
    match len(new_mode):
        # this shouldn't happen, but if it happened then better to know about it
        case 0:
            sendmessage('Binding mode без названия', 'Не красиво', timeout='2700')
        # default, resize - one word modes
        case 1:
            BINDING_MODE = new_mode[0]
            rewrite_all_binding_modes()
        # long string modes like launch for example
        case _:
            # make this variable not None so on_window_new will catch the notification window reference
            NOTIFICATION_CON = ''
            BINDING_MODE = new_mode[0].strip()
            rewrite_all_binding_modes()
            # split mode name ('Launch [f]irefox [c]hrome') to the mode name and it's bindings (if any)
            # so we can show it in notification with a title and a list of options
            sendmessage(BINDING_MODE, '[' + '\n['.join(new_mode[1:]))

def on_window_new(i3, e) -> None:
    """Handler of opening new windows event, saves the container
    into a global variable, if the container belongs to notification daemon,
    saves app class to FOR_BACKUP if the app requires a backup"""

    global NOTIFICATION_CON, FOR_BACKUP, GAME_MODE
    # if it's not any window of interest
    if e.container.window_class is None:
        return
    windows_account.window_opened(e.container)
    # grab only notifications and only if it's expected when NOTIFICATION_CON is ''
    if NOTIFICATION_CON == '' and e.container.window_class == 'Xfce4-notifyd':
        NOTIFICATION_CON = e.container
        return
    # store the app class name as a flag that there was an app opened, which needs a backup
    if (app_class := e.container.window_class.lower()) in BACKUPS.keys():
        FOR_BACKUP.append(app_class)
        return
    # if mpv is opened, switch to it's ws
    if e.container.window_class == 'mpv':
        # get all mps windows
        mpv = windows_account.get_tracked_windows_by_class('mpv')
        for win in mpv:
            # swicth to the ws, containing one, which was opened in this event
            if win.w_id == e.container.id:
                i3.command(f'workspace {win.w_current_ws}')
        return
    game = get_the_game_name(e.container)
    if game is None:
        return
    if not GAME_MODE:
        GAME_MODE = True
        taskkiller = Thread(target=process_killer('picom'))
        taskkiller.start()

def on_workspace_focus(i3, e) -> None:
    """Changes the current workspace number for a screen"""

    output = e.current.ipc_data['output']
    if SCREENS[output].active_ws != e.current.name:
        SCREENS[output].active_ws = e.current.name
        SCREENS[output].write_state()

def on_window_close(i3, e) -> None:
    """Backups dir/files when the application, which needs it, is closed.
    Keeps three backups total, overwrites the oldest one. Also tracks
    if a game from GAMES was closed, so the GAME_MODE should be set to off"""

    global FOR_BACKUP, GAME_MODE
    # not a window of interest
    if e.container.window_class is None:
        return
    windows_account.window_closed(e.container)
    # if any of apps requiring backup is closing, there should be a flag
    # in FOR_BACKUP that one of such apps was opened. Also we react
    # only to the last windows of such class
    # not empty
    if FOR_BACKUP:
        # closing window is in there
        if (app_class := e.container.window_class.lower()) in FOR_BACKUP:
            FOR_BACKUP.remove(app_class)
            # it shoud be the last window, thus shouldn't be in this list
            if app_class in FOR_BACKUP:
                return
            # create the backup directory, in a case it doesn't exist
            os.makedirs(BACKUPS[app_class].backup_dir, exist_ok=True)
            # in the backup destination path should be n directories, named by timestamps
            # when the backup was done. But in one day only one backup directory getting
            # overwriten. Thus, first we need to get the backup directory content and
            # analyze  names there
            backup_dir_content = []
            # get backup dir content
            for dir in os.listdir(BACKUPS[app_class].backup_dir):
                if os.path.isdir(os.path.join(BACKUPS[app_class].backup_dir, dir)) and dir.isdigit():
                    backup_dir_content.append(dir)
            # get the newest mtime of the source location and check if backup not needed
            newest_mtime = str(get_newest_mtime(BACKUPS[app_class].source_location))
            if newest_mtime in backup_dir_content:
                return
            # cp -u hangs if we give no input files, so we should check if there are files
            # and it overall makes no sense to backup nothing
            files_to_backup = [os.path.join(BACKUPS[app_class].source_location, file) for file in os.listdir(BACKUPS[app_class].source_location)]
            if not files_to_backup:
                return
            # on this point it's established that a backup is required, so if an app's data
            # requires syncing with gdrive, we do it here
            if BACKUPS[app_class].sync_gdrive:
                # if the gdrive folder name wasn't stated in the config.py, relying to default
                # then pull out the nearest name from the path
                gdrive_folder = BACKUPS[app_class].gdrive_path
                if not gdrive_folder:
                    gdrive_folder = os.path.basename(BACKUPS[app_class].source_location.strip('/'))
                # we also need to temporarily switch the working directory because the
                # gdrive sync script has some files in it's root direcory to work with
                current_dir = os.getcwd()
                os.chdir(os.path.dirname(GDRIVE['script_path']))
                subprocess.Popen([
                    GDRIVE['python_path'],
                    GDRIVE['script_path'],
                    BACKUPS[app_class].source_location,
                    gdrive_folder,
                    '--ignore-directories',
                    'path=.obsidian,type=all_files'
                ])
                os.chdir(current_dir)
            # updating today backup
            for item in backup_dir_content:
                # updating today's backup. Converting from timestamp to compare with today date
                if datetime.fromtimestamp(int(item)).date() == date.today():
                    subprocess.run([
                        'cp',
                        '-ur',
                        *files_to_backup,
                        os.path.join(BACKUPS[app_class].backup_dir, item)
                    ])
                    sendmessage('Backup updated', f'Today backup of <b>{app_class}</b> was updated', '4000')
                    return
            # there is no today backup
            else:
                # creating today's backup directory
                today_backup_dir = os.path.join(BACKUPS[app_class].backup_dir, newest_mtime)
                os.mkdir(today_backup_dir)
                # copying contents
                subprocess.run(['cp', '-r', *files_to_backup, today_backup_dir])
                sendmessage('Backup created', f'Today backup of <b>{app_class}</b> was created', '4000')
                # now we have to check if there are too many backups and delete unnecessary
                if (backup_amount := len(backup_dir_content) + 1) > BACKUPS[app_class].backup_amount:
                    # sort by names which are dates
                    backup_dir_content.sort()
                    # extend to full paths
                    backup_dir_content = [ os.path.join(BACKUPS[app_class].backup_dir, dir) for dir in backup_dir_content ]
                    subprocess.run(['rm', '-r', *backup_dir_content[:backup_amount - BACKUPS[app_class].backup_amount]])
                return
    # check if one of the games is exited
    game = get_the_game_name(e.container)
    if game is None:
        return
    GAME_MODE = False
    # fix particles in ini
    if game == 'Planetside2':
        PS2_player.fix_particles(f'{PS2_DIR}UserOptions.ini')
    # remove steam from the scratchpad
    if steam_win := find_in_scratchpad('Steam'):
        for win in steam_win:
            win.command('move container to workspace gaming; floating disable; floating enable')
    # if it's in tray - bring the window
    elif not i3.get_tree().find_classed('Steam'):
        subprocess.Popen(['steam'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not process_searcher('picom'):
        subprocess.Popen(['picom', '-b'])

def on_window_focus(i3, e) -> None:
    """Handler for the window focus event and also for binding event
    Changes the tiling indicator"""

    # to get the correct layout of a container, we have to take it from it's parent
    # the reason isn't really obvious. Unless it's a workspace
    focused = i3.get_tree().find_focused()
    # this is the only way to intercept Steam from appearing over game
    if GAME_MODE and focused.window_class == 'Steam':
        e.container.command('move scratchpad')
        # in a case ps2 lost it's fullscreen mode
        w_ps2 = i3.get_tree().find_named('Planetside2')
        if w_ps2 and w_ps2[0].fullscreen_mode == 0:
            w_ps2[0].command('fullscreen enable')
    update_binding_modes(focused)

def on_binding_change(i3, e) -> None:
    """Binding change handler. Excludes mode changes,
    the processing is equal to on_window_focus"""

    if e.binding.command == 'nop':
        shortcut = (*e.binding.event_state_mask, e.binding.symbol)
        match NOP_SHORTCUTS.get(shortcut):
            case 'assign_windows':
                windows_account.go_default()
                i3.command('workspace comm; workspace browser')
                sendmessage('Go default', 'Applications were brought to their assigned workspaces', '2700')
            case 'open_mkv':
                mpv = subprocess.Popen(['mpv', paste()], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                sendmessage('mpv from clipboard', f'mpv was opened with pid {mpv.pid}')
            case 'switch_windows':
                visible_ws = []
                # search for wisible workspaces, save their ids
                for ws in i3.get_workspaces():
                    if ws.visible:
                        visible_ws.append({'name': ws.name, 'id': ws.ipc_data['id']})
                # this shouldn't happen, but in a case of screens amount change
                if len(visible_ws) != 2:
                    return
                # get all the direct children of each visible ws, they are in focus
                tree = i3.get_tree()
                for ws in visible_ws:
                    ws['focus'] = tree.find_by_id(ws['id']).focus
                # exchange windows between ws using temp ws
                # otherwise if there is a pseudo container, and it was moved let's say to the
                # right, it will soak up all the windows which are already on the right
                def move_focus(focus: list, ws: str) -> None:
                    """Searcher all container ids in focus list and moves them 
                    to a specifies ws"""
                    for foc in focus:
                        tree.find_by_id(foc).command(f'move container to workspace {ws}')
                move_focus(visible_ws[0]['focus'], 'temp')
                move_focus(visible_ws[1]['focus'], visible_ws[0]['name'])
                move_focus(visible_ws[0]['focus'], visible_ws[1]['name'])
            case _:
                return
    if 'mode' not in e.binding.command:
        update_binding_modes(i3.get_tree().find_focused())

def on_window_move(i3, e) -> None:
    windows_account.window_moved(e.container)
# Initialize files for xfce4 genmons
get_screens()
# Subscribe to events
i3.on(Event.MODE, on_mode_change)
i3.on(Event.WINDOW_NEW, on_window_new)
i3.on(Event.WORKSPACE_FOCUS, on_workspace_focus)
i3.on(Event.WINDOW_CLOSE, on_window_close)
i3.on(Event.WINDOW_FOCUS, on_window_focus)
i3.on(Event.BINDING, on_binding_change)
i3.on(Event.WINDOW_MOVE, on_window_move)
# Start the main loop and wait for events to come in.
try:
    i3.main()
except Exception as e:
    sendmessage('ERROR', str(e))
