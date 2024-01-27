import re
import sys
import glob
import pathlib
import logging
import aiohttp
import inspect
import colorlog
import datetime
import unicodedata
from functools import wraps
from typing import (
    TYPE_CHECKING,
    Callable,
    Iterable,
    Union,
    Optional,
    Any,
    Set,
    List,
    Dict,
)

from .exceptions import PermissionsError
from .constants import (
    DEFAULT_MUSICBOT_LOG_FILE,
    DEFAULT_DISCORD_LOG_FILE,
    DISCORD_MSG_CHAR_LIMIT,
)

if TYPE_CHECKING:
    from discord import VoiceChannel, StageChannel, Member
    from multidict import CIMultiDictProxy
    from .bot import MusicBot

log = logging.getLogger(__name__)


def _add_logger_level(levelname: str, level: int, *, func_name: str = "") -> None:
    """
    Add a logging function and level to the musicbot logger.

    :param: levelname:
        The reference name of the level, e.g. DEBUG, WARNING, etc
    :param: level:
        Numeric logging level
    :param: func_name:
        The name of the logger function to log to a level, e.g. "info" for log.info(...)
    """
    _func_prototype = (
        "def {logger_func_name}(self, message, *args, **kwargs):\n"
        "    if self.isEnabledFor({levelname}):\n"
        "        self._log({levelname}, message, args, **kwargs)"
    )

    func_name = func_name or levelname.lower()

    setattr(logging, levelname, level)
    logging.addLevelName(level, levelname)

    exec(
        _func_prototype.format(logger_func_name=func_name, levelname=levelname),
        logging.__dict__,
        locals(),
    )
    setattr(logging.Logger, func_name, eval(func_name))


def setup_loggers() -> None:
    """set up all logging handlers for musicbot and discord.py"""
    if len(logging.getLogger("musicbot").handlers) > 1:
        log.debug("Skipping logger setup, already set up")
        return

    # Do some pre-flight checking...
    log_file = pathlib.Path(DEFAULT_MUSICBOT_LOG_FILE)
    if not log_file.parent.is_dir():
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise RuntimeError(
                f"Cannot create log file directory due to an error:\n{str(e)}"
            ) from e

    if not log_file.is_file():
        try:
            log_file.touch(exist_ok=True)
        except Exception as e:
            raise RuntimeError(
                f"Cannot create log file due to an error:\n{str(e)}"
            ) from e

    # logging checks done, we should be able to take off.
    _add_logger_level("EVERYTHING", 1)
    _add_logger_level("NOISY", 4, func_name="noise")
    _add_logger_level("FFMPEG", 5)
    _add_logger_level("VOICEDEBUG", 6)

    logger = logging.getLogger("musicbot")
    # initially set logging to everything, it will be changed when config is loaded.
    logger.setLevel(logging.EVERYTHING)  # type: ignore[attr-defined]

    # Setup logging to file for musicbot.
    try:
        fhandler = logging.FileHandler(filename=log_file, encoding="utf-8", mode="w")
    except Exception as e:
        raise RuntimeError(
            f"Could not create or use the log file due to an error:\n{str(e)}"
        ) from e

    fhandler.setFormatter(
        logging.Formatter(
            "[{asctime}] {levelname} - {name} | "
            "In {filename}::{threadName}({thread}), line {lineno} in {funcName}: {message}",
            style="{",
        )
    )
    logger.addHandler(fhandler)

    # Setup logging to console for musicbot.
    shandler = logging.StreamHandler(stream=sys.stdout)
    sformatter = colorlog.LevelFormatter(
        fmt={
            "DEBUG": "{log_color}[{levelname}:{module}] {message}",
            "INFO": "{log_color}{message}",
            "WARNING": "{log_color}{levelname}: {message}",
            "ERROR": "{log_color}[{levelname}:{module}] {message}",
            "CRITICAL": "{log_color}[{levelname}:{module}] {message}",
            "EVERYTHING": "{log_color}[{levelname}:{module}] {message}",
            "NOISY": "{log_color}[{levelname}:{module}] {message}",
            "VOICEDEBUG": "{log_color}[{levelname}:{module}][{relativeCreated:.9f}] {message}",
            "FFMPEG": "{log_color}[{levelname}:{module}][{relativeCreated:.9f}] {message}",
        },
        log_colors={
            "DEBUG": "cyan",
            "INFO": "white",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "bold_red",
            "EVERYTHING": "bold_cyan",
            "NOISY": "bold_white",
            "FFMPEG": "bold_purple",
            "VOICEDEBUG": "purple",
        },
        style="{",
        datefmt="",
    )
    shandler.setFormatter(sformatter)  # type: ignore[arg-type]
    # shandler.setLevel(self.config.debug_level)
    logger.addHandler(shandler)

    # Setup logging for discord module.
    dlogger = logging.getLogger("discord")
    dhandler = logging.FileHandler(
        filename=DEFAULT_DISCORD_LOG_FILE, encoding="utf-8", mode="w"
    )
    dhandler.setFormatter(
        logging.Formatter("[{asctime}] {levelname} - {name}: {message}", style="{")
    )
    dlogger.addHandler(dhandler)
    # initially set discord logging to debug, it will be changed when config is loaded.
    dlogger.setLevel(logging.DEBUG)


def muffle_discord_console_log() -> None:
    """
    Changes discord console logger output to periods only.
    Kind of like a progress indicator.
    """
    dlog = logging.getLogger("discord")
    dlh = logging.StreamHandler(stream=sys.stdout)
    dlh.terminator = ""
    try:
        dlh.setFormatter(logging.Formatter("."))
    except ValueError:
        dlh.setFormatter(logging.Formatter(".", validate=False))
    dlog.addHandler(dlh)


def mute_discord_console_log() -> None:
    """
    Removes the discord console logger output handler added by muffle_discord_console_log()
    """
    dlogger = logging.getLogger("discord")
    for h in dlogger.handlers:
        if getattr(h, "terminator", None) == "":
            dlogger.removeHandler(h)
            print()


def set_logging_level(level: int) -> None:
    """sets the logging level for musicbot and discord.py"""
    set_lvl_name = logging.getLevelName(level)
    log.info(f"Changing log level to {set_lvl_name}")

    logger = logging.getLogger("musicbot")
    logger.setLevel(level)

    dlogger = logging.getLogger("discord")
    if level <= logging.DEBUG:
        dlogger.setLevel(logging.DEBUG)
    else:
        dlogger.setLevel(level)


def shutdown_loggers() -> None:
    """Removes all musicbot and discord log handlers"""
    # This is the last log line of the logger session.
    log.info("MusicBot loggers have been called to shutdown.")

    logger = logging.getLogger("musicbot")
    for handler in logger.handlers:
        handler.flush()
        handler.close()
    logger.handlers.clear()

    dlogger = logging.getLogger("discord")
    for handler in dlogger.handlers:
        handler.flush()
        handler.close()
    dlogger.handlers.clear()


def rotate_log_files(max_kept: int = 2, date_fmt: str = ".ended-%Y-%j-%H%m%S") -> None:
    """
    Handles moving and pruning log files.
    By default the last-run log file is always kept.
    If `max_kept` is set to 0, no rotation is done.
    If `max_kept` is set 1 or greater, up to this number of logs will be kept.
    This should only be used before setup_loggers() or after shutdown_loggers()

    :param: max_kept:  number of old logs to keep.
    :param: date_fmt:  format compatible with datetime.strftime() for rotated filename.
    """
    # TODO: this needs to be more reliable. Extra or renamed files in the
    # log directory might break this implementation.
    # We should probably use a method to read file times rather than using glob...
    if not max_kept:
        return

    # date that will be used for files rotated now.
    before = datetime.datetime.now().strftime(date_fmt)

    # rotate musicbot logs
    logfile = pathlib.Path(DEFAULT_MUSICBOT_LOG_FILE)
    logpath = logfile.parent
    if logfile.is_file():
        new_name = logpath.joinpath(f"{logfile.stem}{before}{logfile.suffix}")
        # Cannot use logging here, but some notice to console is OK.
        print(f"Moving the log file from this run to:  {new_name}")
        logfile.rename(new_name)

    # make sure we are in limits
    logstem = glob.escape(logfile.stem)
    logglob = sorted(logpath.glob(f"{logstem}*.log"), reverse=True)
    if len(logglob) > max_kept:
        for path in logglob[max_kept:]:
            if path.is_file():
                path.unlink()

    # rotate discord.py logs
    dlogfile = pathlib.Path(DEFAULT_DISCORD_LOG_FILE)
    dlogpath = dlogfile.parent
    if dlogfile.is_file():
        new_name = dlogfile.parent.joinpath(f"{dlogfile.stem}{before}{dlogfile.suffix}")
        dlogfile.rename(new_name)

    # make sure we are in limits
    logstem = glob.escape(dlogfile.stem)
    logglob = sorted(dlogpath.glob(f"{logstem}*.log"), reverse=True)
    if len(logglob) > max_kept:
        for path in logglob[max_kept:]:
            if path.is_file():
                path.unlink()


def load_file(
    filename: pathlib.Path, skip_commented_lines: bool = True, comment_char: str = "#"
) -> List[str]:
    """
    Read `filename` into list of strings but ignore lines starting
    with the given `comment_char` character.
    Default comment character is #
    """
    try:
        with open(filename, encoding="utf8") as f:
            results = []
            for line in f:
                line = line.strip()

                if line and not (
                    skip_commented_lines and line.startswith(comment_char)
                ):
                    results.append(line)

            return results

    except IOError as e:
        print("Error loading", filename, e)
        return []


def write_file(filename: pathlib.Path, contents: Iterable[str]) -> None:
    with open(filename, "w", encoding="utf8") as f:
        for item in contents:
            f.write(str(item))
            f.write("\n")


def slugify(value: str, allow_unicode: bool = False) -> str:
    """
    Taken from https://github.com/django/django/blob/master/django/utils/text.py
    Convert to ASCII if 'allow_unicode' is False. Convert spaces or repeated
    dashes to single dashes. Remove characters that aren't alphanumerics,
    underscores, or hyphens. Convert to lowercase. Also strip leading and
    trailing whitespace, dashes, and underscores.
    """
    value = str(value)
    if allow_unicode:
        value = unicodedata.normalize("NFKC", value)
    else:
        value = (
            unicodedata.normalize("NFKD", value)
            .encode("ascii", "ignore")
            .decode("ascii")
        )
    value = re.sub(r"[^\w\s-]", "", value.lower())
    return re.sub(r"[-\s]+", "-", value).strip("-_")


def paginate(
    content: Union[str, List[str]],
    *,
    length: int = DISCORD_MSG_CHAR_LIMIT,
    reserve: int = 0,
) -> List[str]:
    """
    Split up a large string or list of strings into chunks for sending to discord.
    """
    if isinstance(content, str):
        contentlist = content.split("\n")
    elif isinstance(content, list):
        contentlist = content
    else:
        raise ValueError("Content must be str or list, not %s" % type(content))

    chunks = []
    currentchunk = ""

    for line in contentlist:
        if len(currentchunk) + len(line) < length - reserve:
            currentchunk += line + "\n"
        else:
            chunks.append(currentchunk)
            currentchunk = ""

    if currentchunk:
        chunks.append(currentchunk)

    return chunks


async def get_headers(
    session: aiohttp.ClientSession,
    url: str,
    *,
    timeout: int = 5,
    allow_redirects: bool = True,
    req_headers: Dict[str, Any] = {},
) -> Union["CIMultiDictProxy[str]", None]:
    """
    Uses given aiohttp `session` to make a HEAD request against given `url` to fetch headers only.
    If `headerfield` is set, only the given header field is returned.

    :param: timeout:  Set a different timeout for the HEAD request.
    :param: allow_redirect:  Follow "Location" headers through, on by default.
    :param: req_headers:  Set a collection of headers to send with the HEAD request.
    """
    req_timeout = aiohttp.ClientTimeout(total=timeout)
    async with session.head(
        url, timeout=req_timeout, allow_redirects=allow_redirects, headers=req_headers
    ) as response:
        return response.headers


def instance_diff(obj1: Any, obj2: Any) -> Dict[str, Tuple[Any, Any]]:
    """
    Compute a dict showing which attributes have changed between two given objects.
    Objects must be of the same type and have __slots__ or __dict__.
    """
    if type(obj1) is not type(obj2):
        raise ValueError("Objects must be of the same type to get differences.")

    changes: Dict[str, Tuple[Any, Any]] = {}
    keys = set()
    if hasattr(obj1, "__slots__") and hasattr(obj2, "__slots__"):
        vars1 = getattr(obj1, "__slots__", [])
        vars2 = getattr(obj2, "__slots__", [])
        if isinstance(vars1, list) and isinstance(vars2, list):
            keys = set(vars1 + vars2)
    elif hasattr(obj1, "__dict__") and hasattr(obj2, "__dict__"):
        vars1 = getattr(obj1, "__dict__", {})
        vars2 = getattr(obj2, "__dict__", {})
        if isinstance(vars1, dict) and isinstance(vars2, dict):
            keys = set(list(vars1.keys()) + list(vars2.keys()))
    else:
        raise ValueError(
            f"Objects don't have __slots__ or __dict__ attribute: ({type(obj1)}, {type(obj2)})"
        )

    for key in keys:
        val1 = getattr(obj1, key, None)
        val2 = getattr(obj2, key, None)
        if val1 != val2:
            changes[key] = (val1, val2)
    return changes


def _func_() -> str:
    """
    Gets the name of the calling frame code object.
    Emulates __func__ from C++
    """
    frame = inspect.currentframe()
    if not frame or not frame.f_back:
        raise RuntimeError(
            "Call to _func_() failed, may not be available in this context."
        )

    return frame.f_back.f_code.co_name


def _get_variable(name: str) -> Any:
    stack = inspect.stack()
    try:
        for frames in stack:
            try:
                frame = frames[0]
                current_locals = frame.f_locals
                if name in current_locals:
                    return current_locals[name]
            finally:
                del frame
    finally:
        del stack


# TODO: Add some sort of `denied` argument for a message to send when someone else tries to use it
def owner_only(func: Callable[..., Any]) -> Any:
    @wraps(func)
    async def wrapper(self: "MusicBot", *args: Any, **kwargs: Any) -> Any:
        # Only allow the owner to use these commands
        orig_msg = _get_variable("message")

        if not orig_msg or orig_msg.author.id == self.config.owner_id:
            return await func(self, *args, **kwargs)
        else:
            raise PermissionsError("Only the owner can use this command.", expire_in=30)

    return wrapper


def dev_only(func: Callable[..., Any]) -> Any:
    @wraps(func)
    async def wrapper(self: "MusicBot", *args: Any, **kwargs: Any) -> Any:
        orig_msg = _get_variable("message")

        if orig_msg.author.id in self.config.dev_ids:
            return await func(self, *args, **kwargs)
        else:
            raise PermissionsError("Only dev users can use this command.", expire_in=30)

    setattr(wrapper, "dev_cmd", True)
    return wrapper


def is_empty_voice_channel(
    voice_channel: Union["VoiceChannel", "StageChannel", None],
    *,
    exclude_me: bool = True,
    exclude_deaf: bool = True,
    include_bots: Set[int] = set(),
) -> bool:
    """
    Check if the given `voice_channel` is figuratively or literally empty.

    :param: `exclude_me`: Exclude our bot instance, the default.
    :param: `exclude_deaf`: Excludes members who are self-deaf or server-deaf.
    :param: `include_bots`: A list of bot IDs to include if they are present.
    """
    if not voice_channel:
        log.debug("Cannot count members when voice_channel is None.")
        return True

    def _check(member: "Member") -> bool:
        if exclude_me and member == voice_channel.guild.me:
            return False

        if (
            member.voice
            and exclude_deaf
            and any([member.voice.deaf, member.voice.self_deaf])
        ):
            return False

        if member.bot and member.id not in include_bots:
            return False

        return True

    return not sum(1 for m in voice_channel.members if _check(m))


def count_members_in_voice(
    voice_channel: Union["VoiceChannel", "StageChannel", None],
    include_only: Iterable[int] = [],
    include_bots: Iterable[int] = [],
    exclude_ids: Iterable[int] = [],
    exclude_me: bool = True,
    exclude_deaf: bool = True,
) -> int:
    """
    Counts the number of members in given voice channel.
    By default it excludes all deaf users, all bots, and the MusicBot client itself.

    :param: voice_channel:  A VoiceChannel to inspect.
    :param: include_only:  A list of Member IDs to check for, only members in this list are counted if present.
    :param: include_bots:  A list of Bot Member IDs to include.  By default all bots are excluded.
    :param: exclude_ids:  A list of Member IDs to exclude from the count.
    :param: exclude_me:  A switch to, by default, exclude the bot ClientUser.
    :param: exclude_deaf:  A switch to, by default, exclude members who are deaf.
    """
    if not voice_channel:
        log.debug("Cannot count members when voice_channel is None.")
        return 0

    num_voice = 0
    log.noise(  # type: ignore[attr-defined]
        f"Channel Count Pre-Filter:  {len(voice_channel.members)}"
    )
    for member in voice_channel.members:
        if not member:
            continue

        if member.bot and member.id not in include_bots:
            continue

        if exclude_me and member == voice_channel.guild.me:
            continue

        if exclude_ids and member.id in exclude_ids:
            continue

        voice = member.voice
        if not voice:
            continue

        if exclude_deaf and (voice.deaf or voice.self_deaf):
            continue

        if include_only and member.id not in include_only:
            continue

        num_voice += 1
    log.noise(f"Channel Count Post-Filter:  {num_voice}")  # type: ignore[attr-defined]
    return num_voice


def format_song_duration(time_delta: str) -> str:
    """Conditionally remove hour component of timedelta string if it is 0."""
    duration_array = time_delta.split(":")
    return time_delta if int(duration_array[0]) > 0 else ":".join(duration_array[1:])


def format_size_from_bytes(size_bytes: int) -> str:
    suffix = {0: "", 1: "Ki", 2: "Mi", 3: "Gi", 4: "Ti"}
    power = 1024
    size = float(size_bytes)
    i = 0
    while size > power:
        size /= power
        i += 1
    return f"{size:.3f} {suffix[i]}B"


def format_size_to_bytes(size_str: str, strict_si: bool = False) -> int:
    """Convert human-friendly *bytes notation into integer.
    Note: this function is not intended to convert Bits notation.

    Option `strict_si` will use 1000 rather than 1024 for SI suffixes.
    """
    si_units = 1024
    if strict_si:
        si_units = 1000
    suffix_list = {
        "kilobyte": si_units,
        "megabyte": si_units**2,
        "gigabyte": si_units**3,
        "terabyte": si_units**4,
        "petabyte": si_units**5,
        "exabyte": si_units**6,
        "zetabyte": si_units**7,
        "yottabyte": si_units**8,
        "kb": si_units,
        "mb": si_units**2,
        "gb": si_units**3,
        "tb": si_units**4,
        "pb": si_units**5,
        "eb": si_units**6,
        "zb": si_units**7,
        "yb": si_units**8,
        "kibibyte": 1024,
        "mebibyte": 1024**2,
        "gibibyte": 1024**3,
        "tebibyte": 1024**4,
        "pebibyte": 1024**5,
        "exbibyte": 1024**6,
        "zebibyte": 1024**7,
        "yobibyte": 1024**8,
        "kib": 1024,
        "mib": 1024**2,
        "gib": 1024**3,
        "tib": 1024**4,
        "pib": 1024**5,
        "eib": 1024**6,
        "zib": 1024**7,
        "yib": 1024**8,
    }
    size_str = size_str.lower().strip().strip("s")
    for suffix in suffix_list:
        if size_str.endswith(suffix):
            return int(float(size_str[0 : -len(suffix)]) * suffix_list[suffix])
    else:
        if size_str.endswith("b"):
            size_str = size_str[0:-1]
        elif size_str.endswith("byte"):
            size_str = size_str[0:-4]
    return int(size_str)


def format_time_to_seconds(time_str: Union[str, int]) -> int:
    """Convert a phrase containing time duration(s) to seconds as int
    This function allows for intresting/sloppy time notations like:
    - 1yearand2seconds  = 31556954
    - 8s 1d             = 86408
    - .5 hours          = 1800
    - 99 + 1            = 100
    - 3600              = 3600
    Only partial seconds are not supported, thus ".5s + 1.5s" will be 1 not 2.

    Param `time_str` is assumed to contain a time duration as str or int.
    Returns 0 if no time value is recognised, rather than raise a ValueError.
    """
    if isinstance(time_str, int):
        return time_str

    # TODO: find a good way to make this i18n friendly.
    time_lex = re.compile(r"(\d*\.?\d+)\s*(y|d|h|m|s)?", re.I)
    unit_seconds = {
        "y": 31556952,
        "d": 86400,
        "h": 3600,
        "m": 60,
        "s": 1,
    }
    total_sec = 0
    for value, unit in time_lex.findall(time_str):
        if not unit:
            unit = "s"
        else:
            unit = unit[0].lower().strip()
        total_sec += int(float(value) * unit_seconds[unit])
    return total_sec
