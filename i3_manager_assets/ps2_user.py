#!/usr/bin/env python3

import subprocess
from collections import namedtuple
from sys import argv
from os import path as os_path
from sys import path as sys_path
sys_path.append( os_path.dirname( os_path.realpath(__file__) ) )

from config import PS2_DIR, I3_HELPER_FILES


# a class to store settings of one ps2 player
class PS2_player:
    # the varying settings
    # ParticleLOD gets default 0 to prevent a particle bug
    ini_settings = namedtuple('ini_settings', [
        'MouseSensitivity',
        'ScopedMouseSensitivity',
        'ADSMouseSensitivity',
        'VehicleMouseSensitivity',
        'VehicleGunnerMouseSensitivity',
        'FlightMouseSensitivity',
        'AbilityQueueSeconds',
        ], defaults='0'
    )

    def __init__(self, ini_settings: tuple, kb_settings_file: str) -> None:
        # personal settings
        self.ini = self.ini_settings(*ini_settings)
        # keybinding file
        self.kb_settings_file = kb_settings_file   

    @classmethod
    def _check_strings(cls, file_path: str, proper_strings: dict) -> None:
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

    def replace_kb_file(self, source_file_dir: str, dest_file_dir: str) -> None:
        """Replaces key bindings file in the file_dir game folder
        to the one, specified in self.kb_settings_file and laying
        in the same folder with this script"""
        subprocess.Popen(['cp', f"{source_file_dir}{self.kb_settings_file}", f"{dest_file_dir}InputProfile_User.xml"])

    def change_ini_settings_for_player(self, ini_file_path: str) -> None:
        """Checks a given ini_file_path with the personal settings,
        and if it differs, rewrites it with a new, changed content"""

        # settings_string = { k: v for k in self.ini_settings._fields for v in getattr(self.ini, k) }
        self._check_strings(ini_file_path, self.ini._asdict())

    @classmethod
    def fix_particles(cls, ini_file_path: str) -> None:
        """Checks exactly one setting - ParticleLOD,
        fixes if necessary. This behaviour is required every time,
        the game is launched or closed"""

        cls._check_strings(ini_file_path, {'ParticleLOD': '0'})

def declare_players() -> dict[str, PS2_player]:
    """Returns a list of classes, containing player settings"""

    return {
        'jastix': PS2_player(
            ini_settings=('0.220000', '0.220000', '0.220000', '0.320000', '0.180000', '0.370000', '1.000000'),
            kb_settings_file='jastix_InputProfile_User.xml'
        ),
        'hekto': PS2_player(
            ini_settings=('0.230000', '0.230000', '0.230000', '0.320000', '0.180000', '0.370000', '0.000000'),
            kb_settings_file='hekto_InputProfile_User.xml'
        )
    }

if __name__ == '__main__':
    # if there are more arguments than just a script name
    if len(argv) > 1:
        # get the player
        player = declare_players().get(argv[1])
        if player is not None:
            # prepare both files
            player.replace_kb_file(I3_HELPER_FILES, PS2_DIR)
            player.change_ini_settings_for_player(f'{PS2_DIR}UserOptions.ini')
