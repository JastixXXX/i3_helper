from i3ipc import Connection, con
from i3_manager_assets.config import (
    OUTPUTS, DEFAULT_ASSIGNMENT, NON_BANISHING_APPS
)
from time import sleep
from os.path import expanduser


class WindowsAccount:
# A class to store information about the majority of applications (their windows)
# Stores configured apps for the option to banish such windows to other workspaces
# or put applications with default assignment to workspaces to make "go default" work
    class App:
        """A class to store information about one window.
        if duplicateds the info from default assignment,
        but shouldn't have too much of impact to the
        performance

            w_id: an id of the exact window
            w_cls: class name of it
            w_current_ws: the ws where window is currently located
            w_default_ws: the assigned ws for this window if set
            w_sharing: a list of app, allowed to share the ws
            w_default_output: the output where window assigned to be
            w_current_output: the output where the windows is now
            w_parent_id: if a window was spawned by another window,
                    the id of this another window be recorded here
        """
        def __init__(
            self,
            w_id: int,
            w_cls: str,
            w_current_ws: str,
            w_default_ws: str|None = None,
            w_sharing: list|None = None,
            w_default_output: str|None = None,
            w_current_output: str|None = None,
            w_parent_id: int|None = None
        ) -> None:
            self.w_id = w_id
            self.w_cls = w_cls.lower()
            self.w_default_ws = w_default_ws
            self.w_current_ws = w_current_ws
            self.w_sharing = w_sharing
            self.w_default_output = w_default_output
            self.w_current_output = w_current_output
            self.w_parent_id = w_parent_id

    def __init__(self, i3: Connection) -> None:
        self.windows = []
        self.i3 = i3
        # get data about ws assignment to outputs
        self._get_ws_assignment()

    def _get_ws_assignment(self) -> None:
        """Config is the only way to get workspaces,
        assigned to exact outputs
        """
        self.ws_to_output = {}
        with open(expanduser('~/.config/i3/config'), 'r') as f:
            # parse line by line
            for line in f:
                # split by spaces
                parts = line.strip().split()
                # we are looking for lines like 'workspace 2 output primary',
                # 'workspace 5 output VGA1 LVDS1' or 'workspace "2: vim" output VGA1'
                if parts and parts[0] == 'workspace' and 'output' in parts:
                    output = parts.index('output')
                    # get everything between "workspace" and "output"
                    workspace = ' '.join(parts[1:output]).lstrip('$ws')
                    self.ws_to_output[workspace] = parts[output + 1]
              
    def _get_tracked_windows_of_ws(self, ws: str) -> list:
        """Returns all tracked windows of a given ws"""
        ws_windows = []
        for win in self.windows:
            if win.w_current_ws == ws:
                ws_windows.append(win)
        return ws_windows

    def _get_new_container(self, w_id: int) -> con.Con | None:
        """The container, returned by the event handler,
        isn't integrated into a tree yet, thus stuff like
        parent or ws can be None, so it requires to find
        this container again"""
        new_con = self.i3.get_tree().find_by_id(w_id)
        if new_con is not None:
            return new_con
        # give it another try with a bit more time
        sleep(0.2)
        return self.i3.get_tree().find_by_id(w_id)

    def _move_window(self, win: App, ws: str | None = None) -> None:
        """Moves the given app to another ws. Finds
        new ws or moves to a given one"""
        self._print_windows('move')
        # find new window container just to grab the layout
        # just a window.command doesn't require it
        new_win_con = self._get_new_container(win.w_id)
        # some apps spwan and despawn windows, so a container can be None
        if new_win_con is None:
            # remove it from the accounting
            self.windows.remove(win)
        else:
            if ws is None:
                new_ws = self._search_ws_for_new_window(win)
                # always switch to the moving ws, otherwise the other one, currently
                # focused will be moved.
                new_win_con.command(f'move container to workspace {new_ws}; workspace {new_ws};')
                # # update the location of the container
                # win.w_current_ws = new_ws
                # new_win_con.command(f'move container to workspace {new_ws}; workspace {new_ws}; '
                #                     f'move workspace to output {screen}; layout {new_win_con.parent.layout}')
            else:
                new_win_con.command(f'move container to workspace {ws}; workspace {ws}')
               
    def get_tracked_windows_by_class(self, w_cls: str) -> list:
        """Searches already opened windows of the same class, returns
        a list of them"""
        return [ win for win in self.windows if win.w_cls == w_cls ]
    
    def _get_tracked_windows_by_id(self, w_id: int) -> App|None:
        """Searches a window with some id among already opened windows"""
        for win in self.windows:
            if win.w_id == w_id:
                return win

    def _search_ws_for_new_window(self, app: App) -> int:
        """Apps have their predefined workspaces, but if the screen
        capacity is exceeded or conflicting with other apps on the same ws
        a new ws should be found. We are gonna simply go from ws num 1 to
        30, which is a sane number and see if can place our app there. It
        should also stay on the same screen, as it's now"""
        # we also should take into account existing ws-es, because
        # they could be moved to another screen, so ditch those,
        # which reside on the another screen(s)
        ws_existing = {
            'this_screen': [],
            'other_screens': []
        }
        for ws in self.i3.get_tree().workspaces():
            if ws.ipc_data['output'] == app.w_current_output:
                ws_existing['this_screen'].append(ws.num)
            else:
                ws_existing['other_screens'].append(ws.num)
        for num in range(1, 31):
            # ws is already on another screen
            if num in ws_existing['other_screens']:
                continue
            # ws is assigned to another screen in config
            if self.ws_to_output.get(num, '') != app.w_current_output:
                continue
            # if ws is empty - it's the result, which means it's
            # not included in existing ws
            if not num in ws_existing['this_screen']:
                return num
            # if ws isn't empty, we should check, if can place
            # this app there
            ws_windows = self._get_tracked_windows_of_ws(app.w_current_ws)
            if (len(ws_windows) > OUTPUTS[app.w_current_output]['capacity'] or
                self._detect_conflicts(ws_windows, app)):
                continue
            return num
            
    def _get_window(self, window: con.Con, parent_id: int|None = None) -> App|None:
        """Creates a class for windows accounting from a container data"""
        w_container = self._get_new_container(window.id)
        # create an App with parametersh which exist for sure
        app = self.App(
            w_cls=w_container.window_class,
            w_id=w_container.id,
            w_current_ws=w_container.workspace().name,
            w_current_output=w_container.ipc_data['output'],
            w_parent_id=parent_id            
        )
        # now check if there are special settings for this app
        settings = None
        for def_ass in DEFAULT_ASSIGNMENT:
            if def_ass.name == app.w_cls:
                settings = def_ass
                break
        if settings is None:
            return app
        app.w_default_ws =settings.ws
        app.w_default_output = settings.output
        app.w_sharing = settings.share_screen
        return app

    # def _remove_window_from_accounting(self, w_id: int) -> None:
    #     """Searches the windows by it's id and removes
    #     it from the list self.windows"""
    #     if (win := self._window_accounted(w_id)) is not None:
    #         self.windows.remove(win)

    def _update_ws(self, w_id: int) -> None:
        """Refreshes a workspace of a window if it was moved.
        Requests a new container of a window in a case the
        old one stopped to exist"""
        win_con = self._get_new_container(w_id)
        app = self._get_tracked_windows_by_id(w_id)
        # if for some reason the container stopped to exist, it should be removed
        if win_con is None:
            self.windows.remove(app)
            return
        # if window and still exists, we can grab it's workspace
        app.w_current_ws = win_con.workspace().name
        app.w_current_output = win_con.ipc_data['output']

    def _detect_conflicts(self, ws_windows: list[App], new_app: App) -> bool:
        """Two cases for screen sharing are available:
        an app may don't care who to share with, or an app
        may have a list of apps to share screen with. This
        list can also be empty, so it doesn't want
        other apps to come

        Args:
            ws_windows (list[App]): a list of already existing
                    on the ws windows. They can be conflicting
                    to each other
            new_app (App): a new app, which was placed to the
                    ws by default

        Returns:
            bool: True if a new app or any of existing apps
                    don't want to share screen
        """
        # the new app has a list of allowed apps to share with
        if (new_app.w_sharing is not None and
            not all([ other_w.w_cls in new_app.w_sharing for other_w in ws_windows ])):
            return True
        # if any of other apps don't want to share with this one
        for app in ws_windows:
            if (app.w_sharing is not None and
                not new_app.w_cls in app.w_sharing):
                return True
        # there are np conflicts
        return False

    def _print_windows(self, func_name: str = '') -> None:
        """for debug purposes"""
        print(f'------------{func_name}-------------')
        for num, win in enumerate(self.windows):
            print(f'{num}. id: {win.w_id} | class: {win.w_cls} | default ws: '
                  f'{win.w_default_ws} | current ws: {win.w_current_ws} | '
                  f'default output: {win.w_default_output} | current output: {win.w_current_output}'
                  f' | sharing: {win.w_sharing} | parent id: {win.w_parent_id}')

    def init_windows(self) -> None: # checked
        """Loops over all existing windows to store the windows of interest"""
        for win in self.i3.get_tree().leaves():
            # we don't track pseudocontainers
            if win.window_class is None:
                continue
            self.windows.append(self._get_window(win))

    def window_opened(self, window: con.Con, focused: int) -> None: # checked
        """Function for window open event. Stores the windows of interest,
        banishes the conflicting windows if one is opened or residing on
        a predefined ws of an opened window. Unless there are already
        windows of the same class on the ws"""
        self._print_windows('open')
        # if a pseudocontainer
        if window.window_class is None:
            return
        # extract data to the class App, taking parent id if
        # assuming a parent exists. Also get last focused window
        # by it's given id
        focused_con = self._get_new_container(focused)
        new_window = self._get_window(
            window,
            focused if focused_con.window_class == window.window_class else None
        )
        # if a new window was spawned by an existing one -
        # move new one on it's ws
        if new_window.w_parent_id is not None:
            # get tracked parent window
            parent = self._get_tracked_windows_by_id(new_window.w_parent_id)
            # add a new window to it's presumable parent
            self._move_window(new_window, parent.w_current_ws)
            # now we can append it
            self.windows.append(new_window)
            return 
        # append the new window regardless
        self.windows.append(new_window)
        # if a new window is among non banising or floating,
        # nothing has to be done
        if (new_window.w_cls in NON_BANISHING_APPS or
            window.floating in ['auto_on', 'user_on']):
            return
        # request the list of windows where the new window residing
        ws_windows = self._get_tracked_windows_of_ws(new_window.w_current_ws)
        # we should banich window if the ws is full in it's output
        # capacity, or if new window or existing on this ws windows
        # dont' allow each other
        if (len(ws_windows) > OUTPUTS[new_window.w_current_output]['capacity'] or
            self._detect_conflicts(ws_windows, new_window)):
            self._move_window(new_window)
    
    def window_closed(self, window: con.Con) -> None: # checked
        """Removes windows from accounting if it was sthere"""
        self._print_windows('close')
        self.windows.remove(self._get_tracked_windows_by_id(window.id))

    def window_moved(self, window: con.Con) -> None:
        """Refreshes the current ws of a window, if it's accounted"""
        self._print_windows('move')
        # i3 spawns pseudocontainers in some occasions, which can contain
        # several windows. In such case the window.window_class is None
        # single window
        if window.window_class is not None:
            self._update_ws(window.id)
        # several
        else:
            for leaf in window.leaves():
                self._update_ws(leaf.id)
    
    def go_default(self) -> None:
        """Reassigns accounted windows to their default workspaces"""
        # firstly loop over windows and if they don't reside
        # on their default workspaces - move them
        conflicting = []
        for win in self.windows:
            if win.w_current_ws != self.default_assignment[win.w_cls]:
                self._move_window(win=win, ws=win.w_default_ws)
            if win.w_conflicting:
                conflicting.append(win)
        # when all default ws are taken, it's possible to properly assing conflicting
        # no point to do anything if there is just one conflicting window or non
        if len(conflicting) < 2:
            return
        # for each conflicting
        for win in conflicting:
            # if a default window
            ws_windows = self._get_tracked_windows_of_ws(win.w_default_ws)
            if len(ws_windows) < 2:
                continue
            for ws_win in ws_windows:
                if ws_win.w_conflicting and ws_win.w_id != win.w_id:
                    self._move_window(win=win)
