import subprocess
import os
from re import fullmatch, IGNORECASE
from .config import (
    BACKUPS, PS2_DIR, COMPOSITOR_PROCESS_NAME,
    COMPOSITOR_SERVICE_NAME, COMPOSITOR_LAUNCH,
    REDSHIFT_SERVICE_NAME, REDSHIFT_PROCESS_NAME,
    REDSHIFT_LAUNCH, GAMES
)
from datetime import datetime
from glob import glob
from time import sleep
# from i3ipc import con
from threading import Timer, Event


# ======================= backups =======================
def make_backup(app_cls: str) -> str:
    """Tries to make a backup. Return a result as
    a text message, because a backup can consist of
    several parts - a local and a gdrive one

    Args:
        app (str): the app name, which should be found
            in config BACKUPS
    """
    def get_newest_mtime(source_path: str) -> int:
        """Returns mtime of a newest file in a given path,
        rounded to int, ignoring dotfiles/dotdirs"""
        max_mtime = 0
        # recursively walk the directory
        for root, _, files in os.walk(source_path):
            # ignore dotfiles/dotdirs
            if not '/.' in root:
                # iterate over all files in a current dir
                for file in files:
                    # if a file is newer, than we met before - update the value
                    file_mtime = os.path.getmtime(os.path.join(root, file))
                    if file_mtime > max_mtime:
                        max_mtime = file_mtime
        # the floating part isn't needed
        return int(max_mtime)
    
    def remove_dirs_from_tail(dirs: list[str], keep_amount: int) -> None:
        """Shrinks the amount of dirs to the set amount

        Args:
            dirs (list[str]): list of dirs names in backup folder
            remove_amount (int): how many to keep
        """
        # turn dirs names to full paths
        full_dirs_paths = [ os.path.join(BACKUPS[app_cls].backup_dir, dir) for dir in dirs ]
        dirs_to_remove = []
        for dir in full_dirs_paths:
            # skip n dirs which should be kept
            if keep_amount > 0:
                keep_amount -= 1
                continue
            else:
                # add dirs for deletion
                dirs_to_remove.append(dir)
        # check if there anything to delete
        if dirs_to_remove:
            # remove recursively
            subprocess.run(['rm', '-r', *dirs_to_remove])        
    
    # just a check to avoid unexpected issues
    if not app_cls in BACKUPS.keys():
        return f'Backup was requested for {app_cls} which is absent in the config'
    # create the backup directory, in a case it doesn't exist
    os.makedirs(BACKUPS[app_cls].backup_dir, exist_ok=True)
    # in the backup destination path should be n directories, named by timestamps
    # when the backup was done. But in one day only one backup directory getting
    # overwritten. Thus, first we need to get the backup directory content and
    # analyze  names there
    backup_dir_content = []
    # get backup dir content
    for dir in os.listdir(BACKUPS[app_cls].backup_dir):
        # dirs names are timestamps, so the name string should be digit
        # just in case there is something else in the folder, filter
        # it at least to some extent
        if os.path.isdir(os.path.join(BACKUPS[app_cls].backup_dir, dir)) and dir.isdigit():
            # turn it into int, we'll be comparing with int further
            backup_dir_content.append(dir)
    # for some reason a list comes as a mess
    backup_dir_content.sort()
    # get the newest mtime of the source location and check if backup not needed
    newest_mtime = str(get_newest_mtime(BACKUPS[app_cls].source_location))
    if newest_mtime in backup_dir_content:
        return 'No new files found, backup is not required'
    # just in case check if there are any files in a directory
    # makes no sense to backup nothing
    if len(os.listdir(BACKUPS[app_cls].source_location)) == 0:
        return (f'The backup source {BACKUPS[app_cls].source_location} '
                'is an empty dir, backup is not required')
    # now when we figured out that a backup is required
    # four things should be done:
    # 1. maybe only gdrive backup is required, backup_amount = 0
    # for local backup:
    # 2. if today folder exists, backup goes there and
    # it should be renamed according to the newest file timestamp
    # 3. if today folder doesn't exist - create it and backup there
    # 4. delete redundant backups
    # prepare a variable to gather a message about backup success
    return_message = ''
    if BACKUPS[app_cls].backup_amount < 0:
        return f'Invalid backup amount. It should be 0(for endless backups) or more'
    # look for today directory on the backup dir
    # it should have timestamp in the name older than today beginning
    today_beginning = str(int(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()))
    # today dir sits either on top of the list backup_dir_content or doesn't exist
    if len(backup_dir_content) and backup_dir_content[-1] > today_beginning:
        today_dir = backup_dir_content[-1]
    else:
        today_dir = None
    # source_files_path = os.path.join(BACKUPS[app_cls].source_location, '*')
    source_files = glob(os.path.join(BACKUPS[app_cls].source_location, '*'))
    full_backup_path = os.path.join(BACKUPS[app_cls].backup_dir, newest_mtime)
    # if we found today backup, update it
    if today_dir is not None:
        subprocess.run([
            'cp', '-ur', *source_files,
            os.path.join(BACKUPS[app_cls].backup_dir, today_dir)
        ])
        return_message += f'Updated local today backup of <b>{app_cls}</b>'
        # also rename the updated dir to reflect the newest file
        os.rename(
            os.path.join(BACKUPS[app_cls].backup_dir, today_dir),
            full_backup_path,
        )
    # if today backup doesn't exist , create it
    else:
        # create a new directory
        os.makedirs(full_backup_path)
        # drop files there
        subprocess.run(['cp', '-r', *source_files, full_backup_path])
        return_message += f'Created new local today backup of <b>{app_cls}</b>'
        # add newly created dir
        backup_dir_content.append(newest_mtime)
        # if we created a folder, probably we have to remove redundant dirs:
        # if we want only 3 or less backups, just simply remove others
        # and we already know that backup_amount is positive
        # we also should check if it's 0, because 0 is for endless amount
        if 0 < BACKUPS[app_cls].backup_amount < 4:
            # keep 3 or less dirs
            remove_dirs_from_tail(backup_dir_content, BACKUPS[app_cls].backup_amount)
        # backup_amount may be big but the amount of backups
        # is still small, 4 or less, just skip such. start from 5
        elif len(backup_dir_content) > 4:
            # here comes more complicated logic, because we should
            # keep two weeks backups and 3 days backups
            # take the oldest dir, turn to int for arithmetic
            # and add the threshold
            oldest = int(backup_dir_content[0]) + int(BACKUPS[app_cls].old_backup_interval.total_seconds())
            # add the one we start the count from
            allowed_dirs_to_leave = [backup_dir_content[0]]
            # remove 3 every day backups and the oldest one from the beginning
            backup_dir_content = backup_dir_content[1:-3]
            dirs_to_remove = []
            # for dirs between the edge one and three days backups
            for dir in backup_dir_content:
                # check if the gap between them is smaller than expected
                if oldest > int(dir):
                    dirs_to_remove.append(dir)
                else:
                    # get new threshold
                    oldest = int(dir) + int(BACKUPS[app_cls].old_backup_interval.total_seconds())
                    allowed_dirs_to_leave.append(dir)
            # if we got more backups than required
            if (BACKUPS[app_cls].backup_amount != 0 and
                len(allowed_dirs_to_leave) > (BACKUPS[app_cls].backup_amount) - 3):
                dirs_to_remove += allowed_dirs_to_leave[:len(allowed_dirs_to_leave) + 3 - BACKUPS[app_cls].backup_amount]
            # remove the unnecessary dirs
            if dirs_to_remove:
                remove_dirs_from_tail(dirs_to_remove, 0)
    # on this point it's established that a backup is required and the
    # local one is created. Let's check the necessity of gdrive backup
    if not BACKUPS[app_cls].sync_gdrive:
        return return_message
    if BACKUPS[app_cls].gdrive_args is None:
        return (f'The argument "gdrive_args" for an app {app_cls} should not'
                ' be None if sync_gdrive is True')
    # we also need to temporarily switch the working directory because the
    # gdrive sync script has some files in it's root directory to work with
    current_dir = os.getcwd()
    os.chdir(os.path.dirname(BACKUPS[app_cls].gdrive_script_path))
    subprocess.run([
        BACKUPS[app_cls].gdrive_python_path,
        BACKUPS[app_cls].gdrive_script_path,
        BACKUPS[app_cls].source_location,
        *BACKUPS[app_cls].gdrive_args
    ])
    os.chdir(current_dir)
    return return_message


# ======================= games =========================
def fix_particles() -> None:
    """Checks exactly one setting - ParticleLOD,
    fixes if necessary. This behavior is required every time,
    the game is launched or closed"""

    def check_strings(file_path: str, proper_strings: dict[str, str]) -> None:
        """Checks the file for listed strings. If sees any difference - 
        replaces those strings to proper ones"""
        # flag to rewrite the file if there were changes
        rewrite_requires = False
        # preparing a new content of ini file
        new_ini_file = []
        with open(file_path, 'r') as f:
            for line_in_file in f.readlines():
                # get the original line as default
                resulting_line = line_in_file
                # looping through the all varying setting fields
                for setting_name, setting_val in proper_strings.items():
                    if line_in_file.startswith(setting_name):
                        settings_line = f'{setting_name}={setting_val}'
                        if line_in_file.strip() == settings_line:
                            continue
                        # rewrite the default line
                        resulting_line = f'{settings_line}\n'
                        # set the flag
                        rewrite_requires = True
                new_ini_file.append(resulting_line)
        # rewrite if necessary
        if rewrite_requires:
            with open(file_path, 'w') as f:
                f.writelines(new_ini_file)
    check_strings(f'{PS2_DIR}UserOptions.ini', {'ParticleLOD': '0'})


# ======================= misc ==========================
def sendmessage(title: str, message: str='', timeout: str='10000', urgency: str='normal') -> None:
    """Sends a message to notification daemon in a separate process.
    urgency=critical makes a message stay until closed manually,
    for other message types types don't forget timeout, default
    timeout is set to 10 seconds"""
    # uses i3 icon for the message
    icon = '/usr/share/doc/i3/logo-30.png'
    subprocess.Popen(['notify-send', '-i', icon, '-t', timeout, '-u', urgency, title, message])

def process_searcher(proc_name: str) -> bool:
    """Searches the process by name, returns True if found"""        
    try:
        subprocess.run(['pgrep', '-U', str(os.getuid()), proc_name],  check=True)
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


def pid_searcher(proc_name: str) -> str|None:
    """Searches the given process name among all processes,
    return it's PID if found or None if no process with such
    name
    """
    try:
        return subprocess.run(
            ['pgrep', '-U', str(os.getuid()), proc_name],
            text=True,
            capture_output=True,
            check=True
        ).stdout.strip()
    except subprocess.CalledProcessError:
        return None
    

def find_window_by_pid(pid: str) -> int|None:
    """Searches window id by process PID. Process may have
    it's window id in it's variables, so the function parses them
    """
    with open(f'/proc/{pid}/environ', 'r') as f:
        for var in f.read().split('\0'):
            var_name, var_val = var.split('=')
            if var_name == 'WINDOWID':
                return int(var_val)


def get_client_pid_by_id(win_id: int) -> int|None:
    """Requests WM_CLIENT_LEADER property. If we got some
    window id which isn't equal to win_id, means we are
    dealing with the child window, return the value. If
    window id we got is the same as win_id, it's not a
    child window, return None

    Args:
        win_id (int): window id to look parent for

    Returns:
        int|None: parent window id or None if window
                with win_id has no parent
    """
    try:
        # getting something like: 'WM_CLIENT_LEADER(WINDOW): window id # 0x5c00001\n'
        result = subprocess.run(
            ['xprop', '-id', str(win_id), 'WM_CLIENT_LEADER'],
            text=True,
            capture_output=True,
            check=True
        ).stdout
        # the property can absent
        if 'not found' in result:
            return None
        # clean unnecessary strings in the output, convert hex string to int
        result = int(result.replace('WM_CLIENT_LEADER(WINDOW): window id # ', '').strip(), 16)
        if result != win_id:
            return result
    except subprocess.CalledProcessError:
        return None   


def it_is_a_game(win_cls: str) -> bool:
    """Checks if a given string matches any pattern in
    GAMES list

    Args:
        win_cls (str): window class name which can be a game

    Returns:
        bool: verdict
    """
    for game in GAMES:
        if fullmatch(game, win_cls, IGNORECASE):
            return True
    return False


class CompositorManager:
    """This class keeps track of the timers, designated
    to start or kill picom. Stops the timer, if it's not
    required anymore.
    """
    # for timers references
    compositor_starter = None
    compositor_killer = None
    # timers state - ticking if set
    compositor_starter_event = Event()
    compositor_killer_event = Event()

    def __init__(self, timer_delay: int=5, off_redshift: bool=True) -> None:
        # delay for a timer
        self.timer_delay = timer_delay
        # is it necessary of not to turn off redshift as well.
        # redshift doesn't lowed the performance, so there
        # is not strict necessity
        self.off_redshift = off_redshift

    # these four staticmethods are nice to have outside
    # of this class too for manual compositor and
    # redshift management
    @staticmethod
    def kill_service_or_process(
        service_name: str, process_name: str
    ) -> None:
        # a systemd service, call the stop at the background (popen nature)
        # nothing will happen if it's not running
        if service_name:
            subprocess.Popen(['systemctl', '--user', 'stop', service_name])
        # a normal process, kill if exists
        elif process_name and process_searcher(process_name):
            process_killer(process_name)   

    @staticmethod
    def start_service_or_process(
        service_name: str, process_name: str, process_options: list|None
    ) -> None:
        # a systemd service, call the stop at the background (popen nature)
        # nothing will happen if it's not running
        if service_name:
            subprocess.Popen(['systemctl', '--user', 'start', service_name])
        # a normal process, launch if doesn't exist
        elif (process_name and process_options is not None and
              not process_searcher(process_name)):
            subprocess.Popen(process_options)


    def postponed_compositor_killer(self) -> None:
        """Waits n seconds, giving an opportunity to a game to
        open and close all temporary windows (some games do this).
        Then kills compositor. This task can be explicitly stopped.

        Args:
            timer_active (Event): a threading safe boolean, which
                    plays a role of a flag that timer did the job
        """
        def task(timer_active: Event) -> None:
            """timer's task. Kills compositor if finds it's
            process or stops the systemd service. Clears the
            event, flagging the timer task as done.

            Args:
                timer_active (Event): thread safe flag entity,
                        timer activity flag
            """
            timer_active.clear()
            self.kill_service_or_process(
                COMPOSITOR_SERVICE_NAME,
                COMPOSITOR_PROCESS_NAME
            )
            if self.off_redshift:
                self.kill_service_or_process(
                    REDSHIFT_SERVICE_NAME,
                    REDSHIFT_PROCESS_NAME
                )                
        
        # if game appeared but the timer to bring compositor
        # is set - stop this timer and clear it's event
        if self.compositor_starter_event.is_set() and self.compositor_starter is not None:
            self.compositor_starter.cancel()
            self.compositor_starter_event.clear()
        # if killer is already assigned - stop
        if self.compositor_killer_event.is_set():
            return
        # create and start the new timer, set it's event
        self.compositor_killer_event.set()
        self.compositor_killer = Timer(self.timer_delay, task, args=(self.compositor_killer_event,))
        self.compositor_killer.start()
    
    def postponed_compositor_starter(self) -> None:
        """Waits n seconds, giving an opportunity to a game to
        open and close all temporary windows. Then starts picom
        if wasn't explicitly stopped


        Args:
            timer_active (Event): a threading safe boolean, which
                    plays a role of a flag that timer did the job
        """   
        def task(timer_active: Event) -> None:
            """timer's task. Starts picom if doesn't find it if picom is
            set to run as a process or starts the systemd service.
            Clears the event, flagging the timer task as done

            Args:
                timer_active (Event): thread safe flag entity,
                        timer activity flag
            """
            timer_active.clear()
            self.start_service_or_process(
                COMPOSITOR_SERVICE_NAME,
                COMPOSITOR_PROCESS_NAME,
                COMPOSITOR_LAUNCH
            )
            if self.off_redshift:
                self.start_service_or_process(
                    REDSHIFT_SERVICE_NAME,
                    REDSHIFT_PROCESS_NAME,
                    REDSHIFT_LAUNCH
                )                

        # if game disappeared but the timer to stop picom
        # is set - stop this timer and clear it's event
        if self.compositor_killer_event.is_set() and self.compositor_killer is not None:
            self.compositor_killer.cancel()
            self.compositor_killer_event.clear()
        # if starter is already assigned - stop
        if self.compositor_starter_event.is_set():
            return
        # create and start the new timer, set it's event
        self.compositor_starter_event.set()
        self.compositor_starter = Timer(4, task, args=(self.compositor_starter_event,))
        self.compositor_starter.start()
        return
