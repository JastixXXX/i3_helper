from i3ipc import Connection, con
from i3_manager_assets.config import (
    OUTPUTS, DEFAULT_ASSIGNMENT, NON_BANISHING_APPS
)


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
        """
        def __init__(
            self,
            w_id: int,
            w_cls: str,
            w_current_ws: str,
            w_default_ws: str|None = None,
            w_sharing: list|None = None,
            w_default_output: str|None = None,
            w_current_output: str|None = None
        ) -> None:
            self.w_id = w_id
            self.w_cls = w_cls.lower()
            self.w_default_ws = w_default_ws
            self.w_current_ws = w_current_ws
            self.w_sharing = w_sharing
            self.w_default_output = w_default_output
            self.w_current_output = w_current_output

    # first_unnamed_ws = sum([ len(out) for out in OUTPUTS.values() ]) + 1

    # all partiall classes to track. Not all windows have
    # special rules to behave. Only those, which stated in config
    window_cls_to_track = set([ app.name for app in DEFAULT_ASSIGNMENT ])
    # all named ws
    # named_ws = [ ws for out in OUTPUTS.values() for ws in out ]

    def __init__(self, i3: Connection) -> None:
        self.windows = []
        self.i3 = i3

    def _check_if_should_be_tracked(self, w_cls: str) -> bool:
        """Checks if an app is an app of interest"""
        w_cls_lower = w_cls.lower()
        for app_cls in self.window_cls_to_track:
            if app_cls == w_cls_lower:
                return True
        return False
           
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
        can't retrieve it's ws, so it requires to find
        this container again"""
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
            
    def _get_window(self, window: con.Con) -> App:
        """Creates a class for windows accounting from a container data"""
        w_container = self._get_new_container(window.id)
        # if w_container is None:
        #     return
        settings = None
        for app in DEFAULT_ASSIGNMENT:
            if app.name == window.window_class.lower():
                settings = app
                break
        # if settings is None:
        #     return
        return self.App(
            w_cls=window.window_class,
            w_id=window.id,
            w_current_ws=w_container.workspace().name,
            w_default_ws=settings.ws,
            w_current_output='', # TODO
            w_default_output=settings.output,
            w_sharing=settings.share_screen
        )

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
            if win.windows_class is None:
                continue
            if self._check_if_should_be_tracked(win.window_class):
                self.windows.append(self._get_window(win))

    def window_opened(self, window: con.Con) -> None:
        """Function for window open event. Stores the windows of interest,
        banishes the conflicting windows if one is opened or residing on
        a predefined ws of an opened window. Unless there are already
        windows of the same class on the ws"""
        # if a pseudocontainer or not a window from config
        if (window.windows_class is None or not
            self._check_if_should_be_tracked(window.window_class)):
            return
        # extract data to the class App
        new_window = self._get_window(window)
        # if such window class already exists somewhere, move window to this ws
        if (tracked := self.get_tracked_windows_by_class(new_window.w_cls)):
            # focused = self.i3.get_tree().find_focused()
            # if (focused.window_class is not None and
            #     focused.id != new_window.w_id and
            #     self._window_class_to_partial(focused.window_class) == new_window.w_cls):
            # self._move_window(new_window, self._window_accounted(focused.id).w_current_ws)
            # we can't know which exact window called the new one, so we add it to the first occurence i.e. tracked[0]
            self._move_window(new_window, tracked[0].w_current_ws)  
            # now we can append it
            self.windows.append(new_window)
            return
        # append the new window regardless
        self.windows.append(new_window)
        # if the new window is conflicting
        if new_window.w_conflicting:
            # request the list of windows where the new window residing
            ws_windows = self._get_tracked_windows_of_ws(new_window.w_current_ws)
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
