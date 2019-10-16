import os 
import logging
import hashlib
from configparser import ConfigParser
from shutil import rmtree
from datetime import datetime, timedelta, date
from dateutil.parser import parse

LOG_FILE = 'log.txt'
CFG_FILE = 'config.txt'
WARN_ROWS = 1000000  # 이 행수 이상 경고

profile = 'profile.default'
selected_tables = {}
first_sel_db = first_sel_db_idx = None


# 각종 경로 초기화
mod_dir = os.path.dirname(os.path.abspath(__file__))
home_dir = os.path.expanduser('~')
proj_dir = os.path.join(home_dir, ".pypbac")
cache_base_dir = os.path.join(proj_dir, 'cache')
log_path = os.path.join(proj_dir, LOG_FILE)
cfg_path = os.path.join(proj_dir, CFG_FILE)

# 필요한 디렉토리 생성
if not os.path.isdir(proj_dir):
    os.mkdir(proj_dir)
if not os.path.isdir(cache_base_dir):
    os.mkdir(cache_base_dir)


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


def get_text_hash(text):
    """텍스트 해쉬 구하기."""
    md5 = hashlib.md5()
    md5.update(text.encode('utf-8'))
    return md5.hexdigest()


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


def get_cache_dir(pro_name):
    return os.path.join(cache_base_dir, pro_name)


def get_meta_path(pro_name):
    cache_dir = get_cache_dir(pro_name)
    meta_path = os.path.join(cache_dir, 'metadata.txt')
    return meta_path


def check_cache_dir(pro_name):
    """프로파일 용 캐쉬 디렉토리를 확인 후 없으면 만듦.
    
    Args:
        pro_name (str): 프로파일 명
    
    Returns:
        str: 프로파일 캐쉬 디렉토리 경로
    """
    cache_dir = get_cache_dir(pro_name)
    if not os.path.isdir(cache_dir):
        os.mkdir(cache_dir)
    return cache_dir


def del_cache(pro_name):
    pcache_dir = get_cache_dir(pro_name)
    if os.path.isdir(pcache_dir):
        warning("Remove old profile cache dir: {}".format(pcache_dir))
        rmtree(pcache_dir)
    os.mkdir(pcache_dir)


def make_query_rel(db, table, before, offset, dscfg, for_count):
    """상대 시간으로 질의를 만듦.

    Args:
        db (str): DB명
        table (str): table명
        before (date): 몇 일 전부터
        offset (date): 몇 일치 
        dscfg (ConfigParser): 데이터 스크립트 설정
        for_count: 행수 구하기 여부
    """
    assert before > 0 and offset > 0
    today = datetime.today().date()
    end_dt = today - timedelta(days=before)
    start_dt = end_dt - timedelta(days=offset - 1)
    start_dt = start_dt.strftime('%Y%m%d')
    end_dt = end_dt.strftime('%Y%m%d')
    return _make_query(db, table, start_dt, end_dt, dscfg, for_count)


def _add_column_query(db, table, query, dscfg):
    """쿼리에 컬럼 추가."""
    for sect in dscfg.keys():
        if not sect.startswith('column'):
            continue

        add = False
        if sect == 'column':
            add = True
        elif sect.startswith('column.'):
            elms = sect.split('.')
            _table = elms[1]
            if len(elms) == 3:
                _db = elms[2]
                add = table == _table and db == _db
            else:
                add = table == _table

        if add:
            ccfg = dscfg[sect]
            for line in ccfg.values():
                query += ", {}".format(line)
    return query


def _add_filter_query(db, table, query, dscfg):
    """쿼리에 필터 추가."""
    for sect in dscfg.keys():
        if not sect.startswith('filter'):
            continue

        add = False
        if sect == 'filter':
            add = True
        elif sect.startswith('filter.'):
            elms = sect.split('.')
            _table = elms[1]
            if len(elms) == 3:
                _db = elms[2]
                add = table == _table and db == _db
            else:
                add = table == _table

        if add:
            fcfg = dscfg[sect]
            for line in fcfg.values():
                query += " AND {}".format(line)
    return query


def _make_query(db, table, start_dt, end_dt, dscfg, for_count):
    if not for_count:
        query = "SELECT *"
        if dscfg is not None:
            query = _add_column_query(db, table, query, dscfg)
    else:
        query = "SELECT COUNT(*) as cnt"
    if start_dt == end_dt:
        query += " FROM {}.{} WHERE (year || month || day) = '{}'".\
            format(db, table, end_dt)
    else:
        query += " FROM {}.{} WHERE (year || month || day) >= '{}' AND "\
                "(year || month || day) <= '{}'".\
                format(db, table, start_dt, end_dt)
        if dscfg is not None:                
            query = _add_filter_query(db, table, query, dscfg)
    return query


def make_query_abs(db, table, start_dt, end_dt, dscfg, for_count):
    """절대 시간으로 질의를 만듦.

    Args:
        db (str): DB명
        table (str): table명
        start_dt (date): 시작일
        end_dt (date): 종료일
        dscfg (ConfigParser): 데이터 스크립트 설정
        for_count: 행수 구하기 여부
    """
    assert type(start_dt) is date and type(end_dt) is date
    start_dt = start_dt.strftime('%Y%m%d')
    end_dt = end_dt.strftime('%Y%m%d')
    return _make_query(db, table, start_dt, end_dt, dscfg, for_count)


def get_query_rows_rel(cursor, db, table, before, offset, dscfg):
    info("get_query_rows_rel")
    query = make_query_rel(db, table, before, offset, dscfg, True)
    info("  query: {}".format(query))
    rows = cursor.execute(query).fetchone()
    return rows[0]


def get_query_rows_abs(cursor, db, table, start_dt, end_dt, dscfg):
    info("get_query_rows_abs")
    query = make_query_abs(db, table, start_dt, end_dt, dscfg, True)
    info("  query: {}".format(query))
    rows = cursor.execute(query).fetchone()
    return rows[0]
