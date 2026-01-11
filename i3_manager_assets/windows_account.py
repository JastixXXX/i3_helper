from time import sleep
from i3ipc import Connection, con
from dataclasses import dataclass
from re import fullmatch, IGNORECASE

from i3_manager_assets.config import (
    OUTPUTS, DEFAULT_ASSIGNMENT, NON_BANISHING_APPS,
    LEFT_RIGHT, TERMINAL_APPS, WS_SPECIAL
)
from .additional_funcs import (
        pid_searcher, find_window_by_pid, get_client_pid_by_id,
        CompositorManager, it_is_a_game
    )


class WindowsAccount:
# A class to store information about the majority of applications (their windows)
# Stores configured apps for the option to banish such windows to other workspaces
# or put applications with default assignment to workspaces to make "go default" work
    
    @dataclass
    class App:
        """A class to store information about one window.
        it duplicates the info from default assignment,
        but shouldn't have too much of impact to the
        performance

            w_con_id: an id of the exact window container
            w_win_id: an id of window in the system, not in wm
            w_cls: class name of it
            w_current_ws: the ws where window is currently located
            w_default_ws: the assigned ws for this window if set
            w_sharing: False if an app doesn't want other apps to
                    be opened on the same screen
            w_default_output: the output where window assigned to be
            w_current_output: the output where the windows is now
            w_parent_id: if a window was spawned by another window,
                    the id of this another window be recorded here
            w_floating: this state is taken into account when
                    searching new ws for a window
            w_terminal_app: special case when apps, running in a
                    terminal won't be treated as a terminal, but
                    as standalone apps
        """
        w_con_id: int
        w_win_id: int
        w_cls: str
        w_current_ws: int
        w_floating: str
        w_current_output: str
        w_default_output: str|None = None
        w_default_ws: int = 0
        w_sharing: bool = True
        w_parent_id: int|None = None
        w_terminal_app: bool = False


    def __init__(self, i3: Connection) -> None:
        self.windows = []
        self.i3 = i3
     

    def _get_tracked_windows_of_ws(self, ws: int, skip_floating: bool=False) -> list[App]:
        """Returns all tracked windows of a given ws

        Args:
            ws (int): ws num
            skip_floating (bool, optional): ignore floating windows

        Returns:
            list (App): list of windows
        """
        ws_windows = []
        for win in self.windows:
            if win.w_current_ws == ws:
                if skip_floating and win.w_floating in ['auto_on', 'user_on']:
                    continue
                ws_windows.append(win)
        return ws_windows


    def _get_tracked_windows_by_class(self, class_name: str) -> list[App]:
        """Returns all tracked windows of a given class

        Args:
            class_name (str): class name of a window to look for,
                    may be string or regex pattern

        Returns:
            list (App): list of windows
        """
        return [ win for win in self.windows if fullmatch(class_name, win.w_cls, IGNORECASE) is not None ]


    def _get_new_container(self, w_con_id: int) -> con.Con | None:
        """The container, returned by the event handler,
        isn't integrated into a tree yet, thus stuff like
        parent or ws can be None, so it requires to find
        this container again

        Args:
            w_con_id (int): id of a container to look for

        Returns:
            con.Con | None: container object
        """
        new_con = self.i3.get_tree().find_by_id(w_con_id)
        if new_con is not None:
            return new_con
        # give it another try with a bit more time
        sleep(0.2)
        return self.i3.get_tree().find_by_id(w_con_id)


    def _move_window(self, win: App, ws: int=0, output: str|None=None) -> None|int:
        """Moves the given app to another ws. Finds new ws
        or moves to a given one.

        Args:
            win (App): window
            ws (int, optional): ws where to move window to. Makes
                    no sense to provide if output is given
            output (str | None, optional): screen where to look
                    for a new ws for the given window.

        Returns:
            None|int: new ws found for the given window
        """
        # find new window container just to grab the layout
        # just a window.command doesn't require it
        new_win_con = self._get_new_container(win.w_con_id)
        # some apps spawn and despawn windows, so a container can be None
        if new_win_con is None:
            # remove it from the accounting
            self._remove_window_from_accounting(win.w_con_id)
        else:
            if not ws:
                new_ws = self._search_new_ws_for_window(win, output)
                # always switch to the moving ws, otherwise the other one, currently
                # focused will be moved.
                new_win_con.command(
                    f'move container to workspace {new_ws}; workspace {new_ws}; '
                    f'move workspace to output {output if output is not None else win.w_current_output}; '
                    f'layout {new_win_con.parent.layout}'
                )
                # for the proper switch to the new opened window we have to refresh the
                # ws data right here (and it will be double refreshed later again)
                self._update_ws(win.w_con_id)
                return new_ws
            else:
                new_win_con.command(f'move container to workspace {ws}; workspace {ws}')
                # if ws is given then we should check if moving from the scratchpad
                # if so, toggle floating mode to detach from the scratchpad
                if win.w_current_output == '__i3':
                    # it's floating
                    if win.w_floating in ['auto_on', 'user_on']:
                        new_win_con.command('floating disable; floating enable')
                    else:
                        new_win_con.command('floating enable; floating disable')
               
   
    def _get_tracked_window_by_con_id(self, w_con_id: int) -> App|None:
        """Searches a window with given container id among
        already opened windows
        """
        for win in self.windows:
            if win.w_con_id == w_con_id:
                return win


    def _get_tracked_window_by_win_id(self, w_win_id: int) -> App|None:
        """Searches a window with given window id among
        already opened windows
        """
        for win in self.windows:
            if win.w_win_id == w_win_id:
                return win


    def _search_new_ws_for_window(self, app: App, output: str|None=None) -> int:
        """Apps have their predefined workspaces, but if the screen
        capacity is exceeded or conflicting with other apps on the same ws
        a new ws should be found. We are gonna simply go from ws num 1 to
        30, which is a sane number and see if can place our app somewhere.
        It should also stay on the same screen, as it's now if output is
        not specified.
        If output specified, window will be placed there.
        Sidenote - named workspaces have no ws.num, they have "-1".
        All of them. So we should either add named workspaces to the list
        of workspaces we are gonna check for new window placement, or
        totally ignore them. We are gonna ignore.

        Args:
            app (App): window
            output (str | None, optional): force the screen where window
                    should be placed

        Returns:
            int: new ws num
        """
        if output is None:
            output = app.w_default_output or app.w_current_output
        ws_on_other_screens = []
        # we assume there can be more than one other screen
        for output_name, output_prop in OUTPUTS.items():
            if output_name == output:
                continue
            ws_on_other_screens += output_prop['ws']
        for num in range(1, 31):
            # ws is assigned on another screen
            if num in ws_on_other_screens:
                continue
            # let's see if there are some windows on this ws
            ws = self._get_tracked_windows_of_ws(num, skip_floating=True)
            # if ws is empty - it's the result, which means it's
            if not ws:
                return num
            # if ws isn't empty, we should check, if can place this app there
            if not self._check_window_can_be_placed_to_ws(app, ws=num, output=output):
                continue
            return num
        # unlikely we won't find a proper ws, but to prevent errors
        # we are gonna return ws 99 as a backup
        return 99
            

    def _get_window(self, window: con.Con, parent_id: int|None = None) -> App|None:
        """Creates a class for windows accounting from a container data

        Args:
            window (con.Con): window in it's container
            parent_id (int | None, optional): if was detected that
                    the given window has parent

        Returns:
            App|None: window on None if container stopped to exist
        """
        w_container = self._get_new_container(window.id)
        # if window quickly despawned, w_container will be None,
        # also, seems like xfce panel has no ws num, exclude it too
        if (w_container is None or
            w_container.workspace() is None or
            w_container.window_class is None):
            return
        # create an App with parameters which exist for sure
        app = self.App(
            w_con_id=w_container.id,
            w_win_id=w_container.window,
            w_cls=w_container.window_class,
            w_current_ws=w_container.workspace().num,
            w_floating=w_container.floating,
            w_current_output=w_container.ipc_data['output'],
            w_parent_id=parent_id     
        )
        # now check if there are special settings for this app
        for def_ass in DEFAULT_ASSIGNMENT:
            # found match, add settings data to fields
            if fullmatch(def_ass.name, app.w_cls, IGNORECASE) is not None:
                app.w_default_ws = def_ass.ws
                app.w_default_output = def_ass.output
                app.w_sharing = def_ass.share_screen                
                return app
        # check if it's a terminal app
        for term_app_name, term_app_ws in TERMINAL_APPS.items():
            term_app_win_id = self._get_term_app_window_id(term_app_name)
            if app.w_win_id == term_app_win_id:
                # it has special ws despite terminal may be non banishing
                app.w_default_ws = term_app_ws
                break
        return app


    def _remove_window_from_accounting(self, w_con_id: int) -> None:
        """Searches the windows by it's id and removes
        it from the list self.windows

        Args:
            w_con_id (int): window to remove
        """
        for win in self.windows:
            if win.w_con_id == w_con_id:
                self.windows.remove(win)
                return


    def _update_ws(self, w_con_id: int) -> None:
        """Refreshes data about ws of a window if it was moved.
        Requests a new container of a window in a case the
        old one stopped to exist

        Args:
            w_con_id (int): window to refresh info about
        """
        win_con = self._get_new_container(w_con_id)
        app = self._get_tracked_window_by_con_id(w_con_id)
        # unlikely to happen, but if prev func can return None
        # we should check if it didn't happen
        if app is None:
            return
        # if for some reason the container stopped to exist, it should be removed
        if win_con is None:
            self._remove_window_from_accounting(app.w_con_id)
            return
        # if window still exists, we can grab it's workspace
        # but we won't rewrite data if it was moved to the scratchpad,
        # which mean app keeps the old data about normal ws
        app.w_current_ws = win_con.workspace().num
        app.w_current_output = win_con.ipc_data['output']


    def _check_window_should_be_moved(self, app: App) -> bool:
        """Checks if an app should be moved from the ws
        where it was placed by default.

        Args:
            app (App): window

        Returns:
            bool: verdict
        """
        if app.w_current_ws == app.w_default_ws == WS_SPECIAL:
            return False
        # get all apps sitting on the current ws
        ws_windows = self._get_tracked_windows_of_ws(app.w_current_ws)
        # remove our new app from the list because it was
        # already placed there
        ws_windows.remove(app)
        # if ws is empty, then no point for further checks
        if not ws_windows:
            return False
        # if new app or any of other apps don't want to share
        # the screen at all, then new app should be moved
        if not app.w_sharing or not all([ other.w_sharing for other in ws_windows ]):
            return True
        # now we can check if new app fits into the screen capacity
        if len(ws_windows) < OUTPUTS[app.w_current_output]['capacity']:
            return False
        return True


    def _check_window_can_be_placed_to_ws(self, app: App, ws: int, output: str) -> bool:
        """Checks if a window can be placed to the requested ws.

        Args:
            app (App): window
            ws (int): ws where new window should be placed
            output (str): screen where a window should be placed.
                    required because they can have different
                    capacities

        Returns:
            bool: verdict
        """
        ws_windows = self._get_tracked_windows_of_ws(ws, skip_floating=True)
        # if ws is empty, then no point for further checks
        if not ws_windows:
            return True
        # if new app or any of other apps don't want to share
        # the screen at all, then new app should be moved
        if not app.w_sharing or not all([ other.w_sharing for other in ws_windows ]):
            return False
        # now we can check if new app fits into the screen capacity
        if len(ws_windows) < OUTPUTS[output]['capacity']:
            return True
        return False


    def _get_term_app_window_id(self, app_name: str) -> int|None:
        """Searches terminal app window id by the
        given name

        Args:
            app_name (str): app name to look for
        Returns:
            int|None: pid if found
        """
        terminal_app_pid = pid_searcher(app_name)
        if terminal_app_pid is not None:
            return find_window_by_pid(terminal_app_pid)


    def _show_ws_with_windows(self) -> None:
        """Checks if there are some windows on currently visible
        workspaces. If no - looks for the first occupied ws on
        the current outputs and switches to it
        """
        for ws in self.i3.get_workspaces():
            if not ws.visible:
                continue
            # if there are windows on the visible ws, no need to
            # do anything
            if self._get_tracked_windows_of_ws(ws.num):
                continue
            # to not leave an empty screen, we take all occupied ws of the
            # screen, and take the first one, sorted by the ws num
            screen_wins = []
            for window in self.windows:
                if window.w_current_output == ws.output:
                    screen_wins.append(window)
            # if there are windows on the screen at all
            if screen_wins:
                screen_wins.sort(key=lambda item: item.w_current_ws)
                self.i3.command(f'workspace {screen_wins[0].w_current_ws}')            


    def _print_windows(self, func_name: str = '') -> None:
        """For debug purposes

        Args:
            func_name (str, optional): function name where is was called
                    from, or some label
        """
        print(f'------------{func_name}-------------')
        for num, win in enumerate(self.windows):
            print(f'{num}. id: {win.w_con_id} | window {win.w_win_id} | class: {win.w_cls} | default ws: '
                  f'{win.w_default_ws} | current ws: {win.w_current_ws} | '
                  f'default output: {win.w_default_output} | current output: {win.w_current_output}'
                  f' | sharing: {win.w_sharing} | parent id: {win.w_parent_id} | floating: {win.w_floating}')


    def init_windows(self) -> None:
        """Loops over all existing windows to store the windows of interest
        """
        for win in self.i3.get_tree().leaves():
            # we don't track pseudocontainers
            if win.window_class is None:
                continue
            self.windows.append(self._get_window(win))


    def window_opened(self, window: con.Con, focused: int) -> None:
        """Function for window open event. Stores the windows of interest,
        banishes the conflicting windows if one is opened or residing on
        a predefined ws of an opened window. Unless there are already
        windows of the same class on the ws

        Args:
            window (con.Con): the opening window
            focused (int): container id of the currently focused
                    window. Not the one is getting opened
        """
        # if a pseudocontainer
        if window.window_class is None:
            return
        # if it's among so called NON_BANISHING_APPS, i.e. apps
        # which require to have multiple windows for different tasks
        # we are not gonna look for a parent
        new_window = self._get_window(window)
        if new_window is None:
            return
        self.windows.append(new_window)
        # terminal apps are special cases because they run inside of a terminal
        # window and terminal containing it should be moved to the predefined
        # ws. Apps also require some time to launch, otherwise
        # we can't distinguish what kind of terminal is getting opened
        sleep(0.2)
        for term_app_name, term_app_ws in TERMINAL_APPS.items():
            term_app_win_id = self._get_term_app_window_id(term_app_name)
            if new_window.w_win_id == term_app_win_id:
                # it has special ws despite terminal may be non banishing
                new_window.w_default_ws = term_app_ws
                new_window.w_terminal_app = True
                break
        # window can spawn two kind of windows - transient and actual child.
        # we consider both as children and have to check for both.
        # terminal apps are a special case again here, we don't expect
        # them have parents, neither they have children, but can have transient
        parent = None
        # 1. Check for transient because it's easy
        if window.ipc_data['window_properties']['transient_for'] is not None:
            parent = self._get_tracked_window_by_win_id(window.ipc_data['window_properties']['transient_for'])
        # 2. Check if window has leader window. Often applications have
        # invisible leader, acting like a daemon. In this case we are
        # gonna assume that focused window is the parent. But if there
        # is no leader, it's definitely not a child window of some app
        elif not new_window.w_terminal_app:
            leader_id = get_client_pid_by_id(new_window.w_win_id)
            if leader_id is not None:
                # first try direct search
                parent = self._get_tracked_window_by_win_id(leader_id)
                # if didn't find (likely), take focused if it has
                # the same class
                if parent is None:
                    focused_accounted = self._get_tracked_window_by_con_id(focused)
                    # if focused window is of different class, we consider
                    # we didn't find the parent
                    if focused_accounted is not None and focused_accounted.w_cls == new_window.w_cls:
                        parent = focused_accounted
        # assign parent, ofc if parent isn't a terminal app
        # it shouldn't be the same con, neither an app of some other class
        if (
            parent is not None and
            parent.w_cls == new_window.w_cls and
            parent.w_con_id != new_window.w_con_id
        ):
            new_window.w_parent_id = parent.w_con_id
        if any([ fullmatch(app, new_window.w_cls, IGNORECASE) for app in NON_BANISHING_APPS ]):
            return
        # if a new window was spawned by an existing one -
        # move new one on it's ws, unless the presumable
        # parent is already closed
        if new_window.w_parent_id is not None:
            # if new window is already on the proper ws
            if new_window.w_current_ws == parent.w_current_ws:
                return
            else:
                # add a new window to it's presumable parent
                self._move_window(new_window, parent.w_current_ws)
                return
        # if the new window is floating and presumably has no parent,
        # nothing has to be done further
        if new_window.w_floating in ['auto_on', 'user_on']:
            return
        # we should banish window if the ws is full in it's output
        # capacity, or if new window or existing on this ws windows
        # dont' allow each other
        if self._check_window_should_be_moved(new_window):
            self._move_window(new_window)
    

    def window_closed(self, window: con.Con) -> None:
        """Removes windows from accounting if it was there

        Args:
            window (con.Con): window which got closed
        """
        # this window could be someone's parent, remove this
        # yes, parent can be closed before his children
        for win in self.windows:
            if win.w_parent_id == window.id:
                win.w_parent_id = None
        self._remove_window_from_accounting(window.id)


    def window_moved(self, window: con.Con) -> None:
        """Refreshes the current ws of a window, if it's accounted

        Args:
            window (con.Con): window which were moved
        """
        # weird thing - if window is assigned in config to another ws
        # it get's moved before! the open even happened on i3ipc
        if self._get_tracked_window_by_con_id(window.id) is None:
            return
        # i3 spawns pseudocontainers in some occasions, which can contain
        # several windows. In such case the window.window_class is None
        # single window
        if window.window_class is not None:
            self._update_ws(window.id)
        # several
        else:
            for leaf in window.leaves():
                self._update_ws(leaf.id)


    def window_floating_changed(self, window: con.Con) -> None:
        """Changes floating state for tracked windows

        Args:
            window (con.Con): target window
        """
        win = self._get_tracked_window_by_con_id(window.id)
        # if window is opened as floating, this event happens
        # before window opened, so beware
        if win is not None:
            win.w_floating = window.floating
    

    def go_default(self) -> None:
        """Reassigns accounted windows to their default workspaces
        and outputs. Doesn't solve conflicts because it will require
        very heavy logic
        """

        def win_upd_ws_output(win: WindowsAccount.App, ws: int, output: str) -> None:
            """Updates attributes

            Args:
                win (WindowsAccount.App): window
                ws (int): probably new ws
                output (str): probably new output
            """
            setattr(win, 'w_current_ws', ws)
            setattr(win, 'w_current_output', output)

        # terminal apps live in a terminal, if launched at all. Find it's ids
        # xray_id = self._get_xray_window_id()
        # we should get what ws is where. Some are predefined
        # in the config, but not all of them
        # map ws to the output name
        ws_to_out = {}
        # map ws to the it's capacity
        ws_to_cap = {}
        for out, props in OUTPUTS.items():
            for ws in props['ws']:
                ws_to_out[ws] = out
                ws_to_cap[ws] = props['capacity']
        for ws in self.i3.get_tree().workspaces():
            # skip named, if exist
            if ws.num == -1:
                continue
            if ws_to_out.get(ws.num) is None:
                ws_to_out[ws.num] = ws.ipc_data['output']
        # move all child windows to a wm ws99, thus we can move
        # them to their parents later, but do it virtually
        for win in self.windows:
            if win.w_parent_id is not None:
                win.w_current_ws = 99
        # loop over all windows and place them according to ws
        # and output settings, where ws is more priority
        for win in self.windows:
            if win.w_current_ws == 99:
                continue
            # # process our special case - xray
            # if xray_id is not None and win.w_win_id == xray_id and win.w_current_ws != XRAY_WS:
            #     self._move_window(win, ws=XRAY_WS)
            #     continue
            if win.w_default_ws and win.w_current_ws != win.w_default_ws:
                # if it's non banishing app, we don't move a window
                # if a window of the same class is already there
                if any([ fullmatch(app, win.w_cls, IGNORECASE) for app in NON_BANISHING_APPS ]):
                    target_ws_wins = self._get_tracked_windows_of_ws(win.w_default_ws)
                    if win.w_cls in [ other.w_cls for other in target_ws_wins ]:
                        continue
                self._move_window(win, ws=win.w_default_ws)
                # update win props
                win_upd_ws_output(win, win.w_default_ws, ws_to_out[win.w_default_ws])
                # don't check the output settings, because ws has more priority
                continue
            # if ws isn't set but the output is and windows isn't there
            if (win.w_default_output is not None and
                win.w_current_output != win.w_default_output):
                # move window to a proper output. _move_window returns the new ws
                new_ws = self._move_window(win, output=win.w_default_output)
                # update properties. they will be updated anyway, but we need it now
                win_upd_ws_output(win, new_ws, win.w_default_output)
        # go through all and move conflicting windows:
        # get all occupied ws except named and 99, which contains those who have a parent
        all_ws = [ ws for ws in self.i3.get_tree().workspaces() if not ws.num in [-1, 99] ]
        # loop over all occupied
        for num in range(1, all_ws[-1].num + 1):
            # all windows, already sitting on the ws
            vacant_ws_wins = self._get_tracked_windows_of_ws(num, skip_floating=True)
            if not vacant_ws_wins:
                continue
            # those with assigned ws
            assigned_wins = [ win for win in vacant_ws_wins if win.w_default_ws == num ]
            # if an assigned window is non sharing - we don't care, they stay
            non_sharing_assigned = False
            non_sharing_wins = []
            # loop over all ws windows
            for win in vacant_ws_wins:
                # find all non sharing windows which aren't assigned to this ws
                if win.w_sharing == False:
                    if win.w_default_ws != num:
                        non_sharing_wins.append(win)
                    # or there is a window which isn't sharing but assigned to ws
                    else:
                        non_sharing_assigned = True
            # if there is any assigned window, move all non sharing
            if assigned_wins:
                for win in non_sharing_wins:
                    new_ws = self._move_window(win)
                    win_upd_ws_output(win, new_ws, win.w_default_output)
            # if there is any non sharing and no assigned - move all other
            elif non_sharing_wins:
                # remove this non sharing from the list of ws wins
                vacant_ws_wins.remove(non_sharing_wins[0])
                for win in vacant_ws_wins:
                    new_ws = self._move_window(win)
                    win_upd_ws_output(win, new_ws, win.w_default_output)
                continue
            # filter all windows which aren't assigned to this ws
            all_other_wins = [ win for win in vacant_ws_wins if win not in assigned_wins ]
            # get the capacity which remains after all assigned windows took their place
            capacity_remains = ws_to_cap.get(num, 1) - len(assigned_wins)
            if not all_other_wins:
                continue
            # if no more capacity remains, or there is a non sharing window
            if capacity_remains <= 0 or non_sharing_assigned:
                # move all other windows
                for win in all_other_wins:
                    new_ws = self._move_window(win)
                    win_upd_ws_output(win, new_ws, win.w_default_output)
            # move those which don't fit into the capacity
            elif len(all_other_wins) > capacity_remains:
                for win in all_other_wins[capacity_remains:]:
                    new_ws = self._move_window(win)
                    win_upd_ws_output(win, new_ws, win.w_default_output)
        # if there are any child windows
        ws99 = self._get_tracked_windows_of_ws(99)
        # move them to their parents. Capacity or non sharing stuff
        # aren't taken into account in this case
        if ws99:
            for win in ws99:
                # find where the parent is, take into account the possibility
                # of possible errors when parent doesn't exist, it shouldn't happen though
                parent = self._get_tracked_window_by_con_id(win.w_parent_id)
                new_ws = self._move_window(win, parent.w_current_ws if parent is not None else 0)
                if new_ws != parent.w_current_ws:
                    win_upd_ws_output(win, new_ws, win.w_default_output)
        # now we have to fill gaps in ws sequences if they exist
        # to fill them we are gonna take windows only from the same output
        output_ws_wins = {}
        # get the list of ws on each output
        for ws in self.i3.get_tree().workspaces():
            output_ws_wins.setdefault(ws.ipc_data['output'], []).append(ws.num)
        # for each screen
        for output, ws_list in output_ws_wins.items():
            # check if there are more ws that one, otherwise makes no sense
            # to continue, go to other screen
            if len(ws_list) <= 1:
                continue
            # prepare the list of ws and gaps, it's just a sequence from 1
            # to maximum existing ws, with ws, assigned or located to another
            # screen removed. +1 is necessary because range doesn't take the last one
            ws_seq = list(range(1, ws_list[-1] + 1))
            # remove assigned to another screen
            for ws, out in ws_to_out.items():
                if output != out and ws in ws_seq:
                    ws_seq.remove(ws)
            # remove those used on another screen
            for all_screen_ws in output_ws_wins.values():
                # skip this screen
                if all_screen_ws == ws_list:
                    continue
                # remove ws located on other screens
                for ws in all_screen_ws:
                    if ws in ws_list:
                        ws_list.remove(ws)
            # now we try to fill gaps taking windows from other ws,
            # starting from the tail
            for seq_num, ws in enumerate(ws_seq):
                ws_wins = self._get_tracked_windows_of_ws(ws)
                # if capacity is exceeded - skip
                if len(ws_wins) >= OUTPUTS[output]['capacity']:
                    continue
                # if there are non sharing windows - skip
                if not all(win.w_sharing for win in ws_wins):
                    continue
                # starting from the tail not taking current ws
                for ws_target in ws_seq[seq_num:][::-1]:
                    # get windows of a target ws
                    target_ws_wins = self._get_tracked_windows_of_ws(ws_target)
                    # we should remove those, which are assigned to the target ws
                    target_ws_wins = [ win for win in target_ws_wins if win.w_default_ws is None ]
                    # it can happen there are no windows left - skip
                    if not target_ws_wins:
                        continue
                    # now we can try to move the rest
                    for win in target_ws_wins:
                        new_win_ws = self._search_new_ws_for_window(win)
                        # if we can't move the window in any gap - skip
                        if new_win_ws >= win.w_current_ws:
                            continue
                        self._move_window(win, new_win_ws)
        # to not leave an empty screen, call function to look for an
        # occupied ws
        self._show_ws_with_windows()


    def move_left_right(self, binding_name: str, win: con.Con) -> None:
        """Moves selected container to another screen without
        specification if the exact ws. If the moving container
        has the only non floating window, it will be placed
        according to all restrictions. If it's a pack of at
        least two non floating windows, it will be placed on
        the free ws.

        Args:
            binding_name (str): left, right
            win (con.Con): target window
        """
        # get output name from the config
        output_name = LEFT_RIGHT.get(binding_name)
        # if it wasn't configured
        if output_name is None:
            return
        # if it's a pseudocontainer
        if win.window_class is None:
            if len(win.leaves()) > 1:
                return
            win = win.nodes[0]
        # if it's a normal window or a pseudocontainer with one window
        # get this window stored and fake it's current output to
        # make function _search_new_ws_for_window look on another screen
        app = self._get_tracked_window_by_con_id(win.id)
        # there is a possibility it's a mistake and window is already
        # on the proper output
        if app.w_current_output == output_name:
            return
        # preserve the current output to switch to some windows later
        old_output = app.w_current_output
        old_ws = app.w_current_ws
        # when output is set, _move_window will look for a proper ws
        self._move_window(app, output=output_name)
        # if there are windows left on the ws where we moved windows
        # from - return
        if self._get_tracked_windows_of_ws(old_ws):
            return
        # to not leave an empty screen, call function to look for an
        # occupied ws
        self._show_ws_with_windows()
            

    def hide_steam(self, steam: con.Con) -> None:
        """moves steam to scratchpad if it was activated
        over a game window

        Args:
            steam (con.Con): steam window
        """
        steam_win = self._get_tracked_window_by_con_id(steam.id)
        steam_ws = self._get_tracked_windows_of_ws(steam_win.w_current_ws)
        # if game and steam share one ws, hide steam
        for win in steam_ws:
            if it_is_a_game(win.w_cls):
                steam.command('move scratchpad')
                break


    def show_steam(self) -> None:
        """Brings steam back to the last used ws if this
        ws has no games. And if steam is on the scratchpad
        """
        # look for steam
        steam = self._get_tracked_windows_by_class('^steam$')
        if not steam:
            return
        # look for steam on scratchpad
        steam_in_scr = self.i3.get_tree().scratchpad().find_classed('steam')
        if steam_in_scr:
            sleep(1)
            # bring in a normal ws all windows if possible
            for win in steam_in_scr:
                steam_win = self._get_tracked_window_by_con_id(win.id)
                steam_ws = self._get_tracked_windows_of_ws(steam_win.w_current_ws)
                # if no more games on steam ws, show steam on it's current ws
                if not any([ it_is_a_game(game.w_cls) for game in steam_ws ]):
                    self._move_window(steam_win, ws=steam_win.w_current_ws)    
                # if there are games still open, not point to continue
                else:
                    return
            # show steam on the screen only if it was in teh scratchpad
            self.i3.command(f'workspace {steam[0].w_current_ws}')
        

    def start_eye_candy_services(self, compositor_manager: CompositorManager) -> None:
        """Starts the services, like picom and redshift if
        there are no games anymore.

        Args:
            compositor_manager (CompositorManager): initialized instance
        """
        # check if any game is still launched
        for win in self.windows:
            if it_is_a_game(win.w_cls):
                return
        # no games found, start the services
        compositor_manager.postponed_compositor_starter()


    def stop_eye_candy_services(self, compositor_manager: CompositorManager) -> None:
        """Stops the services, like picom and redshift.

        Args:
            compositor_manager (CompositorManager): initialized instance
        """
        compositor_manager.postponed_compositor_killer()
