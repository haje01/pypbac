import os 
import logging
import hashlib
from configparser import ConfigParser
from shutil import rmtree
from datetime import datetime, timedelta


LOG_FILE = 'log.txt'
CFG_FILE = 'config.txt'
WARN_ROWS = 1000000  # 이 행수 이상 경고

profile = 'profile.default'
selected_tables = {}
first_sel_db = first_sel_db_idx = None


# 각종 경로 초기화
mod_dir = os.path.dirname(os.path.abspath(__file__))
home_dir = os.path.expanduser('~')
pypbac_dir = os.path.join(home_dir, ".pypbac")
cache_dir = os.path.join(pypbac_dir, 'cache')
pcache_dir = os.path.join(cache_dir, 'default')
log_path = os.path.join(pypbac_dir, LOG_FILE)
cfg_path = os.path.join(pypbac_dir, CFG_FILE)
meta_path = os.path.join(pcache_dir, 'metadata.txt')

# 필요한 디렉토리 생성
if not os.path.isdir(pypbac_dir):
    os.mkdir(pypbac_dir)
if not os.path.isdir(cache_dir):
    os.mkdir(cache_dir)
if not os.path.isdir(pcache_dir):
    os.mkdir(pcache_dir)


logging.basicConfig(
     filename=log_path,
     level=logging.INFO, 
     format= '[%(asctime)s] {%(pathname)s:%(lineno)d} %(levelname)s - %(message)s',
     datefmt='%H:%M:%S'
 )

# set up logging to console
console = logging.StreamHandler()
console.setLevel(logging.DEBUG)
# set a format which is simpler for console use
formatter = logging.Formatter('%(name)-12s: %(levelname)-8s %(message)s')
console.setFormatter(formatter)
# add the handler to the root logger
logging.getLogger('').addHandler(console)

logger = logging.getLogger(__name__)

def info(msg):
    logger.info(msg)


def warning(msg):
    logger.warning(msg)


def error(msg):
    logger.error(msg)


def critical(mst):
    logger.critical(mst)


def get_file_hash(path):
    """파일 해쉬 구하기."""
    hash = None
    md5 = hashlib.md5()
    with open(path, 'rb') as f:
        data = f.read()
        md5.update(data)
        hash = md5.hexdigest()
    info("get_file_hash from {}: {}".format(path, hash))
    return hash


def load_config():
    """설정 읽기

    Args:
        apply_doc (bool): 읽은 설정을 도큐먼트에 적용 여부.
    """
    warning("Load config: {}".format(cfg_path))
    cfg = ConfigParser()
    cfg.read(cfg_path)
    cfg_hash = get_file_hash(cfg_path)

    return cfg, cfg_hash


def del_cache():
    warning("Remove old profile cache dir: {}".format(pcache_dir))
    rmtree(pcache_dir)
    os.mkdir(pcache_dir)


def make_query_rel(db, table, before, offset, for_count):
    """상대 시간으로 질의를 만듦.

    Args:
        db (str): DB명
        table (str): table명
        before (date): 몇 일 전부터
        offset (date): 몇 일치 
        for_count: 행수 구하기 여부
    """
    assert before > 0 and offset > 0
    today = datetime.today().date()
    end_dt = today - timedelta(days=before)
    start_dt = end_dt - timedelta(days=offset - 1)
    start_dt = start_dt.strftime('%Y%m%d')
    end_dt = end_dt.strftime('%Y%m%d')
    return _make_query(db, table, start_dt, end_dt, for_count)


def _make_query(db, table, start_dt, end_dt, for_count):
    if not for_count:
        query = "SELECT * "
    else:
        query = "SELECT COUNT(*) as cnt "
    if start_dt == end_dt:
        query += "FROM {}.{} WHERE (year || month || day) = '{}'".\
            format(db, table, end_dt)
    else:
        query += "FROM {}.{} WHERE (year || month || day) >= '{}' AND "\
                "(year || month || day) <= '{}'".\
                format(db, table, start_dt, end_dt)
    return query


def make_query_abs(db, table, start_dt, end_dt, for_count):
    """절대 시간으로 질의를 만듦.

    Args:
        db (str): DB명
        table (str): table명
        start_dt (date): 시작일
        end_dt (date): 종료일
        for_count: 행수 구하기 여부
    """
    assert type(start_dt) is date and type(end_dt) is date
    start_dt = start_dt.strftime('%Y%m%d')
    end_dt = end_dt.strftime('%Y%m%d')
    return _make_query(db, table, start_dt, end_dt, for_count)


def get_query_rows_rel(cursor, db, table, before, offset):
    info("get_query_rows_rel")
    query = make_query_rel(db, table, before, offset, True)
    info("  query: {}".format(query))
    rows = cursor.execute(query).fetchone()
    return rows[0]


def get_query_rows_abs(cursor, db, table, start_dt, end_dt):
    info("get_query_rows_abs")
    query = make_query_abs(db, table, start_dt, end_dt, True)
    info("  query: {}".format(query))
    rows = cursor.execute(query).fetchone()
    return rows[0]
