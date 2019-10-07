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
from datetime import date
from configparser import ConfigParser
from datetime import datetime, timedelta
from copy import deepcopy
from shutil import rmtree, copyfile
from pathlib import Path
import logging
import hashlib

import pandas as pd
from dateutil.parser import parse
from pyathena import connect

LOG_FILE = 'log.txt'
PBTDIR_PTRN = r"os.chdir\((?:u')?(.*)(?:')\)"
CFG_FILE = 'config.txt'
WIN_WIDTH = 370
WIN_HEIGHT = 610
RESULT_VALID_TIME = 60  # 이전 결과를 재활용할 시간 (Power BI에서 파이썬을 계속 띄우는 문제 때문)
WARN_ROWS = 1000000  # 이 행수 이상 경고

conn = cursor = databases = org_cfg = cfg_hash = None
pbt_dir = None
profile = 'profile.default'
selected_tables = {}
first_sel_db = first_sel_db_idx = None


# 로그파일 초기화
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

# Power BI에서 실행 여부 \
POWER_BI = len(sys.argv) > 1 and sys.argv[1].lower() == 'pythonscriptwrapper.py'
start_mode = 'Setting GUI' if not POWER_BI else 'Power BI'
critical("======== PyPBAC Start ({}) ========".format(start_mode))
warning("Start up argv: {}".format(sys.argv))
warning("Project Dir: {}".format(pypbac_dir))


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
    global org_cfg, cfg_hash
    warning("Load config: {}".format(cfg_path))
    cfg = ConfigParser()
    cfg.read(cfg_path)
    org_cfg = deepcopy(cfg)
    cfg_hash = get_file_hash(cfg_path)

    return cfg


def del_cache():
    warning("Remove old profile cache dir: {}".format(pcache_dir))
    rmtree(pcache_dir)
    os.mkdir(pcache_dir)


def check_import_data(cfg):
    """Power BI 용 데이터 가져오기.
    
    - 유효한 로컬 캐쉬가 았으면 그것을 이용
    - 아니면 새로 가져와 로컬 캐쉬에 저장
    """
    global pbt_dir

    # Python 데이터 소스용 임시 디렉토리 얻음
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
        warning("Power BI Temp Dir: {}".format(pbt_dir))

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

    # 아니면 새로 가져옴
    _import_data(cfg)


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


def get_query_rows_rel(db, table, before, offset):
    query = make_query_rel(db, table, before, offset, True)
    rows = cursor.execute(query).fetchone()
    return rows[0]


def get_query_rows_abs(db, table, start_dt, end_dt):
    query = make_query_abs(db, table, start_dt, end_dt, True)
    rows = cursor.execute(query).fetchone()
    return rows[0]


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
    global conn, cursor
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
                cnt = get_query_rows_rel(db, tbl, before, offset)
                query = make_query_rel(db, tbl, before, offset, False)

            else:
                cnt = get_query_rows_abs(db, tbl, start, end)
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
            df.to_csv(spath, index=False)
            info("Copy from {} to {}\n".format(spath, dpath))
            copyfile(spath, dpath)

    # 메타정보 기록
    save_metadata()
    critical("======= Import successful =======")


# Power BI 데이터소스에서 구동한 경우 
if POWER_BI:
    # 설정 읽기
    cfg = load_config()
    # 데이터 임포트 후 종료
    check_import_data(cfg)
    sys.exit()


from tkinter import *
from tkinter import ttk
from tkinter import messagebox

from datepicker import Datepicker
import tkSimpleDialog


cfg = ConfigParser()


def save_config(cfg):
    global org_cfg

    info("Save config file to {}".format(cfg_path))
    with open(cfg_path, 'w') as cfgfile:
        cfg.write(cfgfile)
    org_cfg = deepcopy(cfg)


class AWSConfigDlg(tkSimpleDialog.Dialog):

    def body(self, master):

        self.need_connect = False

        Label(master, text="Access Key :").grid(row=0)
        Label(master, text="Secret Key :").grid(row=1)
        Label(master, text="S3 Stage Dir :").grid(row=2)

        self.acval = StringVar()
        self.ackey = Entry(master, textvariable=self.acval, width=30)
        self.scval = StringVar()
        self.sckey = Entry(master, textvariable=self.scval, width=30)
        self.sckey.configure(show="*")
        self.s3val = StringVar()
        self.s3dir = Entry(master, textvariable=self.s3val, width=30)

        try:
            self.acval.set(cfg['aws']['access_key'])
            self.scval.set(cfg['aws']['secret_key'])
            self.s3val.set(cfg['aws']['s3_stage_dir'])
        except Exception as e:
            pass

        self.ackey.grid(row=0, column=1)
        self.sckey.grid(row=1, column=1)
        self.s3dir.grid(row=2, column=1)
        return self.ackey # initial focus

    def validate(self):
        access_key = self.ackey.get()
        secret_key = self.sckey.get()
        s3_stage_dir = self.s3dir.get()

        if len(access_key) == 0:
            messagebox.showerror("Error", "Access Key를 입력해주세요.")
            self.initial_focus = self.ackey
            return 0

        if len(secret_key) == 0:
            messagebox.showerror("Error", "Secret Key를 입력해주세요.")
            self.initial_focus = self.sckey
            return 0

        if len(s3_stage_dir) == 0:
            messagebox.showerror("Error", "S3 Stage 경로를 입력해주세요.")
            self.initial_focus = self.s3dir
            return 0
        return 1

    def apply(self):
        global cfg
        cfg['aws'] = {}
        cfg['aws']['access_key'] = self.ackey.get()
        cfg['aws']['secret_key'] = self.sckey.get()
        cfg['aws']['s3_stage_dir'] = self.s3dir.get()
        self.need_connect = org_cfg != cfg
        save_config(cfg)


info("Construct GUI.")
win = Tk()
win.title("Athena 가져오기 설정")
win.geometry("{}x{}+100+100".format(WIN_WIDTH, WIN_HEIGHT))
tbl_text = None


def set_wait_cursor():
    global tbl_text
    win.config(cursor='wait')
    if tbl_text is not None:
        tbl_text.config(cursor='wait')
    win.update_idletasks()


def unset_wait_cursor():
    global tbl_text
    win.config(cursor='')
    if tbl_text is not None:
        tbl_text.config(cursor='')


def show_aws_config():
    return AWSConfigDlg(win, title="AWS 계정")


# Document Data
warning("Init document data")
ttype = StringVar()
ttype.set('rel')
lct_val = IntVar()
lct_val.set(1)
rel_bg_var = IntVar()
rel_bg_var.set(1)
rel_off_var = IntVar()
rel_off_var.set(1)
st_dp_val = ed_dp_val = None


def apply_cfg_to_doc(cfg):
    """읽은 설정을 도큐먼트에 적용."""
    global selected_tables, st_dp_val, ed_dp_val, first_sel_db

    info("apply_cfg_to_doc")
    # 대상 시간
    sect = cfg[profile]
    if 'ttype' in sect:
        ttype.set(sect['ttype'])
        
    if 'before' in sect:
        rel_bg_var.set(int(sect['before']))
    if 'offset' in sect:
        rel_off_var.set(int(sect['offset']))

    if 'start' in sect:
        st_dp_val = parse(sect['start']).date()
    if 'end' in sect:
        ed_dp_val = parse(sect['end']).date()

    # DB를 순회
    for key in cfg[profile].keys():
        if not key.startswith('db_'):
            continue

        db = key[3:]
        tables = eval(sect[key])
        if first_sel_db is None and len(tables) > 0:
            first_sel_db = db
        selected_tables[db] = tables

    if 'cache_valid_hour' in sect:
        cache_valid_hour = int(sect['cache_valid_hour'])
        lct_val.set(cache_valid_hour)


# 설정 읽기
need_aws = False
if os.path.isfile(cfg_path):
    try:
        cfg = load_config()
        apply_cfg_to_doc(cfg)
    except Exception as e:
        error(str(e))
        messagebox.showerror("에러", "설정 읽기 오류입니다.\n{} 파일 확인 후 시작해주세요.".format(CFG_FILE))
        sys.exit()

    if 'aws' not in cfg.sections():
        messagebox.showwarning("경고", "AWS 계정 설정이 없습니다. 먼저 설정 해주세요.")        
        need_aws = True
else:
    messagebox.showwarning("경고", "설정 파일이 없습니다. 먼저 AWS 계정부터 설정 해주세요.")
    need_aws = True


def get_tables(db):
    _tables = cursor.execute('show tables in {}'.format(db)).fetchall()
    return [r[0] for r in _tables]


abs_frame = LabelFrame(win, text="날자 선택")
rel_frame = LabelFrame(win, text="범위 선택")


def pack_rel_frame():
    rel_frame.pack(side=TOP, pady=(10, 10))


def pack_abs_frame():
    abs_frame.pack(side=TOP, pady=(10, 10))


def on_ttype():
    switch_absrel_frame(ttype.get())


# 날자 타입
ttype_frame = Frame(win)
rel_rbt = Radiobutton(ttype_frame, text="상대 시간", variable=ttype, value="rel", command=on_ttype)
rel_rbt.pack(side=LEFT, expand=True, padx=(20, 10))
abs_rbt = Radiobutton(ttype_frame, text="절대 시간", variable=ttype, value="abs", command=on_ttype)
abs_rbt.pack(side=LEFT, expand=True, padx=(10, 20))
ttype_frame.pack(side=TOP, pady=(20, 0))

# 상대 시간
rel_bg_etr = Entry(rel_frame, textvariable=rel_bg_var, width=5, justify=CENTER)
rel_bg_etr.pack(side=LEFT, padx=(15, 5), pady=(10, 10))
Label(rel_frame, text="일 전부터").pack(side=LEFT, pady=(10, 10))
rel_off_etr = Entry(rel_frame, textvariable=rel_off_var, width=5, justify=CENTER)
rel_off_etr.pack(side=LEFT, padx=(10, 5), pady=(10, 10))
Label(rel_frame, text="일치 데이터").pack(side=LEFT, padx=(0, 15), pady=(10, 10))
pack_rel_frame()

# 절대 시간 
dts_frame = Frame(abs_frame)
st_lbl = Label(dts_frame, justify="left", text="시작일")
st_lbl.grid(row=0, column=0, stick=W, padx=(10, 20), pady=(3, 3))
st_dp = Datepicker(dts_frame)
if st_dp_val is not None:
    st_dp.current_date = st_dp_val
st_dp.grid(row=0, column=1, padx=(10, 20), pady=(3, 3))
dts_frame.pack(side=TOP)

dte_frame = Frame(abs_frame)
ed_lbl = Label(dte_frame, justify="left", text="종료일")
ed_lbl.grid(row=0, column=0, stick=W, padx=(10, 20), pady=(3, 3))
ed_dp = Datepicker(dte_frame)
if ed_dp_val is not None:
    ed_dp.current_date = ed_dp_val
ed_dp.grid(row=0, column=1, padx=(10, 20), pady=(3, 3))
dte_frame.pack(side=TOP, pady=(7, 10))
pack_abs_frame()

# 날자 이후 UI프레임
after_dt_frame = Frame(win)
sel_frame = Frame(after_dt_frame)

def switch_absrel_frame(tval):
    after_dt_frame.pack_forget()
    if tval == 'rel':
        abs_frame.pack_forget()
        pack_rel_frame()
    else:
        rel_frame.pack_forget()        
        pack_abs_frame()
    after_dt_frame.pack(side=TOP)


# DB 선택 UI
db_frame = LabelFrame(sel_frame, text="DB 선택")
db_val = StringVar()
db_combo = ttk.Combobox(db_frame, width=20, textvariable=db_val,
                        state="readonly")
prev_db = None


def on_db_sel(eobj):
    global prev_db

    db = db_combo.get()
    if prev_db is not None:
        update_sel_tables(prev_db)
    prev_db = db

    set_wait_cursor()
    disable_controls()
    def _db_set():
        db = db_combo.get()
        info("Read tables from '{}'.".format(db))
        fill_tables(db)
        enable_controls()
        unset_wait_cursor()

    win.after(10, _db_set)


db_combo.bind("<<ComboboxSelected>>", on_db_sel)
db_combo.pack(padx=(10, 10), pady=(10,))
db_frame.pack(side=TOP)


def fill_tables(db):
    global tbl_ckbs, tbl_cvs
    info("fill_tables for {}".format(db))

    tables = get_tables(db)
    # 이전에 선택된 테이블들 
    if db in selected_tables:
        selected = selected_tables[db]
        info("  selected: {}".format(selected))
    else:
        selected = []

    num_tbl = len(tables)
    for ckbs in tbl_ckbs:
        # ckbs.pack_forget()
        ckbs.destroy()
    tbl_ckbs = []
    tbl_cvs = []
    tbl_text.configure(state='normal')
    tbl_text.delete('1.0', END)

    for i, tbl in enumerate(tables):
        cv = IntVar()
        if tbl in selected:
            cv.set(1)
        ckb = Checkbutton(tbl_text, text=tbl, variable=cv)
        tbl_text.window_create("end", window=ckb)
        tbl_text.insert("end", "\n")
        tbl_ckbs.append(ckb)
        tbl_cvs.append(cv)

    tbl_text.configure(state='disabled')
    tbl_frame.update()
    return tbl_ckbs


# Table 선택 UI
tbl_frame = LabelFrame(sel_frame, text="테이블 선택")
tbl_text = Text(tbl_frame, wrap="none", height=15, background=tbl_frame.cget('bg'), bd=0)
tbl_text.grid_propagate(False)
tbl_vsb = Scrollbar(tbl_frame, orient="vertical", command=tbl_text.yview)
tbl_text.configure(yscrollcommand=tbl_vsb.set)
tbl_vsb.pack(side="right", fill="y")
tbl_text.pack(fill='both', expand=True, padx=(15, 15), pady=(5, 20))
tbl_text.configure(state='disabled')

tbl_frame.pack(side=TOP, fill=None, expand=False, padx=(20, 20), pady=(10, 10))
sel_frame.pack(side=TOP)
tbl_ckbs = []
tbl_cvs = []

def on_all():
    """테이블 전체 선택."""
    for cv in tbl_cvs:
        cv.set(1)


def on_none():
    """테이블 전체 지우기."""
    for cv in tbl_cvs:
        cv.set(0)


tbb_frame = Frame(after_dt_frame)
all_btn = ttk.Button(tbb_frame, text="전체 선택", width=8, command=on_all)
all_btn.pack(side=LEFT, expand=YES)
none_btn = ttk.Button(tbb_frame, text="전체 취소", width=8, command=on_none)
none_btn.pack(side=LEFT, expand=YES)
tbb_frame.pack(fill=BOTH, expand=YES)

switch_absrel_frame(ttype.get())


def update_sel_tables(db):
    """이전 DB의 선택된 테이블 기억."""
    global selected_tables
    info("update_sel_tables for {}".format(db))
    selected = []
    for i, cv in enumerate(tbl_cvs):
        if cv.get() == 1:
            selected.append(tbl_ckbs[i]['text'])
    selected_tables[db] = selected


def validate_cfg():
    """설정 값 확인."""
    _cfg = ConfigParser()
    _cfg[profile] = {}  # 기본 프로파일

    if ttype.get() == 'rel':
        # 상대 시간
        before = rel_bg_var.get()
        offset = rel_off_var.get()
        if before <= 0:
            messagebox.showerror("Error", "몇 일 전부터 시작할지 양의 정수로 지정해 주세요.")
            return
        elif offset <= 0:
            messagebox.showerror("Error", "몇 일치 데이터를 가져올지 양의 정수로 지정해 주세요.")
            return
        _cfg[profile]['ttype'] = 'rel'
        _cfg[profile]['before'] = str(before)
        _cfg[profile]['offset'] = str(offset)
    else:
        # 절대 시간
        start = st_dp.get()
        end = ed_dp.get()
        db_name = db_combo.get()

        if len(start) == 0:
            messagebox.showerror("Error", "시작일을 선택해주세요.")
            return
        elif len(end) == 0:
            messagebox.showerror("Error", "종료일을 선택해주세요.")
            return
        elif len(db_name) == 0:
            messagebox.showerror("Error", "선택된 DB가 없습니다.")
            return

        start = parse(start).date()
        end = parse(end).date()
        if start > end:
            messagebox.showerror("Error", "종료일이 시작일보다 빠릅니다.")
            return
        _cfg[profile]['ttype'] = 'abs'
        _cfg[profile]['start'] = str(start)
        _cfg[profile]['end'] = str(end)


    # 가져올 행수를 체크
    tbl_cnt = 0
    for db, tbls in selected_tables.items():
        for tbl in tbls:
            tbl_cnt += 1
            if ttype.get() == 'rel':
                cnt = get_query_rows_rel(db, tbl, before, offset)
            else:
                cnt = get_query_rows_abs(db, tbl, start, end)
            if cnt > WARN_ROWS:
                rv = messagebox.askquestion("경고", "{} DB의 {} 테이블의 행수가 매우 큽니다 ({:,} 행)."
                                            "\n정말 가져오겠습니까?".format(db, tbl, cnt))
                if rv != 'yes':
                    return

    if tbl_cnt == 0:
        messagebox.showerror("Error", "선택된 테이블이 없습니다.")
        return

    # 선택된 테이블 기억
    for db in selected_tables.keys():
        tables = selected_tables[db]
        if len(tables) > 0:
            _cfg[profile]["db_" + db] = str(tables)

    # 캐쉬 유효 시간
    cache_valid_hour = lct_val.get()
    if cache_valid_hour <= 0:
        messagebox.showerror("Error", "캐쉬 수명은 최소 0보다 커야 합니다.")
        return
    _cfg[profile]['cache_valid_hour'] = str(lct_val.get())

    return _cfg


def on_save():
    """설정 저장"""
    global cfg
    disable_controls()
    set_wait_cursor()

    db = db_combo.get()
    update_sel_tables(db)

    # 설정 검증
    _cfg = validate_cfg()
    if _cfg is None:
        return
    if 'aws' in cfg:
        _cfg['aws'] = cfg['aws']
    save_config(_cfg)
    win.destroy()


def on_aws():
    d = show_aws_config()
    if d.need_connect:
        try_connect()


def on_del_cache():
    del_cache()
    messagebox.showinfo("Info", "로컬 캐쉬를 제거했습니다.")


confirm_frame = Frame(after_dt_frame)

lct_frame = Frame(confirm_frame)
Label(lct_frame, text="로컬 캐쉬 유효 시간:").pack(side=LEFT)
lct_etr = Entry(lct_frame, textvariable=lct_val, width=3, justify="center")
lct_etr.pack(side=LEFT, padx=(5, 2))
Label(lct_frame, text="시간").pack(side=LEFT)
lct_frame.pack(side=TOP, pady=(20, 0))

aws_btn = ttk.Button(confirm_frame, text="AWS 계정", width=10, command=on_aws)
aws_btn.pack(side=LEFT, expand=YES, padx=(20, 7), pady=(20, 20))

flush_btn = ttk.Button(confirm_frame, text="로컬 캐쉬 제거", width=15, command=on_del_cache)
flush_btn.pack(side=LEFT, expand=YES, padx=(7, 7), pady=(20, 20))

save_btn = ttk.Button(confirm_frame, text="저장 후 종료", width=15,
                        command=on_save)
save_btn.pack(side=LEFT, expand=YES, padx=(7, 20), pady=(20, 20))
confirm_frame.pack(fill=BOTH, expand=YES)


DISABLE_CTRLS = [st_dp, ed_dp, all_btn, none_btn, lct_etr, aws_btn, flush_btn, db_combo,
                 save_btn, rel_rbt, abs_rbt, rel_bg_etr, rel_off_etr, st_dp, ed_dp]


def disable_controls():
    for ctl in DISABLE_CTRLS:
        ctl['state'] = 'disabled'
    tbl_text['state'] = 'disabled'
    for ckb in tbl_ckbs:
        ckb['state'] = 'disabled'
    win.update_idletasks()


def enable_controls():
    for ctl in DISABLE_CTRLS:
        ctl['state'] = 'normal'
    for ckb in tbl_ckbs:
        ckb['state'] = 'normal'
    db_combo['state'] = 'readonly'


def try_connect():
    # 설정 정보를 이용해 접속
    set_wait_cursor()
    disable_controls()

    def _connect(cfg):
        global conn, cursor, databases
        try:
            info("Connect.")
            conn = connect(aws_access_key_id=cfg['aws']['access_key'],
                aws_secret_access_key=cfg['aws']['secret_key'],
                s3_staging_dir=cfg['aws']['s3_stage_dir'],
                region_name='ap-northeast-2')

            cursor = conn.cursor()
            databases = [rv[0] for rv in cursor.execute('show databases').fetchall()]

        except Exception as e:
            error("=== DB Error Message ===")
            error(str(e))
            messagebox.showerror("에러", "DB 접속 에러. AWS 설정을 확인해 주세요.")
            aws_btn['state'] = 'normal'
        else:
            warning("Connect success.")
            enable_controls()
            db_combo['values'] = databases
        finally:
            unset_wait_cursor()

    win.after(100, lambda: _connect(cfg))

    while databases is None :
        win.update()
        time.sleep(1)


def find_first_db_idx():
    for idx, db in enumerate(databases):
        if first_sel_db == db:
            return idx
    return 0

if 'win' not in sys.platform:
    style = ttk.Style()
    style.theme_use('clam')

if not need_aws:
    try_connect()
    first_sel_db = db_combo.current(find_first_db_idx())
    on_db_sel(None)
else:
    disable_controls()
    aws_btn['state'] = 'normal'

win.mainloop()

