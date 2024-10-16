from i3ipc import Connection, con
from i3_manager_assets.config import (
    OUTPUTS, DEFAULT_ASSIGNMENT, NON_BANISHING_APPS,
    LEFT_RIGHT
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
            w_sharing: False if an app doesn't want otehr apps to
                    be opened on the same screen
            w_default_output: the output where window assigned to be
            w_current_output: the output where the windows is now
            w_parent_id: if a window was spawned by another window,
                    the id of this another window be recorded here
            w_floating: this state is taken into account when
                    searching new ws for a window
        """

        def __init__(
            self,
            w_id: int,
            w_cls: str,
            w_current_ws: int,
            w_floating: str,
            w_default_ws: int = 0,
            w_sharing: bool = True,
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
            self.w_floating = w_floating

    def __init__(self, i3: Connection) -> None:
        self.windows = []
        self.i3 = i3
     

    def _get_tracked_windows_of_ws(self, ws: int, skip_floating: bool=False) -> list:
        """Returns all tracked windows of a given ws"""
        ws_windows = []
        for win in self.windows:
            if win.w_current_ws == ws:
                if skip_floating and win.w_floating in ['auto_on', 'user_on']:
                    continue
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


    def _move_window(self, win: App, ws: int=0, output: str|None=None) -> None|int:
        """Moves the given app to another ws. Finds
        new ws or moves to a given one. If output is given,
        searches a ws there. Ofc it makes no sense to
        provide ws if output is given.
        Returns new workspace, found for the window
        """
        # find new window container just to grab the layout
        # just a window.command doesn't require it
        new_win_con = self._get_new_container(win.w_id)
        # some apps spwan and despawn windows, so a container can be None
        if new_win_con is None:
            # remove it from the accounting
            self._remove_window_from_accounting(win.w_id)
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
                return new_ws
            else:
                new_win_con.command(f'move container to workspace {ws}; workspace {ws}')
               
   
    def _get_tracked_windows_by_id(self, w_id: int) -> App|None:
        """Searches a window with some id among already opened windows"""
        for win in self.windows:
            if win.w_id == w_id:
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
        totally ignore them. We are gonna ignore."""
        # # if a window has parent, it should always go to his parent
        # if app.w_parent_id is not None:
        #     for win in self.windows:
        #         if win.w_id == app.w_parent_id:
        #             return win.w_current_ws
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
            # if ws isn't empty, we should check, if can place
            # this app there
            if self._check_window_should_be_moved(app, ws=num, output=output):
                continue
            return num
            

    def _get_window(self, window: con.Con, parent_id: int|None = None) -> App|None:
        """Creates a class for windows accounting from a container data"""
        w_container = self._get_new_container(window.id)
        # if window quickly despawned, w_container will be None
        if w_container is None:
            return
        # create an App with parametersh which exist for sure
        app = self.App(
            w_cls=w_container.window_class,
            w_id=w_container.id,
            w_current_ws=w_container.workspace().num if w_container.workspace().num != -1 else w_container.workspace().name,
            w_floating=w_container.floating,
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


    def _remove_window_from_accounting(self, w_id: int) -> None:
        """Searches the windows by it's id and removes
        it from the list self.windows"""
        for win in self.windows:
            if win.w_id == w_id:
                self.windows.remove(win)
                return


    def _update_ws(self, w_id: int) -> None:
        """Refreshes a workspace of a window if it was moved.
        Requests a new container of a window in a case the
        old one stopped to exist"""
        win_con = self._get_new_container(w_id)
        app = self._get_tracked_windows_by_id(w_id)
        # if for some reason the container stopped to exist, it should be removed
        if win_con is None:
            self._remove_window_from_accounting(app.w_id)
            return
        # if window and still exists, we can grab it's workspace
        # but we won't rewrite data if it was moved to the scratchpad
        if app.w_current_ws != -1:
            app.w_current_ws = win_con.workspace().num
            app.w_current_output = win_con.ipc_data['output']


    def _check_window_should_be_moved(self, app: App, ws: int=0, output: str|None=None) -> bool:
        """Checks if an app should be moved from the ws
        where it was placed by default. If ws is given then
        output shuld be given too, it checks if app can be
        placed to this ws. If all these aren't given, takes
        info from app
        """
        if ws:
            ws_windows = self._get_tracked_windows_of_ws(ws, skip_floating=True)
        else:
            # get all apps sitting on the current ws
            ws_windows = self._get_tracked_windows_of_ws(app.w_current_ws)
            # remove our new app from the list because it was
            # already placed there
            ws_windows.remove(app)
        # if ws is empty, then no point for further checks
        if not ws_windows:
            return False
        # if new app or any of other apps don't want to share
        # the screen at all, then new app shoould be moved
        if not app.w_sharing or not all([ other.w_sharing for other in ws_windows ]):
            return True
        # now we can check if new app fits into the screen capacity
        if ws:
            if len(ws_windows) < OUTPUTS[output]['capacity']:
                return False
        else:
            if len(ws_windows) < OUTPUTS[app.w_current_output]['capacity']:
                return False
        return True


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
        # if window was quickly despawned, new_window will be none
        if new_window.w_cls in NON_BANISHING_APPS:
            return
        # get parent id, assuming a parent exists and it's the previously
        # focused window. Also get this prev focused window by it's given id
        parent = self._get_tracked_windows_by_id(focused)
        # move a new window to it's parent, if it's not already there and
        # ofc if their classes are the same. Parent also can be ws withot a class
        if parent is not None and parent.w_cls == new_window.w_cls:
            new_window.w_parent_id = focused
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
        # we should banich window if the ws is full in it's output
        # capacity, or if new window or existing on this ws windows
        # dont' allow each other
        if self._check_window_should_be_moved(new_window):
            self._move_window(new_window)
    

    def window_closed(self, window: con.Con) -> None: # checked
        """Removes windows from accounting if it was there"""
        # this window could be someone's parent, remove this
        # yes, parent can be closed before his children
        for win in self.windows:
            if win.w_parent_id == window.id:
                win.w_parent_id = None
        self._remove_window_from_accounting(window.id)


    def window_moved(self, window: con.Con) -> None: # checked
        """Refreshes the current ws of a window, if it's accounted"""
        # weird this - if window is assigned in config to another ws
        # if get's moved before! the open even happend on i3ipc
        if self._get_tracked_windows_by_id(window.id) is None:
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


    def window_floating_changed(self, window: con.Con) -> None: # checked
        """Changes floating state for tracked windows"""
        win = self._get_tracked_windows_by_id(window.id)
        # if window is opened as floating, this event happens
        # before window opened, so beware
        if win is not None:
            win.w_floating = window.floating
    

    def go_default(self) -> None:
        """Reassigns accounted windows to their default workspaces
        and outputs. Doesn't solve conflicts because it will require
        very heavy logic"""
        def win_upd_ws_output(win: WindowsAccount.App, ws: int, output: str) -> None:
            """Updates attributes"""
            setattr(win, 'w_current_ws', ws)
            setattr(win, 'w_current_output', output)

        # def find_win_to_fill_gap(
        #         wins: list[WindowsAccount.App],
        #         start_ws: int,
        #         stop_ws: int,
        #         output: str,
        #         vacant_ws_wins: int,
        #         ws_to_output: dict,
        #         wins_to_move: list[WindowsAccount.App]
        #     ) -> WindowsAccount.App|None:
        #     """Finds a proper window to fill a gap in the sequence
        #     """
        #     # just in a case ws 99, which we use as a tmp during
        #     # windows exchange, is still active
        #     if stop_ws > 30:
        #         stop_ws = 30
        #     for num in range(stop_ws, start_ws + 1, -1):
        #         pass

        
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
            if win.w_default_ws and win.w_current_ws != win.w_default_ws:
                # if it's non banishing app, we don't move a window
                # if a window of the same class is already there
                if win.w_cls in NON_BANISHING_APPS:
                    target_ws_wins = self._get_tracked_windows_of_ws(win.w_default_ws)
                    if win.w_cls in [ other.w_cls for other in target_ws_wins ]:
                        continue
                self._move_window(win, ws=win.w_default_ws)
                # update win props
                win_upd_ws_output(win, win.w_default_ws, ws_to_out[win.w_default_ws])
                # don't check the output setings, because ws has more priority
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
            # get the capacity which remins after all asigned windows took their place
            capacity_remains = ws_to_cap.get(num, 1) - len(assigned_wins)
            if not all_other_wins:
                continue
            # if no more capacity remins, or there is a non sharing window
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
                parent = self._get_tracked_windows_by_id(win.w_parent_id)
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


    def move_left_right(self, binding_name: str, win: con.Con) -> None:
        """Moves selected container to another screen without
        specification if the exact ws. If the moving container
        has the only non floating window, it will be placed
        according to all restrictions. If it's a pack of at
        least two non floating windows, it will be plased on
        the free ws.

        Args:
            binding_name (str): left, right
        """
        # get output name from the config
        output_name = LEFT_RIGHT.get(binding_name)
        # if it wasn't configured
        if output_name is None:
            return
        # if it's a pseudocontainer
        if win.window_class is None:
            if len(win.leaves()) > 1:
                pass
                return
            win = win.nodes[0]
        # if it's a normal window or a pseudocontainer with one window
        # get this window stored and fake it's current output to
        # make function _search_new_ws_for_window look on another screen
        app = self._get_tracked_windows_by_id(win.id)
        # there is a possibility it's a mistake and window is already
        # on the proper output
        if app.w_current_output == output_name:
            return
        # when output is set, _move_window will look for a proper ws
        self._move_window(app, output=output_name)
        # to not leave an empty screen, we take all occupied ws of the
        # screen, and take the first one, sorted by the ws num, except
        # one we are moving
        screen_wins = []
        for window in self.windows:
            if window.w_current_output == app.w_current_output and window.w_id != app.w_id:
                screen_wins.append(window)
        # if there are windows on the screen at all
        if screen_wins:
            screen_wins.sort(key=lambda item: item.w_current_ws)
            self.i3.command(f'workspace {screen_wins[0].w_current_ws}')
            


    def hide_steam(self, games_ids: list, steam: con.Con) -> None:
        """moves steam to scratchpad if it was activated
        over a game window

        Args:
            games_ids (list): a list of games ids, so we can
                    see if a window is actually a game window
        """
        steam_app = self._get_tracked_windows_by_id(steam.id)
        steam_ws = self._get_tracked_windows_of_ws(steam_app.w_current_ws)
        steam_ws_ids = [ app.w_id for app in steam_ws ]
        # if game and steam share one ws
        if any([ game in steam_ws_ids for game in games_ids ]):
            steam.command('move scratchpad')


    def show_steam(self, games_ids: list) -> None:
        """Brings steam back to the last used ws if this
        ws has no games. And if steam is on the scratchpad

        Args:
            games_ids (list): a list of games ids, so we can
                    see if a window is actually a game window
        """
        # look for steam on scratchpad
        steam_in_scr = self.i3.get_tree().scratchpad().find_classed('steam')
        if not steam_in_scr:
            return
        # bring all windows if possible
        for win in steam_in_scr:
            steam_app = self._get_tracked_windows_by_id(win.id)
            steam_ws = self._get_tracked_windows_of_ws(steam_app.w_current_ws)
            # if no more games on steam ws, show steam
            if not any([ game in steam_ws for game in games_ids ]):
                self._move_window(steam_app, ws=steam_app.w_current_ws)
            # if there are games still open, not point to continue
            else:
                return
