from i3ipc import Connection, con
from i3_manager_assets.config import (
    OUTPUTS, DEFAULT_ASSIGNMENT, NON_BANISHING_APPS
)
from time import sleep


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

    # first_unnamed_ws = sum([ len(out) for out in OUTPUTS.values() ]) + 1

    # all partiall classes to track. Not all windows have
    # special rules to behave. Only those, which stated in config
    # window_cls_to_track = set([ app.name for app in DEFAULT_ASSIGNMENT ])
    # all named ws
    # named_ws = [ ws for out in OUTPUTS.values() for ws in out ]

    def __init__(self, i3: Connection) -> None:
        self.windows = []
        self.i3 = i3

    # def _check_settings_exist(self, w_cls: str) -> bool:
    #     """Checks if an app is an app of interest"""
    #     w_cls_lower = w_cls.lower()
    #     for app_cls in self.window_cls_to_track:
    #         if app_cls == w_cls_lower:
    #             return True
    #     return False
           
    def _window_accounted(self, w_id: int) -> App|None:
        """Checks if an app is already stored in the class"""
        for win in self.windows:
            if w_id == win.w_id:
                return win
    
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

    def _move_window(
            self,
            win: App,
            ws: str | None = None,
            ) -> None:
        """Moves the given app to the other ws"""
        # find new window container just to grab the layout
        # just a window.command doesn't require it
        new_win_con = self._get_new_container(win.w_id)
        # some apps spwan and despawn windows, so a container can be None
        if new_win_con is None:
            # remove it from the accounting
            self._remove_window_from_accounting(win.w_id)
        else:
            # if ws is None, then we should grab the layout and assign it to the proper
            # screen, because we are moving conflicting. Otherwise we are just
            # moving a windows to an other windows of this class
            # find new ws
            if ws is None:
                new_ws = self._search_ws_for_new_window()
                for k, v in self.outputs.items():
                    if new_ws in v:
                        screen = k
                        break
                else:
                    screen = 'DP-0'
                # always switch to the moving ws, otherwise the other one, currently
                # focused will be moved.
                new_win_con.command(f'move container to workspace {new_ws}; workspace {new_ws}; '
                                    f'move workspace to output {screen}; layout {new_win_con.parent.layout}')
            else:
                new_win_con.command(f'move container to workspace {ws}; workspace {ws}')
            # update the location of the container
            self._update_ws(win.w_id)
    
    def _window_class_to_partial(self, w_cls: str) -> str | None:
        """Turns a full class name to a partial one"""
        for cls in self.window_cls_to_track:
            if w_cls.lower().startswith(cls):
            # if cls.startswith(w_cls.lower()):
                return cls
            
    def get_tracked_windows_by_class(self, w_cls: str) -> list:
        """Searches already opened windows of the same class, returns
        a list of them"""
        return [ win for win in self.windows if win.w_cls == w_cls ]
    
    def _get_tracked_windows_by_id(self, w_id: int) -> list:
        """Searches a window with some id among already opened windows"""
        for win in self.windows:
            if win.w_id == w_id:\
                return win

    def _search_ws_for_new_window(self) -> str:
        """Conflicting apps have their predefined workspaces, but if there is already a such
        app, a new ws should be found. First named workspaces on specified screen are taken,
        if there are non such, a new number named ws will be created"""
        # for the purpose to find the first empty ws, we have to know which aren't empty
        non_empty_ws = []
        for ws in self.i3.get_tree().workspaces():
            # if there are any windows - it's not empty
            if ws.leaves():
                non_empty_ws.append(ws.num)
        # starting with the first unnamed ws
        # and looping through numbers, untill we find a non occupied one
        for ws in range(self.first_unnamed_ws, 100):
            if ws not in non_empty_ws:
                return str(ws)
            
    def _get_window(self, window: con.Con, parent_id: int|None = None) -> App|None:
        """Creates a class for windows accounting from a container data"""
        w_container = self._get_new_container(window.id)
        # a new window will never be output. so take parent
        parent = w_container.parent
        while parent.type != 'output':
            parent = parent.parent
        # create an App with parametersh which exist for sure
        app = self.App(
            w_cls=w_container.window_class,
            w_id=w_container.id,
            w_current_ws=w_container.workspace().name,
            w_current_output=parent.name,
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

    def _remove_window_from_accounting(self, w_id: int) -> None:
        """Searches the windows by it's id and removes from the list self.windows"""
        if (win := self._window_accounted(w_id)) is not None:
            self.windows.remove(win)

    def _update_ws(self, w_id: int) -> None:
        """Refreshes a workspace of a window if it was moved.
        Requests a new container of a window in a case the
        old one stopped to exist"""
        win_con = self._get_new_container(w_id)
        # if for some reason the container stopped to exist, it should be removed
        if win_con is None:
            self._remove_window_from_accounting(w_id)
            return
        # if a window is accounted and still exists, we can grab it's workspace
        if (win := self._window_accounted(win_con.id)) is not None:
            win.w_current_ws = win_con.workspace().name     

    def _print_windows(self) -> None:
        """for debug purposes"""
        print('-------------------------')
        for num, win in enumerate(self.windows):
            print(num, 'id', win.w_id, '| class', win.w_cls, '| default ws', win.w_default_ws, '| current ws', win.w_current_ws)

    def init_windows(self) -> None: # checked
        """Loops over all existing windows to store the windows of interest"""
        for win in self.i3.get_tree().leaves():
            # we don't track pseudocontainers
            if win.window_class is None:
                continue
            self.windows.append(self._get_window(win))

    def window_opened(self, window: con.Con, focused: int) -> None:
        """Function for window open event. Stores the windows of interest,
        banishes the conflicting windows if one is opened or residing on
        a predefined ws of an opened window. Unless there are already
        windows of the same class on the ws"""
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
        # if a new window is among non banising, nothing has to be done
        if new_window.w_cls is NON_BANISHING_APPS:
            return
        # request the list of windows where the new window residing
        ws_windows = self._get_tracked_windows_of_ws(new_window.w_current_ws)
        # we should banich window if the ws is full in it's output
        # capacity, or if new window or existing on this ws windows
        # dont' allow each other
        if (
            len(ws_windows) > OUTPUTS[new_window.w_default_output]['capacity'] or
            not any()
        )
        # banish it only if it's not the only window on ws or there are no windows of the same class
        # because if there are windows of the same class
        if len(ws_windows) > 1:
            self._move_window(new_window)
    
    def window_closed(self, window: con.Con) -> None: # checked
        """Removes windows from accounting if it was sthere"""
        self._remove_window_from_accounting(window.id)

    def window_moved(self, window: con.Con) -> None:
        """Refreshes the current ws of a window, if it's accounted"""
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
