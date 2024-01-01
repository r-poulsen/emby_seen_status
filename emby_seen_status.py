#!/bin/env python
""" Generates a list of media available in Emby and their seen status for each profile """

from dataclasses import dataclass
from typing import Optional
import sys
import os
import argparse
import requests
import yaml


@dataclass
class EmbyProfile:
    """ An Emby profile. For now, find these in the web UI when inspecting the user's profile """
    name: str
    id: str


class EmbyItem:
    """ The default Emby item (movie probably)"""
    name: str
    id: int
    seen_by: Optional[list] = []

    def __init__(self, item_data: dict, profile: EmbyProfile):
        self.name = item_data['Name']
        self.id = item_data['Id']
        self.profile = profile
        if item_data['UserData']['Played']:
            self.seen_by = [profile.name]
        else:
            self.seen_by = []

    @classmethod
    def create_from_dict(cls, item_data: dict, profile: EmbyProfile) -> 'EmbyItem':
        """ Initialize an item from a dict """

        if item_data['Type'] == 'Episode':
            return EmbyEpisode(item_data=item_data, profile=profile)

        if item_data['Type'] == 'Series':
            return EmbySeries(item_data=item_data, profile=profile)

        return cls(item_data=item_data, profile=profile)


class EmbyEpisode(EmbyItem):
    """ An Emby episode """

    def __init__(self, item_data: dict, profile: EmbyProfile):
        self.series_id = item_data['SeriesId']
        if 'ParentIndexNumber' in item_data:
            self.season = item_data['ParentIndexNumber']
        else:
            self.season = 0
        self.season_name = item_data['SeasonName']
        self.episode = item_data['IndexNumber']
        super().__init__(item_data=item_data, profile=profile)


class EmbySeries(EmbyItem):
    """ An Emby series """

    def __init__(self, item_data: dict, profile: EmbyProfile):
        super().__init__(item_data=item_data, profile=profile)


class EmbySeen:
    """ Generates a list of media available in Emby and their seen status for each profile """

    def __init__(self, config):
        self.config = config
        self.host = self.config['emby']['host']
        self.api_key = self.config['emby']['api_key']
        self.profiles = []
        self.output = []
        self.output_title_max_len = 0
        self.names = []
        self.output_names_max_len = 0
        self.get_profiles()

    def get_profiles(self):
        """ Get the list of users """
        re = requests.get(
            f"{self.host}/Users?api_key={self.api_key}",
            timeout=10)

        re.raise_for_status()

        for user_data in re.json():
            self.profiles.append(
                EmbyProfile(name=user_data['Name'], id=user_data['Id'])
            )

    def output_append(self, item):
        """ Append an item to the output list """
        self.output_title_max_len = max(
            self.output_title_max_len, len(item[1]))
        for name in item[2]:
            if name not in self.names:
                self.names.append(name)
                self.output_names_max_len = max(
                    self.output_names_max_len, len(name))

        self.output.append(item)

    def display_output(self):
        """ Display the output list """

        print(f"┏{'━'*9}┳{'━' * (self.output_title_max_len+2)}", end="")
        for _ in self.names:
            print(f"┳{'━' * (self.output_names_max_len+2)}", end="")
        print("┓")

        print(f"┃ Type    ┃ {'Title':{self.output_title_max_len}}", end="")
        for name in self.names:
            print(f" ┃ {name:{self.output_names_max_len}}", end="")
        print(" ┃")

        for item in self.output:

            print(f"┣{'━'*9}╋{'━' * (self.output_title_max_len+2)}", end="")
            for _ in self.names:
                print(f"╋{'━' * (self.output_names_max_len+2)}", end="")
            print("┫")

            print(f"┃ {item[0]:7} ┃ {
                  item[1]:{self.output_title_max_len}}", end="")

            for name in self.names:
                if name in item[2]:
                    print(f" ┃ {name:{self.output_names_max_len}}", end="")
                else:
                    print(f" ┃ {'':{self.output_names_max_len}}", end="")
            print(" ┃")

        print(f"┗{'━'*9}┻{'━' * (self.output_title_max_len+2)}", end="")
        for _ in self.names:
            print(f"┻{'━' * (self.output_names_max_len+2)}", end="")
        print("┛")

    def get_media_list(self):
        """ Get a list of media available in Emby for each profile """
        movies, series, episodes = {}, {}, {}
        for profile in self.profiles:

            print(f"Getting media list for {
                  profile.name}...", file=sys.stderr, flush=True, end="")
            re = requests.get(
                f"{self.host}/Users/{profile.id}/Items?" +
                "IncludeItemTypes=Movie,Series,Episode&" +
                f"Recursive=true&StartIndex=0&api_key={self.api_key}",
                timeout=10)
            print(" ", end="", file=sys.stderr, flush=True)

            re.raise_for_status()

            print("", file=sys.stderr, flush=True)

            for item_data in re.json()['Items']:

                # print(item_data)

                item = EmbyItem.create_from_dict(
                    item_data=item_data, profile=profile
                )

                if item.__class__ == EmbyEpisode:
                    if item.id in episodes:
                        if item.seen_by:
                            episodes[item.id].seen_by.append(profile.name)
                    else:
                        episodes[item.id] = item
                elif item.__class__ == EmbySeries:
                    if item.id in series:
                        if item.seen_by:
                            series[item.id].seen_by.append(profile.name)
                    else:
                        series[item.id] = item
                else:
                    if item.id in movies:
                        if item.seen_by:
                            movies[item.id].seen_by.append(profile.name)
                    else:
                        movies[item.id] = item

        s = ""

        for _, e in sorted(
            episodes.items(), key=lambda x: (
                series[x[1].series_id].name, x[1].season, x[1].season_name, x[1].episode
            )
        ):

            if s != series[e.series_id].name:
                s = series[e.series_id].name
                self.output_append(["Series", s, series[e.series_id].seen_by])

            if s not in self.config['hide_episodes']:
                self.output_append([
                    "Episode",
                    f"{series[e.series_id].name} [{
                        e.season:02d}x{e.episode:02d}] {e.name}",
                    e.seen_by
                ])

        for _, m in sorted(movies.items(), key=lambda x: x[1].name):
            self.output_append(["Movie", m.name, m.seen_by])

        self.display_output()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Generates a list of media available in the library of an Emby server and ' +
        'their "seen" status for each user.')
    parser.add_argument('--config-file', help='Path to the configuration file')
    parser.add_argument('--server-url', help='Emby server URL')
    parser.add_argument('--api-key', help='Emby API key')
    args = parser.parse_args()

    config_file = args.config_file

    if config_file is None:
        # Check for default configuration file locations
        default_config_files = [
            os.path.expanduser('~/.config/emby_seen_status.yaml'),
            os.path.expanduser('~/.emby_seen_status.yaml'),
            'emby_seen_status.yaml'
        ]

        for file in default_config_files:
            if os.path.exists(file):
                config_file = file
                break

    c = {
        'emby': {}
    }

    if config_file is not None:

        with open(file=config_file, mode='r', encoding='utf-8') as f:
            c = yaml.safe_load(f)

    if args.server_url:
        c['emby']['host'] = args.server_url

    if args.api_key:
        c['emby']['api_key'] = args.api_key

    # Sanity check that both a server URL and API key are set
    if 'host' not in c['emby'] or 'api_key' not in c['emby']:
        print(
            "ERROR: Server URL and API key must be set in the configuration file " +
            "or on the command line"
        )
        sys.exit(1)

    seen = EmbySeen(c)
    seen.get_media_list()
