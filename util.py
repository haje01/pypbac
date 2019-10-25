import os 
import re
import logging
import hashlib
from configparser import ConfigParser
from shutil import rmtree
from datetime import datetime, timedelta, date

from dateutil.parser import parse
import requests

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


def make_query_rel(db, table, before, offset, dscfg, mode, cols=None):
    """상대 시간으로 질의를 만듦.

    Args:
        db (str): DB명
        table (str): table명
        before (date): 몇 일 전부터
        offset (date): 몇 일치 
        dscfg (ConfigParser): 데이터 스크립트 설정
        mode: 쿼리 모드 ('count' - 행 수 구하기, 'preview' - 프리뷰)
        cols: 명시적 선택 컬럼
    """
    assert before > 0 and offset > 0
    today = datetime.today().date()
    end_dt = today - timedelta(days=before)
    start_dt = end_dt - timedelta(days=offset - 1)
    start_dt = start_dt.strftime('%Y%m%d')
    end_dt = end_dt.strftime('%Y%m%d')
    return _make_query(db, table, start_dt, end_dt, dscfg, mode, cols)


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


def _make_query(db, table, start_dt, end_dt, dscfg, mode, cols):
    assert mode in ('default', 'count', 'preview')

    if mode in ('default', 'preview'):
        if cols is None:
            query = "SELECT *"
        else:
            scols = ', '.join(cols)
            query = "SELECT {}".format(scols)
        if dscfg is not None:
            query = _add_column_query(db, table, query, dscfg)
    elif mode == 'count':
        query = "SELECT COUNT(*) AS cnt"

    if start_dt == end_dt:
        query += " FROM {}.{} WHERE (year || month || day) = '{}'".\
            format(db, table, end_dt)
    else:
        query += " FROM {}.{} WHERE (year || month || day) >= '{}' AND "\
                "(year || month || day) <= '{}'".\
                format(db, table, start_dt, end_dt)
        if dscfg is not None:                
            query = _add_filter_query(db, table, query, dscfg)
    
    if mode == 'preview':
        query += " LIMIT 50"
    return query


def make_query_abs(db, table, start_dt, end_dt, dscfg, mode, cols=None):
    """절대 시간으로 질의를 만듦.

    Args:
        db (str): DB명
        table (str): table명
        start_dt (date): 시작일
        end_dt (date): 종료일
        dscfg (ConfigParser): 데이터 스크립트 설정
        mode: 쿼리 모드 ('count' - 행 수 구하기, 'preview' - 프리뷰)
        cols: 명시적 선택 컬럼
    """
    assert type(start_dt) is date and type(end_dt) is date
    start_dt = start_dt.strftime('%Y%m%d')
    end_dt = end_dt.strftime('%Y%m%d')
    return _make_query(db, table, start_dt, end_dt, dscfg, mode, cols)


def get_query_rows_rel(cursor, db, table, before, offset, dscfg):
    """상대 날자로 쿼리 대상 행수 구함."""
    info("get_query_rows_rel")
    query = make_query_rel(db, table, before, offset, dscfg, "count")
    info("  query: {}".format(query))
    rows = cursor.execute(query).fetchone()
    return rows[0]


def get_query_rows_abs(cursor, db, table, start_dt, end_dt, dscfg):
    """절대 날자로 쿼리 대상 행수 구함."""
    info("get_query_rows_abs")
    query = make_query_abs(db, table, start_dt, end_dt, dscfg, "count")
    info("  query: {}".format(query))
    rows = cursor.execute(query).fetchone()
    return rows[0]


def get_query_preview_rel(cursor, db, table, before, offset, dscfg):
    """상대 날자로 쿼리 프리뷰 구함."""
    info("get_query_preview_rel: {} - {}".format(db, table))
    query = make_query_rel(db, table, before, offset, dscfg, "preview")
    info("  query: {}".format(query))
    rows = cursor.execute(query).fetchall()
    return rows


def get_query_preview_abs(cursor, db, table, start_dt, end_dt, dscfg):
    """절대 날자로 쿼리 프리뷰 구함."""
    info("get_query_preview_abs: {} - {}".format(db, table))
    query = make_query_abs(db, table, start_dt, end_dt, dscfg, "preview")
    info("  query: {}".format(query))
    rows = cursor.execute(query).fetchall()
    return rows


def get_table_columns(cursor, db, table):
    """테이블의 컬럼명을 얻음."""
    info("get_table_columns: {} - {}".format(db, table))
    query = "SHOW COLUMNS IN {}.{}".format(db, table)
    info("  query: {}".format(query))
    cols = cursor.execute(query).fetchall()
    cols = [col[0].strip() for col in cols]
    return cols


def get_local_version():
    """로컬(version.txt) 버전을 구함.
    
    [0, 0, 3, 0] -> "v0.0.3" 형태로 바꾸어 사용
    
    """
    path = os.path.join(mod_dir, 'version.txt')
    info("get_version() from '{}'".format(path))
    try:
        with open(path, 'rt') as fp:
            txt = fp.read()
            try:
                match = re.search(r'filevers=\((.*)\)', txt)
                elms = match.groups()[0].split(',')
                elms = [e.strip() for e in elms]
            except Exception as e:
                error("get_version() error {} - {}".format(str(e), txt))
            else:
                elms = elms[:3]
                version = 'v' + '.'.join(elms)  
                return version
    except Exception as e:
        error("File open error: {}".format(e))

def get_latest_release():

    """원격(github)에 릴리즈된 최신 버전 정보 구함.

    주의: 시간당 60회 아상 요청하면 "API rate limit exceeded" 에러가 발생. 이때는 None 리턴
    
    Returns:
        tuple: 버전 태그, 버전 타이틀, 버전 설명, 생성 날자, pre-release 여부
    """
    info("get_latest_release")
    url = "https://api.github.com/repos/haje01/pypbac/releases/latest"
    res = requests.get(url)
    body = res.json()
    try:
        return body['tag_name'], body['name'], body['body'], body['created_at'], body['prerelease']
    except Exception as e:
        error("Invalid release info - {}".format(str(e)))
        if 'message' in body:
            warning(body['message'])


if __name__ == "__main__":
    # test script here.
    rel = get_latest_release()
    pass