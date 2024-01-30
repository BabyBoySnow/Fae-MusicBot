import codecs
import configparser
import logging
import os
import pathlib
import shutil
import sys
from typing import TYPE_CHECKING, Any, List, Optional, Set, Tuple, Union

from .constants import (
    BUNDLED_AUTOPLAYLIST_FILE,
    DEFAULT_AUDIO_CACHE_PATH,
    DEFAULT_AUTOPLAYLIST_FILE,
    DEFAULT_BLACKLIST_FILE,
    DEFAULT_FOOTER_TEXT,
    DEFAULT_I18N_FILE,
    DEFAULT_OPTIONS_FILE,
    EXAMPLE_OPTIONS_FILE,
)
from .exceptions import HelpfulError
from .utils import format_size_to_bytes, format_time_to_seconds, set_logging_level

if TYPE_CHECKING:
    from .bot import MusicBot

log = logging.getLogger(__name__)


def get_all_keys(
    conf: Union["ExtendedConfigParser", configparser.ConfigParser]
) -> List[str]:
    """Returns all config keys as a list"""
    sects = dict(conf.items())
    keys = []
    for k in sects:
        s = sects[k]
        keys += list(s.keys())
    return keys


def create_empty_file_ifnoexist(path: pathlib.Path) -> None:
    if not path.is_file():
        with open(path, "a", encoding="utf8") as fh:
            fh.close()
            log.warning("Creating %s", path)


class Config:
    def __init__(self, config_file: pathlib.Path) -> None:
        self.config_file = config_file
        self.find_config()

        config = ExtendedConfigParser(interpolation=None)
        config.read(config_file, encoding="utf-8")

        confsections = {"Credentials", "Permissions", "Chat", "MusicBot"}.difference(
            config.sections()
        )
        if confsections:
            sections_str = ", ".join([f"[{s}]" for s in confsections])
            raise HelpfulError(
                "One or more required config sections are missing.",
                "Fix your config.  Each [Section] should be on its own line with "
                f"nothing else on it.  The following sections are missing: {sections_str}",
                preface="An error has occured parsing the config:\n",
            )

        self._confpreface = "An error has occured reading the config:\n"
        self._confpreface2 = "An error has occured validating the config:\n"

        self._login_token: str = config.get(
            "Credentials", "Token", fallback=ConfigDefaults.token
        )

        self.auth: Tuple[str] = ("",)

        self.spotify_clientid = config.get(
            "Credentials", "Spotify_ClientID", fallback=ConfigDefaults.spotify_clientid
        )
        self.spotify_clientsecret = config.get(
            "Credentials",
            "Spotify_ClientSecret",
            fallback=ConfigDefaults.spotify_clientsecret,
        )

        self.owner_id: int = config.getownerid(
            "Permissions", "OwnerID", fallback=ConfigDefaults.owner_id
        )
        self.dev_ids = config.getidset(
            "Permissions", "DevIDs", fallback=ConfigDefaults.dev_ids
        )
        self.bot_exception_ids = config.getidset(
            "Permissions", "BotExceptionIDs", fallback=ConfigDefaults.bot_exception_ids
        )

        self.command_prefix = config.get(
            "Chat", "CommandPrefix", fallback=ConfigDefaults.command_prefix
        )
        self.bound_channels = config.getidset(
            "Chat", "BindToChannels", fallback=ConfigDefaults.bound_channels
        )
        self.unbound_servers = config.getboolean(
            "Chat", "AllowUnboundServers", fallback=ConfigDefaults.unbound_servers
        )
        self.autojoin_channels = config.getidset(
            "Chat", "AutojoinChannels", fallback=ConfigDefaults.autojoin_channels
        )
        self.dm_nowplaying = config.getboolean(
            "Chat", "DMNowPlaying", fallback=ConfigDefaults.dm_nowplaying
        )
        self.no_nowplaying_auto = config.getboolean(
            "Chat",
            "DisableNowPlayingAutomatic",
            fallback=ConfigDefaults.no_nowplaying_auto,
        )
        self.nowplaying_channels = config.getidset(
            "Chat", "NowPlayingChannels", fallback=ConfigDefaults.nowplaying_channels
        )
        self.delete_nowplaying = config.getboolean(
            "Chat", "DeleteNowPlaying", fallback=ConfigDefaults.delete_nowplaying
        )

        self.default_volume = config.getfloat(
            "MusicBot", "DefaultVolume", fallback=ConfigDefaults.default_volume
        )
        self.skips_required = config.getint(
            "MusicBot", "SkipsRequired", fallback=ConfigDefaults.skips_required
        )
        self.skip_ratio_required = config.getfloat(
            "MusicBot", "SkipRatio", fallback=ConfigDefaults.skip_ratio_required
        )
        self.save_videos = config.getboolean(
            "MusicBot", "SaveVideos", fallback=ConfigDefaults.save_videos
        )
        self.storage_limit_bytes = config.getdatasize(
            "MusicBot", "StorageLimitBytes", fallback=ConfigDefaults.storage_limit_bytes
        )
        self.storage_limit_days = config.getint(
            "MusicBot", "StorageLimitDays", fallback=ConfigDefaults.storage_limit_days
        )
        self.storage_retain_autoplay = config.getboolean(
            "MusicBot",
            "StorageRetainAutoPlay",
            fallback=ConfigDefaults.storage_retain_autoplay,
        )
        self.now_playing_mentions = config.getboolean(
            "MusicBot",
            "NowPlayingMentions",
            fallback=ConfigDefaults.now_playing_mentions,
        )
        self.auto_summon = config.getboolean(
            "MusicBot", "AutoSummon", fallback=ConfigDefaults.auto_summon
        )
        self.auto_playlist = config.getboolean(
            "MusicBot", "UseAutoPlaylist", fallback=ConfigDefaults.auto_playlist
        )
        self.auto_playlist_random = config.getboolean(
            "MusicBot",
            "AutoPlaylistRandom",
            fallback=ConfigDefaults.auto_playlist_random,
        )
        self.auto_pause = config.getboolean(
            "MusicBot", "AutoPause", fallback=ConfigDefaults.auto_pause
        )
        self.delete_messages = config.getboolean(
            "MusicBot", "DeleteMessages", fallback=ConfigDefaults.delete_messages
        )
        self.delete_invoking = config.getboolean(
            "MusicBot", "DeleteInvoking", fallback=ConfigDefaults.delete_invoking
        )
        self.persistent_queue = config.getboolean(
            "MusicBot", "PersistentQueue", fallback=ConfigDefaults.persistent_queue
        )
        self.status_message = config.get(
            "MusicBot", "StatusMessage", fallback=ConfigDefaults.status_message
        )
        self.write_current_song = config.getboolean(
            "MusicBot", "WriteCurrentSong", fallback=ConfigDefaults.write_current_song
        )
        self.allow_author_skip = config.getboolean(
            "MusicBot", "AllowAuthorSkip", fallback=ConfigDefaults.allow_author_skip
        )
        self.use_experimental_equalization = config.getboolean(
            "MusicBot",
            "UseExperimentalEqualization",
            fallback=ConfigDefaults.use_experimental_equalization,
        )
        self.embeds = config.getboolean(
            "MusicBot", "UseEmbeds", fallback=ConfigDefaults.embeds
        )
        self.queue_length = config.getint(
            "MusicBot", "QueueLength", fallback=ConfigDefaults.queue_length
        )
        self.remove_ap = config.getboolean(
            "MusicBot", "RemoveFromAPOnError", fallback=ConfigDefaults.remove_ap
        )
        self.show_config_at_start = config.getboolean(
            "MusicBot",
            "ShowConfigOnLaunch",
            fallback=ConfigDefaults.show_config_at_start,
        )
        self.legacy_skip = config.getboolean(
            "MusicBot", "LegacySkip", fallback=ConfigDefaults.legacy_skip
        )
        self.leavenonowners = config.getboolean(
            "MusicBot",
            "LeaveServersWithoutOwner",
            fallback=ConfigDefaults.leavenonowners,
        )
        self.usealias = config.getboolean(
            "MusicBot", "UseAlias", fallback=ConfigDefaults.usealias
        )
        self.footer_text = config.get(
            "MusicBot", "CustomEmbedFooter", fallback=ConfigDefaults.footer_text
        )
        self.self_deafen = config.getboolean(
            "MusicBot", "SelfDeafen", fallback=ConfigDefaults.self_deafen
        )
        self.leave_inactive_channel = config.getboolean(
            "MusicBot",
            "LeaveInactiveVC",
            fallback=ConfigDefaults.leave_inactive_channel,
        )
        self.leave_inactive_channel_timeout = config.getduration(
            "MusicBot",
            "LeaveInactiveVCTimeOut",
            fallback=ConfigDefaults.leave_inactive_channel_timeout,
        )
        self.leave_after_queue_empty = config.getboolean(
            "MusicBot",
            "LeaveAfterSong",
            fallback=ConfigDefaults.leave_after_queue_empty,
        )
        self.leave_player_inactive_for = config.getduration(
            "MusicBot",
            "LeavePlayerInactiveFor",
            fallback=ConfigDefaults.leave_player_inactive_for,
        )
        self.searchlist = config.getboolean(
            "MusicBot", "SearchList", fallback=ConfigDefaults.searchlist
        )
        self.defaultsearchresults = config.getint(
            "MusicBot",
            "DefaultSearchResults",
            fallback=ConfigDefaults.defaultsearchresults,
        )

        self.enable_options_per_guild = config.getboolean(
            "MusicBot",
            "EnablePrefixPerGuild",
            fallback=ConfigDefaults.enable_options_per_guild,
        )

        self.round_robin_queue = config.getboolean(
            "MusicBot",
            "RoundRobinQueue",
            fallback=ConfigDefaults.defaultround_robin_queue,
        )

        dbg_str, dbg_int = config.getdebuglevel(
            "MusicBot", "DebugLevel", fallback=ConfigDefaults.debug_level_str
        )
        self.debug_level_str: str = dbg_str
        self.debug_level: int = dbg_int
        self.debug_mode: bool = self.debug_level <= logging.DEBUG
        set_logging_level(self.debug_level)

        self.blacklist_file = config.getpathlike(
            "Files", "BlacklistFile", fallback=ConfigDefaults.blacklist_file
        )
        self.auto_playlist_file = config.getpathlike(
            "Files", "AutoPlaylistFile", fallback=ConfigDefaults.auto_playlist_file
        )
        self.i18n_file = config.getpathlike(
            "Files", "i18nFile", fallback=ConfigDefaults.i18n_file
        )
        self.audio_cache_path = config.getpathlike(
            "Files", "AudioCachePath", fallback=ConfigDefaults.audio_cache_path
        )

        # This value gets set dynamically, based on success with API authentication.
        self.spotify_enabled = False

        self.run_checks()

        self.missing_keys: Set[str] = set()
        self.check_changes(config)

        self.setup_autoplaylist()

    def check_changes(self, conf: "ExtendedConfigParser") -> None:
        exfile = "config/example_options.ini"
        if os.path.isfile(exfile):
            usr_keys = get_all_keys(conf)
            exconf = configparser.ConfigParser(interpolation=None)
            if not exconf.read(exfile, encoding="utf-8"):
                return
            ex_keys = get_all_keys(exconf)
            if set(usr_keys) != set(ex_keys):
                self.missing_keys = set(ex_keys) - set(
                    usr_keys
                )  # to raise this as an issue in bot.py later

    def run_checks(self) -> None:
        """
        Validation logic for bot settings.
        """
        if self.i18n_file != ConfigDefaults.i18n_file and not os.path.isfile(
            self.i18n_file
        ):
            log.warning(
                "i18n file does not exist. Trying to fallback to: %s",
                ConfigDefaults.i18n_file,
            )
            self.i18n_file = ConfigDefaults.i18n_file

        if not os.path.isfile(self.i18n_file):
            raise HelpfulError(
                "Your i18n file was not found, and we could not fallback.",
                "As a result, the bot cannot launch. Have you moved some files? "
                "Try pulling the recent changes from Git, or resetting your local repo.",
                preface=self._confpreface,
            )

        log.info("Using i18n: %s", self.i18n_file)

        if self.audio_cache_path:
            try:
                acpath = self.audio_cache_path
                if acpath.is_file():
                    raise HelpfulError(
                        "AudioCachePath config option is a file path.",
                        "Change it to a directory / folder path instead.",
                        preface=self._confpreface2,
                    )
                # Might as well test for multiple issues here since we can give feedback.
                if not acpath.is_dir():
                    acpath.mkdir(parents=True, exist_ok=True)
                actest = acpath.joinpath(".bot-test-write")
                actest.touch(exist_ok=True)
                actest.unlink(missing_ok=True)
            except PermissionError as e:
                raise HelpfulError(
                    "AudioCachePath config option cannot be used due to invalid permissions.",
                    "Check that directory permissions and ownership are correct.",
                    preface=self._confpreface2,
                ) from e
            except Exception as e:
                log.exception(
                    "Some other exception was thrown while validating AudioCachePath."
                )
                raise HelpfulError(
                    "AudioCachePath config option could not be set due to some exception we did not expect.",
                    "Double check the setting and maybe report an issue.",
                    preface=self._confpreface2,
                ) from e

        log.info("Audio Cache will be stored in:  %s", self.audio_cache_path)

        if not self._login_token:
            # Attempt to fallback to an environment variable.
            env_token = os.environ.get("MUSICBOT_TOKEN")
            if env_token:
                self._login_token = env_token
                self.auth = (self._login_token,)
            else:
                raise HelpfulError(
                    "No bot token was specified in the config, or as an environment variable.",
                    "As of v1.9.6_1, you are required to use a Discord bot account. "
                    "See https://github.com/Just-Some-Bots/MusicBot/wiki/FAQ for info.",
                    preface=self._confpreface,
                )

        else:
            self.auth = (self._login_token,)

        if self.spotify_clientid and self.spotify_clientsecret:
            self.spotify_enabled = True

        self.delete_invoking = self.delete_invoking and self.delete_messages

        create_empty_file_ifnoexist(self.blacklist_file)

        if not self.footer_text:
            self.footer_text = ConfigDefaults.footer_text

    # TODO: Add save function for future editing of options with commands
    #       Maybe add warnings about fields missing from the config file

    async def async_validate(self, bot: "MusicBot") -> None:
        log.debug("Validating options...")

        # attempt to get the owner ID from app-info.
        if self.owner_id == 0:
            if bot.cached_app_info:
                self.owner_id = bot.cached_app_info.owner.id
                log.debug("Acquired owner id via API")
            else:
                raise HelpfulError(
                    "Discord app info is not available. (Probably a bug!)",
                    "You may need to set OwnerID config manually, and report this.",
                    preface="Error fetching OwnerID automatically:\n",
                )

        if not bot.user:
            log.critical("If we ended up here, something is not right.")
            return

        if self.owner_id == bot.user.id:
            raise HelpfulError(
                "Your OwnerID is incorrect or you've used the wrong credentials.",
                "The bot's user ID and the id for OwnerID is identical. "
                "This is wrong. The bot needs a bot account to function, "
                "meaning you cannot use your own account to run the bot on. "
                "The OwnerID is the id of the owner, not the bot. "
                "Figure out which one is which and use the correct information.",
                preface=self._confpreface2,
            )

    def find_config(self) -> None:
        config = configparser.ConfigParser(interpolation=None)

        # Check for options.ini and copy example ini if missing.
        if not self.config_file.is_file():
            ini_file = self.config_file.with_suffix(".ini")
            if ini_file.is_file():
                try:
                    # Excplicit compat with python 3.8
                    if sys.version_info >= (3, 9):
                        shutil.move(ini_file, self.config_file)
                    else:
                        # shutil.move in 3.8 expects str and not path-like.
                        shutil.move(str(ini_file), str(self.config_file))
                    log.info(
                        "Moving %s to %s, you should probably turn file extensions on.",
                        ini_file,
                        self.config_file,
                    )
                except (
                    OSError,
                    IsADirectoryError,
                    NotADirectoryError,
                    FileExistsError,
                    PermissionError,
                ) as e:
                    log.exception(
                        "Something went wrong while trying to move .ini to config file path."
                    )
                    raise HelpfulError(
                        f"Config file move failed due to error:  {str(e)}",
                        "Verify your config folder and files exist, and can be read by the bot.",
                    ) from e

            elif os.path.isfile(EXAMPLE_OPTIONS_FILE):
                shutil.copy(EXAMPLE_OPTIONS_FILE, self.config_file)
                log.warning("Options file not found, copying example_options.ini")

            else:
                raise HelpfulError(
                    "Your config files are missing. Neither options.ini nor example_options.ini were found.",
                    "Grab the files back from the archive or remake them yourself and copy paste the content "
                    "from the repo. Stop removing important files!",
                )

        # load the config and check if settings are configured.
        if not config.read(self.config_file, encoding="utf-8"):
            c = configparser.ConfigParser()
            owner_id = ""
            try:
                c.read(self.config_file, encoding="utf-8")
                owner_id = c.get("Permissions", "OwnerID", fallback="").strip().lower()

                if not owner_id.isdigit() and owner_id != "auto":
                    log.critical(
                        "Please configure settings in '%s' and re-run the bot.",
                        DEFAULT_OPTIONS_FILE,
                    )
                    sys.exit(1)

            except ValueError as e:  # Config id value was changed but its not valid
                raise HelpfulError(
                    "Invalid config value for OwnerID",
                    "The OwnerID option requires a user ID number or 'auto'.",
                ) from e

    def setup_autoplaylist(self) -> None:
        # check for an copy the bundled playlist file if configured file is empty.
        if not self.auto_playlist_file.is_file():
            bundle_file = pathlib.Path(BUNDLED_AUTOPLAYLIST_FILE)
            if bundle_file.is_file():
                shutil.copy(bundle_file, self.auto_playlist_file)
                log.debug(
                    "Copying bundled autoplaylist '%s' to '%s'",
                    BUNDLED_AUTOPLAYLIST_FILE,
                    self.auto_playlist_file,
                )
            else:
                log.warning(
                    "Missing bundled autoplaylist file, cannot pre-load playlist."
                )

        # ensure cache map and removed files have values based on the configured file.
        path = self.auto_playlist_file.parent
        stem = self.auto_playlist_file.stem
        ext = self.auto_playlist_file.suffix

        ap_removed_file = self.auto_playlist_file.with_name(f"{stem}_removed{ext}")
        ap_cachemap_file = self.auto_playlist_file.with_name(f"{stem}.cachemap.json")

        self.auto_playlist_removed_file = path.joinpath(ap_removed_file)
        self.auto_playlist_cachemap_file = path.joinpath(ap_cachemap_file)


class ConfigDefaults:
    owner_id: int = 0

    token: str = ""
    dev_ids: Set[int] = set()
    bot_exception_ids: Set[int] = set()

    spotify_clientid: str = ""
    spotify_clientsecret: str = ""

    command_prefix: str = "!"
    bound_channels: Set[int] = set()
    unbound_servers: bool = False
    autojoin_channels: Set[int] = set()
    dm_nowplaying: bool = False
    no_nowplaying_auto: bool = False
    nowplaying_channels: Set[int] = set()
    delete_nowplaying: bool = True

    default_volume: float = 0.15
    skips_required: int = 4
    skip_ratio_required: float = 0.5
    save_videos: bool = True
    storage_retain_autoplay: bool = True
    storage_limit_bytes: int = 0
    storage_limit_days: int = 0
    now_playing_mentions: bool = False
    auto_summon: bool = True
    auto_playlist: bool = True
    auto_playlist_random: bool = True
    auto_pause: bool = True
    delete_messages: bool = True
    delete_invoking: bool = False
    persistent_queue: bool = True
    debug_level: int = logging.INFO
    debug_level_str: str = "INFO"
    status_message: str = ""
    write_current_song: bool = False
    allow_author_skip: bool = True
    use_experimental_equalization: bool = False
    embeds: bool = True
    queue_length: int = 10
    remove_ap: bool = True
    show_config_at_start: bool = False
    legacy_skip: bool = False
    leavenonowners: bool = False
    usealias: bool = True
    searchlist: bool = False
    self_deafen: bool = True
    leave_inactive_channel: bool = False
    leave_inactive_channel_timeout: float = 300.0
    leave_after_queue_empty: bool = False
    leave_player_inactive_for: float = 0.0
    defaultsearchresults: int = 3
    enable_options_per_guild: bool = False
    footer_text: str = DEFAULT_FOOTER_TEXT
    defaultround_robin_queue: bool = False

    options_file: pathlib.Path = pathlib.Path(DEFAULT_OPTIONS_FILE)
    blacklist_file: pathlib.Path = pathlib.Path(DEFAULT_BLACKLIST_FILE)
    auto_playlist_file: pathlib.Path = pathlib.Path(DEFAULT_AUTOPLAYLIST_FILE)
    i18n_file: pathlib.Path = pathlib.Path(DEFAULT_I18N_FILE)
    audio_cache_path: pathlib.Path = pathlib.Path(
        os.path.join(os.getcwd(), DEFAULT_AUDIO_CACHE_PATH)
    )


class ExtendedConfigParser(configparser.ConfigParser):
    """A collection of typed converters for ConfigParser."""

    def getownerid(
        self,
        section: str,
        key: str,
        fallback: int = 0,
        raw: bool = False,  # pylint: disable=unused-argument
        vars: Any = None,  # pylint: disable=unused-argument,redefined-builtin
    ) -> int:
        """get the owner ID or 0 for auto"""
        val = self.get(section, key, fallback="").strip()
        if not val:
            return fallback
        if val.lower() == "auto":
            return 0

        try:
            return int(val)
        except ValueError as e:
            raise HelpfulError(
                f"OwnerID is not valid. Your setting:  {val}",
                "Set OwnerID to a numerical ID or set it to 'auto' to have the bot find it.",
                preface="Error while loading config:\n",
            ) from e

    def getpathlike(
        self,
        section: str,
        key: str,
        fallback: pathlib.Path,
        raw: bool = False,  # pylint: disable=unused-argument
        vars: Any = None,  # pylint: disable=unused-argument,redefined-builtin
    ) -> pathlib.Path:
        """
        get a config value and parse it as a Path object.
        the `fallback` argument is required.
        """
        val = self.get(section, key, fallback="").strip()
        if not val:
            return fallback
        return pathlib.Path(val)

    def getidset(
        self,
        section: str,
        key: str,
        fallback: Optional[Set[int]] = None,
        raw: bool = False,  # pylint: disable=unused-argument
        vars: Any = None,  # pylint: disable=unused-argument,redefined-builtin
    ) -> Set[int]:
        """get a config value and parse it as a set of ID values."""
        val = self.get(section, key, fallback="").strip()
        if not val and fallback:
            return set(fallback)

        str_ids = val.replace(",", " ").split()
        try:
            return set(int(i) for i in str_ids)
        except ValueError as e:
            raise HelpfulError(
                f"One of the IDs in your config `{key}` is invalid.",
                "Ensure all IDs are numerical, and separated only by spaces or commas.",
                preface="Error while loading config:\n",
            ) from e

    def getdebuglevel(
        self,
        section: str,
        key: str,
        fallback: str = "",
        raw: bool = False,  # pylint: disable=unused-argument
        vars: Any = None,  # pylint: disable=unused-argument,redefined-builtin
    ) -> Tuple[str, int]:
        """get a config value an parse it as a logger level."""
        val = self.get(section, key, fallback="").strip().upper()
        if not val and fallback:
            val = fallback.upper()

        int_level = 0
        str_level = val
        if hasattr(logging, val):
            int_level = getattr(logging, val)
            return (str_level, int_level)

        log.warning(
            'Invalid DebugLevel option "%s" given, falling back to INFO',
            val,
        )
        return ("INFO", logging.INFO)

    def getdatasize(
        self,
        section: str,
        key: str,
        fallback: int = 0,
        raw: bool = False,  # pylint: disable=unused-argument
        vars: Any = None,  # pylint: disable=unused-argument,redefined-builtin
    ) -> int:
        """get a config value and parse it as a human readable data size"""
        val = self.get(section, key, fallback="").strip()
        if not val and fallback:
            return fallback
        try:
            return format_size_to_bytes(val)
        except ValueError:
            log.warning(
                "Config '%s' has invalid config value '%s' using default instead.",
                key,
                val,
            )
            return fallback

    def getduration(
        self,
        section: str,
        key: str,
        fallback: Union[int, float] = 0,
        raw: bool = False,  # pylint: disable=unused-argument,
        vars: Any = None,  # pylint: disable=unused-argument,redefined-builtin
    ) -> float:
        """get a config value parsed as a time duration."""
        val = self.get(section, key, fallback="").strip()
        if not val and fallback:
            return float(fallback)
        seconds = format_time_to_seconds(val)
        return float(seconds)

    def getstrset(  # pylint: disable=dangerous-default-value
        self,
        section: str,
        key: str,
        fallback: Set[str] = set(),
        raw: bool = False,  # pylint: disable=unused-argument
        vars: Any = None,  # pylint: disable=unused-argument,redefined-builtin
    ) -> Set[str]:
        """get a config value parsed as a set of string values."""
        val = self.get(section, key, fallback="").strip()
        if not val and fallback:
            return set(fallback)
        return set(x for x in val.replace(",", " ").split())


setattr(
    ConfigDefaults,
    codecs.decode(b"ZW1haWw=", "\x62\x61\x73\x65\x36\x34").decode("ascii"),
    None,
)
setattr(
    ConfigDefaults,
    codecs.decode(b"cGFzc3dvcmQ=", "\x62\x61\x73\x65\x36\x34").decode("ascii"),
    None,
)
setattr(
    ConfigDefaults,
    codecs.decode(b"dG9rZW4=", "\x62\x61\x73\x65\x36\x34").decode("ascii"),
    None,
)


# These two are going to be wrappers for the id lists, with add/remove/load/save functions
# and id/object conversion so types aren't an issue
class Blacklist:
    pass


class Whitelist:
    pass
