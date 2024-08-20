#!/usr/bin/env python3

# The script shows current i3 binding mode via
# notifications. Replaces same feature of i3 bar

import subprocess
from i3ipc import Connection, Event, con
from i3_manager_assets.additional_funcs import (
    make_backup, fix_particles, sendmessage,
    process_searcher, PicomManager, get_the_game_name
)
from i3_manager_assets.windows_account import WindowsAccount
from i3_manager_assets.config import COLORS, BACKUPS
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
# A list of games opened (yeah, makes no sense to open several games 
# simultaneously, but it's possible). When empty we can to cuf off
# extra checks when working with scratchpad. Required to prevent
# steam to show up on top of the game, because it's very hard to
# get into the game again if this happened
GAMES = []
# since there is no way to distinguish a new window parent, then we
# have to assumme that if a new window and focused window have the
# same class, wery likely the focused window is the parent
# of that new window. So we are gonna store it's id
FOCUSED = None


# contains an information about a screen state for quick output
class OneScreen:
    """This class is responsible for tracking the state
    which should be shown on a screen. That "default|h|5".
    One screen - one instance
    """

    def __init__(self, name: str, active_ws: str | None = None, split_type: str | None = None) -> None:
        # turns screen output name into a file name which starts with i3
        self.name = f'/tmp/i3_{name}'
        # currently active workspace
        self.active_ws = active_ws
        # h or v for the output
        self._split_type = split_type
        # splith or splitv, the inner i3ipc value. Required, so we can
        # check, if any changes happened and don't rewrite a file
        self.inner_split_type = None

    @property
    def split_type(self) -> str | None:
        return self._split_type

    @split_type.setter
    def split_type(self, value: str) -> None:
        """Basically shortens the inner identifiers

        Args:
            value (str): the value, used by i3
        """
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
picom_manager = PicomManager(timer_delay=5)
windows_account = WindowsAccount(i3)
windows_account.init_windows()
windows_account._search_ws_for_new_window()

def get_screens() -> None:
    """Gets the information about the initial state of workspaces, like
    active workspaces and their layouts"""

    # Basicly returns an item for each connected screen and xroot in addition
    for screen in i3.get_outputs():
        # we need only physical screens
        if 'xroot' not in screen.name:
            SCREENS[screen.name] = OneScreen(
                                        name=screen.name,
                                        active_ws=screen.current_workspace
                                    )
    # # this is the only way get visible right now workspaces, get_tree() doesn't give this
    # for ws in i3.get_workspaces():
    #     if ws.visible:
    #         SCREENS[ws.output].active_ws = ws.name
    # getting layouts like splitv and splith for each visible workspace
    for ws in i3.get_tree().workspaces():
        for screen in SCREENS.values():
            if screen.active_ws == ws.name:
                screen.split_type = ws.layout
                screen.write_state()

####################### helper functions ##############################

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

def update_binding_modes(focused: con.Con) -> None: # checked
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

############################ event handlers #############################

# def on_mode_change(i3, e) -> None:
#     """Handler of mode change event"""

#     global NOTIFICATION_CON, BINDING_MODE
#     # close a notification from the previous binding mode if happened to be on
#     close_old_notification()
#     # for the genmon we should take only the first word of a binding mode name
#     # and show the rest in a notification
#     new_mode = e.change.split('[')
#     match len(new_mode):
#         # this shouldn't happen, but if it happened then better to know about it
#         case 0:
#             sendmessage('Binding mode без названия', 'Не красиво', timeout='2700')
#         # default, resize - one word modes
#         case 1:
#             BINDING_MODE = new_mode[0]
#             rewrite_all_binding_modes()
#         # long string modes like launch for example
#         case _:
#             # make this variable not None so on_window_new will catch the notification window reference
#             NOTIFICATION_CON = ''
#             BINDING_MODE = new_mode[0].strip()
#             rewrite_all_binding_modes()
#             # split mode name ('Launch [f]irefox [c]hrome') to the mode name and it's bindings (if any)
#             # so we can show it in notification with a title and a list of options
#             sendmessage(BINDING_MODE, '[' + '\n['.join(new_mode[1:]))

def on_window_new(i3, e) -> None:
    """Handler of opening new windows event, saves the container
    into a global variable, if the container belongs to notification daemon,
    saves app class to FOR_BACKUP if the app requires a backup"""

    global NOTIFICATION_CON, FOR_BACKUP, GAMES
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
    # get the non steam game. Such have to be set explicitly
    # in the config. Meant for native games, usually empty
    game = get_the_game_name(e.container)
    # if a window isn't a game, don't continue
    if game is None and not 'steam_app_' in e.container.window_class:
        return
    # if picom was already killed or a killer timer was started
    # no point to continue. Just put the information about
    # this window in the games windows array
    if GAMES:
        GAMES.append(e.container.id)
        return
    # add the game window id in the array for accounting
    GAMES.append(e.container.id)
    # kill picom. The function will decide if it\s necessary
    picom_manager.postponed_picom_killer()

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

    global FOR_BACKUP, GAMES
    # not a window of interest
    if e.container.window_class is None:
        return
    windows_account.window_closed(e.container)
    # if any of apps requiring backup is closing, there should be an item
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
            sendmessage('Backup results', make_backup(app_class), '4000')
    # the rest is related only to the opened
    # and maybe closing now games
    if not GAMES:
        return
    # remove steam from the scratchpad if it's there
    if steam_win := find_in_scratchpad('Steam'):
        for win in steam_win:
            windows_account.bring_from_scratchpad(win)
            # win.command('move container to workspace gaming; floating disable; floating enable')
    # if it's in tray - windows don't exist but processes
    # do, then bring the window
    elif not i3.get_tree().find_classed('Steam') and process_searcher('steam'):
        subprocess.Popen(['steam'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # fix particles in ini
    if 'Planetside2' in e.container.window_class:
        fix_particles()
    # remove the closing game window
    if e.container.id in GAMES:
        GAMES.remove(e.container.id)
    # if there are still games, no point to start the
    # picom. Do it only when the last game window is closed
    if GAMES:
        return
    # start picom. The function will decide if it\s necessary
    picom_manager.postponed_picom_starter()

def on_window_focus(i3, e) -> None:
    """Handler for the window focus event and also for binding event
    Changes the tiling indicator"""

    global FOCUSED
    # to get the correct layout of a container, we have to take it from it's parent
    # the reason isn't really obvious. Unless it's a workspace
    focused = i3.get_tree().find_focused()
    # this is the only way to intercept Steam from appearing over game
    if GAMES and focused.window_class.lower() == 'steam':
        e.container.command('move scratchpad')
        # # in a case ps2 lost it's fullscreen mode
        # w_ps2 = i3.get_tree().find_named('Planetside2')
        # if w_ps2 and w_ps2[0].fullscreen_mode == 0:
        #     w_ps2[0].command('fullscreen enable')
    update_binding_modes(focused.id)
    FOCUSED = focused.id

# def on_binding_change(i3, e) -> None:
#     """Binding change handler. Excludes mode changes,
#     the processing is equal to on_window_focus"""

#     if e.binding.command == 'nop':
#         shortcut = (*e.binding.event_state_mask, e.binding.symbol)
#         match NOP_SHORTCUTS.get(shortcut):
#             case 'assign_windows':
#                 windows_account.go_default()
#                 i3.command('workspace comm; workspace browser')
#                 sendmessage('Go default', 'Applications were brought to their assigned workspaces', '2700')
#             case 'open_mkv':
#                 mpv = subprocess.Popen(['mpv', paste()], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
#                 sendmessage('mpv from clipboard', f'mpv was opened with pid {mpv.pid}')
#             case 'switch_windows':
#                 visible_ws = []
#                 # search for wisible workspaces, save their ids
#                 for ws in i3.get_workspaces():
#                     if ws.visible:
#                         visible_ws.append({'name': ws.name, 'id': ws.ipc_data['id']})
#                 # this shouldn't happen, but in a case of screens amount change
#                 if len(visible_ws) != 2:
#                     return
#                 # get all the direct children of each visible ws, they are in focus
#                 tree = i3.get_tree()
#                 for ws in visible_ws:
#                     ws['focus'] = tree.find_by_id(ws['id']).focus
#                 # exchange windows between ws using temp ws
#                 # otherwise if there is a pseudo container, and it was moved let's say to the
#                 # right, it will soak up all the windows which are already on the right
#                 def move_focus(focus: list, ws: str) -> None:
#                     """Searcher all container ids in focus list and moves them 
#                     to a specifies ws"""
#                     for foc in focus:
#                         tree.find_by_id(foc).command(f'move container to workspace {ws}')
#                 move_focus(visible_ws[0]['focus'], 'temp')
#                 move_focus(visible_ws[1]['focus'], visible_ws[0]['name'])
#                 move_focus(visible_ws[0]['focus'], visible_ws[1]['name'])
#             case _:
#                 return
#     if 'mode' not in e.binding.command:
#         update_binding_modes(i3.get_tree().find_focused())

# def on_window_move(i3, e) -> None:
#     windows_account.window_moved(e.container)

# Initialize files for xfce4 genmons
get_screens()
# initialize the variable. Can happen that it will be
# a workspace, instead of a window, but it won't
# change anything to the logic
FOCUSED = i3.get_tree().find_focused().id
# Subscribe to events
# i3.on(Event.MODE, on_mode_change)
i3.on(Event.WINDOW_NEW, on_window_new)
i3.on(Event.WORKSPACE_FOCUS, on_workspace_focus)
i3.on(Event.WINDOW_CLOSE, on_window_close)
i3.on(Event.WINDOW_FOCUS, on_window_focus)
# i3.on(Event.BINDING, on_binding_change)
# i3.on(Event.WINDOW_MOVE, on_window_move)
# Start the main loop and wait for events to come in.
try:
    i3.main()
except Exception as e:
    sendmessage('ERROR', str(e))
