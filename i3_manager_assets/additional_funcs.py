import subprocess
import os
from config import BACKUPS
from datetime import datetime


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
    # overwriten. Thus, first we need to get the backup directory content and
    # analyze  names there
    backup_dir_content = []
    # get backup dir content
    for dir in os.listdir(BACKUPS[app_cls].backup_dir):
        # dirs names are timestamps, so the name string should be digit
        # just in case there is something else in teh flder, filter
        # it at least to some extent
        if os.path.isdir(os.path.join(BACKUPS[app_cls].backup_dir, dir)) and dir.isdigit():
            # turn it into int, we'll be comparing with int further
            backup_dir_content.append(dir)
    # get the newest mtime of the source location and check if backup not needed
    newest_mtime = str(get_newest_mtime(BACKUPS[app_cls].source_location))
    if newest_mtime in backup_dir_content:
        return 'No new files found, backup is not required'
    # just in case check if there are any files in a directory
    # makes no sense to backup nothing
    if len(os.listdir(BACKUPS[app_cls].source_location)) == 0:
        return (f'The backup source {BACKUPS[app_cls].source_location} '
                'is an empty dir, backup is not required')
    # now when we fihured out that a backup is required
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
    today_beginning = int(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    today_dir = None
    for dir in backup_dir_content:
        if int(dir) > today_beginning:
            today_dir = dir
            break
    source_files_path = os.path.join(BACKUPS[app_cls].source_location, '*')
    full_backup_path = os.path.join(BACKUPS[app_cls].backup_dir, newest_mtime)
    # if we found today backup, update it
    if today_dir is not None:
        subprocess.run([
            'cp', '-ur', source_files_path,
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
        # drop files there. Risky with shell, but I trust myself :)
        subprocess.run(['cp', '-r', source_files_path, full_backup_path], shell=True)
        return_message += f'Created new local today backup of <b>{app_cls}</b>'
        # add newly created dir
        backup_dir_content.append(newest_mtime)
        # sort by names which are dates, reverse to get newest first
        backup_dir_content.sort(reverse=True)
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
            oldest = int(backup_dir_content[-1]) + BACKUPS[app_cls].old_backup_interval.total_seconds()
            # remove 3 every day backups and the oldest one from the end
            backup_dir_content = backup_dir_content[3:-1]
            dirs_to_remove = []
            for dir in backup_dir_content:
                # another proper backup is expected to be newer than the threshold
                if oldest > int(dir):
                    dirs_to_remove.append(dir)
                else:
                    # get new threshold
                    oldest = int(dir) + BACKUPS[app_cls].old_backup_interval.total_seconds()
            # remove the unnecessary dirs
            remove_dirs_from_tail(dirs_to_remove, 0)
    # on this point it's established that a backup is required and the
    # local one is created. Let's check the necessity of gdrive backup
    if not BACKUPS[app_cls].sync_gdrive:
        return return_message
    if BACKUPS[app_cls].gdrive_args is None:
        return (f'The argument "gdrive_args" for an app {app_cls} should not'
                ' be None if sync_gdrive is True')
    # we also need to temporarily switch the working directory because the
    # gdrive sync script has some files in it's root direcory to work with
    current_dir = os.getcwd()
    os.chdir(os.path.dirname(BACKUPS[app_cls].gdrive_script_path))
    subprocess.run([
        BACKUPS[app_cls].gdrive_python_path,
        BACKUPS[app_cls].gdrive_script_path,
        BACKUPS[app_cls].source_location,
        *BACKUPS[app_cls].gdrive_args
    ])
    os.chdir(current_dir)


print(make_backup('testapp'))
