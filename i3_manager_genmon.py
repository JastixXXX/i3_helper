#!/usr/bin/env python3

# The script shows current i3 binding mode via
# notifications. Replaces same feature of i3 bar

import subprocess
from traceback import format_exc
from pyperclip import paste
from re import fullmatch, IGNORECASE
from i3ipc import Connection, Event, con
from time import sleep
from pyautogui import write
from i3_manager_assets.windows_account import WindowsAccount
from i3_manager_assets.additional_funcs import (
    make_backup, fix_particles, sendmessage,
    CompositorManager, it_is_a_game, ersatz_clipboard_paste
)
from i3_manager_assets.config import (
    BACKUPS, GENMON_OUTPUT_MAPPING, COLORS,
    NOTIFICATION_CLASS, NOP_SHORTCUTS, EXCHANGE_SCREENS,
    VIDEOPLAYER
)


#################### just shared variables ###################
# Notification container
NOTIFICATION_CON = None
# A currently active binding mode. Assume that it's default because 
# there is no way to request it, only listen to events
BINDING_MODE = 'default'
# All actual screens. Supposed to hold references to OneScreen
SCREENS = {}
# since there is no way to distinguish a new window parent, then we
# have to assume that if a new window and focused window have the
# same class, very likely the focused window is the parent
# of that new window. So we are gonna store it's id
FOCUSED = 0
              
# contains an information about a screen state for quick output
class OneScreen:
    """This class is responsible for tracking the state
    which should be shown on a screen. That "default|h|5".
    One screen - one instance
    """

    def __init__(self, name: str, active_ws: str|None=None, split_type: str|None=None) -> None:
        # turns screen output name into a file name which starts with i3
        self.name = f'/tmp/i3_{name}'
        # currently active workspace
        self.active_ws = active_ws
        # h or v for the output
        self._split_type = split_type
        # splith or splitv, the inner i3ipc value. Required, so we can
        # check, if any changes happened and don't rewrite a file
        self.inner_split_type = None
        # take the proper genmon name from settings
        self.genmon = GENMON_OUTPUT_MAPPING[name]

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
        """Forms a colorized string and writes it to a file,
        calls the refresh command on a proper genmon
        """
        with open(self.name, 'w+') as f:
            color = COLORS.get(BINDING_MODE, '#E34234')
            f.write(f'<txt><span foreground="{color}"> {BINDING_MODE}</span> ⬩ {self.split_type} ⬩ {self.active_ws} </txt>')
        # refresh the genmon, the process result and output isn't interesting
        subprocess.Popen(
            ['xfce4-panel', f'--plugin-event={self.genmon}:refresh:bool:true'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

####################### initialization ############################

# Create the Connection object that can be used to send commands and subscribe
# to events. Connection() without parameters may not work sometimes. Find the socket
# for the robustness. Also give i3 some time to get up in a case the script is
# called not from i3 config, but, for example, as a systemd unit
# do 10 attempts to get the socket
socket_path = ''
for _ in range(10):
    try:
        socket_path = str(subprocess.check_output(["i3", "--get-socketpath"]).decode().strip())
        # we got the socket, no need to wait anymore
        break
    # if i3 is not running yet, subprocess.CalledProcessError will return non-zero exit code
    except subprocess.CalledProcessError:
        sleep(1)
# if i3 didn't open it's socket within 10 seconds
if not socket_path:
    exit(1)
i3 = Connection(socket_path)
picom_manager = CompositorManager(timer_delay=5)
windows_account = WindowsAccount(i3)
windows_account.init_windows()

def get_screens() -> None:
    """Gets the information about the initial state of workspaces, like
    active workspaces and their layouts
    """
    # Basically returns an item for each connected screen and xroot in addition
    for screen in i3.get_outputs():
        # we need only physical screens
        if 'xroot' not in screen.name:
            SCREENS[screen.name] = OneScreen(name=screen.name)
    # this is the only way get visible right now workspaces, get_tree() doesn't give this
    for ws in i3.get_workspaces():
        if ws.visible:
            SCREENS[ws.output].active_ws = ws.num
    for ws in i3.get_tree().workspaces():
        for screen in SCREENS.values():
            if screen.active_ws == ws.num:
                screen.split_type = ws.layout
                screen.write_state()

####################### helper functions ##############################

def rewrite_all_binding_modes() -> None:
    """Updates binding mode for all screens/files because the mode is global
    """
    for v in SCREENS.values():
        v.write_state()


def close_old_notification() -> None:
    """Closes the current, binding mode related notification and
    sets NOTIFICATION_CON to default
    """
    # if NOTIFICATION_CON has a reference to a container - the notification has to be killed
    global NOTIFICATION_CON
    if isinstance(NOTIFICATION_CON, con.Con):
        NOTIFICATION_CON.command('kill')
    # set to default
    NOTIFICATION_CON = None


def update_binding_modes(focused: con.Con) -> None: # checked
    """Updates the information about layout types. Takes focused
    because this container is also used in caller functions
    """
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

def on_mode_change(i3, e) -> None:
    """Handler of mode change event
    """
    global NOTIFICATION_CON, BINDING_MODE
    # close a notification from the previous binding mode if happened to be on
    close_old_notification()
    # for the genmon we should take only the first word of a binding mode name
    # and show the rest in a notification
    new_mode = e.change.split('[')
    match len(new_mode):
        # this shouldn't happen, but if it happened then better to know about it
        case 0:
            sendmessage('Binding mode without name', 'It is not good', timeout='2700')
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
            sendmessage(BINDING_MODE, '[' + '\n['.join(new_mode[1:]), urgency='critical')


def on_window_new(i3, e) -> None:
    """Handler of opening new windows event, saves the container
    into a global variable, if the container belongs to notification daemon,
    saves app class to FOR_BACKUP if the app requires a backup
    """
    global NOTIFICATION_CON
    # if it's not any window of interest
    if e.container.window_class is None:
        return
    windows_account.window_opened(e.container, FOCUSED)
    # if there is some game - steam one or a native one,
    # turn off picom and redshift
    if it_is_a_game(e.container.window_class):
        # kill picom. The function will decide if it's necessary
        windows_account.stop_eye_candy_services(picom_manager)
        return
    # grab only notifications and only if it's expected when NOTIFICATION_CON is ''
    if NOTIFICATION_CON == '' and e.container.window_class.lower() == NOTIFICATION_CLASS:
        NOTIFICATION_CON = e.container
        return
    # if video player is opened, switch to it's ws
    if fullmatch(VIDEOPLAYER, e.container.window_class, IGNORECASE):
        # get all player windows
        player = windows_account._get_tracked_windows_by_class(VIDEOPLAYER)
        for win in player:
            # switch to the ws, containing one, which was opened in this event.
            if win.w_con_id == e.container.id:
                i3.command(f'workspace {win.w_current_ws}')
        return


def on_workspace_focus(i3, e) -> None:
    """Changes the current workspace number for a screen
    """
    output = e.current.ipc_data['output']
    if SCREENS[output].active_ws != e.current.name:
        SCREENS[output].active_ws = e.current.name
        SCREENS[output].write_state()


def on_window_close(i3, e) -> None:
    """Backups dir/files when the application, which needs it, is closed.
    Keeps three backups total, overwrites the oldest one. Also tracks
    if a game was closed, it should be deleted from the list
    """
    # not a window of interest
    if e.container.window_class is None:
        return
    windows_account.window_closed(e.container)
    # check if the closing app requires backup. It also makes sense
    # only if it's the last this app window
    for app_name_pattern in BACKUPS.keys():
        if fullmatch(app_name_pattern, e.container.window_class, IGNORECASE):
            # look for other windows of this class, if non - make backup
            if not windows_account._get_tracked_windows_by_class(app_name_pattern):
                sendmessage('Backup results', make_backup(app_name_pattern), '4000')
            return
    # check if a game is exited
    if it_is_a_game(e.container.window_class):
        # fix particles in ini, if it's ps2
        if (hasattr(e.container, 'name') and e.container.name is not None and
            'planetside2' in e.container.name.lower()):
            fix_particles()
        # remove steam from the scratchpad, if the last steam game exited,
        # start picom if there are no games anymore.
        # all checks will be done inside those functions
        windows_account.show_steam()
        windows_account.start_eye_candy_services(picom_manager)


def on_window_focus(i3, e) -> None:
    """Handler for the window focus event and also for binding event
    Changes the tiling indicator
    """
    global FOCUSED
    # to get the correct layout of a container, we have to take it from it's parent
    # the reason isn't really obvious. Unless it's a workspace
    focused = i3.get_tree().find_focused()
    if focused.window_class is None:
        return
    # this is the only way to intercept Steam from appearing over game
    if focused.window_class.lower() == 'steam':
        windows_account.hide_steam(e.container)
    update_binding_modes(focused)
    FOCUSED = focused.id


def on_binding_change(i3, e) -> None:
    """Binding change handler. Excludes mode changes,
    the processing is equal to on_window_focus
    """
    if e.binding.command.startswith('nop'):
        shortcut = (*e.binding.event_state_mask, e.binding.symbol)
        match NOP_SHORTCUTS.get(shortcut):
            case 'go_default':
                windows_account.go_default()
                sendmessage('Go default', 'Applications were brought to their assigned workspaces', '2700')
            case 'open_mpv':
                mpv = subprocess.Popen(['mpv', paste()], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                sendmessage('mpv from clipboard', f'mpv was opened with pid {mpv.pid}', urgency='critical')
            case 'exchange_screens':
                # search for visible workspaces, save their ids
                visible_ws = []
                for ws in i3.get_workspaces():
                    if ws.visible and ws.output in EXCHANGE_SCREENS:
                        visible_ws.append(ws.ipc_data['id'])
                # we can command to children windows of a ws.
                # but first get actual containers from ids
                ws_cons = []
                for ws_id in visible_ws:
                    # we don't work with such
                    # if any of these workspaces are named - return
                    if (ws_con := i3.get_tree().find_by_id(ws_id)).num == -1:
                        return
                    ws_cons.append(ws_con)
                # use temporary ws99 as a buffer
                ws_cons[1].command_children('move container to workspace 99')
                ws_cons[0].command_children(f'move container to workspace {ws_cons[1].num}')
                # find ws99 container
                for ws in i3.get_tree().workspaces():
                    if ws.num == 99:
                        ws.command_children(f'move container to workspace {ws_cons[0].num}')
                        break
            case 'move_to_left':
                windows_account.move_left_right('move_to_left', i3.get_tree().find_focused())
            case 'move_to_right':
                windows_account.move_left_right('move_to_right', i3.get_tree().find_focused())
            case 'paste_clipboard':
                ersatz_clipboard_paste()
            case _:
                return
    if 'mode' not in e.binding.command:
        update_binding_modes(i3.get_tree().find_focused())


def on_window_move(i3, e) -> None:
    windows_account.window_moved(e.container)


def on_window_floating(i3, e) -> None:
    windows_account.window_floating_changed(e.container)


# Initialize files for xfce4 genmons
get_screens()
# initialize the variable. Can happen that it will be
# a workspace, instead of a window, but it won't
# change anything to the logic
FOCUSED = i3.get_tree().find_focused().id
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
except Exception:
    sendmessage('ERROR', format_exc(), urgency='critical')
