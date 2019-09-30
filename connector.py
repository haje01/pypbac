import os
import sys
from datetime import date
from configparser import ConfigParser
from dateutil.parser import parse
from copy import deepcopy

from pyathena import connect
import pandas as pd

from tkinter import *
from tkinter import ttk
from tkinter import messagebox

from datepicker import Datepicker
from vscroll import VerticalScrolledFrame
import tkSimpleDialog

CFG_NAME = 'config.ini'
WIN_WIDTH = 370
WIN_HEIGHT = 570
WARN_ROWS = 1000000  # 이 행수 이상 경고
conn = cursor = databases = org_cfg = None

cfg = ConfigParser()

def get_cfg_path():
    """설정파일 경로."""
    adir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(adir, CFG_NAME)


def save_config():
    """AWS Access/Secret 키 저장"""
    global org_cfg
    print("Save config file.")
    path = get_cfg_path()
    with open(path, 'w') as cfgfile:
        cfg.write(cfgfile)


class ConfigDlg(tkSimpleDialog.Dialog):

    def body(self, master):

        self.need_restart = False

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
            self.initial_focus = self.sckey
            return 0

        if len(secret_key) == 0:
            messagebox.showerror("Error", "Secret Key를 입력해주세요.")
            self.initial_focus = self.sckey
            return 0

        if len(s3_stage_dir) == 0:
            messagebox.showerror("Error", "S3 Stage 경로를 입력해주세요.")
            self.initial_focus = self.sckey
            return 0

        return 1

    def apply(self):
        cfg['aws'] = {}
        cfg['aws']['access_key'] = self.ackey.get()
        cfg['aws']['secret_key'] = self.sckey.get()
        cfg['aws']['s3_stage_dir'] = self.s3dir.get()
        need_restart = org_cfg is not None and org_cfg != cfg
        if org_cfg is None or need_restart:
            save_config()
            if need_restart:
                messagebox.showwarning("경고", "설정이 변경되었습니다. 재시작이 필요합니다.")
                self.need_restart = True


win = Tk()
win.title("Athena 데이터 임포터")
win.geometry("{}x{}+100+100".format(WIN_WIDTH, WIN_HEIGHT))


def show_config():
    return ConfigDlg(win, title="설정")


cfg_path = get_cfg_path()
if os.path.isfile(cfg_path):
    try:
        cfg.read(cfg_path)
        org_cfg = deepcopy(cfg)
    except Exception as e:
        messagebox.showerror("에러", "잘못된 설정파일입니다.\n프로그램 종료후 다시 시작해주세요.")
        os.unlink(cfg_path)
        win.destroy()
else:
    messagebox.showwarning("경고", "설정파일이 없습니다. 먼저 설정을 해주세요.")
    show_config()


# 설정 정보를 이용해 접속
conn = connect(aws_access_key_id=cfg['aws']['access_key'],
                aws_secret_access_key=cfg['aws']['secret_key'],
                s3_staging_dir=cfg['aws']['s3_stage_dir'],
                region_name='ap-northeast-2')

try:
    cursor = conn.cursor()
    databases = cursor.execute('show databases').fetchall()
except Exception as e:
    messagebox.showerror("에러", "DB 접속 에러 :\n{}".format(e))


def get_tables(db):
    return cursor.execute('show tables in {}'.format(db)).fetchall()


def on_cfg():
    d = show_config()
    if d.need_restart:
        win.destroy()


# 대상 날자
dt_frame = LabelFrame(win, text="날자 선택")
dts_frame = Frame(dt_frame)
st_lbl = Label(dts_frame, justify="left", text="시작일")
st_lbl.grid(row=0, column=0, stick=W, padx=(10, 20), pady=(3, 3))
st_dp = Datepicker(dts_frame)
st_dp.grid(row=0, column=1, padx=(10, 20), pady=(3, 3))
dts_frame.pack(side=TOP)

dte_frame = Frame(dt_frame)
ed_lbl = Label(dte_frame, justify="left", text="종료일")
ed_lbl.grid(row=0, column=0, stick=W, padx=(10, 20), pady=(3, 3))
ed_dp = Datepicker(dte_frame)
ed_dp.grid(row=0, column=1, padx=(10, 20), pady=(3, 3))
dte_frame.pack(side=TOP, pady=(7, 10))
dt_frame.pack(side=TOP, pady=(20, 10))


sel_frame = Frame(win)

# DB 선택 UI
db_frame = LabelFrame(sel_frame, text="DB 선택")
db_combo = ttk.Combobox(db_frame, width=20, textvariable=StringVar(),
                        state="readonly")


def on_db_sel(eobj):
    db = db_combo.get()
    tables = get_tables(db)
    fill_tables(tables)


db_combo.bind("<<ComboboxSelected>>", on_db_sel)
db_combo['values'] = databases
db_combo.pack(padx=(10, 10), pady=(10,))
db_frame.grid(row=1, column=1, padx=(20, 20), pady=(10, 10))

vtbl_frame = None


def fill_tables(tables):
    global tbl_ckbs, tbl_cvs
    num_tbl = len(tables)
    for ckbs in tbl_ckbs:
        ckbs.pack_forget()
        ckbs.destroy()
    tbl_ckbs = []
    tbl_cvs = []
    for i, tbl in enumerate(tables):
        cv = IntVar()
        ckb = Checkbutton(vtbl_frame.interior, text=tbl, variable=cv)
        if i == 0:
            pady=(10, 3)
        elif i == num_tbl-1:
            pady=(3, 15)
        else:
            pady=(3, 3)
        ckb.grid(row=i, stick=W, padx=(10, 20), pady=pady)
        tbl_ckbs.append(ckb)
        tbl_cvs.append(cv)
    if len(tables) > 0:
        vtbl_frame.pack()
    tbl_frame.update()
    return tbl_ckbs


# Table 선택 UI
tbl_frame = LabelFrame(sel_frame, text="테이블 선택")
vtbl_frame = VerticalScrolledFrame(tbl_frame)
# vtbl_frame.pack()
# vtbl_frame = fill_tables(databases[0], tbl_frame)
tbl_frame.grid(row=2, column=1, padx=(20, 20), pady=(5, 5))
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


tbb_frame = Frame(win)
all_btn = ttk.Button(tbb_frame, text="전체 선택", width=7, command=on_all)
all_btn.pack(side=LEFT, expand=YES)
none_btn = ttk.Button(tbb_frame, text="전체 취소", width=7, command=on_none)
none_btn.pack(side=LEFT, expand=YES)
tbb_frame.pack(fill=BOTH, expand=YES)


def get_sel_tables():
    """현재 선택된 테이블 리스트를 반환."""
    selected = []
    for i, cv in enumerate(tbl_cvs):
        if cv.get() == 1:
            selected.append(tbl_ckbs[i]['text'])
    return selected


def validate():
    """설정 값 확인."""
    start_dt = st_dp.get()
    end_dt = ed_dp.get()
    db_name = db_combo.get()
    selected = get_sel_tables()

    if len(start_dt) == 0:
        messagebox.showerror("Error", "시작일을 선택해주세요.")
        return
    elif len(end_dt) == 0:
        messagebox.showerror("Error", "종료일을 선택해주세요.")
        return
    elif len(db_name) == 0:
        messagebox.showerror("Error", "선택된 DB가 없습니다.")
        return
    elif len(selected) == 0:
        messagebox.showerror("Error", "선택된 테이블이 없습니다.")
        return

    start_dt = parse(start_dt).date()
    end_dt = parse(end_dt).date()
    if start_dt > end_dt:
        messagebox.showerror("Error", "종료일이 시작일보다 빠릅니다.")
        return

    return start_dt, end_dt, db_name, selected


def make_query(start_dt, end_dt, db, table, count):
    """질의를 만듦.

    Args:
        start_dt (date): 시작일
        end_dt (date): 종료일
        db (str): DB명
        table (str): table명
        count: 행수 구하기 여부
    """
    assert type(start_dt) is date and type(end_dt) is date
    start_dt = start_dt.strftime('%Y%m%d')
    end_dt = end_dt.strftime('%Y%m%d')

    if not count:
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


def get_query_rows(start_dt, end_dt, db, table,):
    query = make_query(start_dt, end_dt, db, table, True)
    rows = cursor.execute(query).fetchone()
    return rows[0
                            ]


def on_import():
    """가져오기."""
    # 설정 검증
    rv = validate()
    if rv is None:
        return
    start_dt, end_dt, db, tables = rv

    # 먼저 가져올 행수를 체크
    rows = {}
    for tbl in tables:
        cnt = get_query_rows(start_dt, end_dt, db, tbl)
        if cnt > WARN_ROWS:
            rv = messagebox.askquestion("경고", "가져올 행수가 매우 큽니다 ({:,} 행)."
                                        "\n정말 가져오겠습니까?".format(cnt))
            if rv != 'yes':
                return
        rows[tbl] = cnt

    for tbl in tables:
        cnt = rows[tbl]
        print("\nImport '{}' ({:,} rows) from '{}'".format(tbl, cnt, db))
        query = make_query(start_dt, end_dt, db, tbl, False)
        df = pd.read_sql(query, conn)
        print(df.head())
        globals()[tbl] = df

    win.destroy()


confirm_frame = Frame(win)
cfg_btn = ttk.Button(confirm_frame, text="설정", width=5, command=on_cfg)
cfg_btn.pack(side=LEFT, expand=YES, padx=(20, 10))

import_btn = ttk.Button(confirm_frame, text="가져오기", width=27,
                        command=on_import)
import_btn.pack(side=LEFT, expand=YES, padx=(10, 20))
confirm_frame.pack(fill=BOTH, expand=YES)


if 'win' not in sys.platform:
    style = ttk.Style()
    style.theme_use('clam')


db_combo.current(0)
on_db_sel(None)


win.mainloop()

