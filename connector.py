"""AWS에서 데이터 가져오기."""
# Power Bi에 경고 없이 빠르게 파이썬 버전을 반환
import warnings
warnings.filterwarnings('ignore')  # disable warning for dist binary.
import sys
import platform

if len(sys.argv) > 1 and sys.argv[1] == '-V':
    print("Python {}".format(platform.python_version()))
    sys.exit()

# 여기서 부터 시작 ---------------------------------

import os
import sys
import re
import codecs
import time
from configparser import ConfigParser
from datetime import datetime, timedelta
from shutil import copyfile
from pathlib import Path

import pandas as pd
from dateutil.parser import parse
from pyathena import connect

from util import *

PBTDIR_PTRN = r"os.chdir\((?:u')?(.*)(?:')\)"
cursor = None
cfg_hash = None

# Power BI에서 실행 여부 \
POWER_BI = len(sys.argv) > 1 and sys.argv[1].lower() == 'pythonscriptwrapper.py'
start_mode = 'Test' if not POWER_BI else 'Power BI'
critical("======== Connector Start ({} Mode) ========".format(start_mode))
info("Start up argv: {}".format(sys.argv))
info("Project Dir: {}".format(pypbac_dir))


def copy_cache(pbt_dir):
    """로컬 캐쉬를 복사."""
    info("copy_cache from {}".format(pcache_dir))
    cnt = 0
    for ofile in os.listdir(pcache_dir):
        if not ofile.endswith('.csv'):
            continue
        spath = os.path.join(pcache_dir, ofile)
        dpath = os.path.join(pbt_dir, ofile)
        info("Copy from {} to {}".format(spath, dpath))
        copyfile(spath, dpath)
        cnt += 1
    info("  total {} files copied.".format(cnt))


def check_import_data(cfg):
    """Power BI 용 데이터 가져오기.
    
    - 유효한 로컬 캐쉬가 았으면 그것을 이용
    - 아니면 새로 가져와 로컬 캐쉬에 저장
    """
    global pbt_dir

    # Python 데이터 소스용 임시 디렉토리 얻음
    if POWER_BI:
        arg = sys.argv[1]
        with codecs.open(arg, 'r', encoding='utf-8') as fp:
            wrapper = fp.read()
        try:
            pbt_dir = re.search(PBTDIR_PTRN, wrapper).groups()[0]
        except Exception as e:
            error("Can't find Working Directory at PythonScriptWrapper.py:")
            error(wrapper)
            sys.exit()
    else:
        pbt_dir = os.path.join(mod_dir, 'temp')
        if not os.path.isdir(pbt_dir):
            os.mkdir(pbt_dir)

    info("Power BI Temp Dir: {}".format(pbt_dir))

    # 가능하면 캐쉬 이용
    if os.path.isdir(cache_dir) and os.path.isfile(meta_path):
        # 메타 데이터 읽어옴
        meta = ConfigParser()
        meta.read(meta_path)

        # 캐쉬 수명 체크
        created = parse(meta['default']['created'])
        dif = datetime.now() - created
        days, hours, mins = dif.days, dif.seconds // 3600, dif.seconds // 60
        cache_valid_hour = int(cfg[profile]['cache_valid_hour'])
        valid_life = dif.seconds < cache_valid_hour * 3600
        info("Cache created {} days {} hours {} minutess ago: {}".format(days, hours, mins, valid_life))
        meta_cfg_hash = meta['default']['config_hash']
        valid_cfg = meta_cfg_hash == cfg_hash
        if not valid_cfg:
            info("Config hash mismatch: {}(old) != {}(new)".format(meta_cfg_hash, cfg_hash))
        else:
            info("Config hash match: {}".format(cfg_hash))

        # 캐쉬 이용 가능하면
        if valid_life and valid_cfg:
            # 유효한 캐쉬를 복사해 사용하고
            warning("Use cache data.")
            try:
                copy_cache(pbt_dir)
            except Exception as e:
                error("Copy error: {}".format(str(e)))
            # 종료
            # time.sleep(5)  # 미리보기 안되는 이슈에 도움?
            sys.exit()
        else:
            # 오래된 캐쉬 지움
            del_cache()
    else:
        info("No cache available. Import now.")

    # 아니면 새로 가져옴
    _import_data(cfg)


def save_metadata():
    warning("save_metadata")
    meta = ConfigParser()
    meta['default'] = {}
    created = datetime.now()
    meta['default']['created'] = created.strftime('%Y-%m-%d %H:%M:%S')
    meta['default']['config_hash'] = cfg_hash

    with open(meta_path, 'w') as fp:
        meta.write(fp)


def _import_data(cfg):
    """설정대로 데이터 가져오기.
    
    - Power BI에서 불려짐
    - 유효한 캐쉬가 있으면 이용
    - 아니면 새로 가져옴
    """
    global cursor
    warning("Import data.")

    # 접속
    info("Connect to import.")
    conn = connect(aws_access_key_id=cfg['aws']['access_key'],
        aws_secret_access_key=cfg['aws']['secret_key'],
        s3_staging_dir=cfg['aws']['s3_stage_dir'],
        region_name='ap-northeast-2')
    cursor = conn.cursor()

    sect = cfg[profile]
    ttype = sect['ttype']
    if ttype == 'rel':
        before = int(sect['before'])
        offset = int(sect['offset'])
    else:
        start = parse(sect['start']).date()
        end = parse(sect['end']).date()

    # 모든 대상 DB의 테이블에 대해
    for key in cfg[profile].keys():
        if not key.startswith('db_'):
            continue 
        db = key[3:]
        tables = eval(cfg[profile][key])
        for tbl in tables:
            # 쿼리 준비
            if ttype == 'rel':
                cnt = get_query_rows_rel(cursor, db, tbl, before, offset)
                query = make_query_rel(db, tbl, before, offset, False)

            else:
                cnt = get_query_rows_abs(cursor, db, tbl, start, end)
                query = make_query_abs(db, tbl, start, end, False)

            # 가져옴
            warning("Import '{}' ({:,} rows) from '{}'".format(tbl, cnt, db))
            info("  query: {}".format(query))
            df = pd.read_sql(query, conn)
            csv_file = "{}.{}.csv".format(db, tbl)
            spath = os.path.join(pcache_dir, csv_file)
            dpath = os.path.join(pbt_dir, csv_file)            

            # 저장
            info("Write CSV to cache: {}".format(spath))
            df.to_csv(spath, index=False, encoding='utf-8-sig')
            info("Copy from {} to {}\n".format(spath, dpath))
            copyfile(spath, dpath)

    # 메타정보 기록
    save_metadata()
    critical("======= Import successful =======")


# 설정 읽기
cfg, cfg_hash = load_config()
# 데이터 임포트 후 종료
check_import_data(cfg)
