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

import tkinter  # pyinstaller 빌드에서 tcl/tk 포함되지 않는 것 방지
import win32api
import pandas as pd
from dateutil.parser import parse
from pyathena import connect

from util import *

PBTDIR_PTRN = r"os.chdir\((?:u')?(.*)(?:')\)"
PRO_BEGIN_PTRN = r"# Original Script[^#]+"
PRO_END_PTRN = r"# Epilog -[^#]+"

cursor = None

# Power BI에서 실행 여부 \
POWER_BI = len(sys.argv) > 1 and sys.argv[1].lower() == 'pythonscriptwrapper.py'
start_mode = 'Test' if not POWER_BI else 'Power BI'
critical("======== Connector Start ({} Mode) ========".format(start_mode))
info("Start up argv: {}".format(sys.argv))
info("Project Dir: {}".format(proj_dir))


def copy_cache(pbt_dir, cache_dir):
    """로컬 캐쉬를 복사."""
    info("copy_cache from {}".format(cache_dir))
    cnt = 0
    for ofile in os.listdir(cache_dir):
        if not ofile.endswith('.csv'):
            continue
        spath = os.path.join(cache_dir, ofile)
        dpath = os.path.join(pbt_dir, ofile)
        info("  copy from {} to {}".format(spath, dpath))
        copyfile(spath, dpath)
        cnt += 1
    info("total {} files copied.".format(cnt))


def get_dscript_cfg(wrapper):
    """PythonScriptWrapper.py에서 프로파일 관련 설정 얻기.
    
    Args:
        wrapper (str): PythonScriptWrapper.py의 내용
    
    Returns:
        tuple: 데이터 스크립트 파싱한 ConfigParser, 데이터 스크립트 hash
    """
    bg_match = re.search(r"# Original Script[^#]+", wrapper)
    begin = bg_match.span()[1] + 1
    ed_match = re.search("# Epilog -[^#]+", wrapper)
    end = ed_match.span()[0] - 1
    dscript = "[default]\n{}".format(wrapper[begin:end].strip())
    dscript_hash = get_text_hash(dscript)
    info("=== Data script in PythonScriptWrapper.py ===")
    info(dscript)
    info("======")
    cfg = ConfigParser()
    try:
        cfg.read_string(dscript)
    except Exception as e:
        warning("Invalid config format: {}".format(str(e)))
        return
    return cfg, dscript_hash


def check_import_data(cfg, cfg_hash):
    """Power BI 용 데이터 가져오기.
    
    - 유효한 로컬 캐쉬가 았으면 그것을 이용
    - 아니면 새로 가져와 로컬 캐쉬에 저장
    """
    global pbt_dir

    # PythonScriptWrapper.py에서 데이터 소스용 임시 디렉토리와 데이터 스크립트 정보 얻음
    pro_name = 'default'
    dscript_hash = ''
    dscfg = None
    if POWER_BI:
        arg = sys.argv[1]
        with codecs.open(arg, 'r', encoding='utf-8') as fp:
            wrapper = fp.read()

        try:
            # Power BI 데이터 소스 임시 경로
            pbt_dir = re.search(PBTDIR_PTRN, wrapper).groups()[0]
        except Exception as e:
            error("Can not find pbt_dir in PythonScriptWrapper.py:")
            info(wrapper)   
            sys.exit(-1)

        try:
            # 프로파일 정보
            res = get_dscript_cfg(wrapper)
            if res is not None:
                dscfg, dscript_hash = res
                ddscfg = dscfg['default']
                if 'profile' in ddscfg:
                    pro_name = ddscfg['profile']
        except Exception as e:
            error("Data script error: {}".format(str(e)))

        if pro_name == 'default':
            info("Using default profile.")
    else:
        # VS Code에서 실행?
        critical("======= No argument. Exit now =======")
        sys.exit()
        # pbt_dir = os.path.join(mod_dir, 'temp')
        # if not os.path.isdir(pbt_dir):
        #     os.mkdir(pbt_dir)

    # 설정 파일에서 해당 프로파일 정보 찾아보기
    pkey = "profile.{}".format(pro_name)
    if pkey in cfg:
        pcfg = cfg[pkey]
    else:
        error("Can not find '{}' profile.".format(pro_name))
        win32api.MessageBox(0, "설정에서 '{}' 프로파일을 찾을 수 없습니다.".format(pro_name))
        sys.exit(-1)

    # 필요한 경로 얻기
    cache_dir = check_cache_dir(pro_name)
    meta_path = get_meta_path(pro_name)
    info("Power BI Temp Dir: {}".format(pbt_dir))
    info("pro_name: {}".format(pro_name))
    info("cache_dir: {}".format(cache_dir))
    info("meta_path: {}".format(meta_path))

    # 가능하면 캐쉬 이용
    if os.path.isdir(cache_dir) and os.path.isfile(meta_path):
        # 메타 데이터 읽어옴
        meta = ConfigParser()
        meta.read(meta_path)
        metad = meta['default']
        # 캐쉬 수명 체크
        if 'created' in metad:
            created = parse(metad['created'])
            dif = datetime.now() - created
            days, hours, mins = dif.days, dif.seconds // 3600, dif.seconds // 60
            cache_valid_hour = int(pcfg['cache_valid_hour'])
            valid_life = dif.seconds < cache_valid_hour * 3600
            info("Cache created {} days {} hours {} minutess ago: {}".format(days, hours, mins, valid_life))
        else:
            valid_life = False

        # 설정 변화 체크
        meta_cfg_hash = metad['config_hash'] if 'config_hash' in metad else None
        valid_cfg = meta_cfg_hash == cfg_hash
        if not valid_cfg:
            info("Config hash mismatch: {}(old) != {}(new)".format(meta_cfg_hash, cfg_hash))
        else:
            info("Config hash match: {}".format(cfg_hash))

        # 데이터 스크립트 체크
        meta_dscript_hash = metad['dscript_hash'] if 'dscript_hash' in metad else None
        valid_dscript = meta_dscript_hash == dscript_hash
        if not valid_dscript:
            info("Data script hash mismatch: {}(old) != {}(new)".format(meta_dscript_hash, dscript_hash))
        else:
            info("Data script hash match: {}".format(dscript_hash))

        # 캐쉬 이용 가능하면
        if valid_life and valid_cfg and valid_dscript:
            # 유효한 캐쉬를 복사해 사용하고
            warning("Use cache data.")
            try:
                copy_cache(pbt_dir, cache_dir)
            except Exception as e:
                error("Copy error: {}".format(str(e)))
            # 종료
            # time.sleep(5)  # 미리보기 안되는 이슈에 도움?
            sys.exit()
        else:
            # 오래된 캐쉬 지움
            del_cache(pro_name)
    else:
        info("No valid cache. Import now.")

    # 아니면 새로 가져옴
    _import_profile_data(cfg, pcfg, dscfg, cache_dir, meta_path, cfg_hash, dscript_hash)


def save_metadata(meta_path, cfg_hash, dscript_hash):
    warning("save_metadata")
    meta = ConfigParser()
    metad = {}

    created = datetime.now()
    metad['created'] = created.strftime('%Y-%m-%d %H:%M:%S')
    metad['config_hash'] = cfg_hash
    metad['dscript_hash'] = dscript_hash

    meta['default'] = metad
    with open(meta_path, 'w') as fp:
        meta.write(fp)


def _import_profile_data(cfg, pcfg, dscfg, cache_dir, meta_path, cfg_hash, dscript_hash):
    """설정대로 프로파일 데이터 가져오기.
    
    - Power BI에서 불려짐
    - 유효한 캐쉬가 있으면 이용
    - 아니면 새로 가져옴

    Args:
        cfg (ConfigParser): 설정
        pcfg: 프로파일 설정
        dscfg: 데이터 스크립트 설정
        cache_dir: 프로파일 용 캐쉬 디렉토리
        meta_path: 프로파일 용 메티파일 경로
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

    sect = pcfg
    ttype = sect['ttype']
    if ttype == 'rel':
        before = int(sect['before'])
        offset = int(sect['offset'])
    else:
        start = parse(sect['start']).date()
        end = parse(sect['end']).date()

    # 모든 대상 DB의 테이블에 대해
    for key in pcfg.keys():
        if not key.startswith('db_'):
            continue 
        db = key[3:]
        tables = eval(pcfg[key])
        for tbl in tables:
            cols = None
            if type(tbl) is not str:
                tbl, cols = tbl
            # 쿼리 준비
            no_part = no_part_table(cursor, db, tbl)
            if ttype == 'rel':
                cnt = get_query_rows_rel(cursor, db, tbl, before, offset, dscfg, no_part)
                query = make_query_rel(db, tbl, before, offset, dscfg, "default", no_part, cols)
            else:
                cnt = get_query_rows_abs(cursor, db, tbl, start, end, dscfg, no_part)
                query = make_query_abs(db, tbl, start, end, dscfg, "default", no_part, cols)

            # 가져옴
            warning("Import '{}' ({:,} rows) from '{}'".format(tbl, cnt, db))
            info("  query: {}".format(query))
            try:
                df = pd.read_sql(query, conn)
            except Exception:
                win32api.MessageBox(0, "다음 쿼리에 에러가 있습니다:\n" + query, "쿼리 에러")
                sys.exit(-1)

            csv_file = "{}.{}.csv".format(db, tbl)
            spath = os.path.join(cache_dir, csv_file)
            dpath = os.path.join(pbt_dir, csv_file)            

            # 저장
            info("Write CSV to cache: {}".format(spath))
            df.to_csv(spath, index=False, encoding='utf-8-sig')
            info("Copy from {} to {}\n".format(spath, dpath))
            copyfile(spath, dpath)

    # 메타정보 기록
    save_metadata(meta_path, cfg_hash, dscript_hash)
    critical("======= Import successful =======")


# 설정 읽기
cfg, cfg_hash = load_config()
# 데이터 임포트 후 종료
check_import_data(cfg, cfg_hash)
